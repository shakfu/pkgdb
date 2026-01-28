"""SVG badge generation for download statistics."""


def _format_count(count: int) -> str:
    """Format a download count for display in badge.

    Examples: 1234 -> "1.2K", 1234567 -> "1.2M", 123 -> "123"
    """
    if count >= 1_000_000_000:
        return f"{count / 1_000_000_000:.1f}B"
    elif count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    elif count >= 1_000:
        return f"{count / 1_000:.1f}K"
    return str(count)


def _estimate_text_width(text: str, font_size: int = 11) -> int:
    """Estimate text width in pixels (approximate)."""
    # Average character width for Verdana/DejaVu Sans at 11px is ~7px
    char_width = font_size * 0.65
    return int(len(text) * char_width)


def generate_badge_svg(
    label: str,
    value: str,
    color: str = "#4c1",
    label_color: str = "#555",
) -> str:
    """Generate a shields.io-style SVG badge.

    Args:
        label: Left side text (e.g., "downloads")
        value: Right side text (e.g., "1.2M")
        color: Background color for the value side (default: green)
        label_color: Background color for the label side (default: gray)

    Returns:
        SVG string for the badge.
    """
    font_size = 11
    padding = 6
    height = 20

    label_width = _estimate_text_width(label, font_size) + padding * 2
    value_width = _estimate_text_width(value, font_size) + padding * 2
    total_width = label_width + value_width

    # Text positions (centered in each section)
    label_x = label_width / 2
    value_x = label_width + value_width / 2

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{total_width}" height="{height}">
  <linearGradient id="smooth" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="round">
    <rect width="{total_width}" height="{height}" rx="3" fill="#fff"/>
  </clipPath>
  <g clip-path="url(#round)">
    <rect width="{label_width}" height="{height}" fill="{label_color}"/>
    <rect x="{label_width}" width="{value_width}" height="{height}" fill="{color}"/>
    <rect width="{total_width}" height="{height}" fill="url(#smooth)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="{font_size}">
    <text x="{label_x}" y="15" fill="#010101" fill-opacity=".3">{label}</text>
    <text x="{label_x}" y="14" fill="#fff">{label}</text>
    <text x="{value_x}" y="15" fill="#010101" fill-opacity=".3">{value}</text>
    <text x="{value_x}" y="14" fill="#fff">{value}</text>
  </g>
</svg>'''


# Predefined color schemes
BADGE_COLORS = {
    "green": "#4c1",
    "brightgreen": "#44cc11",
    "blue": "#007ec6",
    "lightblue": "#5bc0de",
    "orange": "#fe7d37",
    "red": "#e05d44",
    "yellow": "#dfb317",
    "gray": "#9f9f9f",
}


def generate_downloads_badge(
    count: int,
    period: str = "total",
    color: str | None = None,
) -> str:
    """Generate a downloads badge for a package.

    Args:
        count: Download count.
        period: One of "total", "month", "week", "day".
        color: Badge color (default: auto-select based on count).

    Returns:
        SVG string for the badge.
    """
    # Auto-select color based on download count if not specified
    if color is None:
        if count >= 1_000_000:
            color = BADGE_COLORS["brightgreen"]
        elif count >= 100_000:
            color = BADGE_COLORS["green"]
        elif count >= 10_000:
            color = BADGE_COLORS["blue"]
        elif count >= 1_000:
            color = BADGE_COLORS["lightblue"]
        else:
            color = BADGE_COLORS["gray"]

    # Format label based on period
    label_map = {
        "total": "downloads",
        "month": "downloads/month",
        "week": "downloads/week",
        "day": "downloads/day",
    }
    label = label_map.get(period, "downloads")

    value = _format_count(count)

    return generate_badge_svg(label, value, color=color)
