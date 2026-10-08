from ipaddress import IPv4Address, IPv6Address

import httpx
import pytest
from fastapi import HTTPException

import connector

URL = "http://svc-b-cont:8080/getAll"


@pytest.fixture
def server(monkeypatch):
    """Route make_request's httpx client to a fake server; returns the list of received requests."""
    received, real_client = [], httpx.AsyncClient

    def install(status=200, json=None, error=None):
        def handler(request):
            received.append(request)
            if error: raise error
            return httpx.Response(status, json=json)
        monkeypatch.setattr(connector.httpx, "AsyncClient",
                            lambda: real_client(transport=httpx.MockTransport(handler)))
        return received
    return install


# --- validate_ip ---

def test_valid_ipv4():
    assert connector.validate_ip("8.8.8.8") == IPv4Address("8.8.8.8")


def test_valid_ipv6():
    assert connector.validate_ip("2001:4860:4860::8888") == IPv6Address("2001:4860:4860::8888")


@pytest.mark.parametrize("ip", ["", "abc", "256.1.1.1", "1.2.3", "8.8.8.8/24"])
def test_invalid_ip_is_a_400(ip):
    with pytest.raises(HTTPException) as e:
        connector.validate_ip(ip)
    assert e.value.status_code == 400


# --- make_request ---

async def test_get_returns_the_json(server):
    received = server(json={"a": 1})
    assert await connector.make_request(URL, 5, "ServiceB") == {"a": 1}
    assert received[0].method == "GET"


async def test_post_sends_the_json_body(server):
    received = server(json={"success": True})
    await connector.make_request(URL, 5, "ServiceB", method="POST", json_data={"ip": "8.8.8.8"})
    assert received[0].method == "POST"
    assert received[0].content == b'{"ip":"8.8.8.8"}'


async def test_delete_method(server):
    received = server(json={"success": True})
    await connector.make_request(URL, 5, "ServiceB", method="DELETE")
    assert received[0].method == "DELETE"


async def test_error_status_is_a_502_with_the_reason(server):
    server(status=400, json={"detail": "missing fields"})
    with pytest.raises(HTTPException) as e:
        await connector.make_request(URL, 5, "ServiceB")
    assert e.value.status_code == 502
    assert "ServiceB failed (400): missing fields" in e.value.detail


@pytest.mark.parametrize("error, status", [
    (httpx.ReadTimeout("timed out"), 504),
    (httpx.ConnectError("connection refused"), 503),
])
async def test_network_errors(server, error, status):
    server(error=error)
    with pytest.raises(HTTPException) as e:
        await connector.make_request(URL, 5, "ServiceB")
    assert e.value.status_code == status
