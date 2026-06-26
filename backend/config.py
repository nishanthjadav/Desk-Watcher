import os
from dataclasses import dataclass, field


@dataclass
class Config:
    camera_index: int = int(os.getenv("CAMERA_INDEX", "0"))
    frame_width: int = 1280
    frame_height: int = 720

    # Sliding window: how many seconds of pose frames to feed the classifier
    window_size_s: float = 3.0
    min_frames_to_classify: int = 15

    # Don't re-log same event unless it's been this many seconds
    min_event_duration_s: float = 10.0

    show_preview: bool = os.getenv("SHOW_PREVIEW", "true").lower() == "true"
    privacy_mode: bool = os.getenv("PRIVACY_MODE", "false").lower() == "true"

    db_path: str = os.getenv("DB_PATH", os.path.expanduser("~/.desk-watcher/events.db"))
    model_path: str = os.getenv("MODEL_PATH", "models/activity_classifier.pkl")
    pose_model_path: str = os.getenv("POSE_MODEL_PATH", "models/pose_landmarker_lite.task")
