from pydantic import BaseModel


class ZoneResponse(BaseModel):
    inserted: int
