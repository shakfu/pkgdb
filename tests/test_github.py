"""Tests for GitHub integration: URL parsing, repo stats, API interactions."""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from pkgdb import (
    get_db_connection,
    init_db,
    RepoStats,
    RepoResult,
    parse_github_url,
    extract_github_url,
    get_github_token,
)
from pkgdb.github import (
    _parse_repo_data,
    _parse_datetime,
    fetch_package_github_stats,
)


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
        yesterday = datetime.now() - timedelta(days=1)
        stats = _make_repo_stats(pushed_at=yesterday)
        assert stats.days_since_push == 1

    def test_days_since_push_none(self):
        stats = _make_repo_stats(pushed_at=None)
        assert stats.days_since_push is None

    def test_is_active_recent_push(self):
        stats = _make_repo_stats(pushed_at=datetime.now() - timedelta(days=10))
        assert stats.is_active is True

    def test_is_active_old_push(self):
        stats = _make_repo_stats(pushed_at=datetime.now() - timedelta(days=400))
        assert stats.is_active is False

    def test_activity_status_very_active(self):
        stats = _make_repo_stats(pushed_at=datetime.now() - timedelta(days=5))
        assert stats.activity_status == "very active"

    def test_activity_status_active(self):
        stats = _make_repo_stats(pushed_at=datetime.now() - timedelta(days=60))
        assert stats.activity_status == "active"

    def test_activity_status_maintained(self):
        stats = _make_repo_stats(pushed_at=datetime.now() - timedelta(days=200))
        assert stats.activity_status == "maintained"

    def test_activity_status_stale(self):
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
        conn = get_db_connection(temp_db)
        init_db(conn)

        api_data = _make_github_api_response()
        mock_api_resp = json.dumps(api_data).encode()
        pypi_data = json.dumps({
            "info": {
                "project_urls": {"Repository": "https://github.com/testowner/testrepo"},
            }
        }).encode()

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
        conn = get_db_connection(temp_db)
        init_db(conn)

        pypi_data = json.dumps({
            "info": {"project_urls": {"Homepage": "https://example.com"}}
        }).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = pypi_data
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("pkgdb.github.urlopen", return_value=mock_resp):
            result = fetch_package_github_stats("test-pkg", conn=conn)

        assert result.success is False
        assert "No GitHub repository" in result.error
        conn.close()
