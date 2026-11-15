import logging
import os
import sys
from collections.abc import MutableMapping
from logging.handlers import RotatingFileHandler
from typing import Any


class VEKAFormatter(logging.Formatter):
    """Custom formatter that ensures context is appended cleanly."""

    def format(self, record: logging.LogRecord) -> str:
        # Standard formatting first
        msg = super().format(record)

        # Append any extra context dictionary stored in record.context
        if hasattr(record, 'context') and isinstance(record.context, dict) and record.context:
            context_str = ' | '.join(f'{k}={v}' for k, v in record.context.items() if v is not None)
            if context_str:
                msg = f'{msg} | Context: [{context_str}]'

        return msg


class VEKALoggerAdapter(logging.LoggerAdapter):
    """Adapter to easily pass contextual information to the logger."""

    def process(self, msg: str, kwargs: MutableMapping[str, Any]) -> tuple[str, MutableMapping[str, Any]]:
        context = kwargs.pop('context', {})
        if self.extra:
            context.update(self.extra)
        kwargs['extra'] = {'context': context}
        return msg, kwargs


def setup_logging(log_level: str | None = None) -> None:
    """Sets up global logging configuration. Call this once at startup."""
    if log_level is None:
        from src.config.config import LOG_LEVEL

        log_level = LOG_LEVEL or 'INFO'

    level = getattr(logging, log_level.upper(), logging.INFO)

    # We use a consistent machine-readable text format
    fmt_string = '%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s'
    formatter = VEKAFormatter(fmt_string)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Clear existing handlers
    root_logger.handlers.clear()

    # Console handler (primary for Docker)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # Containers are read-only/non-root and use stdout. Explicit local opt-in only.
    if os.getenv('VEKA_LOG_TO_FILE', '0') == '1':
        os.makedirs('logs', exist_ok=True)
        file_handler = RotatingFileHandler('logs/bot.log', encoding='utf-8', maxBytes=5 * 1024 * 1024, backupCount=3)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    # Muffle spammy library loggers
    logging.getLogger('discord').setLevel(logging.WARNING)
    logging.getLogger('nextcord').setLevel(logging.WARNING)
    logging.getLogger('asyncio').setLevel(logging.WARNING)


def get_logger(name: str, **default_context) -> VEKALoggerAdapter:
    """Get a wrapped logger that supports context injection."""
    logger = logging.getLogger(name)
    return VEKALoggerAdapter(logger, default_context)
