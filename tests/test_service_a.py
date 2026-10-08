import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient


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
    assert calls == [("GET", "http://svc-b-cont:8080/getAll")]


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
    assert calls == [("DELETE", "http://svc-b-cont:8080/delete/abc123")]
