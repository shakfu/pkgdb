"""HTML report generation with SVG charts."""

import logging
import math
from datetime import datetime
from typing import Any

from .api import fetch_os_stats, fetch_python_versions
from .types import CategoryDownloads, EnvSummary, PackageStats

logger = logging.getLogger("pkgdb")

# -----------------------------------------------------------------------------
# Theme and Chart Constants
# -----------------------------------------------------------------------------

# Primary theme color (used for links, accents, chart elements)
THEME_PRIMARY_COLOR = "#4a90a4"

# Chart dimensions
DEFAULT_BAR_CHART_WIDTH = 600
DEFAULT_BAR_CHART_HEIGHT = 300
DEFAULT_LINE_CHART_WIDTH = 600
DEFAULT_LINE_CHART_HEIGHT = 200
DEFAULT_PIE_CHART_SIZE = 220

# Pie chart limits
PIE_CHART_MAX_ITEMS = 6  # Maximum slices before grouping into "Other"

# Line chart limits
LINE_CHART_MAX_SERIES = 5  # Maximum number of packages to show in multi-line chart


# -----------------------------------------------------------------------------
# CSS Styles
# -----------------------------------------------------------------------------


def _get_common_styles() -> str:
    """Return CSS styles shared by all reports."""
    return f"""
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }}
        h1, h2, h3 {{
            color: #333;
        }}
        .chart-container {{
            background: white;
            border-radius: 8px;
            padding: 20px;
            margin: 20px 0;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            overflow-x: auto;
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
            background: {THEME_PRIMARY_COLOR};
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
        .pie-charts-row {{
            display: flex;
            flex-wrap: wrap;
            gap: 40px;
            justify-content: flex-start;
        }}
        .pie-chart-wrapper {{
            flex: 0 0 auto;
        }}
        .pie-chart-wrapper h3 {{
            margin: 0 0 10px 0;
            font-size: 14px;
            color: #555;
        }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 20px;
            margin: 20px 0;
        }}
        .stat-card {{
            background: white;
            border-radius: 8px;
            padding: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            text-align: center;
        }}
        .stat-value {{
            font-size: 24px;
            font-weight: bold;
            color: {THEME_PRIMARY_COLOR};
        }}
        .stat-label {{
            font-size: 12px;
            color: #666;
            margin-top: 5px;
        }}
        a {{
            color: {THEME_PRIMARY_COLOR};
        }}
    """


# -----------------------------------------------------------------------------
# HTML Template
# -----------------------------------------------------------------------------


def _render_html_document(
    title: str, body_content: str, styles: str | None = None
) -> str:
    """Render a complete HTML document.

    Args:
        title: Page title.
        body_content: HTML content for the body.
        styles: Optional CSS styles. Defaults to common styles.

    Returns:
        Complete HTML document as string.
    """
    if styles is None:
        styles = _get_common_styles()

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>{styles}</style>
</head>
<body>
{body_content}
    <p class="generated">Generated on {timestamp}</p>
</body>
</html>
"""


# -----------------------------------------------------------------------------
# SVG Chart Components
# -----------------------------------------------------------------------------


def make_svg_pie_chart(
    data: list[tuple[str, int]], chart_id: str, size: int = 200
) -> str:
    """Generate an SVG pie chart."""
    if not data:
        return ""

    total = sum(v for _, v in data)
    if total == 0:
        return "<p>No data available.</p>"

    # Limit to top items, group rest as "Other"
    if len(data) > PIE_CHART_MAX_ITEMS:
        top_data = data[: PIE_CHART_MAX_ITEMS - 1]
        other_total = sum(v for _, v in data[PIE_CHART_MAX_ITEMS - 1 :])
        if other_total > 0:
            top_data.append(("Other", other_total))
        data = top_data

    cx, cy = size // 2, size // 2
    radius = size // 2 - 10
    legend_width = 150
    total_width = size + legend_width

    svg_parts = [
        f'<svg id="{chart_id}" viewBox="0 0 {total_width} {size}" '
        f'style="width:100%;max-width:{total_width}px;height:auto;font-family:system-ui,sans-serif;font-size:11px;">'
    ]

    start_angle: float = 0
    for i, (name, value) in enumerate(data):
        if value == 0:
            continue
        pct = value / total
        angle = pct * 360
        end_angle = start_angle + angle

        # Calculate arc path
        start_rad = math.radians(start_angle - 90)
        end_rad = math.radians(end_angle - 90)

        x1 = cx + radius * math.cos(start_rad)
        y1 = cy + radius * math.sin(start_rad)
        x2 = cx + radius * math.cos(end_rad)
        y2 = cy + radius * math.sin(end_rad)

        large_arc = 1 if angle > 180 else 0
        hue = (i * 360 // len(data)) % 360

        path = f"M {cx} {cy} L {x1:.1f} {y1:.1f} A {radius} {radius} 0 {large_arc} 1 {x2:.1f} {y2:.1f} Z"
        svg_parts.append(f'<path d="{path}" fill="hsl({hue}, 70%, 50%)"/>')

        # Legend item
        ly = 20 + i * 25
        svg_parts.append(
            f'<rect x="{size + 10}" y="{ly - 8}" width="12" height="12" fill="hsl({hue}, 70%, 50%)"/>'
        )
        svg_parts.append(
            f'<text x="{size + 28}" y="{ly}" fill="#333">{name} ({pct * 100:.1f}%)</text>'
        )

        start_angle = end_angle

    svg_parts.append("</svg>")
    return "\n".join(svg_parts)


def _make_svg_bar_chart(data: list[tuple[str, int]], title: str, chart_id: str) -> str:
    """Generate an SVG bar chart."""
    if not data:
        return ""

    max_val = max(v for _, v in data) or 1
    bar_height = 28
    bar_gap = 6
    label_width = 160
    value_width = 80
    chart_width = 700
    bar_area_width = chart_width - label_width - value_width
    chart_height = len(data) * (bar_height + bar_gap) + 20

    svg_parts = [
        f'<svg id="{chart_id}" viewBox="0 0 {chart_width} {chart_height}" '
        f'style="width:100%;max-width:{chart_width}px;height:auto;font-family:system-ui,sans-serif;font-size:12px;">'
    ]

    for i, (name, value) in enumerate(data):
        y = i * (bar_height + bar_gap) + 10
        bar_width = (value / max_val) * bar_area_width if max_val > 0 else 0
        hue = (i * 360 // len(data)) % 360

        # Label
        svg_parts.append(
            f'<text x="{label_width - 8}" y="{y + bar_height // 2 + 4}" '
            f'text-anchor="end" fill="#333">{name}</text>'
        )
        # Bar
        svg_parts.append(
            f'<rect x="{label_width}" y="{y}" width="{bar_width:.1f}" '
            f'height="{bar_height}" fill="hsl({hue}, 70%, 50%)" rx="3"/>'
        )
        # Value
        svg_parts.append(
            f'<text x="{label_width + bar_area_width + 8}" y="{y + bar_height // 2 + 4}" '
            f'fill="#666">{value:,}</text>'
        )

    svg_parts.append("</svg>")
    return "\n".join(svg_parts)


def _make_single_line_chart(
    dates: list[str],
    values: list[int],
    chart_width: int = 600,
    chart_height: int = 200,
    color: str = "hsl(200, 70%, 50%)",
) -> str:
    """Generate an SVG line chart for a single data series.

    Args:
        dates: List of date strings for x-axis.
        values: List of values for y-axis.
        chart_width: Width of the chart in pixels.
        chart_height: Height of the chart in pixels.
        color: Line color (CSS color string).

    Returns:
        SVG string, or empty string if insufficient data.
    """
    if len(dates) < 2 or len(values) < 2:
        return ""

    margin = {"top": 20, "right": 20, "bottom": 40, "left": 80}
    plot_width = chart_width - margin["left"] - margin["right"]
    plot_height = chart_height - margin["top"] - margin["bottom"]
    max_val = max(values) or 1

    svg_parts = [
        f'<svg viewBox="0 0 {chart_width} {chart_height}" '
        f'style="width:100%;max-width:{chart_width}px;height:auto;font-family:system-ui,sans-serif;font-size:11px;">'
    ]

    # Y-axis labels and grid lines
    for i in range(5):
        y_val = max_val * (4 - i) / 4
        y_pos = margin["top"] + (i * plot_height / 4)
        svg_parts.append(
            f'<text x="{margin["left"] - 8}" y="{y_pos + 4}" '
            f'text-anchor="end" fill="#666">{int(y_val):,}</text>'
        )
        svg_parts.append(
            f'<line x1="{margin["left"]}" y1="{y_pos}" '
            f'x2="{chart_width - margin["right"]}" y2="{y_pos}" '
            f'stroke="#eee" stroke-width="1"/>'
        )

    # X-axis labels (first, middle, last)
    for idx in [0, len(dates) // 2, len(dates) - 1]:
        x_pos = margin["left"] + (idx / (len(dates) - 1)) * plot_width
        svg_parts.append(
            f'<text x="{x_pos}" y="{chart_height - 10}" '
            f'text-anchor="middle" fill="#666">{dates[idx]}</text>'
        )

    # Line
    points = []
    for i, val in enumerate(values):
        x = margin["left"] + (i / max(1, len(values) - 1)) * plot_width
        y = margin["top"] + plot_height - (val / max_val) * plot_height
        points.append(f"{x:.1f},{y:.1f}")

    svg_parts.append(
        f'<polyline points="{" ".join(points)}" '
        f'fill="none" stroke="{color}" stroke-width="2"/>'
    )
    svg_parts.append("</svg>")

    return "\n".join(svg_parts)


def _make_multi_line_chart(
    history_data: dict[str, list[dict[str, Any]]] | None,
    chart_id: str,
    max_lines: int = LINE_CHART_MAX_SERIES,
) -> str:
    """Generate an SVG line chart showing multiple packages over time.

    Args:
        history_data: Dict mapping package names to their history records.
        chart_id: SVG element ID.
        max_lines: Maximum number of packages to show (default: LINE_CHART_MAX_SERIES).

    Returns:
        SVG string, or message if insufficient data.
    """
    if not history_data:
        return ""

    # Collect all dates and find date range
    all_dates: set[str] = set()
    for pkg_history in history_data.values():
        for h in pkg_history:
            all_dates.add(h["fetch_date"])

    if not all_dates:
        return ""

    sorted_dates = sorted(all_dates)
    if len(sorted_dates) < 2:
        return "<p>Not enough historical data for time-series chart.</p>"

    chart_width = 700
    chart_height = 300
    margin = {"top": 20, "right": 120, "bottom": 40, "left": 80}
    plot_width = chart_width - margin["left"] - margin["right"]
    plot_height = chart_height - margin["top"] - margin["bottom"]

    # Find max value across all packages
    max_val = 0
    for pkg_history in history_data.values():
        for h in pkg_history:
            max_val = max(max_val, h["total"] or 0)
    max_val = max_val or 1

    svg_parts = [
        f'<svg id="{chart_id}" viewBox="0 0 {chart_width} {chart_height}" '
        f'style="width:100%;max-width:{chart_width}px;height:auto;font-family:system-ui,sans-serif;font-size:11px;">'
    ]

    # Draw axes
    svg_parts.append(
        f'<line x1="{margin["left"]}" y1="{margin["top"]}" '
        f'x2="{margin["left"]}" y2="{chart_height - margin["bottom"]}" '
        f'stroke="#ccc" stroke-width="1"/>'
    )
    svg_parts.append(
        f'<line x1="{margin["left"]}" y1="{chart_height - margin["bottom"]}" '
        f'x2="{chart_width - margin["right"]}" y2="{chart_height - margin["bottom"]}" '
        f'stroke="#ccc" stroke-width="1"/>'
    )

    # Draw Y-axis labels
    for i in range(5):
        y_val = max_val * (4 - i) / 4
        y_pos = margin["top"] + (i * plot_height / 4)
        svg_parts.append(
            f'<text x="{margin["left"] - 8}" y="{y_pos + 4}" '
            f'text-anchor="end" fill="#666">{int(y_val):,}</text>'
        )
        svg_parts.append(
            f'<line x1="{margin["left"]}" y1="{y_pos}" '
            f'x2="{chart_width - margin["right"]}" y2="{y_pos}" '
            f'stroke="#eee" stroke-width="1"/>'
        )

    # Draw X-axis labels (show first, middle, last dates)
    date_positions = [0, len(sorted_dates) // 2, len(sorted_dates) - 1]
    for idx in date_positions:
        if idx < len(sorted_dates):
            x_pos = margin["left"] + (idx / max(1, len(sorted_dates) - 1)) * plot_width
            svg_parts.append(
                f'<text x="{x_pos}" y="{chart_height - margin["bottom"] + 16}" '
                f'text-anchor="middle" fill="#666">{sorted_dates[idx]}</text>'
            )

    # Draw lines for top packages by total
    top_packages = sorted(
        history_data.keys(),
        key=lambda p: max((h["total"] or 0) for h in history_data[p]),
        reverse=True,
    )[:max_lines]

    for pkg_idx, pkg in enumerate(top_packages):
        pkg_history = sorted(history_data[pkg], key=lambda h: h["fetch_date"])
        hue = (pkg_idx * 360 // len(top_packages)) % 360
        color = f"hsl({hue}, 70%, 50%)"

        # Build path
        points = []
        for h in pkg_history:
            date_idx = sorted_dates.index(h["fetch_date"])
            x = margin["left"] + (date_idx / max(1, len(sorted_dates) - 1)) * plot_width
            y = (
                margin["top"]
                + plot_height
                - ((h["total"] or 0) / max_val) * plot_height
            )
            points.append(f"{x:.1f},{y:.1f}")

        if points:
            svg_parts.append(
                f'<polyline points="{" ".join(points)}" '
                f'fill="none" stroke="{color}" stroke-width="2"/>'
            )

            # Add label at end
            last_x = (
                margin["left"]
                + ((len(sorted_dates) - 1) / max(1, len(sorted_dates) - 1)) * plot_width
            )
            last_h = pkg_history[-1]
            last_y = (
                margin["top"]
                + plot_height
                - ((last_h["total"] or 0) / max_val) * plot_height
            )
            svg_parts.append(
                f'<text x="{last_x + 8}" y="{last_y + 4}" fill="{color}">{pkg}</text>'
            )

    svg_parts.append("</svg>")
    return "\n".join(svg_parts)


# -----------------------------------------------------------------------------
# Environment Charts Helper
# -----------------------------------------------------------------------------


def _build_env_charts(
    py_versions: list[CategoryDownloads] | None,
    os_stats: list[CategoryDownloads] | None,
    size: int = 220,
) -> tuple[str, str]:
    """Build pie charts for Python versions and OS distribution.

    Args:
        py_versions: Python version data from API.
        os_stats: OS stats data from API.
        size: Pie chart size in pixels.

    Returns:
        Tuple of (py_version_chart_html, os_chart_html).
    """
    py_version_chart = ""
    if py_versions:
        py_data = [
            (v.get("category", "unknown"), v.get("downloads", 0))
            for v in py_versions
            if v.get("category") and v.get("category") != "null"
        ]
        py_version_chart = make_svg_pie_chart(py_data, "py-version-chart", size=size)

    os_chart = ""
    if os_stats:
        os_data = []
        for s in os_stats:
            name = s.get("category", "unknown")
            if name == "null":
                name = "Unknown"
            os_data.append((name, s.get("downloads", 0)))
        os_chart = make_svg_pie_chart(os_data, "os-chart", size=size)

    return py_version_chart, os_chart


# -----------------------------------------------------------------------------
# Public Report Generation Functions
# -----------------------------------------------------------------------------


def generate_html_report(
    stats: list[dict[str, Any]],
    output_file: str,
    history: dict[str, list[dict[str, Any]]] | None = None,
    packages: list[str] | None = None,
    env_summary: EnvSummary | None = None,
) -> None:
    """Generate a self-contained HTML report with inline SVG charts.

    Args:
        stats: List of package statistics
        output_file: Path to write HTML file
        history: Historical data for time-series chart
        packages: List of package names (unused, kept for compatibility)
        env_summary: Pre-fetched Python version and OS summary data
    """
    if not stats:
        logger.warning("No statistics available to generate report.")
        return

    # Build charts
    totals_data = [(s["package_name"], s["total"] or 0) for s in stats]
    month_data = sorted(
        [(s["package_name"], s["last_month"] or 0) for s in stats],
        key=lambda x: x[1],
        reverse=True,
    )
    day_data = sorted(
        [(s["package_name"], s["last_day"] or 0) for s in stats],
        key=lambda x: x[1],
        reverse=True,
    )

    totals_chart = _make_svg_bar_chart(totals_data, "Total Downloads", "totals-chart")
    month_chart = _make_svg_bar_chart(month_data, "Last Month", "month-chart")
    day_chart = _make_svg_bar_chart(day_data, "Last Day", "day-chart")
    time_series_chart = (
        _make_multi_line_chart(history, "time-series-chart") if history else ""
    )

    # Environment summary charts
    env_summary_html = ""
    if env_summary:
        py_data = env_summary.get("python_versions", [])
        os_data = env_summary.get("os_distribution", [])
        py_chart = (
            make_svg_pie_chart(py_data, "py-version-chart", size=200) if py_data else ""
        )
        os_chart = make_svg_pie_chart(os_data, "os-chart", size=200) if os_data else ""

        if py_chart or os_chart:
            env_summary_html = f"""
    <div class="chart-container">
        <h2>Environment Summary (Aggregated)</h2>
        <div class="pie-charts-row">
            {f'<div class="pie-chart-wrapper"><h3>Python Versions</h3>{py_chart}</div>' if py_chart else ""}
            {f'<div class="pie-chart-wrapper"><h3>Operating Systems</h3>{os_chart}</div>' if os_chart else ""}
        </div>
    </div>
"""

    # Build stats table rows
    table_rows = ""
    for i, s in enumerate(stats, 1):
        table_rows += f"""            <tr>
                <td>{i}</td>
                <td><a href="https://pypi.org/project/{s["package_name"]}/">{s["package_name"]}</a></td>
                <td class="number">{s["total"] or 0:,}</td>
                <td class="number">{s["last_month"] or 0:,}</td>
                <td class="number">{s["last_week"] or 0:,}</td>
                <td class="number">{s["last_day"] or 0:,}</td>
            </tr>
"""

    # Build body content
    body_content = f"""    <h1>PyPI Package Download Statistics</h1>

    <div class="chart-container">
        <h2>Total Downloads by Package</h2>
        {totals_chart}
    </div>

    <div class="chart-container">
        <h2>Recent Downloads (Last Month)</h2>
        {month_chart}
    </div>

    <div class="chart-container">
        <h2>Recent Downloads (Last Day)</h2>
        {day_chart}
    </div>

    {f'<div class="chart-container"><h2>Downloads Over Time (Top 5)</h2>{time_series_chart}</div>' if time_series_chart else ""}

    {env_summary_html}

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
{table_rows}        </tbody>
    </table>
"""

    html = _render_html_document("PyPI Package Download Statistics", body_content)

    with open(output_file, "w") as f:
        f.write(html)
    logger.info("Report generated: %s", output_file)


def generate_package_html_report(
    package: str,
    output_file: str,
    stats: PackageStats | None = None,
    history: list[dict[str, Any]] | None = None,
) -> None:
    """Generate a detailed HTML report for a single package.

    Includes download stats, Python version distribution, and OS breakdown.
    """
    from .api import fetch_package_stats

    logger.info("Fetching detailed stats for %s...", package)

    # Fetch fresh stats from API if not provided
    if stats is None:
        stats = fetch_package_stats(package)

    if not stats:
        logger.warning("Could not fetch stats for %s", package)
        return

    # Fetch environment data and build charts
    py_versions = fetch_python_versions(package)
    os_stats = fetch_os_stats(package)
    py_version_chart, os_chart = _build_env_charts(py_versions, os_stats, size=220)

    # Build history chart
    history_chart = ""
    if history and len(history) >= 2:
        sorted_history = sorted(history, key=lambda h: h["fetch_date"])
        dates = [h["fetch_date"] for h in sorted_history]
        values = [h["total"] or 0 for h in sorted_history]
        history_chart = _make_single_line_chart(dates, values)

    # Build body content
    body_content = f"""    <h1>{package}</h1>
    <p><a href="https://pypi.org/project/{package}/">View on PyPI</a></p>

    <div class="stats-grid">
        <div class="stat-card">
            <div class="stat-value">{stats["total"]:,}</div>
            <div class="stat-label">Total Downloads</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{stats["last_month"]:,}</div>
            <div class="stat-label">Last Month</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{stats["last_week"]:,}</div>
            <div class="stat-label">Last Week</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{stats["last_day"]:,}</div>
            <div class="stat-label">Last Day</div>
        </div>
    </div>

    {f'<div class="chart-container"><h2>Downloads Over Time</h2>{history_chart}</div>' if history_chart else ""}

    <div class="chart-container">
        <h2>Environment Distribution</h2>
        <div class="pie-charts-row">
            {f'<div class="pie-chart-wrapper"><h3>Python Versions</h3>{py_version_chart}</div>' if py_version_chart else "<p>Python version data not available</p>"}
            {f'<div class="pie-chart-wrapper"><h3>Operating Systems</h3>{os_chart}</div>' if os_chart else "<p>OS data not available</p>"}
        </div>
    </div>
"""

    html = _render_html_document(f"{package} - Download Statistics", body_content)

    with open(output_file, "w") as f:
        f.write(html)
    logger.info("Report generated: %s", output_file)
