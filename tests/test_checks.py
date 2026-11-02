"""Tests for anomaly and milestone detection (pkgdb check)."""

import sqlite3
from datetime import datetime, timedelta

from pkgdb import (
    CI_STATE_FAIL,
    CI_STATE_PASS,
    CI_STATE_RUNNING,
    detect_anomaly,
    detect_milestones,
    get_ci_status,
    get_db_connection,
    init_db,
    store_ci_status,
    weekly_totals,
)
from pkgdb.checks import detect_new_ci_failures
from pkgdb.service import PackageStatsService


def _series(daily_values, start="2026-01-05"):
    """Build a contiguous daily series from a list of per-day download counts."""
    d0 = datetime.strptime(start, "%Y-%m-%d").date()
    return [
        ((d0 + timedelta(days=i)).isoformat(), v) for i, v in enumerate(daily_values)
    ]


class TestWeeklyTotals:
    def test_two_weeks(self):
        series = _series([10] * 7 + [20] * 7)
        weeks = weekly_totals(series, 2)
        assert [total for _, total in weeks] == [140, 70]  # most recent first

    def test_stops_before_data_start(self):
        series = _series([5] * 7)  # only one week of data
        weeks = weekly_totals(series, 8)
        assert len(weeks) == 1
        assert weeks[0][1] == 35

    def test_empty(self):
        assert weekly_totals([], 4) == []
        assert weekly_totals(_series([1, 2, 3]), 0) == []


class TestDetectAnomaly:
    def test_spike_flat_baseline(self):
        # 8 baseline weeks at 100/day (700/wk), last week at 200/day (1400/wk)
        series = _series([100] * 56 + [200] * 7)
        event = detect_anomaly(series)
        assert event is not None
        assert event["kind"] == "spike"
        assert event["value"] == 1400
        assert event["baseline"] == 700.0
        assert event["change_pct"] == 100.0
        assert event["period"] == "week"

    def test_drop_flat_baseline(self):
        series = _series([100] * 56 + [20] * 7)
        event = detect_anomaly(series)
        assert event is not None
        assert event["kind"] == "drop"
        assert event["value"] == 140
        assert event["change_pct"] < 0

    def test_no_anomaly_when_stable(self):
        # Last week only slightly above a flat baseline -> below the 50% rule
        series = _series([100] * 56 + [103] * 7)
        assert detect_anomaly(series) is None

    def test_variance_baseline_uses_zscore(self):
        # Baseline with spread; a big last week should exceed the z threshold
        weekly = [600, 700, 650, 720, 680, 710, 690, 700]
        daily = []
        for wk in weekly:
            daily += [wk // 7] * 7
        daily += [2000]  # inflate; padded below to a full week
        daily += [0] * 6
        series = _series(daily)
        event = detect_anomaly(series)
        assert event is not None
        assert event["kind"] == "spike"
        assert abs(event["z_score"]) >= 2.5

    def test_skips_low_volume_packages(self):
        # Baseline averages < min_weekly (10); even a big jump is ignored
        series = _series([1] * 56 + [5] * 7)
        assert detect_anomaly(series) is None

    def test_insufficient_history(self):
        # Fewer than baseline_weeks + 1 weeks of data -> no verdict
        series = _series([100] * 20)
        assert detect_anomaly(series) is None

    def test_custom_thresholds(self):
        series = _series([100] * 56 + [130] * 7)  # +30%
        # Default flat rule needs 50%; a 25% z-agnostic override still needs std
        assert detect_anomaly(series) is None
        # But lowering the flat-baseline path isn't exposed; verify baseline_weeks
        short = detect_anomaly(series, baseline_weeks=4)
        # 4 baseline weeks all 700, last 910 -> +30%, flat rule 50% -> still None
        assert short is None


class TestDetectMilestones:
    def test_upward_crossing(self):
        assert detect_milestones(900, 1100, [1000]) == [1000]

    def test_multiple_crossings_sorted(self):
        assert detect_milestones(900, 11000, [1000, 5000, 10000, 50000]) == [
            1000,
            5000,
            10000,
        ]

    def test_no_crossing(self):
        assert detect_milestones(1100, 1200, [1000]) == []

    def test_exact_boundary_is_inclusive(self):
        assert detect_milestones(999, 1000, [1000]) == [1000]

    def test_downward_not_reported(self):
        assert detect_milestones(1200, 1100, [1000]) == []

    def test_none_totals(self):
        assert detect_milestones(None, 1000, [500]) == []
        assert detect_milestones(500, None, [500]) == []


def _ci_row(**overrides):
    row = {
        "repo_key": "o/r",
        "workflow_name": "build",
        "state": CI_STATE_FAIL,
        "run_url": "https://github.com/o/r/actions/runs/1",
        "first_failed_at": "2026-10-01T00:00:00",
        "notified_failed_at": None,
    }
    row.update(overrides)
    return row


class TestDetectNewCIFailures:
    def test_unreported_failure_is_an_event(self):
        [event] = detect_new_ci_failures([_ci_row()])
        assert event["kind"] == "ci_failure"
        assert event["package"] == "o/r"
        assert event["workflow"] == "build"
        assert event["first_failed_at"] == "2026-10-01T00:00:00"
        assert event["run_url"] == "https://github.com/o/r/actions/runs/1"

    def test_reported_streak_is_silent(self):
        row = _ci_row(notified_failed_at="2026-10-01T00:00:00")
        assert detect_new_ci_failures([row]) == []

    def test_new_streak_after_reported_one_fires(self):
        row = _ci_row(
            first_failed_at="2026-10-20T00:00:00",
            notified_failed_at="2026-10-01T00:00:00",
        )
        assert len(detect_new_ci_failures([row])) == 1

    def test_non_failing_states_ignored(self):
        rows = [
            _ci_row(state=CI_STATE_PASS, first_failed_at=None),
            # A running workflow keeps its streak but is not a failure now.
            _ci_row(state=CI_STATE_RUNNING),
        ]
        assert detect_new_ci_failures(rows) == []


class TestRunChecksCI:
    """`run_checks(ci=True)` reports each failure streak exactly once."""

    @staticmethod
    def _record(temp_db, state, started=None, workflow="build"):
        conn = get_db_connection(temp_db)
        init_db(conn)
        store_ci_status(conn, "o/r", workflow, state, run_started_at=started)
        conn.close()

    @staticmethod
    def _ci_events(service):
        return [e for e in service.run_checks(ci=True) if e["kind"] == "ci_failure"]

    def test_opt_in(self, temp_db):
        self._record(temp_db, CI_STATE_FAIL, "2026-10-01T00:00:00")
        service = PackageStatsService(temp_db)
        assert service.run_checks() == []
        # Not marked while disabled, so enabling it still reports the failure.
        assert len(self._ci_events(service)) == 1

    def test_standing_failure_reported_once(self, temp_db):
        self._record(temp_db, CI_STATE_FAIL, "2026-10-01T00:00:00")
        service = PackageStatsService(temp_db)
        assert len(self._ci_events(service)) == 1
        # Later scans keep it failing; check must stay quiet.
        self._record(temp_db, CI_STATE_FAIL, "2026-10-02T00:00:00")
        self._record(temp_db, CI_STATE_RUNNING)
        self._record(temp_db, CI_STATE_FAIL, "2026-10-03T00:00:00")
        assert self._ci_events(service) == []

    def test_break_after_fix_reported_again(self, temp_db):
        self._record(temp_db, CI_STATE_FAIL, "2026-10-01T00:00:00")
        service = PackageStatsService(temp_db)
        assert len(self._ci_events(service)) == 1
        self._record(temp_db, CI_STATE_PASS)
        assert self._ci_events(service) == []
        self._record(temp_db, CI_STATE_FAIL, "2026-10-20T00:00:00")
        [event] = self._ci_events(service)
        assert event["first_failed_at"] == "2026-10-20T00:00:00"

    def test_scan_preserves_notified_marker(self, temp_db):
        self._record(temp_db, CI_STATE_FAIL, "2026-10-01T00:00:00")
        PackageStatsService(temp_db).run_checks(ci=True)
        self._record(temp_db, CI_STATE_FAIL, "2026-10-05T00:00:00")
        conn = get_db_connection(temp_db)
        [row] = get_ci_status(conn)
        conn.close()
        assert row["notified_failed_at"] == "2026-10-01T00:00:00"


def test_init_db_adds_notified_column_to_old_table(temp_db):
    conn = sqlite3.connect(temp_db)
    conn.execute(
        """CREATE TABLE github_ci_status (
            repo_key TEXT NOT NULL, workflow_name TEXT NOT NULL,
            state TEXT NOT NULL, branch TEXT, run_id INTEGER, run_url TEXT,
            run_started_at TEXT, first_failed_at TEXT, checked_at TEXT NOT NULL,
            PRIMARY KEY (repo_key, workflow_name))"""
    )
    conn.commit()
    init_db(conn)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(github_ci_status)")}
    conn.close()
    assert "notified_failed_at" in columns
