from fastapi import FastAPI, HTTPException
import connector, API_manager

app = FastAPI()
api_manager = API_manager.APIManager()
api_manager.api_list = [API_manager.GeoAPIProvider1(), API_manager.GeoAPIProvider2()]

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

    # Get geo information from the API manager
    try: 
        response_dict = await api_manager.get_geo_infos(ip)
    except API_manager.ProviderUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except API_manager.InvalidIPError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Adding the ip in Services B DB
    return await connector.make_request(
        BASE_URL + "/AddIp", 8, "ServiceB-AddIp", method='POST',
        json_data=response_dict
    )
