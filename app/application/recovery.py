from pathlib import Path

import structlog

from app.application._protocols import BackgroundTasks, DbConfig
from app.application.analyze_service import _run_analysis
from app.domain.params import AnalysisParams
from app.infra.persistence import run_repository
from app.infra.persistence.database import get_session_factory

logger = structlog.get_logger(__name__)


def recover_incomplete_runs(
    background_tasks: BackgroundTasks,
    *,
    params: AnalysisParams,
    db_config: DbConfig,
    claim_limit: int,
) -> int:
    factory = get_session_factory(db_config.database_url)

    with factory() as session:
        runs = run_repository.claim_incomplete_runs(session, limit=claim_limit)
        session.commit()

    requeued = 0
    for run in runs:
        file_path = Path(run.file_path) if run.file_path else None
        if file_path is None or not file_path.exists():
            logger.warning("recovery_skipped_missing_file", run_id=run.id, file_path=run.file_path)
            continue
        logger.info("recovery_requeuing", run_id=run.id, status=run.status)
        background_tasks.add_task(_run_analysis, run.id, file_path, params, db_config)
        requeued += 1

    if requeued:
        logger.info("recovery_completed", requeued=requeued)
    return requeued
