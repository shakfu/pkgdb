"""PyPI stats API client functions."""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from json import JSONDecodeError
from urllib.error import URLError

import pypistats  # type: ignore[import-untyped]

from .types import CategoryDownloads, EnvSummary, PackageStats

logger = logging.getLogger("pkgdb")

# Default number of parallel workers for API calls
DEFAULT_MAX_WORKERS = 5

# Exceptions that indicate API/network errors (not programming bugs)
_API_ERRORS = (
    JSONDecodeError,  # Malformed JSON response
    URLError,  # Network/connection errors
    ValueError,  # Invalid data format
    KeyError,  # Missing expected keys
    TypeError,  # Unexpected data types
    OSError,  # Network-related OS errors
)


def fetch_package_stats(package_name: str) -> PackageStats | None:
    """Fetch download statistics for a package from PyPI.

    Returns None if the package doesn't exist or the API is unreachable.
    """
    try:
        recent_json = pypistats.recent(package_name, format="json")
        recent_data = json.loads(recent_json)

        data = recent_data.get("data", {})

        overall_json = pypistats.overall(package_name, format="json")
        overall_data = json.loads(overall_json)

        total = 0
        for item in overall_data.get("data", []):
            if item.get("category") == "without_mirrors":
                total = item.get("downloads", 0)
                break

        stats: PackageStats = {
            "last_day": data.get("last_day", 0),
            "last_week": data.get("last_week", 0),
            "last_month": data.get("last_month", 0),
            "total": total,
        }

        return stats
    except _API_ERRORS as e:
        logger.warning("Error fetching stats for %s: %s", package_name, e)
        return None


def fetch_python_versions(package_name: str) -> list[CategoryDownloads] | None:
    """Fetch download breakdown by Python version for a package.

    Returns None if the package doesn't exist or the API is unreachable.
    """
    try:
        result = pypistats.python_minor(package_name, format="json")
        data = json.loads(result)
        versions: list[CategoryDownloads] = data.get("data", [])
        # Sort by downloads descending
        return sorted(versions, key=lambda x: x.get("downloads", 0), reverse=True)
    except _API_ERRORS as e:
        logger.warning("Error fetching Python versions for %s: %s", package_name, e)
        return None


def fetch_os_stats(package_name: str) -> list[CategoryDownloads] | None:
    """Fetch download breakdown by operating system for a package.

    Returns None if the package doesn't exist or the API is unreachable.
    """
    try:
        result = pypistats.system(package_name, format="json")
        data = json.loads(result)
        systems: list[CategoryDownloads] = data.get("data", [])
        # Sort by downloads descending
        return sorted(systems, key=lambda x: x.get("downloads", 0), reverse=True)
    except _API_ERRORS as e:
        logger.warning("Error fetching OS stats for %s: %s", package_name, e)
        return None


def aggregate_env_stats(
    packages: list[str], max_workers: int = DEFAULT_MAX_WORKERS
) -> EnvSummary:
    """Aggregate Python version and OS distribution across all packages.

    Uses parallel fetching for improved performance.

    Args:
        packages: List of package names to aggregate.
        max_workers: Maximum number of parallel API requests.

    Returns:
        Dict with 'python_versions' and 'os_distribution' lists of (name, count) tuples.
    """
    py_totals: dict[str, int] = {}
    os_totals: dict[str, int] = {}

    def fetch_env_for_package(
        pkg: str,
    ) -> tuple[list[CategoryDownloads] | None, list[CategoryDownloads] | None]:
        """Fetch both Python versions and OS stats for a package."""
        return fetch_python_versions(pkg), fetch_os_stats(pkg)

    # Fetch all package env data in parallel
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_env_for_package, pkg): pkg for pkg in packages}

        for future in as_completed(futures):
            py_data, os_data = future.result()

            if py_data:
                for item in py_data:
                    version = item.get("category", "unknown")
                    if version and version != "null":
                        py_totals[version] = py_totals.get(version, 0) + item.get(
                            "downloads", 0
                        )

            if os_data:
                for item in os_data:
                    os_name = item.get("category", "unknown")
                    if os_name == "null":
                        os_name = "Unknown"
                    os_totals[os_name] = os_totals.get(os_name, 0) + item.get(
                        "downloads", 0
                    )

    # Convert to sorted lists
    py_versions = sorted(py_totals.items(), key=lambda x: x[1], reverse=True)
    os_distribution = sorted(os_totals.items(), key=lambda x: x[1], reverse=True)

    return {
        "python_versions": py_versions,
        "os_distribution": os_distribution,
    }


def fetch_all_package_stats(
    packages: list[str], max_workers: int = DEFAULT_MAX_WORKERS
) -> dict[str, PackageStats | None]:
    """Fetch stats for multiple packages in parallel.

    Args:
        packages: List of package names to fetch.
        max_workers: Maximum number of parallel API requests.

    Returns:
        Dict mapping package names to their stats (or None if fetch failed).
    """
    results: dict[str, PackageStats | None] = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_package_stats, pkg): pkg for pkg in packages}

        for future in as_completed(futures):
            pkg = futures[future]
            results[pkg] = future.result()

    return results
