"""Tests for PyPI and GitHub release storage and retrieval."""

import pytest

from pkgdb import (
    get_db,
    store_pypi_releases,
    get_pypi_releases,
    get_all_pypi_releases,
    store_github_releases,
    get_github_releases,
    get_all_github_releases,
    PyPIRelease,
    GitHubRelease,
)


class TestPyPIReleases:
    """Tests for PyPI release storage and retrieval."""

    def test_store_and_get_pypi_releases(self, temp_db):
        """Round-trip: store then retrieve PyPI releases."""
        releases = [
            PyPIRelease(version="0.1.0", upload_date="2025-01-15"),
            PyPIRelease(version="0.2.0", upload_date="2025-06-01"),
        ]
        with get_db(temp_db) as conn:
            store_pypi_releases(conn, "my-pkg", releases)
            result = get_pypi_releases(conn, "my-pkg")

        assert result is not None
        assert len(result) == 2
        assert result[0]["version"] == "0.1.0"
        assert result[1]["version"] == "0.2.0"

    def test_get_pypi_releases_cache_miss(self, temp_db):
        """get_pypi_releases returns None when no data cached."""
        with get_db(temp_db) as conn:
            result = get_pypi_releases(conn, "nonexistent-pkg")
        assert result is None

    def test_get_all_pypi_releases_ignores_cache(self, temp_db):
        """get_all_pypi_releases returns data regardless of cache state."""
        releases = [PyPIRelease(version="1.0", upload_date="2025-01-01")]
        with get_db(temp_db) as conn:
            store_pypi_releases(conn, "my-pkg", releases)
            # Expire the cache
            conn.execute(
                "UPDATE release_cache SET expires_at = datetime('now', '-1 hour') "
                "WHERE cache_key = 'pypi:my-pkg'"
            )
            conn.commit()
            # Cache is expired, but get_all should still return data
            assert get_pypi_releases(conn, "my-pkg") is None
            result = get_all_pypi_releases(conn, "my-pkg")
        assert len(result) == 1

    def test_store_pypi_releases_upsert(self, temp_db):
        """Storing releases with same version should update, not duplicate."""
        releases1 = [PyPIRelease(version="1.0", upload_date="2025-01-01")]
        releases2 = [PyPIRelease(version="1.0", upload_date="2025-01-02")]
        with get_db(temp_db) as conn:
            store_pypi_releases(conn, "my-pkg", releases1)
            store_pypi_releases(conn, "my-pkg", releases2)
            result = get_all_pypi_releases(conn, "my-pkg")
        assert len(result) == 1
        assert result[0]["upload_date"] == "2025-01-02"


class TestGitHubReleases:
    """Tests for GitHub release storage and retrieval."""

    def test_store_and_get_github_releases(self, temp_db):
        """Round-trip: store then retrieve GitHub releases."""
        releases = [
            GitHubRelease(tag_name="v0.1.0", published_at="2025-01-15", name="First"),
            GitHubRelease(tag_name="v0.2.0", published_at="2025-06-01", name=None),
        ]
        with get_db(temp_db) as conn:
            store_github_releases(conn, "owner/repo", releases)
            result = get_github_releases(conn, "owner/repo")

        assert result is not None
        assert len(result) == 2
        assert result[0]["tag_name"] == "v0.1.0"

    def test_get_github_releases_cache_miss(self, temp_db):
        """get_github_releases returns None when no data cached."""
        with get_db(temp_db) as conn:
            result = get_github_releases(conn, "owner/nonexistent")
        assert result is None
