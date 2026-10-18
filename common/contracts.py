from pydantic import BaseModel, EmailStr, IPvAnyAddress, Field
from typing import Annotated

PasswordStr = Annotated[str, Field(min_length=8, max_length=128, pattern=r"^[\x21-\x7E]+$")]

class SignInRequest(BaseModel):
    email: EmailStr             # required
    password: PasswordStr | None = None # optional
    ip_address: IPvAnyAddress   # required