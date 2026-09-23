import httpx
from pydantic import BaseModel, IPvAnyAddress
from fastapi import HTTPException

class ValidIpDTO(BaseModel):
    ip: IPvAnyAddress

def validate_ip(ip: str):
    # Instantiate the Pydantic model to perform validation
    try: validated = ValidIpDTO(ip=ip)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    print("validation passed: ", validated.ip)
    return validated.ip


async def make_request(url, timeout, service_name, method='GET', json_data=None):
    async with httpx.AsyncClient() as client:
        http_method, kwargs = client.get, {"timeout": timeout}
        if method == 'POST':
            http_method, kwargs['json'] = client.post, json_data
        if method == 'DELETE': http_method = client.delete

        try: response = await http_method(url, **kwargs)
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail=f"{service_name} timed out")
        except httpx.RequestError:
            raise HTTPException(status_code=503, detail=f"{service_name} unreachable")

    if response.status_code != 200:
        try: reason = response.json().get("detail", response.text)
        except ValueError: reason = response.text
        raise HTTPException(status_code=502, detail=f"{service_name} failed ({response.status_code}): {reason}")
    return response.json()


def free_ip_api_key_picker(js):
    result = {}
    our_keys = {
        "ipAddress",
        "latitude",
        "longitude",
        "countryName",
        "cityName",
        "asn",
        "asnOrganization",
        "isProxy"
    }
    for k,v in js.items():
        if k in our_keys: result[k] = v
    return result
