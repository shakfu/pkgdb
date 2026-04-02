"""Configuration file support for pkgdb.

Loads settings from ~/.pkgdb/config.toml, providing persistent defaults
that CLI flags can override.
"""

import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("pkgdb")

# Use tomllib (3.11+) or tomli (3.10 fallback)
if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:
        tomllib = None  # type: ignore[assignment]


def get_config_path() -> Path:
    """Get the path to the config file (~/.pkgdb/config.toml)."""
    return Path.home() / ".pkgdb" / "config.toml"


@dataclass
class PkgdbConfig:
    """Configuration loaded from config.toml.

    All fields are optional -- missing fields use the application defaults.
    CLI flags always override config values.
    """

    # [defaults]
    database: str | None = None
    github: bool = False
    environment: bool = False
    no_browser: bool = False
    sort_by: str = "total"

    # [report]
    report_output: str | None = None

    # [init]
    pypi_user: str | None = None

    # Raw parsed data for extensibility
    _raw: dict[str, Any] = field(default_factory=dict, repr=False)


def load_config(config_path: Path | None = None) -> PkgdbConfig:
    """Load configuration from TOML file.

    Args:
        config_path: Path to config file. If None, uses the default location.

    Returns:
        PkgdbConfig with values from the file, or defaults if file doesn't exist.
    """
    if config_path is None:
        config_path = get_config_path()

    if not config_path.exists():
        return PkgdbConfig()

    if tomllib is None:
        logger.debug(
            "config.toml found but tomli not installed (Python 3.10). "
            "Install 'tomli' or upgrade to Python 3.11+ for config file support."
        )
        return PkgdbConfig()

    try:
        with open(config_path, "rb") as f:
            raw = tomllib.load(f)
    except Exception as e:
        logger.warning("Could not parse %s: %s", config_path, e)
        return PkgdbConfig()

    defaults = raw.get("defaults", {})
    report = raw.get("report", {})
    init_section = raw.get("init", {})

    return PkgdbConfig(
        database=defaults.get("database"),
        github=defaults.get("github", False),
        environment=defaults.get("environment", False),
        no_browser=defaults.get("no_browser", False),
        sort_by=defaults.get("sort_by", "total"),
        report_output=report.get("output"),
        pypi_user=init_section.get("pypi_user"),
        _raw=raw,
    )
