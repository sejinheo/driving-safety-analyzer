import asyncio
import hashlib
from collections.abc import AsyncIterator
from dataclasses import asdict
from pathlib import Path
from typing import cast

import polars as pl
import structlog
from psycopg import Connection
from sqlalchemy.orm import Session

from app.application._protocols import BackgroundTasks, DbConfig
from app.application.dto.analyze_dto import AcceptedResponse
from app.domain.enums import RunStatus
from app.domain.exceptions import EmptyLogFileError
from app.domain.params import AnalysisParams
from app.domain.pipeline import (
    aggregation,
    cleansing,
    events,
    interpolation,
    normalize,
    segmentation,
)
from app.infra.parsing.json_stream import iter_chunks
from app.infra.persistence import result_repository, run_repository, staging_repository
from app.infra.persistence.database import get_pool, get_session_factory
from app.infra.persistence.zone_repository import query_zone_hits
from app.infra.storage.raw_file_store import save_upload_and_hash

logger = structlog.get_logger(__name__)


async def accept(
    *,
    stream: AsyncIterator[bytes] | None,
    vehicle_id_query: str | None,
    background_tasks: BackgroundTasks,
    session: Session,
    params: AnalysisParams,
    storage_dir: Path,
    default_log_path: Path,
    max_upload_mb: int,
    db_config: DbConfig,
) -> AcceptedResponse:
    if stream is None:
        file_path = default_log_path
        if file_path.stat().st_size == 0:
            raise EmptyLogFileError()
        sha256 = await asyncio.to_thread(_hash_file, file_path)
    else:
        file_path, sha256 = await save_upload_and_hash(
            stream,
            storage_dir,
            size_limit=max_upload_mb * 1024 * 1024,
        )

    vehicle_id_default = vehicle_id_query if vehicle_id_query is not None else "UNKNOWN"

    run = await asyncio.to_thread(
        run_repository.create_run,
        session,
        file_hash=sha256,
        file_path=str(file_path),
        params=asdict(params),
        vehicle_id_default=vehicle_id_default,
    )
    await asyncio.to_thread(session.commit)

    if run.status == RunStatus.COMPLETED:
        return AcceptedResponse(run_id=run.id, status=RunStatus(run.status))

    background_tasks.add_task(_run_analysis, run.id, file_path, params, db_config)
    return AcceptedResponse(run_id=run.id, status=RunStatus.PENDING)


def _run_analysis(
    run_id: int,
    file_path: Path,
    params: AnalysisParams,
    db_config: DbConfig,
) -> None:
    pool = get_pool(db_config.database_url, db_config.db_pool_min_size, db_config.db_pool_max_size)
    factory = get_session_factory(db_config.database_url)

    with factory() as session, pool.connection() as conn:
        try:
            _ingest(run_id=run_id, file_path=file_path, conn=conn, session=session, params=params)
            _analyze(run_id=run_id, conn=conn, session=session, params=params)
        except Exception as exc:
            logger.exception("analysis_failed", run_id=run_id, error=str(exc))
            try:
                session.rollback()
                run_repository.set_status(
                    session, run_id=run_id, status=RunStatus.FAILED, error_message=str(exc)
                )
                session.commit()
            except Exception:
                logger.exception("failed_to_mark_run_failed", run_id=run_id)
                raise


def _ingest(
    *,
    run_id: int,
    file_path: Path,
    conn: Connection,
    session: Session,
    params: AnalysisParams,
) -> None:
    run_repository.set_status(session, run_id=run_id, status=RunStatus.INGESTING)
    session.commit()

    run = run_repository.get_checkpoint(session, run_id=run_id)
    skip = run.ingest_next_index or 0
    total = 0
    rejected_total = 0

    for raw_chunk, raw_rejected in iter_chunks(file_path, params.read_chunk_size, skip=skip):
        source_offset = skip + total

        df = pl.DataFrame(
            {
                "vehicle_id": [r.get("vehicle_id") for r in raw_chunk],
                "ts_raw": [r.get("ts") for r in raw_chunk],
                "speed_raw": [r.get("speed") for r in raw_chunk],
                "lat_raw": [r.get("lat") for r in raw_chunk],
                "lon_raw": [r.get("lon") for r in raw_chunk],
            },
            schema={
                "vehicle_id": pl.String,
                "ts_raw": pl.String,
                "speed_raw": pl.String,
                "lat_raw": pl.String,
                "lon_raw": pl.String,
            },
        )
        clean, rejected_df = normalize.normalize(df, params)

        records = (
            clean.with_columns(
                (pl.lit(source_offset) + pl.int_range(pl.len())).alias("source_index")
            )
            .select(
                "source_index",
                "vehicle_id",
                "ts",
                "speed",
                "lat",
                "lon",
                "cell_key",
                "speed_invalid",
                "speed_out_of_range",
                "gps_swapped",
                "gps_invalid",
            )
            .to_dicts()
        )

        rejected: list[tuple[int, dict[str, object], str]] = [
            (source_offset + len(raw_chunk) + i, cast(dict[str, object], r), "NOT_OBJECT")
            for i, (_, r) in enumerate(raw_rejected)
        ] + [
            (source_offset + i, {"reason": str(row["reason"])}, str(row["reason"]))
            for i, row in enumerate(rejected_df.to_dicts())
        ]

        total += len(raw_chunk) + len(raw_rejected)
        rejected_total += len(raw_rejected) + len(rejected_df)

        staging_repository.save_chunk(
            conn,
            run_id=run_id,
            records=records,
            rejected=rejected,
            ingest_next_index=skip + total,
        )

    run_repository.set_status(session, run_id=run_id, status=RunStatus.ANALYZING)
    session.commit()
    logger.info("ingest_completed", run_id=run_id, total=total, rejected=rejected_total)


def _analyze(
    *,
    run_id: int,
    conn: Connection,
    session: Session,
    params: AnalysisParams,
) -> None:
    run = run_repository.get_checkpoint(session, run_id=run_id)
    last_vehicle = run.analyze_last_vehicle or ""
    last_ts = run.analyze_last_ts or 0

    carry: pl.DataFrame | None = None
    trips_frames: list[pl.DataFrame] = []
    points_frames: list[pl.DataFrame] = []
    events_frames: list[pl.DataFrame] = []
    buf_points = 0
    total_trips = 0
    total_events = 0

    for chunk_df in staging_repository.iter_analyze_chunks(
        conn,
        run_id=run_id,
        last_vehicle=last_vehicle,
        last_ts=last_ts,
        chunk_size=params.read_chunk_size,
    ):
        buffer = pl.concat([carry, chunk_df]) if carry is not None else chunk_df
        buffer, _ = cleansing.merge_duplicates(buffer)
        buffer = segmentation.assign_trip_ids(buffer, params)
        completed, carry = segmentation.split_completed(buffer)

        if completed.is_empty():
            continue

        all_events, trips_df = _process_df(completed, conn, params)
        trips_frames.append(trips_df.with_columns(pl.lit(run_id).alias("run_id")))
        points_frames.append(completed)
        events_frames.append(all_events)
        buf_points += len(completed)

        if buf_points >= params.write_batch_points:
            flushed_trips, flushed_events = _flush(
                conn,
                run_id=run_id,
                trips_frames=trips_frames,
                points_frames=points_frames,
                events_frames=events_frames,
            )
            total_trips += flushed_trips
            total_events += flushed_events
            trips_frames, points_frames, events_frames, buf_points = [], [], [], 0

    if carry is not None and not carry.is_empty():
        carry = segmentation.assign_trip_ids(carry, params)
        all_events, trips_df = _process_df(carry, conn, params)
        trips_frames.append(trips_df.with_columns(pl.lit(run_id).alias("run_id")))
        points_frames.append(carry)
        events_frames.append(all_events)

    if trips_frames:
        flushed_trips, flushed_events = _flush(
            conn,
            run_id=run_id,
            trips_frames=trips_frames,
            points_frames=points_frames,
            events_frames=events_frames,
        )
        total_trips += flushed_trips
        total_events += flushed_events

    run_repository.complete_run(
        session, run_id=run_id, report={}, trip_count=total_trips, event_count=total_events
    )
    session.commit()
    logger.info("analysis_completed", run_id=run_id, trips=total_trips, events=total_events)


def _process_df(
    df: pl.DataFrame,
    conn: Connection,
    params: AnalysisParams,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    df = cleansing.remove_speed_spikes(df, params)
    df = cleansing.remove_gps_teleports(df, params)
    df = interpolation.interpolate_values(df, params)
    df = interpolation.interpolate_rows(df, params)

    harsh = events.detect_harsh_events(df, params)
    zone_hits = query_zone_hits(df, conn)
    school = events.detect_school_zone_events(df, zone_hits, params)
    has_events = not harsh.is_empty() or not school.is_empty()
    all_events = pl.concat([harsh, school]) if has_events else pl.DataFrame(schema=harsh.schema)

    trips_df = aggregation.aggregate_trips(df, all_events)
    return all_events, trips_df


def _flush(
    conn: Connection,
    *,
    run_id: int,
    trips_frames: list[pl.DataFrame],
    points_frames: list[pl.DataFrame],
    events_frames: list[pl.DataFrame],
) -> tuple[int, int]:
    trips = pl.concat(trips_frames).to_dicts()
    if not trips:
        return 0, 0

    points = pl.concat(points_frames).to_dicts()
    ev_list = pl.concat(events_frames).to_dicts()

    last = trips[-1]
    result_repository.save_trips_batch(
        conn,
        run_id=run_id,
        trips=trips,
        points=points,
        events=ev_list,
        last_vehicle=str(last["vehicle_id"]),
        last_ts=cast(int, last["end_ts"]),
    )
    return len(trips), len(ev_list)


def _hash_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()
