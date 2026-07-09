"""
Shared watcher↔API status channel.

The watcher and the API run as two separate PyInstaller sidecars, so they
can't share in-process state. This module is the tiny bridge between them:
the watcher writes a status file, the API reads it and exposes it via
`GET /status` for the dashboard to poll.

The file lives next to the SQLite DB (same per-user appdata directory), so
we reuse `Config().db_path`'s directory rather than duplicating the
platform-specific path logic that lives in config.py.
"""

import json
import os
import tempfile
from datetime import datetime, timezone

from config import Config

_config = Config()
STATUS_PATH = os.path.join(os.path.dirname(_config.db_path), "status.json")


def write_status(camera_ok: bool, detail: str) -> None:
    """
    Atomically write the current watcher status.

    Atomic (write-temp + os.replace) so a reader in the API process never
    observes a half-written file. Best-effort: a write failure must never
    take down the watcher's main loop, so all errors are swallowed.
    """
    payload = {
        "camera_ok": camera_ok,
        "detail": detail,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "watcher_pid": os.getpid(),
    }
    try:
        os.makedirs(os.path.dirname(STATUS_PATH), exist_ok=True)
        # Write to a temp file in the same dir (so os.replace is atomic — a
        # cross-filesystem rename would not be) then swap it into place.
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(STATUS_PATH), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            os.replace(tmp, STATUS_PATH)
        except Exception:
            # Clean up the temp file if the swap failed.
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception:
        # Status reporting is diagnostic, not load-bearing. Never crash the
        # watcher because we couldn't write a status file.
        pass


def read_status() -> dict | None:
    """
    Read the current watcher status, or None if it's absent/unreadable.

    None means "unknown" — the API treats that as the watcher still starting
    up, not as an error. Callers should not distinguish "file missing" from
    "file corrupt"; both are equally uninformative.
    """
    try:
        with open(STATUS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
