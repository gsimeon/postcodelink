"""Application configuration using Pydantic Settings."""
import os
import secrets
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "PostcodeLink Nigeria API"
    VERSION: str = "1.1.0"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"
    
    # Database URL: default SQLite, switchable to PostgreSQL via DATABASE_URL
    DATABASE_URL: str = "sqlite:///./postcodelink.db"
    
    # CORS
    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://postcodelink.ng",
    ]
    
    # Security & JWT Token Auth
    # In production, SECRET_KEY must be provided via environment variable
    SECRET_KEY: str = os.getenv("SECRET_KEY", "postcodelink_dev_secret_key_change_in_production_" + secrets.token_hex(16))
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours
    
    # Delivery PIN / OTP Security
    OTP_MAX_ATTEMPTS: int = 3
    OTP_LOCKOUT_MINUTES: int = 15
    OTP_EXPIRE_HOURS: int = 24
    
    # Seeding & External Integrations
    SEED_DEMO_DATA: bool = True
    NIPOST_API_KEY: str = ""
    NIPOST_API_URL: str = ""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )


settings = Settings()
