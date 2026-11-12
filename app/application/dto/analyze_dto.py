from pydantic import BaseModel, ConfigDict

from app.domain.enums import EventType, RunStatus


class TripSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    trip_id: int
    vehicle_id: str
    start_time: str
    end_time: str
    duration_sec: int
    distance_m: float
    point_count: int
    event_counts: dict[EventType, int]


class AcceptedResponse(BaseModel):
    run_id: int
    status: RunStatus
