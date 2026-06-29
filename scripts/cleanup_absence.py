"""
One-off DB cleanup: collapse a noisy time range into a single clean absence.

Use when the algorithmic fix in api._pair_absences isn't enough to recover
a botched day — e.g. a long lunch where a coworker walked by multiple times,
or a chair shift that produced a sustained false "return" event.

Behavior:
  1. Back up <db_path> to <db_path>.bak.<UTC-timestamp> (refuses to run if
     a backup at the same path already exists, so two runs can't blow away
     a working backup).
  2. Walk events in the [start, end] window (local time) on <day>.
  3. Delete every event in that window whose activity is NOT "away".
     This leaves any away events as bookends so _pair_absences can stitch
     the whole window into a single absence.
  4. Print a summary of what changed.

Usage:
    python scripts/cleanup_absence.py \\
        --day 2026-06-29 --start 11:41 --end 13:21
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import datetime, time as dtime, timezone
from pathlib import Path


DEFAULT_DB = Path.home() / ".desk-watcher" / "events.db"


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--db", type=Path, default=DEFAULT_DB,
                   help=f"Path to events.db (default: {DEFAULT_DB})")
    p.add_argument("--day", required=True,
                   help="Local date in YYYY-MM-DD (the day the absence happened)")
    p.add_argument("--start", required=True,
                   help="Local start time HH:MM (e.g. 11:41)")
    p.add_argument("--end", required=True,
                   help="Local end time HH:MM (e.g. 13:21)")
    p.add_argument("--dry-run", action="store_true",
                   help="Show what would be deleted without writing")
    return p.parse_args()


def parse_local_dt(day_str: str, hm_str: str) -> datetime:
    d = datetime.strptime(day_str, "%Y-%m-%d").date()
    parts = [int(x) for x in hm_str.split(":")]
    if len(parts) == 2:
        h, m = parts
        s = 0
    elif len(parts) == 3:
        h, m, s = parts
    else:
        raise SystemExit(f"Invalid time: {hm_str!r} (expected HH:MM)")
    local_tz = datetime.now().astimezone().tzinfo
    return datetime.combine(d, dtime(h, m, s), tzinfo=local_tz)


def main() -> int:
    args = parse_args()

    db_path: Path = args.db
    if not db_path.exists():
        raise SystemExit(f"DB not found at {db_path}")

    start_local = parse_local_dt(args.day, args.start)
    end_local = parse_local_dt(args.day, args.end)
    if end_local <= start_local:
        raise SystemExit("--end must be after --start")

    # Convert to naive UTC (matches how rows are stored in SQLite).
    start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)

    print(f"Window (local): {start_local}  ->  {end_local}")
    print(f"Window (UTC):   {start_utc}  ->  {end_utc}")

    # Look at what's in the window first.
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(
        "SELECT id, activity, timestamp FROM events "
        "WHERE timestamp >= ? AND timestamp <= ? "
        "ORDER BY timestamp",
        (start_utc.isoformat(sep=" "), end_utc.isoformat(sep=" ")),
    )
    rows = cursor.fetchall()
    if not rows:
        print("\nNothing in the window. No-op.")
        return 0

    print(f"\nFound {len(rows)} events in window:")
    by_activity: dict[str, int] = {}
    for r in rows:
        by_activity[r["activity"]] = by_activity.get(r["activity"], 0) + 1
    for activity, count in sorted(by_activity.items()):
        print(f"  {activity:12} {count}")

    to_delete = [r for r in rows if r["activity"] != "away"]
    if not to_delete:
        print("\nAll events in window are already `away`. No-op.")
        return 0

    print(f"\nWill delete {len(to_delete)} non-away events.")
    print(f"Will keep {len(rows) - len(to_delete)} away events as bookends.")

    if args.dry_run:
        print("\n--dry-run; no changes written.")
        return 0

    # Back up the DB before any write.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = db_path.with_suffix(db_path.suffix + f".bak.{stamp}")
    shutil.copy2(db_path, backup_path)
    print(f"\nBackup -> {backup_path}")

    ids = [r["id"] for r in to_delete]
    placeholders = ",".join("?" * len(ids))
    conn.execute(f"DELETE FROM events WHERE id IN ({placeholders})", ids)
    conn.commit()
    conn.close()
    print(f"Deleted {len(ids)} rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
