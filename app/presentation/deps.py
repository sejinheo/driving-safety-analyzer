from collections.abc import Iterator
from typing import TYPE_CHECKING, Annotated

import psycopg
import psycopg_pool
from fastapi import Depends, Request
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.domain.params import AnalysisParams

if TYPE_CHECKING:
    from app.application._protocols import BackgroundTasks


def get_pool(request: Request) -> psycopg_pool.ConnectionPool:
    return request.app.state.pool


def get_analysis_pool(request: Request) -> psycopg_pool.ConnectionPool:
    return request.app.state.analysis_pool


def get_session_factory(request: Request) -> sessionmaker[Session]:
    return request.app.state.session_factory


def get_bg_tasks(request: Request) -> "BackgroundTasks":
    return request.app.state.bg_tasks


def get_conn(
    pool: Annotated[psycopg_pool.ConnectionPool, Depends(get_pool)],
) -> Iterator[psycopg.Connection]:
    with pool.connection() as conn:
        yield conn


def get_session(
    factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> Iterator[Session]:
    with factory() as session:
        yield session


def get_params(settings: Annotated[Settings, Depends(get_settings)]) -> AnalysisParams:
    return settings.to_analysis_params()


ConnDep = Annotated[psycopg.Connection, Depends(get_conn)]
SessionDep = Annotated[Session, Depends(get_session)]
ParamsDep = Annotated[AnalysisParams, Depends(get_params)]
BgTasksDep = Annotated["BackgroundTasks", Depends(get_bg_tasks)]
AnalysisPoolDep = Annotated[psycopg_pool.ConnectionPool, Depends(get_analysis_pool)]
