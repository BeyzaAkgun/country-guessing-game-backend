from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    app_name: str = "GeoGame API"
    app_env: str = "development"
    debug: bool = True
    secret_key: str

    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7

    database_url: str
    redis_url: str = "redis://localhost:6379/0"
    allowed_origins: List[str] = [
    "http://localhost:3000",
    "http://localhost:8081",
    "http://localhost:5173",
]
    guest_session_expire_hours: int = 24

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


settings = Settings()