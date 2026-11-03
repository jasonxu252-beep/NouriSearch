"""Application settings, read from the environment and an optional .env file."""

from functools import lru_cache
from typing import Literal, Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_PASSWORD = "nourisearch_dev"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NOURISEARCH_",
        env_file=(".env", "../.env"),
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_format: Literal["console", "json"] = "console"
    database_url: str = (
        f"postgresql+psycopg://nourisearch:{DEV_PASSWORD}@localhost:5433/nourisearch"
    )
    database_pool_size: int = 5

    @model_validator(mode="after")
    def reject_development_password_in_production(self) -> Self:
        if self.environment == "production" and DEV_PASSWORD in self.database_url:
            raise ValueError("Production cannot use the development database password.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
