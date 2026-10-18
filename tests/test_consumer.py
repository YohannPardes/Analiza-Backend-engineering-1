import logging

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from memory import UserMemory

pytestmark = pytest.mark.usefixtures("clean_memory")

EVENT = {"email": "alice@example.com", "password": None, "ip_address": "1.2.3.4"}   # as ServiceA publishes it


@pytest.fixture
def requests_to_b(consumer, monkeypatch):
    """Replace the consumer's call to ServiceB: record it and answer like ServiceB would."""
    sent = []

    async def fake_make_request(url, timeout, service_name, method="GET", json_data=None):
        sent.append({"url": url, "method": method, "json": json_data})
        return {"success": True, "message": "User added successfully"}

    monkeypatch.setattr(consumer, "make_request", fake_make_request)
    return sent


@pytest.fixture
def real_service_b(consumer, service_b, monkeypatch):
    """Route the consumer's calls into the real ServiceB app (in memory, no Docker)."""
    client = TestClient(service_b.app)

    async def to_service_b(url, timeout, service_name, method="GET", json_data=None):
        response = client.request(method, url.removeprefix("http://svc-b-cont:8080"), json=json_data)
        if response.status_code != 200:                     # same contract as connector.make_request
            raise HTTPException(status_code=502, detail=f"{service_name} failed ({response.status_code})")
        return response.json()

    monkeypatch.setattr(consumer, "make_request", to_service_b)


# --- what the consumer sends ---

def test_event_is_posted_to_service_b(consumer, requests_to_b):
    consumer.handle(EVENT)
    assert requests_to_b == [{"url": "http://svc-b-cont:8080/users", "method": "POST", "json": EVENT}]


def test_each_event_is_one_call(consumer, requests_to_b):
    for i in range(3):
        consumer.handle({**EVENT, "email": f"user{i}@example.com"})
    assert [call["json"]["email"] for call in requests_to_b] == [f"user{i}@example.com" for i in range(3)]


def test_success_is_logged(consumer, requests_to_b, caplog):
    with caplog.at_level(logging.INFO):
        consumer.handle(EVENT)
    assert "Message processed successfully" in caplog.text


# --- failures must not stop the consumer ---

@pytest.mark.parametrize("status, detail", [
    (503, "ServiceB unreachable"),
    (504, "ServiceB timed out"),
    (502, "ServiceB failed (500): Internal Server Error"),
])
def test_service_b_failure_is_logged_not_raised(consumer, monkeypatch, caplog, status, detail):
    async def failing(*args, **kwargs):
        raise HTTPException(status_code=status, detail=detail)
    monkeypatch.setattr(consumer, "make_request", failing)

    with caplog.at_level(logging.ERROR):
        consumer.handle(EVENT)                                  # returns normally: the loop goes on
    assert str(status) in caplog.text and detail in caplog.text


# --- end to end: event -> consumer -> ServiceB memory ---

def test_signup_stores_the_user(consumer, real_service_b):
    consumer.handle(EVENT)
    assert "alice@example.com" in UserMemory.users


def test_signin_of_a_known_user_keeps_one_record(consumer, real_service_b, caplog):
    consumer.handle(EVENT)
    with caplog.at_level(logging.INFO):
        consumer.handle({**EVENT, "ip_address": "5.6.7.8"})

    assert len(UserMemory.users) == 1
    assert "User already exists" in caplog.text


def test_invalid_event_is_rejected_by_service_b_and_skipped(consumer, real_service_b, caplog):
    with caplog.at_level(logging.ERROR):
        consumer.handle({**EVENT, "email": "not-an-email"})

    assert UserMemory.users == {}
    assert "Error processing message" in caplog.text
