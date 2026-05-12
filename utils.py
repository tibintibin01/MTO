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
from contextvars import ContextVar
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

class MetricsManager:
    _metrics = {"request_count": 0, "error_count": 0, "latency_sum": 0.0, "last_updated": None}
    _lock = threading.Lock()

    @classmethod
    def record_request(cls, latency_ms: float, is_error: bool = False):
        with cls._lock:
            cls._metrics["request_count"] += 1
            cls._metrics["latency_sum"] += latency_ms
            if is_error: cls._metrics["error_count"] += 1
            cls._metrics["last_updated"] = datetime.now().isoformat()
            try:
                base_dir = os.path.dirname(os.path.abspath(__file__))
                path = os.path.join(base_dir, "logs", "metrics.json")
                with open(path, "w") as f: json.dump(cls._metrics, f)
            except: pass

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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)
ERROR_LOG_PATH = os.path.join(LOGS_DIR, "system.log")

# Setup professional rotating JSON logger
logger = logging.getLogger("MTOSystem")
logger.setLevel(logging.INFO)
handler = RotatingFileHandler(ERROR_LOG_PATH, maxBytes=5*1024*1024, backupCount=5, encoding="utf-8")
handler.addFilter(ContextFilter())
handler.setFormatter(JSONFormatter(datefmt='%Y-%m-%d %H:%M:%S'))
logger.addHandler(handler)

# Also log to console for development visibility
console = logging.StreamHandler()
console.addFilter(ContextFilter())
console.setFormatter(logging.Formatter('[%(asctime)s] [%(request_id)s] %(levelname)s: %(message)s'))
logger.addHandler(console)

def log_critical_event(event_type: str, message: str, user: str = "SYSTEM"):
    """Logs a critical event for monitoring and alerting tools."""
    logger.critical(f"EVENT_TYPE={event_type} | USER={user} | MESSAGE={message}")

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

        logger.error(msg)
        return ERROR_LOG_PATH
    except Exception:
        return None

from pathlib import Path

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
            # Assumes utils.py is in project root or near it
            base_path = Path(__file__).resolve().parent
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
