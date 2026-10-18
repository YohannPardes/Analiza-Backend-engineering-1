from kafka import KafkaConsumer
import asyncio
import json
import os
import logging
from fastapi import HTTPException
from connector import make_request

consumer = KafkaConsumer(
    os.environ["KAFKA_TOPIC"],
    bootstrap_servers=os.environ["KAFKA_BOOTSTRAP_SERVERS"],
    group_id=os.environ["KAFKA_GROUP_ID"],
    auto_offset_reset="earliest",
    value_deserializer=lambda v: json.loads(v),      # bytes → dict (reverse of ServiceA's serializer)
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

service_b_url = "http://svc-b-cont:8080"  # ServiceB's URL

def handle(message: dict):
    """
    Handle the incoming message from Kafka.
    :param message: The message received from Kafka, expected to be a dictionary.
    """
    logger.info(f"Received message: {message}")
    # Received message: {'email': 'alice-63f488@example.com', 'password': 'Secret#123', 'ip_address': '10.101.117.249'}
    try:
        # make_request is async: run it to completion here (this worker is plain sync code)
        result = asyncio.run(make_request(service_b_url + "/users",
                                          timeout=10,
                                          service_name="ServiceB",
                                          method='POST',
                                          json_data=message))
    except HTTPException as e:      # make_request turns timeouts, unreachable and non-200 answers into this
        logger.error(f"Error processing message: {e.status_code} - {e.detail}")
        return

    logger.info(f"Message processed successfully: {result}")


for message in consumer:
    handle(message.value)  # message.value = a dict

