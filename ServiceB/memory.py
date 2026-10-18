from uuid import uuid4
import asyncio
from contracts import SignInRequest

class Memory():

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.mem_lock = asyncio.Lock()

    @classmethod
    async def acquire_the_lock(cls, func, *args):
        async with cls.mem_lock:
            value = await func(*args)
        return value


class IpMemory(Memory):
    data = {} # {euwewuy: geoData1, eriuwyv: geoData2}
    used_ips = set() # {10.10.0.4, 1.1.2.2, 30.40.50.60}

    @classmethod
    async def get_all_ips(cls):
        return list(cls.used_ips)

    @classmethod
    async def get_data(cls):
        return dict(cls.data)

    @classmethod
    async def length_of_data(cls):
        return len(cls.data)

    @classmethod
    async def does_key_exist(cls, key):
        return key in cls.data

    @classmethod
    async def does_ip_exist(cls, ip):
        """checks if ip exists in memory and returns boolean"""
        return ip in cls.used_ips

    @classmethod
    async def add_if_new(cls, request_data):
        """adds the record unless its ip is already stored; returns the new id or None"""
        if request_data["ipAddress"] in cls.used_ips:
            return None
        new_id = str(uuid4())[:8]
        cls.data[new_id] = request_data
        cls.used_ips.add(request_data["ipAddress"])
        return new_id

    @classmethod
    async def delete_if_exists(cls, key):
        """deletes the record; returns False if the key wasn't there"""
        record = cls.data.pop(key, None)
        if record is None:
            return False
        cls.used_ips.discard(record["ipAddress"])
        return True

class UserMemory(Memory):
    users = {}  # TODO: type hint, e.g. users: dict[str, SignInRequest] = {}

    @classmethod
    async def add_if_new(cls, request_data : SignInRequest):
        """adds the record unless its email is already stored"""
        if request_data.email in cls.users.keys():
            return {"success": True, "added" : False, "message": "User already exists"}

        cls.users[request_data.email] = request_data
        return {"success": True, "added": True, "message": "User added successfully"}    
        