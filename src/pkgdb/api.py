"""PyPI stats API client functions."""

import json
from typing import Any

import pypistats  # type: ignore[import-untyped]


def fetch_package_stats(package_name: str) -> dict[str, Any] | None:
    """Fetch download statistics for a package from PyPI."""
    try:
        recent_json = pypistats.recent(package_name, format="json")
        recent_data = json.loads(recent_json)

        data = recent_data.get("data", {})
        stats: dict[str, Any] = {
            "last_day": data.get("last_day", 0),
            "last_week": data.get("last_week", 0),
            "last_month": data.get("last_month", 0),
        }

        overall_json = pypistats.overall(package_name, format="json")
        overall_data = json.loads(overall_json)

        total = 0
        for item in overall_data.get("data", []):
            if item.get("category") == "without_mirrors":
                total = item.get("downloads", 0)
                break
        stats["total"] = total

        return stats
    except Exception as e:
        print(f"  Error fetching stats for {package_name}: {e}")
        return None


def fetch_python_versions(package_name: str) -> list[dict[str, Any]] | None:
    """Fetch download breakdown by Python version for a package."""
    try:
        result = pypistats.python_minor(package_name, format="json")
        data = json.loads(result)
        versions: list[dict[str, Any]] = data.get("data", [])
        # Sort by downloads descending
        return sorted(versions, key=lambda x: x.get("downloads", 0), reverse=True)
    except Exception as e:
        print(f"  Error fetching Python versions for {package_name}: {e}")
        return None


def fetch_os_stats(package_name: str) -> list[dict[str, Any]] | None:
    """Fetch download breakdown by operating system for a package."""
    try:
        result = pypistats.system(package_name, format="json")
        data = json.loads(result)
        systems: list[dict[str, Any]] = data.get("data", [])
        # Sort by downloads descending
        return sorted(systems, key=lambda x: x.get("downloads", 0), reverse=True)
    except Exception as e:
        print(f"  Error fetching OS stats for {package_name}: {e}")
        return None


def aggregate_env_stats(packages: list[str]) -> dict[str, list[tuple[str, int]]]:
    """Aggregate Python version and OS distribution across all packages.

    Returns dict with 'python_versions' and 'os_distribution' lists of (name, count) tuples.
    """
    py_totals: dict[str, int] = {}
    os_totals: dict[str, int] = {}

    for pkg in packages:
        py_data = fetch_python_versions(pkg)
        if py_data:
            for item in py_data:
                version = item.get("category", "unknown")
                if version and version != "null":
                    py_totals[version] = py_totals.get(version, 0) + item.get(
                        "downloads", 0
                    )

        os_data = fetch_os_stats(pkg)
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
