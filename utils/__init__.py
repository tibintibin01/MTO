import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
import os
import traceback
import pandas as pd
import json
import uuid
import time
import threading
from typing import Optional, Any, Dict, List
from contextvars import ContextVar
from pathlib import Path
import secrets
import hashlib
import base64
import binascii

# --- SECURITY CONSTANTS ---
# Legacy scheme kept for migration detection only — new hashes use bcrypt.
PASSWORD_SCHEME = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 200000


# --- CONFIGURATION MANAGEMENT ---
class ConfigManager:
    """Handles local persistence of user settings and UI state."""
    _config_file = "config.json"
    _defaults = {
        "appearance_mode": "dark",
        "language": "en",
        "toast_duration": 3000,
        "auto_refresh_interval": 30,
        "sidebar_collapsed": False
    }
    _config = {}

    @classmethod
    def load(cls):
        if not os.path.exists(cls._config_file):
            cls._config = cls._defaults.copy()
            cls.save()
        else:
            try:
                with open(cls._config_file, "r") as f:
                    cls._config = {**cls._defaults, **json.load(f)}
            except Exception:
                cls._config = cls._defaults.copy()

    @classmethod
    def save(cls):
        try:
            with open(cls._config_file, "w") as f:
                json.dump(cls._config, f, indent=4)
        except Exception as e:
            print(f"ERROR: Failed to save config: {e}")

    @classmethod
    def get(cls, key: str, default: Any = None) -> Any:
        if not cls._config: cls.load()
        return cls._config.get(key, default)

    @classmethod
    def set(cls, key: str, value: Any):
        if not cls._config: cls.load()
        cls._config[key] = value
        cls.save()

# --- FEATURE TOGGLES ---
class FeatureManager:
    """Manages system feature flags via environment variables."""
    _defaults = {
        "BULK_IMPORT": True,
        "DELINQUENCY_NOTICES": False,
        "CLOUD_BACKUP": False,
        "SENTRY_TELEMETRY": True,
        "MAINTENANCE_MODE": False,
    }

    @classmethod
    def is_enabled(cls, feature_name: str) -> bool:
        env_key = f"MTO_ENABLE_{feature_name.upper()}"
        if feature_name.upper() == "MAINTENANCE_MODE":
            env_key = "MTO_MAINTENANCE_MODE"
            
        val = os.getenv(env_key)
        if val is None:
            return cls._defaults.get(feature_name.upper(), False)
        return str(val).lower() in ("1", "true", "yes", "on")

def is_feature_enabled(feature_name: str) -> bool:
    """Helper to check if a feature is enabled."""
    return FeatureManager.is_enabled(feature_name)

# --- OBSERVABILITY CONTEXT ---
_request_id_ctx_var: ContextVar[Optional[str]] = ContextVar("request_id", default="SYSTEM")

def set_request_id(request_id: str = None):
    _request_id_ctx_var.set(request_id or str(uuid.uuid4()))

def get_request_id():
    return _request_id_ctx_var.get()

class ContextFilter(logging.Filter):
    def filter(self, record):
        record.request_id = get_request_id()
        return True

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "SYSTEM"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_record["traceback"] = self.formatException(record.exc_info)
        return json.dumps(log_record)

def format_date_for_db(date_str: Optional[str]) -> Optional[str]:
    if not date_str: return None
    date_str = date_str.replace("/", "-").strip()
    try:
        return datetime.strptime(date_str, "%m-%d-%Y").strftime("%Y-%m-%d")
    except ValueError:
        try: return datetime.strptime(date_str, "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError as e: 
            log_error_to_file(f"Date format warning for db: {date_str}", error=e)
            return date_str

def format_date_for_display(date_val: Any) -> str:
    if not date_val: return ""
    try:
        if isinstance(date_val, str):
            return datetime.strptime(date_val, "%Y-%m-%d").strftime("%m-%d-%Y")
        return date_val.strftime("%m-%d-%Y")
    except (ValueError, TypeError, AttributeError) as e:
        log_error_to_file(f"Date display format warning: {date_val}", error=e)
        return str(date_val)

def format_curr(val: Any) -> str:
    try: return "{:,.2f}".format(float(val)) if val else "0.00"
    except (ValueError, TypeError) as e: 
        log_error_to_file(f"Currency format warning: {val}", error=e)
        return "0.00"

def clean_num(val: Any) -> float:
    try: 
        if pd.isna(val) or val == "": return 0.0
        s = str(val).replace(",", "").replace("â‚±", "").strip()
        return float(s) if s else 0.0
    except (ValueError, TypeError) as e: 
        log_error_to_file(f"Number clean warning: {val}", error=e)
        return 0.0

# Path Configuration
# Updated for package structure (moves up one level to project root)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)
ERROR_LOG_PATH = os.path.join(LOGS_DIR, "system.log")

# Setup professional rotating JSON logger
sys_logger = logging.getLogger("MTOSystem")
sys_logger.setLevel(logging.INFO)
try:
    handler = RotatingFileHandler(ERROR_LOG_PATH, maxBytes=5*1024*1024, backupCount=5, encoding="utf-8")
    handler.addFilter(ContextFilter())
    handler.setFormatter(JSONFormatter(datefmt='%Y-%m-%d %H:%M:%S'))
    sys_logger.addHandler(handler)
except PermissionError as exc:
    # A locked log file should not prevent the API server from starting.
    sys_logger.warning("Could not open system.log; continuing with console logging only: %s", exc)

# Also log to console for development visibility
console = logging.StreamHandler()
console.addFilter(ContextFilter())
console.setFormatter(logging.Formatter('[%(asctime)s] [%(request_id)s] %(levelname)s: %(message)s'))
sys_logger.addHandler(console)

def log_critical_event(event_type: str, message: str, user: str = "SYSTEM"):
    """Logs a critical event for monitoring and alerting tools."""
    sys_logger.critical(f"EVENT_TYPE={event_type} | USER={user} | MESSAGE={message}")

def log_error_to_file(context: str, error: Optional[Exception] = None, extra: Optional[Any] = None, traceback_text: Optional[str] = None) -> Optional[str]:
    """Professional wrapper for the system logger to maintain compatibility."""
    try:
        msg = context
        if error:
            msg += f" | Error: {error}"
        if extra:
            msg += f" | Details: {extra}"
        
        if traceback_text:
            msg += f"\nTraceback:\n{traceback_text}"
        elif error:
            # If an error is provided but no traceback, capture it if possible
            auto_traceback = traceback.format_exc()
            if auto_traceback and auto_traceback.strip() != "NoneType: None":
                msg += f"\nTraceback:\n{auto_traceback}"

        print(f"CRITICAL LOG: {msg}")
        sys_logger.error(msg)
        return ERROR_LOG_PATH
    except Exception as log_e:
        print(f"CRITICAL: Logging failed (Shadow Check): {log_e}")
        return None

class LocalizationManager:
    _instance = None
    _strings = {}
    _current_locale = "en"

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(LocalizationManager, cls).__new__(cls)
            cls._instance._load_strings()
        return cls._instance

    def _load_strings(self):
        try:
            # Updated path logic: __file__ is root/utils/__init__.py, locales are in root/locales
            base_path = Path(__file__).resolve().parent.parent
            locale_path = base_path / "locales" / f"{self._current_locale}.json"
            if locale_path.exists():
                with open(locale_path, "r", encoding="utf-8") as f:
                    self._strings = json.load(f)
            else:
                print(f"CRITICAL: Locale file not found at {locale_path}")
        except Exception as e:
            print(f"CRITICAL: Failed to load strings: {e}")

    def get(self, key, default=None):
        keys = key.split(".")
        val = self._strings
        try:
            for k in keys:
                val = val[k]
            return val
        except (KeyError, TypeError):
            return default or key

    def set_locale(self, locale):
        """Switches the current locale and reloads strings."""
        if locale == self._current_locale:
            return
        self._current_locale = locale
        self._load_strings()

def tr(key, default=None):
    """Global helper for translation."""
    return LocalizationManager().get(key, default)

def export_data_to_excel(data, columns, filename_prefix="Export"):
    """
    General purpose export tool. 
    data: List of lists/tuples representing rows.
    columns: List of column headers.
    """
    try:
        from tkinter import filedialog, messagebox
        import pandas as pd
        
        # Ask user for save location
        default_name = f"{filename_prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        save_path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx"), ("CSV files", "*.csv")],
            initialfile=default_name
        )
        
        if not save_path:
            return None

        df = pd.DataFrame(data, columns=columns)
        
        if save_path.endswith(".csv"):
            df.to_csv(save_path, index=False)
        else:
            df.to_excel(save_path, index=False)
            
        messagebox.showinfo("Success", f"Data exported successfully to:\n{save_path}")
        return save_path
    except Exception as e:
        log_error_to_file("Failed to export data", e)
        from tkinter import messagebox
        messagebox.showerror("Export Error", f"Failed to export data: {str(e)}")
        return None

# --- SECURITY UTILITIES ---
# Single authoritative password hashing implementation for the entire project.
# All new hashes are bcrypt. Legacy PBKDF2-SHA256 hashes are still verifiable
# so existing accounts keep working; they are transparently re-hashed to bcrypt
# on the next successful login.
#
# Implementation note: we call the `bcrypt` package directly rather than going
# through passlib because passlib 1.7.4 is incompatible with bcrypt >= 4.0
# (the __about__ attribute was removed). Using bcrypt directly avoids that
# dependency entirely and is straightforward.


def hash_password(password: str) -> str:
    """
    Hashes a plaintext password with bcrypt (cost factor 12).
    Always use this for new hashes — never store plaintext.

    bcrypt truncates at 72 bytes. Passwords longer than 72 bytes are
    pre-hashed with SHA-256 (hex digest = 64 ASCII bytes, safely under the
    limit) so the full password entropy is preserved.
    """
    if password is None:
        raise ValueError("Password is required.")
    import bcrypt as _bcrypt
    secret = _prepare_bcrypt_secret(str(password))
    return _bcrypt.hashpw(secret, _bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, stored_value: str) -> bool:
    """
    Verifies a plaintext password against a stored hash.

    Handles both current (bcrypt) and legacy (pbkdf2_sha256) hashes so
    existing accounts are not locked out during the migration period.
    Returns True on a match, False otherwise.
    """
    if not stored_value:
        return False
    stored_text = str(stored_value)

    # --- bcrypt path ---
    if stored_text.startswith("$2b$") or stored_text.startswith("$2a$"):
        try:
            import bcrypt as _bcrypt
            secret = _prepare_bcrypt_secret(str(password))
            return _bcrypt.checkpw(secret, stored_text.encode("utf-8"))
        except Exception:
            return False

    # --- Legacy PBKDF2-SHA256 path ---
    if stored_text.startswith(f"{PASSWORD_SCHEME}$"):
        try:
            _, iteration_text, salt_b64, digest_b64 = stored_text.split("$", 3)
            salt = base64.b64decode(salt_b64.encode("ascii"))
            expected_digest = base64.b64decode(digest_b64.encode("ascii"))
            actual_digest = hashlib.pbkdf2_hmac(
                "sha256",
                str(password).encode("utf-8"),
                salt,
                int(iteration_text),
            )
            return secrets.compare_digest(actual_digest, expected_digest)
        except (ValueError, binascii.Error, TypeError):
            return False
        except Exception as e:
            log_error_to_file("Unexpected error during legacy password verification", e)
            return False

    return False


def _prepare_bcrypt_secret(password: str) -> bytes:
    """
    Returns the password as bytes ready for bcrypt.
    Passwords longer than 72 bytes are pre-hashed with SHA-256 so the full
    entropy is preserved (bcrypt silently truncates at 72 bytes otherwise).
    The hex digest is 64 ASCII bytes — well within bcrypt's limit.
    """
    encoded = password.encode("utf-8")
    if len(encoded) > 72:
        encoded = hashlib.sha256(encoded).hexdigest().encode("ascii")
    return encoded


def is_password_hashed(password_value: str) -> bool:
    """
    Returns True if the stored value is any recognised hash format
    (bcrypt or legacy PBKDF2). Used to detect plain-text passwords.
    """
    s = str(password_value)
    return (
        s.startswith("$2b$")
        or s.startswith("$2a$")
        or s.startswith(f"{PASSWORD_SCHEME}$")
    )


def needs_rehash(stored_value: str) -> bool:
    """
    Returns True when a stored hash is a legacy PBKDF2 hash that should be
    upgraded to bcrypt on the next successful login.
    """
    return str(stored_value).startswith(f"{PASSWORD_SCHEME}$")

