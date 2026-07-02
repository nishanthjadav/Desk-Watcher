from datetime import datetime, date, time as dtime, timedelta, timezone
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from database import SessionLocal, Event

app = FastAPI(title="Desk Watcher API")

app.add_middleware(
    CORSMiddleware,
    # 5173 is the Vite dev origin (source workflow). The two `tauri.*`
    # entries are the schemes Tauri's webview uses when the frontend is
    # loaded from the app bundle — without them, every fetch from inside
    # the packaged app gets a CORS block.
    allow_origins=[
        "http://localhost:5173",
        "tauri://localhost",
        "http://tauri.localhost",
    ],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/healthz")
def healthz():
    """
    Cheap readiness probe. The Tauri Rust supervisor polls this after
    launching the api sidecar and only reveals the dashboard window once
    it returns 200, so the user doesn't see a "failed to fetch" flash
    before uvicorn has bound its port.
    """
    return {"ok": True}


NOISE_FLOOR_S = 60          # absences shorter than this are detection glitches, not breaks
SHORT_BREAK_MAX_S = 20 * 60 # <= 20 min => short break (anything under is a short break)
LUNCH_MIN_S = 20 * 60       # >= 20 min and in midday window => lunch candidate
LUNCH_WINDOW = (11, 15)     # default [start_hour, end_hour) for lunch detection, LOCAL time.
                            # Used when the request does not override work hours. When
                            # start_hour/end_hour are provided we derive the lunch window
                            # from those via _lunch_window() so an early-shift or late-shift
                            # user still gets their midday break classified correctly.

# An absence only ends when we see at least this much continuous presence.
# Without this, a coworker walking past your camera during lunch produces
# ~2 seconds of "at_desk", which would close the absence and split your
# lunch into two short breaks. Three minutes is comfortably above the
# longest "someone walks by" event and comfortably below a real return.
MIN_RETURN_S = 180

# Sips logged within this window of each other count as one drink. A single
# drink rarely happens as one continuous wrist-near-nose event — you raise
# the bottle, sip, lower slightly, sip again. Each crossing of the pose
# threshold is its own DB row, but a human would call it one sip.
SIP_COALESCE_GAP_S = 90

# Phone events logged within this window of each other count as one
# session. Watcher heartbeats `phone` every ~10s while you're on your
# phone, so a 70-minute scroll would otherwise show up as 420 "sessions."
# A real new session is when you've genuinely put the phone down for at
# least this long (default 2 minutes).
PHONE_SESSION_GAP_S = 120


LOCAL_TZ = datetime.now().astimezone().tzinfo


def _as_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def _to_local(ts: datetime) -> datetime:
    return _as_utc(ts).astimezone(LOCAL_TZ)


def _local_day_bounds_utc(day: date) -> tuple[datetime, datetime]:
    start_local = datetime.combine(day, dtime.min, tzinfo=LOCAL_TZ)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _lunch_window(start_hour: int | None, end_hour: int | None) -> tuple[int, int]:
    """
    Pick the [start_hour, end_hour) local-time window used to detect lunch.

    When the caller doesn't override work hours, we keep the historical
    default (11a–3p). When they do, we shift the window proportionally so
    an early-shift worker (6a–2p) still gets their midday absence flagged.
    The window is midpoint ± 2 hours, rounded to the nearest hour and
    clamped inside the workday.
    """
    if start_hour is None or end_hour is None:
        return LUNCH_WINDOW
    midpoint = (start_hour + end_hour) / 2
    lo = int(round(midpoint - 2))
    hi = int(round(midpoint + 2))
    # Clamp inside the workday. If the day is narrower than 4 hours the
    # window collapses to the workday itself — the classifier still works.
    lo = max(start_hour, lo)
    hi = min(end_hour, hi)
    if hi <= lo:
        return (start_hour, end_hour)
    return (lo, hi)


def _window_for_day(
    day: date, start_hour: int | None, end_hour: int | None
) -> tuple[datetime, datetime] | None:
    """
    Convert a local-time [start_hour, end_hour) work window on `day` to UTC.

    Returns None when the caller isn't restricting hours — callers use this
    to short-circuit clipping entirely (preserving byte-for-byte legacy
    output when no override is present).
    """
    if start_hour is None or end_hour is None:
        return None
    start_local = datetime.combine(day, dtime(hour=start_hour), tzinfo=LOCAL_TZ)
    end_local = datetime.combine(day, dtime(hour=0), tzinfo=LOCAL_TZ) + timedelta(hours=end_hour)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _clip_seconds(
    seg_start: datetime, seg_end: datetime, window: tuple[datetime, datetime] | None
) -> float:
    """
    Return the overlap of [seg_start, seg_end) with the work-hours window,
    in seconds. Zero if disjoint. When window is None we return the raw
    duration — no clipping requested.
    """
    if seg_end <= seg_start:
        return 0.0
    if window is None:
        return (seg_end - seg_start).total_seconds()
    ws, we = window
    lo = max(seg_start, ws)
    hi = min(seg_end, we)
    if hi <= lo:
        return 0.0
    return (hi - lo).total_seconds()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _events_for_day(db: Session, day: date) -> list[Event]:
    start_utc, end_utc = _local_day_bounds_utc(day)
    start_naive = start_utc.replace(tzinfo=None)
    end_naive = end_utc.replace(tzinfo=None)
    events = (
        db.query(Event)
        .filter(Event.timestamp >= start_naive, Event.timestamp < end_naive)
        .order_by(Event.timestamp)
        .all()
    )
    for e in events:
        e.timestamp = _as_utc(e.timestamp)
    return events


def _pair_absences(events: list[Event], day: date) -> list[dict]:
    """
    Walk transitions and emit one absence record per (away → sustained return)
    pair.

    "Sustained return" means we must see at least MIN_RETURN_S of continuous
    non-away time before we accept that the absence ended. Brief at_desk
    bursts caused by a coworker walking through the camera's view should
    NOT split a lunch into two pieces.
    """
    # Precompute the timestamps of the "away" events so we can look ahead
    # in O(log n) per check.
    away_times = [e.timestamp for e in events if e.activity == "away"]

    def next_away_after(t: datetime) -> datetime | None:
        # Linear scan is fine for typical day-sized event lists (<10k rows).
        # If this ever shows up in profiling, switch to bisect.
        for at in away_times:
            if at > t:
                return at
        return None

    absences: list[dict] = []
    away_start: datetime | None = None

    for e in events:
        if e.activity == "away":
            if away_start is None:
                away_start = e.timestamp
            # else: still away, ignore.
            continue

        # Non-away event while an absence is open. Decide whether this is
        # a real return or a brief detection blip mid-absence.
        if away_start is None:
            continue

        upcoming_away = next_away_after(e.timestamp)
        if upcoming_away is not None and (upcoming_away - e.timestamp).total_seconds() < MIN_RETURN_S:
            # Not sustained — another away comes soon. Treat this as noise
            # inside the absence; don't close it.
            continue

        # Sustained return: close the absence here.
        absences.append({
            "start": away_start,
            "end": e.timestamp,
            "duration_s": (e.timestamp - away_start).total_seconds(),
        })
        away_start = None

    if away_start is not None:
        # End-of-day in local time, converted to UTC for arithmetic with timestamps.
        end_of_day_local = datetime.combine(day, dtime.max, tzinfo=LOCAL_TZ)
        end_of_day = end_of_day_local.astimezone(timezone.utc)
        now = _now_utc()
        cap = min(end_of_day, now) if day == date.today() else end_of_day
        if cap > away_start:
            absences.append({
                "start": away_start,
                "end": cap,
                "duration_s": (cap - away_start).total_seconds(),
                "open": True,
            })

    return absences


def _classify_absences(
    absences: list[dict], lunch_window: tuple[int, int] = LUNCH_WINDOW
) -> list[dict]:

    classified = [dict(a) for a in absences]

    lunch_idx: int | None = None
    lunch_dur = 0.0
    for i, a in enumerate(classified):
        if a["duration_s"] < LUNCH_MIN_S:
            continue
        start_hour = _to_local(a["start"]).hour
        if not (lunch_window[0] <= start_hour < lunch_window[1]):
            continue
        if a["duration_s"] > lunch_dur:
            lunch_dur = a["duration_s"]
            lunch_idx = i

    for i, a in enumerate(classified):
        d = a["duration_s"]
        if d < NOISE_FLOOR_S:
            a["category"] = "noise"
        elif i == lunch_idx:
            a["category"] = "lunch"
        elif d <= SHORT_BREAK_MAX_S:
            a["category"] = "short_break"
        else:
            a["category"] = "long_break"

    return classified


def _filter_events_outside_absences(events: list[Event], absences: list[dict]) -> list[Event]:
    """
    Remove non-`away` events that fall inside any real absence interval.

    Why: if you're confirmed away from your desk between 2:33 and 3:21,
    you can't have been sipping or on your phone in that window. Yet a
    coworker walking past the camera can trigger a brief pose detection,
    and the classifier might call it `sipping` or `phone`. Those events
    should not appear on the dashboard.

    Filtering at the events level means the timeline, sip count, phone
    count, and at-desk totals all stay consistent — they all run off
    the same filtered list. The raw events stay in the DB for forensics.

    Note: `away` events are NEVER filtered. They define the absence
    intervals themselves; removing them would break _pair_absences on
    the next call.
    """
    if not absences:
        return events
    # Only real absences count — `noise` segments (sub-NOISE_FLOOR) get
    # the user-walked-past treatment as part of the existing noise floor,
    # so we don't want to suppress events inside those.
    real_intervals = [
        (a["start"], a["end"])
        for a in absences
        if a.get("category") != "noise"
    ]
    if not real_intervals:
        return events

    def in_any_interval(ts) -> bool:
        for start, end in real_intervals:
            if start <= ts < end:
                return True
        return False

    return [e for e in events if e.activity == "away" or not in_any_interval(e.timestamp)]


@app.get("/events")
def get_events(target_date: str | None = None, db: Session = Depends(get_db)):
    day = datetime.strptime(target_date, "%Y-%m-%d").date() if target_date else date.today()
    events = _events_for_day(db, day)
    return [
        {
            "id": e.id,
            "activity": e.activity,
            "confidence": e.confidence,
            "timestamp": e.timestamp.isoformat(),
        }
        for e in events
    ]


def _coalesce_sips(events: list[Event], gap_s: int = SIP_COALESCE_GAP_S) -> int:
    """
    Count distinct drinks, not raw `sipping` events.

    A single drink (raise bottle → swallow → lower → swallow again) can
    cross the wrist-near-nose threshold several times in the DB. This
    folds any sip events within `gap_s` of the previous sip into one
    drink. Returns the number of distinct drinks.

    Assumes events are already ordered by timestamp (which `_events_for_day`
    guarantees).
    """
    sip_times = [e.timestamp for e in events if e.activity == "sipping"]
    if not sip_times:
        return 0

    drinks = 1
    prev = sip_times[0]
    for ts in sip_times[1:]:
        if (ts - prev).total_seconds() > gap_s:
            drinks += 1
        prev = ts
    return drinks


def _coalesce_phone_sessions(events: list[Event], gap_s: int = PHONE_SESSION_GAP_S) -> int:
    """
    Count distinct phone sessions, not raw `phone` events.

    Same chain semantics as _coalesce_sips: consecutive phone rows within
    `gap_s` of the previous phone row belong to the same session. A new
    session begins when you've been off your phone for at least gap_s.

    Watcher heartbeats `phone` every ~10s while the activity persists, so
    a 70-minute scroll produces ~420 rows but counts as 1 session.
    """
    phone_times = [e.timestamp for e in events if e.activity == "phone"]
    if not phone_times:
        return 0

    sessions = 1
    prev = phone_times[0]
    for ts in phone_times[1:]:
        if (ts - prev).total_seconds() > gap_s:
            sessions += 1
        prev = ts
    return sessions


def _activity_seconds(
    events: list[Event],
    day: date,
    activity: str,
    window: tuple[datetime, datetime] | None = None,
) -> float:
    if not events:
        return 0.0
    end_of_day_local = datetime.combine(day, dtime.max, tzinfo=LOCAL_TZ)
    end_of_day = end_of_day_local.astimezone(timezone.utc)
    trailing_end = min(_now_utc(), end_of_day) if day == date.today() else end_of_day

    total_s = 0.0
    for i, e in enumerate(events):
        if e.activity != activity:
            continue
        end_ts = events[i + 1].timestamp if i + 1 < len(events) else trailing_end
        if window is None:
            total_s += max(0.0, (end_ts - e.timestamp).total_seconds())
        else:
            total_s += _clip_seconds(e.timestamp, end_ts, window)
    return total_s


@app.get("/summary")
def get_summary(
    target_date: str | None = None,
    start_hour: int | None = None,
    end_hour: int | None = None,
    db: Session = Depends(get_db),
):
    day = datetime.strptime(target_date, "%Y-%m-%d").date() if target_date else date.today()
    events = _events_for_day(db, day)

    lunch_window = _lunch_window(start_hour, end_hour)
    window = _window_for_day(day, start_hour, end_hour)

    # Compute absences first, then drop spurious in-absence events so the
    # downstream counts (sips, phone sessions, phone duration) reflect
    # only things that actually could have happened.
    absences = _classify_absences(_pair_absences(events, day), lunch_window)
    events = _filter_events_outside_absences(events, absences)

    sip_count = _coalesce_sips(events)
    phone_session_count = _coalesce_phone_sessions(events)
    phone_seconds = _activity_seconds(events, day, "phone", window)
    phone_avg_session_s = (phone_seconds / phone_session_count) if phone_session_count else 0

    by_cat: dict[str, list[dict]] = {
        "short_break": [], "long_break": [], "lunch": [], "noise": [],
    }
    for a in absences:
        by_cat[a["category"]].append(a)

    # Real breaks, filtered to those that overlap the work-hours window.
    # An absence entirely outside your work hours (e.g. before you started
    # for the day) shouldn't count as a break in your summary.
    def overlaps_window(a: dict) -> bool:
        if window is None:
            return True
        return _clip_seconds(a["start"], a["end"], window) > 0

    real_breaks = [a for a in (by_cat["short_break"] + by_cat["long_break"]) if overlaps_window(a)]

    # Report clipped durations so averages line up with the visible bars.
    def visible_duration_s(a: dict) -> float:
        if window is None:
            return a["duration_s"]
        return _clip_seconds(a["start"], a["end"], window)

    avg_break_s = (
        sum(visible_duration_s(a) for a in real_breaks) / len(real_breaks)
    ) if real_breaks else 0

    lunch_candidate = by_cat["lunch"][0] if by_cat["lunch"] else None
    lunch = lunch_candidate if lunch_candidate and overlaps_window(lunch_candidate) else None

    def serialize(a: dict) -> dict:
        return {
            "start": a["start"].isoformat(),
            "end": a["end"].isoformat(),
            "duration_min": round(visible_duration_s(a) / 60, 1),
            "category": a["category"],
        }

    # Absences visible in the UI: exclude noise AND exclude ones fully
    # outside the work-hours window.
    visible_absences = [
        a for a in absences
        if a["category"] != "noise" and overlaps_window(a)
    ]

    return {
        "date": day.isoformat(),
        "sip_count": sip_count,
        "phone_count": phone_session_count,
        "phone_min": round(phone_seconds / 60, 1),
        "phone_avg_session_min": round(phone_avg_session_s / 60, 1),
        "short_break_count": sum(1 for a in real_breaks if a["category"] == "short_break"),
        "long_break_count": sum(1 for a in real_breaks if a["category"] == "long_break"),
        "break_count": len(real_breaks),
        "avg_break_duration_min": round(avg_break_s / 60, 1),
        "lunch": {
            "start": lunch["start"].isoformat(),
            "end": lunch["end"].isoformat(),
            "duration_min": round(visible_duration_s(lunch) / 60, 1),
        } if lunch else None,
        "absences": [serialize(a) for a in visible_absences],
        "total_events": len(events),
    }


@app.get("/timeline")
def get_timeline(
    target_date: str | None = None,
    start_hour: int | None = None,
    end_hour: int | None = None,
    db: Session = Depends(get_db),
):

    day = datetime.strptime(target_date, "%Y-%m-%d").date() if target_date else date.today()
    events = _events_for_day(db, day)
    if not events:
        return {"date": day.isoformat(), "segments": []}

    lunch_window = _lunch_window(start_hour, end_hour)

    # Drop spurious non-away events that fall inside a real absence (e.g.
    # a coworker triggering pose detection during your lunch break). Same
    # treatment as /summary so the bar matches the breaks list.
    absences = _classify_absences(_pair_absences(events, day), lunch_window)
    events = _filter_events_outside_absences(events, absences)
    if not events:
        return {"date": day.isoformat(), "segments": []}

    end_of_day_local = datetime.combine(day, dtime.max, tzinfo=LOCAL_TZ)
    end_of_day = end_of_day_local.astimezone(timezone.utc)
    trailing_end = min(_now_utc(), end_of_day) if day == date.today() else end_of_day

    raw: list[dict] = []
    for i, e in enumerate(events):
        end_ts = events[i + 1].timestamp if i + 1 < len(events) else trailing_end
        if end_ts <= e.timestamp:
            continue
        raw.append({"activity": e.activity, "start": e.timestamp, "end": end_ts})

    merged: list[dict] = []
    for seg in raw:
        if merged and merged[-1]["activity"] == seg["activity"]:
            merged[-1]["end"] = seg["end"]
        else:
            merged.append(dict(seg))

    cleaned: list[dict] = []
    for seg in merged:
        dur = (seg["end"] - seg["start"]).total_seconds()
        if seg["activity"] == "away" and dur < NOISE_FLOOR_S and cleaned:
            cleaned[-1]["end"] = seg["end"]
            continue
        if cleaned and cleaned[-1]["activity"] == seg["activity"]:
            cleaned[-1]["end"] = seg["end"]
        else:
            cleaned.append(dict(seg))

    # For the timeline we deliberately do NOT clip to the work-hours
    # window here. The frontend draws its own window band and clips
    # visually — leaving the raw segments intact lets the client show
    # "extra" activity fading at the edges without a re-fetch. If we
    # later want strictly-clipped timeline output we can add an
    # additional pass; for now segments carry natural durations.
    segments = [
        {
            "activity": s["activity"],
            "start": s["start"].isoformat(),
            "end": s["end"].isoformat(),
            "duration_s": (s["end"] - s["start"]).total_seconds(),
        }
        for s in cleaned
    ]

    return {"date": day.isoformat(), "segments": segments}


@app.get("/weekly")
def get_weekly_summary(
    start_hour: int | None = None,
    end_hour: int | None = None,
    db: Session = Depends(get_db),
):
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    lunch_window = _lunch_window(start_hour, end_hour)
    result = []
    for i in range(5):
        day = monday + timedelta(days=i)
        window = _window_for_day(day, start_hour, end_hour)
        events = _events_for_day(db, day)
        absences = _classify_absences(_pair_absences(events, day), lunch_window)
        events = _filter_events_outside_absences(events, absences)
        sip_count = _coalesce_sips(events)

        def overlaps(a: dict) -> bool:
            if window is None:
                return True
            return _clip_seconds(a["start"], a["end"], window) > 0

        short_break = sum(1 for a in absences if a["category"] == "short_break" and overlaps(a))
        long_break = sum(1 for a in absences if a["category"] == "long_break" and overlaps(a))
        lunch = next((a for a in absences if a["category"] == "lunch" and overlaps(a)), None)
        lunch_dur_s = _clip_seconds(lunch["start"], lunch["end"], window) if lunch else 0.0
        result.append({
            "date": day.isoformat(),
            "sip_count": sip_count,
            "short_break_count": short_break,
            "long_break_count": long_break,
            "break_count": short_break + long_break,
            "lunch_duration_min": round(lunch_dur_s / 60, 1) if lunch else None,
        })
    return result


@app.get("/productivity")
def get_productivity(
    days: int = 90,
    start_hour: int | None = None,
    end_hour: int | None = None,
    db: Session = Depends(get_db),
):

    days = max(1, min(days, 365))
    today = date.today()
    out: list[dict] = []
    lunch_window = _lunch_window(start_hour, end_hour)

    for i in range(days - 1, -1, -1):
        day = today - timedelta(days=i)
        window = _window_for_day(day, start_hour, end_hour)
        events = _events_for_day(db, day)
        absences = _classify_absences(_pair_absences(events, day), lunch_window)
        events = _filter_events_outside_absences(events, absences)

        def overlaps(a: dict) -> bool:
            if window is None:
                return True
            return _clip_seconds(a["start"], a["end"], window) > 0

        short_break = sum(1 for a in absences if a["category"] == "short_break" and overlaps(a))
        long_break = sum(1 for a in absences if a["category"] == "long_break" and overlaps(a))
        lunch = next((a for a in absences if a["category"] == "lunch" and overlaps(a)), None)

        # Total minutes off-desk for the day. Includes lunch, short_break,
        # long_break. Excludes `noise` absences (sub-NOISE_FLOOR detection
        # glitches). Used by the frontend to compute the focus ratio.
        # When a work-hours window is set, break time is clipped to the
        # portion that falls INSIDE work hours — a 30-minute break that
        # straddles 5:00p only counts the minutes before 5:00p.
        break_total_s = 0.0
        for a in absences:
            if a.get("category") == "noise":
                continue
            if window is None:
                break_total_s += a["duration_s"]
            else:
                break_total_s += _clip_seconds(a["start"], a["end"], window)

        # Total minutes on phone for the day. Walks segments the same way
        # the live /summary does.
        phone_s = _activity_seconds(events, day, "phone", window)

        at_desk_s = 0.0
        for j, e in enumerate(events):
            if e.activity not in ("at_desk", "sipping"):
                continue
            if j + 1 < len(events):
                end_ts = events[j + 1].timestamp
            else:
                end_of_day_local = datetime.combine(day, dtime.max, tzinfo=LOCAL_TZ)
                end_of_day = end_of_day_local.astimezone(timezone.utc)
                end_ts = min(_now_utc(), end_of_day) if day == today else end_of_day
            if window is None:
                at_desk_s += max(0.0, (end_ts - e.timestamp).total_seconds())
            else:
                at_desk_s += _clip_seconds(e.timestamp, end_ts, window)

        lunch_dur_s = _clip_seconds(lunch["start"], lunch["end"], window) if lunch else 0.0

        out.append({
            "date": day.isoformat(),
            "break_count": short_break + long_break,
            "short_break_count": short_break,
            "long_break_count": long_break,
            "lunch_duration_min": round(lunch_dur_s / 60, 1) if lunch else None,
            "at_desk_min": round(at_desk_s / 60, 1),
            "break_total_min": round(break_total_s / 60, 1),
            "phone_min": round(phone_s / 60, 1),
        })

    return out
