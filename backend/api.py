from datetime import datetime, date, time as dtime, timedelta
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


# Tuning knobs for break classification.
NOISE_FLOOR_S = 60          # absences shorter than this are detection glitches, not breaks
BATHROOM_MAX_S = 6 * 60     # <= 6 min => bathroom
SHORT_BREAK_MAX_S = 20 * 60 # <= 20 min => short break
LUNCH_MIN_S = 20 * 60       # >= 20 min and in midday window => lunch candidate
LUNCH_WINDOW = (11, 15)     # [start_hour, end_hour) for lunch detection


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _events_for_day(db: Session, day: date) -> list[Event]:
    start = datetime.combine(day, dtime.min)
    end = start + timedelta(days=1)
    return (
        db.query(Event)
        .filter(Event.timestamp >= start, Event.timestamp < end)
        .order_by(Event.timestamp)
        .all()
    )


def _pair_absences(events: list[Event], day: date) -> list[dict]:
    """
    Walk transitions and emit one absence record per away→present pair.
    Open away segments are closed at end-of-day so the loop is bounded.
    """
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
        end_of_day = datetime.combine(day, dtime.max)
        # Cap an unclosed absence at end-of-day or "now", whichever is sooner.
        now = datetime.utcnow()
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
    """
    Tag every absence as noise / bathroom / short_break / long_break / lunch.
    The single longest midday absence >= LUNCH_MIN_S is lunch; everything else
    in that bucket becomes long_break.
    """
    classified = [dict(a) for a in absences]

    # Identify the one lunch candidate first.
    lunch_idx: int | None = None
    lunch_dur = 0.0
    for i, a in enumerate(classified):
        if a["duration_s"] < LUNCH_MIN_S:
            continue
        start_hour = a["start"].hour
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


@app.get("/summary")
def get_summary(target_date: str | None = None, db: Session = Depends(get_db)):
    day = datetime.strptime(target_date, "%Y-%m-%d").date() if target_date else date.today()
    events = _events_for_day(db, day)

    sip_count = sum(1 for e in events if e.activity == "sipping")
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
    """
    Return the day as contiguous segments of activity for a Gantt-style timeline.
    Each segment is {activity, start, end} where end is the next event's timestamp
    (or "now" / end-of-day for the trailing segment).
    """
    day = datetime.strptime(target_date, "%Y-%m-%d").date() if target_date else date.today()
    events = _events_for_day(db, day)
    if not events:
        return {"date": day.isoformat(), "segments": []}

    segments: list[dict] = []
    for i, e in enumerate(events):
        if i + 1 < len(events):
            end_ts = events[i + 1].timestamp
        else:
            end_of_day = datetime.combine(day, dtime.max)
            end_ts = min(datetime.utcnow(), end_of_day) if day == date.today() else end_of_day
        if end_ts <= e.timestamp:
            continue
        segments.append({
            "activity": e.activity,
            "start": e.timestamp.isoformat(),
            "end": end_ts.isoformat(),
            "duration_s": (end_ts - e.timestamp).total_seconds(),
        })

    return {"date": day.isoformat(), "segments": segments}


@app.get("/weekly")
def get_weekly_summary(db: Session = Depends(get_db)):
    """Per-day rollup for the last 7 days, reusing the same classification logic."""
    today = date.today()
    result = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        events = _events_for_day(db, day)
        sip_count = sum(1 for e in events if e.activity == "sipping")
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
    """
    Per-day rollup for a GitHub-contributions-style heatmap.
    Returns: [{ date, break_count, bathroom_count, short_break_count,
                long_break_count, lunch_duration_min, at_desk_min }]
    `at_desk_min` is total time logged as at-desk/sipping/stretching during
    the day, useful for filtering out days when the watcher wasn't running.
    """
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

        # Approximate at-desk minutes from segment durations (cheap pass).
        at_desk_s = 0.0
        for j, e in enumerate(events):
            if e.activity not in ("at_desk", "sipping", "stretching"):
                continue
            if j + 1 < len(events):
                end_ts = events[j + 1].timestamp
            else:
                end_of_day = datetime.combine(day, dtime.max)
                end_ts = min(datetime.utcnow(), end_of_day) if day == today else end_of_day
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
