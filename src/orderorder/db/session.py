"""Engine and session factory. SQLite by default; Postgres when DATABASE_URL says so."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from orderorder.config import get_settings
from orderorder.db.models import Base


@lru_cache
def get_engine(url: str | None = None) -> Engine:
    url = url or get_settings().db_url
    if url.startswith("sqlite"):
        engine = create_engine(url, future=True)

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - trivial
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

        return engine
    return create_engine(url, future=True, pool_pre_ping=True)


def init_db(url: str | None = None) -> Engine:
    """Create any missing tables. For tests and for a first run on an empty database.

    This calls `create_all`, which creates what is not there and **never alters what is**. That is
    fine for an empty database and for the in-memory one the suite builds, and it is not a way to
    change a schema: the first column this application wants to widen after a deployment would need
    doing by hand. `orderorder migrate` is the way to move an existing database, and
    `alembic_version` is how it knows where that database already stands.

    A database created here is unstamped, so `migrate` would try to build tables that exist. Callers
    that create a database they intend to keep should follow with `stamp_head`; `orderorder init-db`
    does.
    """
    engine = get_engine(url)
    Base.metadata.create_all(engine)
    return engine


def _alembic_config(url: str | None = None):
    """Alembic's configuration, pointed at the migrations that ship inside this package.

    Built here rather than read from `alembic.ini` so that it works from an installed wheel and from
    inside the container, where the repository root and its ini file are not present.
    """
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parent.parent / "migrations"))
    config.set_main_option("sqlalchemy.url", url or get_settings().db_url)
    return config


def stamp_head(url: str | None = None) -> None:
    """Record that this database is at the latest revision, without running anything.

    For a database whose tables already exist -- the 1.2 GB corpus, or anything `init_db` built
    before migrations existed. Running the baseline against it would try to create tables it already
    has; stamping says "this schema is current" and lets the next real migration apply cleanly.
    """
    from alembic import command

    command.stamp(_alembic_config(url), "head")


def upgrade_db(url: str | None = None, revision: str = "head") -> None:
    """Apply outstanding migrations. The way a deployed database changes shape."""
    from alembic import command

    command.upgrade(_alembic_config(url), revision)


def current_revision(url: str | None = None) -> str | None:
    """The revision this database is stamped at, or None if it has never been stamped."""
    from alembic.runtime.migration import MigrationContext

    engine = get_engine(url)
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


@contextmanager
def get_session(url: str | None = None) -> Iterator[Session]:
    factory = sessionmaker(bind=get_engine(url), expire_on_commit=False)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
