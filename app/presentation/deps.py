from collections.abc import Iterator
from typing import Annotated

import psycopg
from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.domain.params import AnalysisParams
from app.infra.persistence.database import get_pool, get_session_factory


def get_conn(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Iterator[psycopg.Connection]:
    pool = get_pool(settings.database_url, settings.db_pool_min_size, settings.db_pool_max_size)
    with pool.connection() as conn:
        yield conn


def get_session(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Iterator[Session]:
    factory = get_session_factory(settings.database_url)
    with factory() as session:
        yield session


def get_params(settings: Annotated[Settings, Depends(get_settings)]) -> AnalysisParams:
    return settings.to_analysis_params()


ConnDep = Annotated[psycopg.Connection, Depends(get_conn)]
SessionDep = Annotated[Session, Depends(get_session)]
ParamsDep = Annotated[AnalysisParams, Depends(get_params)]
