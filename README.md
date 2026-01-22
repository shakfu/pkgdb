# pkglog

Track PyPI package download statistics. Fetches download stats via the pypistats API, stores historical data in SQLite, and generates HTML reports with charts.

## Installation

Requires Python 3.13+. Uses [uv](https://github.com/astral-sh/uv) for dependency management.

```bash
uv sync
```

## Usage

### Configure packages

Edit `packages.yml` to list the packages you want to track:

```yaml
published:
  - my-package
  - another-package
```

### Commands

```bash
# Fetch latest stats from PyPI and store in database
pkglog fetch

# Display stats in terminal
pkglog list

# Generate HTML report with charts (opens in browser)
pkglog report

# Fetch stats and generate report in one step
pkglog update
```

### Options

```bash
# Use custom database file
pkglog -d custom.db fetch

# Use custom packages file
pkglog -p custom.yml fetch

# Specify output file for report
pkglog report -o custom-report.html
```

## Architecture

Single-file CLI application with four commands:

- **fetch**: Calls `pypistats.recent()` and `pypistats.overall()` for each package, stores results in SQLite
- **list**: Queries latest stats per package, prints formatted table to terminal
- **report**: Generates self-contained HTML report with Chart.js visualizations
- **update**: Runs fetch then report

### Data flow

```
packages.yml -> pypistats API -> SQLite (pkg.db) -> HTML/terminal output
```

### Database schema

The `package_stats` table stores:
- `package_name`: Package identifier
- `fetch_date`: Date stats were fetched (YYYY-MM-DD)
- `last_day`, `last_week`, `last_month`: Recent download counts
- `total`: Total downloads (excluding mirrors)

Stats are upserted per package per day, so running fetch multiple times on the same day updates rather than duplicates.

## Files

- `pkglog.py`: Main CLI application
- `packages.yml`: Package list configuration
- `pkg.db`: SQLite database (auto-created)
- `report.html`: Generated HTML report (default output)

## Development

```bash
# Install dev dependencies
uv sync

# Run tests
pytest

# Run tests with verbose output
pytest -v
```

## Dependencies

Runtime:
- `pypistats`: PyPI download statistics API client
- `pyyaml`: YAML configuration parsing
- `tabulate`: Terminal table formatting

Development:
- `pytest`: Testing framework
