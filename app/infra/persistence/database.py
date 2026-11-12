import time

import psycopg_pool
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.infra.persistence.models import Base


def _psycopg_dsn(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://")


def build_pool(database_url: str, min_size: int, max_size: int) -> psycopg_pool.ConnectionPool:
    return psycopg_pool.ConnectionPool(
        _psycopg_dsn(database_url),
        min_size=min_size,
        max_size=max_size,
        open=True,
    )


def build_engine(database_url: str) -> Engine:
    return create_engine(database_url, pool_pre_ping=True, pool_size=5, max_overflow=10)


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def create_tables(engine: Engine, *, retries: int = 10, delay: float = 2.0) -> None:
    for attempt in range(1, retries + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
                conn.commit()
            Base.metadata.create_all(engine)
            return
        except OperationalError:
            if attempt == retries:
                raise
            time.sleep(delay)
