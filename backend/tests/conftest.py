"""
Pytest fixtures for the backend test suite. Plain-Python helpers
(make_landmarks, seed_events) live in `test_utils.py` so they can be
imported directly by test modules; the @pytest.fixture functions here
are auto-discovered, no import needed.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Make `from classifier import ...` resolve when running pytest from the
# repo root with no pythonpath config (belt-and-suspenders alongside
# pyproject.toml).
BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# Point Config away from the real user DB at collection time so any
# stray import-side-effect (e.g. database.py creating its engine on
# first import) can't touch ~/.desk-watcher/events.db.
os.environ.setdefault("DB_PATH", str(BACKEND / "tests" / "_test_safety_default.db"))

from test_utils import make_landmarks  # noqa: E402  (after sys.path/env setup)


# ── Posture preset fixtures ───────────────────────────────────────────────

@pytest.fixture
def upright_landmarks() -> list[float]:
    """Nose well above shoulders; hands at desk height. The 'normal sitting' baseline."""
    return make_landmarks(
        nose=(0.50, 0.30),
        left_ear=(0.45, 0.30),
        right_ear=(0.55, 0.30),
        left_shoulder=(0.40, 0.55),
        right_shoulder=(0.60, 0.55),
        left_wrist=(0.30, 0.65),
        right_wrist=(0.70, 0.65),
    )


@pytest.fixture
def head_down_landmarks() -> list[float]:
    """Chin-to-chest: nose below ear line, near shoulder line."""
    return make_landmarks(
        nose=(0.50, 0.50),
        left_ear=(0.45, 0.42),
        right_ear=(0.55, 0.42),
        left_shoulder=(0.40, 0.60),
        right_shoulder=(0.60, 0.60),
        left_wrist=(0.30, 0.65),
        right_wrist=(0.70, 0.65),
    )


@pytest.fixture
def phone_in_lap_landmarks() -> list[float]:
    """Both wrists low and close together in x; head upright."""
    return make_landmarks(
        nose=(0.50, 0.30),
        left_ear=(0.45, 0.30),
        right_ear=(0.55, 0.30),
        left_shoulder=(0.40, 0.55),
        right_shoulder=(0.60, 0.55),
        left_wrist=(0.48, 0.85),
        right_wrist=(0.55, 0.85),
    )


@pytest.fixture
def sipping_landmarks() -> list[float]:
    """One wrist within 0.15 of the nose."""
    return make_landmarks(
        nose=(0.50, 0.30),
        left_shoulder=(0.40, 0.55),
        right_shoulder=(0.60, 0.55),
        left_wrist=(0.30, 0.65),
        right_wrist=(0.55, 0.35),
    )


# ── FastAPI test client ───────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    """
    Yield a FastAPI TestClient backed by an isolated SQLite file. Each
    test gets its own DB so seeded events from one test never leak.

    We point DB_PATH at a per-test file BEFORE importing `database`/`api`
    so the engine is created against the test DB.
    """
    db_file = tmp_path / "events.db"
    monkeypatch.setenv("DB_PATH", str(db_file))

    # Force-reimport so the engine picks up the new DB_PATH.
    for mod in ("api", "database", "config"):
        sys.modules.pop(mod, None)

    import database  # noqa: WPS433 — late import is intentional
    import api as api_module  # noqa: WPS433

    from fastapi.testclient import TestClient

    def _override_get_db():
        db = database.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    api_module.app.dependency_overrides[api_module.get_db] = _override_get_db

    try:
        with TestClient(api_module.app) as c:
            # Expose modules so tests can seed events via SessionLocal
            # without re-importing them.
            c.database = database  # type: ignore[attr-defined]
            c.api = api_module  # type: ignore[attr-defined]
            yield c
    finally:
        api_module.app.dependency_overrides.clear()
