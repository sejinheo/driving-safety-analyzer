from typing import Final

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
)
_ACTIVE_STATUS_VALUES: Final = [s.value for s in _ACTIVE_STATUSES]

_CHECK_ACTIVE_RUNS: Final = "SELECT 1 FROM analysis_runs WHERE status = ANY(%s) LIMIT 1"

_DELETE_ALL_ZONES: Final = "DELETE FROM school_zones"

_COPY_ZONES: Final = "COPY school_zones (name, lat, lon, radius_m, geom) FROM STDIN"


def replace_all(conn: Connection, *, zones: list[Zone]) -> int:
    try:
        with conn.transaction():
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


def _copy_zones(conn: Connection, *, zones: list[Zone]) -> int:
    if not zones:
        return 0
    with conn.cursor() as cur, cur.copy(_COPY_ZONES) as copy:
        for z in zones:
            for name in z.names:
                copy.write_row(
                    (
                        name,
                        z.lat,
                        z.lon,
                        z.radius_m,
                        f"SRID=4326;POINT({z.lon} {z.lat})",
                    )
                )
    return sum(len(z.names) for z in zones)
