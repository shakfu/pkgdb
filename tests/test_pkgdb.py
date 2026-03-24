"""Tests for pkgdb - PyPI package download statistics tracker."""

import json
import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from pkgdb import (
    get_db_connection,
    get_db,
    init_db,
    load_packages,
    add_package,
    remove_package,
    get_packages,
    get_packages_needing_update,
    record_fetch_attempt,
    import_packages_from_file,
    load_packages_from_file,
    store_stats,
    store_stats_batch,
    get_latest_stats,
    get_package_history,
    get_all_history,
    get_database_stats,
    calculate_growth,
    make_sparkline,
    export_csv,
    export_json,
    export_markdown,
    fetch_package_stats,
    fetch_python_versions,
    fetch_os_stats,
    aggregate_env_stats,
    make_svg_pie_chart,
    generate_html_report,
    generate_package_html_report,
    generate_badge_svg,
    generate_downloads_badge,
    BADGE_COLORS,
    main,
    get_config_dir,
    DEFAULT_DB_FILE,
    DEFAULT_PACKAGES_FILE,
    DEFAULT_REPORT_FILE,
    PackageStatsService,
    PackageInfo,
    FetchResult,
    PackageDetails,
    SyncResult,
    DatabaseInfo,
    validate_package_name,
    validate_output_path,
    fetch_user_packages,
    check_package_exists,
    parse_date_arg,
)


@pytest.fixture
def temp_db():
    """Create a temporary database file."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def temp_packages_file():
    """Create a temporary packages.json file."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as f:
        json.dump({"published": ["package-a", "package-b"]}, f)
        packages_path = f.name
    yield packages_path
    Path(packages_path).unlink(missing_ok=True)


@pytest.fixture
def db_conn(temp_db):
    """Create an initialized database connection."""
    conn = get_db_connection(temp_db)
    init_db(conn)
    yield conn
    conn.close()


class TestDatabaseOperations:
    """Tests for database initialization and operations."""

    def test_get_db_connection_creates_connection(self, temp_db):
        """get_db_connection should return a working connection."""
        conn = get_db_connection(temp_db)
        assert conn is not None
        assert isinstance(conn, sqlite3.Connection)
        conn.close()

    def test_get_db_connection_uses_row_factory(self, temp_db):
        """get_db_connection should set row_factory to sqlite3.Row."""
        conn = get_db_connection(temp_db)
        assert conn.row_factory == sqlite3.Row
        conn.close()

    def test_init_db_creates_table(self, temp_db):
        """init_db should create the package_stats table."""
        conn = get_db_connection(temp_db)
        init_db(conn)

        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='package_stats'"
        )
        result = cursor.fetchone()
        assert result is not None
        assert result["name"] == "package_stats"
        conn.close()

    def test_init_db_creates_indexes(self, temp_db):
        """init_db should create indexes on package_name and fetch_date."""
        conn = get_db_connection(temp_db)
        init_db(conn)

        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )
        indexes = {row["name"] for row in cursor.fetchall()}
        assert "idx_package_name" in indexes
        assert "idx_fetch_date" in indexes
        conn.close()

    def test_init_db_idempotent(self, temp_db):
        """init_db should be safe to call multiple times."""
        conn = get_db_connection(temp_db)
        init_db(conn)
        init_db(conn)  # Should not raise

        cursor = conn.execute(
            "SELECT COUNT(*) as count FROM sqlite_master WHERE type='table' AND name='package_stats'"
        )
        assert cursor.fetchone()["count"] == 1
        conn.close()

    def test_init_db_creates_packages_table(self, temp_db):
        """init_db should create the packages table."""
        conn = get_db_connection(temp_db)
        init_db(conn)

        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='packages'"
        )
        result = cursor.fetchone()
        assert result is not None
        assert result["name"] == "packages"
        conn.close()

    def test_get_db_context_manager(self, temp_db):
        """get_db should provide a context manager that auto-initializes and closes."""
        with get_db(temp_db) as conn:
            # Should be initialized - tables should exist
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='package_stats'"
            )
            assert cursor.fetchone() is not None

            # Should be usable
            add_package(conn, "test-package")
            packages = get_packages(conn)
            assert "test-package" in packages

        # Connection should be closed after context
        # Verify by trying to use it (should fail)
        import sqlite3
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")

    def test_get_db_closes_on_exception(self, temp_db):
        """get_db should close connection even when exception occurs."""
        conn_ref = None
        try:
            with get_db(temp_db) as conn:
                conn_ref = conn
                raise ValueError("Test exception")
        except ValueError:
            pass

        # Connection should be closed
        import sqlite3
        with pytest.raises(sqlite3.ProgrammingError):
            conn_ref.execute("SELECT 1")


class TestPackageManagement:
    """Tests for package management functions."""

    def test_add_package_success(self, db_conn):
        """add_package should insert a package and return True."""
        result = add_package(db_conn, "test-package")
        assert result is True

        cursor = db_conn.execute(
            "SELECT package_name FROM packages WHERE package_name = ?",
            ("test-package",)
        )
        row = cursor.fetchone()
        assert row is not None
        assert row["package_name"] == "test-package"

    def test_add_package_duplicate(self, db_conn):
        """add_package should return False for duplicate package."""
        add_package(db_conn, "test-package")
        result = add_package(db_conn, "test-package")
        assert result is False

        cursor = db_conn.execute(
            "SELECT COUNT(*) as count FROM packages WHERE package_name = ?",
            ("test-package",)
        )
        assert cursor.fetchone()["count"] == 1

    def test_remove_package_success(self, db_conn):
        """remove_package should delete a package and return True."""
        add_package(db_conn, "test-package")
        result = remove_package(db_conn, "test-package")
        assert result is True

        cursor = db_conn.execute(
            "SELECT COUNT(*) as count FROM packages WHERE package_name = ?",
            ("test-package",)
        )
        assert cursor.fetchone()["count"] == 0

    def test_remove_package_not_found(self, db_conn):
        """remove_package should return False if package doesn't exist."""
        result = remove_package(db_conn, "nonexistent")
        assert result is False

    def test_get_packages_empty(self, db_conn):
        """get_packages should return empty list when no packages."""
        packages = get_packages(db_conn)
        assert packages == []

    def test_get_packages_returns_list(self, db_conn):
        """get_packages should return list of package names."""
        add_package(db_conn, "package-b")
        add_package(db_conn, "package-a")
        add_package(db_conn, "package-c")

        packages = get_packages(db_conn)
        assert packages == ["package-a", "package-b", "package-c"]  # Sorted

    def test_import_packages_from_json(self, db_conn, temp_packages_file):
        """import_packages_from_file should import packages from JSON."""
        added, skipped = import_packages_from_file(db_conn, temp_packages_file)
        assert added == 2
        assert skipped == 0

        packages = get_packages(db_conn)
        assert "package-a" in packages
        assert "package-b" in packages

    def test_import_packages_skips_duplicates(self, db_conn, temp_packages_file):
        """import_packages_from_file should skip existing packages."""
        add_package(db_conn, "package-a")

        added, skipped = import_packages_from_file(db_conn, temp_packages_file)
        assert added == 1
        assert skipped == 1

    def test_load_packages_from_text_file(self):
        """load_packages_from_file should parse plain text files."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("requests\n")
            f.write("flask\n")
            f.write("# this is a comment\n")
            f.write("  django  \n")
            f.write("\n")  # empty line
            path = f.name

        try:
            packages = load_packages_from_file(path)
            assert packages == ["requests", "flask", "django"]
        finally:
            Path(path).unlink(missing_ok=True)

    def test_load_packages_from_json_list(self):
        """load_packages_from_file should parse JSON array."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(["requests", "flask"], f)
            path = f.name

        try:
            packages = load_packages_from_file(path)
            assert packages == ["requests", "flask"]
        finally:
            Path(path).unlink(missing_ok=True)

    def test_load_packages_from_json_object(self):
        """load_packages_from_file should parse JSON object with packages key."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"packages": ["requests", "flask"]}, f)
            path = f.name

        try:
            packages = load_packages_from_file(path)
            assert packages == ["requests", "flask"]
        finally:
            Path(path).unlink(missing_ok=True)


class TestLoadPackages:
    """Tests for loading packages from JSON."""

    def test_load_packages_returns_list(self, temp_packages_file):
        """load_packages should return a list of package names."""
        packages = load_packages(temp_packages_file)
        assert isinstance(packages, list)
        assert packages == ["package-a", "package-b"]

    def test_load_packages_empty_published(self):
        """load_packages should return empty list if published key is missing."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump({"other_key": ["something"]}, f)
            path = f.name

        try:
            packages = load_packages(path)
            assert packages == [] or packages is None
        finally:
            Path(path).unlink(missing_ok=True)

    def test_load_packages_file_not_found(self):
        """load_packages should raise FileNotFoundError for missing files."""
        with pytest.raises(FileNotFoundError):
            load_packages("/nonexistent/packages.json")


class TestStoreAndRetrieveStats:
    """Tests for storing and retrieving statistics."""

    def test_store_stats_inserts_record(self, db_conn):
        """store_stats should insert a record into the database."""
        stats = {
            "last_day": 100,
            "last_week": 700,
            "last_month": 3000,
            "total": 50000,
        }
        store_stats(db_conn, "test-package", stats)

        cursor = db_conn.execute(
            "SELECT * FROM package_stats WHERE package_name = ?",
            ("test-package",),
        )
        row = cursor.fetchone()
        assert row is not None
        assert row["package_name"] == "test-package"
        assert row["last_day"] == 100
        assert row["last_week"] == 700
        assert row["last_month"] == 3000
        assert row["total"] == 50000

    def test_store_stats_replaces_on_same_date(self, db_conn):
        """store_stats should replace stats for same package on same date."""
        stats1 = {"last_day": 100, "last_week": 700, "last_month": 3000, "total": 50000}
        stats2 = {"last_day": 200, "last_week": 1400, "last_month": 6000, "total": 60000}

        store_stats(db_conn, "test-package", stats1)
        store_stats(db_conn, "test-package", stats2)

        cursor = db_conn.execute(
            "SELECT COUNT(*) as count FROM package_stats WHERE package_name = ?",
            ("test-package",),
        )
        assert cursor.fetchone()["count"] == 1

        cursor = db_conn.execute(
            "SELECT total FROM package_stats WHERE package_name = ?",
            ("test-package",),
        )
        assert cursor.fetchone()["total"] == 60000

    def test_get_latest_stats_returns_most_recent(self, db_conn):
        """get_latest_stats should return only the most recent stats per package."""
        db_conn.execute("""
            INSERT INTO package_stats
            (package_name, fetch_date, last_day, last_week, last_month, total)
            VALUES
            ('pkg-a', '2024-01-01', 10, 70, 300, 1000),
            ('pkg-a', '2024-01-02', 20, 140, 600, 2000),
            ('pkg-b', '2024-01-01', 5, 35, 150, 500)
        """)
        db_conn.commit()

        stats = get_latest_stats(db_conn)
        assert len(stats) == 2

        pkg_a = next(s for s in stats if s["package_name"] == "pkg-a")
        assert pkg_a["fetch_date"] == "2024-01-02"
        assert pkg_a["total"] == 2000

    def test_get_latest_stats_ordered_by_total(self, db_conn):
        """get_latest_stats should return stats ordered by total downloads DESC."""
        db_conn.execute("""
            INSERT INTO package_stats
            (package_name, fetch_date, last_day, last_week, last_month, total)
            VALUES
            ('low-pkg', '2024-01-01', 1, 7, 30, 100),
            ('high-pkg', '2024-01-01', 100, 700, 3000, 10000),
            ('mid-pkg', '2024-01-01', 10, 70, 300, 1000)
        """)
        db_conn.commit()

        stats = get_latest_stats(db_conn)
        assert stats[0]["package_name"] == "high-pkg"
        assert stats[1]["package_name"] == "mid-pkg"
        assert stats[2]["package_name"] == "low-pkg"

    def test_get_latest_stats_empty_db(self, db_conn):
        """get_latest_stats should return empty list for empty database."""
        stats = get_latest_stats(db_conn)
        assert stats == []


class TestHistoricalData:
    """Tests for historical data retrieval and analysis."""

    def test_get_package_history_returns_records(self, db_conn):
        """get_package_history should return historical records for a package."""
        db_conn.execute("""
            INSERT INTO package_stats
            (package_name, fetch_date, last_day, last_week, last_month, total)
            VALUES
            ('pkg-a', '2024-01-01', 10, 70, 300, 1000),
            ('pkg-a', '2024-01-02', 20, 140, 600, 2000),
            ('pkg-a', '2024-01-03', 30, 210, 900, 3000),
            ('pkg-b', '2024-01-01', 5, 35, 150, 500)
        """)
        db_conn.commit()

        history = get_package_history(db_conn, "pkg-a")
        assert len(history) == 3
        # Should be ordered by date descending
        assert history[0]["fetch_date"] == "2024-01-03"
        assert history[2]["fetch_date"] == "2024-01-01"

    def test_get_package_history_respects_limit(self, db_conn):
        """get_package_history should respect the limit parameter."""
        db_conn.execute("""
            INSERT INTO package_stats
            (package_name, fetch_date, last_day, last_week, last_month, total)
            VALUES
            ('pkg-a', '2024-01-01', 10, 70, 300, 1000),
            ('pkg-a', '2024-01-02', 20, 140, 600, 2000),
            ('pkg-a', '2024-01-03', 30, 210, 900, 3000)
        """)
        db_conn.commit()

        history = get_package_history(db_conn, "pkg-a", limit=2)
        assert len(history) == 2

    def test_get_package_history_empty_for_unknown(self, db_conn):
        """get_package_history should return empty list for unknown package."""
        history = get_package_history(db_conn, "nonexistent")
        assert history == []

    def test_get_all_history_groups_by_package(self, db_conn):
        """get_all_history should return history grouped by package name."""
        db_conn.execute("""
            INSERT INTO package_stats
            (package_name, fetch_date, last_day, last_week, last_month, total)
            VALUES
            ('pkg-a', '2024-01-01', 10, 70, 300, 1000),
            ('pkg-a', '2024-01-02', 20, 140, 600, 2000),
            ('pkg-b', '2024-01-01', 5, 35, 150, 500)
        """)
        db_conn.commit()

        history = get_all_history(db_conn)
        assert "pkg-a" in history
        assert "pkg-b" in history
        assert len(history["pkg-a"]) == 2
        assert len(history["pkg-b"]) == 1

    def test_get_all_history_orders_by_date_asc(self, db_conn):
        """get_all_history should order records by date ascending within each package."""
        db_conn.execute("""
            INSERT INTO package_stats
            (package_name, fetch_date, last_day, last_week, last_month, total)
            VALUES
            ('pkg-a', '2024-01-03', 30, 210, 900, 3000),
            ('pkg-a', '2024-01-01', 10, 70, 300, 1000),
            ('pkg-a', '2024-01-02', 20, 140, 600, 2000)
        """)
        db_conn.commit()

        history = get_all_history(db_conn)
        dates = [h["fetch_date"] for h in history["pkg-a"]]
        assert dates == ["2024-01-01", "2024-01-02", "2024-01-03"]


class TestGrowthCalculation:
    """Tests for growth calculation functions."""

    def test_calculate_growth_positive(self):
        """calculate_growth should return positive percentage for increase."""
        assert calculate_growth(150, 100) == 50.0

    def test_calculate_growth_negative(self):
        """calculate_growth should return negative percentage for decrease."""
        assert calculate_growth(50, 100) == -50.0

    def test_calculate_growth_zero_previous(self):
        """calculate_growth should return None when previous is zero."""
        assert calculate_growth(100, 0) is None

    def test_calculate_growth_none_values(self):
        """calculate_growth should return None when values are None."""
        assert calculate_growth(None, 100) is None
        assert calculate_growth(100, None) is None

    def test_get_stats_with_growth_uses_weekly_column(self, temp_db):
        """week_growth should be computed from last_week, not last_month."""
        from datetime import datetime, timedelta
        from pkgdb.db import get_stats_with_growth

        conn = get_db_connection(temp_db)
        init_db(conn)
        add_package(conn, "test-pkg")

        today = datetime.now()
        eight_days_ago = (today - timedelta(days=8)).strftime("%Y-%m-%d")
        today_str = today.strftime("%Y-%m-%d")

        # Insert stats directly with deliberately different weekly vs monthly values
        conn.execute(
            "INSERT INTO package_stats (package_name, fetch_date, last_day, last_week, last_month, total) VALUES (?, ?, ?, ?, ?, ?)",
            ("test-pkg", eight_days_ago, 10, 100, 1000, 5000),
        )
        conn.execute(
            "INSERT INTO package_stats (package_name, fetch_date, last_day, last_week, last_month, total) VALUES (?, ?, ?, ?, ?, ?)",
            ("test-pkg", today_str, 15, 200, 1500, 6000),
        )
        conn.commit()

        stats = get_stats_with_growth(conn)
        pkg_stat = next(s for s in stats if s["package_name"] == "test-pkg")

        # week_growth should compare last_week values: (200-100)/100 = 100%
        # If it wrongly used last_month: (1500-1000)/1000 = 50%
        assert pkg_stat["week_growth"] == 100.0
        conn.close()


class TestSparkline:
    """Tests for sparkline generation."""

    def test_make_sparkline_basic(self):
        """make_sparkline should generate a string of correct width."""
        sparkline = make_sparkline([1, 2, 3, 4, 5], width=5)
        assert len(sparkline) == 5

    def test_make_sparkline_empty(self):
        """make_sparkline should handle empty list."""
        sparkline = make_sparkline([], width=7)
        assert len(sparkline) == 7

    def test_make_sparkline_constant_values(self):
        """make_sparkline should handle constant values."""
        sparkline = make_sparkline([5, 5, 5, 5, 5], width=5)
        assert len(sparkline) == 5

    def test_make_sparkline_uses_last_values(self):
        """make_sparkline should use the last N values when list is longer."""
        sparkline = make_sparkline([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], width=5)
        assert len(sparkline) == 5


class TestExportFormats:
    """Tests for export format functions."""

    @pytest.fixture
    def sample_stats(self):
        """Sample stats for export tests."""
        return [
            {"package_name": "pkg-a", "total": 10000, "last_month": 3000, "last_week": 700, "last_day": 100, "fetch_date": "2024-01-15"},
            {"package_name": "pkg-b", "total": 5000, "last_month": 1500, "last_week": 350, "last_day": 50, "fetch_date": "2024-01-15"},
        ]

    def test_export_csv_format(self, sample_stats):
        """export_csv should produce valid CSV output."""
        output = export_csv(sample_stats)

        # Check header
        assert "rank,package_name,total,last_month,last_week,last_day,fetch_date" in output

        # Check data rows
        assert "1,pkg-a,10000,3000,700,100,2024-01-15" in output
        assert "2,pkg-b,5000,1500,350,50,2024-01-15" in output

    def test_export_csv_empty_stats(self):
        """export_csv should handle empty stats."""
        output = export_csv([])
        # Should have header row
        assert "rank,package_name" in output
        # Should not have data rows beyond header
        assert output.count("pkg") == 0

    def test_export_json_format(self, sample_stats):
        """export_json should produce valid JSON output."""
        output = export_json(sample_stats)
        data = json.loads(output)

        assert "generated" in data
        assert "packages" in data
        assert len(data["packages"]) == 2

        pkg_a = data["packages"][0]
        assert pkg_a["rank"] == 1
        assert pkg_a["name"] == "pkg-a"
        assert pkg_a["total"] == 10000

    def test_export_json_empty_stats(self):
        """export_json should handle empty stats."""
        output = export_json([])
        data = json.loads(output)
        assert data["packages"] == []

    def test_export_markdown_format(self, sample_stats):
        """export_markdown should produce valid Markdown table."""
        output = export_markdown(sample_stats)
        lines = output.split("\n")

        # Check header
        assert "| Rank | Package | Total | Month | Week | Day |" in lines[0]
        assert "|------|---------|" in lines[1]

        # Check data rows contain package names
        assert "pkg-a" in output
        assert "pkg-b" in output

    def test_export_markdown_empty_stats(self):
        """export_markdown should handle empty stats."""
        output = export_markdown([])
        lines = output.split("\n")
        assert len(lines) == 2  # Just header and separator


class TestFetchPackageStats:
    """Tests for fetching stats from PyPI API."""

    def test_fetch_package_stats_parses_response(self):
        """fetch_package_stats should parse pypistats responses correctly."""
        recent_response = json.dumps({
            "data": {"last_day": 100, "last_week": 700, "last_month": 3000}
        })
        overall_response = json.dumps({
            "data": [
                {"category": "with_mirrors", "downloads": 100000},
                {"category": "without_mirrors", "downloads": 50000},
            ]
        })

        with patch("pkgdb.api.pypistats.recent", return_value=recent_response):
            with patch("pkgdb.api.pypistats.overall", return_value=overall_response):
                stats = fetch_package_stats("test-package")

        assert stats["last_day"] == 100
        assert stats["last_week"] == 700
        assert stats["last_month"] == 3000
        assert stats["total"] == 50000

    def test_fetch_package_stats_handles_error(self, caplog):
        """fetch_package_stats should return None and log error on failure."""
        with patch("pkgdb.api.pypistats.recent", side_effect=ValueError("API error")):
            stats = fetch_package_stats("nonexistent-package")

        assert stats is None
        assert "Error fetching stats" in caplog.text

    def test_fetch_python_versions_parses_response(self):
        """fetch_python_versions should parse pypistats response correctly."""
        mock_response = json.dumps({
            "data": [
                {"category": "3.10", "downloads": 1000},
                {"category": "3.11", "downloads": 2000},
                {"category": "3.9", "downloads": 500},
            ]
        })

        with patch("pkgdb.api.pypistats.python_minor", return_value=mock_response):
            versions = fetch_python_versions("test-package")

        assert versions is not None
        assert len(versions) == 3
        # Should be sorted by downloads descending
        assert versions[0]["category"] == "3.11"
        assert versions[0]["downloads"] == 2000

    def test_fetch_python_versions_handles_error(self, capsys):
        """fetch_python_versions should return None on error."""
        with patch("pkgdb.api.pypistats.python_minor", side_effect=ValueError("API error")):
            versions = fetch_python_versions("nonexistent-package")

        assert versions is None

    def test_fetch_os_stats_parses_response(self):
        """fetch_os_stats should parse pypistats response correctly."""
        mock_response = json.dumps({
            "data": [
                {"category": "Linux", "downloads": 5000},
                {"category": "Windows", "downloads": 2000},
                {"category": "Darwin", "downloads": 1000},
            ]
        })

        with patch("pkgdb.api.pypistats.system", return_value=mock_response):
            os_stats = fetch_os_stats("test-package")

        assert os_stats is not None
        assert len(os_stats) == 3
        # Should be sorted by downloads descending
        assert os_stats[0]["category"] == "Linux"
        assert os_stats[0]["downloads"] == 5000

    def test_fetch_os_stats_handles_error(self, capsys):
        """fetch_os_stats should return None on error."""
        with patch("pkgdb.api.pypistats.system", side_effect=ValueError("API error")):
            os_stats = fetch_os_stats("nonexistent-package")

        assert os_stats is None


class TestHTMLReportGeneration:
    """Tests for HTML report generation."""

    def test_generate_html_report_creates_file(self):
        """generate_html_report should create a self-contained HTML file with SVG."""
        stats = [
            {
                "package_name": "test-pkg",
                "total": 1000,
                "last_month": 300,
                "last_week": 70,
                "last_day": 10,
            }
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", delete=False
        ) as f:
            output_path = f.name

        try:
            generate_html_report(stats, output_path)
            assert Path(output_path).exists()

            content = Path(output_path).read_text()
            assert "<!DOCTYPE html>" in content
            assert "test-pkg" in content
            assert "<svg" in content
            assert "cdn" not in content.lower()
        finally:
            Path(output_path).unlink(missing_ok=True)

    def test_generate_html_report_includes_all_packages(self):
        """generate_html_report should include all packages in the report."""
        stats = [
            {"package_name": "pkg-a", "total": 1000, "last_month": 300, "last_week": 70, "last_day": 10},
            {"package_name": "pkg-b", "total": 500, "last_month": 150, "last_week": 35, "last_day": 5},
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", delete=False
        ) as f:
            output_path = f.name

        try:
            generate_html_report(stats, output_path)
            content = Path(output_path).read_text()
            assert "pkg-a" in content
            assert "pkg-b" in content
        finally:
            Path(output_path).unlink(missing_ok=True)

    def test_generate_html_report_empty_stats(self, caplog):
        """generate_html_report should handle empty stats gracefully."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", delete=False
        ) as f:
            output_path = f.name

        try:
            generate_html_report([], output_path)
            assert "No statistics available" in caplog.text
        finally:
            Path(output_path).unlink(missing_ok=True)

    def test_generate_html_report_with_history(self):
        """generate_html_report should include time-series chart when history provided."""
        stats = [
            {"package_name": "pkg-a", "total": 3000, "last_month": 900, "last_week": 210, "last_day": 30},
        ]
        history = {
            "pkg-a": [
                {"package_name": "pkg-a", "fetch_date": "2024-01-01", "total": 1000, "last_month": 300, "last_week": 70, "last_day": 10},
                {"package_name": "pkg-a", "fetch_date": "2024-01-02", "total": 2000, "last_month": 600, "last_week": 140, "last_day": 20},
                {"package_name": "pkg-a", "fetch_date": "2024-01-03", "total": 3000, "last_month": 900, "last_week": 210, "last_day": 30},
            ]
        }

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", delete=False
        ) as f:
            output_path = f.name

        try:
            generate_html_report(stats, output_path, history)
            content = Path(output_path).read_text()
            assert "Downloads Over Time" in content
            assert "time-series-chart" in content
            assert "polyline" in content  # SVG line element
        finally:
            Path(output_path).unlink(missing_ok=True)

    def test_generate_html_report_includes_growth_columns(self):
        """generate_html_report should include growth columns when stats have growth data."""
        stats = [
            {
                "package_name": "test-pkg",
                "total": 1000,
                "last_month": 300,
                "last_week": 70,
                "last_day": 10,
                "week_growth": 25.0,
                "month_growth": -10.5,
            }
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", delete=False
        ) as f:
            output_path = f.name

        try:
            generate_html_report(stats, output_path)
            content = Path(output_path).read_text()
            assert "Week Growth" in content
            assert "Month Growth" in content
            assert "+25.0%" in content
            assert "-10.5%" in content
        finally:
            Path(output_path).unlink(missing_ok=True)

    def test_generate_html_report_omits_growth_when_absent(self):
        """generate_html_report should not show growth columns when stats lack growth data."""
        stats = [
            {
                "package_name": "test-pkg",
                "total": 1000,
                "last_month": 300,
                "last_week": 70,
                "last_day": 10,
            }
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", delete=False
        ) as f:
            output_path = f.name

        try:
            generate_html_report(stats, output_path)
            content = Path(output_path).read_text()
            assert "Week Growth" not in content
            assert "Month Growth" not in content
        finally:
            Path(output_path).unlink(missing_ok=True)


class TestCLI:
    """Tests for CLI argument parsing and commands."""

    def test_default_values(self):
        """Default values should be set correctly."""
        config_dir = get_config_dir()
        assert DEFAULT_DB_FILE == str(config_dir / "pkg.db")
        assert DEFAULT_PACKAGES_FILE == str(config_dir / "packages.json")
        assert DEFAULT_REPORT_FILE == str(config_dir / "report.html")

    def test_main_no_command_shows_help(self, capsys):
        """main() with no command should print help."""
        with patch("sys.argv", ["pkgdb"]):
            main()
        captured = capsys.readouterr()
        assert "usage:" in captured.out.lower() or "Available commands" in captured.out

    def test_main_add_command(self, temp_db, caplog):
        """add command should add a package to tracking."""
        with patch("sys.argv", ["pkgdb", "-d", temp_db, "add", "requests"]):
            main()

        assert "Added" in caplog.text
        assert "requests" in caplog.text

        conn = get_db_connection(temp_db)
        packages = get_packages(conn)
        conn.close()
        assert "requests" in packages

    def test_main_add_command_duplicate(self, temp_db, caplog):
        """add command should indicate when package already tracked."""
        conn = get_db_connection(temp_db)
        init_db(conn)
        add_package(conn, "requests")
        conn.close()

        with patch("sys.argv", ["pkgdb", "-d", temp_db, "add", "requests"]):
            main()

        assert "already" in caplog.text

    def test_main_remove_command(self, temp_db, caplog):
        """remove command should remove a package from tracking."""
        conn = get_db_connection(temp_db)
        init_db(conn)
        add_package(conn, "requests")
        conn.close()

        with patch("sys.argv", ["pkgdb", "-d", temp_db, "remove", "requests"]):
            main()

        assert "Removed" in caplog.text
        assert "requests" in caplog.text

        conn = get_db_connection(temp_db)
        packages = get_packages(conn)
        conn.close()
        assert "requests" not in packages

    def test_main_remove_command_not_found(self, temp_db, caplog):
        """remove command should indicate when package not tracked."""
        conn = get_db_connection(temp_db)
        init_db(conn)
        conn.close()

        with patch("sys.argv", ["pkgdb", "-d", temp_db, "remove", "nonexistent"]):
            main()

        assert "was not" in caplog.text

    def test_main_packages_command_empty(self, temp_db, caplog):
        """packages command should indicate when no packages tracked."""
        conn = get_db_connection(temp_db)
        init_db(conn)
        conn.close()

        with patch("sys.argv", ["pkgdb", "-d", temp_db, "packages"]):
            main()

        assert "No packages" in caplog.text

    def test_main_packages_command_with_packages(self, temp_db, capsys, caplog):
        """packages command should display tracked packages."""
        conn = get_db_connection(temp_db)
        init_db(conn)
        add_package(conn, "requests")
        add_package(conn, "flask")
        conn.close()

        with patch("sys.argv", ["pkgdb", "-d", temp_db, "packages"]):
            main()

        captured = capsys.readouterr()
        # Table data goes to stdout
        assert "requests" in captured.out
        assert "flask" in captured.out
        # Header message goes to logging
        assert "Tracking 2 packages" in caplog.text

    def test_main_import_command(self, temp_db, temp_packages_file, caplog):
        """import command should import packages from file."""
        conn = get_db_connection(temp_db)
        init_db(conn)
        conn.close()

        with patch("sys.argv", ["pkgdb", "-d", temp_db, "import", temp_packages_file, "--no-verify"]):
            main()

        assert "Imported 2 packages" in caplog.text

        conn = get_db_connection(temp_db)
        packages = get_packages(conn)
        conn.close()
        assert "package-a" in packages
        assert "package-b" in packages

    def test_main_import_command_file_not_found(self, temp_db, caplog):
        """import command should handle missing file."""
        conn = get_db_connection(temp_db)
        init_db(conn)
        conn.close()

        with patch("sys.argv", ["pkgdb", "-d", temp_db, "import", "/nonexistent/file.json"]):
            main()

        assert "File not found" in caplog.text

    def test_main_fetch_command(self, temp_db):
        """fetch command should fetch and store stats for tracked packages."""
        # First add packages to track
        conn = get_db_connection(temp_db)
        init_db(conn)
        conn.execute("INSERT INTO packages (package_name, added_date) VALUES ('package-a', '2024-01-01')")
        conn.execute("INSERT INTO packages (package_name, added_date) VALUES ('package-b', '2024-01-01')")
        conn.commit()
        conn.close()

        recent_response = json.dumps({
            "data": {"last_day": 100, "last_week": 700, "last_month": 3000}
        })
        overall_response = json.dumps({
            "data": [{"category": "without_mirrors", "downloads": 50000}]
        })

        with patch("sys.argv", ["pkgdb", "-d", temp_db, "fetch"]):
            with patch("pkgdb.api.pypistats.recent", return_value=recent_response):
                with patch("pkgdb.api.pypistats.overall", return_value=overall_response):
                    main()

        conn = get_db_connection(temp_db)
        cursor = conn.execute("SELECT COUNT(*) as count FROM package_stats")
        assert cursor.fetchone()["count"] == 2
        conn.close()

    def test_main_fetch_command_no_packages(self, temp_db, caplog):
        """fetch command should prompt to add packages when none tracked."""
        conn = get_db_connection(temp_db)
        init_db(conn)
        conn.close()

        with patch("sys.argv", ["pkgdb", "-d", temp_db, "fetch"]):
            main()

        assert "No packages" in caplog.text
        assert "pkgdb add" in caplog.text or "pkgdb import" in caplog.text

    def test_main_show_command_empty_db(self, temp_db, caplog):
        """show command should indicate when database is empty."""
        conn = get_db_connection(temp_db)
        init_db(conn)
        conn.close()

        with patch("sys.argv", ["pkgdb", "-d", temp_db, "show"]):
            main()

        assert "No data" in caplog.text or "fetch" in caplog.text.lower()

    def test_main_show_command_with_data(self, temp_db, capsys):
        """show command should display stats from database."""
        conn = get_db_connection(temp_db)
        init_db(conn)
        conn.execute("""
            INSERT INTO package_stats
            (package_name, fetch_date, last_day, last_week, last_month, total)
            VALUES ('test-pkg', '2024-01-01', 10, 70, 300, 1000)
        """)
        conn.commit()
        conn.close()

        with patch("sys.argv", ["pkgdb", "-d", temp_db, "show"]):
            main()

        captured = capsys.readouterr()
        assert "test-pkg" in captured.out

    def test_main_report_command(self, temp_db):
        """report command should generate HTML report."""
        conn = get_db_connection(temp_db)
        init_db(conn)
        conn.execute("""
            INSERT INTO package_stats
            (package_name, fetch_date, last_day, last_week, last_month, total)
            VALUES ('test-pkg', '2024-01-01', 10, 70, 300, 1000)
        """)
        conn.commit()
        conn.close()

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", delete=False
        ) as f:
            output_path = f.name

        try:
            with patch("sys.argv", ["pkgdb", "-d", temp_db, "report", "-o", output_path]):
                with patch("webbrowser.open_new_tab"):
                    main()

            assert Path(output_path).exists()
            content = Path(output_path).read_text()
            assert "test-pkg" in content
        finally:
            Path(output_path).unlink(missing_ok=True)

    def test_main_history_command(self, temp_db, capsys):
        """history command should display historical stats for a package."""
        conn = get_db_connection(temp_db)
        init_db(conn)
        conn.execute("""
            INSERT INTO package_stats
            (package_name, fetch_date, last_day, last_week, last_month, total)
            VALUES
            ('test-pkg', '2024-01-01', 10, 70, 300, 1000),
            ('test-pkg', '2024-01-02', 20, 140, 600, 2000)
        """)
        conn.commit()
        conn.close()

        with patch("sys.argv", ["pkgdb", "-d", temp_db, "history", "test-pkg"]):
            main()

        captured = capsys.readouterr()
        assert "test-pkg" in captured.out
        assert "2024-01-01" in captured.out
        assert "2024-01-02" in captured.out

    def test_main_history_command_unknown_package(self, temp_db, caplog):
        """history command should indicate when no data found."""
        conn = get_db_connection(temp_db)
        init_db(conn)
        conn.close()

        with patch("sys.argv", ["pkgdb", "-d", temp_db, "history", "nonexistent"]):
            main()

        assert "No data found" in caplog.text

    def test_main_export_csv(self, temp_db, capsys):
        """export command should output CSV to stdout."""
        conn = get_db_connection(temp_db)
        init_db(conn)
        conn.execute("""
            INSERT INTO package_stats
            (package_name, fetch_date, last_day, last_week, last_month, total)
            VALUES ('test-pkg', '2024-01-01', 10, 70, 300, 1000)
        """)
        conn.commit()
        conn.close()

        with patch("sys.argv", ["pkgdb", "-d", temp_db, "export", "-f", "csv"]):
            main()

        captured = capsys.readouterr()
        assert "test-pkg" in captured.out
        assert "1000" in captured.out

    def test_main_export_json(self, temp_db, capsys):
        """export command should output JSON."""
        conn = get_db_connection(temp_db)
        init_db(conn)
        conn.execute("""
            INSERT INTO package_stats
            (package_name, fetch_date, last_day, last_week, last_month, total)
            VALUES ('test-pkg', '2024-01-01', 10, 70, 300, 1000)
        """)
        conn.commit()
        conn.close()

        with patch("sys.argv", ["pkgdb", "-d", temp_db, "export", "-f", "json"]):
            main()

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["packages"][0]["name"] == "test-pkg"

    def test_main_export_markdown(self, temp_db, capsys):
        """export command should output Markdown."""
        conn = get_db_connection(temp_db)
        init_db(conn)
        conn.execute("""
            INSERT INTO package_stats
            (package_name, fetch_date, last_day, last_week, last_month, total)
            VALUES ('test-pkg', '2024-01-01', 10, 70, 300, 1000)
        """)
        conn.commit()
        conn.close()

        with patch("sys.argv", ["pkgdb", "-d", temp_db, "export", "-f", "markdown"]):
            main()

        captured = capsys.readouterr()
        assert "| Rank |" in captured.out
        assert "test-pkg" in captured.out

    def test_main_export_to_file(self, temp_db):
        """export command should write to file when -o specified."""
        conn = get_db_connection(temp_db)
        init_db(conn)
        conn.execute("""
            INSERT INTO package_stats
            (package_name, fetch_date, last_day, last_week, last_month, total)
            VALUES ('test-pkg', '2024-01-01', 10, 70, 300, 1000)
        """)
        conn.commit()
        conn.close()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            output_path = f.name

        try:
            with patch("sys.argv", ["pkgdb", "-d", temp_db, "export", "-f", "csv", "-o", output_path]):
                main()

            assert Path(output_path).exists()
            content = Path(output_path).read_text()
            assert "test-pkg" in content
        finally:
            Path(output_path).unlink(missing_ok=True)

    def test_main_stats_command(self, capsys):
        """stats command should display Python versions and OS breakdown."""
        recent_response = json.dumps({
            "data": {"last_day": 100, "last_week": 700, "last_month": 3000}
        })
        overall_response = json.dumps({
            "data": [{"category": "without_mirrors", "downloads": 50000}]
        })
        python_response = json.dumps({
            "data": [
                {"category": "3.11", "downloads": 2000},
                {"category": "3.10", "downloads": 1000},
            ]
        })
        system_response = json.dumps({
            "data": [
                {"category": "Linux", "downloads": 4000},
                {"category": "Windows", "downloads": 1000},
            ]
        })

        with patch("sys.argv", ["pkgdb", "stats", "test-package"]):
            with patch("pkgdb.api.pypistats.recent", return_value=recent_response):
                with patch("pkgdb.api.pypistats.overall", return_value=overall_response):
                    with patch("pkgdb.api.pypistats.python_minor", return_value=python_response):
                        with patch("pkgdb.api.pypistats.system", return_value=system_response):
                            main()

        captured = capsys.readouterr()
        assert "Download Summary" in captured.out
        assert "Python Version Distribution" in captured.out
        assert "Operating System Distribution" in captured.out
        assert "3.11" in captured.out
        assert "Linux" in captured.out

    def test_main_report_command_single_package(self, temp_db):
        """report command with package arg should generate single-package report."""
        conn = get_db_connection(temp_db)
        init_db(conn)
        conn.execute("""
            INSERT INTO package_stats
            (package_name, fetch_date, last_day, last_week, last_month, total)
            VALUES
            ('test-pkg', '2024-01-01', 10, 70, 300, 1000),
            ('test-pkg', '2024-01-02', 20, 140, 600, 2000)
        """)
        conn.commit()
        conn.close()

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", delete=False
        ) as f:
            output_path = f.name

        # Mock API calls for environment data
        python_response = json.dumps({
            "data": [{"category": "3.11", "downloads": 2000}]
        })
        system_response = json.dumps({
            "data": [{"category": "Linux", "downloads": 4000}]
        })

        try:
            with patch("sys.argv", ["pkgdb", "-d", temp_db, "report", "test-pkg", "-o", output_path]):
                with patch("webbrowser.open_new_tab"):
                    with patch("pkgdb.api.pypistats.python_minor", return_value=python_response):
                        with patch("pkgdb.api.pypistats.system", return_value=system_response):
                            main()

            assert Path(output_path).exists()
            content = Path(output_path).read_text()
            # Single package report should have package name as title
            assert "test-pkg" in content
            assert "Environment Distribution" in content
            assert "Python Versions" in content
            assert "Operating Systems" in content
        finally:
            Path(output_path).unlink(missing_ok=True)

    def test_main_report_command_with_env_flag(self, temp_db):
        """report command with --env should include environment summary."""
        conn = get_db_connection(temp_db)
        init_db(conn)
        conn.execute("""
            INSERT INTO package_stats
            (package_name, fetch_date, last_day, last_week, last_month, total)
            VALUES ('test-pkg', '2024-01-01', 10, 70, 300, 1000)
        """)
        conn.commit()
        conn.close()

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", delete=False
        ) as f:
            output_path = f.name

        # Mock API calls for environment data
        python_response = json.dumps({
            "data": [
                {"category": "3.11", "downloads": 2000},
                {"category": "3.10", "downloads": 1000},
            ]
        })
        system_response = json.dumps({
            "data": [
                {"category": "Linux", "downloads": 4000},
                {"category": "Windows", "downloads": 1000},
            ]
        })

        try:
            with patch("sys.argv", ["pkgdb", "-d", temp_db, "report", "-e", "-o", output_path]):
                with patch("webbrowser.open_new_tab"):
                    with patch("pkgdb.api.pypistats.python_minor", return_value=python_response):
                        with patch("pkgdb.api.pypistats.system", return_value=system_response):
                            main()

            assert Path(output_path).exists()
            content = Path(output_path).read_text()
            assert "Environment Summary" in content
            assert "py-version-chart" in content or "os-chart" in content
        finally:
            Path(output_path).unlink(missing_ok=True)

    def test_main_report_command_no_browser(self, temp_db, capsys):
        """report command with --no-browser should not open browser."""
        conn = get_db_connection(temp_db)
        init_db(conn)
        conn.execute("""
            INSERT INTO package_stats
            (package_name, fetch_date, last_day, last_week, last_month, total)
            VALUES ('test-pkg', '2024-01-01', 10, 70, 300, 1000)
        """)
        conn.commit()
        conn.close()

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", delete=False
        ) as f:
            output_path = f.name

        try:
            with patch("sys.argv", ["pkgdb", "-d", temp_db, "report", "--no-browser", "-o", output_path]):
                with patch("webbrowser.open_new_tab") as mock_browser:
                    main()
                    # Browser should NOT be called
                    mock_browser.assert_not_called()

            assert Path(output_path).exists()
            captured = capsys.readouterr()
            # Should not contain "Opening" message
            assert "Opening" not in captured.out
        finally:
            Path(output_path).unlink(missing_ok=True)

    def test_main_version_command(self, capsys):
        """version command should display package version."""
        from pkgdb import __version__

        with patch("sys.argv", ["pkgdb", "version"]):
            main()

        captured = capsys.readouterr()
        assert "pkgdb" in captured.out
        assert __version__ in captured.out

    def test_main_show_command_with_limit(self, temp_db, capsys):
        """show command with --limit should limit output."""
        conn = get_db_connection(temp_db)
        init_db(conn)
        # Add 5 packages
        for i in range(5):
            conn.execute(f"""
                INSERT INTO package_stats
                (package_name, fetch_date, last_day, last_week, last_month, total)
                VALUES ('pkg-{i}', '2024-01-01', {i*10}, {i*70}, {i*300}, {i*1000 + 1000})
            """)
        conn.commit()
        conn.close()

        with patch("sys.argv", ["pkgdb", "-d", temp_db, "show", "--limit", "3"]):
            main()

        captured = capsys.readouterr()
        # Should show only top 3 (highest totals)
        assert "pkg-4" in captured.out  # 5000 total
        assert "pkg-3" in captured.out  # 4000 total
        assert "pkg-2" in captured.out  # 3000 total
        assert "pkg-0" not in captured.out  # 1000 total - should be excluded

    def test_main_show_command_with_sort_by(self, temp_db, capsys):
        """show command with --sort-by should sort by specified field."""
        conn = get_db_connection(temp_db)
        init_db(conn)
        # Add packages with different stats profiles
        conn.execute("""
            INSERT INTO package_stats
            (package_name, fetch_date, last_day, last_week, last_month, total)
            VALUES
            ('high-total', '2024-01-01', 10, 70, 300, 10000),
            ('high-month', '2024-01-01', 10, 70, 9000, 5000),
            ('high-day', '2024-01-01', 500, 70, 300, 3000)
        """)
        conn.commit()
        conn.close()

        # Sort by month
        with patch("sys.argv", ["pkgdb", "-d", temp_db, "show", "--sort-by", "month"]):
            main()

        captured = capsys.readouterr()
        lines = [l for l in captured.out.split("\n") if l.strip()]
        # First data line (after headers) should be high-month
        data_lines = [l for l in lines if "high-" in l]
        assert "high-month" in data_lines[0]

    def test_main_show_command_with_json(self, temp_db, capsys):
        """show command with --json should output JSON."""
        conn = get_db_connection(temp_db)
        init_db(conn)
        conn.execute("""
            INSERT INTO package_stats
            (package_name, fetch_date, last_day, last_week, last_month, total)
            VALUES ('test-pkg', '2024-01-01', 10, 70, 300, 1000)
        """)
        conn.commit()
        conn.close()

        with patch("sys.argv", ["pkgdb", "-d", temp_db, "show", "--json"]):
            main()

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["package"] == "test-pkg"
        assert data[0]["total"] == 1000
        assert data[0]["last_month"] == 300
        assert data[0]["last_week"] == 70
        assert data[0]["last_day"] == 10

    def test_main_history_command_with_since(self, temp_db, capsys):
        """history command with --since should filter by date."""
        conn = get_db_connection(temp_db)
        init_db(conn)
        conn.execute("""
            INSERT INTO package_stats
            (package_name, fetch_date, last_day, last_week, last_month, total)
            VALUES
            ('test-pkg', '2024-01-01', 10, 70, 300, 1000),
            ('test-pkg', '2024-01-05', 20, 140, 600, 2000),
            ('test-pkg', '2024-01-10', 30, 210, 900, 3000)
        """)
        conn.commit()
        conn.close()

        with patch("sys.argv", ["pkgdb", "-d", temp_db, "history", "test-pkg", "--since", "2024-01-05"]):
            main()

        captured = capsys.readouterr()
        assert "test-pkg" in captured.out
        assert "2024-01-01" not in captured.out  # Should be filtered out
        assert "2024-01-05" in captured.out
        assert "2024-01-10" in captured.out

    def test_main_history_command_since_no_data(self, temp_db, caplog):
        """history command with --since should handle no data in range."""
        conn = get_db_connection(temp_db)
        init_db(conn)
        conn.execute("""
            INSERT INTO package_stats
            (package_name, fetch_date, last_day, last_week, last_month, total)
            VALUES ('test-pkg', '2024-01-01', 10, 70, 300, 1000)
        """)
        conn.commit()
        conn.close()

        with patch("sys.argv", ["pkgdb", "-d", temp_db, "history", "test-pkg", "--since", "2024-06-01"]):
            main()

        assert "No data found" in caplog.text
        assert "since 2024-06-01" in caplog.text

    def test_main_sync_command_adds_new_packages(self, temp_db, caplog):
        """sync command should add new packages from PyPI user."""
        # First add an existing package
        conn = get_db_connection(temp_db)
        init_db(conn)
        add_package(conn, "existing-pkg")
        conn.close()

        mock_packages = [["Owner", "existing-pkg"], ["Owner", "new-pkg"]]

        with patch("sys.argv", ["pkgdb", "-d", temp_db, "sync", "--user", "testuser"]):
            with patch("pkgdb.api.xmlrpc.client.ServerProxy") as mock_proxy:
                mock_proxy.return_value.user_packages.return_value = mock_packages
                main()

        assert "Added 1 new packages" in caplog.text
        assert "new-pkg" in caplog.text

        # Verify new package was added
        conn = get_db_connection(temp_db)
        packages = get_packages(conn)
        conn.close()
        assert "existing-pkg" in packages
        assert "new-pkg" in packages

    def test_main_sync_command_no_new_packages(self, temp_db, caplog):
        """sync command should report when no new packages to add."""
        conn = get_db_connection(temp_db)
        init_db(conn)
        add_package(conn, "pkg-a")
        add_package(conn, "pkg-b")
        conn.close()

        mock_packages = [["Owner", "pkg-a"], ["Owner", "pkg-b"]]

        with patch("sys.argv", ["pkgdb", "-d", temp_db, "sync", "--user", "testuser"]):
            with patch("pkgdb.api.xmlrpc.client.ServerProxy") as mock_proxy:
                mock_proxy.return_value.user_packages.return_value = mock_packages
                main()

        assert "No new packages to add" in caplog.text

    def test_main_sync_command_warns_not_on_remote(self, temp_db, caplog):
        """sync command should warn about packages not on remote."""
        conn = get_db_connection(temp_db)
        init_db(conn)
        add_package(conn, "local-only-pkg")
        add_package(conn, "common-pkg")
        conn.close()

        mock_packages = [["Owner", "common-pkg"]]

        with patch("sys.argv", ["pkgdb", "-d", temp_db, "sync", "--user", "testuser"]):
            with patch("pkgdb.api.xmlrpc.client.ServerProxy") as mock_proxy:
                mock_proxy.return_value.user_packages.return_value = mock_packages
                main()

        assert "locally tracked packages not found" in caplog.text
        assert "local-only-pkg" in caplog.text

    def test_main_sync_command_user_not_found(self, temp_db, caplog):
        """sync command should handle API error."""
        import xmlrpc.client

        with patch("sys.argv", ["pkgdb", "-d", temp_db, "sync", "--user", "nonexistent"]):
            with patch("pkgdb.api.xmlrpc.client.ServerProxy") as mock_proxy:
                mock_proxy.return_value.user_packages.side_effect = xmlrpc.client.Fault(1, "User not found")
                main()

        assert "Could not fetch" in caplog.text

    def test_main_sync_command_with_prune(self, temp_db, caplog):
        """sync command with --prune should remove packages not on remote."""
        conn = get_db_connection(temp_db)
        init_db(conn)
        add_package(conn, "local-only-pkg")
        add_package(conn, "common-pkg")
        conn.close()

        mock_packages = [["Owner", "common-pkg"]]

        with patch("sys.argv", ["pkgdb", "-d", temp_db, "sync", "--user", "testuser", "--prune"]):
            with patch("pkgdb.api.xmlrpc.client.ServerProxy") as mock_proxy:
                mock_proxy.return_value.user_packages.return_value = mock_packages
                main()

        assert "Pruned 1 packages" in caplog.text
        assert "local-only-pkg" in caplog.text

        # Verify package was removed from database
        conn = get_db_connection(temp_db)
        packages = get_packages(conn)
        conn.close()
        assert "local-only-pkg" not in packages
        assert "common-pkg" in packages


class TestFetchUserPackages:
    """Tests for fetch_user_packages function."""

    def test_fetch_user_packages_success(self):
        """fetch_user_packages should return list of package names."""
        mock_packages = [["Owner", "pkg-c"], ["Owner", "pkg-a"], ["Owner", "pkg-b"]]

        with patch("pkgdb.api.xmlrpc.client.ServerProxy") as mock_proxy:
            mock_proxy.return_value.user_packages.return_value = mock_packages
            result = fetch_user_packages("testuser")

        assert result == ["pkg-a", "pkg-b", "pkg-c"]  # Should be sorted

    def test_fetch_user_packages_deduplicates(self):
        """fetch_user_packages should deduplicate packages."""
        # User might have multiple roles for same package
        mock_packages = [["Owner", "pkg-a"], ["Maintainer", "pkg-a"], ["Owner", "pkg-b"]]

        with patch("pkgdb.api.xmlrpc.client.ServerProxy") as mock_proxy:
            mock_proxy.return_value.user_packages.return_value = mock_packages
            result = fetch_user_packages("testuser")

        assert result == ["pkg-a", "pkg-b"]

    def test_fetch_user_packages_empty(self):
        """fetch_user_packages should return empty list for user with no packages."""
        with patch("pkgdb.api.xmlrpc.client.ServerProxy") as mock_proxy:
            mock_proxy.return_value.user_packages.return_value = []
            result = fetch_user_packages("testuser")

        assert result == []

    def test_fetch_user_packages_api_error(self):
        """fetch_user_packages should return None on API error."""
        import xmlrpc.client

        with patch("pkgdb.api.xmlrpc.client.ServerProxy") as mock_proxy:
            mock_proxy.return_value.user_packages.side_effect = xmlrpc.client.Fault(1, "Error")
            result = fetch_user_packages("testuser")

        assert result is None

    def test_fetch_user_packages_network_error(self):
        """fetch_user_packages should return None on network error."""
        with patch("pkgdb.api.xmlrpc.client.ServerProxy") as mock_proxy:
            mock_proxy.return_value.user_packages.side_effect = OSError("Connection refused")
            result = fetch_user_packages("testuser")

        assert result is None


class TestPieChart:
    """Tests for SVG pie chart generation."""

    def test_make_svg_pie_chart_creates_svg(self):
        """make_svg_pie_chart should create valid SVG."""
        data = [("Linux", 5000), ("Windows", 2000), ("Darwin", 1000)]
        svg = make_svg_pie_chart(data, "test-chart")

        assert "<svg" in svg
        assert "test-chart" in svg
        assert "</svg>" in svg
        assert "path" in svg  # Pie slices are paths

    def test_make_svg_pie_chart_includes_legend(self):
        """make_svg_pie_chart should include legend with percentages."""
        data = [("Linux", 5000), ("Windows", 2500), ("Darwin", 2500)]
        svg = make_svg_pie_chart(data, "test-chart")

        assert "Linux" in svg
        assert "Windows" in svg
        assert "Darwin" in svg
        assert "%" in svg  # Should show percentages

    def test_make_svg_pie_chart_empty_data(self):
        """make_svg_pie_chart should handle empty data."""
        svg = make_svg_pie_chart([], "test-chart")
        assert svg == ""

    def test_make_svg_pie_chart_zero_total(self):
        """make_svg_pie_chart should handle zero total."""
        data = [("Linux", 0), ("Windows", 0)]
        svg = make_svg_pie_chart(data, "test-chart")
        assert "No data" in svg

    def test_make_svg_pie_chart_groups_others(self):
        """make_svg_pie_chart should group items beyond top 5 as 'Other'."""
        data = [
            ("A", 100), ("B", 90), ("C", 80), ("D", 70), ("E", 60),
            ("F", 50), ("G", 40), ("H", 30),
        ]
        svg = make_svg_pie_chart(data, "test-chart")

        # Should have "Other" in legend
        assert "Other" in svg
        # Should not have all individual items beyond top 5
        assert "H" not in svg


class TestAggregateEnvStats:
    """Tests for aggregating environment stats across packages."""

    def test_aggregate_env_stats_combines_packages(self):
        """aggregate_env_stats should combine stats from multiple packages."""
        python_response_1 = json.dumps({
            "data": [{"category": "3.11", "downloads": 2000}]
        })
        python_response_2 = json.dumps({
            "data": [{"category": "3.11", "downloads": 1000}]
        })
        system_response_1 = json.dumps({
            "data": [{"category": "Linux", "downloads": 4000}]
        })
        system_response_2 = json.dumps({
            "data": [{"category": "Linux", "downloads": 2000}]
        })

        call_count = {"python": 0, "system": 0}

        def mock_python_minor(pkg, format=None):
            call_count["python"] += 1
            return python_response_1 if call_count["python"] == 1 else python_response_2

        def mock_system(pkg, format=None):
            call_count["system"] += 1
            return system_response_1 if call_count["system"] == 1 else system_response_2

        with patch("pkgdb.api.pypistats.python_minor", side_effect=mock_python_minor):
            with patch("pkgdb.api.pypistats.system", side_effect=mock_system):
                result = aggregate_env_stats(["pkg-a", "pkg-b"])

        # Should aggregate downloads
        py_versions = dict(result["python_versions"])
        assert py_versions.get("3.11") == 3000  # 2000 + 1000

        os_dist = dict(result["os_distribution"])
        assert os_dist.get("Linux") == 6000  # 4000 + 2000

    def test_aggregate_env_stats_handles_errors(self):
        """aggregate_env_stats should handle API errors gracefully."""
        with patch("pkgdb.api.pypistats.python_minor", side_effect=ValueError("API error")):
            with patch("pkgdb.api.pypistats.system", side_effect=ValueError("API error")):
                result = aggregate_env_stats(["pkg-a"])

        assert result["python_versions"] == []
        assert result["os_distribution"] == []

    def test_aggregate_env_stats_empty_packages(self):
        """aggregate_env_stats should handle empty package list."""
        result = aggregate_env_stats([])
        assert result["python_versions"] == []
        assert result["os_distribution"] == []


class TestPackageHTMLReport:
    """Tests for single-package HTML report generation."""

    def test_generate_package_html_report_creates_file(self):
        """generate_package_html_report should create HTML file."""
        stats = {"total": 1000, "last_month": 300, "last_week": 70, "last_day": 10}

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", delete=False
        ) as f:
            output_path = f.name

        python_response = json.dumps({
            "data": [{"category": "3.11", "downloads": 2000}]
        })
        system_response = json.dumps({
            "data": [{"category": "Linux", "downloads": 4000}]
        })

        try:
            with patch("pkgdb.api.pypistats.python_minor", return_value=python_response):
                with patch("pkgdb.api.pypistats.system", return_value=system_response):
                    generate_package_html_report("test-pkg", output_path, stats=stats)

            assert Path(output_path).exists()
            content = Path(output_path).read_text()
            assert "<!DOCTYPE html>" in content
            assert "test-pkg" in content
        finally:
            Path(output_path).unlink(missing_ok=True)

    def test_generate_package_html_report_includes_stats_cards(self):
        """generate_package_html_report should include download stat cards."""
        stats = {"total": 1000, "last_month": 300, "last_week": 70, "last_day": 10}

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", delete=False
        ) as f:
            output_path = f.name

        python_response = json.dumps({"data": []})
        system_response = json.dumps({"data": []})

        try:
            with patch("pkgdb.api.pypistats.python_minor", return_value=python_response):
                with patch("pkgdb.api.pypistats.system", return_value=system_response):
                    generate_package_html_report("test-pkg", output_path, stats=stats)

            content = Path(output_path).read_text()
            assert "Total Downloads" in content
            assert "Last Month" in content
            assert "Last Week" in content
            assert "Last Day" in content
            assert "1,000" in content  # Formatted total
        finally:
            Path(output_path).unlink(missing_ok=True)

    def test_generate_package_html_report_includes_env_charts(self):
        """generate_package_html_report should include environment pie charts."""
        stats = {"total": 1000, "last_month": 300, "last_week": 70, "last_day": 10}

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", delete=False
        ) as f:
            output_path = f.name

        python_response = json.dumps({
            "data": [
                {"category": "3.11", "downloads": 2000},
                {"category": "3.10", "downloads": 1000},
            ]
        })
        system_response = json.dumps({
            "data": [
                {"category": "Linux", "downloads": 4000},
                {"category": "Windows", "downloads": 1000},
            ]
        })

        try:
            with patch("pkgdb.api.pypistats.python_minor", return_value=python_response):
                with patch("pkgdb.api.pypistats.system", return_value=system_response):
                    generate_package_html_report("test-pkg", output_path, stats=stats)

            content = Path(output_path).read_text()
            assert "Environment Distribution" in content
            assert "py-version-chart" in content
            assert "os-chart" in content
        finally:
            Path(output_path).unlink(missing_ok=True)

    def test_generate_package_html_report_with_history(self):
        """generate_package_html_report should include history chart when available."""
        stats = {"total": 3000, "last_month": 900, "last_week": 210, "last_day": 30}
        history = [
            {"package_name": "test-pkg", "fetch_date": "2024-01-01", "total": 1000, "last_month": 300, "last_week": 70, "last_day": 10},
            {"package_name": "test-pkg", "fetch_date": "2024-01-02", "total": 2000, "last_month": 600, "last_week": 140, "last_day": 20},
            {"package_name": "test-pkg", "fetch_date": "2024-01-03", "total": 3000, "last_month": 900, "last_week": 210, "last_day": 30},
        ]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", delete=False
        ) as f:
            output_path = f.name

        python_response = json.dumps({"data": []})
        system_response = json.dumps({"data": []})

        try:
            with patch("pkgdb.api.pypistats.python_minor", return_value=python_response):
                with patch("pkgdb.api.pypistats.system", return_value=system_response):
                    generate_package_html_report("test-pkg", output_path, stats=stats, history=history)

            content = Path(output_path).read_text()
            assert "Downloads Over Time" in content
            assert "polyline" in content  # SVG line element
        finally:
            Path(output_path).unlink(missing_ok=True)


class TestPackageStatsService:
    """Tests for the PackageStatsService abstraction layer."""

    def test_service_add_and_remove_package(self, temp_db):
        """Service should add and remove packages."""
        service = PackageStatsService(temp_db)

        # Add package (skip verify for testing)
        assert service.add_package("test-package", verify=False) is True
        assert service.add_package("test-package", verify=False) is False  # Already exists

        # List packages
        packages = service.list_packages()
        assert len(packages) == 1
        assert packages[0].name == "test-package"
        assert isinstance(packages[0], PackageInfo)

        # Remove package
        assert service.remove_package("test-package") is True
        assert service.remove_package("test-package") is False  # Already removed

        assert service.list_packages() == []

    def test_service_import_packages(self, temp_db, temp_packages_file):
        """Service should import packages from file."""
        service = PackageStatsService(temp_db)

        added, skipped, invalid, not_found = service.import_packages(
            temp_packages_file, verify=False
        )
        assert added == 2
        assert skipped == 0
        assert invalid == []
        assert not_found == []

        packages = service.list_packages()
        assert len(packages) == 2

    def test_service_fetch_all_stats(self, temp_db):
        """Service should fetch and store stats for all packages."""
        service = PackageStatsService(temp_db)
        service.add_package("test-pkg", verify=False)

        recent_response = json.dumps({
            "data": {"last_day": 100, "last_week": 700, "last_month": 3000}
        })
        overall_response = json.dumps({
            "data": [{"category": "without_mirrors", "downloads": 50000}]
        })

        progress_calls = []

        def on_progress(current, total, package, stats):
            progress_calls.append((current, total, package, stats))

        with patch("pkgdb.api.pypistats.recent", return_value=recent_response):
            with patch("pkgdb.api.pypistats.overall", return_value=overall_response):
                result = service.fetch_all_stats(progress_callback=on_progress)

        assert isinstance(result, FetchResult)
        assert result.success == 1
        assert result.failed == 0
        assert result.skipped == 0
        assert "test-pkg" in result.results
        assert result.results["test-pkg"]["total"] == 50000

        # Progress callback should have been called
        assert len(progress_calls) == 1
        assert progress_calls[0][0] == 1  # current
        assert progress_calls[0][1] == 1  # total
        assert progress_calls[0][2] == "test-pkg"  # package

    def test_service_get_stats(self, temp_db):
        """Service should retrieve stats."""
        service = PackageStatsService(temp_db)

        # Empty initially
        assert service.get_stats() == []

        # Add some data
        conn = get_db_connection(temp_db)
        init_db(conn)
        conn.execute("""
            INSERT INTO package_stats
            (package_name, fetch_date, last_day, last_week, last_month, total)
            VALUES ('test-pkg', '2024-01-01', 10, 70, 300, 1000)
        """)
        conn.commit()
        conn.close()

        stats = service.get_stats()
        assert len(stats) == 1
        assert stats[0]["package_name"] == "test-pkg"

    def test_service_get_history(self, temp_db):
        """Service should retrieve package history."""
        service = PackageStatsService(temp_db)

        conn = get_db_connection(temp_db)
        init_db(conn)
        conn.execute("""
            INSERT INTO package_stats
            (package_name, fetch_date, last_day, last_week, last_month, total)
            VALUES
            ('test-pkg', '2024-01-01', 10, 70, 300, 1000),
            ('test-pkg', '2024-01-02', 20, 140, 600, 2000)
        """)
        conn.commit()
        conn.close()

        history = service.get_history("test-pkg", limit=10)
        assert len(history) == 2

    def test_service_export(self, temp_db):
        """Service should export stats in various formats."""
        service = PackageStatsService(temp_db)

        conn = get_db_connection(temp_db)
        init_db(conn)
        conn.execute("""
            INSERT INTO package_stats
            (package_name, fetch_date, last_day, last_week, last_month, total)
            VALUES ('test-pkg', '2024-01-01', 10, 70, 300, 1000)
        """)
        conn.commit()
        conn.close()

        # CSV
        csv_output = service.export("csv")
        assert csv_output is not None
        assert "test-pkg" in csv_output

        # JSON
        json_output = service.export("json")
        assert json_output is not None
        data = json.loads(json_output)
        assert data["packages"][0]["name"] == "test-pkg"

        # Markdown
        md_output = service.export("markdown")
        assert md_output is not None
        assert "| Rank |" in md_output

    def test_service_export_empty(self, temp_db):
        """Service should return None for empty export."""
        service = PackageStatsService(temp_db)
        assert service.export("csv") is None

    def test_service_export_invalid_format(self, temp_db):
        """Service should raise ValueError for invalid format."""
        service = PackageStatsService(temp_db)

        conn = get_db_connection(temp_db)
        init_db(conn)
        conn.execute("""
            INSERT INTO package_stats
            (package_name, fetch_date, last_day, last_week, last_month, total)
            VALUES ('test-pkg', '2024-01-01', 10, 70, 300, 1000)
        """)
        conn.commit()
        conn.close()

        with pytest.raises(ValueError, match="Unknown format"):
            service.export("invalid")

    def test_service_fetch_package_details(self, temp_db):
        """Service should fetch detailed package info."""
        service = PackageStatsService(temp_db)

        recent_response = json.dumps({
            "data": {"last_day": 100, "last_week": 700, "last_month": 3000}
        })
        overall_response = json.dumps({
            "data": [{"category": "without_mirrors", "downloads": 50000}]
        })
        python_response = json.dumps({
            "data": [{"category": "3.11", "downloads": 2000}]
        })
        system_response = json.dumps({
            "data": [{"category": "Linux", "downloads": 4000}]
        })

        with patch("pkgdb.api.pypistats.recent", return_value=recent_response):
            with patch("pkgdb.api.pypistats.overall", return_value=overall_response):
                with patch("pkgdb.api.pypistats.python_minor", return_value=python_response):
                    with patch("pkgdb.api.pypistats.system", return_value=system_response):
                        details = service.fetch_package_details("test-pkg")

        assert isinstance(details, PackageDetails)
        assert details.name == "test-pkg"
        assert details.stats is not None
        assert details.stats["total"] == 50000
        assert details.python_versions is not None
        assert len(details.python_versions) == 1
        assert details.os_stats is not None
        assert len(details.os_stats) == 1

    def test_service_generate_report(self, temp_db):
        """Service should generate HTML report."""
        service = PackageStatsService(temp_db)

        conn = get_db_connection(temp_db)
        init_db(conn)
        conn.execute("""
            INSERT INTO package_stats
            (package_name, fetch_date, last_day, last_week, last_month, total)
            VALUES ('test-pkg', '2024-01-01', 10, 70, 300, 1000)
        """)
        conn.commit()
        conn.close()

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", delete=False
        ) as f:
            output_path = f.name

        try:
            result = service.generate_report(output_path)
            assert result is True
            assert Path(output_path).exists()
            content = Path(output_path).read_text()
            assert "test-pkg" in content
        finally:
            Path(output_path).unlink(missing_ok=True)

    def test_service_generate_report_empty(self, temp_db):
        """Service should return False for empty report."""
        service = PackageStatsService(temp_db)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", delete=False
        ) as f:
            output_path = f.name

        try:
            result = service.generate_report(output_path)
            assert result is False
        finally:
            Path(output_path).unlink(missing_ok=True)

    def test_service_sync_packages_adds_new(self, temp_db):
        """sync_packages_from_user should add packages not already tracked."""
        service = PackageStatsService(temp_db)
        service.add_package("existing-pkg", verify=False)

        with patch("pkgdb.service.fetch_user_packages") as mock_fetch:
            mock_fetch.return_value = ["existing-pkg", "new-pkg-1", "new-pkg-2"]
            result = service.sync_packages_from_user("testuser")

        assert isinstance(result, SyncResult)
        assert result.added == ["new-pkg-1", "new-pkg-2"]
        assert result.already_tracked == ["existing-pkg"]
        assert result.not_on_remote == []
        assert result.pruned == []

        # Verify packages were actually added
        packages = [p.name for p in service.list_packages()]
        assert "existing-pkg" in packages
        assert "new-pkg-1" in packages
        assert "new-pkg-2" in packages

    def test_service_sync_packages_detects_not_on_remote(self, temp_db):
        """sync_packages_from_user should detect locally tracked packages not on remote."""
        service = PackageStatsService(temp_db)
        service.add_package("local-only-pkg", verify=False)
        service.add_package("common-pkg", verify=False)

        with patch("pkgdb.service.fetch_user_packages") as mock_fetch:
            mock_fetch.return_value = ["common-pkg", "new-remote-pkg"]
            result = service.sync_packages_from_user("testuser")

        assert result.added == ["new-remote-pkg"]
        assert result.already_tracked == ["common-pkg"]
        assert result.not_on_remote == ["local-only-pkg"]
        assert result.pruned == []

    def test_service_sync_packages_empty_remote(self, temp_db):
        """sync_packages_from_user should handle user with no packages."""
        service = PackageStatsService(temp_db)
        service.add_package("local-pkg", verify=False)

        with patch("pkgdb.service.fetch_user_packages") as mock_fetch:
            mock_fetch.return_value = []
            result = service.sync_packages_from_user("testuser")

        assert result.added == []
        assert result.already_tracked == []
        assert result.not_on_remote == ["local-pkg"]
        assert result.pruned == []

    def test_service_sync_packages_empty_local(self, temp_db):
        """sync_packages_from_user should add all packages when none tracked."""
        service = PackageStatsService(temp_db)

        with patch("pkgdb.service.fetch_user_packages") as mock_fetch:
            mock_fetch.return_value = ["pkg-a", "pkg-b"]
            result = service.sync_packages_from_user("testuser")

        assert result.added == ["pkg-a", "pkg-b"]
        assert result.already_tracked == []
        assert result.not_on_remote == []
        assert result.pruned == []

    def test_service_sync_packages_api_error(self, temp_db):
        """sync_packages_from_user should return None on API error."""
        service = PackageStatsService(temp_db)

        with patch("pkgdb.service.fetch_user_packages") as mock_fetch:
            mock_fetch.return_value = None
            result = service.sync_packages_from_user("testuser")

        assert result is None

    def test_service_sync_packages_no_changes(self, temp_db):
        """sync_packages_from_user should handle case where all packages already tracked."""
        service = PackageStatsService(temp_db)
        service.add_package("pkg-a", verify=False)
        service.add_package("pkg-b", verify=False)

        with patch("pkgdb.service.fetch_user_packages") as mock_fetch:
            mock_fetch.return_value = ["pkg-a", "pkg-b"]
            result = service.sync_packages_from_user("testuser")

        assert result.added == []
        assert sorted(result.already_tracked) == ["pkg-a", "pkg-b"]
        assert result.not_on_remote == []
        assert result.pruned == []

    def test_service_sync_packages_with_prune(self, temp_db):
        """sync_packages_from_user with prune=True should remove packages not on remote."""
        service = PackageStatsService(temp_db)
        service.add_package("local-only-pkg", verify=False)
        service.add_package("common-pkg", verify=False)

        with patch("pkgdb.service.fetch_user_packages") as mock_fetch:
            mock_fetch.return_value = ["common-pkg", "new-remote-pkg"]
            result = service.sync_packages_from_user("testuser", prune=True)

        assert result.added == ["new-remote-pkg"]
        assert result.already_tracked == ["common-pkg"]
        assert result.not_on_remote == ["local-only-pkg"]
        assert result.pruned == ["local-only-pkg"]

        # Verify package was actually removed
        packages = [p.name for p in service.list_packages()]
        assert "local-only-pkg" not in packages
        assert "common-pkg" in packages
        assert "new-remote-pkg" in packages

    def test_service_sync_packages_prune_multiple(self, temp_db):
        """sync_packages_from_user with prune=True should remove multiple packages."""
        service = PackageStatsService(temp_db)
        service.add_package("local-a", verify=False)
        service.add_package("local-b", verify=False)
        service.add_package("common-pkg", verify=False)

        with patch("pkgdb.service.fetch_user_packages") as mock_fetch:
            mock_fetch.return_value = ["common-pkg"]
            result = service.sync_packages_from_user("testuser", prune=True)

        assert result.added == []
        assert result.already_tracked == ["common-pkg"]
        assert result.not_on_remote == ["local-a", "local-b"]
        assert result.pruned == ["local-a", "local-b"]

        # Verify packages were removed
        packages = [p.name for p in service.list_packages()]
        assert packages == ["common-pkg"]


class TestPackageNameValidation:
    """Tests for package name validation."""

    def test_valid_package_names(self):
        """Valid package names should pass validation."""
        valid_names = [
            "requests",
            "my-package",
            "my_package",
            "my.package",
            "package123",
            "A1",
            "a",  # Single char is valid
            "ab",  # Two chars
            "my-pkg.v2_test",  # Mixed separators
        ]
        for name in valid_names:
            is_valid, error = validate_package_name(name)
            assert is_valid, f"'{name}' should be valid, got error: {error}"

    def test_empty_package_name(self):
        """Empty package name should fail validation."""
        is_valid, error = validate_package_name("")
        assert not is_valid
        assert "empty" in error.lower()

    def test_package_name_too_long(self):
        """Package name exceeding 100 chars should fail validation."""
        long_name = "a" * 101
        is_valid, error = validate_package_name(long_name)
        assert not is_valid
        assert "100" in error

    def test_package_name_invalid_start(self):
        """Package names starting with non-alphanumeric should fail."""
        invalid_names = ["-package", "_package", ".package"]
        for name in invalid_names:
            is_valid, error = validate_package_name(name)
            assert not is_valid, f"'{name}' should be invalid"

    def test_package_name_invalid_end(self):
        """Package names ending with non-alphanumeric should fail."""
        invalid_names = ["package-", "package_", "package."]
        for name in invalid_names:
            is_valid, error = validate_package_name(name)
            assert not is_valid, f"'{name}' should be invalid"

    def test_package_name_invalid_chars(self):
        """Package names with invalid characters should fail."""
        invalid_names = ["my package", "my@package", "my!pkg", "my/pkg"]
        for name in invalid_names:
            is_valid, error = validate_package_name(name)
            assert not is_valid, f"'{name}' should be invalid"

    def test_service_add_invalid_package_raises(self, temp_db):
        """Service.add_package should raise ValueError for invalid names."""
        service = PackageStatsService(temp_db)
        with pytest.raises(ValueError) as exc_info:
            service.add_package("")
        assert "empty" in str(exc_info.value).lower()

        with pytest.raises(ValueError):
            service.add_package("-invalid")

    def test_service_import_returns_invalid_names(self, temp_db):
        """Service.import_packages should return list of invalid names."""
        service = PackageStatsService(temp_db)

        # Create a temp file with mix of valid and invalid names
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("valid-pkg\n")
            f.write("-invalid\n")
            f.write("another-valid\n")
            f.write("also invalid spaces\n")
            temp_file = f.name

        try:
            added, skipped, invalid, not_found = service.import_packages(
                temp_file, verify=False
            )
            assert added == 2
            assert skipped == 0
            assert len(invalid) == 2
            assert "-invalid" in invalid
            assert "also invalid spaces" in invalid
            assert not_found == []
        finally:
            Path(temp_file).unlink()


# =============================================================================
# Integration Tests (require network, skipped by default)
# =============================================================================


@pytest.mark.integration
class TestIntegration:
    """Integration tests that make real API calls.

    Run with: pytest -m integration
    Or set environment variable: RUN_INTEGRATION=1 pytest
    """

    @pytest.mark.skipif(
        os.environ.get("RUN_INTEGRATION") != "1",
        reason="Integration tests disabled (set RUN_INTEGRATION=1 to enable)"
    )
    def test_fetch_real_package_stats(self):
        """fetch_package_stats should return real data for a known package."""
        stats = fetch_package_stats("requests")
        assert stats is not None
        assert stats["total"] > 0
        assert stats["last_month"] > 0
        assert stats["last_week"] >= 0
        assert stats["last_day"] >= 0

    @pytest.mark.skipif(
        os.environ.get("RUN_INTEGRATION") != "1",
        reason="Integration tests disabled (set RUN_INTEGRATION=1 to enable)"
    )
    def test_fetch_real_python_versions(self):
        """fetch_python_versions should return real data for a known package."""
        versions = fetch_python_versions("requests")
        assert versions is not None
        assert len(versions) > 0
        # Should have common Python versions
        categories = [v["category"] for v in versions]
        assert any("3." in cat for cat in categories if cat)

    @pytest.mark.skipif(
        os.environ.get("RUN_INTEGRATION") != "1",
        reason="Integration tests disabled (set RUN_INTEGRATION=1 to enable)"
    )
    def test_fetch_real_os_stats(self):
        """fetch_os_stats should return real data for a known package."""
        os_stats = fetch_os_stats("requests")
        assert os_stats is not None
        assert len(os_stats) > 0
        # Should have common OS categories
        categories = [s["category"] for s in os_stats]
        assert any(cat in ["Linux", "Windows", "Darwin"] for cat in categories if cat)

    @pytest.mark.skipif(
        os.environ.get("RUN_INTEGRATION") != "1",
        reason="Integration tests disabled (set RUN_INTEGRATION=1 to enable)"
    )
    def test_fetch_nonexistent_package(self):
        """fetch_package_stats should return None for nonexistent package."""
        stats = fetch_package_stats("this-package-definitely-does-not-exist-12345")
        assert stats is None


# =============================================================================
# Edge Case Tests for Chart Generation
# =============================================================================


class TestChartEdgeCases:
    """Tests for edge cases in chart generation."""

    def test_pie_chart_exactly_six_items(self):
        """Pie chart with exactly PIE_CHART_MAX_ITEMS should not group into Other."""
        data = [
            ("A", 100), ("B", 90), ("C", 80),
            ("D", 70), ("E", 60), ("F", 50),
        ]
        svg = make_svg_pie_chart(data, "test-chart")

        # All items should be present (no "Other")
        assert "A" in svg
        assert "B" in svg
        assert "C" in svg
        assert "D" in svg
        assert "E" in svg
        assert "F" in svg
        assert "Other" not in svg

    def test_pie_chart_seven_items_groups_other(self):
        """Pie chart with 7 items should group last items into Other."""
        data = [
            ("A", 100), ("B", 90), ("C", 80),
            ("D", 70), ("E", 60), ("F", 50), ("G", 40),
        ]
        svg = make_svg_pie_chart(data, "test-chart")

        # Should have "Other" for items beyond limit
        assert "Other" in svg
        # Last item should not appear individually
        assert "G" not in svg

    def test_pie_chart_single_item(self):
        """Pie chart with single item should render correctly."""
        data = [("Only", 100)]
        svg = make_svg_pie_chart(data, "test-chart")

        assert "<svg" in svg
        assert "Only" in svg
        assert "100.0%" in svg

    def test_pie_chart_very_small_slice(self):
        """Pie chart should handle very small percentage slices."""
        data = [("Big", 99999), ("Tiny", 1)]
        svg = make_svg_pie_chart(data, "test-chart")

        assert "Big" in svg
        assert "Tiny" in svg
        # Small slice should still render (even if thin)
        assert svg.count("<path") >= 2

    def test_line_chart_single_data_point(self):
        """Line chart with single data point should return empty."""
        from pkgdb.reports import _make_single_line_chart

        dates = ["2024-01-01"]
        values = [1000]
        svg = _make_single_line_chart(dates, values)

        # Single point cannot form a line
        assert svg == ""

    def test_line_chart_two_data_points(self):
        """Line chart with two data points should render."""
        from pkgdb.reports import _make_single_line_chart

        dates = ["2024-01-01", "2024-01-02"]
        values = [1000, 2000]
        svg = _make_single_line_chart(dates, values)

        assert "<svg" in svg
        assert "polyline" in svg

    def test_line_chart_constant_values(self):
        """Line chart with all same values should render flat line."""
        from pkgdb.reports import _make_single_line_chart

        dates = ["2024-01-01", "2024-01-02", "2024-01-03"]
        values = [1000, 1000, 1000]
        svg = _make_single_line_chart(dates, values)

        assert "<svg" in svg
        assert "polyline" in svg

    def test_line_chart_zero_values(self):
        """Line chart with zero values should render."""
        from pkgdb.reports import _make_single_line_chart

        dates = ["2024-01-01", "2024-01-02", "2024-01-03"]
        values = [0, 0, 0]
        svg = _make_single_line_chart(dates, values)

        assert "<svg" in svg

    def test_bar_chart_very_large_numbers(self):
        """Bar chart should handle very large download numbers."""
        from pkgdb.reports import _make_svg_bar_chart

        data = [
            ("huge-pkg", 1_000_000_000),  # 1 billion
            ("big-pkg", 100_000_000),     # 100 million
        ]
        svg = _make_svg_bar_chart(data, "Downloads", "test-chart")

        assert "<svg" in svg
        assert "huge-pkg" in svg
        assert "1,000,000,000" in svg

    def test_bar_chart_single_item(self):
        """Bar chart with single item should render."""
        from pkgdb.reports import _make_svg_bar_chart

        data = [("only-pkg", 1000)]
        svg = _make_svg_bar_chart(data, "Downloads", "test-chart")

        assert "<svg" in svg
        assert "only-pkg" in svg

    def test_bar_chart_empty_data(self):
        """Bar chart with empty data should return empty string."""
        from pkgdb.reports import _make_svg_bar_chart

        svg = _make_svg_bar_chart([], "Downloads", "test-chart")
        assert svg == ""

    def test_multi_line_chart_single_package(self):
        """Multi-line chart with single package should render."""
        from pkgdb.reports import _make_multi_line_chart

        history = {
            "pkg-a": [
                {"fetch_date": "2024-01-01", "total": 1000},
                {"fetch_date": "2024-01-02", "total": 2000},
            ]
        }
        svg = _make_multi_line_chart(history, "test-chart")

        assert "<svg" in svg
        assert "pkg-a" in svg

    def test_multi_line_chart_empty_history(self):
        """Multi-line chart with empty history should return empty."""
        from pkgdb.reports import _make_multi_line_chart

        svg = _make_multi_line_chart({}, "test-chart")
        assert svg == ""

    def test_multi_line_chart_single_date(self):
        """Multi-line chart with single date should show message."""
        from pkgdb.reports import _make_multi_line_chart

        history = {
            "pkg-a": [{"fetch_date": "2024-01-01", "total": 1000}]
        }
        svg = _make_multi_line_chart(history, "test-chart")

        assert "Not enough" in svg


# =============================================================================
# Error Path Tests
# =============================================================================


class TestErrorPaths:
    """Tests for error handling and edge cases."""

    def test_database_invalid_path(self):
        """get_db should handle invalid paths gracefully."""
        # Directory that doesn't exist
        with pytest.raises((sqlite3.OperationalError, OSError)):
            with get_db("/nonexistent/path/to/db.sqlite") as conn:
                pass

    def test_database_readonly_after_init(self, temp_db):
        """Database operations should work after init."""
        with get_db(temp_db) as conn:
            # Should be able to add packages
            assert add_package(conn, "test-pkg") is True
            # Should be able to query
            packages = get_packages(conn)
            assert "test-pkg" in packages

    def test_store_stats_with_none_values(self, db_conn):
        """store_stats should handle None values in stats dict."""
        stats = {
            "last_day": None,
            "last_week": None,
            "last_month": None,
            "total": None,
        }
        # Should not raise
        store_stats(db_conn, "test-pkg", stats)

        cursor = db_conn.execute(
            "SELECT * FROM package_stats WHERE package_name = ?",
            ("test-pkg",)
        )
        row = cursor.fetchone()
        assert row is not None
        assert row["last_day"] is None
        assert row["total"] is None

    def test_load_packages_invalid_json(self):
        """load_packages should handle invalid JSON gracefully."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{invalid json")
            path = f.name

        try:
            with pytest.raises(json.JSONDecodeError):
                load_packages(path)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_load_packages_from_file_invalid_json(self):
        """load_packages_from_file should handle invalid JSON."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{invalid json")
            path = f.name

        try:
            with pytest.raises(json.JSONDecodeError):
                load_packages_from_file(path)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_load_packages_from_file_wrong_json_type(self):
        """load_packages_from_file should handle wrong JSON structure."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump("just a string", f)
            path = f.name

        try:
            packages = load_packages_from_file(path)
            # Should return empty or handle gracefully
            assert packages == [] or packages is None
        finally:
            Path(path).unlink(missing_ok=True)

    def test_fetch_partial_api_failure(self):
        """fetch_all_package_stats should handle partial failures."""
        from pkgdb.api import fetch_all_package_stats

        recent_success = json.dumps({
            "data": {"last_day": 100, "last_week": 700, "last_month": 3000}
        })
        overall_success = json.dumps({
            "data": [{"category": "without_mirrors", "downloads": 50000}]
        })

        call_count = {"count": 0}

        def mock_recent(pkg, format=None):
            call_count["count"] += 1
            if pkg == "fail-pkg":
                raise ValueError("API error")
            return recent_success

        def mock_overall(pkg, format=None):
            if pkg == "fail-pkg":
                raise ValueError("API error")
            return overall_success

        with patch("pkgdb.api.pypistats.recent", side_effect=mock_recent):
            with patch("pkgdb.api.pypistats.overall", side_effect=mock_overall):
                results = fetch_all_package_stats(["good-pkg", "fail-pkg", "another-good"])

        # Should have results for all packages
        assert len(results) == 3
        # Good packages should have stats
        assert results["good-pkg"] is not None
        assert results["another-good"] is not None
        # Failed package should be None
        assert results["fail-pkg"] is None

    def test_generate_report_handles_missing_history_gracefully(self):
        """generate_html_report should work with None history values."""
        stats = [
            {"package_name": "pkg", "total": 1000, "last_month": 300, "last_week": 70, "last_day": 10}
        ]
        history = {
            "pkg": [
                {"fetch_date": "2024-01-01", "total": None, "last_month": None, "last_week": None, "last_day": None}
            ]
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
            output_path = f.name

        try:
            # Should not raise
            generate_html_report(stats, output_path, history)
            assert Path(output_path).exists()
        finally:
            Path(output_path).unlink(missing_ok=True)

    def test_service_cleanup_empty_db(self, temp_db):
        """Service cleanup should work on empty database."""
        service = PackageStatsService(temp_db)
        orphaned, remaining = service.cleanup()
        assert orphaned == 0
        assert remaining == 0

    def test_service_prune_no_old_data(self, temp_db):
        """Service prune should work when no old data exists."""
        service = PackageStatsService(temp_db)
        deleted = service.prune(days=30)
        assert deleted == 0


# =============================================================================
# Performance Tests (skipped by default)
# =============================================================================


@pytest.mark.slow
class TestPerformance:
    """Performance tests for large datasets.

    Run with: pytest -m slow
    """

    @pytest.mark.skipif(
        os.environ.get("RUN_SLOW_TESTS") != "1",
        reason="Slow tests disabled (set RUN_SLOW_TESTS=1 to enable)"
    )
    def test_large_number_of_packages(self, temp_db):
        """Database should handle 100+ packages efficiently."""
        import time

        service = PackageStatsService(temp_db)

        # Add 100 packages (skip verify for performance testing)
        start = time.time()
        for i in range(100):
            service.add_package(f"test-package-{i:03d}", verify=False)
        add_time = time.time() - start

        # Should complete in reasonable time (< 5 seconds)
        assert add_time < 5.0, f"Adding 100 packages took {add_time:.2f}s"

        # List should be fast
        start = time.time()
        packages = service.list_packages()
        list_time = time.time() - start

        assert len(packages) == 100
        assert list_time < 1.0, f"Listing 100 packages took {list_time:.2f}s"

    @pytest.mark.skipif(
        os.environ.get("RUN_SLOW_TESTS") != "1",
        reason="Slow tests disabled (set RUN_SLOW_TESTS=1 to enable)"
    )
    def test_large_historical_data(self, temp_db):
        """Database should handle 1000+ days of history efficiently."""
        import time
        from datetime import datetime, timedelta

        conn = get_db_connection(temp_db)
        init_db(conn)

        # Insert 1000 days of history for 10 packages
        start = time.time()
        base_date = datetime(2020, 1, 1)
        for pkg_num in range(10):
            pkg_name = f"pkg-{pkg_num}"
            for day in range(1000):
                date = (base_date + timedelta(days=day)).strftime("%Y-%m-%d")
                conn.execute(
                    """
                    INSERT INTO package_stats
                    (package_name, fetch_date, last_day, last_week, last_month, total)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (pkg_name, date, day * 10, day * 70, day * 300, day * 1000)
                )
        conn.commit()
        insert_time = time.time() - start

        # Query should be fast
        start = time.time()
        stats = get_latest_stats(conn)
        query_time = time.time() - start

        conn.close()

        assert len(stats) == 10
        assert insert_time < 30.0, f"Inserting 10k records took {insert_time:.2f}s"
        assert query_time < 1.0, f"Querying latest stats took {query_time:.2f}s"

    @pytest.mark.skipif(
        os.environ.get("RUN_SLOW_TESTS") != "1",
        reason="Slow tests disabled (set RUN_SLOW_TESTS=1 to enable)"
    )
    def test_report_generation_performance(self, temp_db):
        """Report generation should complete in reasonable time."""
        import time

        conn = get_db_connection(temp_db)
        init_db(conn)

        # Create test data: 50 packages with 30 days history each
        from datetime import datetime, timedelta
        base_date = datetime(2024, 1, 1)
        for pkg_num in range(50):
            pkg_name = f"package-{pkg_num:03d}"
            for day in range(30):
                date = (base_date + timedelta(days=day)).strftime("%Y-%m-%d")
                conn.execute(
                    """
                    INSERT INTO package_stats
                    (package_name, fetch_date, last_day, last_week, last_month, total)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (pkg_name, date, 100 + day, 700 + day * 7, 3000 + day * 30, 50000 + day * 100)
                )
        conn.commit()

        stats = get_latest_stats(conn)
        history = get_all_history(conn, limit_per_package=30)
        conn.close()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
            output_path = f.name

        try:
            start = time.time()
            generate_html_report(stats, output_path, history)
            gen_time = time.time() - start

            assert Path(output_path).exists()
            # Should generate in reasonable time (< 5 seconds)
            assert gen_time < 5.0, f"Report generation took {gen_time:.2f}s"

            # File should be reasonable size (< 1MB for 50 packages)
            file_size = Path(output_path).stat().st_size
            assert file_size < 1_000_000, f"Report file is {file_size} bytes"
        finally:
            Path(output_path).unlink(missing_ok=True)

    @pytest.mark.skipif(
        os.environ.get("RUN_SLOW_TESTS") != "1",
        reason="Slow tests disabled (set RUN_SLOW_TESTS=1 to enable)"
    )
    def test_get_stats_with_growth_performance(self, temp_db):
        """get_stats_with_growth should be efficient with many packages."""
        import time
        from datetime import datetime, timedelta
        from pkgdb.db import get_stats_with_growth

        conn = get_db_connection(temp_db)
        init_db(conn)

        # Create 50 packages with 31 days of history
        base_date = datetime(2024, 1, 1)
        for pkg_num in range(50):
            pkg_name = f"pkg-{pkg_num:03d}"
            for day in range(31):
                date = (base_date + timedelta(days=day)).strftime("%Y-%m-%d")
                conn.execute(
                    """
                    INSERT INTO package_stats
                    (package_name, fetch_date, last_day, last_week, last_month, total)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (pkg_name, date, 100, 700, 3000 + day * 10, 50000 + day * 100)
                )
        conn.commit()

        # Time the growth calculation
        start = time.time()
        stats = get_stats_with_growth(conn)
        calc_time = time.time() - start

        conn.close()

        assert len(stats) == 50
        # Should complete quickly due to optimized query (< 1 second)
        assert calc_time < 1.0, f"Growth calculation took {calc_time:.2f}s"
        # Verify growth is calculated
        assert all("week_growth" in s for s in stats)
        assert all("month_growth" in s for s in stats)


# =============================================================================
# Output Path Validation Tests
# =============================================================================


class TestOutputPathValidation:
    """Tests for output path validation."""

    def test_valid_path_in_temp_dir(self):
        """Valid path in temp directory should pass."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "output.html")
            is_valid, error = validate_output_path(path)
            assert is_valid, f"Should be valid: {error}"

    def test_valid_path_with_allowed_extension(self):
        """Path with allowed extension should pass."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "report.html")
            is_valid, error = validate_output_path(path, allowed_extensions=[".html"])
            assert is_valid, f"Should be valid: {error}"

    def test_invalid_extension(self):
        """Path with wrong extension should fail."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "report.txt")
            is_valid, error = validate_output_path(path, allowed_extensions=[".html"])
            assert not is_valid
            assert "extension" in error.lower()

    def test_empty_path(self):
        """Empty path should fail."""
        is_valid, error = validate_output_path("")
        assert not is_valid
        assert "empty" in error.lower()

    def test_nonexistent_parent_directory(self):
        """Path with nonexistent parent should fail."""
        is_valid, error = validate_output_path("/nonexistent/directory/file.html")
        assert not is_valid
        assert "not exist" in error.lower()

    def test_sensitive_system_path_unix(self):
        """Paths to sensitive Unix directories should fail."""
        if os.name != "nt":  # Skip on Windows
            is_valid, error = validate_output_path("/etc/passwd.html")
            assert not is_valid
            # Could be rejected as system directory or as not writable
            assert "directory" in error.lower()

    def test_path_traversal_detection(self):
        """Path traversal attempts should be caught."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # This resolves to parent directory which should still work
            # if it's writable, but the path is normalized
            path = os.path.join(tmpdir, "..", "output.html")
            # The validation should resolve the path
            is_valid, error = validate_output_path(path)
            # May or may not be valid depending on parent permissions
            # The key is that .. is resolved
            assert isinstance(is_valid, bool)

    def test_writable_check(self):
        """Non-writable parent should fail when must_be_writable=True."""
        # /usr should not be writable for normal users
        if os.name != "nt" and not os.access("/usr", os.W_OK):
            is_valid, error = validate_output_path("/usr/output.html", must_be_writable=True)
            assert not is_valid


# =============================================================================
# Batch Stats Storage Tests
# =============================================================================


class TestBatchStatsStorage:
    """Tests for batch stats storage functionality."""

    def test_store_stats_batch_basic(self, db_conn):
        """store_stats_batch should store multiple packages in one transaction."""
        stats_list = [
            ("pkg-a", {"last_day": 10, "last_week": 70, "last_month": 300, "total": 1000}),
            ("pkg-b", {"last_day": 20, "last_week": 140, "last_month": 600, "total": 2000}),
            ("pkg-c", {"last_day": 30, "last_week": 210, "last_month": 900, "total": 3000}),
        ]

        count = store_stats_batch(db_conn, stats_list)
        assert count == 3

        # Verify all packages stored
        cursor = db_conn.execute("SELECT COUNT(*) as count FROM package_stats")
        assert cursor.fetchone()["count"] == 3

        # Verify data correctness
        cursor = db_conn.execute(
            "SELECT total FROM package_stats WHERE package_name = ?", ("pkg-b",)
        )
        assert cursor.fetchone()["total"] == 2000

    def test_store_stats_batch_empty_list(self, db_conn):
        """store_stats_batch should handle empty list."""
        count = store_stats_batch(db_conn, [])
        assert count == 0

    def test_store_stats_batch_single_commit(self, db_conn):
        """store_stats_batch should use single commit (more efficient)."""
        # This is a behavioral test - batch should be faster than individual
        stats_list = [
            (f"pkg-{i}", {"last_day": i, "last_week": i*7, "last_month": i*30, "total": i*100})
            for i in range(10)
        ]

        count = store_stats_batch(db_conn, stats_list)
        assert count == 10

        # All should be stored
        cursor = db_conn.execute("SELECT COUNT(*) as count FROM package_stats")
        assert cursor.fetchone()["count"] == 10

    def test_store_stats_with_commit_false(self, db_conn):
        """store_stats with commit=False should not auto-commit."""
        stats = {"last_day": 100, "last_week": 700, "last_month": 3000, "total": 50000}

        # Store without commit
        store_stats(db_conn, "test-pkg", stats, commit=False)

        # Should be visible in same connection
        cursor = db_conn.execute(
            "SELECT * FROM package_stats WHERE package_name = ?", ("test-pkg",)
        )
        row = cursor.fetchone()
        assert row is not None

        # Manual commit
        db_conn.commit()

    def test_service_fetch_uses_batch_commit(self, temp_db):
        """Service fetch_all_stats should use batch commits."""
        service = PackageStatsService(temp_db)
        service.add_package("pkg-a", verify=False)
        service.add_package("pkg-b", verify=False)

        recent_response = json.dumps({
            "data": {"last_day": 100, "last_week": 700, "last_month": 3000}
        })
        overall_response = json.dumps({
            "data": [{"category": "without_mirrors", "downloads": 50000}]
        })

        with patch("pkgdb.api.pypistats.recent", return_value=recent_response):
            with patch("pkgdb.api.pypistats.overall", return_value=overall_response):
                result = service.fetch_all_stats()

        assert result.success == 2
        assert result.failed == 0
        assert result.skipped == 0

        # Both should be stored
        stats = service.get_stats()
        assert len(stats) == 2


# =============================================================================
# Fetch Attempt Tracking Tests
# =============================================================================


class TestFetchAttemptTracking:
    """Tests for fetch attempt tracking functionality."""

    def test_record_fetch_attempt_success(self, temp_db):
        """record_fetch_attempt should store successful attempts."""
        conn = get_db_connection(temp_db)
        init_db(conn)

        record_fetch_attempt(conn, "test-pkg", success=True)

        cursor = conn.execute(
            "SELECT * FROM fetch_attempts WHERE package_name = ?",
            ("test-pkg",)
        )
        row = cursor.fetchone()
        assert row is not None
        assert row["package_name"] == "test-pkg"
        assert row["success"] == 1
        assert row["attempt_time"] is not None
        conn.close()

    def test_record_fetch_attempt_failure(self, temp_db):
        """record_fetch_attempt should store failed attempts."""
        conn = get_db_connection(temp_db)
        init_db(conn)

        record_fetch_attempt(conn, "test-pkg", success=False)

        cursor = conn.execute(
            "SELECT * FROM fetch_attempts WHERE package_name = ?",
            ("test-pkg",)
        )
        row = cursor.fetchone()
        assert row is not None
        assert row["success"] == 0
        conn.close()

    def test_record_fetch_attempt_updates_existing(self, temp_db):
        """record_fetch_attempt should update existing records."""
        conn = get_db_connection(temp_db)
        init_db(conn)

        # First attempt fails
        record_fetch_attempt(conn, "test-pkg", success=False)
        # Second attempt succeeds
        record_fetch_attempt(conn, "test-pkg", success=True)

        cursor = conn.execute(
            "SELECT COUNT(*) as count FROM fetch_attempts WHERE package_name = ?",
            ("test-pkg",)
        )
        assert cursor.fetchone()["count"] == 1

        cursor = conn.execute(
            "SELECT success FROM fetch_attempts WHERE package_name = ?",
            ("test-pkg",)
        )
        assert cursor.fetchone()["success"] == 1
        conn.close()

    def test_get_packages_needing_update_all_packages(self, temp_db):
        """get_packages_needing_update should return all packages when none have been fetched."""
        conn = get_db_connection(temp_db)
        init_db(conn)
        add_package(conn, "pkg-a")
        add_package(conn, "pkg-b")

        packages = get_packages_needing_update(conn)
        assert set(packages) == {"pkg-a", "pkg-b"}
        conn.close()

    def test_get_packages_needing_update_excludes_recent(self, temp_db):
        """get_packages_needing_update should exclude recently fetched packages."""
        conn = get_db_connection(temp_db)
        init_db(conn)
        add_package(conn, "pkg-a")
        add_package(conn, "pkg-b")
        add_package(conn, "pkg-c")

        # Mark pkg-a as recently fetched
        record_fetch_attempt(conn, "pkg-a", success=True)

        packages = get_packages_needing_update(conn)
        assert "pkg-a" not in packages
        assert set(packages) == {"pkg-b", "pkg-c"}
        conn.close()

    def test_get_packages_needing_update_includes_old_attempts(self, temp_db):
        """get_packages_needing_update should include packages with old attempts."""
        conn = get_db_connection(temp_db)
        init_db(conn)
        add_package(conn, "pkg-a")

        # Insert an old attempt (25 hours ago)
        conn.execute(
            """
            INSERT INTO fetch_attempts (package_name, attempt_time, success)
            VALUES (?, datetime('now', '-25 hours'), 1)
            """,
            ("pkg-a",)
        )
        conn.commit()

        packages = get_packages_needing_update(conn)
        assert "pkg-a" in packages
        conn.close()

    def test_service_fetch_skips_recent_packages(self, temp_db):
        """Service fetch_all_stats should skip recently fetched packages."""
        service = PackageStatsService(temp_db)
        service.add_package("pkg-a", verify=False)
        service.add_package("pkg-b", verify=False)

        recent_response = json.dumps({
            "data": {"last_day": 100, "last_week": 700, "last_month": 3000}
        })
        overall_response = json.dumps({
            "data": [{"category": "without_mirrors", "downloads": 50000}]
        })

        # First fetch - both packages
        with patch("pkgdb.api.pypistats.recent", return_value=recent_response):
            with patch("pkgdb.api.pypistats.overall", return_value=overall_response):
                result1 = service.fetch_all_stats()

        assert result1.success == 2
        assert result1.skipped == 0

        # Second fetch - both should be skipped
        with patch("pkgdb.api.pypistats.recent", return_value=recent_response):
            with patch("pkgdb.api.pypistats.overall", return_value=overall_response):
                result2 = service.fetch_all_stats()

        assert result2.success == 0
        assert result2.skipped == 2

    def test_service_fetch_records_failed_attempts(self, temp_db):
        """Service fetch_all_stats should record failed fetch attempts."""
        service = PackageStatsService(temp_db)
        service.add_package("failing-pkg", verify=False)

        # Mock API to fail with ValueError (which is in _API_ERRORS)
        with patch("pkgdb.api.pypistats.recent", side_effect=ValueError("API error")):
            result1 = service.fetch_all_stats()

        assert result1.failed == 1
        assert result1.success == 0

        # Second fetch should retry the failed package (not skip it)
        with patch("pkgdb.api.pypistats.recent", side_effect=ValueError("API error")):
            result2 = service.fetch_all_stats()

        assert result2.failed == 1
        assert result2.skipped == 0

    def test_get_packages_needing_update_retries_after_failure(self, temp_db):
        """get_packages_needing_update should retry packages whose last attempt failed."""
        conn = get_db_connection(temp_db)
        init_db(conn)
        add_package(conn, "pkg-a")

        # Record a recent failed attempt
        record_fetch_attempt(conn, "pkg-a", success=False)

        packages = get_packages_needing_update(conn)
        assert "pkg-a" in packages
        conn.close()

    def test_get_packages_needing_update_skips_recent_success(self, temp_db):
        """get_packages_needing_update should skip packages with recent successful fetch."""
        conn = get_db_connection(temp_db)
        init_db(conn)
        add_package(conn, "pkg-a")

        # Record a recent successful attempt
        record_fetch_attempt(conn, "pkg-a", success=True)

        packages = get_packages_needing_update(conn)
        assert "pkg-a" not in packages
        conn.close()


class TestNextUpdateTime:
    """Tests for next update time calculation."""

    def test_get_next_update_seconds_with_recent_success(self, temp_db):
        """get_next_update_seconds should return remaining seconds when packages are throttled."""
        from pkgdb import get_next_update_seconds

        conn = get_db_connection(temp_db)
        init_db(conn)
        add_package(conn, "pkg-a")
        record_fetch_attempt(conn, "pkg-a", success=True)

        seconds = get_next_update_seconds(conn)
        # Should be close to 24 hours (86400s), with some tolerance
        assert seconds is not None
        assert 86000 < seconds <= 86400
        conn.close()

    def test_get_next_update_seconds_no_attempts(self, temp_db):
        """get_next_update_seconds should return None when no packages are throttled."""
        from pkgdb import get_next_update_seconds

        conn = get_db_connection(temp_db)
        init_db(conn)
        add_package(conn, "pkg-a")

        seconds = get_next_update_seconds(conn)
        assert seconds is None
        conn.close()

    def test_get_next_update_seconds_only_failed(self, temp_db):
        """get_next_update_seconds should return None when only failed attempts exist."""
        from pkgdb import get_next_update_seconds

        conn = get_db_connection(temp_db)
        init_db(conn)
        add_package(conn, "pkg-a")
        record_fetch_attempt(conn, "pkg-a", success=False)

        seconds = get_next_update_seconds(conn)
        assert seconds is None
        conn.close()

    def test_fetch_result_includes_next_update(self, temp_db):
        """FetchResult should include next_update_seconds when all packages are skipped."""
        service = PackageStatsService(temp_db)
        service.add_package("pkg-a", verify=False)

        # First fetch succeeds
        recent = json.dumps({"data": {"last_day": 10, "last_week": 70, "last_month": 300}})
        overall = json.dumps({"data": [{"category": "without_mirrors", "downloads": 5000}]})
        with patch("pkgdb.api.pypistats.recent", return_value=recent):
            with patch("pkgdb.api.pypistats.overall", return_value=overall):
                result1 = service.fetch_all_stats()

        assert result1.success == 1

        # Second fetch - all skipped, should include next_update_seconds
        result2 = service.fetch_all_stats()
        assert result2.skipped == 1
        assert result2.next_update_seconds is not None
        assert result2.next_update_seconds > 0


# =============================================================================
# Environment Stats Caching Tests
# =============================================================================


class TestEnvStatsCache:
    """Tests for caching Python version and OS distribution stats in SQLite."""

    def test_store_and_retrieve_python_versions(self, temp_db):
        """store_env_stats should persist Python version data retrievable by get_cached_python_versions."""
        from pkgdb import store_env_stats, get_cached_python_versions

        conn = get_db_connection(temp_db)
        init_db(conn)
        add_package(conn, "test-pkg")

        py_versions = [
            {"category": "3.12", "downloads": 500},
            {"category": "3.11", "downloads": 300},
            {"category": "3.10", "downloads": 100},
        ]
        store_env_stats(conn, "test-pkg", python_versions=py_versions)

        cached = get_cached_python_versions(conn, "test-pkg")
        assert cached is not None
        assert len(cached) == 3
        # Should be sorted by downloads descending
        assert cached[0]["category"] == "3.12"
        assert cached[0]["downloads"] == 500
        assert cached[2]["category"] == "3.10"
        conn.close()

    def test_store_and_retrieve_os_stats(self, temp_db):
        """store_env_stats should persist OS data retrievable by get_cached_os_stats."""
        from pkgdb import store_env_stats, get_cached_os_stats

        conn = get_db_connection(temp_db)
        init_db(conn)
        add_package(conn, "test-pkg")

        os_data = [
            {"category": "Linux", "downloads": 800},
            {"category": "Windows", "downloads": 400},
            {"category": "Darwin", "downloads": 200},
        ]
        store_env_stats(conn, "test-pkg", os_data=os_data)

        cached = get_cached_os_stats(conn, "test-pkg")
        assert cached is not None
        assert len(cached) == 3
        assert cached[0]["category"] == "Linux"
        assert cached[0]["downloads"] == 800
        conn.close()

    def test_cached_returns_none_when_empty(self, temp_db):
        """get_cached_* should return None when no data exists."""
        from pkgdb import get_cached_python_versions, get_cached_os_stats

        conn = get_db_connection(temp_db)
        init_db(conn)

        assert get_cached_python_versions(conn, "nonexistent") is None
        assert get_cached_os_stats(conn, "nonexistent") is None
        conn.close()

    def test_store_env_stats_none_inputs(self, temp_db):
        """store_env_stats should handle None inputs gracefully."""
        from pkgdb import store_env_stats, get_cached_python_versions, get_cached_os_stats

        conn = get_db_connection(temp_db)
        init_db(conn)
        add_package(conn, "test-pkg")

        store_env_stats(conn, "test-pkg", python_versions=None, os_data=None)

        assert get_cached_python_versions(conn, "test-pkg") is None
        assert get_cached_os_stats(conn, "test-pkg") is None
        conn.close()

    def test_get_cached_env_summary_aggregates(self, temp_db):
        """get_cached_env_summary should aggregate across all packages."""
        from pkgdb import store_env_stats, get_cached_env_summary

        conn = get_db_connection(temp_db)
        init_db(conn)
        add_package(conn, "pkg-a")
        add_package(conn, "pkg-b")

        store_env_stats(conn, "pkg-a",
            python_versions=[{"category": "3.12", "downloads": 100}],
            os_data=[{"category": "Linux", "downloads": 200}],
        )
        store_env_stats(conn, "pkg-b",
            python_versions=[{"category": "3.12", "downloads": 50}, {"category": "3.11", "downloads": 30}],
            os_data=[{"category": "Linux", "downloads": 100}, {"category": "Windows", "downloads": 80}],
        )

        summary = get_cached_env_summary(conn)
        assert summary is not None

        py_dict = dict(summary["python_versions"])
        assert py_dict["3.12"] == 150
        assert py_dict["3.11"] == 30

        os_dict = dict(summary["os_distribution"])
        assert os_dict["Linux"] == 300
        assert os_dict["Windows"] == 80
        conn.close()

    def test_get_cached_env_summary_returns_none_when_empty(self, temp_db):
        """get_cached_env_summary should return None when no cached data exists."""
        from pkgdb import get_cached_env_summary

        conn = get_db_connection(temp_db)
        init_db(conn)

        assert get_cached_env_summary(conn) is None
        conn.close()

    def test_cleanup_orphaned_stats_cleans_env_tables(self, temp_db):
        """cleanup_orphaned_stats should also remove orphaned env stats."""
        from pkgdb import store_env_stats, get_cached_python_versions, cleanup_orphaned_stats

        conn = get_db_connection(temp_db)
        init_db(conn)
        add_package(conn, "tracked-pkg")

        store_env_stats(conn, "tracked-pkg",
            python_versions=[{"category": "3.12", "downloads": 100}])
        # Insert env data for a package that isn't tracked
        conn.execute(
            "INSERT INTO python_version_stats (package_name, fetch_date, category, downloads) VALUES (?, ?, ?, ?)",
            ("orphan-pkg", "2026-01-01", "3.12", 50),
        )
        conn.commit()

        cleanup_orphaned_stats(conn)

        assert get_cached_python_versions(conn, "tracked-pkg") is not None
        assert get_cached_python_versions(conn, "orphan-pkg") is None
        conn.close()

    def test_prune_old_stats_prunes_env_tables(self, temp_db):
        """prune_old_stats should also remove old env stats."""
        from pkgdb import store_env_stats, get_cached_python_versions, prune_old_stats

        conn = get_db_connection(temp_db)
        init_db(conn)
        add_package(conn, "test-pkg")

        # Insert old env data
        conn.execute(
            "INSERT INTO python_version_stats (package_name, fetch_date, category, downloads) VALUES (?, ?, ?, ?)",
            ("test-pkg", "2020-01-01", "3.8", 100),
        )
        # Insert recent env data
        store_env_stats(conn, "test-pkg",
            python_versions=[{"category": "3.12", "downloads": 200}])

        prune_old_stats(conn, days=30)

        cached = get_cached_python_versions(conn, "test-pkg")
        assert cached is not None
        assert len(cached) == 1
        assert cached[0]["category"] == "3.12"
        conn.close()

    def test_fetch_all_stats_stores_env_data(self, temp_db):
        """fetch_all_stats should store env stats alongside download stats."""
        from pkgdb import get_cached_python_versions, get_cached_os_stats

        service = PackageStatsService(temp_db)
        service.add_package("test-pkg", verify=False)

        recent = json.dumps({"data": {"last_day": 10, "last_week": 70, "last_month": 300}})
        overall = json.dumps({"data": [{"category": "without_mirrors", "downloads": 5000}]})
        py_response = json.dumps({"data": [{"category": "3.12", "downloads": 100}]})
        os_response = json.dumps({"data": [{"category": "Linux", "downloads": 200}]})

        with patch("pkgdb.api.pypistats.recent", return_value=recent):
            with patch("pkgdb.api.pypistats.overall", return_value=overall):
                with patch("pkgdb.api.pypistats.python_minor", return_value=py_response):
                    with patch("pkgdb.api.pypistats.system", return_value=os_response):
                        result = service.fetch_all_stats()

        assert result.success == 1

        conn = get_db_connection(temp_db)
        init_db(conn)
        py = get_cached_python_versions(conn, "test-pkg")
        os_data = get_cached_os_stats(conn, "test-pkg")
        assert py is not None
        assert py[0]["category"] == "3.12"
        assert os_data is not None
        assert os_data[0]["category"] == "Linux"
        conn.close()

    def test_package_report_uses_cached_env(self, temp_db):
        """generate_package_report should use cached env data instead of live API."""
        from pkgdb import store_env_stats

        service = PackageStatsService(temp_db)
        service.add_package("test-pkg", verify=False)

        # Store download stats and env data
        recent = json.dumps({"data": {"last_day": 10, "last_week": 70, "last_month": 300}})
        overall = json.dumps({"data": [{"category": "without_mirrors", "downloads": 5000}]})
        py_response = json.dumps({"data": [{"category": "3.12", "downloads": 100}]})
        os_response = json.dumps({"data": [{"category": "Linux", "downloads": 200}]})

        with patch("pkgdb.api.pypistats.recent", return_value=recent):
            with patch("pkgdb.api.pypistats.overall", return_value=overall):
                with patch("pkgdb.api.pypistats.python_minor", return_value=py_response):
                    with patch("pkgdb.api.pypistats.system", return_value=os_response):
                        service.fetch_all_stats()

        # Generate report -- should NOT call python_minor or system APIs
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            output = f.name

        with patch("pkgdb.api.pypistats.python_minor") as mock_py, \
             patch("pkgdb.api.pypistats.system") as mock_os:
            service.generate_package_report("test-pkg", output)
            mock_py.assert_not_called()
            mock_os.assert_not_called()

        os.unlink(output)


# =============================================================================
# Service Path Validation Tests
# =============================================================================


class TestServicePathValidation:
    """Tests for path validation in service methods."""

    def test_generate_report_validates_path(self, temp_db):
        """generate_report should validate output path."""
        service = PackageStatsService(temp_db)

        # Add some data
        conn = get_db_connection(temp_db)
        init_db(conn)
        conn.execute("""
            INSERT INTO package_stats
            (package_name, fetch_date, last_day, last_week, last_month, total)
            VALUES ('test-pkg', '2024-01-01', 10, 70, 300, 1000)
        """)
        conn.commit()
        conn.close()

        # Invalid extension should fail
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_path = os.path.join(tmpdir, "report.txt")
            with pytest.raises(ValueError) as exc_info:
                service.generate_report(bad_path)
            assert "extension" in str(exc_info.value).lower()

    def test_generate_report_valid_path_works(self, temp_db):
        """generate_report should work with valid path."""
        service = PackageStatsService(temp_db)

        # Add some data
        conn = get_db_connection(temp_db)
        init_db(conn)
        conn.execute("""
            INSERT INTO package_stats
            (package_name, fetch_date, last_day, last_week, last_month, total)
            VALUES ('test-pkg', '2024-01-01', 10, 70, 300, 1000)
        """)
        conn.commit()
        conn.close()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
            output_path = f.name

        try:
            result = service.generate_report(output_path)
            assert result is True
            assert Path(output_path).exists()
        finally:
            Path(output_path).unlink(missing_ok=True)

    def test_generate_package_report_validates_path(self, temp_db):
        """generate_package_report should validate output path."""
        service = PackageStatsService(temp_db)

        python_response = json.dumps({"data": []})
        system_response = json.dumps({"data": []})
        recent_response = json.dumps({
            "data": {"last_day": 100, "last_week": 700, "last_month": 3000}
        })
        overall_response = json.dumps({
            "data": [{"category": "without_mirrors", "downloads": 50000}]
        })

        # Invalid extension should fail
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_path = os.path.join(tmpdir, "report.csv")
            with pytest.raises(ValueError) as exc_info:
                with patch("pkgdb.api.pypistats.python_minor", return_value=python_response):
                    with patch("pkgdb.api.pypistats.system", return_value=system_response):
                        with patch("pkgdb.api.pypistats.recent", return_value=recent_response):
                            with patch("pkgdb.api.pypistats.overall", return_value=overall_response):
                                service.generate_package_report("test-pkg", bad_path)
            assert "extension" in str(exc_info.value).lower()

    def test_export_validates_output_path(self, temp_db):
        """export should validate output path when specified."""
        service = PackageStatsService(temp_db)

        # Add some data
        conn = get_db_connection(temp_db)
        init_db(conn)
        conn.execute("""
            INSERT INTO package_stats
            (package_name, fetch_date, last_day, last_week, last_month, total)
            VALUES ('test-pkg', '2024-01-01', 10, 70, 300, 1000)
        """)
        conn.commit()
        conn.close()

        # Wrong extension for format
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_path = os.path.join(tmpdir, "output.html")
            with pytest.raises(ValueError) as exc_info:
                service.export("csv", output_file=bad_path)
            assert "extension" in str(exc_info.value).lower()


# =============================================================================
# Package Existence Check Tests
# =============================================================================


class TestCheckPackageExists:
    """Tests for check_package_exists function."""

    def test_existing_package_returns_true(self):
        """check_package_exists returns (True, None) for existing package."""
        from pkgdb import check_package_exists

        # Mock a successful HEAD request
        with patch("pkgdb.api.urlopen") as mock_urlopen:
            mock_response = type("MockResponse", (), {"status": 200, "__enter__": lambda s: s, "__exit__": lambda s, *a: None})()
            mock_urlopen.return_value = mock_response

            exists, error = check_package_exists("requests")
            assert exists is True
            assert error is None

    def test_nonexistent_package_returns_false(self):
        """check_package_exists returns (False, None) for 404."""
        from pkgdb import check_package_exists
        from urllib.error import HTTPError

        with patch("pkgdb.api.urlopen") as mock_urlopen:
            error = HTTPError("url", 404, "Not Found", {}, None)
            error.code = 404
            mock_urlopen.side_effect = error

            exists, err = check_package_exists("nonexistent-pkg-xyz123")
            assert exists is False
            assert err is None

    def test_network_error_returns_none_with_message(self):
        """check_package_exists returns (None, message) on network error."""
        from pkgdb import check_package_exists
        from urllib.error import URLError

        with patch("pkgdb.api.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = URLError("Connection refused")

            exists, error = check_package_exists("some-package")
            assert exists is None
            assert error is not None
            assert "Network error" in error

    def test_timeout_returns_none_with_message(self):
        """check_package_exists returns (None, message) on timeout."""
        from pkgdb import check_package_exists

        with patch("pkgdb.api.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = TimeoutError()

            exists, error = check_package_exists("some-package")
            assert exists is None
            assert error is not None
            assert "timed out" in error.lower()


# =============================================================================
# Relative Date Parsing Tests
# =============================================================================


class TestParseDateArg:
    """Tests for parse_date_arg function."""

    def test_standard_date_format(self):
        """parse_date_arg accepts YYYY-MM-DD format."""
        from pkgdb import parse_date_arg

        date, error = parse_date_arg("2024-01-15")
        assert date == "2024-01-15"
        assert error is None

    def test_invalid_standard_date(self):
        """parse_date_arg rejects invalid dates."""
        from pkgdb import parse_date_arg

        date, error = parse_date_arg("2024-13-45")
        assert date is None
        assert error is not None
        assert "Invalid date" in error

    def test_relative_days(self):
        """parse_date_arg parses Nd format."""
        from pkgdb import parse_date_arg
        from datetime import datetime, timedelta

        date, error = parse_date_arg("7d")
        assert error is None
        expected = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        assert date == expected

    def test_relative_weeks(self):
        """parse_date_arg parses Nw format."""
        from pkgdb import parse_date_arg
        from datetime import datetime, timedelta

        date, error = parse_date_arg("2w")
        assert error is None
        expected = (datetime.now() - timedelta(weeks=2)).strftime("%Y-%m-%d")
        assert date == expected

    def test_relative_months(self):
        """parse_date_arg parses Nm format (30 days per month)."""
        from pkgdb import parse_date_arg
        from datetime import datetime, timedelta

        date, error = parse_date_arg("1m")
        assert error is None
        expected = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        assert date == expected

    def test_case_insensitive(self):
        """parse_date_arg is case insensitive for units."""
        from pkgdb import parse_date_arg

        date_lower, _ = parse_date_arg("7d")
        date_upper, _ = parse_date_arg("7D")
        assert date_lower == date_upper

    def test_zero_offset_rejected(self):
        """parse_date_arg rejects zero offset."""
        from pkgdb import parse_date_arg

        date, error = parse_date_arg("0d")
        assert date is None
        assert error is not None
        assert "greater than 0" in error

    def test_invalid_format_rejected(self):
        """parse_date_arg rejects invalid formats."""
        from pkgdb import parse_date_arg

        date, error = parse_date_arg("invalid")
        assert date is None
        assert error is not None
        assert "Invalid date format" in error

    def test_empty_value_rejected(self):
        """parse_date_arg rejects empty values."""
        from pkgdb import parse_date_arg

        date, error = parse_date_arg("")
        assert date is None
        assert error is not None
        assert "empty" in error.lower()


# =============================================================================
# Package Verification in Service Tests
# =============================================================================


class TestServicePackageVerification:
    """Tests for package verification in service methods."""

    def test_add_package_with_verify_rejects_nonexistent(self, temp_db):
        """add_package with verify=True rejects packages not on PyPI."""
        service = PackageStatsService(temp_db)

        with patch("pkgdb.service.check_package_exists") as mock_check:
            mock_check.return_value = (False, None)

            with pytest.raises(ValueError) as exc_info:
                service.add_package("nonexistent-pkg-xyz123", verify=True)

            assert "not found on PyPI" in str(exc_info.value)

    def test_add_package_with_verify_accepts_existing(self, temp_db):
        """add_package with verify=True accepts existing packages."""
        service = PackageStatsService(temp_db)

        with patch("pkgdb.service.check_package_exists") as mock_check:
            mock_check.return_value = (True, None)

            result = service.add_package("requests", verify=True)
            assert result is True

    def test_add_package_without_verify_skips_check(self, temp_db):
        """add_package with verify=False skips PyPI check."""
        service = PackageStatsService(temp_db)

        with patch("pkgdb.service.check_package_exists") as mock_check:
            result = service.add_package("any-package", verify=False)
            assert result is True
            mock_check.assert_not_called()

    def test_add_package_network_error_warns_but_allows(self, temp_db, caplog):
        """add_package warns on network error but allows addition."""
        import logging
        service = PackageStatsService(temp_db)

        with patch("pkgdb.service.check_package_exists") as mock_check:
            mock_check.return_value = (None, "Connection refused")

            with caplog.at_level(logging.WARNING):
                result = service.add_package("some-package", verify=True)

            assert result is True
            assert "Could not verify" in caplog.text

    def test_import_packages_with_verify_skips_not_found(self, temp_db):
        """import_packages with verify=True skips packages not on PyPI."""
        service = PackageStatsService(temp_db)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("requests\nnonexistent-pkg\nflask\n")
            file_path = f.name

        try:
            def mock_check(name):
                if name == "nonexistent-pkg":
                    return (False, None)
                return (True, None)

            with patch("pkgdb.service.check_package_exists", side_effect=mock_check):
                added, skipped, invalid, not_found = service.import_packages(
                    file_path, verify=True
                )

            assert added == 2  # requests and flask
            assert "nonexistent-pkg" in not_found
        finally:
            Path(file_path).unlink(missing_ok=True)

    def test_import_packages_without_verify_adds_all(self, temp_db):
        """import_packages with verify=False adds all valid packages."""
        service = PackageStatsService(temp_db)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("pkg1\npkg2\npkg3\n")
            file_path = f.name

        try:
            with patch("pkgdb.service.check_package_exists") as mock_check:
                added, skipped, invalid, not_found = service.import_packages(
                    file_path, verify=False
                )

            assert added == 3
            assert not_found == []
            mock_check.assert_not_called()
        finally:
            Path(file_path).unlink(missing_ok=True)


# =============================================================================
# CLI --no-verify Flag Tests
# =============================================================================


class TestCLINoVerifyFlag:
    """Tests for --no-verify CLI flag."""

    def test_add_parser_has_no_verify_flag(self):
        """add command should have --no-verify flag."""
        from pkgdb.cli import create_parser

        parser = create_parser()
        args = parser.parse_args(["add", "test-pkg", "--no-verify"])
        assert args.no_verify is True

    def test_add_parser_no_verify_defaults_false(self):
        """add command --no-verify should default to False."""
        from pkgdb.cli import create_parser

        parser = create_parser()
        args = parser.parse_args(["add", "test-pkg"])
        assert getattr(args, "no_verify", False) is False

    def test_import_parser_has_no_verify_flag(self):
        """import command should have --no-verify flag."""
        from pkgdb.cli import create_parser

        parser = create_parser()
        args = parser.parse_args(["import", "packages.txt", "--no-verify"])
        assert args.no_verify is True

    def test_history_since_help_mentions_relative(self):
        """history --since help should mention relative formats."""
        from pkgdb.cli import create_parser
        import io
        import sys

        parser = create_parser()
        # Get help text for history command
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            parser.parse_args(["history", "--help"])
        except SystemExit:
            pass
        help_text = sys.stdout.getvalue()
        sys.stdout = old_stdout

        assert "7d" in help_text or "relative" in help_text.lower()


# =============================================================================
# Database Info Tests
# =============================================================================


class TestDatabaseInfo:
    """Tests for database info/stats functionality."""

    def test_get_database_stats_empty_db(self, db_conn):
        """get_database_stats should return zeros for empty database."""
        stats = get_database_stats(db_conn)

        assert stats["package_count"] == 0
        assert stats["record_count"] == 0
        assert stats["first_fetch"] is None
        assert stats["last_fetch"] is None

    def test_get_database_stats_with_data(self, db_conn):
        """get_database_stats should return correct counts."""
        # Add packages
        add_package(db_conn, "pkg-a")
        add_package(db_conn, "pkg-b")

        # Add stats records
        db_conn.execute("""
            INSERT INTO package_stats
            (package_name, fetch_date, last_day, last_week, last_month, total)
            VALUES ('pkg-a', '2024-01-01', 10, 70, 300, 1000)
        """)
        db_conn.execute("""
            INSERT INTO package_stats
            (package_name, fetch_date, last_day, last_week, last_month, total)
            VALUES ('pkg-a', '2024-01-02', 15, 75, 310, 1015)
        """)
        db_conn.execute("""
            INSERT INTO package_stats
            (package_name, fetch_date, last_day, last_week, last_month, total)
            VALUES ('pkg-b', '2024-01-02', 5, 35, 150, 500)
        """)
        db_conn.commit()

        stats = get_database_stats(db_conn)

        assert stats["package_count"] == 2
        assert stats["record_count"] == 3
        assert stats["first_fetch"] == "2024-01-01"
        assert stats["last_fetch"] == "2024-01-02"

    def test_service_get_database_info(self, temp_db):
        """Service.get_database_info should return DatabaseInfo."""
        service = PackageStatsService(temp_db)
        service.add_package("test-pkg", verify=False)

        # Add a stats record
        conn = get_db_connection(temp_db)
        init_db(conn)
        conn.execute("""
            INSERT INTO package_stats
            (package_name, fetch_date, last_day, last_week, last_month, total)
            VALUES ('test-pkg', '2024-01-15', 10, 70, 300, 1000)
        """)
        conn.commit()
        conn.close()

        info = service.get_database_info()

        assert info["package_count"] == 1
        assert info["record_count"] == 1
        assert info["first_fetch"] == "2024-01-15"
        assert info["last_fetch"] == "2024-01-15"
        assert info["db_size_bytes"] > 0

    def test_show_info_flag_exists(self):
        """show command should have --info flag."""
        from pkgdb.cli import create_parser

        parser = create_parser()
        args = parser.parse_args(["show", "--info"])
        assert args.info is True

    def test_show_info_flag_defaults_false(self):
        """show --info should default to False."""
        from pkgdb.cli import create_parser

        parser = create_parser()
        args = parser.parse_args(["show"])
        assert getattr(args, "info", False) is False

    def test_cmd_show_with_info_flag(self, temp_db, capsys):
        """cmd_show with --info should display database info."""
        service = PackageStatsService(temp_db)
        service.add_package("test-pkg", verify=False)

        # Add stats
        conn = get_db_connection(temp_db)
        init_db(conn)
        conn.execute("""
            INSERT INTO package_stats
            (package_name, fetch_date, last_day, last_week, last_month, total)
            VALUES ('test-pkg', '2024-01-15', 10, 70, 300, 1000)
        """)
        conn.commit()
        conn.close()

        with patch("sys.argv", ["pkgdb", "-d", temp_db, "show", "--info"]):
            main()

        captured = capsys.readouterr()
        assert "Database Info" in captured.out
        assert "Packages:" in captured.out
        assert "Records:" in captured.out
        assert "Date range:" in captured.out


# =============================================================================
# Badge Generation Tests
# =============================================================================


class TestBadgeGeneration:
    """Tests for SVG badge generation."""

    def test_generate_badge_svg_basic(self):
        """generate_badge_svg should return valid SVG."""
        svg = generate_badge_svg("downloads", "1.2M")

        assert svg.startswith("<svg")
        assert "</svg>" in svg
        assert "downloads" in svg
        assert "1.2M" in svg

    def test_generate_badge_svg_custom_colors(self):
        """generate_badge_svg should accept custom colors."""
        svg = generate_badge_svg("test", "value", color="#ff0000", label_color="#00ff00")

        assert "#ff0000" in svg
        assert "#00ff00" in svg

    def test_generate_downloads_badge_formats_count(self):
        """generate_downloads_badge should format large numbers."""
        # Test millions
        svg = generate_downloads_badge(1_500_000)
        assert "1.5M" in svg

        # Test thousands
        svg = generate_downloads_badge(45_000)
        assert "45.0K" in svg

        # Test small numbers
        svg = generate_downloads_badge(500)
        assert "500" in svg

    def test_generate_downloads_badge_periods(self):
        """generate_downloads_badge should use correct labels for periods."""
        svg_total = generate_downloads_badge(1000, period="total")
        assert "downloads" in svg_total

        svg_month = generate_downloads_badge(1000, period="month")
        assert "downloads/month" in svg_month

        svg_week = generate_downloads_badge(1000, period="week")
        assert "downloads/week" in svg_week

        svg_day = generate_downloads_badge(1000, period="day")
        assert "downloads/day" in svg_day

    def test_generate_downloads_badge_auto_color(self):
        """generate_downloads_badge should auto-select color based on count."""
        # High count should get bright green
        svg_high = generate_downloads_badge(2_000_000)
        assert BADGE_COLORS["brightgreen"] in svg_high

        # Low count should get gray
        svg_low = generate_downloads_badge(100)
        assert BADGE_COLORS["gray"] in svg_low

    def test_service_generate_badge(self, temp_db):
        """Service.generate_badge should return SVG for tracked package."""
        service = PackageStatsService(temp_db)

        # Add package and stats
        conn = get_db_connection(temp_db)
        init_db(conn)
        conn.execute(
            "INSERT INTO packages (package_name, added_date) VALUES ('test-pkg', '2024-01-01')"
        )
        conn.execute("""
            INSERT INTO package_stats
            (package_name, fetch_date, last_day, last_week, last_month, total)
            VALUES ('test-pkg', '2024-01-15', 100, 700, 3000, 50000)
        """)
        conn.commit()
        conn.close()

        svg = service.generate_badge("test-pkg")
        assert svg is not None
        assert "<svg" in svg
        assert "50.0K" in svg  # 50000 formatted

    def test_service_generate_badge_different_periods(self, temp_db):
        """Service.generate_badge should support different periods."""
        service = PackageStatsService(temp_db)

        # Add package and stats
        conn = get_db_connection(temp_db)
        init_db(conn)
        conn.execute(
            "INSERT INTO packages (package_name, added_date) VALUES ('test-pkg', '2024-01-01')"
        )
        conn.execute("""
            INSERT INTO package_stats
            (package_name, fetch_date, last_day, last_week, last_month, total)
            VALUES ('test-pkg', '2024-01-15', 100, 700, 3000, 50000)
        """)
        conn.commit()
        conn.close()

        svg_month = service.generate_badge("test-pkg", period="month")
        assert "3.0K" in svg_month  # 3000 formatted
        assert "downloads/month" in svg_month

    def test_service_generate_badge_nonexistent_package(self, temp_db):
        """Service.generate_badge should return None for unknown package."""
        service = PackageStatsService(temp_db)

        svg = service.generate_badge("nonexistent-pkg")
        assert svg is None

    def test_badge_cli_parser(self):
        """badge command should have correct arguments."""
        from pkgdb.cli import create_parser

        parser = create_parser()
        args = parser.parse_args(["badge", "test-pkg"])
        assert args.package == "test-pkg"
        assert args.period == "total"

        args = parser.parse_args(["badge", "test-pkg", "-p", "month", "-o", "badge.svg"])
        assert args.period == "month"
        assert args.output == "badge.svg"

    def test_cmd_badge_outputs_svg(self, temp_db, capsys):
        """cmd_badge should output SVG to stdout."""
        # Add package and stats
        conn = get_db_connection(temp_db)
        init_db(conn)
        conn.execute(
            "INSERT INTO packages (package_name, added_date) VALUES ('test-pkg', '2024-01-01')"
        )
        conn.execute("""
            INSERT INTO package_stats
            (package_name, fetch_date, last_day, last_week, last_month, total)
            VALUES ('test-pkg', '2024-01-15', 100, 700, 3000, 50000)
        """)
        conn.commit()
        conn.close()

        with patch("sys.argv", ["pkgdb", "-d", temp_db, "badge", "test-pkg"]):
            main()

        captured = capsys.readouterr()
        assert "<svg" in captured.out
        assert "</svg>" in captured.out


# ============================================================================
# GitHub Stats Tests
# ============================================================================


from datetime import datetime

from pkgdb import (
    RepoStats,
    RepoResult,
    parse_github_url,
    extract_github_url,
    get_github_token,
)
from pkgdb.github import (
    get_cached_repo_data,
    store_cached_repo_data,
    clear_github_cache,
    get_github_cache_stats,
    _parse_repo_data,
    _parse_datetime,
)


def _make_repo_stats(**overrides):
    """Helper to create a RepoStats with sensible defaults."""
    from datetime import timedelta  # noqa: F811

    defaults = dict(
        owner="test",
        name="repo",
        full_name="test/repo",
        description="Test repo",
        stars=100,
        forks=10,
        open_issues=5,
        watchers=50,
        language="Python",
        license="MIT",
        created_at=datetime.now() - timedelta(days=365),
        updated_at=datetime.now(),
        pushed_at=datetime.now() - timedelta(days=1),
        archived=False,
        fork=False,
        default_branch="main",
        topics=["test"],
    )
    defaults.update(overrides)
    return RepoStats(**defaults)


def _make_github_api_response(**overrides):
    """Helper to create a mock GitHub API response dict."""
    defaults = {
        "owner": {"login": "testowner"},
        "name": "testrepo",
        "full_name": "testowner/testrepo",
        "description": "A test repo",
        "stargazers_count": 42,
        "forks_count": 5,
        "open_issues_count": 3,
        "subscribers_count": 10,
        "language": "Python",
        "license": {"spdx_id": "MIT", "name": "MIT License"},
        "created_at": "2023-01-01T00:00:00Z",
        "updated_at": "2024-06-01T00:00:00Z",
        "pushed_at": "2024-06-01T00:00:00Z",
        "archived": False,
        "fork": False,
        "default_branch": "main",
        "topics": ["python", "testing"],
        "homepage": "https://example.com",
    }
    defaults.update(overrides)
    return defaults


class TestParseGithubUrl:
    """Tests for parse_github_url function."""

    def test_parse_https_url(self):
        result = parse_github_url("https://github.com/owner/repo")
        assert result == ("owner", "repo")

    def test_parse_url_with_www(self):
        result = parse_github_url("https://www.github.com/owner/repo")
        assert result == ("owner", "repo")

    def test_parse_http_url(self):
        result = parse_github_url("http://github.com/owner/repo")
        assert result == ("owner", "repo")

    def test_parse_url_with_trailing_slash(self):
        result = parse_github_url("https://github.com/owner/repo/")
        assert result == ("owner", "repo")

    def test_parse_url_with_subpath(self):
        result = parse_github_url("https://github.com/owner/repo/tree/main")
        assert result == ("owner", "repo")

    def test_parse_url_with_git_suffix(self):
        result = parse_github_url("https://github.com/owner/repo.git")
        assert result == ("owner", "repo")

    def test_parse_non_github_url(self):
        result = parse_github_url("https://gitlab.com/owner/repo")
        assert result is None

    def test_parse_empty_url(self):
        result = parse_github_url("")
        assert result is None


class TestRepoStats:
    """Tests for RepoStats dataclass."""

    def test_days_since_push(self):
        from datetime import timedelta

        yesterday = datetime.now() - timedelta(days=1)
        stats = _make_repo_stats(pushed_at=yesterday)
        assert stats.days_since_push == 1

    def test_days_since_push_none(self):
        stats = _make_repo_stats(pushed_at=None)
        assert stats.days_since_push is None

    def test_is_active_recent_push(self):
        from datetime import timedelta

        stats = _make_repo_stats(pushed_at=datetime.now() - timedelta(days=10))
        assert stats.is_active is True

    def test_is_active_old_push(self):
        from datetime import timedelta

        stats = _make_repo_stats(pushed_at=datetime.now() - timedelta(days=400))
        assert stats.is_active is False

    def test_activity_status_very_active(self):
        from datetime import timedelta

        stats = _make_repo_stats(pushed_at=datetime.now() - timedelta(days=5))
        assert stats.activity_status == "very active"

    def test_activity_status_active(self):
        from datetime import timedelta

        stats = _make_repo_stats(pushed_at=datetime.now() - timedelta(days=60))
        assert stats.activity_status == "active"

    def test_activity_status_maintained(self):
        from datetime import timedelta

        stats = _make_repo_stats(pushed_at=datetime.now() - timedelta(days=200))
        assert stats.activity_status == "maintained"

    def test_activity_status_stale(self):
        from datetime import timedelta

        stats = _make_repo_stats(pushed_at=datetime.now() - timedelta(days=400))
        assert stats.activity_status == "stale"

    def test_activity_status_archived(self):
        stats = _make_repo_stats(archived=True)
        assert stats.activity_status == "archived"

    def test_activity_status_no_push_date(self):
        stats = _make_repo_stats(pushed_at=None)
        assert stats.activity_status == "unknown"


class TestRepoResult:
    """Tests for RepoResult dataclass."""

    def test_success_with_stats(self):
        stats = _make_repo_stats()
        result = RepoResult(package_name="test-pkg", repo_url="https://github.com/test/repo", stats=stats)
        assert result.success is True

    def test_failure_with_error(self):
        result = RepoResult(package_name="test-pkg", repo_url=None, error="Not found")
        assert result.success is False

    def test_no_github_repo(self):
        result = RepoResult(package_name="test-pkg", repo_url=None, error="No GitHub repository found")
        assert result.success is False
        assert result.repo_url is None


class TestParseRepoData:
    """Tests for _parse_repo_data function."""

    def test_parse_full_response(self):
        data = _make_github_api_response()
        stats = _parse_repo_data(data)
        assert stats.owner == "testowner"
        assert stats.name == "testrepo"
        assert stats.full_name == "testowner/testrepo"
        assert stats.stars == 42
        assert stats.forks == 5
        assert stats.open_issues == 3
        assert stats.watchers == 10
        assert stats.language == "Python"
        assert stats.license == "MIT"
        assert stats.archived is False
        assert stats.fork is False
        assert stats.default_branch == "main"
        assert "python" in stats.topics

    def test_parse_response_no_license(self):
        data = _make_github_api_response(license=None)
        stats = _parse_repo_data(data)
        assert stats.license is None

    def test_parse_response_no_homepage(self):
        data = _make_github_api_response(homepage="")
        stats = _parse_repo_data(data)
        assert stats.homepage is None

    def test_parse_response_missing_optional_fields(self):
        data = _make_github_api_response()
        del data["language"]
        del data["topics"]
        stats = _parse_repo_data(data)
        assert stats.language is None
        assert stats.topics == []


class TestParseDatetime:
    """Tests for _parse_datetime helper."""

    def test_parse_iso_with_z(self):
        result = _parse_datetime("2024-01-15T10:30:00Z")
        assert result is not None
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15
        assert result.tzinfo is None

    def test_parse_none(self):
        result = _parse_datetime(None)
        assert result is None


class TestGitHubCache:
    """Tests for GitHub API cache functions."""

    def test_store_and_retrieve_cached_data(self, temp_db):
        conn = get_db_connection(temp_db)
        init_db(conn)

        data = _make_github_api_response()
        store_cached_repo_data(conn, "owner", "repo", data)

        cached = get_cached_repo_data(conn, "owner", "repo")
        assert cached is not None
        assert cached["stargazers_count"] == 42
        conn.close()

    def test_cache_miss(self, temp_db):
        conn = get_db_connection(temp_db)
        init_db(conn)

        cached = get_cached_repo_data(conn, "nonexistent", "repo")
        assert cached is None
        conn.close()

    def test_cache_case_insensitive(self, temp_db):
        conn = get_db_connection(temp_db)
        init_db(conn)

        data = _make_github_api_response()
        store_cached_repo_data(conn, "Owner", "Repo", data)

        cached = get_cached_repo_data(conn, "owner", "repo")
        assert cached is not None
        conn.close()

    def test_clear_expired_cache(self, temp_db):
        conn = get_db_connection(temp_db)
        init_db(conn)

        # Insert an already-expired entry
        from pkgdb.github import _ensure_cache_table
        _ensure_cache_table(conn)
        conn.execute(
            """INSERT INTO github_cache (repo_key, data, fetched_at, expires_at)
               VALUES (?, ?, datetime('now'), datetime('now', '-1 hour'))""",
            ("expired/repo", json.dumps({"test": True})),
        )
        conn.commit()

        cleared = clear_github_cache(conn, expired_only=True)
        assert cleared == 1
        conn.close()

    def test_clear_all_cache(self, temp_db):
        conn = get_db_connection(temp_db)
        init_db(conn)

        data = _make_github_api_response()
        store_cached_repo_data(conn, "owner1", "repo1", data)
        store_cached_repo_data(conn, "owner2", "repo2", data)

        cleared = clear_github_cache(conn, expired_only=False)
        assert cleared == 2
        conn.close()

    def test_cache_stats(self, temp_db):
        conn = get_db_connection(temp_db)
        init_db(conn)

        data = _make_github_api_response()
        store_cached_repo_data(conn, "owner", "repo", data)

        stats = get_github_cache_stats(conn)
        assert stats["total"] == 1
        assert stats["valid"] == 1
        assert stats["expired"] == 0
        conn.close()

    def test_cache_stats_empty(self, temp_db):
        conn = get_db_connection(temp_db)
        init_db(conn)

        stats = get_github_cache_stats(conn)
        assert stats["total"] == 0
        assert stats["valid"] == 0
        assert stats["expired"] == 0
        conn.close()


class TestExtractGithubUrl:
    """Tests for extract_github_url function."""

    def test_extract_from_project_urls_repository(self):
        mock_response = json.dumps({
            "info": {
                "project_urls": {
                    "Repository": "https://github.com/owner/repo",
                    "Homepage": "https://example.com",
                }
            }
        }).encode()

        from unittest.mock import MagicMock
        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_response
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("pkgdb.github.urlopen", return_value=mock_resp):
            url = extract_github_url("test-pkg")
        assert url == "https://github.com/owner/repo"

    def test_extract_from_project_urls_source(self):
        mock_response = json.dumps({
            "info": {
                "project_urls": {
                    "Source": "https://github.com/owner/repo",
                }
            }
        }).encode()

        from unittest.mock import MagicMock
        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_response
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("pkgdb.github.urlopen", return_value=mock_resp):
            url = extract_github_url("test-pkg")
        assert url == "https://github.com/owner/repo"

    def test_extract_from_home_page_fallback(self):
        mock_response = json.dumps({
            "info": {
                "home_page": "https://github.com/owner/repo",
                "project_urls": {
                    "Documentation": "https://docs.example.com",
                },
            }
        }).encode()

        from unittest.mock import MagicMock
        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_response
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("pkgdb.github.urlopen", return_value=mock_resp):
            url = extract_github_url("test-pkg")
        assert url == "https://github.com/owner/repo"

    def test_extract_no_github_url(self):
        mock_response = json.dumps({
            "info": {
                "home_page": "https://example.com",
                "project_urls": {
                    "Homepage": "https://example.com",
                },
            }
        }).encode()

        from unittest.mock import MagicMock
        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_response
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("pkgdb.github.urlopen", return_value=mock_resp):
            url = extract_github_url("test-pkg")
        assert url is None

    def test_extract_network_error(self):
        from urllib.error import URLError

        with patch("pkgdb.github.urlopen", side_effect=URLError("fail")):
            url = extract_github_url("test-pkg")
        assert url is None


class TestGetGithubToken:
    """Tests for get_github_token function."""

    def test_github_token_env(self):
        with patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"}, clear=False):
            # Remove GH_TOKEN if present to avoid interference
            os.environ.pop("GH_TOKEN", None)
            assert get_github_token() == "test-token"

    def test_gh_token_env(self):
        with patch.dict(os.environ, {"GH_TOKEN": "gh-token"}, clear=False):
            os.environ.pop("GITHUB_TOKEN", None)
            assert get_github_token() == "gh-token"

    def test_no_token(self):
        with patch.dict(os.environ, {}, clear=True):
            assert get_github_token() is None


class TestFetchPackageGithubStats:
    """Tests for fetch_package_github_stats function."""

    def test_fetch_success(self, temp_db):
        from pkgdb.github import fetch_package_github_stats

        conn = get_db_connection(temp_db)
        init_db(conn)

        api_data = _make_github_api_response()
        mock_api_resp = json.dumps(api_data).encode()
        pypi_data = json.dumps({
            "info": {
                "project_urls": {"Repository": "https://github.com/testowner/testrepo"},
            }
        }).encode()

        from unittest.mock import MagicMock

        def mock_urlopen(req, **kwargs):
            mock_resp = MagicMock()
            url = req.full_url if hasattr(req, 'full_url') else str(req)
            if "pypi.org" in url:
                mock_resp.read.return_value = pypi_data
            else:
                mock_resp.read.return_value = mock_api_resp
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        with patch("pkgdb.github.urlopen", side_effect=mock_urlopen):
            result = fetch_package_github_stats("test-pkg", conn=conn)

        assert result.success is True
        assert result.stats is not None
        assert result.stats.stars == 42
        assert result.stats.forks == 5
        conn.close()

    def test_fetch_no_github_repo(self, temp_db):
        from pkgdb.github import fetch_package_github_stats

        conn = get_db_connection(temp_db)
        init_db(conn)

        pypi_data = json.dumps({
            "info": {"project_urls": {"Homepage": "https://example.com"}}
        }).encode()

        from unittest.mock import MagicMock
        mock_resp = MagicMock()
        mock_resp.read.return_value = pypi_data
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("pkgdb.github.urlopen", return_value=mock_resp):
            result = fetch_package_github_stats("test-pkg", conn=conn)

        assert result.success is False
        assert "No GitHub repository" in result.error
        conn.close()


class TestGithubDatabaseInit:
    """Tests for GitHub cache table creation in init_db."""

    def test_init_db_creates_github_cache_table(self, temp_db):
        conn = get_db_connection(temp_db)
        init_db(conn)

        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='github_cache'"
        )
        result = cursor.fetchone()
        assert result is not None
        assert result["name"] == "github_cache"
        conn.close()


class TestServiceGithubStats:
    """Tests for PackageStatsService GitHub methods."""

    def test_fetch_github_stats_with_mock(self, temp_db):
        service = PackageStatsService(temp_db)
        with get_db(temp_db) as conn:
            add_package(conn, "test-pkg")

        stats = _make_repo_stats(stars=200, forks=20)
        result = RepoResult(
            package_name="test-pkg",
            repo_url="https://github.com/test/repo",
            stats=stats,
        )

        with patch("pkgdb.service.fetch_package_github_stats", return_value=result):
            results = service.fetch_github_stats(packages=["test-pkg"])

        assert len(results) == 1
        assert results[0].success is True
        assert results[0].stats.stars == 200

    def test_clear_github_cache(self, temp_db):
        service = PackageStatsService(temp_db)
        # Populate cache
        with get_db(temp_db) as conn:
            data = _make_github_api_response()
            store_cached_repo_data(conn, "owner", "repo", data)

        cleared = service.clear_github_cache(expired_only=False)
        assert cleared == 1

    def test_github_cache_stats(self, temp_db):
        service = PackageStatsService(temp_db)
        stats = service.get_github_cache_stats()
        assert stats["total"] == 0
        assert stats["valid"] == 0
        assert stats["expired"] == 0


class TestGithubCLI:
    """Tests for GitHub CLI commands."""

    def test_github_command_no_packages(self, temp_db, capsys):
        with patch("sys.argv", ["pkgdb", "-d", temp_db, "github"]):
            main()
        # Should warn about no packages

    def test_github_cache_command(self, temp_db, capsys):
        # Add a package so it doesn't exit early
        with get_db(temp_db) as conn:
            add_package(conn, "test-pkg")

        with patch("sys.argv", ["pkgdb", "-d", temp_db, "github", "cache"]):
            main()

        captured = capsys.readouterr()
        assert "GitHub Cache Statistics:" in captured.out
        assert "Total entries:" in captured.out

    def test_github_clear_command(self, temp_db):
        with get_db(temp_db) as conn:
            add_package(conn, "test-pkg")

        with patch("sys.argv", ["pkgdb", "-d", temp_db, "github", "clear", "--all"]):
            main()

    def test_github_fetch_command_with_results(self, temp_db, capsys):
        with get_db(temp_db) as conn:
            add_package(conn, "test-pkg")

        stats = _make_repo_stats(stars=100, forks=10, language="Python")
        result = RepoResult(
            package_name="test-pkg",
            repo_url="https://github.com/test/repo",
            stats=stats,
        )

        with patch("pkgdb.service.fetch_package_github_stats", return_value=result):
            with patch("sys.argv", ["pkgdb", "-d", temp_db, "github", "fetch"]):
                main()

        captured = capsys.readouterr()
        assert "test-pkg" in captured.out
        assert "100" in captured.out


class TestGithubInReport:
    """Tests for GitHub stats in HTML reports."""

    def test_report_includes_github_columns(self, temp_db):
        from pkgdb.reports import generate_html_report
        from pkgdb.github import RepoStats

        stats = [{
            "package_name": "test-pkg",
            "total": 50000,
            "last_month": 3000,
            "last_week": 700,
            "last_day": 100,
        }]
        gh_stats = {
            "test-pkg": _make_repo_stats(
                stars=42, forks=5, language="Python",
                full_name="owner/test-pkg",
            ),
        }
        output = os.path.join(os.path.dirname(temp_db), "test_report.html")
        generate_html_report(stats, output, github_stats=gh_stats)

        with open(output) as f:
            html = f.read()

        assert "Stars" in html
        assert "Forks" in html
        assert "Language" in html
        assert "Activity" in html
        assert "Repository" in html
        assert "owner/test-pkg" in html
        assert "42" in html
        Path(output).unlink(missing_ok=True)

    def test_report_without_github_has_no_github_columns(self, temp_db):
        from pkgdb.reports import generate_html_report

        stats = [{
            "package_name": "test-pkg",
            "total": 50000,
            "last_month": 3000,
            "last_week": 700,
            "last_day": 100,
        }]
        output = os.path.join(os.path.dirname(temp_db), "test_report.html")
        generate_html_report(stats, output)

        with open(output) as f:
            html = f.read()

        assert "Stars" not in html
        assert "Forks" not in html
        Path(output).unlink(missing_ok=True)

    def test_report_github_missing_package_shows_dash(self, temp_db):
        from pkgdb.reports import generate_html_report

        stats = [
            {
                "package_name": "has-gh",
                "total": 50000,
                "last_month": 3000,
                "last_week": 700,
                "last_day": 100,
            },
            {
                "package_name": "no-gh",
                "total": 1000,
                "last_month": 100,
                "last_week": 20,
                "last_day": 5,
            },
        ]
        gh_stats = {
            "has-gh": _make_repo_stats(stars=99, forks=7, full_name="owner/has-gh"),
        }
        output = os.path.join(os.path.dirname(temp_db), "test_report.html")
        generate_html_report(stats, output, github_stats=gh_stats)

        with open(output) as f:
            html = f.read()

        assert "owner/has-gh" in html
        # The no-gh row should have dash placeholders
        assert html.count("Stars") == 1  # only in header
        Path(output).unlink(missing_ok=True)
