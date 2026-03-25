# TODO

Feature ideas for pkgdb, ordered by priority.

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
