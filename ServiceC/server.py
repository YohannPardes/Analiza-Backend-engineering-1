from fastapi import FastAPI, HTTPException
import connector

app = FastAPI()
BASE_URL = "http://svc-b-cont:8080"

@app.get("/")
async def get_data():
    print(f"START: Get Data")
    return await connector.make_request(
        BASE_URL + "/getAll", 5, "ServiceB-GetAll"
    )

@app.get("/resolve-ip/{ip}")
async def resolve_ip(ip: str):
    print(f"START: Add IP {ip}")
    ip = connector.validate_ip(ip)

    response_dict = await connector.make_request(
        f"https://free.freeipapi.com/api/v1/json/{ip}", 4, "FreeIpAPI"
    )
    geo_data = connector.free_ip_api_key_picker(response_dict)
    if geo_data.get("latitude") is None or geo_data.get("longitude") is None:
        raise HTTPException(status_code=502, detail=f"FreeIpAPI returned no location for {ip}")
    print(f"free api worked: {geo_data}")
    return await connector.make_request(
        BASE_URL + "/AddIp", 8, "ServiceB-AddIp", method='POST',
        json_data=geo_data
    )
