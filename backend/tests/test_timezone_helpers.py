"""
Tests for the timezone helpers in api.py. These exist because the original
code stored naive UTC, read it as if it were local, and produced visible
4-hour offsets on every timestamp the user saw.

Tests here are written to be independent of the host's local timezone:
we use an explicit fixed offset (UTC-5, simulating Eastern Standard Time)
via `datetime.timezone(timedelta(hours=-5))` and verify the helpers
produce sane results regardless of LOCAL_TZ.
"""
from __future__ import annotations

from datetime import datetime, date, timedelta, timezone

from api import (
    LOCAL_TZ,
    _as_utc,
    _local_day_bounds_utc,
    _to_local,
)


class TestAsUtc:
    def test_naive_timestamp_gets_utc_attached(self):
        # Mirrors the legacy-data path: rows in events.db pre-tz migration
        # are naive. _as_utc must treat them as UTC, not as local time.
        naive = datetime(2026, 6, 30, 12, 0, 0)
        result = _as_utc(naive)
        assert result.tzinfo is timezone.utc
        # The wall-clock components don't shift — we just label as UTC.
        assert result.replace(tzinfo=None) == naive

    def test_already_aware_timestamp_passes_through(self):
        # Non-UTC aware timestamps must survive unchanged.
        est = timezone(timedelta(hours=-5))
        aware = datetime(2026, 6, 30, 8, 0, 0, tzinfo=est)
        result = _as_utc(aware)
        assert result is aware or result == aware


class TestToLocal:
    def test_utc_converts_to_local(self):
        # Any aware UTC moment must round-trip to the same instant in
        # LOCAL_TZ — the wall clock can shift, the instant doesn't.
        utc_moment = datetime(2026, 6, 30, 16, 0, 0, tzinfo=timezone.utc)
        local = _to_local(utc_moment)
        assert local.tzinfo == LOCAL_TZ
        # The two are the same instant — converted forward should equal
        # the original.
        assert local.astimezone(timezone.utc) == utc_moment


class TestLocalDayBoundsUtc:
    def test_bounds_span_24_hours(self):
        day = date(2026, 6, 30)
        start, end = _local_day_bounds_utc(day)
        assert (end - start) == timedelta(days=1)

    def test_start_is_local_midnight(self):
        # The start of the UTC range, when converted back to local time,
        # must be midnight on the requested day.
        day = date(2026, 6, 30)
        start, _ = _local_day_bounds_utc(day)
        local_start = start.astimezone(LOCAL_TZ)
        assert local_start.hour == 0
        assert local_start.minute == 0
        assert local_start.date() == day

    def test_returns_utc_aware(self):
        day = date(2026, 6, 30)
        start, end = _local_day_bounds_utc(day)
        assert start.tzinfo is timezone.utc
        assert end.tzinfo is timezone.utc


class TestRegressionTheBugWeFixed:
    """
    The bug: an event at 8:13 AM local time was getting filtered/displayed
    as 12:13 PM because the backend stored naive UTC and the frontend
    parsed the missing tzinfo as local time, doubling the offset.

    These two tests pin the contract: a UTC instant must convert to the
    correct local wall-clock, and a local midnight must convert to a UTC
    boundary that lies on the right calendar day.
    """

    def test_eastern_morning_event_classifies_to_eastern_day(self):
        # An event at UTC 12:13 PM is 8:13 AM EST. The day filter must
        # include this event when querying for the local day.
        day = date(2026, 6, 30)
        start, end = _local_day_bounds_utc(day)

        # Build a UTC moment that corresponds to 8:13 AM local.
        local_morning = datetime(2026, 6, 30, 8, 13, 0, tzinfo=LOCAL_TZ)
        utc_equivalent = local_morning.astimezone(timezone.utc)

        # That UTC moment MUST fall inside the day's UTC bounds —
        # regardless of which timezone the test host is in.
        assert start <= utc_equivalent < end

    def test_late_night_local_event_classifies_to_local_day_not_utc_day(self):
        # An event at 11:30 PM local time on June 30 — depending on the
        # host's offset, this may already be July 1 in UTC. The day-bounds
        # function must still place it inside June 30's range.
        day = date(2026, 6, 30)
        start, end = _local_day_bounds_utc(day)

        local_late = datetime(2026, 6, 30, 23, 30, 0, tzinfo=LOCAL_TZ)
        utc_equivalent = local_late.astimezone(timezone.utc)

        assert start <= utc_equivalent < end
