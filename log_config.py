"""
Centralized Logging Configuration for Meeting Intelligence Agent
Provides unified logging setup and configuration
"""

import os
import sys
import logging
import logging.handlers
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

# Import constants
from src.constants.app import (
    LOG_FORMAT, LOG_DATE_FORMAT, LOG_FILE_PATH, LOG_LEVELS
)

# Global logger registry
_loggers: Dict[str, logging.Logger] = {}
_configured = False


def setup_logging(
    log_level: str = None,
    log_file: str = None,
    log_format: str = None,
    enable_console: bool = True,
    enable_file: bool = True,
    max_file_size: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5
) -> None:
    """
    Setup centralized logging configuration

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Path to log file
        log_format: Log message format
        enable_console: Enable console logging
        enable_file: Enable file logging
        max_file_size: Maximum log file size before rotation
        backup_count: Number of backup files to keep
    """
    global _configured

    if _configured:
        return

    # Set defaults
    log_level = log_level or os.getenv('LOG_LEVEL', 'INFO')
    log_file = log_file or LOG_FILE_PATH
    log_format = log_format or LOG_FORMAT

    # Convert log level string to logging constant
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    # Create log directory if it doesn't exist
    if log_file:
        log_dir = Path(log_file).parent
        log_dir.mkdir(parents=True, exist_ok=True)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Clear existing handlers
    root_logger.handlers.clear()

    # Create formatter
    formatter = logging.Formatter(
        fmt=log_format,
        datefmt=LOG_DATE_FORMAT
    )

    # Console handler
    if enable_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(numeric_level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    # File handler with rotation
    if enable_file and log_file:
        try:
            file_handler = logging.handlers.RotatingFileHandler(
                filename=log_file,
                maxBytes=max_file_size,
                backupCount=backup_count,
                encoding='utf-8'
            )
            file_handler.setLevel(numeric_level)
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
        except Exception as e:
            print(f"Warning: Could not setup file logging: {e}")

    # Set configured flag
    _configured = True

    # Log configuration success
    logger = logging.getLogger(__name__)
    logger.info(f"Logging configured - Level: {log_level}, File: {log_file}")


def get_logger(name: str = None, setup_if_needed: bool = True) -> logging.Logger:
    """
    Get a logger instance with optional automatic setup

    Args:
        name: Logger name (defaults to calling module)
        setup_if_needed: Automatically setup logging if not configured

    Returns:
        Logger instance
    """
    global _loggers, _configured

    # Auto-setup if needed
    if setup_if_needed and not _configured:
        setup_logging()

    # Use calling module name if not provided
    if name is None:
        frame = sys._getframe(1)
        name = frame.f_globals.get('__name__', 'unknown')

    # Return cached logger or create new one
    if name not in _loggers:
        _loggers[name] = logging.getLogger(name)

    return _loggers[name]


def configure_audit_logging() -> None:
    """Configure specific settings for audit logging"""
    # Ensure audit loggers don't propagate to avoid duplicate logs
    audit_loggers = [
        'src.utility.logging.audit_logger',
        'src.utility.logging.function_logger',
        'src.utility.logging.workflow_logger',
        'src.utility.logging.performance_logger',
        'src.utility.logging.langchain_agent_audit_logger'
    ]

    for logger_name in audit_loggers:
        logger = logging.getLogger(logger_name)
        logger.propagate = False

        # Add specific handler for audit logs if needed
        audit_log_file = os.path.join(
            Path(LOG_FILE_PATH).parent,
            'audit.log'
        )

        try:
            audit_handler = logging.handlers.RotatingFileHandler(
                filename=audit_log_file,
                maxBytes=50 * 1024 * 1024,  # 50MB
                backupCount=10,
                encoding='utf-8'
            )

            audit_formatter = logging.Formatter(
                fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt=LOG_DATE_FORMAT
            )
            audit_handler.setFormatter(audit_formatter)
            logger.addHandler(audit_handler)

        except Exception as e:
            print(f"Warning: Could not setup audit logging: {e}")


def configure_performance_logging() -> None:
    """Configure specific settings for performance logging"""
    perf_logger = logging.getLogger('src.utility.logging.performance_logger')

    # Create performance-specific log file
    perf_log_file = os.path.join(
        Path(LOG_FILE_PATH).parent,
        'performance.log'
    )

    try:
        perf_handler = logging.handlers.RotatingFileHandler(
            filename=perf_log_file,
            maxBytes=20 * 1024 * 1024,  # 20MB
            backupCount=5,
            encoding='utf-8'
        )

        perf_formatter = logging.Formatter(
            fmt='%(asctime)s - PERF - %(message)s',
            datefmt=LOG_DATE_FORMAT
        )
        perf_handler.setFormatter(perf_formatter)
        perf_logger.addHandler(perf_handler)
        perf_logger.propagate = False

    except Exception as e:
        print(f"Warning: Could not setup performance logging: {e}")


def configure_cron_logging() -> None:
    """Configure specific settings for cron job logging"""
    cron_logger = logging.getLogger('src.utility.cron')

    # Create cron-specific log file
    cron_log_file = os.path.join(
        Path(LOG_FILE_PATH).parent,
        'cron.log'
    )

    try:
        cron_handler = logging.handlers.RotatingFileHandler(
            filename=cron_log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=3,
            encoding='utf-8'
        )

        cron_formatter = logging.Formatter(
            fmt='%(asctime)s - CRON - %(levelname)s - %(message)s',
            datefmt=LOG_DATE_FORMAT
        )
        cron_handler.setFormatter(cron_formatter)
        cron_logger.addHandler(cron_handler)
        cron_logger.propagate = False

    except Exception as e:
        print(f"Warning: Could not setup cron logging: {e}")


def get_log_stats() -> Dict[str, Any]:
    """Get logging statistics and configuration info"""
    return {
        "configured": _configured,
        "active_loggers": len(_loggers),
        "logger_names": list(_loggers.keys()),
        "log_file": LOG_FILE_PATH,
        "log_level": logging.getLogger().level,
        "handlers_count": len(logging.getLogger().handlers),
        "timestamp": datetime.now().isoformat()
    }


def reset_logging() -> None:
    """Reset logging configuration (useful for testing)"""
    global _configured, _loggers

    # Clear all handlers
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Clear logger registry
    _loggers.clear()
    _configured = False


# Auto-configure specialized logging on import
def _auto_configure():
    """Automatically configure specialized logging"""
    try:
        configure_audit_logging()
        configure_performance_logging()
        configure_cron_logging()
    except Exception as e:
        print(f"Warning: Auto-configuration failed: {e}")


# Run auto-configuration
_auto_configure()