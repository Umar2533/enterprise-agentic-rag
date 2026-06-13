from pydantic import BaseModel


class MessageResponse(BaseModel):
    success: bool
    message: str

