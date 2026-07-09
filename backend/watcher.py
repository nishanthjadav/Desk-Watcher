import os
import sys
import time

# status + config are pure-stdlib imports (no native deps), so we can import
# them BEFORE the heavy ML stack. That lets us catch a failing native import
# below and report it to the dashboard before the process dies.
from config import Config
import status

try:
    import cv2
    import numpy as np
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision as mp_vision
except (ImportError, OSError) as e:
    # On a machine missing the Visual C++ runtime, importing cv2/torch/
    # mediapipe raises a DLL-load failure here. Without this guard the
    # sidecar would die with a cryptic traceback that goes to the log and
    # nowhere the user can see. Report a specific, actionable message to
    # the status channel (which the dashboard surfaces) before re-raising.
    msg = str(e)
    if "DLL" in msg or "vcruntime" in msg.lower() or "_C" in msg:
        detail = (
            "Missing Visual C++ runtime. Install the Microsoft Visual C++ "
            "2015-2022 Redistributable (x64) and relaunch."
        )
    else:
        detail = f"Failed to load a required library: {msg}"
    status.write_status(camera_ok=False, detail=detail)
    print(f"[watcher] fatal import error: {detail}", file=sys.stderr)
    raise

from database import SessionLocal, log_event
from classifier import ActivityClassifier
from phone_detector import PhoneDetector

POSE_CONNECTIONS = [
    (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
    (11, 23), (12, 24), (23, 24),
    (23, 25), (25, 27), (27, 29), (29, 31), (27, 31),
    (24, 26), (26, 28), (28, 30), (30, 32), (28, 32),
]

config = Config()
try:
    classifier = ActivityClassifier(config.model_path)
    phone_detector = PhoneDetector(config.phone_model_path, conf_threshold=config.phone_conf_threshold)
except Exception as e:
    # Model load can fail on a frozen build if a dynamically-imported
    # dependency (e.g. an sklearn/scipy submodule the pickle references)
    # wasn't bundled, or if the weights file is missing. This happens at
    # module import, before main()'s supervisor loop, so report it to the
    # status channel here — otherwise the process dies silently and the
    # dashboard shows a permanently empty "loading" state with no clue why.
    detail = f"Failed to load the activity model: {e}"
    status.write_status(camera_ok=False, detail=detail)
    print(f"[watcher] fatal model-load error: {detail}", file=sys.stderr)
    raise
# Head-down and sip-pose trackers used to live here as inputs to the
# classifier's geometry short-circuits. The live classifier now runs on
# the trained model alone (with a YOLO cross-check on phone), so no
# rolling pose-feature tracking is needed.

frame_buffer: list[tuple[float, list]] = []

last_event: str = "unknown"
last_event_time: float = time.time()
in_frame: bool = False


_last_phone_visible: bool = False
_last_phone_bbox: tuple[float, float, float, float] | None = None
_last_phone_run_ts: float = 0.0
_frames_since_phone_run: int = 0

# Throttle for the "camera ok" heartbeat. The status file is written on a
# cadence, not every frame, to avoid pointless disk churn at ~30fps. The
# API's /status endpoint treats a status older than ~30s as stale, so a
# 5s heartbeat leaves comfortable margin.
_STATUS_HEARTBEAT_S = 5.0
_last_status_write_ts: float = 0.0


def open_camera(cfg: Config):
    """
    Try to open the configured camera. Returns an opened VideoCapture, or
    None if the camera can't be opened (busy, absent, or permission denied).

    On failure we release the dud handle so we don't leak capture objects
    across retry attempts.
    """
    cap = cv2.VideoCapture(cfg.camera_index)
    if not cap.isOpened():
        cap.release()
        return None
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, cfg.frame_width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg.frame_height)
    return cap


def _heartbeat_camera_ok() -> None:
    """Write a `camera_ok=True` status at most once per _STATUS_HEARTBEAT_S."""
    global _last_status_write_ts
    now = time.time()
    if now - _last_status_write_ts >= _STATUS_HEARTBEAT_S:
        status.write_status(camera_ok=True, detail="Camera active.")
        _last_status_write_ts = now


def extract_landmarks(result) -> list[float] | None:
    if not result.pose_landmarks:
        return None
    lm = result.pose_landmarks[0]
    return [val for p in lm for val in (p.x, p.y, p.visibility)]


def draw_landmarks(frame, result) -> None:
    if not result.pose_landmarks:
        return
    h, w = frame.shape[:2]
    lm = result.pose_landmarks[0]
    pts = [(int(p.x * w), int(p.y * h)) for p in lm]
    for a, b in POSE_CONNECTIONS:
        if a < len(pts) and b < len(pts):
            cv2.line(frame, pts[a], pts[b], (0, 255, 0), 2)
    for x, y in pts:
        cv2.circle(frame, (x, y), 3, (0, 0, 255), -1)


def draw_phone_bbox(frame, bbox: tuple[float, float, float, float] | None) -> None:
    if bbox is None:
        return
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = bbox
    p1 = (int(x1 * w), int(y1 * h))
    p2 = (int(x2 * w), int(y2 * h))
    cv2.rectangle(frame, p1, p2, (0, 165, 255), 2)  # orange box
    cv2.putText(frame, "phone", (p1[0], max(p1[1] - 6, 12)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 165, 255), 1)


def should_log_event(new_event: str) -> bool:
    global last_event, last_event_time
    now = time.time()
    if new_event != last_event or (now - last_event_time) > config.min_event_duration_s:
        last_event = new_event
        last_event_time = now
        return True
    return False


def build_landmarker() -> mp_vision.PoseLandmarker:
    if not os.path.exists(config.pose_model_path):
        raise FileNotFoundError(
            f"Pose model not found at {config.pose_model_path}. "
            f"Run: python download_models.py"
        )
    options = mp_vision.PoseLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=config.pose_model_path),
        running_mode=mp_vision.RunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=0.6,
        min_tracking_confidence=0.5,
    )
    return mp_vision.PoseLandmarker.create_from_options(options)


def maybe_run_phone_detection(frame_bgr) -> None:

    global _last_phone_visible, _last_phone_bbox, _last_phone_run_ts, _frames_since_phone_run

    _frames_since_phone_run += 1
    if _frames_since_phone_run < config.frames_between_phone_runs:

        if _last_phone_visible and (time.time() - _last_phone_run_ts) > config.phone_visible_staleness_s:
            _last_phone_visible = False
            _last_phone_bbox = None
        return

    _frames_since_phone_run = 0
    detection = phone_detector.detect(frame_bgr)
    _last_phone_visible = detection.visible
    _last_phone_bbox = detection.bbox
    _last_phone_run_ts = time.time()


def run_detection_loop(cap, landmarker, db) -> str:
    """
    Run the per-frame detection loop until the camera stops yielding frames
    or the user quits the preview window.

    Returns a reason string:
      "quit"        — user pressed Q in the preview window.
      "camera_lost" — cap.read() started failing (camera unplugged, or the
                      device was grabbed by another process mid-session).

    The outer supervisor (`main`) decides what to do with each: quit exits,
    camera_lost triggers a re-open retry so the watcher self-heals.
    """
    global in_frame, frame_buffer

    # A single dropped frame is normal; a sustained run of them means the
    # camera is gone. Count consecutive failures and bail once we cross the
    # threshold rather than exiting on the first hiccup.
    consecutive_read_failures = 0
    MAX_READ_FAILURES = 30

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            consecutive_read_failures += 1
            if consecutive_read_failures >= MAX_READ_FAILURES:
                return "camera_lost"
            time.sleep(0.05)
            continue
        consecutive_read_failures = 0

        # Heartbeat the "camera ok" status (throttled). Placed here so it
        # only fires while we're actually pulling frames.
        _heartbeat_camera_ok()

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        ts_ms = int(time.time() * 1000)
        result = landmarker.detect_for_video(mp_image, ts_ms)

        maybe_run_phone_detection(frame)

        landmarks = extract_landmarks(result)
        now = time.time()

        if landmarks is None:
            if in_frame:
                in_frame = False
                if should_log_event("away"):
                    log_event(db, "away", confidence=1.0)
                    print(f"[{time.strftime('%H:%M:%S')}] away")
            frame_buffer.clear()
        else:
            in_frame = True
            frame_buffer.append((now, landmarks))

            cutoff = now - config.window_size_s
            frame_buffer = [(t, lm) for t, lm in frame_buffer if t >= cutoff]

            if len(frame_buffer) >= config.min_frames_to_classify:
                activity, confidence = classifier.predict(
                    frame_buffer,
                    phone_visible=_last_phone_visible,
                )
                if should_log_event(activity):
                    log_event(db, activity, confidence=confidence)
                    print(f"[{time.strftime('%H:%M:%S')}] {activity} ({confidence:.2f})")

        if config.show_preview:
            if not config.privacy_mode:
                draw_landmarks(frame, result)
                draw_phone_bbox(frame, _last_phone_bbox if _last_phone_visible else None)
            cv2.putText(frame, last_event, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            cv2.imshow("Desk Watcher", frame)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            return "quit"

    # cap.isOpened() went false without a read failure — treat as camera lost.
    return "camera_lost"


def main():
    """
    Supervisor loop: keep the camera open and the detection loop running,
    self-healing across camera-busy / camera-lost conditions.

    The camera being unavailable is the single most common real-world
    failure mode in a packaged install (Teams/Zoom/OS camera app holding the
    device). Rather than exiting — which leaves the dashboard silently empty
    — we report the condition to the status channel and retry every
    `camera_retry_s` seconds. When the device frees up, the next open
    succeeds and we resume.
    """
    db = SessionLocal()

    try:
        with build_landmarker() as landmarker:
            # The preview window (and its "press Q" quit) only exists when
            # SHOW_PREVIEW is on. In the packaged app it's off, so say what's
            # actually true: the watcher runs in the background.
            if config.show_preview:
                print("Desk Watcher running. Press Q in the preview window to quit.")
            else:
                print("Desk Watcher running in the background.")
            while True:
                cap = open_camera(config)
                if cap is None:
                    status.write_status(
                        camera_ok=False,
                        detail=(
                            f"Camera unavailable (index {config.camera_index}). "
                            "It may be in use by another app — close it and "
                            "we'll reconnect automatically."
                        ),
                    )
                    print(
                        f"[watcher] camera index {config.camera_index} "
                        f"unavailable; retrying in {config.camera_retry_s}s",
                        file=sys.stderr,
                    )
                    time.sleep(config.camera_retry_s)
                    continue

                try:
                    reason = run_detection_loop(cap, landmarker, db)
                finally:
                    cap.release()

                if reason == "quit":
                    break

                # camera_lost: report, pause, and loop back to re-open.
                status.write_status(
                    camera_ok=False,
                    detail="Lost the camera. Reconnecting…",
                )
                print("[watcher] camera lost mid-session; will re-open", file=sys.stderr)
                time.sleep(config.camera_retry_s)
    finally:
        cv2.destroyAllWindows()
        db.close()


if __name__ == "__main__":
    main()
