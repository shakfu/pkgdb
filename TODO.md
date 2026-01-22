# TODO

Feature ideas for pkglog, ordered by priority.

## High Priority

### Historical Trends
- [x] Time-series chart showing downloads over time per package
- [x] Growth metrics (week-over-week, month-over-month % change)
- [x] `pkglog history <package>` command to show historical stats for one package
- [x] Sparklines in the terminal table view

### Export Formats
- [x] `pkglog export --format csv` for spreadsheet analysis
- [x] `pkglog export --format json` for programmatic use
- [x] Markdown table output for embedding in READMEs

## Medium Priority

### Richer pypistats Data
- [ ] Per-version download breakdown (not available via pypistats API)
- [x] Python version distribution
- [x] OS/platform breakdown

### Database Maintenance
- [ ] `pkglog prune --older-than 90d` to clean old data
- [ ] Database size/stats info in `pkglog list`

### Package Discovery
- [ ] `pkglog init --user <pypi-username>` to auto-populate packages.yml from PyPI account
- [ ] Import packages from pyproject.toml dependencies

## Low Priority

### Comparison Mode
- [ ] Track packages you don't own (competitors, dependencies)
- [ ] Separate `watched` key in packages.yml
- [ ] Side-by-side comparison charts

### Alerts
- [ ] Detect significant spikes or drops in downloads
- [ ] Weekly digest summary
- [ ] Email notification support
- [ ] Webhook support (Slack, Discord, generic)
