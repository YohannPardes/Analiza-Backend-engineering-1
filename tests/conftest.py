import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent

# the containers copy these files flat into /app, so mirror that import layout
for folder in ("common", "ServiceB"):
    sys.path.insert(0, str(ROOT / folder))

from memory import IpMemory


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


@pytest.fixture
def clean_memory():
    """IpMemory keeps its state on the class, so empty it around every test."""
    IpMemory.data.clear()
    IpMemory.used_ips.clear()
    yield
    IpMemory.data.clear()
    IpMemory.used_ips.clear()
