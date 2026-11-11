from pydantic import BaseModel, ConfigDict

from app.domain.enums import EventType, RunStatus


class AnalysisReport(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total_records: int
    rejected_records: int
    rejected_by_reason: dict[str, int]
    duplicates_merged: int
    speed_nullified: int
    gps_swapped: int
    gps_nullified: int
    gps_teleport_removed: int
    speed_spikes_removed: int
    interpolated_values: int
    interpolated_rows: int


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


class AnalyzeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_id: int
    status: RunStatus
    report: AnalysisReport
    trips: list[TripSummary]
