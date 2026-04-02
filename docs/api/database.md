# Database Operations

Low-level SQLite operations. Most users should use `PackageStatsService` instead of calling these directly.

## Connection Management

::: pkgdb.db.get_db

::: pkgdb.db.get_db_connection

::: pkgdb.db.get_config_dir

## Schema

::: pkgdb.db.init_db

## Package Management

::: pkgdb.db.add_package

::: pkgdb.db.remove_package

::: pkgdb.db.get_packages

## Stats Storage

::: pkgdb.db.store_stats

::: pkgdb.db.store_stats_batch

::: pkgdb.db.get_latest_stats

::: pkgdb.db.get_package_history

::: pkgdb.db.get_all_history

::: pkgdb.db.get_stats_with_growth

## Environment Stats

::: pkgdb.db.store_env_stats

::: pkgdb.db.get_cached_python_versions

::: pkgdb.db.get_cached_os_stats

::: pkgdb.db.get_cached_env_summary

## Release Data

::: pkgdb.db.store_pypi_releases

::: pkgdb.db.get_pypi_releases

::: pkgdb.db.get_all_pypi_releases

::: pkgdb.db.store_github_releases

::: pkgdb.db.get_github_releases

::: pkgdb.db.get_all_github_releases

## Fetch Tracking

::: pkgdb.db.record_fetch_attempt

::: pkgdb.db.get_packages_needing_update

::: pkgdb.db.get_next_update_seconds

## Maintenance

::: pkgdb.db.cleanup_orphaned_stats

::: pkgdb.db.prune_old_stats

::: pkgdb.db.get_database_stats
