"""How Alembic reaches this application's database.

Two things here are decisions rather than boilerplate.

**The URL comes from the application, not from `alembic.ini`.** `orderorder.config` already decides
which database is in use, from `DATABASE_URL` and the data directory; writing that down a second time
in an ini file gives you two answers to one question, and the way that fails is quiet — a migration
run against the developer's SQLite while everyone believes it reached production.

**`render_as_batch` is on.** SQLite cannot `ALTER` a column, and this deployment's corpus is a 1.2 GB
SQLite file (`docs/DEPLOYMENT.md` §2.4). Batch mode makes Alembic do what SQLite requires by hand —
build the new table, copy, swap — so that the same migration script works on both backends. Without
it, the first migration that alters anything works on Postgres in development and fails on the file
that actually holds the corpus.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

from orderorder.config import get_settings
from orderorder.db.models import Base

config = context.config

# What `--autogenerate` compares the database against.
target_metadata = Base.metadata


def _url() -> str:
    return config.get_main_option("sqlalchemy.url") or get_settings().db_url


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it, for a reviewer or a DBA who wants to read it first."""
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
