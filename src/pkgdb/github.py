"""GitHub API client for fetching repository statistics."""

import json
import logging
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .utils import utcnow

logger = logging.getLogger("pkgdb")

GITHUB_API = "https://api.github.com"
GITHUB_REPO_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/([^/]+)/([^/]+?)(?:\.git)?(?:/.*)?$"
)
PYPI_JSON_API = "https://pypi.org/pypi"

# Cache TTL: 24 hours
GITHUB_CACHE_TTL_HOURS = 24

# Cache-key suffix for the issues-only count, which is a separate API call.
OPEN_ISSUES_CACHE_SUFFIX = "#open-issues"

GITHUB_CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS github_cache (
    repo_key TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL
)
"""


@dataclass
class RepoStats:
    """Statistics for a GitHub repository."""

    owner: str
    name: str
    full_name: str
    description: str | None
    stars: int
    forks: int
    # GitHub's open_issues_count, which counts open pull requests as issues.
    open_issues: int
    watchers: int
    language: str | None
    license: str | None
    created_at: datetime | None
    updated_at: datetime | None
    pushed_at: datetime | None
    archived: bool
    fork: bool
    default_branch: str
    topics: list[str]
    homepage: str | None = None
    # Open issues with pull requests excluded, from the search API. None when
    # the count could not be fetched; see fetch_open_issue_count().
    open_issues_excl_prs: int | None = None

    @property
    def repo_url(self) -> str:
        """Canonical HTTPS URL of the git repository."""
        return f"https://github.com/{self.full_name}"

    @property
    def issues_url(self) -> str:
        """URL of the repository's open issue list."""
        return f"{self.repo_url}/issues"

    @property
    def days_since_push(self) -> int | None:
        if self.pushed_at:
            # pushed_at comes from the API as UTC with the tzinfo stripped.
            return (utcnow() - self.pushed_at).days
        return None

    @property
    def is_active(self) -> bool:
        days = self.days_since_push
        return days is not None and days < 365

    @property
    def activity_status(self) -> str:
        if self.archived:
            return "archived"
        days = self.days_since_push
        if days is None:
            return "unknown"
        if days < 30:
            return "very active"
        if days < 90:
            return "active"
        if days < 365:
            return "maintained"
        return "stale"


@dataclass
class RepoResult:
    """Result of fetching repo stats for a package."""

    package_name: str
    repo_url: str | None
    stats: RepoStats | None = None
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.stats is not None


def parse_github_url(url: str) -> tuple[str, str] | None:
    """Extract owner and repo name from a GitHub URL.

    Returns (owner, repo) tuple or None if not a GitHub URL.
    """
    if not url:
        return None
    match = GITHUB_REPO_PATTERN.match(url)
    if match:
        return match.group(1), match.group(2)
    return None


def get_github_token() -> str | None:
    """Get GitHub token from environment (GITHUB_TOKEN or GH_TOKEN)."""
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def extract_github_url(package_name: str) -> str | None:
    """Extract GitHub repository URL from PyPI package metadata.

    Queries the PyPI JSON API and looks for GitHub URLs in project_urls
    and home_page fields.

    Returns the GitHub URL or None if not found.
    """
    url = f"{PYPI_JSON_API}/{package_name}/json"
    try:
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
    except (HTTPError, URLError, TimeoutError, OSError) as e:
        logger.warning("Could not fetch PyPI metadata for '%s': %s", package_name, e)
        return None

    info = data.get("info", {})

    # Check project_urls first (most reliable)
    project_urls = info.get("project_urls") or {}
    for key in ("Repository", "Source", "Source Code", "Code", "GitHub", "Homepage"):
        val = project_urls.get(key, "")
        if val and "github.com" in val.lower():
            return str(val)

    # Fallback to home_page
    home_page = info.get("home_page") or ""
    if "github.com" in home_page.lower():
        return str(home_page)

    # Check all project_urls values
    for val in project_urls.values():
        if val and "github.com" in val.lower():
            return str(val)

    return None


# ---------------------------------------------------------------------------
# GitHub API Cache
# ---------------------------------------------------------------------------


def _get_cache_key(owner: str, repo: str) -> str:
    return f"{owner.lower()}/{repo.lower()}"


def _ensure_cache_table(conn: sqlite3.Connection) -> None:
    conn.execute(GITHUB_CACHE_SCHEMA)


def _get_cached_json(
    conn: sqlite3.Connection, cache_key: str
) -> dict[str, Any] | None:
    """Get a cached API response by key if still valid."""
    _ensure_cache_table(conn)
    cursor = conn.execute(
        "SELECT data FROM github_cache WHERE repo_key = ? AND expires_at > datetime('now')",
        (cache_key,),
    )
    row = cursor.fetchone()
    if row:
        try:
            result: dict[str, Any] = json.loads(row["data"])
            return result
        except json.JSONDecodeError:
            return None
    return None


def _store_cached_json(
    conn: sqlite3.Connection,
    cache_key: str,
    data: dict[str, Any],
    ttl_hours: int = GITHUB_CACHE_TTL_HOURS,
) -> None:
    """Store an API response under a cache key."""
    _ensure_cache_table(conn)
    # UTC: compared against SQLite's datetime('now') in _get_cached_json.
    expires_at = utcnow() + timedelta(hours=ttl_hours)
    conn.execute(
        """INSERT OR REPLACE INTO github_cache (repo_key, data, fetched_at, expires_at)
           VALUES (?, ?, datetime('now'), ?)""",
        (cache_key, json.dumps(data), expires_at.isoformat()),
    )
    conn.commit()


def get_cached_repo_data(
    conn: sqlite3.Connection, owner: str, repo: str
) -> dict[str, Any] | None:
    """Get cached GitHub API response if still valid."""
    return _get_cached_json(conn, _get_cache_key(owner, repo))


def store_cached_repo_data(
    conn: sqlite3.Connection,
    owner: str,
    repo: str,
    data: dict[str, Any],
    ttl_hours: int = GITHUB_CACHE_TTL_HOURS,
) -> None:
    """Store GitHub API response in cache."""
    _store_cached_json(conn, _get_cache_key(owner, repo), data, ttl_hours)


def clear_github_cache(conn: sqlite3.Connection, expired_only: bool = True) -> int:
    """Clear GitHub API cache entries.

    Returns number of entries cleared.
    """
    _ensure_cache_table(conn)
    if expired_only:
        conn.execute("DELETE FROM github_cache WHERE expires_at <= datetime('now')")
    else:
        conn.execute("DELETE FROM github_cache")
    deleted: int = conn.execute("SELECT changes()").fetchone()[0]
    conn.commit()
    return deleted


def get_github_cache_stats(conn: sqlite3.Connection) -> dict[str, int]:
    """Get statistics about the GitHub cache."""
    _ensure_cache_table(conn)
    total = conn.execute("SELECT COUNT(*) FROM github_cache").fetchone()[0]
    valid = conn.execute(
        "SELECT COUNT(*) FROM github_cache WHERE expires_at > datetime('now')"
    ).fetchone()[0]
    return {"total": total, "valid": valid, "expired": total - valid}


# ---------------------------------------------------------------------------
# Exponential Backoff
# ---------------------------------------------------------------------------


def _exponential_backoff(
    attempt: int,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
) -> float:
    """Calculate delay for exponential backoff."""
    import random

    delay: float = min(base_delay * (2**attempt), max_delay)
    delay = delay * (0.5 + random.random())
    return delay


def _fetch_with_backoff(
    url: str,
    headers: dict[str, str],
    max_retries: int = 3,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Fetch URL with exponential backoff on rate limiting (403).

    Raises HTTPError on non-retryable errors or max retries exceeded.
    """
    last_error: HTTPError | None = None

    for attempt in range(max_retries + 1):
        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=timeout) as response:
                result: dict[str, Any] = json.loads(response.read().decode())
                return result
        except HTTPError as e:
            if e.code == 403:
                last_error = e
                if attempt < max_retries:
                    delay = _exponential_backoff(attempt)
                    retry_after = e.headers.get("Retry-After")
                    if retry_after:
                        try:
                            delay = max(delay, float(retry_after))
                        except ValueError:
                            pass
                    time.sleep(delay)
                    continue
            raise

    if last_error:
        raise last_error
    raise RuntimeError("Unexpected state in backoff loop")


# ---------------------------------------------------------------------------
# Parsing & Fetching
# ---------------------------------------------------------------------------


def _parse_datetime(date_str: str | None) -> datetime | None:
    if date_str:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00")).replace(
            tzinfo=None
        )
    return None


def _parse_repo_data(data: dict[str, Any]) -> RepoStats:
    """Parse GitHub API response into RepoStats."""
    license_name = None
    if data.get("license"):
        license_name = data["license"].get("spdx_id") or data["license"].get("name")

    return RepoStats(
        owner=data["owner"]["login"],
        name=data["name"],
        full_name=data["full_name"],
        description=data.get("description"),
        stars=data.get("stargazers_count", 0),
        forks=data.get("forks_count", 0),
        open_issues=data.get("open_issues_count", 0),
        watchers=data.get("subscribers_count", 0),
        language=data.get("language"),
        license=license_name,
        created_at=_parse_datetime(data.get("created_at")),
        updated_at=_parse_datetime(data.get("updated_at")),
        pushed_at=_parse_datetime(data.get("pushed_at")),
        archived=data.get("archived", False),
        fork=data.get("fork", False),
        default_branch=data.get("default_branch", "main"),
        topics=data.get("topics", []),
        homepage=data.get("homepage") or None,
    )


def _github_headers() -> dict[str, str]:
    """Build request headers, adding the token when one is configured."""
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "pkgdb",
    }
    token = get_github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_open_issue_count(
    owner: str,
    repo: str,
    conn: sqlite3.Connection | None = None,
    use_cache: bool = True,
) -> int | None:
    """Count a repository's open issues, excluding pull requests.

    The repository endpoint's ``open_issues_count`` counts open pull requests
    as issues, so this asks the search API for ``is:issue is:open`` instead.
    Cached alongside the repo response with the same TTL.

    Returns None when the count could not be determined, which callers should
    render as unknown rather than as zero. The search API has its own, tighter
    rate limit (30 requests/minute authenticated, 10 unauthenticated), so this
    is the part of a GitHub fetch most likely to come back empty.
    """
    cache_key = _get_cache_key(owner, repo) + OPEN_ISSUES_CACHE_SUFFIX
    if use_cache and conn is not None:
        cached = _get_cached_json(conn, cache_key)
        if cached is not None:
            count = cached.get("open_issues")
            return int(count) if isinstance(count, int) else None

    query = f"repo:{owner}/{repo}+is:issue+is:open"
    url = f"{GITHUB_API}/search/issues?q={query}&per_page=1"
    try:
        data = _fetch_with_backoff(url, _github_headers(), max_retries=2, timeout=30.0)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as e:
        logger.debug("Open issue count unavailable for %s/%s: %s", owner, repo, e)
        return None

    total = data.get("total_count")
    if not isinstance(total, int):
        return None

    if use_cache and conn is not None:
        _store_cached_json(conn, cache_key, {"open_issues": total})
    return total


def fetch_repo_stats(
    owner: str,
    repo: str,
    conn: sqlite3.Connection | None = None,
    use_cache: bool = True,
) -> RepoStats:
    """Fetch repository statistics from GitHub API.

    Uses cached responses when available (24h TTL).
    Supports GITHUB_TOKEN/GH_TOKEN for higher rate limits.
    Uses exponential backoff on rate limiting (403).

    Raises HTTPError on API errors.
    """
    # Check cache first
    cached = (
        get_cached_repo_data(conn, owner, repo)
        if use_cache and conn is not None
        else None
    )
    if cached:
        stats = _parse_repo_data(cached)
    else:
        url = f"{GITHUB_API}/repos/{owner}/{repo}"
        data = _fetch_with_backoff(
            url, _github_headers(), max_retries=3, timeout=30.0
        )

        # Cache the response
        if use_cache and conn is not None:
            store_cached_repo_data(conn, owner, repo, data)

        stats = _parse_repo_data(data)

    # open_issues_count counts pull requests too; get the issues-only figure
    # separately. Cached independently, so a warm cache costs no requests.
    stats.open_issues_excl_prs = fetch_open_issue_count(
        owner, repo, conn=conn, use_cache=use_cache
    )
    return stats


def fetch_package_github_stats(
    package_name: str,
    conn: sqlite3.Connection | None = None,
    use_cache: bool = True,
) -> RepoResult:
    """Fetch GitHub stats for a PyPI package.

    Looks up the GitHub repo URL from PyPI metadata, then fetches
    repository statistics from the GitHub API.
    """
    github_url = extract_github_url(package_name)
    if not github_url:
        return RepoResult(
            package_name=package_name,
            repo_url=None,
            error="No GitHub repository found in PyPI metadata",
        )

    parsed = parse_github_url(github_url)
    if not parsed:
        return RepoResult(
            package_name=package_name,
            repo_url=github_url,
            error="Could not parse GitHub URL",
        )

    owner, repo = parsed
    try:
        stats = fetch_repo_stats(owner, repo, conn=conn, use_cache=use_cache)
        return RepoResult(package_name=package_name, repo_url=github_url, stats=stats)
    except HTTPError as e:
        if e.code == 404:
            error = "Repository not found"
        elif e.code == 403:
            error = "Rate limited (retries exhausted)"
        else:
            error = f"HTTP {e.code}"
        return RepoResult(package_name=package_name, repo_url=github_url, error=error)
    except (URLError, TimeoutError, OSError) as e:
        return RepoResult(package_name=package_name, repo_url=github_url, error=str(e))


def fetch_github_releases(owner: str, repo: str) -> list[dict[str, Any]] | None:
    """Fetch release list from the GitHub Releases API.

    Args:
        owner: Repository owner.
        repo: Repository name.

    Returns:
        List of release dicts with tag_name, published_at, and name,
        sorted by published_at ascending. Returns None on API error,
        or an empty list if the repo has no releases.
    """
    token = get_github_token()
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "pkgdb",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = f"{GITHUB_API}/repos/{owner}/{repo}/releases?per_page=100"
    try:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode())
    except HTTPError as e:
        if e.code == 404:
            return []
        logger.warning(
            "Error fetching GitHub releases for %s/%s: HTTP %d", owner, repo, e.code
        )
        return None
    except (URLError, TimeoutError, OSError) as e:
        logger.warning("Error fetching GitHub releases for %s/%s: %s", owner, repo, e)
        return None

    if not isinstance(data, list):
        return []

    releases = []
    for r in data:
        published_at = r.get("published_at")
        if not published_at or r.get("draft"):
            continue
        releases.append(
            {
                "tag_name": r.get("tag_name", ""),
                "published_at": published_at[:10],  # YYYY-MM-DD
                "name": r.get("name"),
            }
        )

    releases.sort(key=lambda x: x["published_at"])
    return releases
