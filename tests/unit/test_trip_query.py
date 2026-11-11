from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from app.application.dto.trip_dto import EventDetail, TripDetailResponse
from app.application.trip_query import get_trip_detail
from app.domain.enums import EventType
from app.domain.exceptions import TripNotFoundError


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


def _make_event(
    *,
    event_id: int,
    trip_id: int,
    event_type: EventType,
    detail: dict,
) -> MagicMock:
    event = MagicMock()
    event.id = event_id
    event.trip_id = trip_id
    event.type = event_type.value
    event.start_ts = 1_700_000_100
    event.end_ts = 1_700_000_110
    event.lat = 37.5
    event.lon = 127.0
    event.detail = detail
    return event


def test_get_trip_detail_returns_response(mocker: MockerFixture) -> None:
    trip = _make_trip(trip_id=1, run_id=1)
    mocker.patch(
        "app.application.trip_query.get_trip_with_events",
        return_value=(trip, []),
    )
    session = MagicMock()

    result = get_trip_detail(session, trip_id=1)

    assert isinstance(result, TripDetailResponse)
    assert result.trip_id == 1
    assert result.run_id == 1
    assert result.events == []


def test_get_trip_detail_includes_events(mocker: MockerFixture) -> None:
    trip = _make_trip(trip_id=1, run_id=1)
    event = _make_event(
        event_id=10,
        trip_id=1,
        event_type=EventType.SCHOOL_ZONE_SPEEDING,
        detail={"max_speed_kmh": 42.1, "zones": "광장초등학교"},
    )
    mocker.patch(
        "app.application.trip_query.get_trip_with_events",
        return_value=(trip, [event]),
    )
    session = MagicMock()

    result = get_trip_detail(session, trip_id=1)

    assert len(result.events) == 1
    ev = result.events[0]
    assert isinstance(ev, EventDetail)
    assert ev.event_id == 10
    assert ev.type == EventType.SCHOOL_ZONE_SPEEDING
    assert ev.speed_kmh == pytest.approx(42.1)


def test_get_trip_detail_speed_kmh_from_harsh_event(mocker: MockerFixture) -> None:
    trip = _make_trip(trip_id=2, run_id=1)
    event = _make_event(
        event_id=20,
        trip_id=2,
        event_type=EventType.HARSH_ACCEL,
        detail={"max_change_kmh": 15.5},
    )
    mocker.patch(
        "app.application.trip_query.get_trip_with_events",
        return_value=(trip, [event]),
    )
    session = MagicMock()

    result = get_trip_detail(session, trip_id=2)

    assert result.events[0].speed_kmh == pytest.approx(15.5)


def test_get_trip_detail_raises_when_not_found(mocker: MockerFixture) -> None:
    mocker.patch(
        "app.application.trip_query.get_trip_with_events",
        side_effect=TripNotFoundError(99),
    )
    session = MagicMock()

    with pytest.raises(TripNotFoundError):
        get_trip_detail(session, trip_id=99)
