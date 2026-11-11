from collections.abc import AsyncIterator
from typing import Annotated, cast

from fastapi import APIRouter, BackgroundTasks, Depends, UploadFile

from app.application import analyze_service
from app.application.dto.analyze_dto import AcceptedResponse
from app.core.config import Settings, get_settings
from app.presentation.deps import ParamsDep, SessionDep

router = APIRouter()

SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.post("/analyze", response_model=AcceptedResponse, status_code=202)
async def analyze(
    background_tasks: BackgroundTasks,
    session: SessionDep,
    params: ParamsDep,
    settings: SettingsDep,
    file: UploadFile | None = None,
    vehicle_id: str | None = None,
) -> AcceptedResponse:
    return await analyze_service.accept(
        stream=cast(AsyncIterator[bytes] | None, file),
        vehicle_id_query=vehicle_id,
        background_tasks=background_tasks,
        session=session,
        params=params,
        storage_dir=settings.raw_storage_dir,
        default_log_path=settings.default_log_path,
        max_upload_mb=settings.max_upload_mb,
        db_config=settings,
    )
