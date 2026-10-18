import pytest
from fastapi.testclient import TestClient

from memory import UserMemory

pytestmark = pytest.mark.usefixtures("clean_memory")

PARIS = {"ipAddress": "1.1.1.1", "latitude": 48.8566, "longitude": 2.3522}
VERSAILLES = {"ipAddress": "2.2.2.2", "latitude": 48.8049, "longitude": 2.1204}
TOKYO = {"ipAddress": "3.3.3.3", "latitude": 35.6762, "longitude": 139.6503}


@pytest.fixture
def client(service_b):
    return TestClient(service_b.app)


def add(client, record):
    return client.post("/ips", json=record).json()


def test_add_ip(client):
    body = add(client, PARIS)

    assert body["success"] is True and body["data_length"] == 1
    assert client.get("/ips").json() == {body["new_id"]: PARIS}
    assert client.get("/ips/addresses").json() == ["1.1.1.1"]


def test_add_duplicate_ip(client):
    add(client, PARIS)
    assert add(client, PARIS) == {"success": False, "message": "IP address already exists"}


@pytest.mark.parametrize("missing", ["ipAddress", "latitude", "longitude"])
def test_add_ip_with_missing_field_is_a_400(client, missing):
    response = client.post("/ips", json={**PARIS, missing: None})
    assert response.status_code == 400
    assert missing in response.json()["detail"]


def test_delete(client):
    new_id = add(client, PARIS)["new_id"]

    assert client.delete(f"/ips/{new_id}").json() == {"success": True, "data_length": 0}
    assert client.get("/ips").json() == {}


def test_delete_unknown_id(client):
    assert client.delete("/ips/missing").json()["success"] is False


def test_generate_geo_clusters(client):
    europe = [PARIS, VERSAILLES, {"ipAddress": "4.4.4.4", "latitude": 50.8503, "longitude": 4.3517},
              {"ipAddress": "5.5.5.5", "latitude": 51.5074, "longitude": -0.1278}]
    japan = [TOKYO, {"ipAddress": "6.6.6.6", "latitude": 34.6937, "longitude": 135.5023}]
    for record in europe + japan:
        add(client, record)

    clusters = client.get("/clusters").json()
    assert sorted(len(entry) - 2 for entry in clusters.values()) == [2, 4]     # minus the 2 coordinate entries


# --- users ---

ALICE = {"email": "alice@example.com", "password": None, "ip_address": "1.2.3.4"}   # shaped like a Kafka event


def test_add_new_user(client):
    response = client.post("/users", json=ALICE)

    assert response.status_code == 200
    assert response.json() == {"success": True, "message": "User added successfully"}
    assert "alice@example.com" in UserMemory.users


def test_existing_user_is_a_normal_answer(client):
    """An existing user is the signin case: still 200, nothing new stored."""
    client.post("/users", json=ALICE)
    response = client.post("/users", json={**ALICE, "ip_address": "5.6.7.8"})

    assert response.status_code == 200
    assert response.json() == {"success": True, "message": "User already exists"}
    assert len(UserMemory.users) == 1


def test_user_with_password(client):
    assert client.post("/users", json={**ALICE, "password": "Secret#123"}).status_code == 200


@pytest.mark.parametrize("body", [
    {"ip_address": "1.2.3.4"},                       # no email
    {"email": "alice@example.com"},                  # no ip
    {**ALICE, "email": "not-an-email"},
    {**ALICE, "ip_address": "999.1.1.1"},
    {},
])
def test_invalid_user_is_rejected_and_not_stored(client, body):
    assert client.post("/users", json=body).status_code == 422
    assert UserMemory.users == {}


def test_users_and_ips_do_not_mix(client):
    client.post("/users", json=ALICE)
    assert client.get("/ips").json() == {}
