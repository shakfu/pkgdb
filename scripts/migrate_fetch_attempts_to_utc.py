#!/usr/bin/env python3
"""Convert pre-0.2.2 `fetch_attempts` timestamps from local time to UTC.

Before 0.2.2, `record_fetch_attempt()` stamped rows with `datetime.now()`
(local) while `get_packages_needing_update()` compared them against SQLite's
`datetime('now')` (UTC). The 24-hour cooldown therefore ran for 24 hours plus
the machine's UTC offset east of UTC, and expired early west of it.

0.2.2 writes UTC, but rows already in the database keep their local stamps and
are now read as UTC, so a machine east of UTC sees one final cooldown up to its
offset too long. This script rewrites those rows once. It is not needed on a
database created by 0.2.2 or later, and doing nothing is also a valid choice --
the next successful fetch rewrites each row correctly anyway.

Each timestamp is converted through the local zone's offset *at that
timestamp*, so a database spanning a DST change converts correctly rather than
by a single flat offset.

Run it with no arguments first: it defaults to a dry run and only reports.

    python3 scripts/migrate_fetch_attempts_to_utc.py
    python3 scripts/migrate_fetch_attempts_to_utc.py --apply

Caveat: if some rows were written by a machine in another zone -- a CI job
running the `fetch-stats.yml` workflow writes UTC, since GitHub Actions runs in
UTC -- those rows are already correct and this script would shift them wrongly.
The dry run lists every change so you can check before applying.
"""

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB = Path.home() / ".pkgdb" / "pkg.db"

# The predicate `get_packages_needing_update()` uses, so the before/after counts
# reported here are the ones that actually gate a fetch.
THROTTLED = (
    "SELECT COUNT(*) FROM fetch_attempts "
    "WHERE datetime(attempt_time) > datetime('now', '-24 hours') AND success = 1"
)


def local_to_utc(stamp: str) -> str:
    """Reinterpret a naive local timestamp as UTC.

    `astimezone()` on a naive datetime treats it as local and attaches the
    offset in force on that date, which is what makes this correct across a
    DST boundary.
    """
    naive = datetime.fromisoformat(stamp)
    return naive.astimezone().astimezone(timezone.utc).replace(tzinfo=None).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert pre-0.2.2 fetch_attempts timestamps to UTC.",
    )
    parser.add_argument(
        "-d", "--database", type=Path, default=DEFAULT_DB,
        help=f"Database to migrate (default: {DEFAULT_DB})",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Write the changes. Without this the script only reports.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Run even if this database was already migrated.",
    )
    args = parser.parse_args()

    if not args.database.exists():
        print(f"error: no database at {args.database}", file=sys.stderr)
        return 1

    # Applying twice would subtract the offset twice, so the first successful
    # run drops a marker beside the database.
    marker = args.database.with_suffix(args.database.suffix + ".utc-migrated")
    if marker.exists() and not args.force:
        print(f"Already migrated (marker: {marker}). Use --force to run anyway.")
        return 0

    conn = sqlite3.connect(args.database)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT package_name, attempt_time FROM fetch_attempts ORDER BY attempt_time"
    ).fetchall()

    if not rows:
        print("Nothing to do: fetch_attempts is empty.")
        return 0

    changes = []
    for row in rows:
        converted = local_to_utc(row["attempt_time"])
        if converted != row["attempt_time"]:
            changes.append((row["package_name"], row["attempt_time"], converted))

    throttled_before = conn.execute(THROTTLED).fetchone()[0]
    print(f"Database        : {args.database}")
    print(f"Attempt rows    : {len(rows)}")
    print(f"Rows to change  : {len(changes)}")
    print(f"Throttled now   : {throttled_before}")

    if not changes:
        print("\nAll timestamps already match UTC. Nothing to do.")
        return 0

    print("\n  package                        stored local      ->  utc")
    for name, before, after in changes:
        print(f"  {name:<30} {before[:19]}  ->  {after[:19]}")

    if not args.apply:
        print("\nDry run. Re-run with --apply to write these changes.")
        return 0

    backup = args.database.with_suffix(
        args.database.suffix + datetime.now().strftime(".backup-%Y%m%d-%H%M%S")
    )
    shutil.copy2(args.database, backup)
    print(f"\nBackup written  : {backup}")

    with conn:
        conn.executemany(
            "UPDATE fetch_attempts SET attempt_time = ? WHERE package_name = ?",
            [(after, name) for name, _, after in changes],
        )

    throttled_after = conn.execute(THROTTLED).fetchone()[0]
    marker.write_text(
        f"fetch_attempts converted from local time to UTC on "
        f"{datetime.now().isoformat(timespec='seconds')}\n"
    )
    print(f"Rows updated    : {len(changes)}")
    print(f"Throttled now   : {throttled_after} (was {throttled_before})")
    print(f"Released        : {throttled_before - throttled_after} packages")
    print("\nRun `pkgdb update` to fetch them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
