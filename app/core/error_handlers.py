import structlog
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from structlog.contextvars import get_contextvars

from app.domain.exceptions import AppError

logger = structlog.get_logger(__name__)


def _request_id() -> str:
    return get_contextvars().get("request_id", "")


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.code,
            "message": exc.message,
            "detail": exc.detail,
            "request_id": _request_id(),
        },
    )


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "code": "VALIDATION_ERROR",
            "message": "Request validation failed",
            "detail": exc.errors(),
            "request_id": _request_id(),
        },
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_error", request_id=_request_id())
    return JSONResponse(
        status_code=500,
        content={
            "code": "INTERNAL_ERROR",
            "message": "An internal error occurred",
            "detail": {},
            "request_id": _request_id(),
        },
    )
