# TODO

Feature ideas for pkglog, ordered by priority.

## High Priority

### Historical Trends
- [ ] Time-series chart showing downloads over time per package
- [ ] Growth metrics (week-over-week, month-over-month % change)
- [ ] `pkglog history <package>` command to show historical stats for one package
- [ ] Sparklines in the terminal table view

### Export Formats
- [ ] `pkglog export --format csv` for spreadsheet analysis
- [ ] `pkglog export --format json` for programmatic use
- [ ] Markdown table output for embedding in READMEs

## Medium Priority

### Richer pypistats Data
- [ ] Per-version download breakdown
- [ ] Python version distribution
- [ ] OS/platform breakdown

### Package Discovery
- [ ] `pkglog init --user <pypi-username>` to auto-populate packages.yml from PyPI account
- [ ] Import packages from pyproject.toml dependencies

### Database Maintenance
- [ ] `pkglog prune --older-than 90d` to clean old data
- [ ] Database size/stats info in `pkglog list`

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
