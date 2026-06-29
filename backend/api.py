from datetime import datetime, date, time as dtime, timedelta, timezone
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from database import SessionLocal, Event

app = FastAPI(title="Desk Watcher API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


NOISE_FLOOR_S = 60          # absences shorter than this are detection glitches, not breaks
BATHROOM_MAX_S = 6 * 60     # <= 6 min => bathroom
SHORT_BREAK_MAX_S = 20 * 60 # <= 20 min => short break
LUNCH_MIN_S = 20 * 60       # >= 20 min and in midday window => lunch candidate
LUNCH_WINDOW = (11, 15)     # [start_hour, end_hour) for lunch detection, LOCAL time

# Sips logged within this window of each other count as one drink. A single
# drink rarely happens as one continuous wrist-near-nose event — you raise
# the bottle, sip, lower slightly, sip again. Each crossing of the pose
# threshold is its own DB row, but a human would call it one sip.
SIP_COALESCE_GAP_S = 90


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

    absences: list[dict] = []
    away_start: datetime | None = None

    for e in events:
        if e.activity == "away":
            if away_start is None:
                away_start = e.timestamp
        else:
            if away_start is not None:
                absences.append({
                    "start": away_start,
                    "end": e.timestamp,
                    "duration_s": (e.timestamp - away_start).total_seconds(),
                })
                away_start = None

    if away_start is not None:
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


def _classify_absences(absences: list[dict]) -> list[dict]:

    classified = [dict(a) for a in absences]

    lunch_idx: int | None = None
    lunch_dur = 0.0
    for i, a in enumerate(classified):
        if a["duration_s"] < LUNCH_MIN_S:
            continue
        start_hour = _to_local(a["start"]).hour
        if not (LUNCH_WINDOW[0] <= start_hour < LUNCH_WINDOW[1]):
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
        elif d <= BATHROOM_MAX_S:
            a["category"] = "bathroom"
        elif d <= SHORT_BREAK_MAX_S:
            a["category"] = "short_break"
        else:
            a["category"] = "long_break"

    return classified


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


def _activity_seconds(events: list[Event], day: date, activity: str) -> float:
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
        total_s += max(0.0, (end_ts - e.timestamp).total_seconds())
    return total_s


@app.get("/summary")
def get_summary(target_date: str | None = None, db: Session = Depends(get_db)):
    day = datetime.strptime(target_date, "%Y-%m-%d").date() if target_date else date.today()
    events = _events_for_day(db, day)

    sip_count = _coalesce_sips(events)
    phone_count = sum(1 for e in events if e.activity == "phone")
    phone_seconds = _activity_seconds(events, day, "phone")
    absences = _classify_absences(_pair_absences(events, day))

    by_cat: dict[str, list[dict]] = {
        "bathroom": [], "short_break": [], "long_break": [], "lunch": [], "noise": [],
    }
    for a in absences:
        by_cat[a["category"]].append(a)

    real_breaks = by_cat["bathroom"] + by_cat["short_break"] + by_cat["long_break"]
    avg_break_s = (sum(a["duration_s"] for a in real_breaks) / len(real_breaks)) if real_breaks else 0

    lunch = by_cat["lunch"][0] if by_cat["lunch"] else None

    def serialize(a: dict) -> dict:
        return {
            "start": a["start"].isoformat(),
            "end": a["end"].isoformat(),
            "duration_min": round(a["duration_s"] / 60, 1),
            "category": a["category"],
        }

    return {
        "date": day.isoformat(),
        "sip_count": sip_count,
        "phone_count": phone_count,
        "phone_min": round(phone_seconds / 60, 1),
        "bathroom_count": len(by_cat["bathroom"]),
        "short_break_count": len(by_cat["short_break"]),
        "long_break_count": len(by_cat["long_break"]),
        "break_count": len(real_breaks),
        "avg_break_duration_min": round(avg_break_s / 60, 1),
        "lunch": {
            "start": lunch["start"].isoformat(),
            "end": lunch["end"].isoformat(),
            "duration_min": round(lunch["duration_s"] / 60, 1),
        } if lunch else None,
        "absences": [serialize(a) for a in absences if a["category"] != "noise"],
        "total_events": len(events),
    }


@app.get("/timeline")
def get_timeline(target_date: str | None = None, db: Session = Depends(get_db)):

    day = datetime.strptime(target_date, "%Y-%m-%d").date() if target_date else date.today()
    events = _events_for_day(db, day)
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
def get_weekly_summary(db: Session = Depends(get_db)):
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    result = []
    for i in range(5):
        day = monday + timedelta(days=i)
        events = _events_for_day(db, day)
        sip_count = _coalesce_sips(events)
        absences = _classify_absences(_pair_absences(events, day))
        bathroom = sum(1 for a in absences if a["category"] == "bathroom")
        short_break = sum(1 for a in absences if a["category"] == "short_break")
        long_break = sum(1 for a in absences if a["category"] == "long_break")
        lunch = next((a for a in absences if a["category"] == "lunch"), None)
        result.append({
            "date": day.isoformat(),
            "sip_count": sip_count,
            "bathroom_count": bathroom,
            "short_break_count": short_break,
            "long_break_count": long_break,
            "break_count": bathroom + short_break + long_break,
            "lunch_duration_min": round(lunch["duration_s"] / 60, 1) if lunch else None,
        })
    return result


@app.get("/productivity")
def get_productivity(days: int = 90, db: Session = Depends(get_db)):

    days = max(1, min(days, 365))
    today = date.today()
    out: list[dict] = []

    for i in range(days - 1, -1, -1):
        day = today - timedelta(days=i)
        events = _events_for_day(db, day)
        absences = _classify_absences(_pair_absences(events, day))
        bathroom = sum(1 for a in absences if a["category"] == "bathroom")
        short_break = sum(1 for a in absences if a["category"] == "short_break")
        long_break = sum(1 for a in absences if a["category"] == "long_break")
        lunch = next((a for a in absences if a["category"] == "lunch"), None)

      
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
            at_desk_s += max(0.0, (end_ts - e.timestamp).total_seconds())

        out.append({
            "date": day.isoformat(),
            "break_count": bathroom + short_break + long_break,
            "bathroom_count": bathroom,
            "short_break_count": short_break,
            "long_break_count": long_break,
            "lunch_duration_min": round(lunch["duration_s"] / 60, 1) if lunch else None,
            "at_desk_min": round(at_desk_s / 60, 1),
        })

    return out
