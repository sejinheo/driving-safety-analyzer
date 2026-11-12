from typing import Final

import polars as pl
import structlog
from psycopg import Connection
from psycopg.errors import DatabaseError, OperationalError

from app.domain.enums import RunStatus
from app.domain.exceptions import AnalysisInProgressError, DataIngestionError, DbUnavailableError
from app.domain.zone import Zone

logger = structlog.get_logger(__name__)

_ACTIVE_STATUSES: Final = (
    RunStatus.PENDING,
    RunStatus.INGESTING,
    RunStatus.ANALYZING,
    RunStatus.RECOVERING,
)
_ACTIVE_STATUS_VALUES: Final = [s.value for s in _ACTIVE_STATUSES]

_CHECK_ACTIVE_RUNS: Final = "SELECT 1 FROM analysis_runs WHERE status = ANY(%s) LIMIT 1"
_GET_ZONE_HASH: Final = """
    SELECT md5(
        string_agg(name || lat::text || lon::text || radius_m::text, ',' ORDER BY name, lat, lon)
    )
    FROM school_zones
"""

_LOCK_ZONES_TABLE: Final = "LOCK TABLE school_zones IN ACCESS EXCLUSIVE MODE"
_DELETE_ALL_ZONES: Final = "DELETE FROM school_zones"

_COPY_ZONES: Final = "COPY school_zones (name, lat, lon, radius_m, geom) FROM STDIN"


def get_current_zone_hash(conn: Connection) -> str:
    try:
        row = conn.execute(_GET_ZONE_HASH).fetchone()
    except OperationalError as exc:
        raise DbUnavailableError() from exc
    except DatabaseError as exc:
        raise DataIngestionError(str(exc)) from exc
    return row[0] if row and row[0] is not None else ""


def replace_all(conn: Connection, *, zones: list[Zone]) -> int:
    try:
        with conn.transaction():
            conn.execute(_LOCK_ZONES_TABLE)
            row = conn.execute(_CHECK_ACTIVE_RUNS, (_ACTIVE_STATUS_VALUES,)).fetchone()
            if row is not None:
                raise AnalysisInProgressError()
            conn.execute(_DELETE_ALL_ZONES)
            inserted = _copy_zones(conn, zones=zones)
        logger.info("zones_replaced", count=inserted)
        return inserted
    except (AnalysisInProgressError, DataIngestionError, DbUnavailableError):
        raise
    except OperationalError as exc:
        raise DbUnavailableError() from exc
    except DatabaseError as exc:
        raise DataIngestionError(str(exc)) from exc


_QUERY_ZONE_HITS: Final = """
    SELECT p.trip_id, p.ts, sz.name AS zone_name
    FROM unnest(%(lats)s, %(lons)s, %(trip_ids)s, %(tss)s) AS p(lat, lon, trip_id, ts)
    JOIN school_zones sz
      ON ST_DWithin(
           sz.geom,
           ST_SetSRID(ST_MakePoint(p.lon, p.lat), 4326)::geography,
           sz.radius_m
         )
"""

_ZONE_HITS_SCHEMA: Final = {
    "trip_id": pl.Int64,
    "ts": pl.Int64,
    "zone_name": pl.String,
}


def query_zone_hits(df: pl.DataFrame, conn: Connection, *, chunk_size: int = 10000) -> pl.DataFrame:
    with_coords = df.filter(pl.col("lat").is_not_null() & pl.col("lon").is_not_null())
    if with_coords.is_empty():
        return pl.DataFrame(schema=_ZONE_HITS_SCHEMA)

    all_rows: list[tuple[int, int, str]] = []
    n = len(with_coords)
    for start in range(0, n, chunk_size):
        chunk = with_coords.slice(start, chunk_size)
        try:
            rows = conn.execute(
                _QUERY_ZONE_HITS,
                {
                    "lats": chunk["lat"].to_list(),
                    "lons": chunk["lon"].to_list(),
                    "trip_ids": chunk["trip_id"].to_list(),
                    "tss": chunk["ts"].to_list(),
                },
            ).fetchall()
        except OperationalError as exc:
            raise DbUnavailableError() from exc
        except DatabaseError as exc:
            raise DataIngestionError(str(exc)) from exc
        all_rows.extend(rows)

    if not all_rows:
        return pl.DataFrame(schema=_ZONE_HITS_SCHEMA)

    return pl.DataFrame(
        {
            "trip_id": [r[0] for r in all_rows],
            "ts": [r[1] for r in all_rows],
            "zone_name": [r[2] for r in all_rows],
        },
        schema=_ZONE_HITS_SCHEMA,
    )


def _copy_zones(conn: Connection, *, zones: list[Zone]) -> int:
    if not zones:
        return 0
    inserted = 0
    with conn.cursor() as cur, cur.copy(_COPY_ZONES) as copy:
        for z in zones:
            for name in z.names:
                geom = f"SRID=4326;POINT({z.lon} {z.lat})"
                copy.write_row((name, z.lat, z.lon, z.radius_m, geom))
                inserted += 1
    return inserted
