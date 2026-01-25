"""Export functions for various formats."""

import csv
import io
import json
from datetime import datetime
from typing import Any


def export_csv(stats: list[dict[str, Any]], output: io.StringIO | None = None) -> str:
    """Export stats to CSV format."""
    if output is None:
        output = io.StringIO()

    writer = csv.writer(output)
    writer.writerow(
        [
            "rank",
            "package_name",
            "total",
            "last_month",
            "last_week",
            "last_day",
            "fetch_date",
        ]
    )

    for i, s in enumerate(stats, 1):
        writer.writerow(
            [
                i,
                s["package_name"],
                s.get("total") or 0,
                s.get("last_month") or 0,
                s.get("last_week") or 0,
                s.get("last_day") or 0,
                s.get("fetch_date", ""),
            ]
        )

    return output.getvalue()


def export_json(stats: list[dict[str, Any]]) -> str:
    """Export stats to JSON format."""
    export_data = {
        "generated": datetime.now().isoformat(),
        "packages": [
            {
                "rank": i,
                "name": s["package_name"],
                "total": s.get("total") or 0,
                "last_month": s.get("last_month") or 0,
                "last_week": s.get("last_week") or 0,
                "last_day": s.get("last_day") or 0,
                "fetch_date": s.get("fetch_date", ""),
            }
            for i, s in enumerate(stats, 1)
        ],
    }
    return json.dumps(export_data, indent=2)


def export_markdown(stats: list[dict[str, Any]]) -> str:
    """Export stats to Markdown table format."""
    lines = [
        "| Rank | Package | Total | Month | Week | Day |",
        "|------|---------|------:|------:|-----:|----:|",
    ]

    for i, s in enumerate(stats, 1):
        lines.append(
            f"| {i} | {s['package_name']} | {s.get('total') or 0:,} | "
            f"{s.get('last_month') or 0:,} | {s.get('last_week') or 0:,} | "
            f"{s.get('last_day') or 0:,} |"
        )

    return "\n".join(lines)
