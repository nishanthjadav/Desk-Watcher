"""
_pair_absences and _classify_absences in api.py are the heart of the
breaks dashboard. They take a flat event list and turn it into
classified absences (noise / short_break / long_break / lunch).

Tests use a `FakeEvent` to avoid touching the real DB — these functions
only read `.activity` and `.timestamp`, so a NamedTuple is enough.

All timestamps in fixtures are anchored to LOCAL_TZ so the lunch-hour
check (which uses local hour) behaves the same regardless of which
timezone the CI runner happens to be in.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date, time as dtime, timedelta

import pytest

from api import (
    LOCAL_TZ,
    NOISE_FLOOR_S,
    _classify_absences,
    _pair_absences,
)


@dataclass
class FakeEvent:
    activity: str
    timestamp: datetime


def at(hour: int, minute: int = 0, second: int = 0, *, day: date | None = None) -> datetime:
    """
    Helper: produce a local-tz datetime at HH:MM on `day` (defaults to
    a fixed date so the test is deterministic). The api helpers convert
    to UTC internally — we always provide tz-aware inputs to mirror the
    real watcher's behavior.
    """
    day = day or date(2026, 6, 30)
    return datetime.combine(day, dtime(hour, minute, second), tzinfo=LOCAL_TZ)


# ── _pair_absences ────────────────────────────────────────────────────────

class TestPairAbsences:
    def test_no_events_returns_empty(self):
        assert _pair_absences([], date(2026, 6, 30)) == []

    def test_single_away_to_return_produces_one_absence(self):
        events = [
            FakeEvent("at_desk", at(9, 0)),
            FakeEvent("away", at(9, 30)),
            FakeEvent("at_desk", at(9, 34)),
        ]
        absences = _pair_absences(events, date(2026, 6, 30))
        assert len(absences) == 1
        assert absences[0]["duration_s"] == 4 * 60

    def test_two_absences_in_a_day(self):
        events = [
            FakeEvent("at_desk", at(9, 0)),
            FakeEvent("away", at(9, 30)),
            FakeEvent("at_desk", at(9, 34)),
            FakeEvent("away", at(12, 0)),
            FakeEvent("at_desk", at(12, 35)),
        ]
        absences = _pair_absences(events, date(2026, 6, 30))
        durations = [a["duration_s"] for a in absences]
        assert durations == [4 * 60, 35 * 60]

    def test_unclosed_away_capped_at_end_of_day_for_past_days(self):
        # Past day with no closing event — should be capped at end-of-day,
        # not extended forward in time.
        past_day = date(2026, 6, 1)
        events = [
            FakeEvent("at_desk", datetime.combine(past_day, dtime(9, 0), tzinfo=LOCAL_TZ)),
            FakeEvent("away", datetime.combine(past_day, dtime(15, 0), tzinfo=LOCAL_TZ)),
        ]
        absences = _pair_absences(events, past_day)
        assert len(absences) == 1
        # End of day = 23:59:59.999999 minus 15:00 ≈ 9 hours.
        assert absences[0]["duration_s"] >= 8 * 3600
        assert absences[0].get("open") is True

    def test_phone_event_does_not_open_an_absence(self):
        # A phone event is not "away" — the user is still at their desk,
        # just disengaged. Mid-sequence phone events must not split the
        # at-desk run into spurious absences.
        events = [
            FakeEvent("at_desk", at(9, 0)),
            FakeEvent("phone", at(9, 15)),
            FakeEvent("at_desk", at(9, 30)),
        ]
        assert _pair_absences(events, date(2026, 6, 30)) == []

    def test_back_to_back_away_runs_collapse(self):
        # Two consecutive `away` events with no intervening present event
        # should produce a single absence from the first to the next
        # present event.
        events = [
            FakeEvent("at_desk", at(9, 0)),
            FakeEvent("away", at(9, 10)),
            FakeEvent("away", at(9, 12)),    # re-logged, watcher hysteresis
            FakeEvent("at_desk", at(9, 30)),
        ]
        absences = _pair_absences(events, date(2026, 6, 30))
        assert len(absences) == 1
        assert absences[0]["duration_s"] == 20 * 60


# ── _classify_absences ────────────────────────────────────────────────────

def _absence(start: datetime, duration_s: float) -> dict:
    return {
        "start": start,
        "end": start + timedelta(seconds=duration_s),
        "duration_s": float(duration_s),
    }


class TestClassifyAbsences:
    def test_short_glitch_is_noise(self):
        a = _absence(at(9, 0), NOISE_FLOOR_S - 5)
        out = _classify_absences([a])
        assert out[0]["category"] == "noise"

    def test_brief_break_is_short_break(self):
        # 4 minutes — well above the noise floor, well under the 20-min
        # short_break ceiling. With the bathroom category collapsed, any
        # break under 20 minutes is a short_break.
        a = _absence(at(10, 0), 4 * 60)
        out = _classify_absences([a])
        assert out[0]["category"] == "short_break"

    def test_mid_length_break_is_short_break(self):
        # 12 minutes — still under the 20-min ceiling. After collapsing
        # the bathroom category, any break under 20 minutes is a short_break.
        a = _absence(at(10, 0), 12 * 60)
        out = _classify_absences([a])
        assert out[0]["category"] == "short_break"

    def test_long_break_when_outside_lunch_window(self):
        # 40 minutes at 3pm — past the lunch window (11–15), so it stays
        # long_break instead of being promoted to lunch.
        a = _absence(at(15, 30), 40 * 60)
        out = _classify_absences([a])
        assert out[0]["category"] == "long_break"

    def test_midday_long_absence_is_lunch(self):
        a = _absence(at(12, 30), 35 * 60)
        out = _classify_absences([a])
        assert out[0]["category"] == "lunch"

    def test_only_longest_midday_qualifying_absence_is_lunch(self):
        # Two qualifying-duration absences in the lunch window: only the
        # longer one wins the "lunch" label. The other becomes long_break.
        a1 = _absence(at(11, 30), 22 * 60)
        a2 = _absence(at(13, 30), 45 * 60)
        out = _classify_absences([a1, a2])
        categories = [o["category"] for o in out]
        assert categories == ["long_break", "lunch"]

    def test_lunch_window_excludes_late_afternoon(self):
        # 16:00 (4pm) is past the LUNCH_WINDOW = (11, 15) end. Even a long
        # absence here is long_break, not lunch — important when you took
        # an actual long afternoon break.
        a = _absence(at(16, 0), 60 * 60)
        out = _classify_absences([a])
        assert out[0]["category"] == "long_break"

    def test_lunch_hour_check_uses_local_time(self):
        # Regression for the timezone bug we hit: the original code did
        # `a["start"].hour` on a UTC datetime. If LOCAL_TZ != UTC, a 12pm
        # local absence would have a different .hour and miss the window.
        #
        # Construct an absence whose UTC hour is OUTSIDE 11–15 but whose
        # LOCAL hour is INSIDE. With the bug present, this would fail.
        # With the fix (using _to_local), it passes regardless of host tz.
        if LOCAL_TZ is None or LOCAL_TZ.utcoffset(datetime(2026, 6, 30)) == timedelta(0):
            # Test only meaningful when host is NOT UTC. On a UTC runner
            # we can't construct a discrepancy, so skip.
            pytest.skip("LOCAL_TZ is UTC — no discrepancy to detect.")

        # 12:30pm local time → lunch window
        a = _absence(at(12, 30), 40 * 60)
        out = _classify_absences([a])
        assert out[0]["category"] == "lunch"


# ── Integration: events → absences → categories ───────────────────────────

class TestPipelineIntegration:
    def test_realistic_workday(self):
        """A full simulated workday — sanity-check the categories end-to-end."""
        d = date(2026, 6, 30)
        events = [
            FakeEvent("at_desk",  at(8, 0,  day=d)),
            FakeEvent("away",     at(9, 30, day=d)),    # short_break (4 min)
            FakeEvent("at_desk",  at(9, 34, day=d)),
            FakeEvent("away",     at(12, 0, day=d)),    # lunch
            FakeEvent("at_desk",  at(12, 40, day=d)),
            FakeEvent("away",     at(14, 0, day=d)),    # short_break (15 min)
            FakeEvent("at_desk",  at(14, 15, day=d)),
            FakeEvent("away",     at(16, 0, day=d)),    # long_break (off window)
            FakeEvent("at_desk",  at(16, 30, day=d)),
        ]
        absences = _classify_absences(_pair_absences(events, d))
        cats = [a["category"] for a in absences]
        assert cats == ["short_break", "lunch", "short_break", "long_break"]
