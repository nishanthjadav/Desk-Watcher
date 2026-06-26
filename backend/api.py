from datetime import datetime, date, timedelta
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


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/events")
def get_events(target_date: str | None = None, db: Session = Depends(get_db)):
    """Return all events for a given date (defaults to today)."""
    if target_date:
        day = datetime.strptime(target_date, "%Y-%m-%d").date()
    else:
        day = date.today()

    start = datetime.combine(day, datetime.min.time())
    end = start + timedelta(days=1)

    events = (
        db.query(Event)
        .filter(Event.timestamp >= start, Event.timestamp < end)
        .order_by(Event.timestamp)
        .all()
    )
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
    """Return daily summary stats."""
    if target_date:
        day = datetime.strptime(target_date, "%Y-%m-%d").date()
    else:
        day = date.today()

    start = datetime.combine(day, datetime.min.time())
    end = start + timedelta(days=1)

    events = (
        db.query(Event)
        .filter(Event.timestamp >= start, Event.timestamp < end)
        .order_by(Event.timestamp)
        .all()
    )

    sip_count = sum(1 for e in events if e.activity == "sipping")

    # Calculate break durations by pairing "away" start with next "at_desk"
    breaks = []
    lunch_duration_min = None
    away_start = None

    for e in events:
        if e.activity == "away" and away_start is None:
            away_start = e.timestamp
        elif e.activity == "at_desk" and away_start is not None:
            duration_min = (e.timestamp - away_start).total_seconds() / 60
            # Classify as lunch if midday and long enough
            if 11 <= away_start.hour <= 14 and duration_min >= 20:
                lunch_duration_min = duration_min
            else:
                breaks.append(duration_min)
            away_start = None

    avg_break_min = round(sum(breaks) / len(breaks), 1) if breaks else 0

    return {
        "date": day.isoformat(),
        "sip_count": sip_count,
        "break_count": len(breaks),
        "avg_break_duration_min": avg_break_min,
        "lunch_duration_min": round(lunch_duration_min, 1) if lunch_duration_min else None,
        "total_events": len(events),
    }


@app.get("/weekly")
def get_weekly_summary(db: Session = Depends(get_db)):
    """Return per-day summary for the last 7 days."""
    today = date.today()
    result = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        # Reuse summary logic inline
        start = datetime.combine(day, datetime.min.time())
        end = start + timedelta(days=1)
        events = (
            db.query(Event)
            .filter(Event.timestamp >= start, Event.timestamp < end)
            .all()
        )
        sip_count = sum(1 for e in events if e.activity == "sipping")
        break_count = sum(1 for e in events if e.activity == "away")
        result.append({"date": day.isoformat(), "sip_count": sip_count, "break_count": break_count})
    return result
