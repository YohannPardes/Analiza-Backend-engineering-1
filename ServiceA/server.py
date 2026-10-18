import logging
import os
from fastapi import FastAPI, HTTPException
import connector
import uvicorn
from contracts import SignInRequest
from sign_in import SignInService, InMemoryIpThrottle
from publisher import get_producer
from contextlib import asynccontextmanager


### SETUP ###
# logging init
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)



# FastAPI app init
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup code
    logger.info("Starting up the application...")
    # setting up the producer (Kafka producer)
    producer = get_producer()
    # sign in service initialization
    global sign_in_service  # to be reused in the endpoint
    sign_in_service = SignInService(
        ip_throttle=InMemoryIpThrottle(window_seconds=60),
        producer=producer,
        topic=os.environ["KAFKA_TOPIC"]
    )
    yield
    # Shutdown code
    logger.info("Shutting down the application...")
    producer.close()  # Close the Kafka producer on shutdown

app = FastAPI(lifespan=lifespan)

# Constants for external service URLs
BASE_URL_B = "http://svc-b-cont:8080"
BASE_URL_C = "http://svc-c-cont:8080"



### ENDPOINTS ###
@app.get("/")
async def get_data():
    logger.info("START: Get Data")
    return await connector.make_request(
        BASE_URL_B + "/ips", 2, "ServiceB-GetAll"
    )

@app.post("/resolve-ip-list")
async def resolve_ip_list(ips: list[str]):
    ips = list(dict.fromkeys(ip.strip() for ip in ips if ip.strip()))  # drop blanks + duplicates, keep order
    return_dict = {"success": True, "failed_ip_count": 0, "failed_ips": []}
    for ip in ips:
        try:
            result = await connector.make_request(
                BASE_URL_C + f"/resolve-ip/{ip}", 15, "ServiceC-ResolveIp"
            )
            message = None if result.get("success") else result.get("message")
        except HTTPException as e:
            message = e.detail

        if message is not None:
            logger.warning(f"Error resolving IP {ip}: {message}")
            return_dict["success"] = False
            return_dict["failed_ip_count"] += 1
            return_dict["failed_ips"].append((ip, message))

    return return_dict

@app.get("/favicon.ico")
def favicon():
    logger.info("START: favicon")
    return "ok"

@app.get("/delete/{iid}")
async def delete(iid):
    logger.info(f"START: delete {iid}")
    return await connector.make_request(
        BASE_URL_B + f"/ips/{iid}", 2, "ServiceB-Delete", method='DELETE'
    )

@app.post("/sign-in")
async def sign_in(request : SignInRequest):
    logger.info(f"START: sign-in {request.email}")

    # process the sign-in request
    success = await sign_in_service.handle(request)
    if not success:
        logger.error("Sign-in request failed to process.")
        raise HTTPException(status_code=503, detail="Failed to process sign-in request.")

    return {"message": "Your request was received."}





if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8081, workers=1)
