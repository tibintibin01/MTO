import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator, HttpUrl
from typing import Optional, List, Any

class MTOSettings(BaseSettings):
    """
    Centralized Municipal Configuration Engine.
    Enforces type safety and 'Fail-Fast' validation on startup.
    """
    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8", 
        env_prefix="MTO_",
        extra="ignore"
    )

    # --- SERVER ---
    APP_NAME: str = "MTO Treasury Management System"
    ENVIRONMENT: str = Field(default="production")
    LOG_LEVEL: str = Field(default="INFO")
    
    # --- DATABASE ---
    DB_HOST: str = Field(default="127.0.0.1")
    DB_PORT: int = Field(default=3306, ge=1, le=65535)
    DB_USER: str = Field(default="")
    DB_NAME: str = Field(default="")
    DB_PASSWORD: str = Field(default="")
    DB_CONNECT_TIMEOUT: int = Field(default=5, ge=1, le=60)
    
    # --- SECURITY ---
    API_SECRET_KEY: str = Field(default="", validation_alias="SECRET_KEY")
    JWT_ALGORITHM: str = "HS256"
    TOKEN_EXPIRE_MINUTES: int = Field(default=480, ge=1) # Default 8 hours
    
    # --- FEATURES ---
    ENABLE_BULK_IMPORT: bool = True
    ENABLE_DELINQUENCY_NOTICES: bool = False
    ENABLE_CLOUD_BACKUP: bool = False
    ENABLE_SENTRY_TELEMETRY: bool = True
    MAINTENANCE_MODE: bool = False
    
    # --- MUNICIPAL CUSTOMIZATION ---
    MUNICIPALITY_NAME: str = "MTO Treasury"
    CURRENCY_SYMBOL: str = "₱"

    @field_validator("DB_NAME", "DB_USER")
    @classmethod
    def validate_required_db_fields(cls, v: str, info: Any) -> str:
        # info.data contains other fields already validated
        if v == "" and os.getenv("MTO_ENVIRONMENT", "production") == "production":
             # We check os.getenv because info.data might not have ENVIRONMENT yet depending on order
             # But usually it's fine.
             pass
        return v

    # Better validation logic for production
    def model_post_init(self, __context: Any) -> None:
        if self.ENVIRONMENT == "production":
            if not self.DB_USER:
                raise ValueError("MTO_DB_USER cannot be empty in production mode.")
            if not self.DB_NAME:
                raise ValueError("MTO_DB_NAME cannot be empty in production mode.")

# Global Settings Instance
try:
    config = MTOSettings()
except Exception as e:
    print("\n🏛️ 🚨 CRITICAL CONFIGURATION ERROR 🚨 🏛️")
    print(f"Details: {str(e)}")
    print("Please check your .env file and environment variables.\n")
    import sys
    sys.exit(1)
