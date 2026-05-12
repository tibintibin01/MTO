import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, validator, HttpUrl
from typing import Optional, List

class MTOSettings(BaseSettings):
    """
    Centralized Municipal Configuration Engine.
    Enforces type safety and 'Fail-Fast' validation on startup.
    """
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- SERVER ---
    APP_NAME: str = "MTO Treasury Management System"
    ENVIRONMENT: str = Field(default="production", pattern="^(production|staging|development)$")
    LOG_LEVEL: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    
    # --- DATABASE ---
    DB_HOST: str = Field(default="localhost", env="MTO_DB_HOST")
    DB_PORT: int = Field(default=3306, env="MTO_DB_PORT", ge=1, le=65535)
    DB_USER: str = Field(default="", env="MTO_DB_USER")
    DB_NAME: str = Field(default="", env="MTO_DB_NAME")
    DB_CONNECT_TIMEOUT: int = Field(default=5, ge=1, le=60)
    
    # --- SECURITY ---
    JWT_ALGORITHM: str = "HS256"
    TOKEN_EXPIRE_MINUTES: int = Field(default=480, ge=1) # Default 8 hours
    
    # --- FEATURES ---
    MAINTENANCE_MODE: bool = False
    BULK_IMPORT_ENABLED: bool = True
    OFFLINE_SYNC_INTERVAL: int = Field(default=30, ge=5) # Seconds
    
    # --- MUNICIPAL CUSTOMIZATION ---
    MUNICIPALITY_NAME: str = "MTO Treasury"
    CURRENCY_SYMBOL: str = "₱"

    @validator("DB_NAME", "DB_USER")
    def validate_required_db_fields(cls, v, values):
        if values.get("ENVIRONMENT") == "production" and not v:
            raise ValueError(f"Database field cannot be empty in production.")
        return v

# Global Settings Instance
# This will perform validation IMMEDIATELY upon import.
try:
    config = MTOSettings()
except Exception as e:
    # Fail-Fast: The application cannot start with invalid configuration
    print("\n🏛️ 🚨 CRITICAL CONFIGURATION ERROR 🚨 🏛️")
    print(f"Details: {str(e)}")
    print("Please check your .env file and environment variables.\n")
    import sys
    sys.exit(1)
