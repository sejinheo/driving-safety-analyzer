from pathlib import Path

import psycopg_pool
import structlog
from sqlalchemy.orm import Session, sessionmaker

from app.application._protocols import BackgroundTasks
from app.application.analyze_service import run_analysis
from app.domain.params import AnalysisParams
from app.infra.persistence import run_repository

logger = structlog.get_logger(__name__)


def recover_incomplete_runs(
    background_tasks: BackgroundTasks,
    *,
    params: AnalysisParams,
    session_factory: sessionmaker[Session],
    pool: psycopg_pool.ConnectionPool,
    claim_limit: int,
    stale_timeout_min: int = 30,
) -> int:
    with session_factory() as session:
        run_repository.fail_stale_runs(session, timeout_min=stale_timeout_min)
        session.commit()

    with session_factory() as session:
        runs = run_repository.claim_incomplete_runs(session, limit=claim_limit)
        session.commit()

    requeued = 0
    for run in runs:
        file_path = Path(run.file_path) if run.file_path else None
        if file_path is None or not file_path.exists():
            logger.warning("recovery_skipped_missing_file", run_id=run.id, file_path=run.file_path)
            continue
        logger.info("recovery_requeuing", run_id=run.id, status=run.status)
        background_tasks.add_task(run_analysis, run.id, file_path, params, pool, session_factory)
        requeued += 1

    if requeued:
        logger.info("recovery_completed", requeued=requeued)
    return requeued
