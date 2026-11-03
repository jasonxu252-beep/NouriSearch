"""Shared fixtures. Integration tests run against a real, freshly migrated PostgreSQL database."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, make_url, text
from sqlalchemy.orm import Session

BACKEND_DIR = Path(__file__).resolve().parent.parent

DEFAULT_TEST_URL = (
    "postgresql+psycopg://nourisearch:nourisearch_dev@localhost:5433/nourisearch_test"
)


@pytest.fixture(scope="session")
def database_url() -> str:
    return os.environ.get("NOURISEARCH_TEST_DATABASE_URL", DEFAULT_TEST_URL)


def alembic_config(url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


@pytest.fixture(scope="session")
def engine(database_url: str) -> Iterator[Engine]:
    """Recreates the test database and migrates it, so every run starts clean."""
    url = make_url(database_url)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
        connection.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()

    command.upgrade(alembic_config(database_url), "head")

    test_engine = create_engine(database_url)
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """A session whose work is rolled back, even when the test commits."""
    connection = engine.connect()
    transaction = connection.begin()
    db_session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield db_session
    finally:
        db_session.close()
        transaction.rollback()
        connection.close()
