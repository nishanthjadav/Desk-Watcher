"""
Regression tests for the timeline coalescing logic in `/timeline`.

The bug we fixed (1-min bar vs 4-min breaks-list discrepancy) was caused
by the timeline returning raw events while the breaks list applied a
noise-floor merge. The fix made the timeline apply the same merge.
These tests pin that contract down:

  - same-activity runs merge into one segment (watcher heartbeats
    re-log at_desk every ~10s; they must not produce 100 tiny segments)
  - sub-NOISE_FLOOR_S `away` segments get absorbed into their neighbors
    (a 15-second detection flicker is not a real break)
  - the final timeline's away durations match what the breaks list shows
"""
from __future__ import annotations

from datetime import datetime, date, timedelta

from api import LOCAL_TZ, NOISE_FLOOR_S
from test_utils import seed_events


TODAY = date.today()


def _ts(hour: int, minute: int = 0, second: int = 0, *, day: date | None = None) -> datetime:
    """Local-tz datetime for fixture event timestamps."""
    day = day or TODAY
    return datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=LOCAL_TZ)


def _seg_total(segments: list[dict], activity: str) -> float:
    return sum(s["duration_s"] for s in segments if s["activity"] == activity)


class TestTimelineMerging:
    def test_consecutive_same_activity_events_merge_into_one_segment(self, client):
        # Simulate the watcher heartbeat: 12 at_desk events 10s apart.
        # Should collapse into a single segment, not 12.
        rows = []
        for i in range(12):
            # Spread heartbeats across 2 minutes (10s apart): 9:00, 9:00:10, ..., 9:01:50
            rows.append((_ts(9, i // 6, (i % 6) * 10), "at_desk"))
        rows.append((_ts(9, 5, 0), "away"))      # ends the at_desk run
        seed_events(client.database, rows)

        resp = client.get(f"/timeline?target_date={TODAY.isoformat()}")
        assert resp.status_code == 200
        segs = resp.json()["segments"]

        at_desk_segs = [s for s in segs if s["activity"] == "at_desk"]
        assert len(at_desk_segs) == 1, "12 heartbeats should collapse to 1 segment"

    def test_sub_noise_floor_away_absorbed_into_neighbors(self, client):
        # 30-second detection flicker (under the 60s noise floor) should
        # NOT appear as a visible away segment. The surrounding at_desk
        # runs should merge across it. We bound the run with a clear
        # closing event so the assertion doesn't depend on what time
        # the test runs.
        rows = [
            (_ts(9, 0),  "at_desk"),
            (_ts(9, 30), "away"),       # 30s flicker
            (_ts(9, 30, 30), "at_desk"),
            (_ts(10, 0), "away"),       # real, supra-floor break
            (_ts(10, 30), "at_desk"),   # closes the real away cleanly
        ]
        seed_events(client.database, rows)

        resp = client.get(f"/timeline?target_date={TODAY.isoformat()}")
        segs = resp.json()["segments"]

        away_segs = [s for s in segs if s["activity"] == "away"]
        # Exactly one away survives — the real 30-minute one, not the
        # 30-second flicker.
        assert len(away_segs) == 1
        assert away_segs[0]["duration_s"] >= NOISE_FLOOR_S

    def test_supra_noise_floor_away_is_preserved(self, client):
        # A 4-minute away (well above the 60s floor) must survive merging.
        # This is the regression: the bar must match what the breaks list
        # shows.
        rows = [
            (_ts(9, 0),  "at_desk"),
            (_ts(9, 30), "away"),
            (_ts(9, 34), "at_desk"),
            (_ts(10, 0), "at_desk"),
        ]
        seed_events(client.database, rows)

        resp = client.get(f"/timeline?target_date={TODAY.isoformat()}")
        segs = resp.json()["segments"]

        away_total = _seg_total(segs, "away")
        # Should be exactly 4 minutes ± clock-jitter (we round to int).
        assert 4 * 60 - 1 <= away_total <= 4 * 60 + 1


class TestTimelineAgreesWithBreaksList:
    def test_durations_consistent_between_timeline_and_summary(self, client):
        """
        For the same seeded day, the short-break duration reported on
        /summary must match the away segment duration on /timeline. This
        is the exact bug we fixed.
        """
        rows = [
            (_ts(9, 0),       "at_desk"),
            (_ts(9, 13),      "away"),
            (_ts(9, 17),      "at_desk"),
            (_ts(10, 0),      "at_desk"),
        ]
        seed_events(client.database, rows)

        timeline = client.get(f"/timeline?target_date={TODAY.isoformat()}").json()
        summary = client.get(f"/summary?target_date={TODAY.isoformat()}").json()

        timeline_away_min = _seg_total(timeline["segments"], "away") / 60
        # Summary returns absences with duration_min already rounded.
        breaks = summary["absences"]
        assert len(breaks) == 1
        # Both should agree to within 0.1 min (the rounding step in
        # summary).
        assert abs(timeline_away_min - breaks[0]["duration_min"]) < 0.2
