import asyncio
from collections.abc import AsyncIterator
from dataclasses import asdict
from pathlib import Path
from typing import cast

import polars as pl
import psycopg_pool
import structlog
from psycopg import Connection
from sqlalchemy.orm import Session, sessionmaker

from app.application._protocols import BackgroundTasks, CancelEvent
from app.application.dto.analyze_dto import AcceptedResponse
from app.domain.enums import RunStatus
from app.domain.exceptions import EmptyLogFileError, MissingFileError
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
from app.infra.persistence.zone_repository import get_current_zone_hash, query_zone_hits
from app.infra.storage.raw_file_store import save_upload_and_hash

logger = structlog.get_logger(__name__)


async def accept(
    *,
    stream: AsyncIterator[bytes] | None,
    vehicle_id_query: str | None,
    background_tasks: BackgroundTasks,
    session: Session,
    conn: Connection,
    pool: psycopg_pool.ConnectionPool,
    session_factory: sessionmaker[Session],
    params: AnalysisParams,
    storage_dir: Path,
    max_upload_mb: int,
) -> AcceptedResponse:
    if stream is None:
        raise MissingFileError()

    file_path, sha256 = await save_upload_and_hash(
        stream,
        storage_dir,
        size_limit=max_upload_mb * 1024 * 1024,
    )
    if file_path.stat().st_size == 0:
        raise EmptyLogFileError()

    vehicle_id_default = vehicle_id_query if vehicle_id_query is not None else "UNKNOWN"
    zone_hash = await asyncio.to_thread(get_current_zone_hash, conn)

    run = await asyncio.to_thread(
        run_repository.create_run,
        session,
        file_hash=sha256,
        zone_hash=zone_hash,
        file_path=str(file_path),
        params=asdict(params),
        vehicle_id_default=vehicle_id_default,
    )
    await asyncio.to_thread(session.commit)

    if run.status == RunStatus.COMPLETED:
        return AcceptedResponse(run_id=run.id, status=RunStatus(run.status))

    background_tasks.add_task(
        run_analysis, run.id, file_path, params, pool, session_factory, vehicle_id_default
    )
    return AcceptedResponse(run_id=run.id, status=RunStatus.PENDING)


def run_analysis(
    run_id: int,
    file_path: Path,
    params: AnalysisParams,
    pool: psycopg_pool.ConnectionPool,
    session_factory: sessionmaker[Session],
    vehicle_id_default: str = "UNKNOWN",
    cancel_event: CancelEvent | None = None,
) -> None:
    with session_factory() as session, pool.connection() as conn:
        conn.autocommit = True
        try:
            run = run_repository.get_checkpoint(session, run_id=run_id)
            if RunStatus(run.status) != RunStatus.ANALYZING:
                cancelled = _ingest(
                    run_id=run_id,
                    file_path=file_path,
                    conn=conn,
                    session=session,
                    params=params,
                    vehicle_id_default=vehicle_id_default,
                    cancel_event=cancel_event,
                )
                if cancelled:
                    return
            _analyze(
                run_id=run_id,
                conn=conn,
                session=session,
                params=params,
                cancel_event=cancel_event,
            )
        except Exception as exc:
            logger.exception("analysis_failed", run_id=run_id, error=str(exc))
            try:
                with session_factory() as err_session:
                    run_repository.set_status(
                        err_session, run_id=run_id, status=RunStatus.FAILED, error_message=str(exc)
                    )
                    err_session.commit()
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
    vehicle_id_default: str,
    cancel_event: CancelEvent | None = None,
) -> bool:
    run_repository.set_status(session, run_id=run_id, status=RunStatus.INGESTING)
    session.commit()

    run = run_repository.get_checkpoint(session, run_id=run_id)
    skip = run.ingest_next_index or 0
    total = 0
    rejected_total = 0

    def _str(v: object) -> str | None:
        return None if v is None else str(v)

    for raw_chunk, raw_rejected in iter_chunks(file_path, params.read_chunk_size, skip=skip):
        source_offset = skip + total

        df = pl.DataFrame(
            {
                "vehicle_id": [_str(r.get("vehicle_id")) for r in raw_chunk],
                "ts_raw": [
                    _str(v if (v := r.get("timestamp")) is not None else r.get("ts"))
                    for r in raw_chunk
                ],
                "speed_raw": [_str(r.get("speed")) for r in raw_chunk],
                "lat_raw": [
                    _str(v if (v := r.get("gps_lat")) is not None else r.get("lat"))
                    for r in raw_chunk
                ],
                "lon_raw": [
                    _str(v if (v := r.get("gps_lon")) is not None else r.get("lon"))
                    for r in raw_chunk
                ],
            },
            schema={
                "vehicle_id": pl.String,
                "ts_raw": pl.String,
                "speed_raw": pl.String,
                "lat_raw": pl.String,
                "lon_raw": pl.String,
            },
        )
        clean, rejected_df = normalize.normalize(df, params, vehicle_id_default=vehicle_id_default)

        records = (
            clean.with_columns(
                (pl.lit(source_offset) + pl.int_range(pl.len())).alias("source_index"),
            )
            .select(
                "source_index",
                "vehicle_id",
                "ts",
                "speed",
                "lat",
                "lon",
                "speed_invalid",
                "speed_out_of_range",
                "gps_swapped",
                "gps_invalid",
            )
            .to_dicts()
        )

        rejected: list[tuple[int, dict[str, object], str]] = [
            (orig_idx, cast(dict[str, object], {"raw": r}), "NOT_OBJECT")
            for orig_idx, r in raw_rejected
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

        if cancel_event is not None and cancel_event.is_set():
            logger.info("ingest_cancelled", run_id=run_id, ingested=total)
            run_repository.set_status(session, run_id=run_id, status=RunStatus.PENDING)
            session.commit()
            return True

    if total == 0:
        raise EmptyLogFileError()

    run_repository.set_status(session, run_id=run_id, status=RunStatus.ANALYZING)
    session.commit()
    logger.info("ingest_completed", run_id=run_id, total=total, rejected=rejected_total)
    return False


def _analyze(
    *,
    run_id: int,
    conn: Connection,
    session: Session,
    params: AnalysisParams,
    cancel_event: CancelEvent | None = None,
) -> None:
    run = run_repository.get_checkpoint(session, run_id=run_id)
    last_vehicle = run.analyze_last_vehicle or ""
    last_ts = run.analyze_last_ts or 0
    last_source_index = run.analyze_last_source_index or 0

    carry: pl.DataFrame | None = None
    chunk_df: pl.DataFrame | None = None
    trips_frames: list[pl.DataFrame] = []
    points_frames: list[pl.DataFrame] = []
    events_frames: list[pl.DataFrame] = []
    buf_points = 0
    total_trips = 0
    total_events = 0
    trip_id_offset = 0
    cursor_source_index = last_source_index

    for chunk_df in staging_repository.iter_analyze_chunks(
        conn,
        run_id=run_id,
        last_vehicle=last_vehicle,
        last_ts=last_ts,
        last_source_index=last_source_index,
        chunk_size=params.read_chunk_size,
    ):
        cursor_source_index = int(chunk_df["source_index"][-1])
        if carry is not None:
            carry = carry.drop("trip_id").select(chunk_df.columns)
        buffer = pl.concat([carry, chunk_df]) if carry is not None else chunk_df
        buffer, _ = cleansing.merge_duplicates(buffer)
        buffer = buffer.select(chunk_df.columns)
        buffer = segmentation.assign_trip_ids(buffer, params, trip_id_offset=trip_id_offset)
        completed, carry = segmentation.split_completed(buffer)
        if carry is not None and not carry.is_empty():
            trip_id_offset = int(carry["trip_id"][0])

        if not completed.is_empty():
            processed, all_events, trips_df = _process_df(completed, conn, params)
            trips_frames.append(trips_df.with_columns(pl.lit(run_id).alias("run_id")))
            points_frames.append(processed)
            events_frames.append(all_events)
            buf_points += len(completed)

            if buf_points >= params.write_batch_points:
                flushed_trips, flushed_events = _flush(
                    conn,
                    run_id=run_id,
                    trips_frames=trips_frames,
                    points_frames=points_frames,
                    events_frames=events_frames,
                    last_source_index=cursor_source_index,
                )
                total_trips += flushed_trips
                total_events += flushed_events
                trips_frames, points_frames, events_frames, buf_points = [], [], [], 0

        if cancel_event is not None and cancel_event.is_set():
            if trips_frames:
                _flush(
                    conn,
                    run_id=run_id,
                    trips_frames=trips_frames,
                    points_frames=points_frames,
                    events_frames=events_frames,
                    last_source_index=cursor_source_index,
                )
            logger.info("analyze_cancelled", run_id=run_id)
            run_repository.set_status(session, run_id=run_id, status=RunStatus.ANALYZING)
            session.commit()
            return

    if carry is not None and not carry.is_empty() and chunk_df is not None:
        if "trip_id" in carry.columns:
            carry = carry.drop("trip_id").select(chunk_df.columns)
        carry = segmentation.assign_trip_ids(carry, params, trip_id_offset=trip_id_offset)
        processed, all_events, trips_df = _process_df(carry, conn, params)
        trips_frames.append(trips_df.with_columns(pl.lit(run_id).alias("run_id")))
        points_frames.append(processed)
        events_frames.append(all_events)

    if trips_frames:
        flushed_trips, flushed_events = _flush(
            conn,
            run_id=run_id,
            trips_frames=trips_frames,
            points_frames=points_frames,
            events_frames=events_frames,
            last_source_index=cursor_source_index,
        )
        total_trips += flushed_trips
        total_events += flushed_events

    result_repository.complete_run_conn(
        conn, run_id=run_id, report={}, trip_count=total_trips, event_count=total_events
    )
    logger.info("analysis_completed", run_id=run_id, trips=total_trips, events=total_events)


def _process_df(
    df: pl.DataFrame,
    conn: Connection,
    params: AnalysisParams,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    df = cleansing.remove_speed_spikes(df, params)
    df = cleansing.remove_gps_teleports(df, params)
    df = interpolation.interpolate_values(df, params)
    df = interpolation.interpolate_rows(df, params)

    harsh = events.detect_harsh_events(df, params)
    zone_hits = query_zone_hits(df, conn, chunk_size=params.zone_query_chunk_size)
    school = events.detect_school_zone_events(df, zone_hits, params)
    has_events = not harsh.is_empty() or not school.is_empty()
    all_events = pl.concat([harsh, school]) if has_events else pl.DataFrame(schema=harsh.schema)

    trips_df = aggregation.aggregate_trips(df, all_events)
    return df, all_events, trips_df


def _flush(
    conn: Connection,
    *,
    run_id: int,
    trips_frames: list[pl.DataFrame],
    points_frames: list[pl.DataFrame],
    events_frames: list[pl.DataFrame],
    last_source_index: int,
) -> tuple[int, int]:
    trips_raw = pl.concat(trips_frames).to_dicts()
    if not trips_raw:
        return 0, 0

    event_type_keys = aggregation.ALL_EVENT_TYPES
    trips = [
        {
            **{k: v for k, v in t.items() if k not in event_type_keys},
            "event_counts": {k: t[k] for k in event_type_keys if t.get(k, 0) > 0},
        }
        for t in trips_raw
    ]

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
        last_source_index=last_source_index,
    )
    return len(trips), len(ev_list)
