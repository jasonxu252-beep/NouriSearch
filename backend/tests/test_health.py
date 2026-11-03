from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.main import create_app


def client_for(engine: Engine) -> TestClient:
    app: FastAPI = create_app()

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    return TestClient(app)


def test_live_needs_no_database() -> None:
    response = TestClient(create_app()).get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_responses_carry_a_request_id() -> None:
    response = TestClient(create_app()).get("/health/live", headers={"x-request-id": "abc123"})
    assert response.headers["x-request-id"] == "abc123"


def test_unknown_routes_use_the_shared_error_shape() -> None:
    response = TestClient(create_app()).get("/does-not-exist")
    assert response.status_code == 404
    assert response.json() == {"code": "http_404", "message": "Not Found"}


@pytest.mark.integration
def test_ready_when_database_matches_code(engine: Engine) -> None:
    response = client_for(engine).get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["migration"] == body["expected_migration"]


@pytest.mark.integration
def test_not_ready_when_migrations_are_behind(engine: Engine) -> None:
    with engine.begin() as connection:
        real = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        connection.execute(text("UPDATE alembic_version SET version_num = 'stale'"))
    try:
        response = client_for(engine).get("/health/ready")
        assert response.status_code == 503
        assert response.json()["migration"] == "stale"
    finally:
        with engine.begin() as connection:
            connection.execute(text("UPDATE alembic_version SET version_num = :v"), {"v": real})


def test_not_ready_when_database_is_unreachable() -> None:
    unreachable = create_engine(
        "postgresql+psycopg://nobody:nothing@localhost:1/none",
        connect_args={"connect_timeout": 1},
    )
    response = client_for(unreachable).get("/health/ready")
    assert response.status_code == 503
    assert response.json()["database"] == "unreachable"
