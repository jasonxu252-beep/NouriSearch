"""Migrations must reproduce the models exactly, and must be reversible."""

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, make_url, text

from app.db import models  # noqa: F401
from app.db.base import Base
from tests.conftest import alembic_config

pytestmark = pytest.mark.integration


@pytest.fixture
def scratch_url(database_url: str) -> Iterator[str]:
    """A separate empty database, so these tests cannot disturb the shared one."""
    url = make_url(database_url)
    name = f"{url.database}_migrations"
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    yield url.set(database=name).render_as_string(hide_password=False)
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()


def test_migrations_produce_exactly_what_the_models_declare(scratch_url: str) -> None:
    command.upgrade(alembic_config(scratch_url), "head")
    engine = create_engine(scratch_url)
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        assert compare_metadata(context, Base.metadata) == []
    engine.dispose()


def test_migrations_can_be_fully_reversed_and_reapplied(scratch_url: str) -> None:
    config = alembic_config(scratch_url)
    command.upgrade(config, "head")
    command.downgrade(config, "base")

    engine = create_engine(scratch_url)
    remaining = set(inspect(engine).get_table_names()) - {"alembic_version"}
    engine.dispose()
    assert remaining == set()

    command.upgrade(config, "head")
