from typing import Final, cast

import structlog
from psycopg import Connection, sql
from psycopg.errors import DatabaseError, OperationalError
from psycopg.types.json import Jsonb
from sqlalchemy import select
from sqlalchemy.exc import OperationalError as SAOperationalError
from sqlalchemy.orm import Session

from app.domain.enums import RunStatus
from app.domain.exceptions import DataIngestionError, DbUnavailableError, TripNotFoundError
from app.infra.persistence.models import AnalysisRun, Event, Trip

logger = structlog.get_logger(__name__)

_TRIP_COLUMNS: Final = (
    "run_id",
    "vehicle_id",
    "start_ts",
    "end_ts",
    "duration_sec",
    "distance_m",
    "point_count",
    "event_count",
    "event_counts",
)
_PG_MAX_PARAMS: Final = 65535
_TRIP_BATCH_SIZE: Final = _PG_MAX_PARAMS // len(_TRIP_COLUMNS)

_COPY_TRIP_POINTS: Final = """
    COPY trip_points (trip_id, ts, lat, lon, speed, is_interpolated,
        speed_invalid, speed_out_of_range, gps_swapped, gps_invalid, speed_spike, gps_teleport)
    FROM STDIN
"""

_COPY_EVENTS: Final = """
    COPY events (trip_id, type, start_ts, end_ts, lat, lon, detail)
    FROM STDIN
"""

_UPDATE_ANALYZE_CHECKPOINT: Final = """
    UPDATE analysis_runs
    SET analyze_last_vehicle = %(last_vehicle)s,
        analyze_last_ts = %(last_ts)s
    WHERE id = %(run_id)s
"""


def save_trips_batch(
    conn: Connection,
    *,
    run_id: int,
    trips: list[dict[str, object]],
    points: list[dict[str, object]],
    events: list[dict[str, object]],
    last_vehicle: str,
    last_ts: int,
) -> None:
    try:
        with conn.transaction():
            trip_id_map = _insert_trips(conn, run_id=run_id, trips=trips)
            _copy_trip_points(conn, points=points, trip_id_map=trip_id_map)
            _copy_events(conn, events=events, trip_id_map=trip_id_map)
            conn.execute(
                _UPDATE_ANALYZE_CHECKPOINT,
                {"run_id": run_id, "last_vehicle": last_vehicle, "last_ts": last_ts},
            )
        logger.info(
            "trips_batch_committed",
            run_id=run_id,
            trips=len(trips),
            points=len(points),
            events=len(events),
        )
    except (DataIngestionError, DbUnavailableError):
        raise
    except ValueError as exc:
        raise DataIngestionError(str(exc)) from exc
    except OperationalError as exc:
        raise DbUnavailableError() from exc
    except DatabaseError as exc:
        raise DataIngestionError(str(exc)) from exc


def get_trip_with_events(session: Session, *, trip_id: int) -> tuple[Trip, list[Event]]:
    trip = _fetch_completed_trip(session, trip_id=trip_id)

    try:
        trip_events = list(
            session.execute(
                select(Event).where(Event.trip_id == trip_id).order_by(Event.start_ts)
            ).scalars()
        )
    except SAOperationalError as exc:
        raise DbUnavailableError() from exc

    return trip, trip_events


def _fetch_completed_trip(session: Session, *, trip_id: int) -> Trip:
    try:
        result = session.execute(
            select(Trip, AnalysisRun)
            .join(AnalysisRun, Trip.run_id == AnalysisRun.id)
            .where(Trip.id == trip_id)
            .where(AnalysisRun.status == RunStatus.COMPLETED)
        ).one_or_none()
    except SAOperationalError as exc:
        raise DbUnavailableError() from exc

    if result is None:
        raise TripNotFoundError(trip_id)

    trip, _ = result
    return trip


def _insert_trips(
    conn: Connection,
    *,
    run_id: int,
    trips: list[dict[str, object]],
) -> dict[int, int]:
    if not trips:
        return {}
    trip_id_map: dict[int, int] = {}
    for i in range(0, len(trips), _TRIP_BATCH_SIZE):
        chunk = trips[i : i + _TRIP_BATCH_SIZE]
        trip_id_map.update(_insert_trips_chunk(conn, run_id=run_id, trips=chunk))
    return trip_id_map


def _insert_trips_chunk(
    conn: Connection,
    *,
    run_id: int,
    trips: list[dict[str, object]],
) -> dict[int, int]:
    placeholders = sql.SQL(", ").join(
        sql.SQL("({})").format(sql.SQL(", ").join([sql.Placeholder()] * len(_TRIP_COLUMNS)))
        for _ in trips
    )
    query = sql.SQL("INSERT INTO trips ({columns}) VALUES {placeholders} RETURNING id").format(
        columns=sql.SQL(", ").join(sql.Identifier(c) for c in _TRIP_COLUMNS),
        placeholders=placeholders,
    )
    params: list[object] = []
    for t in trips:
        params.extend(
            [
                run_id,
                t["vehicle_id"],
                t["start_ts"],
                t["end_ts"],
                t["duration_sec"],
                t["distance_m"],
                t["point_count"],
                t["event_count"],
                Jsonb(t["event_counts"]),
            ]
        )
    rows = conn.execute(query, params).fetchall()
    return {cast(int, t["trip_id"]): row[0] for t, row in zip(trips, rows, strict=True)}


def _copy_trip_points(
    conn: Connection,
    *,
    points: list[dict[str, object]],
    trip_id_map: dict[int, int],
) -> None:
    if not points:
        return
    with conn.cursor() as cur, cur.copy(_COPY_TRIP_POINTS) as copy:
        for p in points:
            copy.write_row(
                (
                    trip_id_map[cast(int, p["trip_id"])],
                    p["ts"],
                    p.get("lat"),
                    p.get("lon"),
                    p.get("speed"),
                    p["is_interpolated"],
                    p["speed_invalid"],
                    p["speed_out_of_range"],
                    p["gps_swapped"],
                    p["gps_invalid"],
                    p["speed_spike"],
                    p["gps_teleport"],
                )
            )


def _copy_events(
    conn: Connection,
    *,
    events: list[dict[str, object]],
    trip_id_map: dict[int, int],
) -> None:
    if not events:
        return
    with conn.cursor() as cur, cur.copy(_COPY_EVENTS) as copy:
        for e in events:
            copy.write_row(
                (
                    trip_id_map[cast(int, e["trip_id"])],
                    e["type"],
                    e["start_ts"],
                    e["end_ts"],
                    e.get("lat"),
                    e.get("lon"),
                    Jsonb(e["detail"]),
                )
            )
