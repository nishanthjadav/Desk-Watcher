"""
Record a session of pose keypoints to CSV with live activity labels.

Uses MediaPipe's task-based Pose Landmarker API (same as backend/watcher.py),
not the legacy mp.solutions.pose which was removed in MediaPipe 0.10+.

Labels are toggled at record time, NOT in a post-hoc tool. This is the
big-win UX: a 25-minute deliberate recording with clean per-frame labels
beats 2 hours of unlabeled "natural" data, because class balance matters
far more than total volume for a small CNN.

Hotkeys (press to toggle the active label — sticky until changed):
    1   at_desk    (default at startup)
    2   sipping
    3   phone
    q   stop recording early

`away` is NOT a key. When you leave the camera's view, MediaPipe stops
detecting a pose and no rows are written for those frames — `away` is
the natural state of "no data in the recording," handled separately
by the live watcher's no-pose check.

Output CSV format:
    timestamp, label, lm0_x, lm0_y, lm0_v, ..., lm32_v

Usage:
    python collect_data.py --duration 900 --output ../data/sessions/session_001.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision


LANDMARK_COUNT = 33

# Default pose model location: backend/models/pose_landmarker_lite.task,
# resolved relative to the repo root (one up from this file's directory).
DEFAULT_POSE_MODEL = Path(__file__).resolve().parent.parent / "backend" / "models" / "pose_landmarker_lite.task"

# Active-label key bindings. The default at session start is "at_desk" —
# the most-common activity. Any key here switches the sticky label.
LABEL_KEYS = {
    ord("1"): "at_desk",
    ord("2"): "sipping",
    ord("3"): "phone",
}

# Per-label preview colors (BGR) — matches the frontend timeline palette.
LABEL_COLOR = {
    "at_desk": (12, 138, 224),    # amber
    "sipping": (74, 192, 247),    # light amber
    "phone":   (32, 64, 160),     # rust
}


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--duration", type=int, default=900, help="Recording duration in seconds (default 900 = 15 min)")
    p.add_argument("--output", required=True, help="Output CSV path")
    p.add_argument("--camera", type=int, default=0)
    p.add_argument(
        "--pose-model",
        type=Path,
        default=DEFAULT_POSE_MODEL,
        help=f"Path to the MediaPipe pose model (default: {DEFAULT_POSE_MODEL})",
    )
    return p.parse_args()


def build_landmarker(model_path: Path) -> mp_vision.PoseLandmarker:
    if not model_path.exists():
        raise SystemExit(
            f"Pose model not found at {model_path}.\n"
            f"Run: cd backend && python download_models.py"
        )
    options = mp_vision.PoseLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=str(model_path)),
        running_mode=mp_vision.RunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=0.6,
        min_tracking_confidence=0.5,
    )
    return mp_vision.PoseLandmarker.create_from_options(options)


def draw_label_hud(frame, label: str, remaining_s: int, rows_written: int, per_label_counts: dict[str, int]) -> None:
    """
    Draw an unmissable colored bar at the top of the preview with the
    current label name, plus a status line at the bottom with timing
    and per-class counts. The point is that you can NEVER lose track
    of which label you're recording.
    """
    h, w = frame.shape[:2]
    color = LABEL_COLOR.get(label, (200, 200, 200))

    # Top banner: solid colored strip with the label name in large text.
    cv2.rectangle(frame, (0, 0), (w, 50), color, -1)
    cv2.putText(
        frame, f"  ● {label.upper()}",
        (10, 36), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA,
    )
    # Hotkey reminder on the right side of the banner.
    cv2.putText(
        frame, "1=at_desk  2=sipping  3=phone  q=quit",
        (w - 420, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA,
    )

    # Bottom strip: remaining time + per-class frame counts.
    cv2.rectangle(frame, (0, h - 36), (w, h), (32, 32, 32), -1)
    cv2.putText(
        frame,
        f"{remaining_s}s left   total {rows_written} frames",
        (10, h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (220, 220, 220), 1, cv2.LINE_AA,
    )
    # Per-class counts on the right, color-coded.
    x = w - 380
    for lbl in ("at_desk", "sipping", "phone"):
        c = per_label_counts.get(lbl, 0)
        cv2.rectangle(frame, (x, h - 24), (x + 10, h - 14), LABEL_COLOR[lbl], -1)
        cv2.putText(
            frame, f"{lbl} {c}",
            (x + 16, h - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (220, 220, 220), 1, cv2.LINE_AA,
        )
        x += 120


def main():
    args = parse_args()
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # CSV header now includes the label column right after the timestamp.
    header = ["timestamp", "label"] + [
        f"lm{i}_{axis}" for i in range(LANDMARK_COUNT) for axis in ("x", "y", "v")
    ]

    cap = cv2.VideoCapture(args.camera)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    start = time.time()
    rows_written = 0
    active_label = "at_desk"  # sticky; toggled by key press
    per_label_counts = {lbl: 0 for lbl in LABEL_KEYS.values()}

    with open(out_path, "w", newline="") as f, build_landmarker(args.pose_model) as landmarker:
        writer = csv.writer(f)
        writer.writerow(header)
        print(f"Recording for {args.duration}s → {out_path}")
        print("Press 1/2/3 to switch label, Q to stop early.")
        print(f"Starting label: {active_label}")

        while cap.isOpened():
            elapsed = time.time() - start
            if elapsed >= args.duration:
                break

            ret, frame = cap.read()
            if not ret:
                break

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            ts_ms = int(time.time() * 1000)
            result = landmarker.detect_for_video(mp_image, ts_ms)

            # The new task-based API returns a list-of-lists (one per detected
            # person). num_poses=1 means we only ever look at index 0.
            # Frames without pose data are NOT written — "away" is captured
            # by the absence of rows, not by a label.
            if result.pose_landmarks:
                lm = result.pose_landmarks[0]
                row = [elapsed, active_label] + [
                    val for point in lm for val in (point.x, point.y, point.visibility)
                ]
                writer.writerow(row)
                rows_written += 1
                per_label_counts[active_label] += 1

            remaining = int(args.duration - elapsed)
            draw_label_hud(frame, active_label, remaining, rows_written, per_label_counts)
            cv2.imshow("Recording", frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key in LABEL_KEYS:
                new_label = LABEL_KEYS[key]
                if new_label != active_label:
                    active_label = new_label
                    print(f"  [{int(elapsed)}s] → {active_label}")

    cap.release()
    cv2.destroyAllWindows()

    print(f"\nDone. Wrote {rows_written} frames to {out_path}")
    print("Per-class breakdown:")
    for lbl, c in per_label_counts.items():
        pct = (c / rows_written * 100) if rows_written else 0
        print(f"  {lbl:10} {c:6} frames  ({pct:5.1f}%)")


if __name__ == "__main__":
    main()
