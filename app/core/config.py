from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Union
import json


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
       
        extra="ignore"
    )

    app_name: str = "country-guessing-game-api"
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
    
    
    from pydantic import field_validator
    
    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_allowed_origins(cls, v: Union[str, List[str], None]) -> List[str]:
        if v is None:
            return [
                "http://localhost:3000",
                "http://localhost:8081",
                "http://localhost:5173",
            ]
        
       
        if isinstance(v, list):
            return v
        
        
        if isinstance(v, str):
           
            if not v or v.strip() == "":
                return []
            
          
            if v.strip().startswith('[') and v.strip().endswith(']'):
                try:
                    return json.loads(v)
                except json.JSONDecodeError:
                   
                    pass
            
       
            cleaned = v.replace('"', '').replace("'", "")
            items = [item.strip() for item in cleaned.split(',') if item.strip()]
            return items
        
       
        return [
            "http://localhost:3000",
            "http://localhost:8081",
            "http://localhost:5173",
        ]


settings = Settings()