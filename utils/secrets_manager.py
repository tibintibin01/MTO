import os
import json
from dotenv import load_dotenv
from typing import Optional
from utils.logger import mto_logger

class SecretsManager:
    """
    Centralized Municipal Secrets Adapter.
    Handles credential retrieval from system environment variables, secure local vaults,
    or developer-friendly fallback env files.
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
            
        self._vault_secrets = {}
        
        # 1. Resolve secure user-level credentials vault (Stored outside the repository)
        vault_path = os.path.expanduser("~/.mto/secrets.json")
        if os.path.exists(vault_path):
            try:
                with open(vault_path, "r", encoding="utf-8") as f:
                    self._vault_secrets = json.load(f) or {}
                mto_logger.info("SecretsManager: Loaded credentials vault from ~/.mto/secrets.json")
            except Exception as e:
                mto_logger.error(f"SecretsManager: Failed to parse ~/.mto/secrets.json: {e}")

        # 2. Load .env file as a local developer-friendly fallback
        load_dotenv()
        self._initialized = True
        
        env_mode = os.getenv("MTO_ENV", "development")
        if env_mode == "production":
            # Hardening: Emit warnings if cleartext .env is found in production and vault is missing
            if os.path.exists(".env") and not self._vault_secrets:
                mto_logger.security("WARNING: Clear-text .env file detected in production workspace! Migrate secrets to system environment or ~/.mto/secrets.json secure vault.", key="MTO_ENV")
            mto_logger.info("SecretsManager initialized in SECURE PRODUCTION mode.")
        else:
            mto_logger.info("SecretsManager initialized in developer-friendly mode.")

    def get(self, key: str, default: Optional[str] = None, required: bool = False) -> Optional[str]:
        """Retrieves a secret with prioritized resolution: Vault -> System Environment -> .env/Fallback."""
        # Priority 1: Secure JSON Vault
        value = self._vault_secrets.get(key)
        
        # Priority 2: System Environment / .env
        if not value:
            value = os.getenv(key)
            
        # Priority 3: Fallback Default
        if not value:
            value = default
        
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

    @property
    def redis_host(self) -> str:
        return self.get("MTO_REDIS_HOST", default="127.0.0.1")

    @property
    def redis_port(self) -> int:
        return int(self.get("MTO_REDIS_PORT", default="6379"))

    @property
    def audit_log_sink_url(self) -> Optional[str]:
        return self.get("MTO_AUDIT_LOG_SINK_URL", default=None)

# Global Instance
secrets = SecretsManager()

