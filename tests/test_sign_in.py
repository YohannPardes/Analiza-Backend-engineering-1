import asyncio
import json
import logging

import pytest
from kafka.errors import KafkaTimeoutError
from pydantic import ValidationError

import publisher
import sign_in
from contracts import SignInRequest
from sign_in import InMemoryIpThrottle, SignInService

VALID = {"email": "a@b.com", "password": "Secret#123", "ip_address": "1.2.3.4"}


class FakeClock:
    """Stand-in for the time module inside sign_in: the test decides what time it is."""
    def __init__(self):
        self.now = 1000.0

    def time(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(sign_in, "time", fake)
    return fake


class FakeProducer:
    def __init__(self, error=None):
        self.sent, self.error = [], error

    def send(self, topic, value):
        if self.error: raise self.error
        self.sent.append((topic, value))


def service(producer, window_seconds=60):
    return SignInService(InMemoryIpThrottle(window_seconds), producer, "user-gateway")


# --- request validation ---

def test_valid_request():
    request = SignInRequest(**VALID)
    assert request.email == "a@b.com" and str(request.ip_address) == "1.2.3.4"


def test_password_is_optional():
    assert SignInRequest(email="a@b.com", ip_address="1.2.3.4").password is None


def test_ipv6_is_accepted():
    assert str(SignInRequest(email="a@b.com", ip_address="2001:4860:4860::8888").ip_address) == "2001:4860:4860::8888"


@pytest.mark.parametrize("missing", ["email", "ip_address"])
def test_required_fields(missing):
    with pytest.raises(ValidationError, match=missing):
        SignInRequest(**{k: v for k, v in VALID.items() if k != missing})


@pytest.mark.parametrize("field, value", [
    ("email", "not-an-email"),
    ("email", "a@"),
    ("ip_address", "999.1.1.1"),
    ("ip_address", "localhost"),
    ("password", "short"),                  # under 8 characters
    ("password", "x" * 129),                # over 128 characters
    ("password", "has space1"),             # space is not allowed
    ("password", "pässwort123"),       # non-ASCII is not allowed
])
def test_invalid_values(field, value):
    with pytest.raises(ValidationError, match=field):
        SignInRequest(**{**VALID, field: value})


# --- IP throttle ---

async def test_first_request_is_allowed(clock):
    assert await InMemoryIpThrottle(60).try_acquire("1.2.3.4")


async def test_same_ip_within_the_window_is_blocked(clock):
    throttle = InMemoryIpThrottle(60)
    await throttle.try_acquire("1.2.3.4")
    clock.now += 59
    assert not await throttle.try_acquire("1.2.3.4")


async def test_ips_are_throttled_independently(clock):
    throttle = InMemoryIpThrottle(60)
    await throttle.try_acquire("1.2.3.4")
    assert await throttle.try_acquire("5.6.7.8")


async def test_allowed_again_after_the_window(clock):
    throttle = InMemoryIpThrottle(60)
    await throttle.try_acquire("1.2.3.4")
    clock.now += 61
    assert await throttle.try_acquire("1.2.3.4")


async def test_blocked_attempts_do_not_extend_the_window(clock):
    """The window counts from the last accepted sign-in, not from the last attempt."""
    throttle = InMemoryIpThrottle(60)
    await throttle.try_acquire("1.2.3.4")         # t=0   accepted
    clock.now += 30
    await throttle.try_acquire("1.2.3.4")         # t=30  blocked
    clock.now += 31
    assert await throttle.try_acquire("1.2.3.4")  # t=61  accepted again


async def test_concurrent_requests_from_one_ip_pass_once(clock):
    throttle = InMemoryIpThrottle(60)
    results = await asyncio.gather(*(throttle.try_acquire("1.2.3.4") for _ in range(20)))
    assert results.count(True) == 1


# --- sign-in service ---

async def test_publishes_the_request_as_json(clock):
    producer = FakeProducer()
    assert await service(producer).handle(SignInRequest(**VALID))
    assert producer.sent == [("user-gateway", VALID)]       # ip_address is a plain string again


async def test_throttled_request_is_not_published(clock):
    producer = FakeProducer()
    sign_in_service = service(producer)
    await sign_in_service.handle(SignInRequest(**VALID))

    assert await sign_in_service.handle(SignInRequest(**{**VALID, "email": "c@d.com"}))   # same IP
    assert len(producer.sent) == 1


async def test_kafka_error_is_reported_and_logged(clock, caplog):
    producer = FakeProducer(error=KafkaTimeoutError("Failed to update metadata after 6.0 secs."))
    with caplog.at_level(logging.ERROR):
        assert await service(producer).handle(SignInRequest(**VALID)) is False
    assert "Failed to update metadata" in caplog.text            # the real cause is in the log


async def test_code_bugs_are_not_hidden_as_kafka_errors(clock):
    producer = FakeProducer(error=TypeError("Object is not JSON serializable"))
    with pytest.raises(TypeError):
        await service(producer).handle(SignInRequest(**VALID))


# --- producer factory ---

def test_producer_needs_the_broker_address(monkeypatch):
    monkeypatch.delenv("KAFKA_BOOTSTRAP_SERVERS", raising=False)
    with pytest.raises(KeyError, match="KAFKA_BOOTSTRAP_SERVERS"):
        publisher.get_producer()


def test_producer_configuration(monkeypatch):
    created = {}
    monkeypatch.setattr(publisher.kafka, "KafkaProducer", lambda **config: created.update(config))
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "kafka-broker:9092")

    publisher.get_producer()

    assert created["bootstrap_servers"] == "kafka-broker:9092"
    assert created["max_block_ms"] <= 10_000                     # a dead broker must not freeze the endpoint for long
    assert json.loads(created["value_serializer"]({"a": 1})) == {"a": 1}
    assert isinstance(created["value_serializer"]({"a": 1}), bytes)
