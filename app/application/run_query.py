from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.application.dto.analyze_dto import TripSummary
from app.application.dto.run_dto import RunResponse
from app.domain.enums import EventType, RunStatus
from app.domain.exceptions import DbUnavailableError, RunNotFoundError
from app.infra.persistence.models import AnalysisRun, Trip


def get_run(session: Session, *, run_id: int) -> RunResponse:
    try:
        run = session.execute(
            select(AnalysisRun).where(AnalysisRun.id == run_id)
        ).scalar_one_or_none()
    except OperationalError as exc:
        raise DbUnavailableError() from exc

    if run is None:
        raise RunNotFoundError(run_id)

    status = RunStatus(run.status)
    if status != RunStatus.COMPLETED:
        return RunResponse(run_id=run.id, status=status)

    try:
        trip_rows = list(
            session.scalars(select(Trip).where(Trip.run_id == run_id).order_by(Trip.start_ts))
        )
    except OperationalError as exc:
        raise DbUnavailableError() from exc

    trips = [_to_trip_summary(t) for t in trip_rows]
    return RunResponse(run_id=run.id, status=status, report=run.report, trips=trips)


def _to_trip_summary(trip: Trip) -> TripSummary:
    return TripSummary(
        trip_id=trip.id,
        vehicle_id=trip.vehicle_id,
        start_time=datetime.fromtimestamp(trip.start_ts, tz=UTC).isoformat(),
        end_time=datetime.fromtimestamp(trip.end_ts, tz=UTC).isoformat(),
        duration_sec=trip.duration_sec,
        distance_m=trip.distance_m,
        point_count=trip.point_count,
        event_counts=cast(dict[EventType, int], trip.event_counts),
    )
