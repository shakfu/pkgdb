"""Database operations for pkgdb."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Generator

from .types import CategoryDownloads, PackageStats
from .utils import calculate_growth


def get_config_dir() -> Path:
    """Get the pkgdb config directory (~/.pkgdb), creating it if needed."""
    config_dir = Path.home() / ".pkgdb"
    config_dir.mkdir(exist_ok=True)
    return config_dir


DEFAULT_DB_FILE = str(get_config_dir() / "pkg.db")
DEFAULT_REPORT_FILE = str(get_config_dir() / "report.html")


def get_db_connection(db_path: str) -> sqlite3.Connection:
    """Create and return a database connection."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def get_db(db_path: str) -> Generator[sqlite3.Connection, None, None]:
    """Context manager for database connections with automatic init and cleanup."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        init_db(conn)
        yield conn
    finally:
        conn.close()


def init_db(conn: sqlite3.Connection) -> None:
    """Initialize the database schema."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS package_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            package_name TEXT NOT NULL,
            fetch_date TEXT NOT NULL,
            last_day INTEGER,
            last_week INTEGER,
            last_month INTEGER,
            total INTEGER,
            UNIQUE(package_name, fetch_date)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS packages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            package_name TEXT NOT NULL UNIQUE,
            added_date TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fetch_attempts (
            package_name TEXT PRIMARY KEY,
            attempt_time TEXT NOT NULL,
            success INTEGER NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS python_version_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            package_name TEXT NOT NULL,
            fetch_date TEXT NOT NULL,
            category TEXT NOT NULL,
            downloads INTEGER NOT NULL,
            UNIQUE(package_name, fetch_date, category)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS os_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            package_name TEXT NOT NULL,
            fetch_date TEXT NOT NULL,
            category TEXT NOT NULL,
            downloads INTEGER NOT NULL,
            UNIQUE(package_name, fetch_date, category)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_package_name
        ON package_stats(package_name)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_pyver_package_name
        ON python_version_stats(package_name)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_os_package_name
        ON os_stats(package_name)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_fetch_date
        ON package_stats(fetch_date)
    """)
    conn.commit()


def add_package(conn: sqlite3.Connection, name: str) -> bool:
    """Add a package to the tracking database.

    Returns True if package was added, False if it already exists.
    """
    added_date = datetime.now().strftime("%Y-%m-%d")
    try:
        conn.execute(
            "INSERT INTO packages (package_name, added_date) VALUES (?, ?)",
            (name, added_date),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def remove_package(conn: sqlite3.Connection, name: str) -> bool:
    """Remove a package from the tracking database.

    Returns True if package was removed, False if it didn't exist.
    """
    cursor = conn.execute(
        "DELETE FROM packages WHERE package_name = ?",
        (name,),
    )
    conn.commit()
    return cursor.rowcount > 0


def get_packages(conn: sqlite3.Connection) -> list[str]:
    """Get list of tracked package names from the database."""
    cursor = conn.execute("SELECT package_name FROM packages ORDER BY package_name")
    return [row["package_name"] for row in cursor.fetchall()]


def record_fetch_attempt(
    conn: sqlite3.Connection,
    package_name: str,
    success: bool,
    commit: bool = True,
) -> None:
    """Record a fetch attempt for a package.

    Args:
        conn: Database connection.
        package_name: Name of the package.
        success: Whether the fetch was successful.
        commit: If True, commit the transaction.
    """
    attempt_time = datetime.now().isoformat()
    conn.execute(
        """
        INSERT OR REPLACE INTO fetch_attempts (package_name, attempt_time, success)
        VALUES (?, ?, ?)
        """,
        (package_name, attempt_time, 1 if success else 0),
    )
    if commit:
        conn.commit()


def get_packages_needing_update(conn: sqlite3.Connection, hours: int = 24) -> list[str]:
    """Get packages that haven't been fetched in the last N hours.

    Args:
        conn: Database connection.
        hours: Number of hours since last attempt to consider stale.

    Returns:
        List of package names that need updating.
    """
    # Get all tracked packages
    all_packages = get_packages(conn)
    if not all_packages:
        return []

    # Get packages with recent attempts
    cursor = conn.execute(
        """
        SELECT package_name FROM fetch_attempts
        WHERE datetime(attempt_time) > datetime('now', ?) AND success = 1
        """,
        (f"-{hours} hours",),
    )
    recent_attempts = {row["package_name"] for row in cursor.fetchall()}

    # Return packages without recent attempts
    return [p for p in all_packages if p not in recent_attempts]


def get_next_update_seconds(conn: sqlite3.Connection, hours: int = 24) -> float | None:
    """Get seconds until the next package becomes eligible for update.

    Finds the oldest successful attempt within the cooldown window and computes
    how many seconds remain until it expires.

    Returns:
        Seconds until the next package is eligible, or None if no packages are throttled.
    """
    cursor = conn.execute(
        """
        SELECT MIN(attempt_time) as earliest
        FROM fetch_attempts
        WHERE datetime(attempt_time) > datetime('now', ?) AND success = 1
        """,
        (f"-{hours} hours",),
    )
    row = cursor.fetchone()
    if not row or not row["earliest"]:
        return None

    earliest = datetime.fromisoformat(row["earliest"])
    expires_at = earliest + timedelta(hours=hours)
    remaining = (expires_at - datetime.now()).total_seconds()
    return max(0.0, remaining)


def store_env_stats(
    conn: sqlite3.Connection,
    package_name: str,
    python_versions: list[CategoryDownloads] | None = None,
    os_data: list[CategoryDownloads] | None = None,
    commit: bool = True,
) -> None:
    """Store environment stats (Python versions, OS distribution) in the database.

    Args:
        conn: Database connection.
        package_name: Name of the package.
        python_versions: Python version download breakdown, or None.
        os_data: OS distribution download breakdown, or None.
        commit: If True, commit the transaction.
    """
    fetch_date = datetime.now().strftime("%Y-%m-%d")
    if python_versions:
        for item in python_versions:
            conn.execute(
                """
                INSERT OR REPLACE INTO python_version_stats
                (package_name, fetch_date, category, downloads)
                VALUES (?, ?, ?, ?)
                """,
                (package_name, fetch_date, item["category"], item["downloads"]),
            )
    if os_data:
        for item in os_data:
            conn.execute(
                """
                INSERT OR REPLACE INTO os_stats
                (package_name, fetch_date, category, downloads)
                VALUES (?, ?, ?, ?)
                """,
                (package_name, fetch_date, item["category"], item["downloads"]),
            )
    if commit:
        conn.commit()


def get_cached_python_versions(
    conn: sqlite3.Connection, package_name: str
) -> list[CategoryDownloads] | None:
    """Get cached Python version stats for a package.

    Returns the most recent fetch date's data, sorted by downloads descending.
    Returns None if no cached data exists.
    """
    cursor = conn.execute(
        """
        SELECT category, downloads FROM python_version_stats
        WHERE package_name = ? AND fetch_date = (
            SELECT MAX(fetch_date) FROM python_version_stats WHERE package_name = ?
        )
        ORDER BY downloads DESC
        """,
        (package_name, package_name),
    )
    rows = cursor.fetchall()
    if not rows:
        return None
    return [{"category": row["category"], "downloads": row["downloads"]} for row in rows]


def get_cached_os_stats(
    conn: sqlite3.Connection, package_name: str
) -> list[CategoryDownloads] | None:
    """Get cached OS distribution stats for a package.

    Returns the most recent fetch date's data, sorted by downloads descending.
    Returns None if no cached data exists.
    """
    cursor = conn.execute(
        """
        SELECT category, downloads FROM os_stats
        WHERE package_name = ? AND fetch_date = (
            SELECT MAX(fetch_date) FROM os_stats WHERE package_name = ?
        )
        ORDER BY downloads DESC
        """,
        (package_name, package_name),
    )
    rows = cursor.fetchall()
    if not rows:
        return None
    return [{"category": row["category"], "downloads": row["downloads"]} for row in rows]


def get_cached_env_summary(
    conn: sqlite3.Connection,
) -> dict[str, list[tuple[str, int]]] | None:
    """Aggregate cached environment stats across all packages.

    Returns dict with 'python_versions' and 'os_distribution' keys,
    each mapping to a list of (category, total_downloads) tuples sorted descending.
    Returns None if no cached data exists.
    """
    # Aggregate Python versions from most recent fetch per package
    py_cursor = conn.execute(
        """
        SELECT pv.category, SUM(pv.downloads) as total
        FROM python_version_stats pv
        INNER JOIN (
            SELECT package_name, MAX(fetch_date) as max_date
            FROM python_version_stats GROUP BY package_name
        ) latest ON pv.package_name = latest.package_name
            AND pv.fetch_date = latest.max_date
        GROUP BY pv.category
        ORDER BY total DESC
        """
    )
    py_rows = py_cursor.fetchall()

    os_cursor = conn.execute(
        """
        SELECT os.category, SUM(os.downloads) as total
        FROM os_stats os
        INNER JOIN (
            SELECT package_name, MAX(fetch_date) as max_date
            FROM os_stats GROUP BY package_name
        ) latest ON os.package_name = latest.package_name
            AND os.fetch_date = latest.max_date
        GROUP BY os.category
        ORDER BY total DESC
        """
    )
    os_rows = os_cursor.fetchall()

    if not py_rows and not os_rows:
        return None

    return {
        "python_versions": [(row["category"], row["total"]) for row in py_rows],
        "os_distribution": [(row["category"], row["total"]) for row in os_rows],
    }


def store_stats(
    conn: sqlite3.Connection,
    package_name: str,
    stats: PackageStats,
    commit: bool = True,
) -> None:
    """Store package statistics in the database.

    Args:
        conn: Database connection.
        package_name: Name of the package.
        stats: Package statistics to store.
        commit: If True, commit the transaction. Set to False for batch operations.
    """
    fetch_date = datetime.now().strftime("%Y-%m-%d")
    conn.execute(
        """
        INSERT OR REPLACE INTO package_stats
        (package_name, fetch_date, last_day, last_week, last_month, total)
        VALUES (?, ?, ?, ?, ?, ?)
    """,
        (
            package_name,
            fetch_date,
            stats.get("last_day"),
            stats.get("last_week"),
            stats.get("last_month"),
            stats.get("total"),
        ),
    )
    if commit:
        conn.commit()


def store_stats_batch(
    conn: sqlite3.Connection, stats_list: list[tuple[str, PackageStats]]
) -> int:
    """Store multiple package statistics in a single transaction.

    More efficient than calling store_stats() multiple times as it uses
    a single commit for all inserts.

    Args:
        conn: Database connection.
        stats_list: List of (package_name, stats) tuples to store.

    Returns:
        Number of packages stored.
    """
    fetch_date = datetime.now().strftime("%Y-%m-%d")
    count = 0

    for package_name, stats in stats_list:
        conn.execute(
            """
            INSERT OR REPLACE INTO package_stats
            (package_name, fetch_date, last_day, last_week, last_month, total)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            (
                package_name,
                fetch_date,
                stats.get("last_day"),
                stats.get("last_week"),
                stats.get("last_month"),
                stats.get("total"),
            ),
        )
        count += 1

    conn.commit()  # Single commit for all
    return count


def get_latest_stats(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Get the most recent stats for all packages, ordered by total downloads."""
    cursor = conn.execute("""
        SELECT ps.*
        FROM package_stats ps
        INNER JOIN (
            SELECT package_name, MAX(fetch_date) as max_date
            FROM package_stats
            GROUP BY package_name
        ) latest ON ps.package_name = latest.package_name
                AND ps.fetch_date = latest.max_date
        ORDER BY ps.total DESC
    """)
    return [dict(row) for row in cursor.fetchall()]


def get_package_history(
    conn: sqlite3.Connection, package_name: str, limit: int = 30
) -> list[dict[str, Any]]:
    """Get historical stats for a specific package, ordered by date descending."""
    cursor = conn.execute(
        """
        SELECT * FROM package_stats
        WHERE package_name = ?
        ORDER BY fetch_date DESC
        LIMIT ?
    """,
        (package_name, limit),
    )
    return [dict(row) for row in cursor.fetchall()]


def get_all_history(
    conn: sqlite3.Connection, limit_per_package: int = 30
) -> dict[str, list[dict[str, Any]]]:
    """Get historical stats for all packages, grouped by package name."""
    cursor = conn.execute(
        """
        SELECT * FROM (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY package_name ORDER BY fetch_date DESC) as rn
            FROM package_stats
        ) WHERE rn <= ?
        ORDER BY package_name, fetch_date ASC
    """,
        (limit_per_package,),
    )

    history: dict[str, list[dict[str, Any]]] = {}
    for row in cursor.fetchall():
        row_dict = dict(row)
        pkg = row_dict["package_name"]
        if pkg not in history:
            history[pkg] = []
        history[pkg].append(row_dict)
    return history


def get_stats_with_growth(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Get latest stats with week-over-week and month-over-month growth metrics.

    Uses a single query to fetch all history, avoiding N+1 query pattern.
    """
    stats = get_latest_stats(conn)
    if not stats:
        return stats

    # Fetch all history in ONE query instead of N queries
    all_history = get_all_history(conn, limit_per_package=31)

    for s in stats:
        pkg = s["package_name"]
        # History is sorted ASC by date, reverse for DESC order
        history = list(reversed(all_history.get(pkg, [])))

        # Find stats from ~7 days ago and ~30 days ago
        week_ago = None
        month_ago = None

        for h in history[1:]:  # Skip the first (current) entry
            days_diff = (
                datetime.strptime(s["fetch_date"], "%Y-%m-%d")
                - datetime.strptime(h["fetch_date"], "%Y-%m-%d")
            ).days
            if week_ago is None and days_diff >= 7:
                week_ago = h
            if month_ago is None and days_diff >= 28:
                month_ago = h
                break

        # Calculate growth
        s["week_growth"] = calculate_growth(
            s["last_week"], week_ago["last_week"] if week_ago else None
        )
        s["month_growth"] = calculate_growth(
            s["total"], month_ago["total"] if month_ago else None
        )

    return stats


def cleanup_orphaned_stats(conn: sqlite3.Connection) -> int:
    """Remove stats for packages that are no longer being tracked.

    Returns the number of orphaned records deleted.
    """
    cursor = conn.execute("""
        DELETE FROM package_stats
        WHERE package_name NOT IN (SELECT package_name FROM packages)
    """)
    deleted = cursor.rowcount
    conn.execute("""
        DELETE FROM python_version_stats
        WHERE package_name NOT IN (SELECT package_name FROM packages)
    """)
    conn.execute("""
        DELETE FROM os_stats
        WHERE package_name NOT IN (SELECT package_name FROM packages)
    """)
    conn.commit()
    return deleted


def prune_old_stats(conn: sqlite3.Connection, days: int = 365) -> int:
    """Remove stats older than the specified number of days.

    Args:
        conn: Database connection.
        days: Delete stats older than this many days (default: 365).

    Returns:
        Number of records deleted.
    """
    cursor = conn.execute(
        """
        DELETE FROM package_stats
        WHERE fetch_date < date('now', ?)
    """,
        (f"-{days} days",),
    )
    deleted = cursor.rowcount
    conn.execute(
        "DELETE FROM python_version_stats WHERE fetch_date < date('now', ?)",
        (f"-{days} days",),
    )
    conn.execute(
        "DELETE FROM os_stats WHERE fetch_date < date('now', ?)",
        (f"-{days} days",),
    )
    conn.commit()
    return deleted


def get_database_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    """Get database statistics.

    Returns:
        Dict with package_count, record_count, first_fetch, and last_fetch.
    """
    # Get package count
    cursor = conn.execute("SELECT COUNT(*) as count FROM packages")
    package_count = cursor.fetchone()["count"]

    # Get record count
    cursor = conn.execute("SELECT COUNT(*) as count FROM package_stats")
    record_count = cursor.fetchone()["count"]

    # Get date range
    cursor = conn.execute(
        "SELECT MIN(fetch_date) as first, MAX(fetch_date) as last FROM package_stats"
    )
    row = cursor.fetchone()
    first_fetch = row["first"]
    last_fetch = row["last"]

    return {
        "package_count": package_count,
        "record_count": record_count,
        "first_fetch": first_fetch,
        "last_fetch": last_fetch,
    }
