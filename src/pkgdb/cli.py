"""CLI argument parsing and command implementations."""

import argparse
import json
from pathlib import Path
from typing import Any
import webbrowser

import yaml
from tabulate import tabulate

from .api import aggregate_env_stats, fetch_package_stats
from .db import (
    DEFAULT_DB_FILE,
    DEFAULT_REPORT_FILE,
    add_package,
    get_all_history,
    get_db,
    get_latest_stats,
    get_package_history,
    get_packages,
    get_stats_with_growth,
    remove_package,
    store_stats,
)
from .export import export_csv, export_json, export_markdown
from .reports import generate_html_report, generate_package_html_report
from .utils import make_sparkline


DEFAULT_PACKAGES_FILE = "packages.yml"


def load_packages(packages_file: str) -> list[str]:
    """Load published packages from YAML file."""
    with open(packages_file) as f:
        data = yaml.safe_load(f)
    result: list[str] = data.get("published", [])
    return result


def load_packages_from_file(file_path: str) -> list[str]:
    """Load package names from a file (YAML, JSON, or plain text).

    Supports:
    - YAML (.yml, .yaml): expects 'published' key with list of packages
    - JSON (.json): expects list of strings or object with 'packages'/'published' key
    - Plain text: one package name per line (comments with # supported)
    """
    path = Path(file_path)
    suffix = path.suffix.lower()

    with open(file_path) as f:
        content = f.read()

    if suffix in (".yml", ".yaml"):
        data = yaml.safe_load(content)
        if isinstance(data, dict):
            return data.get("published", []) or data.get("packages", []) or []
        return []

    if suffix == ".json":
        data = json.loads(content)
        if isinstance(data, list):
            return [str(p) for p in data]
        if isinstance(data, dict):
            return data.get("packages", []) or data.get("published", []) or []
        return []

    # Plain text: one package per line, strip whitespace, skip empty/comments
    packages = []
    for line in content.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            packages.append(line)
    return packages


def import_packages_from_file(conn: Any, file_path: str) -> tuple[int, int]:
    """Import packages from a file into the database.

    Supports YAML, JSON, and plain text formats.
    Returns tuple of (added_count, skipped_count).
    """
    packages = load_packages_from_file(file_path)
    added = 0
    skipped = 0
    for pkg in packages:
        if add_package(conn, pkg):
            added += 1
        else:
            skipped += 1
    return added, skipped


def cmd_fetch(args: argparse.Namespace) -> None:
    """Fetch command: download stats and store in database."""
    with get_db(args.database) as conn:
        packages = get_packages(conn)
        if not packages:
            print("No packages are being tracked.")
            print(
                "Add packages with 'pkgdb add <name>' or import from YAML with 'pkgdb import'."
            )
            return

        total = len(packages)
        print(f"Fetching stats for {total} tracked packages...")

        for i, package in enumerate(packages, 1):
            print(f"[{i}/{total}] Fetching stats for {package}...")
            stats = fetch_package_stats(package)
            if stats:
                store_stats(conn, package, stats)
                print(
                    f"  Total: {stats['total']:,} | Month: {stats['last_month']:,} | "
                    f"Week: {stats['last_week']:,} | Day: {stats['last_day']:,}"
                )

        print("Done.")


def cmd_report(args: argparse.Namespace) -> None:
    """Report command: generate HTML report from stored data.

    If a package name is provided, generates a detailed report for that package.
    Otherwise, generates a summary report for all packages.
    """
    # Check if single-package report requested
    package = getattr(args, "package", None)
    no_browser = getattr(args, "no_browser", False)

    with get_db(args.database) as conn:
        if package:
            # Single package detailed report
            pkg_history = get_package_history(conn, package, limit=30)

            # Find stats in database or fetch fresh
            pkg_stats: dict[str, Any] | None = None
            for h in pkg_history:
                if h["package_name"] == package:
                    pkg_stats = {
                        "total": h["total"],
                        "last_month": h["last_month"],
                        "last_week": h["last_week"],
                        "last_day": h["last_day"],
                    }
                    break

            generate_package_html_report(
                package, args.output, stats=pkg_stats, history=pkg_history
            )
        else:
            # Summary report for all packages
            stats = get_latest_stats(conn)
            all_history = get_all_history(conn, limit_per_package=30)
            packages = [s["package_name"] for s in stats]

            if not stats:
                print("No data in database. Run 'fetch' first.")
                return

            # Fetch environment summary (aggregated across all packages)
            env_summary: dict[str, list[tuple[str, int]]] | None = None
            if args.env:
                print("Fetching environment data (this may take a moment)...")
                env_summary = aggregate_env_stats(packages)

            generate_html_report(stats, args.output, all_history, packages, env_summary)

    if not no_browser:
        print("Opening report in browser...")
        webbrowser.open_new_tab(Path(args.output).resolve().as_uri())


def cmd_update(args: argparse.Namespace) -> None:
    """Sync command: fetch stats then generate report."""
    cmd_fetch(args)
    # Ensure env attribute exists for cmd_report
    if not hasattr(args, "env"):
        args.env = False
    cmd_report(args)


def cmd_show(args: argparse.Namespace) -> None:
    """Show command: display stored statistics in terminal."""
    with get_db(args.database) as conn:
        stats = get_stats_with_growth(conn)
        history = get_all_history(conn, limit_per_package=14)

        if not stats:
            print("No data in database. Run 'fetch' first.")
            return

        rows = []
        for i, s in enumerate(stats, 1):
            pkg = s["package_name"]
            pkg_history = history.get(pkg, [])
            totals = [h["total"] or 0 for h in pkg_history]
            sparkline = make_sparkline(totals, width=7)

            growth_str = ""
            if s.get("month_growth") is not None:
                g = s["month_growth"]
                sign = "+" if g >= 0 else ""
                growth_str = f"{sign}{g:.1f}%"

            rows.append(
                [
                    i,
                    pkg,
                    f"{s['total'] or 0:,}",
                    f"{s['last_month'] or 0:,}",
                    f"{s['last_week'] or 0:,}",
                    f"{s['last_day'] or 0:,}",
                    sparkline,
                    growth_str,
                ]
            )

        headers = ["#", "Package", "Total", "Month", "Week", "Day", "Trend", "Growth"]
        print(tabulate(rows, headers=headers, tablefmt="simple"))


def cmd_list(args: argparse.Namespace) -> None:
    """List command: show tracked packages."""
    with get_db(args.database) as conn:
        packages = get_packages(conn)

        if not packages:
            print("No packages are being tracked.")
            print(
                "Add packages with 'pkgdb add <name>' or import from YAML with 'pkgdb import'."
            )
            return

        # Get added dates for each package
        cursor = conn.execute(
            "SELECT package_name, added_date FROM packages ORDER BY package_name"
        )
        pkg_data = {row["package_name"]: row["added_date"] for row in cursor.fetchall()}

        print(f"Tracking {len(packages)} packages:\n")

        rows = [[pkg, pkg_data.get(pkg, "")] for pkg in packages]
        headers = ["Package", "Added"]
        print(tabulate(rows, headers=headers, tablefmt="simple"))


def cmd_add(args: argparse.Namespace) -> None:
    """Add command: add a package to tracking."""
    with get_db(args.database) as conn:
        if add_package(conn, args.name):
            print(f"Added '{args.name}' to tracking.")
        else:
            print(f"Package '{args.name}' is already being tracked.")


def cmd_remove(args: argparse.Namespace) -> None:
    """Remove command: remove a package from tracking."""
    with get_db(args.database) as conn:
        if remove_package(conn, args.name):
            print(f"Removed '{args.name}' from tracking.")
        else:
            print(f"Package '{args.name}' was not being tracked.")


def cmd_import(args: argparse.Namespace) -> None:
    """Import command: import packages from file (YAML, JSON, or text)."""
    with get_db(args.database) as conn:
        try:
            added, skipped = import_packages_from_file(conn, args.file)
            print(f"Imported {added} packages ({skipped} already tracked).")
        except FileNotFoundError:
            print(f"File not found: {args.file}")


def cmd_history(args: argparse.Namespace) -> None:
    """History command: show historical stats for a package."""
    with get_db(args.database) as conn:
        history = get_package_history(conn, args.package, limit=args.limit)

        if not history:
            print(f"No data found for package '{args.package}'.")
            return

        print(f"Historical stats for {args.package}\n")

        rows = []
        for h in reversed(history):
            rows.append(
                [
                    h["fetch_date"],
                    f"{h['total'] or 0:,}",
                    f"{h['last_month'] or 0:,}",
                    f"{h['last_week'] or 0:,}",
                    f"{h['last_day'] or 0:,}",
                ]
            )

        headers = ["Date", "Total", "Month", "Week", "Day"]
        print(tabulate(rows, headers=headers, tablefmt="simple"))


def cmd_export(args: argparse.Namespace) -> None:
    """Export command: export stats in various formats."""
    with get_db(args.database) as conn:
        stats = get_latest_stats(conn)

        if not stats:
            print("No data in database. Run 'fetch' first.")
            return

        # Generate export based on format
        if args.format == "csv":
            output = export_csv(stats)
        elif args.format == "json":
            output = export_json(stats)
        elif args.format == "markdown" or args.format == "md":
            output = export_markdown(stats)
        else:
            print(f"Unknown format: {args.format}")
            return

        # Write to file or stdout
        if args.output:
            with open(args.output, "w") as f:
                f.write(output)
            print(f"Exported to {args.output}")
        else:
            print(output)


def cmd_stats(args: argparse.Namespace) -> None:
    """Stats command: show detailed statistics for a package."""
    from .api import fetch_os_stats, fetch_python_versions

    package = args.package
    print(f"Fetching detailed stats for {package}...\n")

    # Fetch basic stats
    basic = fetch_package_stats(package)
    if basic:
        print("=== Download Summary ===")
        print(f"  Total:      {basic['total']:>12,}")
        print(f"  Last month: {basic['last_month']:>12,}")
        print(f"  Last week:  {basic['last_week']:>12,}")
        print(f"  Last day:   {basic['last_day']:>12,}")
        print()

    # Fetch Python version breakdown
    py_versions = fetch_python_versions(package)
    if py_versions:
        print("=== Python Version Distribution ===")
        total_downloads = sum(v.get("downloads", 0) for v in py_versions)
        for v in py_versions[:10]:  # Top 10
            version = v.get("category", "unknown")
            downloads = v.get("downloads", 0)
            pct = (downloads / total_downloads * 100) if total_downloads > 0 else 0
            bar = "#" * int(pct / 2)
            print(f"  Python {version:<6} {downloads:>12,} ({pct:>5.1f}%) {bar}")
        print()

    # Fetch OS breakdown
    os_stats = fetch_os_stats(package)
    if os_stats:
        print("=== Operating System Distribution ===")
        total_downloads = sum(s.get("downloads", 0) for s in os_stats)
        for s in os_stats:
            os_name = s.get("category", "unknown")
            if os_name == "null":
                os_name = "Unknown"
            downloads = s.get("downloads", 0)
            pct = (downloads / total_downloads * 100) if total_downloads > 0 else 0
            bar = "#" * int(pct / 2)
            print(f"  {os_name:<10} {downloads:>12,} ({pct:>5.1f}%) {bar}")
        print()


def create_parser() -> argparse.ArgumentParser:
    """Create and configure the argument parser."""
    parser = argparse.ArgumentParser(
        description="Track PyPI package download statistics.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-d",
        "--database",
        default=DEFAULT_DB_FILE,
        help=f"SQLite database file (default: {DEFAULT_DB_FILE})",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # add command
    add_parser = subparsers.add_parser(
        "add",
        help="Add a package to tracking",
    )
    add_parser.add_argument(
        "name",
        help="Package name to add",
    )
    add_parser.set_defaults(func=cmd_add)

    # remove command
    remove_parser = subparsers.add_parser(
        "remove",
        help="Remove a package from tracking",
    )
    remove_parser.add_argument(
        "name",
        help="Package name to remove",
    )
    remove_parser.set_defaults(func=cmd_remove)

    # list command
    list_parser = subparsers.add_parser(
        "list",
        help="List tracked packages",
    )
    list_parser.set_defaults(func=cmd_list)

    # import command
    import_parser = subparsers.add_parser(
        "import",
        help="Import packages from file (YAML, JSON, or text)",
    )
    import_parser.add_argument(
        "file",
        nargs="?",
        default=DEFAULT_PACKAGES_FILE,
        help=f"File to import from - supports .yml, .json, or plain text (default: {DEFAULT_PACKAGES_FILE})",
    )
    import_parser.set_defaults(func=cmd_import)

    # fetch command
    fetch_parser = subparsers.add_parser(
        "fetch",
        help="Fetch download statistics from PyPI for tracked packages",
    )
    fetch_parser.set_defaults(func=cmd_fetch)

    # show command (was 'list')
    show_parser = subparsers.add_parser(
        "show",
        help="Display download stats in terminal",
    )
    show_parser.set_defaults(func=cmd_show)

    # report command
    report_parser = subparsers.add_parser(
        "report",
        help="Generate HTML report with charts",
    )
    report_parser.add_argument(
        "package",
        nargs="?",
        help="Package name for detailed single-package report (optional)",
    )
    report_parser.add_argument(
        "-o",
        "--output",
        default=DEFAULT_REPORT_FILE,
        help=f"Output HTML file (default: {DEFAULT_REPORT_FILE})",
    )
    report_parser.add_argument(
        "-e",
        "--env",
        action="store_true",
        help="Include environment summary (Python versions, OS) in report",
    )
    report_parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't open report in browser (useful for automation)",
    )
    report_parser.set_defaults(func=cmd_report)

    # history command
    history_parser = subparsers.add_parser(
        "history",
        help="Show historical stats for a package",
    )
    history_parser.add_argument(
        "package",
        help="Package name to show history for",
    )
    history_parser.add_argument(
        "-n",
        "--limit",
        type=int,
        default=30,
        help="Number of days to show (default: 30)",
    )
    history_parser.set_defaults(func=cmd_history)

    # stats command
    stats_parser = subparsers.add_parser(
        "stats",
        help="Show detailed stats for a package (Python versions, OS breakdown)",
    )
    stats_parser.add_argument(
        "package",
        help="Package name to show detailed stats for",
    )
    stats_parser.set_defaults(func=cmd_stats)

    # export command
    export_parser = subparsers.add_parser(
        "export",
        help="Export stats in various formats (csv, json, markdown)",
    )
    export_parser.add_argument(
        "-f",
        "--format",
        choices=["csv", "json", "markdown", "md"],
        default="csv",
        help="Export format (default: csv)",
    )
    export_parser.add_argument(
        "-o",
        "--output",
        help="Output file (default: stdout)",
    )
    export_parser.set_defaults(func=cmd_export)

    # update command
    update_parser = subparsers.add_parser(
        "update",
        help="Fetch stats and generate report",
    )
    update_parser.add_argument(
        "-o",
        "--output",
        default=DEFAULT_REPORT_FILE,
        help=f"Output HTML file (default: {DEFAULT_REPORT_FILE})",
    )
    update_parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't open report in browser (useful for automation)",
    )
    update_parser.set_defaults(func=cmd_update)

    return parser


def main() -> None:
    """Main entry point for the CLI."""
    parser = create_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    args.func(args)
