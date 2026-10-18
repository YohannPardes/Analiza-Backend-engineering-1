
import logging
import time
from abc import ABC, abstractmethod
from kafka.errors import KafkaError
from contracts import SignInRequest
import httpx

logger = logging.getLogger(__name__)


class IpThrottle(ABC):

    """
    Abstract base class for IP throttling. 
    In order to keep the interface when adding redis and yield minimal changes
    """

    @abstractmethod
    async def try_acquire(self, ip: str) -> bool:
        """
        Attempt to acquire permission for the given IP address.
        :param ip: The IP address to check.
        :return: True if permission is granted, False otherwise.
        """
        pass

class InMemoryIpThrottle(IpThrottle):

    """
    Simple in memory implementation of the IpThrottle interface.
    """

    def __init__(self, window_seconds: int):
        """
        Initialize the in-memory IP throttle.
        :param window_seconds: The time window in seconds for throttling.
        """
        self.window_seconds = window_seconds
        self.last_seen = {}

    async def try_acquire(self, ip: str) -> bool:
        """
        Attempt to acquire permission for the given IP address.
        :param ip: The IP address to check.
        :return: True if permission is granted, False otherwise.
        """
        current_time = time.time()
        last_time = self.last_seen.get(ip)

        if last_time is None or (current_time - last_time) > self.window_seconds:
            self.last_seen[ip] = current_time
            return True
        else:
            return False

class SignInService():
    """
    The main class that handles the sign-in requests.
    """
    def __init__(self, ip_throttle: IpThrottle, producer, topic: str): 

        self.ip_throttle = ip_throttle
        self.producer = producer
        self.topic = topic

    async def handle(self, request : SignInRequest) -> bool:

        # Check if the IP address is allowed to make a sign-in request
        if not await self.ip_throttle.try_acquire(str(request.ip_address)):
            return True # current behavior, just do nothing.

        try: 
            # Publish the sign-in event to Kafka
            self.producer.send(self.topic, request.model_dump(mode="json"))
            logger.info(f"Published sign-in event to topic {self.topic}")
            return True
        except KafkaError:              # broker unreachable, metadata timeout...; code bugs still raise
            logger.exception(f"Failed to publish sign-in event to topic {self.topic}")
            return False