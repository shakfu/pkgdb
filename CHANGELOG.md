# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2025-01-22

### Added

- Initial release
- CLI commands: `fetch`, `list`, `report`, `update`
- SQLite database storage for historical stats
- HTML report generation with Chart.js visualizations
- YAML-based package configuration (`packages.yml`)
- Support for custom database and packages file paths
- Pytest test suite with 24 tests covering:
  - Database operations
  - Package loading from YAML
  - Statistics storage and retrieval
  - HTML report generation
  - CLI argument parsing
