import os
import json
from dotenv import load_dotenv
from typing import Optional
from utils.logger import mto_logger
from utils.secrets_vault import resolve_secrets_vault_path

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
        
        # 1. Resolve the machine-level vault shared by Administrator setup
        # commands and the Windows SYSTEM API task.
        vault_path = resolve_secrets_vault_path()
        self._vault_path = vault_path
        if vault_path.exists():
            try:
                with vault_path.open("r", encoding="utf-8") as f:
                    self._vault_secrets = json.load(f) or {}
                if not isinstance(self._vault_secrets, dict):
                    raise ValueError("vault root must be a JSON object")
                mto_logger.info(
                    f"SecretsManager: Loaded credentials vault from {vault_path}"
                )
            except Exception as e:
                mto_logger.error(
                    f"SecretsManager: Failed to parse protected vault {vault_path}: {e}"
                )

        # 2. Load .env file as a local developer-friendly fallback
        load_dotenv()
        self._initialized = True

        # Resolve environment mode — check both MTO_ENV and ENVIRONMENT so
        # secrets_manager and config.py always agree on the current mode.
        env_mode = (
            os.getenv("MTO_ENV")
            or os.getenv("ENVIRONMENT")
            or "development"
        ).lower()

        if env_mode == "production":
            # Hardening: Emit warnings if cleartext .env is found in production and vault is missing
            if os.path.exists(".env") and not self._vault_secrets:
                mto_logger.security(
                    "WARNING: Clear-text .env file detected in production workspace! "
                    f"Migrate secrets to system environment or {vault_path}.",
                    key="MTO_ENV"
                )
            mto_logger.info("SecretsManager initialized in SECURE PRODUCTION mode.")
        else:
            mto_logger.info(f"SecretsManager initialized in {env_mode} mode.")

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
        """
        Returns the JWT signing secret. Always required — no fallback.
        Fails fast at startup if missing or too short, regardless of environment.
        A known static default would allow any attacker to forge admin tokens.
        """
        value = self.get("MTO_JWT_SECRET", required=True)
        if len(value) < 32:
            raise EnvironmentError(
                "MTO_JWT_SECRET is too short (minimum 32 characters). "
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(64))\""
            )
        return value

    @property
    def db_password(self) -> str:
        """
        Returns the database password. Required in production — a blank
        password means the application is connecting as root or with no
        authentication, which is a critical security misconfiguration.
        """
        env_mode = (
            os.getenv("MTO_ENV")
            or os.getenv("ENVIRONMENT")
            or "development"
        ).lower()
        value = self.get("MTO_DB_PASSWORD", default="", required=False)
        if env_mode == "production" and not value:
            raise EnvironmentError(
                "MTO_DB_PASSWORD cannot be empty in production. "
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(24))\""
            )
        return value or ""

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

