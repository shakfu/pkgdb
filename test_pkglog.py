"""Tests for pkglog - PyPI package download statistics tracker."""

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from pkglog import (
    get_db_connection,
    init_db,
    load_packages,
    store_stats,
    get_latest_stats,
    fetch_package_stats,
    generate_html_report,
    main,
    DEFAULT_DB_FILE,
    DEFAULT_PACKAGES_FILE,
    DEFAULT_REPORT_FILE,
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
    """Create a temporary packages.yml file."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yml", delete=False
    ) as f:
        yaml.dump({"published": ["package-a", "package-b"]}, f)
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


class TestLoadPackages:
    """Tests for loading packages from YAML."""

    def test_load_packages_returns_list(self, temp_packages_file):
        """load_packages should return a list of package names."""
        packages = load_packages(temp_packages_file)
        assert isinstance(packages, list)
        assert packages == ["package-a", "package-b"]

    def test_load_packages_empty_published(self):
        """load_packages should return empty list if published key is missing."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yml", delete=False
        ) as f:
            yaml.dump({"other_key": ["something"]}, f)
            path = f.name

        try:
            packages = load_packages(path)
            assert packages == [] or packages is None
        finally:
            Path(path).unlink(missing_ok=True)

    def test_load_packages_file_not_found(self):
        """load_packages should raise FileNotFoundError for missing files."""
        with pytest.raises(FileNotFoundError):
            load_packages("/nonexistent/packages.yml")


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

        with patch("pkglog.pypistats.recent", return_value=recent_response):
            with patch("pkglog.pypistats.overall", return_value=overall_response):
                stats = fetch_package_stats("test-package")

        assert stats["last_day"] == 100
        assert stats["last_week"] == 700
        assert stats["last_month"] == 3000
        assert stats["total"] == 50000

    def test_fetch_package_stats_handles_error(self, capsys):
        """fetch_package_stats should return None and print error on failure."""
        with patch("pkglog.pypistats.recent", side_effect=Exception("API error")):
            stats = fetch_package_stats("nonexistent-package")

        assert stats is None
        captured = capsys.readouterr()
        assert "Error fetching stats" in captured.out


class TestHTMLReportGeneration:
    """Tests for HTML report generation."""

    def test_generate_html_report_creates_file(self):
        """generate_html_report should create an HTML file."""
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
            assert "chart.js" in content
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

    def test_generate_html_report_empty_stats(self, capsys):
        """generate_html_report should handle empty stats gracefully."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", delete=False
        ) as f:
            output_path = f.name

        try:
            generate_html_report([], output_path)
            captured = capsys.readouterr()
            assert "No statistics available" in captured.out
        finally:
            Path(output_path).unlink(missing_ok=True)


class TestCLI:
    """Tests for CLI argument parsing and commands."""

    def test_default_values(self):
        """Default values should be set correctly."""
        assert DEFAULT_DB_FILE == "pkg.db"
        assert DEFAULT_PACKAGES_FILE == "packages.yml"
        assert DEFAULT_REPORT_FILE == "report.html"

    def test_main_no_command_shows_help(self, capsys):
        """main() with no command should print help."""
        with patch("sys.argv", ["pkglog"]):
            main()
        captured = capsys.readouterr()
        assert "usage:" in captured.out.lower() or "Available commands" in captured.out

    def test_main_fetch_command(self, temp_db, temp_packages_file):
        """fetch command should fetch and store stats."""
        recent_response = json.dumps({
            "data": {"last_day": 100, "last_week": 700, "last_month": 3000}
        })
        overall_response = json.dumps({
            "data": [{"category": "without_mirrors", "downloads": 50000}]
        })

        with patch("sys.argv", ["pkglog", "-d", temp_db, "-p", temp_packages_file, "fetch"]):
            with patch("pkglog.pypistats.recent", return_value=recent_response):
                with patch("pkglog.pypistats.overall", return_value=overall_response):
                    main()

        conn = get_db_connection(temp_db)
        cursor = conn.execute("SELECT COUNT(*) as count FROM package_stats")
        assert cursor.fetchone()["count"] == 2
        conn.close()

    def test_main_list_command_empty_db(self, temp_db, capsys):
        """list command should indicate when database is empty."""
        conn = get_db_connection(temp_db)
        init_db(conn)
        conn.close()

        with patch("sys.argv", ["pkglog", "-d", temp_db, "list"]):
            main()

        captured = capsys.readouterr()
        assert "No data" in captured.out or "fetch" in captured.out.lower()

    def test_main_list_command_with_data(self, temp_db, capsys):
        """list command should display stats from database."""
        conn = get_db_connection(temp_db)
        init_db(conn)
        conn.execute("""
            INSERT INTO package_stats
            (package_name, fetch_date, last_day, last_week, last_month, total)
            VALUES ('test-pkg', '2024-01-01', 10, 70, 300, 1000)
        """)
        conn.commit()
        conn.close()

        with patch("sys.argv", ["pkglog", "-d", temp_db, "list"]):
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
            with patch("sys.argv", ["pkglog", "-d", temp_db, "report", "-o", output_path]):
                with patch("webbrowser.open_new_tab"):
                    main()

            assert Path(output_path).exists()
            content = Path(output_path).read_text()
            assert "test-pkg" in content
        finally:
            Path(output_path).unlink(missing_ok=True)
