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
            
        # File Handler (JSON)
        file_handler = logging.FileHandler(f"logs/mto_audit_{datetime.now().strftime('%Y%m%d')}.json")
        file_handler.setFormatter(JSONFormatter())
        self.logger.addHandler(file_handler)
        
        # Stream Handler (For console visibility)
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(JSONFormatter())
        self.logger.addHandler(stream_handler)
        
        self._initialized = True

    def log(self, level: str, message: str, extra: Dict[str, Any] = None):
        """Logs a message with optional structured metadata."""
        lvl = getattr(logging, level.upper(), logging.INFO)
        
        # We use a custom attribute to pass extra data to the formatter
        self.logger.log(lvl, message, extra={"extra_data": extra} if extra else None)

    def info(self, message: str, **kwargs):
        self.log("INFO", message, kwargs)

    def error(self, message: str, **kwargs):
        self.log("ERROR", message, kwargs)

    def warning(self, message: str, **kwargs):
        self.log("WARNING", message, kwargs)

    def security(self, message: str, **kwargs):
        """Specialized security event logging."""
        kwargs["category"] = "SECURITY"
        self.log("WARNING", message, kwargs)

# Global Access Point
mto_logger = MTOLogger()
