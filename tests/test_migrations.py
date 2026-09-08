"""That a deployed database can change shape without being rebuilt.

`init_db` calls `create_all`, which creates what is missing and never alters what is there. That is
the right tool for an empty database and for the in-memory one this suite builds, and it is not a way
to change a schema: the first column this application wants to widen, after a pilot has 1.2 GB of
corpus in a SQLite file, would otherwise be a manual job on the file holding the corpus.
`docs/DEPLOYMENT.md` §2.5 calls wiring Alembic the prerequisite for a second release.

The property that keeps it honest is the first test here. A baseline generated once and then left
behind while the models move on is worse than no baseline at all, because it looks like a migration
path and is not one: the deployment would be at a schema no version of this code expects. So the
suite asks Alembic itself whether a freshly migrated database still matches the models, which is the
same comparison `--autogenerate` makes, and fails when someone adds a column without a migration.
"""

from __future__ import annotations

import sqlalchemy as sa

from orderorder.db.models import Base
from orderorder.db.session import _alembic_config, current_revision, upgrade_db


def _url(tmp_path, name: str) -> str:
    return f"sqlite:///{(tmp_path / name).as_posix()}"


def _upgraded(tmp_path, name: str) -> str:
    """A database built the way a deployment builds one: by running the migrations."""
    url = _url(tmp_path, name)
    upgrade_db(url)
    return url


def test_the_migrations_still_describe_the_models(tmp_path) -> None:
    """The drift check. Add a column to a model without a migration and this is what fails."""
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext

    url = _upgraded(tmp_path, "drift.sqlite3")
    engine = sa.create_engine(url)
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        differences = compare_metadata(context, Base.metadata)

    assert differences == [], (
        "the migrations and the models disagree; generate a revision with\n"
        "    uv run alembic revision --autogenerate -m '<what changed>'"
    )


def test_migrating_builds_what_create_all_would_have_built(tmp_path) -> None:
    """Same tables, same columns. The baseline was generated from the models and must still say so."""
    migrated = sa.create_engine(_upgraded(tmp_path, "migrated.sqlite3"))
    created = sa.create_engine(_url(tmp_path, "created.sqlite3"))
    Base.metadata.create_all(created)

    def shape(engine) -> dict[str, set[str]]:
        inspector = sa.inspect(engine)
        return {
            table: {column["name"] for column in inspector.get_columns(table)}
            for table in inspector.get_table_names()
            # Alembic's own bookkeeping is the one table `create_all` has no reason to know about.
            if table != "alembic_version"
        }

    assert shape(migrated) == shape(created)
    assert len(shape(migrated)) == len(Base.metadata.tables)


def test_a_fresh_database_records_where_it_stands(tmp_path) -> None:
    url = _upgraded(tmp_path, "stamped.sqlite3")
    assert current_revision(url) is not None


def test_migrating_twice_changes_nothing(tmp_path) -> None:
    """A deployment runs this on every start; the second run must be a no-op, not an error."""
    url = _upgraded(tmp_path, "twice.sqlite3")
    at = current_revision(url)
    upgrade_db(url)
    assert current_revision(url) == at


def test_stamping_claims_a_database_that_already_has_its_tables(tmp_path) -> None:
    """The path for the ingested corpus: the tables exist, so the baseline must not be run at them."""
    from alembic import command

    url = _url(tmp_path, "corpus.sqlite3")
    engine = sa.create_engine(url)
    Base.metadata.create_all(engine)  # as `init_db` did, before migrations existed
    assert current_revision(url) is None, "an unstamped database looks like it has had nothing applied"

    command.stamp(_alembic_config(url), "head")
    assert current_revision(url) is not None

    # And now the ordinary path is a no-op rather than an attempt to create tables that are there.
    upgrade_db(url)
    inspector = sa.inspect(engine)
    assert "judgment" in inspector.get_table_names()
    assert "paragraph" in inspector.get_table_names()


def test_the_migrations_ship_inside_the_package(tmp_path) -> None:
    """A migration you cannot run on the box you deployed to is not a migration.

    `alembic.ini` at the repository root is not in the wheel and not in the container, so the
    configuration is built in code and points at the package's own directory.
    """
    from pathlib import Path

    import orderorder

    location = Path(_alembic_config(_url(tmp_path, "x.sqlite3")).get_main_option("script_location"))
    assert location.is_dir()
    assert location.is_relative_to(Path(orderorder.__file__).parent)
    assert (location / "env.py").exists()
    assert list((location / "versions").glob("*.py")), "a baseline revision has to be there"
