import pytest
from fastapi.testclient import TestClient

from API_manager import InvalidIPError, ProviderUnavailable

RECORD = {
    "ipAddress": "24.48.0.1", "latitude": 45.511, "longitude": -73.5561,
    "countryName": "Canada", "cityName": "Montreal", "asn": "5769",
    "asnOrganization": "Videotron Ltee", "isProxy": False,
}


@pytest.fixture
def client(service_c):
    return TestClient(service_c.app)


@pytest.fixture
def service_b_calls(service_c, monkeypatch):
    """Replace calls to ServiceB, recording what is sent."""
    received = []

    async def fake_make_request(url, timeout, service_name, method="GET", json_data=None):
        received.append((method, url, json_data))
        return {"success": True}

    monkeypatch.setattr(service_c.connector, "make_request", fake_make_request)
    return received


def geo_lookup(service_c, monkeypatch, result=RECORD, error=None):
    """Replace the API manager lookup with a fixed record or error."""
    async def fake_get_geo_infos(ip):
        if error: raise error
        return result
    monkeypatch.setattr(service_c.api_manager, "get_geo_infos", fake_get_geo_infos)


def test_get_all_is_forwarded_to_service_b(client, service_b_calls):
    client.get("/")
    assert service_b_calls == [("GET", "http://svc-b-cont:8080/getAll", None)]


def test_resolved_ip_is_stored_in_service_b(client, service_c, monkeypatch, service_b_calls):
    geo_lookup(service_c, monkeypatch)

    assert client.get("/resolve-ip/24.48.0.1").json() == {"success": True}
    assert service_b_calls == [("POST", "http://svc-b-cont:8080/AddIp", RECORD)]


def test_malformed_ip_is_a_400(client, service_c, monkeypatch, service_b_calls):
    geo_lookup(service_c, monkeypatch)

    assert client.get("/resolve-ip/not-an-ip").status_code == 400
    assert service_b_calls == []


def test_ip_rejected_by_provider_is_a_400(client, service_c, monkeypatch, service_b_calls):
    geo_lookup(service_c, monkeypatch, error=InvalidIPError("ip-api failed: private range"))

    assert client.get("/resolve-ip/10.0.0.1").status_code == 400
    assert service_b_calls == []


def test_all_providers_unavailable_is_a_503(client, service_c, monkeypatch, service_b_calls):
    geo_lookup(service_c, monkeypatch, error=ProviderUnavailable("All geo providers unavailable"))

    response = client.get("/resolve-ip/24.48.0.1")
    assert response.status_code == 503
    assert "All geo providers unavailable" in response.json()["detail"]
    assert service_b_calls == []
