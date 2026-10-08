import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.usefixtures("clean_memory")

PARIS = {"ipAddress": "1.1.1.1", "latitude": 48.8566, "longitude": 2.3522}
VERSAILLES = {"ipAddress": "2.2.2.2", "latitude": 48.8049, "longitude": 2.1204}
TOKYO = {"ipAddress": "3.3.3.3", "latitude": 35.6762, "longitude": 139.6503}


@pytest.fixture
def client(service_b):
    return TestClient(service_b.app)


def add(client, record):
    return client.post("/AddIp", json=record).json()


def test_add_ip(client):
    body = add(client, PARIS)

    assert body["success"] is True and body["data_length"] == 1
    assert client.get("/getAll").json() == {body["new_id"]: PARIS}
    assert client.get("/getAllIPs").json() == ["1.1.1.1"]


def test_add_duplicate_ip(client):
    add(client, PARIS)
    assert add(client, PARIS) == {"success": False, "message": "IP address already exists"}


@pytest.mark.parametrize("missing", ["ipAddress", "latitude", "longitude"])
def test_add_ip_with_missing_field_is_a_400(client, missing):
    response = client.post("/AddIp", json={**PARIS, missing: None})
    assert response.status_code == 400
    assert missing in response.json()["detail"]


def test_delete(client):
    new_id = add(client, PARIS)["new_id"]

    assert client.delete(f"/delete/{new_id}").json() == {"success": True, "data_length": 0}
    assert client.get("/getAll").json() == {}


def test_delete_unknown_id(client):
    assert client.delete("/delete/missing").json()["success"] is False


def test_generate_geo_clusters(client):
    europe = [PARIS, VERSAILLES, {"ipAddress": "4.4.4.4", "latitude": 50.8503, "longitude": 4.3517},
              {"ipAddress": "5.5.5.5", "latitude": 51.5074, "longitude": -0.1278}]
    japan = [TOKYO, {"ipAddress": "6.6.6.6", "latitude": 34.6937, "longitude": 135.5023}]
    for record in europe + japan:
        add(client, record)

    clusters = client.get("/generate-geo-clusters").json()
    assert sorted(len(entry) - 2 for entry in clusters.values()) == [2, 4]     # minus the 2 coordinate entries
