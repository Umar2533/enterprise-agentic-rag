from pydantic import BaseModel


class CollectionInfo(BaseModel):
    name: str
    provider: str

