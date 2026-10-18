import asyncio

import pytest

from contracts import SignInRequest
from memory import IpMemory, UserMemory

pytestmark = pytest.mark.usefixtures("clean_memory")

RECORD = {"ipAddress": "8.8.8.8", "latitude": 37.4, "longitude": -122.1}
ALICE = SignInRequest(email="alice@example.com", ip_address="1.2.3.4")


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


# --- shared Memory base ---

def test_each_memory_gets_its_own_lock():
    assert isinstance(IpMemory.mem_lock, asyncio.Lock)
    assert IpMemory.mem_lock is not UserMemory.mem_lock      # a user signup never waits on an IP lookup


async def test_users_and_ips_are_stored_separately():
    await UserMemory.add_if_new(ALICE)
    assert await IpMemory.length_of_data() == 0


# --- users ---

async def test_new_user_is_added():
    result = await UserMemory.add_if_new(ALICE)

    assert result["success"] is True and result["added"] is True
    assert UserMemory.users == {"alice@example.com": ALICE}


async def test_existing_user_is_not_added_again():
    await UserMemory.add_if_new(ALICE)
    result = await UserMemory.add_if_new(SignInRequest(email="alice@example.com", ip_address="5.6.7.8"))

    assert result["success"] is True and result["added"] is False
    assert UserMemory.users["alice@example.com"].ip_address == ALICE.ip_address     # the first record is kept


async def test_different_users_are_all_added():
    await UserMemory.add_if_new(ALICE)
    await UserMemory.add_if_new(SignInRequest(email="bob@example.com", ip_address="1.2.3.4"))
    assert sorted(UserMemory.users) == ["alice@example.com", "bob@example.com"]


async def test_concurrent_signups_of_one_email_add_it_once():
    results = await asyncio.gather(*(UserMemory.acquire_the_lock(UserMemory.add_if_new, ALICE) for _ in range(20)))
    assert [r["added"] for r in results].count(True) == 1
