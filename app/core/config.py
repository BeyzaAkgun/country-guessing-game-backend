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

    # Keep as str — we parse it manually via property below
    # This bypasses pydantic-settings trying to JSON-decode it automatically
    allowed_origins: str = "http://localhost:3000,http://localhost:8081,http://localhost:5173"

    guest_session_expire_hours: int = 24

    @property
    def allowed_origins_list(self) -> List[str]:
        v = self.allowed_origins.strip()
        if v.startswith("["):
            import json
            try:
                return json.loads(v)
            except Exception:
                pass
        return [origin.strip() for origin in v.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


settings = Settings()