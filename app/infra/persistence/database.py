from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.infra.persistence.models import Base


def build_engine(database_url: str) -> Engine:
    return create_engine(database_url, pool_pre_ping=True, pool_size=5, max_overflow=10)


def create_tables(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)
