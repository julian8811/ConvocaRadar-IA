from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


def _connect_args(url: str) -> dict[str, object]:
    # SEC-RENDER-STARTUP: psycopg3 caches prepared statements per
    # connection. With SQLAlchemy's connection pool, a previously-used
    # connection that still has a prepared statement in PG's session
    # can collide with a new checkout that uses the same statement
    # name ("_pg3_0"). Disabling prepared statements here avoids the
    # "DuplicatePreparedStatement" error on Render's free tier where
    # connections cycle through a small pool. Performance cost is
    # negligible for this app's workload.
    if url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {"prepare_threshold": None}


settings = get_settings()
engine = create_engine(settings.database_url, connect_args=_connect_args(settings.database_url))
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_all() -> None:
    from app import models  # noqa: F401

    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(bind=engine)
