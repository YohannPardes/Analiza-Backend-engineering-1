import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from kafka.errors import KafkaTimeoutError


@pytest.fixture
def client(service_a):
    return TestClient(service_a.app)


@pytest.fixture
def calls(service_a, monkeypatch):
    """Replace calls to ServiceB/ServiceC: answers per IP, records every URL requested."""
    received = []

    async def fake_make_request(url, timeout, service_name, method="GET", json_data=None):
        received.append((method, url))
        if url.endswith("/resolve-ip/6.6.6.6"):
            raise HTTPException(status_code=503, detail="All geo providers unavailable")
        if url.endswith("/resolve-ip/7.7.7.7"):
            return {"success": False, "message": "IP address already exists"}
        return {"success": True}

    monkeypatch.setattr(service_a.connector, "make_request", fake_make_request)
    return received


def test_get_all_is_forwarded_to_service_b(client, calls):
    assert client.get("/").json() == {"success": True}
    assert calls == [("GET", "http://svc-b-cont:8080/ips")]


def test_resolve_ip_list_success(client, calls):
    body = client.post("/resolve-ip-list", json=["8.8.8.8", "1.1.1.1"]).json()

    assert body == {"success": True, "failed_ip_count": 0, "failed_ips": []}
    assert calls == [("GET", "http://svc-c-cont:8080/resolve-ip/8.8.8.8"),
                     ("GET", "http://svc-c-cont:8080/resolve-ip/1.1.1.1")]


def test_blanks_and_duplicates_are_dropped(client, calls):
    client.post("/resolve-ip-list", json=["8.8.8.8", " 8.8.8.8 ", "", "  "])
    assert len(calls) == 1


def test_failures_are_reported_per_ip(client, calls):
    body = client.post("/resolve-ip-list", json=["8.8.8.8", "6.6.6.6", "7.7.7.7"]).json()

    assert body["success"] is False
    assert body["failed_ip_count"] == 2
    assert body["failed_ips"] == [["6.6.6.6", "All geo providers unavailable"],
                                  ["7.7.7.7", "IP address already exists"]]


def test_delete_is_forwarded_to_service_b(client, calls):
    client.get("/delete/abc123")
    assert calls == [("DELETE", "http://svc-b-cont:8080/ips/abc123")]


# --- sign-in (runs the lifespan with a fake Kafka producer) ---

SIGN_IN = {"email": "a@b.com", "password": "Secret#123", "ip_address": "1.2.3.4"}
RECEIVED = {"message": "Your request was received."}


class FakeProducer:
    def __init__(self):
        self.sent, self.error, self.closed = [], None, False

    def send(self, topic, value):
        if self.error: raise self.error
        self.sent.append((topic, value))

    def close(self):
        self.closed = True


@pytest.fixture
def producer(service_a, monkeypatch):
    fake = FakeProducer()
    monkeypatch.setattr(service_a, "get_producer", lambda: fake)
    monkeypatch.setenv("KAFKA_TOPIC", "user-gateway")
    return fake


@pytest.fixture
def app_client(service_a, producer):
    with TestClient(service_a.app) as client:       # "with" runs startup and shutdown
        yield client


def test_sign_in_publishes_an_event(app_client, producer):
    response = app_client.post("/sign-in", json=SIGN_IN)

    assert response.status_code == 200 and response.json() == RECEIVED
    assert producer.sent == [("user-gateway", SIGN_IN)]


def test_sign_in_without_password(app_client, producer):
    assert app_client.post("/sign-in", json={"email": "a@b.com", "ip_address": "1.2.3.4"}).status_code == 200
    assert producer.sent[0][1]["password"] is None


def test_same_ip_within_a_minute_is_received_but_not_published(app_client, producer):
    app_client.post("/sign-in", json=SIGN_IN)
    response = app_client.post("/sign-in", json={**SIGN_IN, "email": "c@d.com"})

    assert response.status_code == 200 and response.json() == RECEIVED
    assert len(producer.sent) == 1


def test_different_ips_are_all_published(app_client, producer):
    for ip in ("1.1.1.1", "2.2.2.2", "3.3.3.3"):
        app_client.post("/sign-in", json={**SIGN_IN, "ip_address": ip})
    assert [event["ip_address"] for _, event in producer.sent] == ["1.1.1.1", "2.2.2.2", "3.3.3.3"]


@pytest.mark.parametrize("body", [
    {"password": "Secret#123", "ip_address": "1.2.3.4"},            # no email
    {"email": "a@b.com", "password": "Secret#123"},                 # no ip
    {**SIGN_IN, "email": "not-an-email"},
    {**SIGN_IN, "ip_address": "999.1.1.1"},
    {**SIGN_IN, "password": "short"},
    {},
])
def test_invalid_sign_in_is_rejected_and_not_published(app_client, producer, body):
    assert app_client.post("/sign-in", json=body).status_code == 422
    assert producer.sent == []


def test_invalid_request_does_not_start_the_ip_window(app_client, producer):
    app_client.post("/sign-in", json={**SIGN_IN, "email": "not-an-email"})
    app_client.post("/sign-in", json=SIGN_IN)                        # same IP, now valid
    assert len(producer.sent) == 1


def test_kafka_down_returns_503(app_client, producer):
    producer.error = KafkaTimeoutError("Failed to update metadata after 6.0 secs.")
    response = app_client.post("/sign-in", json=SIGN_IN)
    assert response.status_code == 503


def test_shutdown_closes_the_producer(service_a, producer):
    with TestClient(service_a.app):
        assert not producer.closed
    assert producer.closed


def test_startup_needs_the_topic(service_a, producer, monkeypatch):
    monkeypatch.delenv("KAFKA_TOPIC")
    with pytest.raises(KeyError, match="KAFKA_TOPIC"):
        with TestClient(service_a.app):
            pass
