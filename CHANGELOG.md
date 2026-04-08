# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.12]

### Added

- `serve` command: launch a local interactive web dashboard for browsing package stats
  - `pkgdb serve` starts a local HTTP server (stdlib `http.server`, no Flask/FastAPI dependency)
  - Overview page: sortable/filterable table of all tracked packages with growth metrics, click any package to drill down
  - Package detail page: zoomable download history chart (uPlot), release date markers with toggles for PyPI/GitHub sources, ranked horizontal bar charts for Python version and OS breakdown
  - Comparison page: select multiple packages and overlay their download trends on a single chart
  - Live data from SQLite database on each request
  - `--port` flag for custom port (default: 8080)
  - `--no-browser` flag to suppress auto-open
  - uPlot charting library (~40KB) bundled as a package static asset (no CDN dependency)
- `--delay` option for `fetch` and `update` commands to throttle API requests and avoid HTTP 429 rate-limit errors from pypistats (default: 1.0 second between packages, use `--delay 0` to disable)

## [0.1.11]

### Added

- `init` command: guided first-run setup that combines package discovery, stats fetching, and report generation in a single interactive workflow
  - `pkgdb init` prompts for PyPI username or manual package entry, fetches stats, and generates an HTML report
  - `pkgdb init --user <username>` runs non-interactively (useful for scripts and CI)
  - Supports `--no-browser` and `-o` output flags
  - If packages are already tracked, asks whether to continue with a fetch
  - Note: this is a new command distinct from the `init` removed in v0.1.5; that command only synced packages, while this one provides the full setup-to-report workflow
- Configuration file support: `~/.pkgdb/config.toml` for persistent defaults
  - `[defaults]` section: `database`, `github`, `environment`, `no_browser`, `sort_by`
  - `[report]` section: `output` path
  - `[init]` section: `pypi_user` for default PyPI username
  - CLI flags always override config values
  - Uses `tomllib` (stdlib in Python 3.11+); degrades gracefully on Python 3.10 without `tomli`
  - Invalid TOML files log a warning and fall back to defaults
- New module: `config.py` with `PkgdbConfig`, `load_config()`, `get_config_path()`
- New function: `apply_config()` for merging config defaults into CLI args
- `--json` flag added to `packages`, `history`, `stats`, `cleanup`, and `github` commands (including `github cache` and `github clear` subcommands) for machine-readable output
- `show` command now displays a "Next update available in Xh Ym" footer when packages are within the 24-hour fetch cooldown
- `releases` command: show release history for a package from PyPI and GitHub
  - `pkgdb releases <package>` displays a merged, date-sorted table of all releases
  - `--limit N` to show only the most recent N releases
  - `--json` flag for machine-readable output
  - PyPI releases fetched from `https://pypi.org/pypi/{package}/json`
  - GitHub releases fetched from the GitHub Releases API (auto-discovered from PyPI metadata)
  - 24-hour caching for both sources via `release_cache` table
- Project view report: `pkgdb report <package> --project`
  - Generates HTML report with download history line chart overlaid with release markers
  - PyPI releases shown as blue dashed vertical lines; GitHub releases as orange dashed lines
  - Includes merged release history table with date, version, and source
  - Includes environment distribution (Python versions, OS breakdown)
  - Uses 90-day history window (vs 30-day for standard package report)
- New database tables: `pypi_releases`, `github_releases`, `release_cache`
- New types: `PyPIRelease`, `GitHubRelease`
- New API functions: `fetch_pypi_releases()`, `fetch_github_releases()`
- New service methods: `fetch_package_releases()`, `generate_project_report()`
- New report function: `generate_project_html_report()` with `_make_line_chart_with_markers()`
- MkDocs-based API documentation with mkdocs-material theme and mkdocstrings autodoc
  - `make docs` to build, `make docs-serve` to preview locally, `make docs-deploy` to publish to GitHub Pages
  - Covers: getting started, CLI reference, Python API (service, types, database, PyPI, GitHub, reports, config)
  - API reference auto-generated from source docstrings
- `diff` command: compare download stats between two time periods
  - `pkgdb diff` compares current stats to the previous fetch (default)
  - `--period week` compares this week to last week
  - `--period month` compares this month to last month
  - `--sort-by` option to sort by total, month, week, day, change, or name
  - `--json` flag for machine-readable output
  - Shows absolute change and percentage change for each metric

### Changed

- `history` command now generates an HTML report by default with download chart, release markers, and history table (opens in browser)
  - `--text` / `-t` flag for the previous terminal table output
  - `--json` flag unchanged
  - `-o` / `--output` for custom output path, `--no-browser` to suppress browser
  - Default history window increased from 30 to 90 days
- `show` command now hides Trend and Growth columns when there is only one data point per package, producing a cleaner output on first run instead of showing empty sparklines and blank growth percentages
- Split monolithic `tests/test_pkgdb.py` (6100+ lines) into 13 focused test modules: `test_db`, `test_api`, `test_utils`, `test_export`, `test_reports`, `test_badges`, `test_github`, `test_service`, `test_cli`, `test_config`, `test_releases`, `test_integration`, and shared fixtures in `conftest.py`

## [0.1.10]

### Fixed

- `check_package_exists` now normalizes package names per PEP 503 before querying PyPI Simple API, so names with mixed case or underscores (e.g. `Requests`, `my_pkg`) resolve correctly
- `remove_package` now deletes the corresponding `fetch_attempts` row, preventing re-added packages from being incorrectly skipped by `fetch` due to stale attempt records
- `cleanup_orphaned_stats` now also cleans orphaned `fetch_attempts` entries
- GitHub `--sort activity` no longer ranks repos pushed today as stale: fixed operator precedence bug and falsy-zero handling in the sort key
- `pkgdb report <package>` now correctly reports failure when stats cannot be fetched, instead of announcing success and opening a non-existent file

## [0.1.9]

### Added

- GitHub repository statistics: fetch stars, forks, open issues, language, activity status, and more for tracked packages
  - New `github` command with subcommands:
    - `pkgdb github [fetch]` displays GitHub stats table (stars, forks, activity, language) for all tracked packages
    - `pkgdb github cache` shows cache statistics
    - `pkgdb github clear [--all]` clears cached GitHub API responses
  - `--sort` option for GitHub fetch: sort by `stars` (default), `name`, or `activity`
  - `--no-cache` flag to bypass the 24-hour cache and fetch fresh data
  - `-g/--github` flag on `fetch`, `update`, and `report` commands to include GitHub stats alongside PyPI download stats
  - HTML report includes GitHub columns (Stars, Forks, Language, Activity, Repository) when `--github` is passed; pulls from cache if available, skips gracefully if not
  - GitHub repo URL auto-discovery from PyPI package metadata (`project_urls`, `home_page`)
  - Supports `GITHUB_TOKEN` / `GH_TOKEN` environment variables for higher API rate limits
  - 24-hour response caching in SQLite (`github_cache` table) to minimize API calls
  - Exponential backoff with jitter on rate limiting (HTTP 403)
- New module: `github.py` with `RepoStats`, `RepoResult`, `parse_github_url()`, `extract_github_url()`, `fetch_repo_stats()`, `fetch_package_github_stats()`
- New service methods: `fetch_github_stats()`, `clear_github_cache()`, `get_github_cache_stats()`

## [0.1.8]

### Fixed

- `get_stats_with_growth` now computes `week_growth` from `last_week` column instead of `last_month`
- `get_packages_needing_update` now only filters on successful attempts, so transient API failures no longer block retries for 24 hours
- License classifier in `pyproject.toml` corrected from "BSD License" to "MIT License" to match actual license
- CLI "All packages already up to date" message now shows when the next update will be available (e.g. "Next update available in 23h 45m")

### Added

- Environment stats caching: Python version and OS distribution data now stored in SQLite during fetch
  - New tables: `python_version_stats` and `os_stats`
  - `pkgdb report <package>` uses cached env data instead of live API calls (offline-capable)
  - `pkgdb report --env` reads cached aggregated env data (falls back to live API if no cache)
  - Env stats are fetched alongside download stats in the same 24h fetch cycle
- `-e/--env` flag on `pkgdb update` for parity with `pkgdb report` (fetch + env-enabled report in one step)
- Growth indicators (week-over-week, month-over-month) in the HTML report table, with colored arrows for positive/negative trends
- New functions: `store_env_stats()`, `get_cached_python_versions()`, `get_cached_os_stats()`, `get_cached_env_summary()`
- `cleanup_orphaned_stats()` and `prune_old_stats()` now also clean env stats tables
- `get_next_update_seconds()` function to compute seconds until the next package becomes eligible for update
- `FetchResult.next_update_seconds` field for programmatic access to next update timing

### Removed

- Removed references to YAML support in docstrings and help text (YAML parsing was removed in v0.1.3; only JSON and plain text are supported)
- Deleted legacy `packages.yml` (unused since v0.1.3)

## [0.1.7]

### Added

- Fetch attempt tracking: packages are only fetched once per 24-hour period
  - New `fetch_attempts` table tracks when each package was last fetched
  - Both successful and failed fetch attempts are recorded
  - Subsequent `pkgdb update` or `pkgdb fetch` runs skip recently-attempted packages
  - CLI reports skipped count: "Skipped N packages (already fetched in last 24 hours)"
  - Shows "All packages already up to date" when nothing needs fetching
- "Recent Downloads (Last Day)" chart in HTML reports, displayed after the "Last Month" chart
- New functions: `record_fetch_attempt()`, `get_packages_needing_update()`
- `FetchResult` dataclass now includes `skipped` field

## [0.1.6]

### Added

- Package validation: `add` and `import` commands now verify packages exist on PyPI before adding
  - Uses HEAD request to PyPI Simple API for minimal overhead
  - `--no-verify` flag to skip verification for offline/bulk operations
  - Network errors warn but allow operation (fail open)
- Relative date queries: `--since` flag now accepts relative formats
  - `7d` for 7 days ago
  - `2w` for 2 weeks ago
  - `1m` for 1 month ago (treated as 30 days)
  - Still supports `YYYY-MM-DD` format
- New functions: `check_package_exists()`, `parse_date_arg()`, `get_database_stats()`
- Service methods `add_package()` and `import_packages()` now accept `verify` parameter
- Database info: `pkgdb show --info` displays database statistics (file size, package count, record count, date range)
- New type: `DatabaseInfo` TypedDict for database statistics
- Badge generation: `pkgdb badge <package>` generates shields.io-style SVG badges
  - Supports `--period` flag for total/month/week/day
  - Auto-selects color based on download count
  - Output to file with `-o` or stdout
- GitHub Actions workflow template: `.github/workflows/fetch-stats.yml.example`
- New module: `badges.py` with `generate_badge_svg()` and `generate_downloads_badge()`

### Changed

- `import_packages()` now returns 4-tuple: `(added, skipped, invalid, not_found)`

### Fixed

- "Recent Downloads (Last Month)" chart now sorted by decreasing downloads (consistent with "Total Downloads by Package" chart)

## [0.1.5]

### Added

- `sync` command: `pkgdb sync --user <username>` populates or refreshes the package list from a PyPI user account, adding any new packages without duplicating existing ones
- `sync --prune` option: removes locally tracked packages no longer in the user's PyPI account
- `SyncResult` dataclass for programmatic access to sync results (added, already_tracked, not_on_remote, pruned)
- Service method `sync_packages_from_user(username, prune=False)` for the service layer API

### Removed

- `init` command: use `sync --user <username>` instead (same functionality, plus refresh and prune capabilities)

## [0.1.4]

### Added

- `list` alias for `packages` subcommand: `pkgdb list` now works as an alias for `pkgdb packages`

### Fixed

- Graceful handling of HTTP 404 errors during fetch: packages not found on PyPI stats no longer crash the entire fetch operation; they are logged as warnings and counted as failed

## [0.1.3]

### Added

- `version` subcommand: `pkgdb version` displays the package version
- `init` command: `pkgdb init --user <username>` auto-populates packages from a PyPI user account
- `show` command enhancements:
  - `--limit N` to show only top N packages
  - `--sort-by` option to sort by total, month, week, day, growth, or name
  - `--json` flag for machine-readable JSON output
- `history` command: `--since DATE` flag to filter history by date (YYYY-MM-DD)
- `--no-browser` flag for `report` and `update` commands (useful for automation/cron)
- Progress indicator during fetch: `[1/27] Fetching stats for package...`
- Database context manager `get_db()` for safer resource handling
- Service layer `PackageStatsService` for decoupled, testable operations
- Dataclasses: `PackageInfo`, `FetchResult`, `PackageDetails`
- Package name validation: `validate_package_name()` enforces PyPI naming conventions
- Logging module with `-v/--verbose` and `-q/--quiet` flags
- TypedDict types for type safety: `PackageStats`, `CategoryDownloads`, `EnvSummary`, `HistoryRecord`, `StatsWithGrowth`
- Parallel API fetching with `fetch_all_package_stats()` and improved `aggregate_env_stats()`
- `cleanup` command with `--orphans` and `--prune` flags for database maintenance
- Database functions: `cleanup_orphaned_stats()`, `prune_old_stats()`
- Service methods: `cleanup()`, `prune()`
- Named constants for theme colors (`THEME_PRIMARY_COLOR`), chart dimensions, limits (`PIE_CHART_MAX_ITEMS`, `LINE_CHART_MAX_SERIES`), and sparkline parameters (`SPARKLINE_WIDTH`, `SPARKLINE_CHARS`)
- Integration tests (require network, run with `RUN_INTEGRATION=1 pytest -m integration`)
- Performance tests (run with `RUN_SLOW_TESTS=1 pytest -m slow`)
- Edge case tests for chart generation (boundary conditions, single data points, large numbers)
- Error path tests (invalid files, partial API failures, database edge cases)
- Output path validation: `validate_output_path()` checks for path traversal, sensitive directories, file extensions, and write permissions
- Batch stats storage: `store_stats_batch()` for efficient multi-package inserts with single commit
- 98 new tests (167 total, 8 skipped by default)

### Changed

- **BREAKING**: Default config file changed from `packages.yml` to `~/.pkgdb/packages.json`
- **BREAKING**: Renamed `list` command to `packages` for clarity (`pkgdb packages`)
- Removed `pyyaml` dependency - now uses stdlib `json` only
- All data files now consistently use `~/.pkgdb/` directory (packages.json, pkg.db, report.html)
- Service `fetch_all_stats()` now uses batch commits for better performance
- Service report/export methods validate output paths before writing
- Narrowed exception handling in API functions to specific exceptions (`JSONDecodeError`, `URLError`, `ValueError`, `KeyError`, `TypeError`, `OSError`) instead of bare `except` - improves debugging
- Replaced print statements with Python logging throughout CLI/API/reports
- Modular architecture: split monolithic `__init__.py` into focused modules:
  - `utils.py` - Helper functions (sparkline, growth calculation)
  - `export.py` - CSV/JSON/Markdown export
  - `api.py` - pypistats API wrapper functions (now with parallel fetching)
  - `db.py` - Database operations and context manager
  - `service.py` - High-level service layer abstraction
  - `cli.py` - CLI argument parsing and commands
  - `reports.py` - HTML/SVG report generation
  - `logging.py` - Logging configuration with verbose/quiet modes
  - `types.py` - TypedDict definitions for type safety
  - `__init__.py` - Public API re-exports
- All CLI commands now use context manager for database connections
- Refactored `reports.py` to extract shared components:
  - `_render_html_document()` for HTML boilerplate
  - `_make_single_line_chart()` for single-series line charts
  - `_make_multi_line_chart()` for multi-package time-series charts
  - `_build_env_charts()` for Python version and OS pie charts
  - Eliminated ~110 lines of duplicated CSS and SVG chart code

### Fixed

- N+1 query performance issue in `get_stats_with_growth()`: now uses single query via `get_all_history()` instead of one query per package

## [0.1.2]

### Added

- HTML report enhancements:
  - `pkgdb report <package>` generates detailed single-package report with download stats, history chart, Python version and OS distribution pie charts
  - `pkgdb report -e` includes aggregated Python version and OS distribution summary in the main report
- New functions: `make_svg_pie_chart`, `aggregate_env_stats`, `generate_package_html_report`
- 14 new tests for pie charts, environment aggregation, and package reports (69 total)

- `stats` command for detailed package statistics:
  - Python version distribution with visual bars
  - Operating system breakdown (Linux, Windows, Darwin)
  - Download summary (total, month, week, day)
- New functions: `fetch_python_versions`, `fetch_os_stats`

### Note

- Per-version (package version) downloads not available through pypistats API

## [0.1.1]

### Added

- `export` command with support for multiple formats:
  - CSV (`pkgdb export -f csv`)
  - JSON (`pkgdb export -f json`)
  - Markdown (`pkgdb export -f markdown`)
- Export to file with `-o` option or stdout by default
- New functions: `export_csv`, `export_json`, `export_markdown`

- `history` command to view historical stats for a specific package
- Growth metrics (month-over-month percentage change) in `list` output
- Sparkline trend indicators in `list` output
- Time-series chart in HTML report showing downloads over time (top 5 packages)
- New functions: `get_package_history`, `get_all_history`, `calculate_growth`, `make_sparkline`

### Changed

- `list` command now shows trend sparklines and growth percentages
- HTML report now includes "Downloads Over Time" chart when historical data available

## [0.1.0]

### Added

- Initial release
- CLI commands: `fetch`, `list`, `report`, `update`
- SQLite database storage for historical stats
- HTML report generation with SVG visualizations
- YAML-based package configuration (`packages.yml`)
- Support for custom database and packages file paths
- Pytest test suite with 24 tests covering:
  - Database operations
  - Package loading from YAML
  - Statistics storage and retrieval
  - HTML report generation
  - CLI argument parsing
