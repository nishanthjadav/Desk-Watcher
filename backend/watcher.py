import time
import cv2
import mediapipe as mp
from database import SessionLocal, log_event
from classifier import ActivityClassifier
from config import Config

mp_pose = mp.solutions.pose
mp_drawing = mp.solutions.drawing_utils

config = Config()
classifier = ActivityClassifier(config.model_path)

# Sliding window buffer: list of (timestamp, landmarks) tuples
frame_buffer: list[tuple[float, list]] = []

last_event: str = "unknown"
last_event_time: float = time.time()
in_frame: bool = False


def extract_landmarks(results) -> list[float] | None:
    if not results.pose_landmarks:
        return None
    lm = results.pose_landmarks.landmark
    # Flatten x, y, visibility for all 33 landmarks → 99 features
    return [val for lm_point in lm for val in (lm_point.x, lm_point.y, lm_point.visibility)]


def should_log_event(new_event: str) -> bool:
    """Avoid logging the same event repeatedly; require minimum dwell time."""
    global last_event, last_event_time
    now = time.time()
    if new_event != last_event or (now - last_event_time) > config.min_event_duration_s:
        last_event = new_event
        last_event_time = now
        return True
    return False


def main():
    global in_frame, frame_buffer

    cap = cv2.VideoCapture(config.camera_index)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.frame_width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.frame_height)

    db = SessionLocal()

    with mp_pose.Pose(
        min_detection_confidence=0.6,
        min_tracking_confidence=0.5,
        model_complexity=1,
    ) as pose:
        print("Desk Watcher running. Press Q to quit.")
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            # MediaPipe expects RGB
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = pose.process(rgb)

            landmarks = extract_landmarks(results)
            now = time.time()

            if landmarks is None:
                # No person detected
                if in_frame:
                    in_frame = False
                    if should_log_event("away"):
                        log_event(db, "away", confidence=1.0)
                        print(f"[{time.strftime('%H:%M:%S')}] away")
                frame_buffer.clear()
            else:
                in_frame = True
                frame_buffer.append((now, landmarks))

                # Keep only the last N seconds of frames
                cutoff = now - config.window_size_s
                frame_buffer = [(t, lm) for t, lm in frame_buffer if t >= cutoff]

                # Classify once we have enough frames
                if len(frame_buffer) >= config.min_frames_to_classify:
                    activity, confidence = classifier.predict(frame_buffer)
                    if should_log_event(activity):
                        log_event(db, activity, confidence=confidence)
                        print(f"[{time.strftime('%H:%M:%S')}] {activity} ({confidence:.2f})")

            # Optional: show preview with pose overlay
            if config.show_preview:
                if not config.privacy_mode and results.pose_landmarks:
                    mp_drawing.draw_landmarks(
                        frame, results.pose_landmarks, mp_pose.POSE_CONNECTIONS
                    )
                label = last_event
                cv2.putText(frame, label, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                cv2.imshow("Desk Watcher", frame)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    cap.release()
    cv2.destroyAllWindows()
    db.close()


if __name__ == "__main__":
    main()
