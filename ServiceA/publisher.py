import kafka
import json
import os
from kafka.errors import KafkaTimeoutError



def get_producer():
    """
    Returns a producer instance. This function can be modified to return different types of producers
    based on configuration or environment variables.
    """
    try:
        return kafka.KafkaProducer(
            bootstrap_servers=os.environ["KAFKA_BOOTSTRAP_SERVERS"],
            value_serializer=lambda v: json.dumps(v).encode(),
            max_block_ms=10000, 
        )
    except KafkaTimeoutError as e:
        raise RuntimeError("Failed to connect to Kafka broker.") from e