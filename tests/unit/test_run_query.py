from unittest.mock import MagicMock

import pytest

from app.application.dto.analyze_dto import TripSummary
from app.application.dto.run_dto import RunResponse
from app.application.run_query import get_run
from app.domain.enums import RunStatus
from app.domain.exceptions import RunNotFoundError


def _make_run(
    *, run_id: int, status: RunStatus, report: dict | None = None, error_message: str | None = None
) -> MagicMock:
    run = MagicMock()
    run.id = run_id
    run.status = status.value
    run.report = report
    run.error_message = error_message
    return run


def _make_trip(*, trip_id: int, run_id: int) -> MagicMock:
    trip = MagicMock()
    trip.id = trip_id
    trip.run_id = run_id
    trip.vehicle_id = "V1"
    trip.start_ts = 1_700_000_000
    trip.end_ts = 1_700_000_600
    trip.duration_sec = 600
    trip.distance_m = 1000.0
    trip.point_count = 60
    trip.event_counts = {"HARSH_ACCEL": 1}
    return trip


def _session_returning(first_scalar: object, scalars: list | None = None) -> MagicMock:
    session = MagicMock()
    first_result = MagicMock()
    first_result.scalar_one_or_none.return_value = first_scalar
    session.execute.return_value = first_result

    if scalars is not None:
        session.scalars.return_value = scalars

    return session


def test_get_run_returns_status_only_when_not_completed() -> None:
    run = _make_run(run_id=1, status=RunStatus.ANALYZING)
    session = _session_returning(run)

    result = get_run(session, run_id=1)

    assert isinstance(result, RunResponse)
    assert result.status == RunStatus.ANALYZING
    assert result.report is None
    assert result.trips is None


def test_get_run_returns_report_and_trips_when_completed() -> None:
    report = {"total_records": 100, "rejected_records": 0}
    run = _make_run(run_id=1, status=RunStatus.COMPLETED, report=report)
    trip = _make_trip(trip_id=10, run_id=1)
    session = _session_returning(run, scalars=[trip])

    result = get_run(session, run_id=1)

    assert result.status == RunStatus.COMPLETED
    assert result.report == report
    assert result.trips is not None
    assert len(result.trips) == 1
    assert isinstance(result.trips[0], TripSummary)
    assert result.trips[0].trip_id == 10


def test_get_run_raises_when_not_found() -> None:
    session = _session_returning(None)

    with pytest.raises(RunNotFoundError):
        get_run(session, run_id=999)
