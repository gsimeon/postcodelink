"""Application configuration using Pydantic Settings."""
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "PostcodeLink Nigeria API"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    
    # Database URL: default SQLite, switchable to PostgreSQL in .env
    DATABASE_URL: str = "sqlite:///./postcodelink.db"
    
    # CORS
    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://postcodelink.ng",
    ]
    
    # Security
    SECRET_KEY: str = "supersecret_postcodelink_production_key_2026"
    OTP_MAX_ATTEMPTS: int = 3
    OTP_LOCKOUT_MINUTES: int = 15
    
    # External NIPOST or Upstream Postcode Provider
    NIPOST_API_KEY: str = ""
    NIPOST_API_URL: str = ""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )


settings = Settings()

