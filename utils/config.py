import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator, HttpUrl, AliasChoices
from typing import Optional, List, Any

class MTOSettings(BaseSettings):
    """
    Centralized Municipal Configuration Engine.
    Enforces type safety and 'Fail-Fast' validation on startup.
    """
    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"), 
        env_file_encoding="utf-8", 
        env_prefix="MTO_",
        extra="ignore"
    )


    # --- SERVER ---
    APP_NAME: str = "Municipal Revenue System"
    ENVIRONMENT: str = Field(default="production")
    LOG_LEVEL: str = Field(default="INFO")
    
    # --- DATABASE ---
    DB_HOST: str = Field(default="127.0.0.1", validation_alias=AliasChoices("MTO_DB_HOST", "DB_HOST"))
    DB_PORT: int = Field(default=3306, ge=1, le=65535, validation_alias=AliasChoices("MTO_DB_PORT", "DB_PORT"))
    DB_USER: str = Field(default="", validation_alias=AliasChoices("MTO_DB_USER", "DB_USER"))
    DB_NAME: str = Field(default="", validation_alias=AliasChoices("MTO_DB_NAME", "DB_NAME"))
    DB_PASSWORD: str = Field(default="", validation_alias=AliasChoices("MTO_DB_PASSWORD", "DB_PASSWORD"))
    DB_CONNECT_TIMEOUT: int = Field(default=5, ge=1, le=60)
    
    # --- BINARY PATHS ---
    MYSQL_PATH: str = Field(default="mysql")
    MYSQLDUMP_PATH: str = Field(default="mysqldump")
    
    # --- SECURITY ---
    API_SECRET_KEY: str = Field(default="", validation_alias=AliasChoices("MTO_JWT_SECRET", "SECRET_KEY", "MTO_API_SECRET_KEY"))
    JWT_ALGORITHM: str = "HS256"
    TOKEN_EXPIRE_MINUTES: int = Field(default=60, ge=1) # 1 hour
    
    # --- FEATURES ---
    ENABLE_BULK_IMPORT: bool = True
    ENABLE_DELINQUENCY_NOTICES: bool = False
    ENABLE_CLOUD_BACKUP: bool = False
    ENABLE_SENTRY_TELEMETRY: bool = True
    MAINTENANCE_MODE: bool = False
    
    # --- MUNICIPAL CUSTOMIZATION ---
    MUNICIPALITY_NAME: str = "Revenue System"
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
            # Reject root — the application must never run as the DB superuser.
            if self.DB_USER.strip().lower() == "root":
                raise ValueError(
                    "MTO_DB_USER=root is not allowed in production. "
                    "Create a least-privilege 'mto_app' account by running: "
                    "python scripts/create_db_user.py"
                )
            # Reject a blank or placeholder password.
            db_pass = os.getenv("MTO_DB_PASSWORD", "").strip()
            if not db_pass or db_pass in ("CHANGE_ME", "your_secure_db_password",
                                          "your_secure_db_password_min_16_chars"):
                raise ValueError(
                    "MTO_DB_PASSWORD cannot be empty or a placeholder in production. "
                    "Generate one with: python -c \"import secrets; print(secrets.token_hex(24))\""
                )

# Global Settings Instance
try:
    config = MTOSettings()
except Exception as e:
    print("\n🏛️ 🚨 CRITICAL CONFIGURATION ERROR 🚨 🏛️")
    print(f"Details: {str(e)}")
    print("Please check your .env file and environment variables.\n")
    import sys
    sys.exit(1)
