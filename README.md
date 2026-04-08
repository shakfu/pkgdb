# pkgdb

Track, store, and analyze PyPI package download statistics.

Fetches download stats via the pypistats API, stores historical data in SQLite, and generates HTML reports with charts.

[Documentation](https://shakfu.github.io/pkgdb/)

## Installation

```sh
pip install pkgdb
```

To build:

Requires Python 3.10+. Uses [uv](https://github.com/astral-sh/uv) for dependency management.

```bash
uv sync
```

## Usage

### Quick start

The fastest way to get started is `pkgdb init`, which walks you through setup:

```bash
pkgdb init
```

This prompts for your PyPI username (optional), syncs your packages, fetches current stats, and generates an HTML report -- all in one step. For non-interactive use:

```bash
pkgdb init --user <pypi-username> --no-browser
```

### Configure packages

Create `~/.pkgdb/packages.json` to list packages to track:

```json
["my-package", "another-package"]
```

Or use an object with a `published` key:

```json
{"published": ["my-package", "another-package"]}
```

Alternatively, use `pkgdb add <package>` to add packages individually. By default, packages are verified to exist on PyPI before adding. Use `--no-verify` to skip this check.

### Configuration file

Create `~/.pkgdb/config.toml` to set persistent defaults:

```toml
[defaults]
github = true           # always include GitHub stats
environment = true      # always include environment summary
no_browser = false      # don't auto-open reports
sort_by = "total"       # default sort order (total, month, week, day, growth, name)
# database = "~/.pkgdb/pkg.db"  # custom database path

[report]
# output = "~/.pkgdb/report.html"  # custom report path

[init]
# pypi_user = "myusername"  # default PyPI username for init command
```

CLI flags always override config values. The config file is optional -- all settings have sensible defaults.

### Commands

```bash
# Guided first-run setup (sync packages, fetch stats, generate report)
pkgdb init

# Non-interactive init with PyPI username
pkgdb init --user <pypi-username>

# Add a package to tracking (verifies it exists on PyPI)
pkgdb add <package-name>

# Add without verification (offline/bulk use)
pkgdb add <package-name> --no-verify

# Remove a package from tracking
pkgdb remove <package-name>

# Show tracked packages
pkgdb packages

# Import packages from a file (JSON or plain text)
pkgdb import packages.json

# Fetch latest stats from PyPI and store in database
# (skips packages already fetched in the last 24 hours)
pkgdb fetch

# Display stats in terminal (includes trend sparklines and growth %)
pkgdb show

# Show package history (HTML report with chart + releases, opens in browser)
pkgdb history <package-name>

# Show history as text table in terminal
pkgdb history <package-name> --text

# Filter history by date (works with both HTML and text output)
pkgdb history <package-name> --since 7d   # last 7 days
pkgdb history <package-name> --since 2w   # last 2 weeks
pkgdb history <package-name> --since 1m   # last month (30 days)
pkgdb history <package-name> --since 2024-01-01

# Compare stats between time periods
pkgdb diff                   # compare to previous fetch
pkgdb diff --period week     # this week vs last week
pkgdb diff --period month    # this month vs last month

# Show release history for a package (PyPI and GitHub)
pkgdb releases <package-name>

# Show only the most recent 10 releases
pkgdb releases <package-name> --limit 10

# Generate HTML report with charts (opens in browser)
pkgdb report

# Generate detailed HTML report for a single package
pkgdb report <package-name>

# Generate project view with release timeline overlay
pkgdb report <package-name> --project

# Include environment summary (Python versions, OS) in report
pkgdb report -e

# Export stats in various formats
pkgdb export -f csv      # CSV format (default)
pkgdb export -f json     # JSON format
pkgdb export -f markdown # Markdown table

# Show detailed stats for a package (Python versions, OS breakdown)
pkgdb stats <package-name>

# Show database info (size, record counts, date range)
pkgdb show --info

# Generate SVG badge for a package
pkgdb badge <package-name>

# Badge for monthly downloads
pkgdb badge <package-name> --period month

# Save badge to file
pkgdb badge <package-name> -o badge.svg

# Fetch GitHub repository stats (stars, forks, activity, language)
pkgdb github

# Sort GitHub stats by name or activity instead of stars
pkgdb github fetch --sort name

# Bypass GitHub cache and fetch fresh data
pkgdb github fetch --no-cache

# Show GitHub cache statistics
pkgdb github cache

# Clear expired GitHub cache entries (or --all for everything)
pkgdb github clear

# Launch interactive web dashboard (opens browser)
pkgdb serve

# Serve on a custom port without opening browser
pkgdb serve --port 3000 --no-browser

# Fetch stats and generate report in one step
# (skips packages already fetched in the last 24 hours)
pkgdb update

# Fetch stats and generate report with environment summary
pkgdb update -e

# Include GitHub stats in fetch, report, or update
pkgdb fetch --github
pkgdb report --github
pkgdb update --github

# Clean up orphaned stats (for packages no longer tracked)
pkgdb cleanup

# Prune stats older than N days
pkgdb cleanup --days 365

# Sync packages from PyPI user account (initial or refresh)
pkgdb sync --user <pypi-username>

# Sync and remove packages no longer in user's PyPI account
pkgdb sync --user <pypi-username> --prune

# Show version
pkgdb version
```

### Options

```bash
# Use custom database file
pkgdb -d custom.db fetch

# Verbose output (show debug messages)
pkgdb -v fetch

# Quiet mode (only show warnings/errors)
pkgdb -q fetch

# Specify output file for report
pkgdb report -o custom-report.html

# Generate report without opening browser (useful for automation)
pkgdb report --no-browser

# Limit history to N days
pkgdb history my-package -n 14

# History report to file without opening browser
pkgdb history my-package -o history.html --no-browser

# Show history since a specific date (or relative: 7d, 2w, 1m)
pkgdb history my-package --since 2024-01-01
pkgdb history my-package --since 7d

# Skip package verification on import
pkgdb import packages.json --no-verify

# Limit show output to top N packages
pkgdb show --limit 10

# Sort show output by field (total, month, week, day, growth, name)
pkgdb show --sort-by month

# JSON output (available on show, packages, history, stats, cleanup, github)
pkgdb show --json
pkgdb packages --json
pkgdb history my-package --json
pkgdb stats my-package --json
pkgdb cleanup --json
pkgdb github --json

# Export to file instead of stdout
pkgdb export -f json -o stats.json
```

## Architecture

Modular CLI application with the following commands:

**Setup:**
- **init**: Guided first-run setup (sync packages, fetch stats, generate report)

**Package management:**
- **add**: Add a package to tracking
- **remove**: Remove a package from tracking
- **packages**: Show tracked packages with their added dates
- **import**: Import packages from file (JSON or text)
- **sync**: Sync packages from a PyPI user account (with optional `--prune`)

**Data operations:**
- **fetch**: Fetch download stats from PyPI and store in SQLite (with `-g` for GitHub stats)
- **show**: Display stats in terminal with trend sparklines and growth %
- **diff**: Compare download stats between time periods (previous fetch, week-over-week, month-over-month)
- **history**: Show package history as HTML report (default) or text table (`--text`)
- **stats**: Show detailed breakdown (Python versions, OS) for a package
- **releases**: Show release history for a package (PyPI and GitHub)
- **github**: Fetch and display GitHub repository stats (stars, forks, activity, language)
- **export**: Export stats in CSV, JSON, or Markdown format

**Reporting:**
- **report**: Generate HTML report with SVG charts. With `-e` flag, includes Python/OS summary. With `-g` flag, includes GitHub stats (stars, forks, language, activity) in the table. With package argument, generates detailed single-package report. With `-p/--project` flag, generates project view with release timeline overlay
- **badge**: Generate shields.io-style SVG badge for a package
- **update**: Run fetch then report in one step (supports `-e` for environment summary, `-g` for GitHub stats)
- **serve**: Launch interactive web dashboard with live data from SQLite. Overview with sortable/filterable stats table, package detail with zoomable charts and release markers, comparison with multi-package overlay

**Maintenance:**
- **cleanup**: Remove orphaned stats and optionally prune old data
- **version**: Show pkgdb version

### Data flow

```
packages.json -> pypistats API -> SQLite (pkg.db) -> HTML/terminal output
```

### Database schema

The `package_stats` table stores:
- `package_name`: Package identifier
- `fetch_date`: Date stats were fetched (YYYY-MM-DD)
- `last_day`, `last_week`, `last_month`: Recent download counts
- `total`: Total downloads (excluding mirrors)

The `python_version_stats` and `os_stats` tables cache environment data:
- `package_name`: Package identifier
- `fetch_date`: Date stats were fetched (YYYY-MM-DD)
- `category`: Python version (e.g. "3.12") or OS name (e.g. "Linux")
- `downloads`: Download count for that category

The `fetch_attempts` table tracks API requests:
- `package_name`: Package identifier (primary key)
- `attempt_time`: ISO timestamp of last fetch attempt
- `success`: Whether the fetch succeeded (1) or failed (0)

The `github_cache` table caches GitHub API responses:
- `repo_key`: Lowercased `owner/repo` identifier (primary key)
- `data`: Full JSON response from the GitHub API
- `fetched_at`: When the response was cached
- `expires_at`: Cache expiry time (default: 24 hours)

The `pypi_releases` table caches PyPI release history:
- `package_name`: Package identifier
- `version`: Release version string
- `upload_date`: Date the version was uploaded (YYYY-MM-DD)

The `github_releases` table caches GitHub release history:
- `repo_key`: Lowercased `owner/repo` identifier
- `tag_name`: Release tag (e.g. "v0.1.0")
- `published_at`: Date the release was published (YYYY-MM-DD)

The `release_cache` table tracks freshness of release data:
- `cache_key`: Cache identifier (e.g. "pypi:my-package" or "github:owner/repo")
- `fetched_at`: When the data was last fetched
- `expires_at`: Cache expiry time (default: 24 hours)

Stats are upserted per package per day. Fetch attempts are tracked to avoid hitting PyPI rate limits - packages are only fetched once per 24-hour period. Environment stats are cached alongside download stats, so reports can be generated offline. GitHub API responses are cached for 24 hours to minimize API calls. Release data (PyPI and GitHub) is cached for 24 hours.

## Files

Source modules in `src/pkgdb/`:
- `__init__.py`: Public API and version
- `cli.py`: CLI argument parsing and commands
- `config.py`: Configuration file loading (`~/.pkgdb/config.toml`)
- `service.py`: High-level service layer
- `db.py`: Database operations and context manager
- `api.py`: pypistats API wrapper with parallel fetching
- `reports.py`: HTML/SVG report generation
- `server.py`: HTTP server for the interactive web dashboard
- `dashboard.py`: HTML page templates for the dashboard (overview, detail, comparison)
- `github.py`: GitHub API client with caching and rate limit handling
- `badges.py`: SVG badge generation
- `export.py`: CSV/JSON/Markdown export
- `utils.py`: Helper functions and validation
- `types.py`: TypedDict definitions for type safety
- `logging.py`: Logging configuration

Data files (all in `~/.pkgdb/`):
- `config.toml`: Configuration file for persistent defaults (optional)
- `packages.json`: Package list configuration (optional, can use `add` command instead)
- `pkg.db`: SQLite database (auto-created)
- `report.html`: Generated HTML report (default output)

## GitHub Actions

An example workflow is provided at `.github/workflows/fetch-stats.yml.example` for automated daily stats fetching. To use it:

1. Copy to `.github/workflows/fetch-stats.yml` (remove `.example`)
2. Configure your package list or PyPI username
3. The workflow will fetch stats daily and commit updates to your repo

## Documentation

API documentation is built with MkDocs:

```bash
# Build docs
make docs

# Serve locally with live reload
make docs-serve

# Deploy to GitHub Pages
make docs-deploy
```

Then open `http://127.0.0.1:8000` to browse the docs locally.

## Development

```bash
# Install dev dependencies
uv sync

# Run tests
pytest

# Run tests with verbose output
pytest -v

# Full QA (test + lint + typecheck + format)
make qa
```

## Dependencies

Runtime:
- `pypistats`: PyPI download statistics API client
- `tabulate`: Terminal table formatting

Development:
- `pytest`: Testing framework

Documentation:
- `mkdocs`: Static site generator
- `mkdocs-material`: Material theme
- `mkdocstrings[python]`: Auto-generated API docs from docstrings
