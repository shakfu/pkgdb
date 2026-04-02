# TODO

Feature ideas for pkgdb, ordered by priority.

## High Priority

### Local Interactive Dashboard
- [ ] `pkgdb serve` - launch a local web dashboard for browsing package stats
  - Use stdlib `http.server` for the web server (no Flask/FastAPI dependency)
  - Bundle lightweight JavaScript libraries in the package for interactivity (e.g., Chart.js or similar for zoomable/pannable charts, sortable tables, filtering)
  - Dashboard pages:
    - Overview: all tracked packages with sortable stats table, sparklines
    - Package detail: download history chart (zoomable), release timeline, environment breakdown
    - Comparison: side-by-side package charts
  - Live data from the SQLite database (no static HTML generation)
  - `--port` flag for custom port (default: 8080)
  - `--no-browser` flag to suppress auto-open

## Medium Priority

### Database Maintenance
- [ ] Backup/restore - `pkgdb backup` / `pkgdb restore`

### Package Discovery
- [ ] Import packages from pyproject.toml `[project]` section

### GitHub Integration (via `gh` CLI)
- [ ] Auto-discover packages from your repos (scan for pyproject.toml)
- [ ] Publish HTML report to GitHub Pages - `pkgdb publish`

### Organization
- [ ] Package groups/tags - group related packages, aggregate stats per group

## Low Priority

### Comparison Mode
- [ ] Track packages you don't own (competitors, dependencies)
- [ ] Side-by-side comparison charts

### Alerts
- [ ] Detect significant spikes or drops in downloads
- [ ] Milestones - set download targets, notify when reached

### Advanced
- [ ] Server/API mode - REST endpoint for dashboard integration
