# Getting Started

## Installation

```bash
pip install pkgdb
```

Or from source:

```bash
git clone https://github.com/shakfu/pkgdb.git
cd pkgdb
uv sync
```

Requires Python 3.10+.

## First run

The fastest way to get started:

```bash
pkgdb init
```

This prompts for your PyPI username (optional), syncs your packages, fetches current stats, and generates an HTML report.

For non-interactive setup:

```bash
pkgdb init --user <pypi-username> --no-browser
```

## Manual setup

If you prefer manual control:

```bash
# Add packages one at a time
pkgdb add requests
pkgdb add flask

# Or import from a file
echo '["requests", "flask"]' > packages.json
pkgdb import packages.json

# Fetch stats
pkgdb fetch

# View in terminal
pkgdb show

# Generate HTML report
pkgdb report
```

## Configuration

Create `~/.pkgdb/config.toml` for persistent defaults:

```toml
[defaults]
github = true
environment = true
sort_by = "total"

[report]
output = "~/.pkgdb/report.html"

[init]
pypi_user = "myusername"
```

CLI flags always override config values.

## Data storage

All data is stored locally in `~/.pkgdb/`:

| File | Purpose |
|------|---------|
| `pkg.db` | SQLite database (auto-created) |
| `config.toml` | Configuration (optional) |
| `packages.json` | Package list (optional) |
| `report.html` | Generated report (default output) |

## Automated fetching

pkgdb respects a 24-hour cooldown per package to avoid overloading the PyPI stats API. For daily automated fetching, see the GitHub Actions workflow template at `.github/workflows/fetch-stats.yml.example`.
