from datetime import UTC, datetime
from typing import Any

import structlog
from psycopg.errors import UniqueViolation
from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.domain.enums import RunStatus
from app.domain.exceptions import DbUnavailableError, DuplicateAnalysisError, RunNotFoundError
from app.infra.persistence.models import AnalysisRun

logger = structlog.get_logger(__name__)


def create_run(
    session: Session,
    *,
    file_hash: str,
    file_path: str,
    params: dict[str, Any],
    vehicle_id_default: str,
) -> AnalysisRun:
    try:
        existing = get_run_for_update(session, file_hash=file_hash)
        if existing is not None:
            if existing.status != RunStatus.FAILED:
                raise DuplicateAnalysisError(file_hash)
            logger.info("reusing_failed_run", run_id=existing.id, file_hash=file_hash)
            return existing

        run = AnalysisRun(
            file_hash=file_hash,
            file_path=file_path,
            params=params,
            status=RunStatus.PENDING,
            vehicle_id_default=vehicle_id_default,
            created_at=datetime.now(UTC),
        )
        session.add(run)
        session.flush()
        logger.info("run_created", file_hash=file_hash, run_id=run.id)
        return run
    except (DuplicateAnalysisError, RunNotFoundError, DbUnavailableError):
        raise
    except Exception as exc:
        if _is_unique_violation(exc):
            raise DuplicateAnalysisError(file_hash) from exc
        if isinstance(exc, OperationalError):
            raise DbUnavailableError() from exc
        raise


def get_run_for_update(session: Session, *, file_hash: str) -> AnalysisRun | None:
    try:
        stmt = select(AnalysisRun).where(AnalysisRun.file_hash == file_hash).with_for_update()
        return session.execute(stmt).scalar_one_or_none()
    except OperationalError as exc:
        raise DbUnavailableError() from exc


def set_status(
    session: Session,
    *,
    run_id: int,
    status: RunStatus,
    error_message: str | None = None,
) -> None:
    values: dict[str, Any] = {"status": status}
    if status == RunStatus.FAILED:
        values["finished_at"] = datetime.now(UTC)
    if error_message is not None:
        values["error_message"] = error_message

    try:
        session.execute(update(AnalysisRun).where(AnalysisRun.id == run_id).values(**values))
        logger.info("run_status_changed", run_id=run_id, status=status)
    except OperationalError as exc:
        raise DbUnavailableError() from exc


def update_ingest_checkpoint(
    session: Session,
    *,
    run_id: int,
    ingest_next_index: int,
    total_records: int | None = None,
    rejected_records: int | None = None,
) -> None:
    values: dict[str, Any] = {"ingest_next_index": ingest_next_index}
    if total_records is not None:
        values["total_records"] = total_records
    if rejected_records is not None:
        values["rejected_records"] = rejected_records

    try:
        session.execute(update(AnalysisRun).where(AnalysisRun.id == run_id).values(**values))
    except OperationalError as exc:
        raise DbUnavailableError() from exc


def update_analyze_checkpoint(
    session: Session,
    *,
    run_id: int,
    last_vehicle: str,
    last_ts: int,
) -> None:
    try:
        session.execute(
            update(AnalysisRun)
            .where(AnalysisRun.id == run_id)
            .values(analyze_last_vehicle=last_vehicle, analyze_last_ts=last_ts)
        )
    except OperationalError as exc:
        raise DbUnavailableError() from exc


def get_checkpoint(session: Session, *, run_id: int) -> AnalysisRun:
    try:
        stmt = select(AnalysisRun).where(AnalysisRun.id == run_id)
        run = session.execute(stmt).scalar_one_or_none()
    except OperationalError as exc:
        raise DbUnavailableError() from exc

    if run is None:
        raise RunNotFoundError(run_id)
    return run


def complete_run(
    session: Session,
    *,
    run_id: int,
    report: dict[str, Any],
    trip_count: int,
    event_count: int,
) -> None:
    try:
        session.execute(
            update(AnalysisRun)
            .where(AnalysisRun.id == run_id)
            .values(
                status=RunStatus.COMPLETED,
                finished_at=datetime.now(UTC),
                report=report,
                trip_count=trip_count,
                event_count=event_count,
            )
        )
        logger.info("run_completed", run_id=run_id, trip_count=trip_count, event_count=event_count)
    except OperationalError as exc:
        raise DbUnavailableError() from exc


def _is_unique_violation(exc: Exception) -> bool:
    return isinstance(exc.__cause__, UniqueViolation)
