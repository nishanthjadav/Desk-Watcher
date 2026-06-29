import os
import time
import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision
from database import SessionLocal, log_event
from classifier import ActivityClassifier, HeadDownTracker, SipTracker, is_head_down, is_sipping
from phone_detector import PhoneDetector
from config import Config

POSE_CONNECTIONS = [
    (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
    (11, 23), (12, 24), (23, 24),
    (23, 25), (25, 27), (27, 29), (29, 31), (27, 31),
    (24, 26), (26, 28), (28, 30), (30, 32), (28, 32),
]

config = Config()
classifier = ActivityClassifier(config.model_path)
phone_detector = PhoneDetector(config.phone_model_path, conf_threshold=config.phone_conf_threshold)
head_down_tracker = HeadDownTracker(window_s=config.sustained_head_down_window_s)
sip_tracker = SipTracker(window_s=config.sustained_sip_window_s)

frame_buffer: list[tuple[float, list]] = []

last_event: str = "unknown"
last_event_time: float = time.time()
in_frame: bool = False


_last_phone_visible: bool = False
_last_phone_bbox: tuple[float, float, float, float] | None = None
_last_phone_run_ts: float = 0.0
_frames_since_phone_run: int = 0


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


def main():
    global in_frame, frame_buffer

    cap = cv2.VideoCapture(config.camera_index)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.frame_width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.frame_height)

    db = SessionLocal()

    with build_landmarker() as landmarker:
        print("Desk Watcher running. Press Q to quit.")
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

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

                head_down_tracker.add(now, is_head_down(landmarks))
                sip_tracker.add(now, is_sipping(landmarks))

                cutoff = now - config.window_size_s
                frame_buffer = [(t, lm) for t, lm in frame_buffer if t >= cutoff]

                if len(frame_buffer) >= config.min_frames_to_classify:
                    activity, confidence = classifier.predict(
                        frame_buffer,
                        phone_visible=_last_phone_visible,
                        sustained_head_down=head_down_tracker.sustained(),
                        sustained_sipping=sip_tracker.sustained(),
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
                break

    cap.release()
    cv2.destroyAllWindows()
    db.close()


if __name__ == "__main__":
    main()
