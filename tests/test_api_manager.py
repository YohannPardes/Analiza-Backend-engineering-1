import logging
import time

import httpx
import pytest

from API_manager import (APIManager, GeoAPIProvider1, GeoAPIProvider2,
                         InvalidIPError, ProviderUnavailable)

IP = "24.48.0.1"

# real responses for 24.48.0.1, trimmed
FREEIPAPI_BODY = {
    "ipVersion": 4, "ipAddress": IP, "latitude": 45.511, "longitude": -73.5561,
    "countryName": "Canada", "countryCode": "CA", "cityName": "Montreal (Ville-Marie)",
    "asn": "5769", "asnOrganization": "Videotron Ltee", "isProxy": False,
}
IPAPI_BODY = {
    "status": "success", "country": "Canada", "countryCode": "CA", "city": "Montreal",
    "lat": 45.6085, "lon": -73.5493, "org": "Videotron Ltee", "as": "AS5769 Videotron Ltee",
    "query": IP,
}
IPAPI_HEADERS = {"X-Rl": "44", "X-Ttl": "60"}


def fake_get(status=200, json=None, headers=None, text=None, error=None):
    """Stand-in for GeoAPI.get: returns a canned response or raises a network error."""
    async def get(url, timeout):
        if error: raise error
        if text is not None: return httpx.Response(status, text=text, headers=headers)
        return httpx.Response(status, json=json, headers=headers)
    return get


def provider(cls, **response):
    api = cls()
    api.get = fake_get(**response)
    return api


def freeipapi(**response):
    return provider(GeoAPIProvider1, **{"json": FREEIPAPI_BODY, **response})


def ipapi(**response):
    return provider(GeoAPIProvider2, **{"json": IPAPI_BODY, "headers": IPAPI_HEADERS, **response})


def manager(*apis):
    api_manager = APIManager()
    api_manager.api_list = list(apis)
    return api_manager


# --- normalization ---

async def test_freeipapi_is_normalized():
    assert await freeipapi().get_geo_infos(IP) == {
        "ipAddress": IP, "latitude": 45.511, "longitude": -73.5561,
        "countryName": "Canada", "cityName": "Montreal (Ville-Marie)",
        "asn": "5769", "asnOrganization": "Videotron Ltee", "isProxy": False,
    }


async def test_ipapi_is_normalized_to_the_same_format():
    record = await ipapi().get_geo_infos(IP)

    assert record.keys() == (await freeipapi().get_geo_infos(IP)).keys()
    assert record["latitude"] == 45.6085 and record["longitude"] == -73.5493
    assert record["asn"] == "5769"                      # split out of "AS5769 Videotron Ltee"
    assert record["asnOrganization"] == "Videotron Ltee"


async def test_ipapi_fail_status_is_an_invalid_ip():
    api = ipapi(json={"status": "fail", "message": "private range"})       # ip-api fails with HTTP 200
    with pytest.raises(InvalidIPError, match="private range"):
        await api.get_geo_infos("10.0.0.1")


# --- status codes and errors ---

@pytest.mark.parametrize("status, error, available_after", [
    (400, InvalidIPError, True),
    (429, ProviderUnavailable, False),
    (403, ProviderUnavailable, False),
    (500, ProviderUnavailable, True),
    (503, ProviderUnavailable, True),
])
async def test_http_errors(status, error, available_after):
    api = freeipapi(status=status, json={})
    with pytest.raises(error):
        await api.get_geo_infos(IP)
    assert api.is_available() is available_after


async def test_403_blocks_for_an_hour():
    api = ipapi(status=403, json={}, headers={})
    with pytest.raises(ProviderUnavailable):
        await api.get_geo_infos(IP)
    assert api.blocked_until - time.time() == pytest.approx(3600, abs=5)


@pytest.mark.parametrize("network_error", [
    httpx.ReadTimeout("timed out"),
    httpx.ConnectError("connection refused"),
])
async def test_network_errors(network_error):
    with pytest.raises(ProviderUnavailable, match="network error"):
        await freeipapi(error=network_error).get_geo_infos(IP)


async def test_invalid_json():
    with pytest.raises(ProviderUnavailable, match="invalid JSON"):
        await freeipapi(text="<h1>Bad gateway</h1>").get_geo_infos(IP)


# --- rate limiting ---

async def test_blocks_once_the_request_limit_is_reached():
    api = freeipapi()                                   # 10 requests / 10 s
    for _ in range(10):
        await api.get_geo_infos(IP)

    assert not api.is_available()
    with pytest.raises(ProviderUnavailable):
        await api.get_geo_infos(IP)


async def test_failed_requests_count_against_the_limit():
    api = freeipapi(status=500, json={})
    for _ in range(10):
        with pytest.raises(ProviderUnavailable):
            await api.get_geo_infos(IP)
    assert not api.is_available()


async def test_available_again_after_the_window():
    api = freeipapi()
    for _ in range(10):
        await api.get_geo_infos(IP)

    api.end_window_time = api.blocked_until = time.time() - 1      # window is over
    assert api.is_available()


def test_fresh_provider_has_full_availability():
    assert GeoAPIProvider1().get_availability() == 10 / 10
    assert GeoAPIProvider2().get_availability() == 45 / 60


async def test_availability_drops_with_each_request():
    api = freeipapi()
    before = api.get_availability()
    await api.get_geo_infos(IP)
    assert api.get_availability() < before


# --- ip-api headers ---

async def test_headers_are_logged(caplog):
    caplog.set_level(logging.INFO)
    await ipapi(headers={"X-Rl": "12", "X-Ttl": "34"}).get_geo_infos(IP)
    assert "X-Rl: 12, X-Ttl: 34" in caplog.text


async def test_no_requests_left_blocks_for_ttl():
    api = ipapi(headers={"X-Rl": "0", "X-Ttl": "30"})

    assert (await api.get_geo_infos(IP))["ipAddress"] == IP       # this answer is still valid
    assert not api.is_available()
    assert api.blocked_until - time.time() == pytest.approx(30, abs=2)


async def test_missing_headers_are_ignored():
    api = ipapi(headers={})
    await api.get_geo_infos(IP)
    assert api.is_available()


async def test_429_keeps_the_ttl_block_from_the_headers():
    api = ipapi(status=429, json={}, headers={"X-Rl": "0", "X-Ttl": "5"})
    with pytest.raises(ProviderUnavailable):
        await api.get_geo_infos(IP)
    assert api.blocked_until - time.time() == pytest.approx(5, abs=2)


# --- manager ---

async def test_manager_uses_the_most_available_provider():
    first, second = freeipapi(), ipapi()                # 1.0 vs 0.75 requests/s
    await manager(second, first).get_geo_infos(IP)

    assert first.num_requests_inside_window == 1
    assert second.num_requests_inside_window == 0


async def test_manager_falls_back_to_the_next_provider():
    broken, working = freeipapi(status=503, json={}), ipapi()
    record = await manager(broken, working).get_geo_infos(IP)

    assert record["ipAddress"] == IP
    assert working.num_requests_inside_window == 1


async def test_manager_skips_blocked_providers():
    blocked, working = freeipapi(), ipapi()
    blocked.blocked_until = time.time() + 60

    await manager(blocked, working).get_geo_infos(IP)
    assert blocked.num_requests_inside_window == 0


async def test_manager_raises_when_every_provider_fails():
    api_manager = manager(freeipapi(status=500, json={}), ipapi(status=503, json={}, headers={}))
    with pytest.raises(ProviderUnavailable, match="All geo providers unavailable"):
        await api_manager.get_geo_infos(IP)


async def test_manager_does_not_retry_an_invalid_ip():
    rejecting, other = freeipapi(status=400, json={}), ipapi()
    with pytest.raises(InvalidIPError):
        await manager(rejecting, other).get_geo_infos(IP)
    assert other.num_requests_inside_window == 0       # another provider would reject it too
