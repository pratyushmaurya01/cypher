"""Application-wide configuration loaded from environment variables or .env file.

All other modules must read settings through ``get_settings()`` — never call
``os.getenv()`` directly in route or service code.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed, validated settings for the Cypher application.

    Pydantic reads values from environment variables first, then from a .env
    file in the working directory.  Variable names are case-insensitive.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",          # ignore unknown env vars — keeps things clean
    )

    # ------------------------------------------------------------------ #
    # Database (PostgreSQL / SQLite fallback)
    # ------------------------------------------------------------------ #
    # Defaults to local SQLite file for immediate local dev/testing if PostgreSQL
    # is not configured, or set DATABASE_URL=postgresql://user:pass@localhost:5432/cypher
    database_url: str = "sqlite:///./cypher.db"

    # ------------------------------------------------------------------ #
    # JWT Authentication
    # ------------------------------------------------------------------ #
    jwt_secret_key: str = "cypher-insecure-development-secret-key-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60 * 24  # 24 hours

    # ------------------------------------------------------------------ #
    # Neo4j
    # ------------------------------------------------------------------ #
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password"
    neo4j_database: str = "neo4j"

    # ------------------------------------------------------------------ #
    # Storage & Upload
    # ------------------------------------------------------------------ #
    # Persistent directory where repository snapshots are stored
    storage_dir: str = "./storage/repositories"

    # Maximum allowed size for a ZIP upload (bytes).  Default: 50 MB.
    max_upload_bytes: int = 50 * 1024 * 1024

    # ------------------------------------------------------------------ #
    # Application
    # ------------------------------------------------------------------ #
    # Comma-separated list of allowed CORS origins.
    # Example: "http://localhost:3000,http://localhost:5173"
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    # Set to "development" or "production".
    # In production mode raw exception details are hidden from API responses.
    app_env: str = "development"

    @property
    def is_development(self) -> bool:
        return self.app_env.lower() == "development"

    @property
    def cors_origins_list(self) -> list[str]:
        """Return CORS origins as a Python list."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def normalized_database_url(self) -> str:
        """Ensure postgres:// is converted to postgresql:// for SQLAlchemy 2.0 compatibility."""
        url = self.database_url
        if url.startswith("postgres://"):
            return "postgresql://" + url[len("postgres://"):]
        return url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached Settings singleton.

    ``lru_cache`` ensures the .env file is read only once per process.
    In tests, call ``get_settings.cache_clear()`` after overriding env vars.
    """
    return Settings()
