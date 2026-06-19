"""backend/config.py — environment-driven settings for the control plane."""
from __future__ import annotations

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class BackendSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database — SQLite for local dev; set DATABASE_URL to Postgres on Render.
    database_url: str = "sqlite:///./quorum_app.db"

    # Credential encryption (Fernet). Optional in dev; required for remote DBs.
    credential_encryption_key: str = ""

    # Session quotas (control AI/ML credit use).
    max_investigations_per_session: int = 3
    max_followups_per_investigation: int = 2

    # Scope limits.
    max_scope_tables: int = 5
    max_scope_columns: int = 5

    # Band passthrough (the agents read these too).
    band_rest_url: str = ""
    band_ws_url: str = ""
    llm_backend: str = ""

    # CORS (Streamlit origin).
    frontend_origin: str = "*"

    def normalized_database_url(self) -> str:
        """Render/Heroku hand out 'postgres://...'; SQLAlchemy 2 + psycopg wants
        'postgresql+psycopg://...'. Normalize so the same env var works anywhere."""
        url = self.database_url
        if url.startswith("postgres://"):
            url = "postgresql+psycopg://" + url[len("postgres://"):]
        elif url.startswith("postgresql://") and "+psycopg" not in url:
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        return url


@lru_cache
def get_settings() -> BackendSettings:
    return BackendSettings()
