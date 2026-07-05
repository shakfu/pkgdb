"""Tests for PackageStatsService abstraction layer."""

import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from pkgdb import (
    get_db_connection,
    get_db,
    init_db,
    add_package,
    store_stats,
    PackageStatsService,
    PackageInfo,
    FetchResult,
    PackageDetails,
    SyncResult,
    RepoStats,
    RepoResult,
)
from pkgdb.github import store_cached_repo_data


def _make_repo_stats(**overrides):
    """Helper to create a RepoStats with sensible defaults."""
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

    def test_fetch_captures_daily_series(self, temp_db):
        """fetch_all_stats should persist the daily time series when available."""
        service = PackageStatsService(temp_db)
        service.add_package("test-pkg", verify=False)

        recent = json.dumps(
            {"data": {"last_day": 10, "last_week": 70, "last_month": 300}}
        )
        # overall is called twice: aggregate (no total) and daily (total='daily').
        overall_daily = json.dumps(
            {
                "data": [
                    {"category": "without_mirrors", "date": "2026-01-01", "downloads": 100},
                    {"category": "without_mirrors", "date": "2026-01-02", "downloads": 150},
                ]
            }
        )
        overall_agg = json.dumps(
            {"data": [{"category": "without_mirrors", "downloads": 250}]}
        )

        def overall_side_effect(pkg, *args, **kwargs):
            return overall_daily if kwargs.get("total") == "daily" else overall_agg

        py_daily = json.dumps(
            {"data": [{"category": "3.12", "date": "2026-01-01", "downloads": 40}]}
        )
        os_daily = json.dumps(
            {"data": [{"category": "Linux", "date": "2026-01-01", "downloads": 80}]}
        )

        def py_side_effect(pkg, *args, **kwargs):
            return py_daily

        def os_side_effect(pkg, *args, **kwargs):
            return os_daily

        with (
            patch("pkgdb.api.pypistats.recent", return_value=recent),
            patch("pkgdb.api.pypistats.overall", side_effect=overall_side_effect),
            patch("pkgdb.api.pypistats.python_minor", side_effect=py_side_effect),
            patch("pkgdb.api.pypistats.system", side_effect=os_side_effect),
        ):
            result = service.fetch_all_stats()

        assert result.success == 1

        overall = service.get_daily_downloads("test-pkg", dimension="overall")
        assert [r["date"] for r in overall] == ["2026-01-01", "2026-01-02"]
        assert [r["downloads"] for r in overall] == [100, 150]

        python = service.get_daily_downloads("test-pkg", dimension="python")
        assert len(python) == 1 and python[0]["category"] == "3.12"

    def test_get_period_comparison_from_daily(self, temp_db):
        """get_period_comparison returns exact adjacent-window sums."""
        from pkgdb import store_daily_downloads

        service = PackageStatsService(temp_db)
        service.add_package("my-pkg", verify=False)
        rows = [{"date": f"2026-06-{i:02d}", "dimension": "overall",
                 "category": "without_mirrors", "downloads": 10}
                for i in range(1, 8)]
        rows += [{"date": f"2026-06-{i:02d}", "dimension": "overall",
                  "category": "without_mirrors", "downloads": 25}
                 for i in range(8, 15)]
        with get_db(temp_db) as conn:
            store_daily_downloads(conn, "my-pkg", rows)

        # current week (08-14) = 7*25 = 175, previous (01-07) = 7*10 = 70
        assert service.get_period_comparison("my-pkg", 7) == (175, 70)

    def test_get_period_comparison_no_daily_returns_none(self, temp_db):
        service = PackageStatsService(temp_db)
        service.add_package("my-pkg", verify=False)
        assert service.get_period_comparison("my-pkg", 7) is None

    def test_run_checks_detects_spike(self, temp_db):
        from datetime import datetime, timedelta
        from pkgdb import store_daily_downloads

        service = PackageStatsService(temp_db)
        service.add_package("spiky", verify=False)
        d0 = datetime.strptime("2026-01-05", "%Y-%m-%d").date()
        values = [100] * 56 + [220] * 7
        rows = [
            {"date": (d0 + timedelta(days=i)).isoformat(), "dimension": "overall",
             "category": "without_mirrors", "downloads": v}
            for i, v in enumerate(values)
        ]
        with get_db(temp_db) as conn:
            store_daily_downloads(conn, "spiky", rows)

        events = service.run_checks()
        assert len(events) == 1
        assert events[0]["package"] == "spiky"
        assert events[0]["kind"] == "spike"

    def test_run_checks_empty_without_data(self, temp_db):
        service = PackageStatsService(temp_db)
        service.add_package("quiet", verify=False)
        assert service.run_checks(milestones=[1000]) == []

    def test_tag_add_remove_and_list(self, temp_db):
        service = PackageStatsService(temp_db)
        service.add_package("a", verify=False)
        assert service.add_tag("a", "Web") is True
        assert service.get_package_tags("a") == ["web"]
        assert service.remove_tag("a", "web") is True
        assert service.get_package_tags("a") == []

    def test_get_stats_filtered_by_tag(self, temp_db):
        service = PackageStatsService(temp_db)
        for p in ("a", "b", "c"):
            service.add_package(p, verify=False)
            store_stats(
                self._conn(temp_db), p,
                {"last_day": 1, "last_week": 7, "last_month": 30, "total": 100},
            )
        service.add_tag("a", "web")
        service.add_tag("b", "web")
        names = {s["package_name"] for s in service.get_stats(tag="web")}
        assert names == {"a", "b"}

    def test_get_tag_summary_aggregates(self, temp_db):
        service = PackageStatsService(temp_db)
        conn = self._conn(temp_db)
        for p, total in (("a", 100), ("b", 250), ("c", 40)):
            service.add_package(p, verify=False)
            store_stats(
                conn, p,
                {"last_day": 1, "last_week": 7, "last_month": 10, "total": total},
            )
        service.add_tag("a", "web")
        service.add_tag("b", "web")
        service.add_tag("c", "cli")

        summary = {e["tag"]: e for e in service.get_tag_summary()}
        assert summary["web"]["package_count"] == 2
        assert summary["web"]["total"] == 350
        assert summary["cli"]["total"] == 40
        # Ordered by total desc -> web first
        assert service.get_tag_summary()[0]["tag"] == "web"

    @staticmethod
    def _conn(temp_db):
        from pkgdb import get_db_connection, init_db
        conn = get_db_connection(temp_db)
        init_db(conn)
        return conn

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

    def test_fetch_github_stats_records_history(self, temp_db):
        service = PackageStatsService(temp_db)
        with get_db(temp_db) as conn:
            add_package(conn, "test-pkg")

        stats = _make_repo_stats(stars=200, forks=20, open_issues=7, watchers=15)
        result = RepoResult(
            package_name="test-pkg",
            repo_url="https://github.com/test/repo",
            stats=stats,
        )
        with patch("pkgdb.service.fetch_package_github_stats", return_value=result):
            service.fetch_github_stats(packages=["test-pkg"])

        history = service.get_github_history("test-pkg")
        assert len(history) == 1
        assert history[0]["stars"] == 200
        assert history[0]["forks"] == 20

    def test_get_star_growth(self, temp_db):
        from pkgdb import store_github_stats_snapshot

        service = PackageStatsService(temp_db)
        service.add_package("gh-pkg", verify=False)
        with get_db(temp_db) as conn:
            conn.executemany(
                "INSERT INTO github_stats_history (package_name, repo_key, date, "
                "stars, forks, open_issues, watchers) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    ("gh-pkg", "o/r", "2026-05-01", 100, 1, 1, 1),
                    ("gh-pkg", "o/r", "2026-06-10", 130, 1, 1, 1),
                ],
            )
            conn.commit()
        # latest 130 vs baseline >=30 days old (2026-05-01 = 100) -> +30
        assert service.get_star_growth("gh-pkg", days=30) == 30

    def test_get_star_growth_needs_two_points(self, temp_db):
        from pkgdb import store_github_stats_snapshot

        service = PackageStatsService(temp_db)
        service.add_package("gh-pkg", verify=False)
        with get_db(temp_db) as conn:
            store_github_stats_snapshot(conn, "gh-pkg", "o/r", 100, 1, 1, 1)
        assert service.get_star_growth("gh-pkg") is None

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
