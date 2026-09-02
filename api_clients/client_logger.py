"""Local technical logging for the desktop client.

This module deliberately has no dependency on server secrets or database code.
Security and financial audit events remain authoritative on the API server.
"""

from datetime import datetime
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional


class _JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
        }
        metadata = getattr(record, "extra_data", None)
        if isinstance(metadata, dict):
            payload.update(metadata)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


class ClientLogger:
    def __init__(self) -> None:
        self.logger = logging.getLogger("MTO_DESKTOP")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        if self.logger.handlers:
            return

        formatter = _JSONFormatter()
        try:
            log_dir = Path("logs")
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(
                log_dir / f"mto_client_{datetime.now():%Y%m%d}.json",
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)
        except OSError:
            pass

        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        self.logger.addHandler(stream_handler)

    def log(
        self,
        level: str,
        message: str,
        *args: Any,
        extra: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        metadata = dict(extra or {})
        exc_info = kwargs.pop("exc_info", None)
        metadata.update(kwargs)
        self.logger.log(
            getattr(logging, level.upper(), logging.INFO),
            message,
            *args,
            exc_info=exc_info,
            extra={"extra_data": metadata} if metadata else None,
        )

    def info(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.log("INFO", message, *args, **kwargs)

    def warning(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.log("WARNING", message, *args, **kwargs)

    def error(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.log("ERROR", message, *args, **kwargs)

    def critical(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.log("CRITICAL", message, *args, **kwargs)


mto_logger = ClientLogger()
