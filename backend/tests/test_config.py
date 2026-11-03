import pytest
from pydantic import ValidationError

from app.config import DEV_PASSWORD, Settings


def test_production_rejects_the_development_password() -> None:
    with pytest.raises(ValidationError, match="development database password"):
        Settings(
            environment="production",
            database_url=f"postgresql+psycopg://u:{DEV_PASSWORD}@db/nourisearch",
            _env_file=None,  # type: ignore[call-arg]
        )


def test_production_accepts_a_real_password() -> None:
    settings = Settings(
        environment="production",
        database_url="postgresql+psycopg://u:a-real-secret@db/nourisearch",
        _env_file=None,  # type: ignore[call-arg]
    )
    assert settings.environment == "production"
