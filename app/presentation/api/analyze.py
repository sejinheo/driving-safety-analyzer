from collections.abc import AsyncIterator
from typing import Annotated, Final

from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy.orm import Session, sessionmaker

from app.application import analyze_service
from app.application.dto.analyze_dto import AcceptedResponse
from app.core.config import Settings, get_settings
from app.presentation.deps import (
    AnalysisPoolDep,
    BgTasksDep,
    ConnDep,
    ParamsDep,
    SessionDep,
    get_session_factory,
)

router = APIRouter()

SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionFactoryDep = Annotated[sessionmaker[Session], Depends(get_session_factory)]

_CHUNK_SIZE: Final = 65536


async def _iter_upload(file: UploadFile) -> AsyncIterator[bytes]:
    while True:
        chunk = await file.read(_CHUNK_SIZE)
        if not chunk:
            break
        yield chunk


@router.post("/analyze", response_model=AcceptedResponse, status_code=202)
async def analyze(
    background_tasks: BgTasksDep,
    session: SessionDep,
    conn: ConnDep,
    analysis_pool: AnalysisPoolDep,
    session_factory: SessionFactoryDep,
    params: ParamsDep,
    settings: SettingsDep,
    file: UploadFile | None = None,
    vehicle_id: str | None = None,
) -> AcceptedResponse:
    return await analyze_service.accept(
        stream=_iter_upload(file) if file is not None else None,
        vehicle_id_query=vehicle_id,
        background_tasks=background_tasks,
        session=session,
        conn=conn,
        pool=analysis_pool,
        session_factory=session_factory,
        params=params,
        storage_dir=settings.raw_storage_dir,
        max_upload_mb=settings.max_upload_mb,
    )
