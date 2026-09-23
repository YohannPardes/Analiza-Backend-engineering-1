from fastapi import FastAPI, HTTPException, Query
#import uvicorn
from memory import IpMemory
import geo_cluster

app = FastAPI()

@app.get("/getAll")
async def get_data():
    print(f"START: Get Data. Length: {await IpMemory.acquire_the_lock(IpMemory.length_of_data)}")
    return await IpMemory.acquire_the_lock(IpMemory.get_data)

@app.get("/getAllIPs")
async def get_all_ips():
    return await IpMemory.acquire_the_lock(IpMemory.get_all_ips)

@app.post("/AddIp")
async def add_ip(request_data: dict):
    print("START: Add IP")
    missing = [k for k in ("ipAddress", "latitude", "longitude") if request_data.get(k) is None]
    if missing:
        raise HTTPException(status_code=400, detail=f"missing fields: {missing}")

    new_id = await IpMemory.acquire_the_lock(IpMemory.add_if_new, request_data)
    if new_id is None: return {"success": False, "message": "IP address already exists"}

    return {"success": True, "new_id": new_id, "data_length": await IpMemory.acquire_the_lock(IpMemory.length_of_data)}

@app.delete("/delete/{iid}")
async def delete(iid):
    print(f"START: delete {iid}")
    if not await IpMemory.acquire_the_lock(IpMemory.delete_if_exists, iid):
        return {"success": False, "message": "IP address does not exists"}

    return {
        "success": True,
        "data_length": await IpMemory.acquire_the_lock(IpMemory.length_of_data)
    }

@app.get("/generate-geo-clusters")
async def generate_geo_clusters(max_km: float = Query(300, gt=0)):
    print(f"START: generate geo clusters (max_km={max_km})")
    data = await IpMemory.acquire_the_lock(IpMemory.get_data)
    return geo_cluster.cluster(data, max_km=max_km)

#if __name__ == "__main__":
    #uvicorn.run("server:app", host="0.0.0.0", port=8082, workers=1)
