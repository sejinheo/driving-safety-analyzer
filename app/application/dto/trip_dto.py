from pydantic import BaseModel, ConfigDict

from app.domain.enums import EventType


class EventDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: int
    type: EventType
    start_time: str
    end_time: str
    lat: float | None
    lon: float | None
    speed_kmh: float | None
    detail: dict[str, object]



class TripDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    trip_id: int
    run_id: int
    vehicle_id: str
    start_time: str
    end_time: str
    duration_sec: int
    distance_m: float
    point_count: int
    event_counts: dict[EventType, int]
    events: list[EventDetail]
