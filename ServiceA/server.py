from fastapi import FastAPI, HTTPException
import connector
import uvicorn

app = FastAPI()
BASE_URL_B = "http://svc-b-cont:8080"
BASE_URL_C = "http://svc-c-cont:8080"

@app.get("/")
async def get_data():
    print(f"START: Get Data")
    return await connector.make_request(
        BASE_URL_B + "/getAll", 2, "ServiceB-GetAll"
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
            print(f"Error resolving IP {ip}: {message}")
            return_dict["success"] = False
            return_dict["failed_ip_count"] += 1
            return_dict["failed_ips"].append((ip, message))

    return return_dict

@app.get("/favicon.ico")
def favicon():
    print(f"START: favicon")
    return "ok"


@app.get("/delete/{iid}")
async def delete(iid):
    print(f"START: delete {iid}")
    return await connector.make_request(
        BASE_URL_B + f"/delete/{iid}", 2, "ServiceB-Delete", method='DELETE'
    )

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8081, workers=1)
