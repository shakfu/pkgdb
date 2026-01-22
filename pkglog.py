#!/usr/bin/env python3
"""
pkglog - Track PyPI package download statistics.

Reads published packages from packages.yml, fetches download statistics
via pypistats, stores data in SQLite, and generates HTML reports.
"""

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
import webbrowser

import pypistats
import yaml


DEFAULT_PACKAGES_FILE = "packages.yml"
DEFAULT_DB_FILE = "pkg.db"
DEFAULT_REPORT_FILE = "report.html"


def get_db_connection(db_path: str) -> sqlite3.Connection:
    """Create and return a database connection."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Initialize the database schema."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS package_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            package_name TEXT NOT NULL,
            fetch_date TEXT NOT NULL,
            last_day INTEGER,
            last_week INTEGER,
            last_month INTEGER,
            total INTEGER,
            UNIQUE(package_name, fetch_date)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_package_name
        ON package_stats(package_name)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_fetch_date
        ON package_stats(fetch_date)
    """)
    conn.commit()


def load_packages(packages_file: str) -> list[str]:
    """Load published packages from YAML file."""
    with open(packages_file) as f:
        data = yaml.safe_load(f)
    return data.get("published", [])


def fetch_package_stats(package_name: str) -> dict:
    """Fetch download statistics for a package from PyPI."""
    try:
        recent_json = pypistats.recent(package_name, format="json")
        recent_data = json.loads(recent_json)

        data = recent_data.get("data", {})
        stats = {
            "last_day": data.get("last_day", 0),
            "last_week": data.get("last_week", 0),
            "last_month": data.get("last_month", 0),
        }

        overall_json = pypistats.overall(package_name, format="json")
        overall_data = json.loads(overall_json)

        total = 0
        for item in overall_data.get("data", []):
            if item.get("category") == "without_mirrors":
                total = item.get("downloads", 0)
                break
        stats["total"] = total

        return stats
    except Exception as e:
        print(f"  Error fetching stats for {package_name}: {e}")
        return None


def store_stats(conn: sqlite3.Connection, package_name: str, stats: dict) -> None:
    """Store package statistics in the database."""
    fetch_date = datetime.now().strftime("%Y-%m-%d")
    conn.execute("""
        INSERT OR REPLACE INTO package_stats
        (package_name, fetch_date, last_day, last_week, last_month, total)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        package_name,
        fetch_date,
        stats.get("last_day"),
        stats.get("last_week"),
        stats.get("last_month"),
        stats.get("total"),
    ))
    conn.commit()


def get_latest_stats(conn: sqlite3.Connection) -> list[dict]:
    """Get the most recent stats for all packages, ordered by total downloads."""
    cursor = conn.execute("""
        SELECT ps.*
        FROM package_stats ps
        INNER JOIN (
            SELECT package_name, MAX(fetch_date) as max_date
            FROM package_stats
            GROUP BY package_name
        ) latest ON ps.package_name = latest.package_name
                AND ps.fetch_date = latest.max_date
        ORDER BY ps.total DESC
    """)
    return [dict(row) for row in cursor.fetchall()]


def generate_html_report(stats: list[dict], output_file: str) -> None:
    """Generate an HTML report with charts."""
    if not stats:
        print("No statistics available to generate report.")
        return

    package_names = [s["package_name"] for s in stats]
    totals = [s["total"] or 0 for s in stats]
    last_month = [s["last_month"] or 0 for s in stats]
    last_week = [s["last_week"] or 0 for s in stats]
    last_day = [s["last_day"] or 0 for s in stats]

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PyPI Package Download Statistics</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }}
        h1, h2 {{
            color: #333;
        }}
        .chart-container {{
            background: white;
            border-radius: 8px;
            padding: 20px;
            margin: 20px 0;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            background: white;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #eee;
        }}
        th {{
            background: #4a90a4;
            color: white;
        }}
        tr:hover {{
            background: #f9f9f9;
        }}
        .number {{
            text-align: right;
            font-family: monospace;
        }}
        .generated {{
            color: #666;
            font-size: 0.9em;
            margin-top: 20px;
        }}
    </style>
</head>
<body>
    <h1>PyPI Package Download Statistics</h1>

    <div class="chart-container">
        <h2>Total Downloads by Package</h2>
        <canvas id="totalChart"></canvas>
    </div>

    <div class="chart-container">
        <h2>Recent Downloads (Last Month)</h2>
        <canvas id="monthChart"></canvas>
    </div>

    <h2>Detailed Statistics</h2>
    <table>
        <thead>
            <tr>
                <th>Rank</th>
                <th>Package</th>
                <th class="number">Total</th>
                <th class="number">Last Month</th>
                <th class="number">Last Week</th>
                <th class="number">Last Day</th>
            </tr>
        </thead>
        <tbody>
"""

    for i, s in enumerate(stats, 1):
        html += f"""            <tr>
                <td>{i}</td>
                <td><a href="https://pypi.org/project/{s['package_name']}/">{s['package_name']}</a></td>
                <td class="number">{s['total'] or 0:,}</td>
                <td class="number">{s['last_month'] or 0:,}</td>
                <td class="number">{s['last_week'] or 0:,}</td>
                <td class="number">{s['last_day'] or 0:,}</td>
            </tr>
"""

    html += f"""        </tbody>
    </table>

    <p class="generated">Generated on {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>

    <script>
        const packageNames = {json.dumps(package_names)};
        const totals = {json.dumps(totals)};
        const lastMonth = {json.dumps(last_month)};

        const colors = packageNames.map((_, i) =>
            `hsl(${{(i * 360 / packageNames.length) % 360}}, 70%, 50%)`
        );

        new Chart(document.getElementById('totalChart'), {{
            type: 'bar',
            data: {{
                labels: packageNames,
                datasets: [{{
                    label: 'Total Downloads',
                    data: totals,
                    backgroundColor: colors,
                }}]
            }},
            options: {{
                responsive: true,
                plugins: {{
                    legend: {{ display: false }}
                }},
                scales: {{
                    y: {{ beginAtZero: true }}
                }}
            }}
        }});

        new Chart(document.getElementById('monthChart'), {{
            type: 'bar',
            data: {{
                labels: packageNames,
                datasets: [{{
                    label: 'Last Month',
                    data: lastMonth,
                    backgroundColor: colors,
                }}]
            }},
            options: {{
                responsive: true,
                plugins: {{
                    legend: {{ display: false }}
                }},
                scales: {{
                    y: {{ beginAtZero: true }}
                }}
            }}
        }});
    </script>
</body>
</html>
"""

    with open(output_file, "w") as f:
        f.write(html)
    print(f"Report generated: {output_file}")


def cmd_fetch(args) -> None:
    """Fetch command: download stats and store in database."""
    packages = load_packages(args.packages)
    print(f"Loaded {len(packages)} packages from {args.packages}")

    conn = get_db_connection(args.database)
    init_db(conn)

    for package in packages:
        print(f"Fetching stats for {package}...")
        stats = fetch_package_stats(package)
        if stats:
            store_stats(conn, package, stats)
            print(f"  Total: {stats['total']:,} | Month: {stats['last_month']:,} | "
                  f"Week: {stats['last_week']:,} | Day: {stats['last_day']:,}")

    conn.close()
    print("Done.")


def cmd_report(args) -> None:
    """Report command: generate HTML report from stored data."""
    conn = get_db_connection(args.database)
    init_db(conn)

    stats = get_latest_stats(conn)
    conn.close()

    if not stats:
        print("No data in database. Run 'fetch' first.")
        return

    generate_html_report(stats, args.output)
    print("opening...")
    webbrowser.open_new_tab(Path(args.output).resolve().as_uri())


def cmd_update(args) -> None:
    """Sync command: fetch stats then generate report."""
    cmd_fetch(args)
    cmd_report(args)


def cmd_list(args) -> None:
    """List command: show stored statistics."""
    conn = get_db_connection(args.database)
    init_db(conn)

    stats = get_latest_stats(conn)
    conn.close()

    if not stats:
        print("No data in database. Run 'fetch' first.")
        return

    print(f"{'Rank':<5} {'Package':<25} {'Total':>12} {'Month':>10} "
          f"{'Week':>10} {'Day':>8}")
    print("-" * 75)

    for i, s in enumerate(stats, 1):
        print(f"{i:<5} {s['package_name']:<25} {s['total'] or 0:>12,} "
              f"{s['last_month'] or 0:>10,} {s['last_week'] or 0:>10,} "
              f"{s['last_day'] or 0:>8,}")


def main():
    parser = argparse.ArgumentParser(
        description="Track PyPI package download statistics.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-d", "--database",
        default=DEFAULT_DB_FILE,
        help=f"SQLite database file (default: {DEFAULT_DB_FILE})",
    )
    parser.add_argument(
        "-p", "--packages",
        default=DEFAULT_PACKAGES_FILE,
        help=f"Packages YAML file (default: {DEFAULT_PACKAGES_FILE})",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # fetch command
    fetch_parser = subparsers.add_parser(
        "fetch",
        help="Fetch download statistics from PyPI",
    )
    fetch_parser.set_defaults(func=cmd_fetch)

    # report command
    report_parser = subparsers.add_parser(
        "report",
        help="Generate HTML report with charts",
    )
    report_parser.add_argument(
        "-o", "--output",
        default=DEFAULT_REPORT_FILE,
        help=f"Output HTML file (default: {DEFAULT_REPORT_FILE})",
    )
    report_parser.set_defaults(func=cmd_report)

    # list command
    list_parser = subparsers.add_parser(
        "list",
        help="List stored statistics",
    )
    list_parser.set_defaults(func=cmd_list)

    # update command
    update_parser = subparsers.add_parser(
        "update",
        help="Fetch stats and generate report",
    )
    update_parser.add_argument(
        "-o", "--output",
        default=DEFAULT_REPORT_FILE,
        help=f"Output HTML file (default: {DEFAULT_REPORT_FILE})",
    )
    update_parser.set_defaults(func=cmd_update)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    args.func(args)


if __name__ == "__main__":
    main()
