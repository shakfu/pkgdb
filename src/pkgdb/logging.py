"""Logging configuration for pkgdb."""

import logging
import sys

# Create package logger
logger = logging.getLogger("pkgdb")

# Default format for console output
DEFAULT_FORMAT = "%(message)s"
VERBOSE_FORMAT = "%(levelname)s: %(message)s"


def setup_logging(verbose: bool = False, quiet: bool = False) -> None:
    """Configure logging for the CLI.

    Args:
        verbose: If True, show DEBUG level messages with level prefix.
        quiet: If True, suppress INFO messages (only show WARNING+).
    """
    # Remove existing handlers
    logger.handlers.clear()

    # Determine log level
    if quiet:
        level = logging.WARNING
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO

    # Create console handler
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)

    # Use verbose format if verbose mode
    fmt = VERBOSE_FORMAT if verbose else DEFAULT_FORMAT
    handler.setFormatter(logging.Formatter(fmt))

    logger.addHandler(handler)
    logger.setLevel(level)


def get_logger() -> logging.Logger:
    """Get the pkgdb logger."""
    return logger
