from pydantic import BaseModel, ConfigDict

from app.application.dto.analyze_dto import TripSummary
from app.domain.enums import RunStatus


class RunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_id: int
    status: RunStatus
    error_message: str | None = None
    report: dict[str, object] | None = None
    trips: list[TripSummary] | None = None
