import logging
import json
import os
from datetime import datetime
from typing import Any, Dict

class JSONFormatter(logging.Formatter):
    """Custom JSON Formatter for structured municipal logging."""
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.now().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno
        }
        
        # Add extra fields if provided
        if hasattr(record, "extra_data") and isinstance(record.extra_data, dict):
            log_data.update(record.extra_data)
            
        # Exception handling
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
            
        return json.dumps(log_data)

class MTOLogger:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MTOLogger, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
            
        self.logger = logging.getLogger("MTO_SYSTEM")
        self.logger.setLevel(logging.INFO)
        
        # Ensure logs directory exists
        log_dir = "logs"
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
            
        # File Handler (JSON). If the log file is locked or unavailable,
        # keep the application running with console logging.
        try:
            file_handler = logging.FileHandler(f"logs/mto_audit_{datetime.now().strftime('%Y%m%d')}.json")
            file_handler.setFormatter(JSONFormatter())
            self.logger.addHandler(file_handler)
        except PermissionError as exc:
            self.logger.warning(f"Could not open audit log file; continuing with console logging only: {exc}")
        
        # Stream Handler (For console visibility)
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(JSONFormatter())
        self.logger.addHandler(stream_handler)
        
        self._initialized = True

    def log(self, level: str, message: str, *args, extra: Dict[str, Any] = None, **kwargs):
        """Logs a message with optional structured metadata.

        Accepts standard logging-style positional arguments so calls like
        logger.warning("Backup failed: %s", err) cannot crash the app.
        """
        lvl = getattr(logging, level.upper(), logging.INFO)

        metadata = dict(extra or {})
        exc_info = kwargs.pop("exc_info", None)
        metadata.update(kwargs)

        # We use a custom attribute to pass extra data to the formatter.
        self.logger.log(
            lvl,
            message,
            *args,
            exc_info=exc_info,
            extra={"extra_data": metadata} if metadata else None,
        )

        # Asynchronous Immutable Log Shipping Hook
        if level.upper() in ["WARNING", "ERROR"]:
            try:
                from utils.secrets_manager import secrets
                sink_url = secrets.audit_log_sink_url
                if sink_url:
                    import threading
                    import urllib.request
                    import json
                    from datetime import datetime
                    
                    try:
                        rendered_message = message % args if args else message
                    except Exception:
                        rendered_message = str(message)

                    payload = {
                        "timestamp": datetime.now().isoformat(),
                        "level": level.upper(),
                        "message": rendered_message,
                        "metadata": metadata
                    }
                    
                    def ship_log():
                        try:
                            req = urllib.request.Request(
                                sink_url,
                                data=json.dumps(payload).encode("utf-8"),
                                headers={"Content-Type": "application/json"},
                                method="POST"
                            )
                            with urllib.request.urlopen(req, timeout=2.0) as response:
                                response.read()
                        except Exception:
                            pass
                            
                    threading.Thread(target=ship_log, daemon=True).start()
            except Exception:
                pass


    def info(self, message: str, *args, **kwargs):
        self.log("INFO", message, *args, **kwargs)

    def error(self, message: str, *args, **kwargs):
        self.log("ERROR", message, *args, **kwargs)

    def critical(self, message: str, *args, **kwargs):
        self.log("CRITICAL", message, *args, **kwargs)

    def warning(self, message: str, *args, **kwargs):
        self.log("WARNING", message, *args, **kwargs)

    def security(self, message: str, *args, **kwargs):
        """Specialized security event logging."""
        kwargs["category"] = "SECURITY"
        self.log("WARNING", message, *args, **kwargs)

# Global Access Point
mto_logger = MTOLogger()


def info(message: str, *args, **kwargs):
    """Module-level compatibility wrapper for older imports."""
    mto_logger.info(message, *args, **kwargs)


def warning(message: str, *args, **kwargs):
    """Module-level compatibility wrapper for older imports."""
    mto_logger.warning(message, *args, **kwargs)


def error(message: str, *args, **kwargs):
    """Module-level compatibility wrapper for older imports."""
    mto_logger.error(message, *args, **kwargs)


def critical(message: str, *args, **kwargs):
    """Module-level compatibility wrapper for older imports."""
    mto_logger.critical(message, *args, **kwargs)
