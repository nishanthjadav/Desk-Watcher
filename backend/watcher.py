import os
import time
import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision
from database import SessionLocal, log_event
from classifier import ActivityClassifier
from config import Config

POSE_CONNECTIONS = [
    (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
    (11, 23), (12, 24), (23, 24),
    (23, 25), (25, 27), (27, 29), (29, 31), (27, 31),
    (24, 26), (26, 28), (28, 30), (30, 32), (28, 32),
]

config = Config()
classifier = ActivityClassifier(config.model_path)

frame_buffer: list[tuple[float, list]] = []

last_event: str = "unknown"
last_event_time: float = time.time()
in_frame: bool = False


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
                    activity, confidence = classifier.predict(frame_buffer)
                    if should_log_event(activity):
                        log_event(db, activity, confidence=confidence)
                        print(f"[{time.strftime('%H:%M:%S')}] {activity} ({confidence:.2f})")

            if config.show_preview:
                if not config.privacy_mode:
                    draw_landmarks(frame, result)
                cv2.putText(frame, last_event, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                cv2.imshow("Desk Watcher", frame)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    cap.release()
    cv2.destroyAllWindows()
    db.close()


if __name__ == "__main__":
    main()
