from functools import lru_cache

import psycopg_pool
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.infra.persistence.models import Base


def _psycopg_dsn(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://")


@lru_cache
def get_pool(database_url: str, min_size: int, max_size: int) -> psycopg_pool.ConnectionPool:
    return psycopg_pool.ConnectionPool(
        _psycopg_dsn(database_url),
        min_size=min_size,
        max_size=max_size,
        open=True,
    )


@lru_cache
def get_session_factory(database_url: str) -> sessionmaker[Session]:
    engine = build_engine(database_url)
    return sessionmaker(engine, expire_on_commit=False)


def build_engine(database_url: str) -> Engine:
    return create_engine(database_url, pool_pre_ping=True, pool_size=5, max_overflow=10)


def create_tables(engine: Engine) -> None:
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        conn.commit()
    Base.metadata.create_all(engine)


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)
