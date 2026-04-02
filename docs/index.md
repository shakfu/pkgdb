# pkgdb

Track, store, and analyze PyPI package download statistics.

pkgdb fetches download stats via the pypistats API, stores historical data in SQLite, and generates HTML reports with interactive SVG charts.

## Features

- **Track packages** from PyPI with automatic verification
- **Historical data** stored in SQLite for trend analysis
- **HTML reports** with SVG line charts, bar charts, and pie charts
- **Release timeline** overlay on download charts (PyPI and GitHub releases)
- **GitHub integration** for repository stats (stars, forks, activity)
- **Environment breakdown** by Python version and OS
- **Export** to CSV, JSON, or Markdown
- **Configuration file** for persistent defaults

## Quick start

```bash
pip install pkgdb
pkgdb init
```

The `init` command walks you through setup: enter your PyPI username, fetch stats, and generate your first report.

## Usage modes

pkgdb can be used as a **CLI tool** or as a **Python library**.

### CLI

```bash
pkgdb fetch              # fetch latest stats
pkgdb show               # display stats in terminal
pkgdb report             # generate HTML report
pkgdb diff --period week # compare to last week
```

See the [CLI Reference](cli.md) for all commands.

### Python API

```python
from pkgdb import PackageStatsService

svc = PackageStatsService()
stats = svc.get_stats(with_growth=True)

for s in stats:
    print(f"{s['package_name']}: {s['total']:,} downloads")
```

See the [Python API](api/index.md) for full documentation.
