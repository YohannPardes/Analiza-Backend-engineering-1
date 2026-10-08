import pytest

from memory import IpMemory

pytestmark = pytest.mark.usefixtures("clean_memory")

RECORD = {"ipAddress": "8.8.8.8", "latitude": 37.4, "longitude": -122.1}


async def test_add_new_record():
    new_id = await IpMemory.add_if_new(RECORD)

    assert await IpMemory.get_data() == {new_id: RECORD}
    assert await IpMemory.does_ip_exist("8.8.8.8")
    assert await IpMemory.length_of_data() == 1


async def test_duplicate_ip_is_not_added():
    await IpMemory.add_if_new(RECORD)
    assert await IpMemory.add_if_new(dict(RECORD)) is None
    assert await IpMemory.length_of_data() == 1


async def test_delete_frees_the_ip():
    new_id = await IpMemory.add_if_new(RECORD)

    assert await IpMemory.delete_if_exists(new_id)
    assert not await IpMemory.does_key_exist(new_id)
    assert not await IpMemory.does_ip_exist("8.8.8.8")
    assert await IpMemory.add_if_new(RECORD) is not None          # can be added again


async def test_delete_unknown_id():
    assert not await IpMemory.delete_if_exists("missing")


async def test_get_all_ips():
    await IpMemory.add_if_new(RECORD)
    await IpMemory.add_if_new({**RECORD, "ipAddress": "1.1.1.1"})
    assert sorted(await IpMemory.get_all_ips()) == ["1.1.1.1", "8.8.8.8"]


async def test_get_data_returns_a_copy():
    await IpMemory.add_if_new(RECORD)
    (await IpMemory.get_data()).clear()
    assert await IpMemory.length_of_data() == 1


async def test_acquire_the_lock_passes_arguments_and_result():
    new_id = await IpMemory.acquire_the_lock(IpMemory.add_if_new, RECORD)
    assert await IpMemory.acquire_the_lock(IpMemory.does_key_exist, new_id)
