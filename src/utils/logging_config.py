"""
Logging Configuration Module

Provides structured logging setup with file rotation, privacy considerations,
and module-specific loggers for the Explain Screenshot application.
"""

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional, Dict, Any
import json
import traceback
from datetime import datetime
import re


class PrivacyFilter(logging.Filter):
    """Filter to sanitize sensitive information from log messages."""

    def __init__(self):
        super().__init__()
        self.sensitive_patterns = [
            # File paths - sanitize to relative paths
            (r'[A-Za-z]:\\[^\\]+\\[^\\]+\\[^\\]+', self._sanitize_path),
            # User names
            (r'Users\\[^\\]+', r'Users\\[USER]'),
            # Temporary paths
            (r'AppData\\Local\\Temp\\[^\\]+', r'AppData\\Local\\Temp\\[TEMP]'),
        ]

    def _sanitize_path(self, match):
        """Sanitize file path to show only relative structure."""
        path = match.group(0)
        parts = path.split('\\')
        if len(parts) > 3:
            return f"{parts[0]}\\...\\{parts[-2]}\\{parts[-1]}"
        return path

    def filter(self, record):
        """Filter log record to remove sensitive information."""
        if hasattr(record, 'msg') and record.msg:
            import re
            message = str(record.msg)

            for pattern, replacement in self.sensitive_patterns:
                if callable(replacement):
                    # For callable replacements, we need to handle matches differently
                    def replace_func(match):
                        return replacement(match)
                    message = re.sub(pattern, replace_func, message)
                else:
                    message = re.sub(pattern, replacement, message)

            record.msg = message

        return True


class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging."""

    def __init__(self, include_extra: bool = True):
        super().__init__()
        self.include_extra = include_extra

    def format(self, record):
        """Format log record as JSON."""
        log_data = {
            'timestamp': datetime.fromtimestamp(record.created).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno
        }

        # Add exception information if present
        if record.exc_info and record.exc_info[0]:
            log_data['exception'] = {
                'type': record.exc_info[0].__name__,
                'message': str(record.exc_info[1]),
                'traceback': traceback.format_exception(*record.exc_info)
            }

        # Add extra fields if enabled
        if self.include_extra:
            for key, value in record.__dict__.items():
                if key not in ['name', 'msg', 'args', 'levelname', 'levelno',
                              'pathname', 'filename', 'module', 'lineno',
                              'funcName', 'created', 'msecs', 'relativeCreated',
                              'thread', 'threadName', 'processName', 'process',
                              'getMessage', 'exc_info', 'exc_text', 'stack_info']:
                    log_data[f'extra_{key}'] = value

        return json.dumps(log_data, default=str, ensure_ascii=False)


class ApplicationLogger:
    """
    Application logging manager.

    Provides centralized logging configuration with file rotation,
    structured logging, and privacy protection.
    """

    def __init__(
        self,
        app_name: str = "explain-screenshot",
        log_dir: Optional[Path] = None,
        log_level: str = "INFO",
        max_file_size: int = 10 * 1024 * 1024,  # 10MB
        backup_count: int = 5,
        enable_console: bool = True,
        enable_json: bool = True,
        enable_privacy_filter: bool = True
    ):
        """
        Initialize application logger.

        Args:
            app_name: Application name for log file naming
            log_dir: Directory for log files (default: ./logs)
            log_level: Minimum log level to capture
            max_file_size: Maximum size of each log file in bytes
            backup_count: Number of backup log files to keep
            enable_console: Whether to log to console
            enable_json: Whether to use JSON formatting for file logs
            enable_privacy_filter: Whether to apply privacy filtering
        """
        self.app_name = app_name
        self.log_dir = log_dir or Path("logs")
        self.log_level = getattr(logging, log_level.upper())
        self.max_file_size = max_file_size
        self.backup_count = backup_count
        self.enable_console = enable_console
        self.enable_json = enable_json
        self.enable_privacy_filter = enable_privacy_filter

        # Create log directory
        self.log_dir.mkdir(exist_ok=True)

        # Track configured loggers
        self._configured_loggers: Dict[str, logging.Logger] = {}

        # Configure root logger
        self._configure_root_logger()

    def _configure_root_logger(self) -> None:
        """Configure the root logger with handlers."""
        root_logger = logging.getLogger()
        root_logger.setLevel(self.log_level)

        # Clear existing handlers
        root_logger.handlers.clear()

        # Add file handler with rotation
        self._add_file_handler(root_logger)

        # Add console handler if enabled
        if self.enable_console:
            self._add_console_handler(root_logger)

        # Add privacy filter if enabled
        if self.enable_privacy_filter:
            privacy_filter = PrivacyFilter()
            for handler in root_logger.handlers:
                handler.addFilter(privacy_filter)

    def _add_file_handler(self, logger: logging.Logger) -> None:
        """Add rotating file handler to logger."""
        log_file = self.log_dir / f"{self.app_name}.log"

        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=self.max_file_size,
            backupCount=self.backup_count,
            encoding='utf-8'
        )

        if self.enable_json:
            file_handler.setFormatter(JSONFormatter())
        else:
            file_handler.setFormatter(
                logging.Formatter(
                    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
                )
            )

        logger.addHandler(file_handler)

    def _add_console_handler(self, logger: logging.Logger) -> None:
        """Add console handler to logger."""
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(
            logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
        )
        logger.addHandler(console_handler)

    def get_logger(self, name: str) -> logging.Logger:
        """
        Get a logger for a specific module or component.

        Args:
            name: Logger name (typically module name)

        Returns:
            Configured logger instance
        """
        if name in self._configured_loggers:
            return self._configured_loggers[name]

        logger = logging.getLogger(name)
        logger.setLevel(self.log_level)

        # Don't add handlers if already configured by root logger
        if not logger.handlers and name != "root":
            # Create module-specific log file
            module_log_file = self.log_dir / f"{self.app_name}_{name.replace('.', '_')}.log"

            module_handler = logging.handlers.RotatingFileHandler(
                module_log_file,
                maxBytes=self.max_file_size // 2,  # Smaller files for module logs
                backupCount=3,
                encoding='utf-8'
            )

            if self.enable_json:
                module_handler.setFormatter(JSONFormatter())
            else:
                module_handler.setFormatter(
                    logging.Formatter(
                        '%(asctime)s - %(levelname)s - %(message)s'
                    )
                )

            # Add privacy filter if enabled
            if self.enable_privacy_filter:
                module_handler.addFilter(PrivacyFilter())

            logger.addHandler(module_handler)

        self._configured_loggers[name] = logger
        return logger

    def set_log_level(self, level: str) -> None:
        """
        Change the log level for all loggers.

        Args:
            level: New log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        """
        new_level = getattr(logging, level.upper())
        self.log_level = new_level

        # Update root logger
        logging.getLogger().setLevel(new_level)

        # Update all configured loggers
        for logger in self._configured_loggers.values():
            logger.setLevel(new_level)

    def add_context_filter(self, logger_name: str, context: Dict[str, Any]) -> None:
        """
        Add contextual information to a specific logger.

        Args:
            logger_name: Name of the logger to add context to
            context: Dictionary of contextual information
        """
        logger = self.get_logger(logger_name)

        class ContextFilter(logging.Filter):
            def filter(self, record):
                for key, value in context.items():
                    setattr(record, key, value)
                return True

        logger.addFilter(ContextFilter())

    def cleanup_old_logs(self, days_to_keep: int = 30) -> int:
        """
        Clean up old log files.

        Args:
            days_to_keep: Number of days of logs to keep

        Returns:
            Number of files deleted
        """
        from datetime import datetime, timedelta

        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        deleted_count = 0

        for log_file in self.log_dir.glob("*.log*"):
            try:
                file_time = datetime.fromtimestamp(log_file.stat().st_mtime)
                if file_time < cutoff_date:
                    log_file.unlink()
                    deleted_count += 1
            except OSError as e:
                logging.error(f"Error deleting old log file {log_file}: {e}")

        return deleted_count

    def get_log_stats(self) -> Dict[str, Any]:
        """
        Get statistics about log files.

        Returns:
            Dictionary with log file statistics
        """
        stats = {
            'log_directory': str(self.log_dir),
            'total_log_files': 0,
            'total_size_bytes': 0,
            'oldest_log': None,
            'newest_log': None,
            'log_files': []
        }

        log_files = list(self.log_dir.glob("*.log*"))
        stats['total_log_files'] = len(log_files)

        if log_files:
            file_info = []
            for log_file in log_files:
                try:
                    stat_info = log_file.stat()
                    file_data = {
                        'name': log_file.name,
                        'size_bytes': stat_info.st_size,
                        'modified': datetime.fromtimestamp(stat_info.st_mtime).isoformat()
                    }
                    file_info.append(file_data)
                    stats['total_size_bytes'] += stat_info.st_size
                except OSError:
                    continue

            if file_info:
                file_info.sort(key=lambda x: x['modified'])
                stats['oldest_log'] = file_info[0]['modified']
                stats['newest_log'] = file_info[-1]['modified']
                stats['log_files'] = file_info

        return stats


# Global logger instance
_app_logger: Optional[ApplicationLogger] = None


def setup_logging(
    log_dir: Optional[Path] = None,
    log_level: str = "INFO",
    enable_console: bool = True,
    enable_json: bool = True
) -> ApplicationLogger:
    """
    Set up application logging.

    Args:
        log_dir: Directory for log files
        log_level: Minimum log level
        enable_console: Whether to log to console
        enable_json: Whether to use JSON formatting

    Returns:
        Configured ApplicationLogger instance
    """
    global _app_logger

    _app_logger = ApplicationLogger(
        log_dir=log_dir,
        log_level=log_level,
        enable_console=enable_console,
        enable_json=enable_json
    )

    return _app_logger


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger for a module.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Configured logger instance
    """
    global _app_logger

    if _app_logger is None:
        _app_logger = ApplicationLogger()

    return _app_logger.get_logger(name)


def log_performance(func_name: str, execution_time: float, logger: logging.Logger) -> None:
    """
    Log performance metrics for a function.

    Args:
        func_name: Name of the function
        execution_time: Execution time in seconds
        logger: Logger to use
    """
    logger.info(
        "Performance metric",
        extra={
            'metric_type': 'execution_time',
            'function': func_name,
            'duration_seconds': execution_time
        }
    )


def log_user_action(action: str, context: Dict[str, Any], logger: logging.Logger) -> None:
    """
    Log user actions for analytics (privacy-safe).

    Args:
        action: Action identifier
        context: Additional context (sanitized)
        logger: Logger to use
    """
    logger.info(
        f"User action: {action}",
        extra={
            'event_type': 'user_action',
            'action': action,
            **context
        }
    )
