"""Liveness and readiness probes."""

from pathlib import Path
from typing import Annotated

import structlog
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.session import get_session

router = APIRouter(prefix="/health", tags=["health"])
log = structlog.get_logger()

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


class LiveResponse(BaseModel):
    status: str


class ReadyResponse(BaseModel):
    status: str
    database: str
    migration: str | None = None
    expected_migration: str | None = None


def _expected_head() -> str | None:
    config = Config(str(ALEMBIC_INI))
    return ScriptDirectory.from_config(config).get_current_head()


@router.get("/live")
def live() -> LiveResponse:
    return LiveResponse(status="ok")


@router.get("/ready", responses={503: {"model": ReadyResponse}})
def ready(response: Response, session: Annotated[Session, Depends(get_session)]) -> ReadyResponse:
    """Ready means the database answers and its schema matches the deployed code."""
    expected = _expected_head()
    try:
        session.execute(text("SELECT 1"))
        current = session.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except SQLAlchemyError as exc:
        log.warning("readiness_check_failed", error=type(exc).__name__)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadyResponse(
            status="unavailable", database="unreachable", expected_migration=expected
        )

    if current != expected:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadyResponse(
            status="unavailable",
            database="ok",
            migration=current,
            expected_migration=expected,
        )
    return ReadyResponse(status="ok", database="ok", migration=current, expected_migration=expected)
