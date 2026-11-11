from datetime import UTC, datetime
from typing import cast

from sqlalchemy.orm import Session

from app.application.dto.trip_dto import EventDetail, TripDetailResponse
from app.domain.enums import EventType
from app.infra.persistence.models import Event
from app.infra.persistence.result_repository import get_trip_with_events


def get_trip_detail(session: Session, *, trip_id: int) -> TripDetailResponse:
    trip, trip_events = get_trip_with_events(session, trip_id=trip_id)

    return TripDetailResponse(
        trip_id=trip.id,
        run_id=trip.run_id,
        vehicle_id=trip.vehicle_id,
        start_time=datetime.fromtimestamp(trip.start_ts, tz=UTC).isoformat(),
        end_time=datetime.fromtimestamp(trip.end_ts, tz=UTC).isoformat(),
        duration_sec=trip.duration_sec,
        distance_m=trip.distance_m,
        point_count=trip.point_count,
        event_counts=cast(dict[EventType, int], trip.event_counts),
        events=[_to_event_detail(e) for e in trip_events],
    )


def _to_event_detail(event: Event) -> EventDetail:
    raw_detail: dict[str, object] = event.detail or {}
    speed = raw_detail.get("max_speed_kmh")
    if speed is None:
        speed = raw_detail.get("max_change_kmh")
    return EventDetail(
        event_id=event.id,
        type=EventType(event.type),
        start_time=datetime.fromtimestamp(event.start_ts, tz=UTC).isoformat(),
        end_time=datetime.fromtimestamp(event.end_ts, tz=UTC).isoformat(),
        lat=event.lat,
        lon=event.lon,
        speed_kmh=float(cast(float, speed)) if speed is not None else None,
        detail=raw_detail,
    )
