import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import structlog
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.application.recovery import recover_incomplete_runs
from app.core.config import get_settings
from app.core.error_handlers import (
    app_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from app.core.logging import configure_logging
from app.core.middleware import RequestIdMiddleware
from app.domain.exceptions import AppError
from app.infra.persistence.database import (
    build_engine,
    build_pool,
    build_session_factory,
    create_tables,
)
from app.presentation.api import analyze, runs, trips, zones

_STATIC_DIR = Path(__file__).parent.parent / "static"

configure_logging()
logger = structlog.get_logger(__name__)


class _ThreadBackgroundTasks:
    def __init__(self, cancel_event: threading.Event) -> None:
        self._cancel_event = cancel_event
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()

    def add_task(self, func: Callable[..., Any], /, *args: Any, **kwargs: Any) -> None:
        kwargs["cancel_event"] = self._cancel_event
        t = threading.Thread(target=func, args=args, kwargs=kwargs, daemon=False)
        with self._lock:
            self._threads = [th for th in self._threads if th.is_alive()]
            self._threads.append(t)
        t.start()

    def join_all(self) -> None:
        with self._lock:
            threads = list(self._threads)
        for t in threads:
            t.join()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    engine = build_engine(settings.database_url)
    pool = build_pool(settings.database_url, settings.db_pool_min_size, settings.db_pool_max_size)
    analysis_pool = build_pool(
        settings.database_url,
        settings.analysis_pool_min_size,
        settings.analysis_pool_max_size,
    )
    session_factory = build_session_factory(engine)
    cancel_event = threading.Event()
    bg_tasks = _ThreadBackgroundTasks(cancel_event)

    app.state.pool = pool
    app.state.analysis_pool = analysis_pool
    app.state.session_factory = session_factory
    app.state.cancel_event = cancel_event
    app.state.bg_tasks = bg_tasks

    settings.raw_storage_dir.mkdir(parents=True, exist_ok=True)

    try:
        create_tables(engine)
    except Exception:
        logger.exception("create_tables_failed_on_startup")
    try:
        recover_incomplete_runs(
            bg_tasks,
            params=settings.to_analysis_params(),
            session_factory=session_factory,
            pool=analysis_pool,
            claim_limit=settings.recovery_claim_limit,
            stale_timeout_min=settings.stale_run_timeout_min,
        )
    except Exception:
        logger.exception("recovery_failed_on_startup")

    yield

    logger.info("shutdown_signaling_cancel")
    cancel_event.set()
    bg_tasks.join_all()
    logger.info("shutdown_all_analysis_threads_done")
    pool.close()
    analysis_pool.close()
    engine.dispose()


app = FastAPI(lifespan=lifespan)

app.add_middleware(RequestIdMiddleware)

app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
app.add_exception_handler(Exception, unhandled_error_handler)

app.include_router(analyze.router)
app.include_router(runs.router)
app.include_router(trips.router)
app.include_router(zones.router)

app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")
