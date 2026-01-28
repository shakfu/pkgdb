"""Type definitions for pkgdb using TypedDict for known structures."""

from typing import TypedDict


class PackageStats(TypedDict):
    """Download statistics for a package."""

    last_day: int
    last_week: int
    last_month: int
    total: int


class CategoryDownloads(TypedDict):
    """Downloads breakdown by category (Python version or OS)."""

    category: str
    downloads: int


class EnvSummary(TypedDict):
    """Aggregated environment statistics."""

    python_versions: list[tuple[str, int]]
    os_distribution: list[tuple[str, int]]


class HistoryRecord(TypedDict):
    """Historical stats record from database."""

    id: int
    package_name: str
    fetch_date: str
    last_day: int | None
    last_week: int | None
    last_month: int | None
    total: int | None


class StatsWithGrowth(TypedDict, total=False):
    """Stats record with optional growth metrics."""

    id: int
    package_name: str
    fetch_date: str
    last_day: int | None
    last_week: int | None
    last_month: int | None
    total: int | None
    week_growth: float | None
    month_growth: float | None


class DatabaseInfo(TypedDict):
    """Database statistics and metadata."""

    package_count: int
    record_count: int
    first_fetch: str | None
    last_fetch: str | None
    db_size_bytes: int
