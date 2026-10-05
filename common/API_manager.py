from abc import ABC, abstractmethod
from connector import validate_ip
import httpx, time


class ProviderUnavailable(Exception):
    """Temporary provider failure (rate limit, ban, server/network error): try the next provider."""


class InvalidIPError(Exception):
    """The IP itself was rejected: no provider will succeed."""


class APIClient(ABC):

    def __init__(self, request_limit : tuple[int, int], base_url, api_key=None):
        """
        :param request_limit: tuple of (max_requests, time_window_in_seconds)
        :param base_url: Base URL of the API
        :param api_key: API key for authentication
        """
        self.request_limit = request_limit
        self.base_url = base_url
        self.api_key = api_key


    @abstractmethod
    def get(self, url, timeout):       
        pass


class GeoAPI(APIClient):

    def __init__(self, request_limit : tuple[int, int], base_url):
        """
        :param request_limit: tuple of (max_requests, time_window_in_seconds)
        :param base_url: Base URL of the API
        """
        super().__init__(request_limit, base_url)

        self.end_window_time = None
        self.num_requests_inside_window = 0
        self.blocked_until = None

    async def get_geo_infos(self, ip: str):

        # Check availability
        name = self.__class__.__name__
        if not self.is_available():
            raise ProviderUnavailable(f"{name} is currently unavailable. Blocked until {self.blocked_until}")

        url = f"{self.base_url}/{ip}"

        # Update request window and make the request
        self._update_window() # before the call to manage async calls and avoid race conditions
        try:
            response = await self.get(url, timeout=10)
        except httpx.HTTPError as e:            # timeout, DNS, connection refused...
            raise ProviderUnavailable(f"{name} network error: {e!r}") from e
        self.handle_headers(response)
        self._raise_for_status(response, ip)

        # normalizing and returning the response
        try:
            return self.normalize_response(response)
        except ValueError as e:                 # body is not valid JSON
            raise ProviderUnavailable(f"{name} returned invalid JSON") from e

    def _raise_for_status(self, response, ip):
        """Map an unsuccessful HTTP status to ProviderUnavailable or InvalidIPError."""
        name = self.__class__.__name__
        status = response.status_code
        if status == 400:
            raise InvalidIPError(f"{name} rejected IP {ip}")
        if status == 429:
            if not self.blocked_until or self.blocked_until < time.time():   # keep a more precise block set from headers
                self.blocked_until = time.time() + self.request_limit[1]
            raise ProviderUnavailable(f"{name} rate limited (429)")
        if status == 403:
            self.blocked_until = time.time() + 3600   # ip-api bans for 1 hour
            raise ProviderUnavailable(f"{name} forbidden (403)")
        if status != 200:                       # 500, 503 and any other unexpected status
            raise ProviderUnavailable(f"{name} returned {status}")

    def handle_headers(self, response):
        pass

    def _update_window(self):
        if self.end_window_time is None or time.time() > self.end_window_time:
            self.end_window_time = time.time() + self.request_limit[1]
            self.num_requests_inside_window = 0
        self.num_requests_inside_window += 1

    async def get(self, url, timeout):
        async with httpx.AsyncClient(timeout=timeout) as client:
            return await client.get(url)        # full response

    @abstractmethod
    def normalize_response(self, response):
        pass

    def is_available(self):
        if self.blocked_until and time.time() < self.blocked_until:
            return False

        if self.num_requests_inside_window < self.request_limit[0]:
            return True

        if self.end_window_time and time.time() > self.end_window_time:
            self.num_requests_inside_window = 0
            self.end_window_time = None
            return True

        self.blocked_until = self.end_window_time
        return False

    def get_availability(self):

        # first call or after window reset, return max availability
        if self.end_window_time is None or time.time() > self.end_window_time:
            return self.request_limit[0] / self.request_limit[1] # max availability per API

        requests_remaining = self.request_limit[0] - self.num_requests_inside_window
        time_remaining = self.end_window_time - time.time()

        return requests_remaining / time_remaining


class GeoAPIProvider1(GeoAPI):
    
    def __init__(self):

        self.request_limit = (10, 10)
        self.base_url = "https://free.freeipapi.com/api/v1/json"

        super().__init__(request_limit=self.request_limit,
                          base_url=self.base_url)

    def normalize_response(self, response):
        data = response.json()
        return {
            "ipAddress": data.get("ipAddress"),
            "latitude": data.get("latitude"),
            "longitude": data.get("longitude"),
            "countryName": data.get("countryName"),
            "cityName": data.get("cityName"),
            "asn": data.get("asn"),
            "asnOrganization": data.get("asnOrganization"),
            "isProxy": data.get("isProxy"),
        }


class GeoAPIProvider2(GeoAPI):
    
    def __init__(self):

        self.request_limit = (45, 60)
        self.base_url = "http://ip-api.com/json"

        super().__init__(request_limit=self.request_limit,
                          base_url=self.base_url)

    def normalize_response(self, response):
        data = response.json()
        if data.get("status") != "success":     # ip-api reports failures with HTTP 200
            raise InvalidIPError(f"ip-api failed: {data.get('message')}")

        asn, _, asn_organization = data.get("as", "").partition(" ")   # "AS5769 Videotron Ltee"
        return {
            "ipAddress": data.get("query"),
            "latitude": data.get("lat"),
            "longitude": data.get("lon"),
            "countryName": data.get("country"),
            "cityName": data.get("city"),
            "asn": asn.removeprefix("AS") or None,
            "asnOrganization": asn_organization or data.get("org"),
            "isProxy": data.get("proxy"),
        }

    def handle_headers(self, response):
        X_Rl = response.headers.get('X-Rl')
        X_Ttl = response.headers.get('X-Ttl')

        print(f"X-Rl: {X_Rl}, X-Ttl: {X_Ttl}")

        if X_Rl is not None and X_Ttl is not None and int(X_Rl) == 0:
            self.blocked_until = time.time() + int(X_Ttl)



class APIManager:
    """
    Manages multiple API clients and handles request distribution based on their limits.
    The only entry point to touch the API's is through this class."""

    def __init__(self):
        self.api_list = []

    async def get_geo_infos(self, ip: str):
        """
        Get geo information for the given IP address using the available API clients.
        :param ip: IP address to query
        :return: Geo information from the first available API client

        Logic: We are always trying to use the API with the highest #request/time_remaining_window limit first.
        """
        errors = []
        for api in sorted(self.api_list, key=lambda x: x.get_availability(), reverse=True):
            if not api.is_available():
                continue
            try:
                return await api.get_geo_infos(ip)
            except ProviderUnavailable as e:    # InvalidIPError propagates: another provider won't help
                print(f"Error with {api.__class__.__name__}: {e}")
                errors.append(str(e))

        raise ProviderUnavailable(f"All geo providers unavailable: {errors}")




# minimal compilation testing
if __name__ == "__main__":

    provider1 = GeoAPIProvider1()
    provider2 = GeoAPIProvider2()

    api_manager = APIManager()
    api_manager.api_list.append(provider1)
    api_manager.api_list.append(provider2)


    for i in range(20):
        asyncio.run(api_manager.get_geo_infos("34.45.65.78"))

