"""
End-to-end endpoint tests using FastAPI's TestClient against an isolated
SQLite. These cover the response contract — shape and key invariants —
rather than re-testing the inner logic (already covered by
test_absences, test_timeline_merge, test_timezone_helpers).
"""
from __future__ import annotations

from datetime import datetime, date, timedelta

from api import LOCAL_TZ
from test_utils import seed_events


TODAY = date.today()


def _ts(hour: int, minute: int = 0, second: int = 0, *, day: date | None = None) -> datetime:
    day = day or TODAY
    return datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=LOCAL_TZ)


class TestSummaryEndpoint:
    def test_empty_day_returns_zero_counts(self, client):
        resp = client.get(f"/summary?target_date={TODAY.isoformat()}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["sip_count"] == 0
        assert data["phone_count"] == 0
        assert data["break_count"] == 0
        assert data["lunch"] is None
        assert data["absences"] == []

    def test_seeded_day_returns_correct_counts(self, client):
        rows = [
            (_ts(9, 0),  "at_desk"),
            (_ts(9, 15), "sipping"),
            (_ts(9, 16), "at_desk"),
            (_ts(10, 0), "phone"),
            (_ts(10, 10), "at_desk"),    # 10 min on phone
            (_ts(11, 0), "away"),
            (_ts(11, 4), "at_desk"),     # short_break (4 min)
            (_ts(12, 0), "away"),
            (_ts(12, 35), "at_desk"),    # lunch
        ]
        seed_events(client.database, rows)

        data = client.get(f"/summary?target_date={TODAY.isoformat()}").json()

        assert data["sip_count"] == 1
        assert data["phone_count"] == 1
        assert data["phone_min"] >= 9   # ~10 min of phone usage
        assert data["phone_avg_session_min"] >= 9   # one 10-min session
        assert data["short_break_count"] == 1
        assert data["lunch"] is not None
        assert 30 <= data["lunch"]["duration_min"] <= 40

    def test_response_includes_required_fields(self, client):
        # Pin the response keys so a future renaming triggers a test
        # failure (frontend depends on these names).
        data = client.get(f"/summary?target_date={TODAY.isoformat()}").json()
        required = {
            "date", "sip_count", "phone_count", "phone_min", "phone_avg_session_min",
            "short_break_count", "long_break_count",
            "break_count", "avg_break_duration_min",
            "lunch", "absences", "total_events",
        }
        missing = required - data.keys()
        assert not missing, f"Missing keys in /summary: {missing}"

    def test_consecutive_sip_events_coalesce_into_one_drink(self, client):
        # Regression for the over-counting bug. A single drink in the real
        # world produces multiple `sipping` rows in the DB as the wrist
        # crosses the threshold several times. /summary should report 1.
        rows = [
            (_ts(9, 0),     "at_desk"),
            (_ts(9, 5, 0),  "sipping"),
            (_ts(9, 5, 12), "sipping"),    # 12s later — same drink
            (_ts(9, 5, 25), "sipping"),    # 13s later — still same drink
        ]
        seed_events(client.database, rows)
        data = client.get(f"/summary?target_date={TODAY.isoformat()}").json()
        assert data["sip_count"] == 1

    def test_well_separated_sip_events_remain_distinct_drinks(self, client):
        # Two sips more than the 90s coalesce gap apart are two drinks.
        rows = [
            (_ts(9, 0),  "at_desk"),
            (_ts(9, 5),  "sipping"),
            (_ts(9, 30), "sipping"),    # 25 min later — definitely a new drink
        ]
        seed_events(client.database, rows)
        data = client.get(f"/summary?target_date={TODAY.isoformat()}").json()
        assert data["sip_count"] == 2

    def test_consecutive_phone_heartbeats_coalesce_into_one_session(self, client):
        # Regression for the "527 sessions" bug. The watcher heartbeats
        # `phone` every ~10s while you're on your phone. /summary must
        # report the count of distinct SESSIONS, not raw event rows.
        # 7 heartbeats over 60s = 1 session.
        rows = [(_ts(9, 0), "at_desk")]
        for sec in range(0, 60, 10):     # 0, 10, 20, 30, 40, 50
            rows.append((_ts(10, 0, sec), "phone"))
        rows.append((_ts(10, 0, 55), "phone"))   # one more, still same session
        rows.append((_ts(10, 2),     "at_desk")) # end of session
        seed_events(client.database, rows)
        data = client.get(f"/summary?target_date={TODAY.isoformat()}").json()
        assert data["phone_count"] == 1

    def test_well_separated_phone_events_are_distinct_sessions(self, client):
        # Two phone usages > 2 minutes apart are two sessions.
        rows = [
            (_ts(9, 0),  "at_desk"),
            (_ts(9, 30), "phone"),
            (_ts(10, 0), "phone"),    # 30 min later — definitely a new session
        ]
        seed_events(client.database, rows)
        data = client.get(f"/summary?target_date={TODAY.isoformat()}").json()
        assert data["phone_count"] == 2

    def test_sips_inside_a_real_absence_are_suppressed(self, client):
        # Regression: a coworker walks past during your 2:33-3:21 break,
        # which triggers a spurious sip classification. The watcher then
        # immediately re-detects no pose (coworker leaves) so another
        # `away` row follows within MIN_RETURN_S — keeping the absence
        # open. The spurious sip is INSIDE the absence interval and
        # must not be counted.
        rows = [
            (_ts(9, 0),       "at_desk"),
            (_ts(14, 33),     "away"),
            (_ts(14, 50),     "sipping"),   # spurious — coworker walks by
            (_ts(14, 50, 5),  "away"),      # coworker gone 5s later
            (_ts(15, 21),     "at_desk"),
        ]
        seed_events(client.database, rows)
        data = client.get(f"/summary?target_date={TODAY.isoformat()}").json()
        # The spurious mid-absence sip must be suppressed.
        assert data["sip_count"] == 0
        # The absence is still recognized as ONE continuous break
        # (could be classified as short_break, long_break, or lunch
        # depending on duration + time of day — we just check that
        # exactly one absence survives).
        assert len(data["absences"]) == 1

    def test_phone_inside_a_real_absence_is_suppressed(self, client):
        rows = [
            (_ts(9, 0),       "at_desk"),
            (_ts(14, 33),     "away"),
            (_ts(14, 45),     "phone"),     # spurious mid-break phone
            (_ts(14, 46),     "phone"),     # heartbeat
            (_ts(14, 46, 30), "away"),      # back to away within MIN_RETURN_S
            (_ts(15, 21),     "at_desk"),
        ]
        seed_events(client.database, rows)
        data = client.get(f"/summary?target_date={TODAY.isoformat()}").json()
        assert data["phone_count"] == 0
        assert data["phone_min"] == 0


class TestTimelineEndpoint:
    def test_empty_day_returns_empty_segments(self, client):
        data = client.get(f"/timeline?target_date={TODAY.isoformat()}").json()
        assert data["date"] == TODAY.isoformat()
        assert data["segments"] == []

    def test_segments_have_required_shape(self, client):
        seed_events(client.database, [
            (_ts(9, 0), "at_desk"),
            (_ts(10, 0), "away"),
            (_ts(10, 30), "at_desk"),
        ])
        data = client.get(f"/timeline?target_date={TODAY.isoformat()}").json()
        for seg in data["segments"]:
            assert {"activity", "start", "end", "duration_s"} <= seg.keys()
            assert seg["duration_s"] > 0
            # End must be after start.
            assert seg["end"] > seg["start"]


class TestWeeklyEndpoint:
    def test_returns_exactly_five_weekday_entries(self, client):
        # The endpoint anchors to Mon-Fri of the current local week, so
        # the response always has 5 entries regardless of when called.
        data = client.get("/weekly").json()
        assert isinstance(data, list)
        assert len(data) == 5

    def test_weekdays_are_monday_through_friday(self, client):
        data = client.get("/weekly").json()
        # weekday(): Mon=0..Sun=6 → the 5 returned dates must be 0..4.
        weekdays = [date.fromisoformat(d["date"]).weekday() for d in data]
        assert weekdays == [0, 1, 2, 3, 4]

    def test_entry_shape(self, client):
        data = client.get("/weekly").json()
        for entry in data:
            assert {"date", "sip_count", "break_count", "lunch_duration_min"} <= entry.keys()


class TestProductivityEndpoint:
    def test_default_returns_90_days(self, client):
        # Default `days` param is 90.
        data = client.get("/productivity").json()
        assert len(data) == 90

    def test_days_param_respected(self, client):
        data = client.get("/productivity?days=7").json()
        assert len(data) == 7

    def test_days_param_clamped_to_max_365(self, client):
        # Defensive: passing a huge number must clamp, not iterate forever.
        data = client.get("/productivity?days=99999").json()
        assert len(data) == 365

    def test_at_desk_min_excludes_phone(self, client):
        # An hour of phone usage must NOT count toward at_desk_min.
        seed_events(client.database, [
            (_ts(9, 0), "phone"),
            (_ts(10, 0), "at_desk"),
            (_ts(11, 0), "away"),
        ])
        data = client.get("/productivity?days=1").json()
        today_entry = data[0]
        # 1 hour at_desk between 10am–11am. Phone (9-10) and away (11-now)
        # must be excluded. Allow some slack for trailing-end calc.
        assert 55 <= today_entry["at_desk_min"] <= 70

    def test_break_total_and_phone_min_in_productivity(self, client):
        # Inputs the frontend needs to compute focus_ratio per day.
        # ~1h at_desk, ~30 min break, ~30 min phone → focus_ratio ~0.5.
        rows = [
            (_ts(9, 0),   "at_desk"),
            (_ts(10, 0),  "phone"),
            (_ts(10, 30), "at_desk"),
            (_ts(11, 0),  "away"),
            (_ts(11, 30), "at_desk"),    # end-of-day for the test
        ]
        seed_events(client.database, rows)
        data = client.get("/productivity?days=1").json()
        today_entry = data[0]

        # Phone (10:00–10:30) and away/break (11:00–11:30) should both
        # be ~30 min each.
        assert 25 <= today_entry["phone_min"] <= 35
        assert 25 <= today_entry["break_total_min"] <= 35

    def test_response_shape(self, client):
        data = client.get("/productivity?days=3").json()
        for entry in data:
            required = {
                "date", "break_count",
                "short_break_count", "long_break_count",
                "lunch_duration_min", "at_desk_min",
                "break_total_min", "phone_min",
            }
            assert required <= entry.keys()


class TestEventsEndpoint:
    def test_empty_day(self, client):
        data = client.get(f"/events?target_date={TODAY.isoformat()}").json()
        assert data == []

    def test_returns_seeded_events_in_order(self, client):
        seed_events(client.database, [
            (_ts(9, 0), "at_desk"),
            (_ts(10, 30), "phone"),
            (_ts(11, 0), "at_desk"),
        ])
        data = client.get(f"/events?target_date={TODAY.isoformat()}").json()
        activities = [e["activity"] for e in data]
        assert activities == ["at_desk", "phone", "at_desk"]
        # Each event has the expected shape.
        for e in data:
            assert {"id", "activity", "confidence", "timestamp"} <= e.keys()
