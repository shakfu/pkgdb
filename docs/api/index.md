# Python API Overview

pkgdb exposes a Python API for programmatic access to all functionality. The primary entry point is the `PackageStatsService` class.

## Quick start

```python
from pkgdb import PackageStatsService

# Initialize with default database (~/.pkgdb/pkg.db)
svc = PackageStatsService()

# Or use a custom database path
svc = PackageStatsService("/path/to/custom.db")
```

## Common operations

### Fetch and display stats

```python
from pkgdb import PackageStatsService

svc = PackageStatsService()

# Fetch latest stats from PyPI
result = svc.fetch_all_stats()
print(f"Fetched {result.success} packages, {result.failed} failed")

# Get stats with growth metrics
stats = svc.get_stats(with_growth=True)
for s in stats:
    name = s["package_name"]
    total = s["total"]
    growth = s.get("month_growth")
    print(f"{name}: {total:,} total", end="")
    if growth is not None:
        print(f" ({growth:+.1f}%)", end="")
    print()
```

### Package management

```python
svc = PackageStatsService()

# Add packages
svc.add_package("requests")
svc.add_package("flask", verify=False)

# List tracked packages
for pkg in svc.list_packages():
    print(f"{pkg.name} (added {pkg.added_date})")

# Sync from PyPI user
result = svc.sync_packages_from_user("myusername")
print(f"Added: {result.added}")

# Remove a package
svc.remove_package("old-package")
```

### Historical data

```python
svc = PackageStatsService()

# Get history for a specific package
history = svc.get_history("requests", limit=30)
for h in history:
    print(f"{h['fetch_date']}: {h['total']:,}")

# Get history for all packages
all_history = svc.get_all_history(limit_per_package=14)
```

### Reports and export

```python
svc = PackageStatsService()

# Generate HTML report
svc.generate_report("report.html", include_env=True, include_github=True)

# Generate single-package report
svc.generate_package_report("requests", "requests-report.html")

# Generate project view with release timeline
svc.generate_project_report("requests", "requests-project.html")

# Export to various formats
csv_output = svc.export("csv")
json_output = svc.export("json")
md_output = svc.export("markdown")
```

### Release data

```python
svc = PackageStatsService()

# Get PyPI and GitHub releases for a package
pypi_releases, github_releases = svc.fetch_package_releases("requests")

for r in pypi_releases:
    print(f"PyPI: {r['version']} ({r['upload_date']})")

for r in github_releases:
    print(f"GitHub: {r['tag_name']} ({r['published_at']})")
```

### GitHub stats

```python
svc = PackageStatsService()

# Fetch GitHub stats for all tracked packages
results = svc.fetch_github_stats()
for r in results:
    if r.success and r.stats:
        print(f"{r.package_name}: {r.stats.stars} stars")
```

### Database maintenance

```python
svc = PackageStatsService()

# Clean up orphaned stats
orphaned, remaining = svc.cleanup()

# Prune old data
deleted = svc.prune(days=365)

# Database info
info = svc.get_database_info()
print(f"{info['package_count']} packages, {info['record_count']} records")
```

## Module reference

| Module | Description |
|--------|-------------|
| [Service Layer](service.md) | `PackageStatsService` -- the main API |
| [Types](types.md) | TypedDict definitions for data structures |
| [Database](database.md) | SQLite operations |
| [PyPI API](pypi.md) | pypistats wrapper and PyPI JSON API |
| [GitHub](github.md) | GitHub API client |
| [Reports](reports.md) | HTML/SVG report generation |
| [Config](config.md) | Configuration file support |
