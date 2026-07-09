"""
Tests for the watcher↔API status channel (status.py) and the /status
endpoint's staleness logic (api.py).

These deliberately avoid the `client` fixture's module-reload dance: they
monkeypatch status.STATUS_PATH to a tmp file so the round-trip is fully
isolated, then point the api module's status reader at the same file.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def test_write_then_read_round_trip(tmp_path, monkeypatch):
    import status

    monkeypatch.setattr(status, "STATUS_PATH", str(tmp_path / "status.json"))

    assert status.read_status() is None  # nothing written yet

    status.write_status(camera_ok=False, detail="Camera busy.")
    s = status.read_status()
    assert s is not None
    assert s["camera_ok"] is False
    assert s["detail"] == "Camera busy."
    assert "updated_at" in s
    assert isinstance(s["watcher_pid"], int)


def test_write_is_atomic_leaves_no_temp(tmp_path, monkeypatch):
    import status

    monkeypatch.setattr(status, "STATUS_PATH", str(tmp_path / "status.json"))
    status.write_status(camera_ok=True, detail="Camera active.")

    # Only the final file should remain — no stray .tmp files from the
    # write-temp-then-replace dance.
    leftovers = [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


def test_read_status_handles_corrupt_file(tmp_path, monkeypatch):
    import status

    path = tmp_path / "status.json"
    path.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(status, "STATUS_PATH", str(path))

    # Corrupt is indistinguishable from missing — both return None.
    assert status.read_status() is None


def test_status_endpoint_missing_file_is_stale(client, tmp_path, monkeypatch):
    import status

    monkeypatch.setattr(status, "STATUS_PATH", str(tmp_path / "nope.json"))
    resp = client.get("/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["camera_ok"] is None
    assert body["stale"] is True


def test_status_endpoint_fresh_is_not_stale(client, tmp_path, monkeypatch):
    import status

    monkeypatch.setattr(status, "STATUS_PATH", str(tmp_path / "status.json"))
    status.write_status(camera_ok=True, detail="Camera active.")

    body = client.get("/status").json()
    assert body["camera_ok"] is True
    assert body["stale"] is False
    assert body["detail"] == "Camera active."


def test_status_endpoint_old_timestamp_is_stale(client, tmp_path, monkeypatch):
    import status

    path = tmp_path / "status.json"
    old = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    path.write_text(
        json.dumps({"camera_ok": True, "detail": "stale", "updated_at": old}),
        encoding="utf-8",
    )
    monkeypatch.setattr(status, "STATUS_PATH", str(path))

    body = client.get("/status").json()
    # camera_ok was true, but a 5-minute-old heartbeat means the watcher
    # stopped writing — the UI should treat that as a problem.
    assert body["stale"] is True
