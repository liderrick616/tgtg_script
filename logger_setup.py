"""
logger_setup.py — Colored console + file logging for the TGTG bot.
"""

import logging
import sys
from datetime import datetime

try:
    from colorama import Fore, Style, init as colorama_init
    colorama_init(autoreset=True)
    HAS_COLORAMA = True
except ImportError:
    HAS_COLORAMA = False


class ColoredFormatter(logging.Formatter):
    """Custom formatter that adds colors to console output."""

    LEVEL_COLORS = {
        logging.DEBUG: "\033[36m",      # Cyan
        logging.INFO: "\033[32m",       # Green
        logging.WARNING: "\033[33m",    # Yellow
        logging.ERROR: "\033[31m",      # Red
        logging.CRITICAL: "\033[1;31m", # Bold Red
    }
    RESET = "\033[0m"

    LEVEL_ICONS = {
        logging.DEBUG: "🔍",
        logging.INFO: "✅",
        logging.WARNING: "⚠️ ",
        logging.ERROR: "❌",
        logging.CRITICAL: "🔥",
    }

    def format(self, record):
        color = self.LEVEL_COLORS.get(record.levelno, self.RESET)
        icon = self.LEVEL_ICONS.get(record.levelno, "")
        timestamp = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        msg = record.getMessage()
        return f"{color}{timestamp} {icon} [{record.levelname:<7}]{self.RESET} {msg}"


class FileFormatter(logging.Formatter):
    """Clean formatter for log files (no colors)."""

    def format(self, record):
        timestamp = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        return f"{timestamp} [{record.levelname:<7}] {record.getMessage()}"


def setup_logger(level: str = "INFO", log_file: str = "tgtg_bot.log") -> logging.Logger:
    """
    Configure and return the application logger.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR).
        log_file: Path to the log file.

    Returns:
        Configured logger instance.
    """
    logger = logging.getLogger("tgtg_bot")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Clear any existing handlers
    logger.handlers.clear()

    # Console handler with colors
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(ColoredFormatter())
    logger.addHandler(console_handler)

    # File handler (plain text)
    try:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(FileFormatter())
        logger.addHandler(file_handler)
    except (OSError, PermissionError) as e:
        logger.warning(f"Could not create log file '{log_file}': {e}")

    return logger


def get_logger() -> logging.Logger:
    """Get the existing bot logger (or create a default one)."""
    logger = logging.getLogger("tgtg_bot")
    if not logger.handlers:
        return setup_logger()
    return logger
