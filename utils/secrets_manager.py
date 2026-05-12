import os
from dotenv import load_dotenv
from typing import Optional
from utils.logger import mto_logger

class SecretsManager:
    """
    Centralized Municipal Secrets Adapter.
    Handles credential retrieval from environment variables or .env files.
    Architected for future Vault (HashiCorp/AWS) integration.
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SecretsManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
            
        # Load .env file if present
        load_dotenv()
        self._initialized = True
        mto_logger.info("SecretsManager initialized (Environment + .env)")

    def get(self, key: str, default: Optional[str] = None, required: bool = False) -> Optional[str]:
        """Retrieves a secret with optional requirement enforcement."""
        value = os.getenv(key) or default
        
        if not value and required:
            mto_logger.security(f"CRITICAL SECRET MISSING: {key}", key=key)
            raise EnvironmentError(f"Missing required municipal secret: {key}")
            
        return value

    @property
    def jwt_secret(self) -> str:
        return self.get("MTO_JWT_SECRET", default="TEMPORARY_DEV_SECRET_DO_NOT_USE_IN_PROD", required=True)

    @property
    def db_password(self) -> str:
        return self.get("MTO_DB_PASSWORD", default="", required=False)

    @property
    def ssl_passphrase(self) -> str:
        return self.get("MTO_SSL_PASSPHRASE", default=None, required=False)

    @property
    def api_key(self) -> str:
        return self.get("MTO_API_KEY", required=True)

# Global Instance
secrets = SecretsManager()
