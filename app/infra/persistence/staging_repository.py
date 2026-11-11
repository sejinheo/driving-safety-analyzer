import structlog
from psycopg import Connection
from psycopg.errors import DatabaseError, OperationalError
from psycopg.types.json import Jsonb

from app.domain.exceptions import DataIngestionError, DbUnavailableError, RunNotFoundError

logger = structlog.get_logger(__name__)

_RAW_RECORDS_COPY = """
    COPY raw_records (
        run_id, source_index, vehicle_id, ts,
        lat, lon, speed, cell_key,
        speed_invalid, speed_out_of_range, gps_swapped, gps_invalid
    ) FROM STDIN
"""

_REJECTED_RECORDS_COPY = """
    COPY rejected_records (run_id, source_index, raw, reason)
    FROM STDIN
"""

_UPDATE_CHECKPOINT = """
    UPDATE analysis_runs
    SET ingest_next_index = %(ingest_next_index)s
    WHERE id = %(run_id)s
"""


def save_chunk(
    conn: Connection,
    *,
    run_id: int,
    records: list[dict[str, object]],
    rejected: list[tuple[int, dict[str, object], str]],
    ingest_next_index: int,
) -> None:
    try:
        with conn.transaction():
            _copy_raw_records(conn, run_id=run_id, records=records)
            _copy_rejected_records(conn, run_id=run_id, rejected=rejected)
            result = conn.execute(
                _UPDATE_CHECKPOINT,
                {"run_id": run_id, "ingest_next_index": ingest_next_index},
            )
            if result.rowcount == 0:
                raise RunNotFoundError(run_id)
        logger.info(
            "chunk_committed",
            run_id=run_id,
            records=len(records),
            rejected=len(rejected),
            ingest_next_index=ingest_next_index,
        )
    except (RunNotFoundError, DataIngestionError, DbUnavailableError):
        raise
    except OperationalError as exc:
        raise DbUnavailableError() from exc
    except DatabaseError as exc:
        raise DataIngestionError(str(exc)) from exc


def _copy_raw_records(
    conn: Connection,
    *,
    run_id: int,
    records: list[dict[str, object]],
) -> None:
    if not records:
        return
    with conn.cursor() as cur, cur.copy(_RAW_RECORDS_COPY) as copy:
        for r in records:
            copy.write_row(
                (
                    run_id,
                    r["source_index"],
                    r["vehicle_id"],
                    r["ts"],
                    r.get("lat"),
                    r.get("lon"),
                    r.get("speed"),
                    r.get("cell_key"),
                    r["speed_invalid"],
                    r["speed_out_of_range"],
                    r["gps_swapped"],
                    r["gps_invalid"],
                )
            )


def _copy_rejected_records(
    conn: Connection,
    *,
    run_id: int,
    rejected: list[tuple[int, dict[str, object], str]],
) -> None:
    if not rejected:
        return
    with conn.cursor() as cur, cur.copy(_REJECTED_RECORDS_COPY) as copy:
        for source_index, raw, reason in rejected:
            copy.write_row((run_id, source_index, Jsonb(raw), reason))
