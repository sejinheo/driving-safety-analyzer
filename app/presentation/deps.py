from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

import psycopg
import psycopg_pool
from fastapi import Depends
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.domain.params import AnalysisParams
from app.infra.persistence.database import build_engine, build_session_factory


def _psycopg_dsn(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://")


@lru_cache
def _get_pool(database_url: str, min_size: int, max_size: int) -> psycopg_pool.ConnectionPool:
    return psycopg_pool.ConnectionPool(
        _psycopg_dsn(database_url),
        min_size=min_size,
        max_size=max_size,
        open=True,
    )


@lru_cache
def _get_session_factory(database_url: str) -> sessionmaker[Session]:
    engine = build_engine(database_url)
    return build_session_factory(engine)


def get_conn(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Iterator[psycopg.Connection]:
    pool = _get_pool(settings.database_url, settings.db_pool_min_size, settings.db_pool_max_size)
    with pool.connection() as conn:
        yield conn


def get_session(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Iterator[Session]:
    factory = _get_session_factory(settings.database_url)
    with factory() as session:
        yield session


def get_params(settings: Annotated[Settings, Depends(get_settings)]) -> AnalysisParams:
    return settings.to_analysis_params()


ConnDep = Annotated[psycopg.Connection, Depends(get_conn)]
SessionDep = Annotated[Session, Depends(get_session)]
ParamsDep = Annotated[AnalysisParams, Depends(get_params)]
