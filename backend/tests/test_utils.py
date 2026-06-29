"""
Shared test utilities. Lives at backend/tests/test_utils.py and is on
pytest's pythonpath (see pyproject.toml).

The fixture-style helpers (make_landmarks, seed_events) are imported
directly by test modules rather than going through `conftest.py`,
because some host Python installs already have a `tests` package on
sys.path and we don't want to fight that namespace.

Pytest *fixtures* (the @pytest.fixture-decorated functions) still live
in conftest.py — those are auto-discovered, no import needed.
"""
from __future__ import annotations

from datetime import datetime, timezone


# MediaPipe Pose landmark indices we actually exercise in tests. Mirrors
# the constants in classifier.py — duplicated intentionally so a rename
# on the source side surfaces as a test failure.
NOSE = 0
LEFT_EAR = 7
RIGHT_EAR = 8
LEFT_SHOULDER = 11
RIGHT_SHOULDER = 12
LEFT_WRIST = 15
RIGHT_WRIST = 16

LANDMARK_COUNT = 33


def make_landmarks(**overrides) -> list[float]:
    """
    Build a 99-float landmark vector (33 landmarks × (x, y, visibility)).

    By default every landmark sits at (0.5, 0.5, 1.0) — image center,
    fully visible. Pass landmark-name keyword arguments to override:

        make_landmarks(nose=(0.5, 0.30), left_wrist=(0.4, 0.7))
    """
    name_to_idx = {
        "nose": NOSE,
        "left_ear": LEFT_EAR,
        "right_ear": RIGHT_EAR,
        "left_shoulder": LEFT_SHOULDER,
        "right_shoulder": RIGHT_SHOULDER,
        "left_wrist": LEFT_WRIST,
        "right_wrist": RIGHT_WRIST,
    }

    arr = [0.5, 0.5, 1.0] * LANDMARK_COUNT
    for name, value in overrides.items():
        if name not in name_to_idx:
            raise KeyError(f"Unknown landmark name: {name}")
        idx = name_to_idx[name]
        if len(value) == 2:
            x, y = value
            vis = 1.0
        else:
            x, y, vis = value
        base = idx * 3
        arr[base] = x
        arr[base + 1] = y
        arr[base + 2] = vis
    return arr


def seed_events(database_module, rows: list[tuple[datetime, str]]) -> None:
    """
    Insert events directly into the test DB, bypassing log_event so we
    can stamp arbitrary timestamps for fixture days. Tests pass
    timezone-AWARE datetimes; we strip the tz before insert because
    SQLite's DATETIME column stores naive strings (matches what real
    `log_event` does after `datetime.now(timezone.utc)`).
    """
    db = database_module.SessionLocal()
    try:
        for ts, activity in rows:
            if ts.tzinfo is not None:
                ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
            event = database_module.Event(
                activity=activity,
                confidence=1.0,
                timestamp=ts,
            )
            db.add(event)
        db.commit()
    finally:
        db.close()
