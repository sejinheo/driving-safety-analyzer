from fastapi import APIRouter

from app.application.dto.run_dto import RunResponse
from app.application.run_query import get_run as _get_run
from app.presentation.deps import SessionDep

router = APIRouter()


@router.get("/runs/{run_id}", response_model=RunResponse, response_model_exclude_none=True)
def get_run(run_id: int, session: SessionDep) -> RunResponse:
    return _get_run(session, run_id=run_id)
