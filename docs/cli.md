# CLI Reference

All commands support `-d <path>` for a custom database, `-v` for verbose output, and `-q` for quiet mode.

## Setup

### `pkgdb init`

Guided first-run setup: sync packages, fetch stats, generate report.

```bash
pkgdb init                          # interactive
pkgdb init --user <username>        # non-interactive
pkgdb init --no-browser             # don't open report
```

## Package Management

### `pkgdb add <name>`

Add a package to tracking. Verifies it exists on PyPI by default.

```bash
pkgdb add requests
pkgdb add my-pkg --no-verify        # skip PyPI check
```

### `pkgdb remove <name>`

Remove a package from tracking.

### `pkgdb packages`

List tracked packages with their added dates. Alias: `pkgdb list`.

```bash
pkgdb packages --json               # JSON output
```

### `pkgdb import <file>`

Import packages from a JSON or plain text file.

```bash
pkgdb import packages.json
pkgdb import packages.txt --no-verify
```

### `pkgdb sync --user <username>`

Sync package list from a PyPI user account.

```bash
pkgdb sync --user shakfu
pkgdb sync --user shakfu --prune    # remove packages no longer on PyPI
```

## Data Operations

### `pkgdb fetch`

Fetch download stats from PyPI. Skips packages fetched in the last 24 hours.

```bash
pkgdb fetch
pkgdb fetch --github                # also fetch GitHub stats
```

### `pkgdb show`

Display stats in terminal with trend sparklines and growth percentages.

```bash
pkgdb show
pkgdb show --sort-by month
pkgdb show --limit 10
pkgdb show --json
pkgdb show --info                   # database info
```

On first run (single data point), Trend and Growth columns are hidden automatically.

### `pkgdb diff`

Compare download stats between time periods.

```bash
pkgdb diff                          # vs previous fetch
pkgdb diff --period week            # this week vs last week
pkgdb diff --period month           # this month vs last month
pkgdb diff --sort-by change
pkgdb diff --json
```

### `pkgdb history <package>`

Show historical stats for a specific package.

```bash
pkgdb history requests
pkgdb history requests --since 7d
pkgdb history requests --since 2026-01-01
pkgdb history requests --json
```

### `pkgdb stats <package>`

Show detailed stats breakdown (Python versions, OS distribution).

```bash
pkgdb stats requests
pkgdb stats requests --json
```

### `pkgdb releases <package>`

Show release history from PyPI and GitHub.

```bash
pkgdb releases requests
pkgdb releases requests --limit 10
pkgdb releases requests --json
```

### `pkgdb github`

Fetch and display GitHub repository stats.

```bash
pkgdb github                        # fetch stats
pkgdb github fetch --sort stars
pkgdb github fetch --no-cache
pkgdb github cache                  # cache info
pkgdb github clear                  # clear expired cache
pkgdb github --json
```

### `pkgdb export`

Export stats in various formats.

```bash
pkgdb export -f csv
pkgdb export -f json -o stats.json
pkgdb export -f markdown
```

## Reporting

### `pkgdb report`

Generate HTML report with charts.

```bash
pkgdb report                        # all packages
pkgdb report <package>              # single package
pkgdb report <package> --project    # project view with releases
pkgdb report -e                     # include environment data
pkgdb report -g                     # include GitHub stats
pkgdb report -o custom.html
pkgdb report --no-browser
```

### `pkgdb badge <package>`

Generate shields.io-style SVG badge.

```bash
pkgdb badge requests
pkgdb badge requests --period month
pkgdb badge requests -o badge.svg
```

### `pkgdb update`

Shortcut: fetch stats then generate report.

```bash
pkgdb update
pkgdb update -e -g                  # with env and GitHub
```

## Maintenance

### `pkgdb cleanup`

Remove orphaned stats and optionally prune old data.

```bash
pkgdb cleanup
pkgdb cleanup --days 365            # prune stats older than 1 year
pkgdb cleanup --json
```

### `pkgdb version`

Show pkgdb version.
