"""
Interactive labeling tool for pose-recording CSVs from collect_data.py.

Usage:
    python label_data.py path/to/session_001.csv

What it does
------------
Loads a CSV of pose landmarks captured by `collect_data.py` and lets you
attach an activity label to each frame using keyboard shortcuts. Labels
are saved to a SIDECAR file (`<session>.labels.csv`) — the original
recording is treated as immutable raw data.

UX contract: "anchor then commit"
---------------------------------
Labeling a multi-second range with one keystroke per boundary, not per
frame. Concretely:

    1) Scrub to frame N. Press `1` (at_desk).
       → an anchor is set at frame N; the HUD shows "anchor=N activity=at_desk".
    2) Scrub to frame M.
       → pressing the SAME label key (`1`) commits [N, M) as at_desk.
       → pressing a DIFFERENT label key (e.g. `3`) commits [N, M) as at_desk
         AND immediately sets a new anchor at M for the new activity.

This second case is the quick-chain shortcut for transitions: most label
sessions look like long at_desk runs broken by sip/phone bursts, so you
press `1`, scrub to the sip, press `2`, scrub to the end of the sip,
press `1`, and so on — one keystroke per state boundary.

Hotkeys
-------
    1 / 2 / 3 / 4   set anchor or commit range — at_desk / sipping / phone / away
    0               clear the label on the current frame
    Shift+0         clear any label inside the active anchor range
    Esc             cancel the current anchor
    ← / →           step back/forward one frame
    Shift+← / →     jump 30 frames (~3 seconds at 10fps)
    Home / End      jump to first / last frame
    PgUp / PgDn     jump to previous / next labeled-region boundary
    u               undo last label commit
    s               save (also happens automatically on every commit)
    q / Esc-Esc     quit
"""
from __future__ import annotations

import argparse
import csv
import os
import shutil
import sys
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

# cv2 and numpy are loaded lazily inside main() so the data-layer helpers
# (load_csv, save_labels, commit_range, undo, etc.) can be imported and
# tested without OpenCV present. The render functions reference these
# globals, which get filled in before any rendering happens.
cv2 = None  # type: ignore[assignment]
np = None   # type: ignore[assignment]


# ─── Data shapes ────────────────────────────────────────────────────────────

LANDMARK_COUNT = 33
# Body skeleton (kept in sync with backend/watcher.py POSE_CONNECTIONS).
POSE_CONNECTIONS = [
    (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
    (11, 23), (12, 24), (23, 24),
    (23, 25), (25, 27), (27, 29), (29, 31), (27, 31),
    (24, 26), (26, 28), (28, 30), (30, 32), (28, 32),
]
# MediaPipe face landmarks 0..10. Coarse facial layout — useful to see head pose.
FACE_LANDMARKS = list(range(0, 11))
FACE_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 7),
    (0, 4), (4, 5), (5, 6), (6, 8),
    (9, 10),
]

# Activity vocabulary — must match backend/classifier.py ACTIVITIES.
ACTIVITIES = ["at_desk", "sipping", "phone", "away"]
ACTIVITY_KEY = {ord("1"): "at_desk", ord("2"): "sipping", ord("3"): "phone", ord("4"): "away"}
# BGR colors — bright enough to read on the dark canvas.
ACTIVITY_COLOR = {
    "at_desk":  (12, 138, 224),   # amber
    "sipping":  (74, 192, 247),   # light amber
    "phone":    (32, 64, 160),    # rust red
    "away":     (70, 70, 70),     # dark gray
}
UNLABELED_COLOR = (40, 40, 40)
ANCHOR_COLOR = (255, 255, 255)
CURSOR_COLOR = (200, 255, 200)


# ─── Canvas geometry ────────────────────────────────────────────────────────

CANVAS_W = 1100
POSE_H = 540           # tall enough to show full body with margins
TIMELINE_H = 32
HUD_H = 110
PADDING = 12
TOTAL_H = POSE_H + TIMELINE_H + HUD_H + PADDING * 4
BG_COLOR = (24, 22, 20)


# ─── Frame data ─────────────────────────────────────────────────────────────

@dataclass
class Frame:
    """One row of the pose CSV."""
    timestamp: float
    # Flat list of 99 floats (x, y, visibility per landmark).
    landmarks: list[float]


@dataclass
class Session:
    """The full loaded CSV plus the label vector and tool state."""
    csv_path: Path
    labels_path: Path
    frames: list[Frame] = field(default_factory=list)
    # Parallel to `frames`. None means unlabeled.
    labels: list[str | None] = field(default_factory=list)

    cursor: int = 0
    anchor: int | None = None
    anchor_activity: str | None = None

    # Undo stack: each entry is (start, end, prior_labels_slice). Bounded
    # so we don't grow forever during a long session.
    history: deque = field(default_factory=lambda: deque(maxlen=64))
    dirty: bool = False


# ─── Load / save ────────────────────────────────────────────────────────────

def load_csv(csv_path: Path) -> list[Frame]:
    frames: list[Frame] = []
    with open(csv_path, newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        if header[0] != "timestamp":
            raise SystemExit(f"Unexpected CSV: first column must be 'timestamp', got {header[0]!r}")
        for row in reader:
            if not row:
                continue
            ts = float(row[0])
            landmarks = [float(v) for v in row[1:]]
            if len(landmarks) != LANDMARK_COUNT * 3:
                raise SystemExit(
                    f"Row has {len(landmarks)} landmark values, expected {LANDMARK_COUNT * 3}. "
                    f"Is this a session from collect_data.py?"
                )
            frames.append(Frame(timestamp=ts, landmarks=landmarks))
    if not frames:
        raise SystemExit(f"{csv_path}: no rows.")
    return frames


def load_labels(labels_path: Path, n_frames: int) -> list[str | None]:
    labels: list[str | None] = [None] * n_frames
    if not labels_path.exists():
        return labels
    with open(labels_path, newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        # Permissive: accept either ["row","label"] or ["index","label"].
        for row in reader:
            if len(row) < 2:
                continue
            try:
                idx = int(row[0])
            except ValueError:
                continue
            if 0 <= idx < n_frames and row[1] in ACTIVITIES:
                labels[idx] = row[1]
    return labels


def save_labels(session: Session) -> None:
    """Atomic write: tmp file → fsync → rename."""
    tmp = session.labels_path.with_suffix(session.labels_path.suffix + ".tmp")
    with open(tmp, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["row", "label"])
        for i, lbl in enumerate(session.labels):
            if lbl is not None:
                writer.writerow([i, lbl])
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, session.labels_path)
    session.dirty = False


def backup_once(csv_path: Path) -> None:
    """Make a one-time backup of the raw CSV so we can always recover."""
    backup = csv_path.with_suffix(csv_path.suffix + ".bak")
    if not backup.exists():
        shutil.copy2(csv_path, backup)


# ─── Pose rendering ─────────────────────────────────────────────────────────

def _lm_xy(landmarks: list[float], idx: int) -> tuple[float, float] | None:
    """Return (x, y) for landmark idx, or None if low visibility."""
    base = idx * 3
    vis = landmarks[base + 2] if base + 2 < len(landmarks) else 0.0
    if vis < 0.1:
        return None
    return landmarks[base], landmarks[base + 1]


def render_pose(canvas: np.ndarray, frame: Frame, wrist_trail: list[tuple[float, float, float, float]]) -> None:
    """
    Draw the stick figure into `canvas` (which is the pose region, already
    cleared to BG_COLOR). `wrist_trail` is the previous ~6 frames'
    (left_x, left_y, right_x, right_y) tuples for fading wrist trails —
    makes sip/phone motion visible at a single still.
    """
    h, w = canvas.shape[:2]

    def to_px(x: float, y: float) -> tuple[int, int]:
        # Letterbox into a square at the center so portrait/landscape
        # framings both look right.
        side = min(w, h) - 40
        ox = (w - side) // 2
        oy = (h - side) // 2
        return (ox + int(x * side), oy + int(y * side))

    # Wrist trails (oldest = dimmest). Draw before joints so the dots
    # don't overlap the bright wrist markers.
    for age, (lx, ly, rx, ry) in enumerate(wrist_trail):
        # `age=0` is oldest; brighten as age grows toward current.
        falloff = (age + 1) / max(1, len(wrist_trail))
        alpha = int(50 + 150 * falloff)
        color = (0, alpha, alpha)  # cyan-ish
        for x, y in [(lx, ly), (rx, ry)]:
            if 0 <= x <= 1 and 0 <= y <= 1:
                cv2.circle(canvas, to_px(x, y), 3, color, -1, lineType=cv2.LINE_AA)

    # Body skeleton.
    for a, b in POSE_CONNECTIONS:
        pa, pb = _lm_xy(frame.landmarks, a), _lm_xy(frame.landmarks, b)
        if pa and pb:
            cv2.line(canvas, to_px(*pa), to_px(*pb), (110, 200, 110), 2, lineType=cv2.LINE_AA)

    # Face mesh — light blue, thinner.
    for a, b in FACE_CONNECTIONS:
        pa, pb = _lm_xy(frame.landmarks, a), _lm_xy(frame.landmarks, b)
        if pa and pb:
            cv2.line(canvas, to_px(*pa), to_px(*pb), (220, 180, 90), 1, lineType=cv2.LINE_AA)

    # Joints.
    for i in range(LANDMARK_COUNT):
        p = _lm_xy(frame.landmarks, i)
        if not p:
            continue
        # Wrists (15, 16) get the highlight color since sip/phone hinges on them.
        if i in (15, 16):
            cv2.circle(canvas, to_px(*p), 6, (90, 220, 255), -1, lineType=cv2.LINE_AA)
        elif i in FACE_LANDMARKS:
            cv2.circle(canvas, to_px(*p), 2, (220, 180, 90), -1, lineType=cv2.LINE_AA)
        else:
            cv2.circle(canvas, to_px(*p), 3, (90, 160, 90), -1, lineType=cv2.LINE_AA)


def render_timeline(canvas: np.ndarray, session: Session) -> None:
    """One pixel column per frame, colored by label. Cursor + anchor overlaid."""
    h, w = canvas.shape[:2]
    n = len(session.frames)
    if n == 0:
        return

    # Quantize frame index to column index.
    for col in range(w):
        # Use a range of frames per pixel so very long sessions still fit.
        f_start = int(col * n / w)
        f_end = max(f_start + 1, int((col + 1) * n / w))
        # If ANY frame in this pixel column is labeled, use the most-frequent label.
        bucket = session.labels[f_start:f_end]
        labeled = [lbl for lbl in bucket if lbl is not None]
        if labeled:
            # majority pick
            color = ACTIVITY_COLOR[max(set(labeled), key=labeled.count)]
        else:
            color = UNLABELED_COLOR
        canvas[:, col] = color

    # Cursor.
    cursor_col = int(session.cursor * w / max(1, n))
    cv2.line(canvas, (cursor_col, 0), (cursor_col, h - 1), CURSOR_COLOR, 1, lineType=cv2.LINE_AA)

    # Anchor (if any).
    if session.anchor is not None:
        anchor_col = int(session.anchor * w / max(1, n))
        cv2.line(canvas, (anchor_col, 0), (anchor_col, h - 1), ANCHOR_COLOR, 1, lineType=cv2.LINE_AA)
        # Shade the range between anchor and cursor.
        lo, hi = sorted((anchor_col, cursor_col))
        if hi > lo:
            overlay = canvas.copy()
            cv2.rectangle(overlay, (lo, 0), (hi, h - 1), ANCHOR_COLOR, -1)
            cv2.addWeighted(overlay, 0.18, canvas, 0.82, 0, dst=canvas)


def render_hud(canvas: np.ndarray, session: Session) -> None:
    """Frame counter, anchor info, label legend."""
    cv2.rectangle(canvas, (0, 0), (canvas.shape[1], canvas.shape[0]), BG_COLOR, -1)
    n = len(session.frames)
    cur = session.cursor

    cur_label = session.labels[cur] if 0 <= cur < n else None
    cur_label_str = cur_label or "—"
    pct = (cur / max(1, n - 1)) * 100

    cv2.putText(canvas, f"Frame {cur:>6} / {n - 1}   ({pct:5.1f}%)   label: {cur_label_str}",
                (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (220, 220, 220), 1, cv2.LINE_AA)

    anchor_str = (
        f"anchor @ {session.anchor}  activity={session.anchor_activity}"
        if session.anchor is not None
        else "no anchor"
    )
    cv2.putText(canvas, anchor_str, (12, 54),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (180, 220, 255), 1, cv2.LINE_AA)

    # Activity legend with hotkeys and counts.
    counts = {a: 0 for a in ACTIVITIES}
    for lbl in session.labels:
        if lbl in counts:
            counts[lbl] += 1
    total = max(1, sum(counts.values()))
    legend_y = 80
    x = 12
    for i, a in enumerate(ACTIVITIES):
        color = ACTIVITY_COLOR[a]
        cv2.rectangle(canvas, (x, legend_y - 10), (x + 14, legend_y + 2), color, -1)
        cv2.putText(canvas, f"{i+1} {a}  {counts[a]} ({counts[a]*100/total:.0f}%)",
                    (x + 20, legend_y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1, cv2.LINE_AA)
        x += 200

    dirty = "● UNSAVED" if session.dirty else "saved"
    cv2.putText(canvas, dirty, (canvas.shape[1] - 110, 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                (90, 200, 255) if session.dirty else (120, 200, 120), 1, cv2.LINE_AA)


# ─── Labeling operations ────────────────────────────────────────────────────

def push_history(session: Session, start: int, end: int) -> None:
    """Snapshot labels[start:end] for undo."""
    session.history.append((start, end, list(session.labels[start:end])))


def commit_range(session: Session, start: int, end: int, activity: str) -> None:
    """Label half-open [start, end) with `activity`. start < end required."""
    if end <= start:
        return
    push_history(session, start, end)
    for i in range(start, end):
        session.labels[i] = activity
    session.dirty = True


def clear_range(session: Session, start: int, end: int) -> None:
    if end <= start:
        return
    push_history(session, start, end)
    for i in range(start, end):
        session.labels[i] = None
    session.dirty = True


def undo(session: Session) -> None:
    if not session.history:
        return
    start, end, prior = session.history.pop()
    for i, lbl in enumerate(prior):
        session.labels[start + i] = lbl
    session.dirty = True


def jump_to_label_boundary(session: Session, direction: int) -> int:
    """
    Return the index of the next/previous label-boundary frame, where a
    boundary is a frame whose label differs from its neighbor.
    `direction` = +1 (forward) or -1 (back).
    """
    cur = session.cursor
    n = len(session.frames)
    i = cur + direction
    while 0 <= i < n:
        prev = session.labels[i - 1] if i - 1 >= 0 else None
        if session.labels[i] != prev:
            return i
        i += direction
    return max(0, min(cur, n - 1))


# ─── Main loop ──────────────────────────────────────────────────────────────

WINDOW_TITLE = "Desk Watcher labeler"

# OpenCV waitKey codes for arrows / shifted arrows are platform-dependent.
# We accept the common Windows values; on other platforms `q` and `s` and
# the number keys are reliable, and arrows still work for plain step.
KEY_LEFT = 2424832
KEY_RIGHT = 2555904
KEY_SHIFT_LEFT = 2162689   # (varies)
KEY_SHIFT_RIGHT = 2293761
KEY_HOME = 2359296
KEY_END = 2293760
KEY_PGUP = 2162688
KEY_PGDN = 2228224
KEY_ESC = 27
KEY_ENTER = 13


def step_cursor(session: Session, delta: int) -> None:
    n = len(session.frames)
    session.cursor = max(0, min(n - 1, session.cursor + delta))


def handle_label_key(session: Session, activity: str) -> None:
    """
    Anchor-then-commit semantics:
      - No anchor: set an anchor at the current frame for this activity.
      - Anchor + same activity: commit [anchor, cursor] (inclusive of
        cursor — feels more natural for label boundaries) as that activity.
      - Anchor + different activity: commit the existing anchored range
        with its existing activity, then set a new anchor for this activity.
    """
    cur = session.cursor

    # No anchor → drop one.
    if session.anchor is None:
        session.anchor = cur
        session.anchor_activity = activity
        return

    # Anchor exists. Commit the range first.
    lo, hi = sorted((session.anchor, cur))
    commit_range(session, lo, hi + 1, session.anchor_activity or activity)

    if activity == session.anchor_activity:
        # Closing the range with the same key. Clear anchor.
        session.anchor = None
        session.anchor_activity = None
    else:
        # Chain: new anchor at current frame for the new activity.
        session.anchor = cur
        session.anchor_activity = activity


def main() -> int:
    global cv2, np
    import cv2 as _cv2
    import numpy as _np
    cv2 = _cv2
    np = _np

    parser = argparse.ArgumentParser(description="Label a pose-recording CSV.")
    parser.add_argument("csv", type=Path, help="Path to session CSV from collect_data.py")
    args = parser.parse_args()

    csv_path: Path = args.csv
    if not csv_path.exists():
        raise SystemExit(f"No such file: {csv_path}")
    labels_path = csv_path.with_suffix(".labels.csv")

    print(f"Loading {csv_path}...")
    frames = load_csv(csv_path)
    labels = load_labels(labels_path, len(frames))
    n_loaded = sum(1 for lbl in labels if lbl is not None)
    print(f"  {len(frames)} frames, {n_loaded} pre-labeled")
    backup_once(csv_path)

    session = Session(csv_path=csv_path, labels_path=labels_path, frames=frames, labels=labels)
    wrist_trail: deque = deque(maxlen=6)

    # One persistent canvas; subregions are slices into it.
    full_canvas = np.zeros((TOTAL_H, CANVAS_W, 3), dtype=np.uint8)
    pose_region = full_canvas[PADDING:PADDING + POSE_H, PADDING:CANVAS_W - PADDING]
    timeline_region = full_canvas[
        PADDING * 2 + POSE_H:PADDING * 2 + POSE_H + TIMELINE_H,
        PADDING:CANVAS_W - PADDING,
    ]
    hud_region = full_canvas[
        PADDING * 3 + POSE_H + TIMELINE_H:PADDING * 3 + POSE_H + TIMELINE_H + HUD_H,
        PADDING:CANVAS_W - PADDING,
    ]

    cv2.namedWindow(WINDOW_TITLE, cv2.WINDOW_AUTOSIZE)

    print("\nReady. Press ? for hotkey reminder. q to quit, s to save.\n")

    while True:
        # Update wrist trail from a small look-behind window.
        wrist_trail.clear()
        for off in range(-6, 0):
            i = session.cursor + off
            if i < 0:
                continue
            lm = session.frames[i].landmarks
            lw = _lm_xy(lm, 15)
            rw = _lm_xy(lm, 16)
            if lw and rw:
                wrist_trail.append((lw[0], lw[1], rw[0], rw[1]))

        # Render.
        full_canvas[:] = BG_COLOR
        pose_region[:] = BG_COLOR
        render_pose(pose_region, session.frames[session.cursor], list(wrist_trail))
        render_timeline(timeline_region, session)
        render_hud(hud_region, session)
        cv2.imshow(WINDOW_TITLE, full_canvas)

        key = cv2.waitKeyEx(0)  # blocking; tool is event-driven, not animated
        if key == -1:
            continue

        # ASCII keys.
        if key in (ord("q"),):
            if session.dirty:
                save_labels(session)
                print("Saved on quit.")
            break
        if key == ord("s"):
            save_labels(session)
            print(f"Saved → {labels_path}")
            continue
        if key in ACTIVITY_KEY:
            handle_label_key(session, ACTIVITY_KEY[key])
            save_labels(session)
            continue
        if key == ord("0"):
            clear_range(session, session.cursor, session.cursor + 1)
            save_labels(session)
            continue
        if key == ord(")"):  # Shift+0 on US layout
            if session.anchor is not None:
                lo, hi = sorted((session.anchor, session.cursor))
                clear_range(session, lo, hi + 1)
                session.anchor = None
                session.anchor_activity = None
                save_labels(session)
            continue
        if key == ord("u"):
            undo(session)
            save_labels(session)
            continue
        if key == KEY_ESC:
            if session.anchor is not None:
                session.anchor = None
                session.anchor_activity = None
            else:
                if session.dirty:
                    save_labels(session)
                break
            continue

        # Arrow / nav keys.
        if key == KEY_LEFT:
            step_cursor(session, -1)
        elif key == KEY_RIGHT:
            step_cursor(session, 1)
        elif key == KEY_SHIFT_LEFT:
            step_cursor(session, -30)
        elif key == KEY_SHIFT_RIGHT:
            step_cursor(session, 30)
        elif key == KEY_HOME:
            session.cursor = 0
        elif key == KEY_END:
            session.cursor = len(session.frames) - 1
        elif key == KEY_PGUP:
            session.cursor = jump_to_label_boundary(session, -1)
        elif key == KEY_PGDN:
            session.cursor = jump_to_label_boundary(session, +1)
        # Fallback: WASD / hjkl for arrow keys (more portable than the
        # platform-specific waitKeyEx codes).
        elif key in (ord("a"), ord("h")):
            step_cursor(session, -1)
        elif key in (ord("d"), ord("l")):
            step_cursor(session, 1)
        elif key == ord("A"):
            step_cursor(session, -30)
        elif key == ord("D"):
            step_cursor(session, 30)

    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
