from pydantic import BaseModel


class VectorProviderInfo(BaseModel):
    active_provider: str
    supported_providers: list[str]

