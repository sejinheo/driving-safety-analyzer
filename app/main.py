import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

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
from app.presentation.api import analyze, runs, trips

configure_logging()
logger = structlog.get_logger(__name__)


class _ThreadBackgroundTasks:
    def add_task(self, func: Callable[..., Any], /, *args: Any, **kwargs: Any) -> None:
        threading.Thread(target=func, args=args, kwargs=kwargs, daemon=True).start()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    try:
        recover_incomplete_runs(
            _ThreadBackgroundTasks(),
            params=settings.to_analysis_params(),
            db_config=settings,
            claim_limit=settings.recovery_claim_limit,
        )
    except Exception:
        logger.exception("recovery_failed_on_startup")
    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(RequestIdMiddleware)

app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
app.add_exception_handler(Exception, unhandled_error_handler)

app.include_router(analyze.router)
app.include_router(runs.router)
app.include_router(trips.router)
