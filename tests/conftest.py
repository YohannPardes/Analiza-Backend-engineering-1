import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent

# the containers copy these files flat into /app, so mirror that import layout
for folder in ("common", "ServiceA", "ServiceB"):
    sys.path.insert(0, str(ROOT / folder))

import kafka
from memory import IpMemory, UserMemory


def load_server(service):
    """Import <service>/server.py under a unique name (every service calls it server.py)."""
    spec = importlib.util.spec_from_file_location(f"{service}_server", ROOT / service / "server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def service_a():
    return load_server("ServiceA")


@pytest.fixture(scope="session")
def service_b():
    return load_server("ServiceB")


@pytest.fixture(scope="session")
def service_c():
    return load_server("ServiceC")


@pytest.fixture(scope="session")
def consumer():
    """Import kafka-consumer/process.py without Kafka.

    The module creates its KafkaConsumer and runs its loop at import time, so the import
    gets an empty fake consumer: the loop ends at once and handle() is left to test.
    """
    patch = pytest.MonkeyPatch()
    for name, value in {"KAFKA_TOPIC": "user-gateway", "KAFKA_BOOTSTRAP_SERVERS": "kafka-broker:9092",
                        "KAFKA_GROUP_ID": "user-gateway-group"}.items():
        patch.setenv(name, value)
    patch.setattr(kafka, "KafkaConsumer", lambda *args, **kwargs: iter(()))
    spec = importlib.util.spec_from_file_location("kafka_consumer_process", ROOT / "kafka-consumer" / "process.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    patch.undo()
    return module


@pytest.fixture
def clean_memory():
    """IpMemory and UserMemory keep their state on the class, so empty them around every test."""
    IpMemory.data.clear()
    IpMemory.used_ips.clear()
    UserMemory.users.clear()
    yield
    IpMemory.data.clear()
    IpMemory.used_ips.clear()
    UserMemory.users.clear()
