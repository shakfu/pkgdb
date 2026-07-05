"""Anomaly and milestone detection for ``pkgdb check``.

These are pure functions over a package's daily download series (and its recent
totals). They aggregate to whole weeks before looking for anomalies so that the
strong day-of-week seasonality in PyPI downloads (weekday peaks, weekend
troughs) does not masquerade as spikes and drops.
"""

from datetime import datetime, timedelta

from .types import CheckEvent

# Defaults for anomaly detection.
DEFAULT_BASELINE_WEEKS = 8
DEFAULT_Z_THRESHOLD = 2.5
DEFAULT_MIN_WEEKLY = 10
# When the baseline has no variance, flag a week deviating by at least this %.
_FLAT_BASELINE_PCT = 50.0


def weekly_totals(series: list[tuple[str, int]], weeks: int) -> list[tuple[str, int]]:
    """Aggregate a daily series into consecutive 7-day calendar blocks.

    Blocks are anchored on the latest date present and walk backwards, so the
    first entry is the most recent 7 days. Missing dates count as zero.

    Args:
        series: ``(YYYY-MM-DD, downloads)`` pairs (any order).
        weeks: Number of 7-day blocks to produce.

    Returns:
        A list of ``(week_end_date, total)`` pairs, most recent first, with at
        most ``weeks`` entries (fewer if the series does not span that far).
    """
    if not series or weeks < 1:
        return []

    totals: dict[str, int] = {}
    for date, downloads in series:
        totals[date] = totals.get(date, 0) + downloads

    anchor = datetime.strptime(max(totals), "%Y-%m-%d").date()
    earliest = datetime.strptime(min(totals), "%Y-%m-%d").date()

    result: list[tuple[str, int]] = []
    for w in range(weeks):
        week_end = anchor - timedelta(days=w * 7)
        # Stop once a whole block would sit entirely before the first data point.
        if week_end < earliest:
            break
        block = 0
        for i in range(7):
            day = week_end - timedelta(days=i)
            block += totals.get(day.isoformat(), 0)
        result.append((week_end.isoformat(), block))
    return result


def detect_anomaly(
    series: list[tuple[str, int]],
    baseline_weeks: int = DEFAULT_BASELINE_WEEKS,
    z_threshold: float = DEFAULT_Z_THRESHOLD,
    min_weekly: float = DEFAULT_MIN_WEEKLY,
) -> CheckEvent | None:
    """Flag the most recent week if it deviates from its trailing baseline.

    Compares the most recent completed 7-day total against the mean and standard
    deviation of the ``baseline_weeks`` weeks before it. Returns a ``spike`` or
    ``drop`` event when the deviation exceeds ``z_threshold`` standard
    deviations, or None if the week is unremarkable or there is not enough data.

    Packages whose baseline averages fewer than ``min_weekly`` downloads a week
    are skipped, since percentage swings on tiny numbers are just noise.
    """
    weeks = weekly_totals(series, baseline_weeks + 1)
    if len(weeks) < baseline_weeks + 1:
        return None

    _, observed = weeks[0]
    baseline = [total for _, total in weeks[1 : baseline_weeks + 1]]
    mean = sum(baseline) / len(baseline)
    if mean < min_weekly:
        return None

    change_pct = ((observed - mean) / mean) * 100 if mean else 0.0

    variance = sum((x - mean) ** 2 for x in baseline) / len(baseline)
    std = variance**0.5

    if std == 0:
        # Perfectly flat baseline: fall back to a percentage rule.
        if abs(change_pct) < _FLAT_BASELINE_PCT:
            return None
        z_score = 0.0
    else:
        z_score = (observed - mean) / std
        if abs(z_score) < z_threshold:
            return None

    kind = "spike" if observed > mean else "drop"
    direction = "up" if observed > mean else "down"
    event: CheckEvent = {
        "kind": kind,
        "period": "week",
        "value": observed,
        "baseline": round(mean, 1),
        "change_pct": round(change_pct, 1),
        "z_score": round(z_score, 2),
        "message": (
            f"weekly downloads {direction} {abs(change_pct):.0f}% "
            f"({observed:,} vs {mean:,.0f} avg, z={z_score:.1f})"
        ),
    }
    return event


def detect_milestones(
    previous_total: int | None,
    current_total: int | None,
    milestones: list[int],
) -> list[int]:
    """Return milestones crossed upward between two totals.

    A milestone ``m`` is crossed when ``previous_total < m <= current_total``.
    Only upward crossings are reported, so a rolling-window total dipping back
    below a threshold does not re-fire on the next rise.
    """
    if previous_total is None or current_total is None:
        return []
    return sorted(m for m in milestones if previous_total < m <= current_total)
