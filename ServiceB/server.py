import logging
from fastapi import FastAPI, HTTPException
import uvicorn
from memory import IpMemory, UserMemory
import geo_cluster
from contracts import SignInRequest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI()

@app.get("/ips")
async def get_data():
    logger.info(f"START: Get Data. Length: {await IpMemory.acquire_the_lock(IpMemory.length_of_data)}")
    return await IpMemory.acquire_the_lock(IpMemory.get_data)

@app.get("/ips/addresses")
async def get_all_ips():
    return await IpMemory.acquire_the_lock(IpMemory.get_all_ips)

@app.post("/ips")
async def add_ip(request_data: dict):
    logger.info("START: Add IP")
    missing = [k for k in ("ipAddress", "latitude", "longitude") if request_data.get(k) is None]
    if missing:
        raise HTTPException(status_code=400, detail=f"missing fields: {missing}")

    new_id = await IpMemory.acquire_the_lock(IpMemory.add_if_new, request_data)
    if new_id is None: return {"success": False, "message": "IP address already exists"}

    return {"success": True, "new_id": new_id, "data_length": await IpMemory.acquire_the_lock(IpMemory.length_of_data)}

@app.delete("/ips/{iid}")
async def delete(iid):
    logger.info(f"START: delete {iid}")
    if not await IpMemory.acquire_the_lock(IpMemory.delete_if_exists, iid):
        return {"success": False, "message": "IP address does not exists"}

    return {
        "success": True,
        "data_length": await IpMemory.acquire_the_lock(IpMemory.length_of_data)
    }

@app.get("/clusters")
async def generate_geo_clusters():
    logger.info("START: generate geo clusters")
    data = await IpMemory.acquire_the_lock(IpMemory.get_data)
    return geo_cluster.cluster(data)

@app.post("/users")
async def add_user(request_data: SignInRequest):
    logger.info("START: Add User")

    output = await UserMemory.acquire_the_lock(UserMemory.add_if_new, request_data)
    if not output["success"]:
        raise HTTPException(status_code=400, detail=output["message"])
    if not output.get("added"):
        return {"success": True, "message": "User already exists"}

    return {"success": True, "message": "User added successfully"}


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8082, workers=1)
    