import os
from dataclasses import dataclass, field


@dataclass
class Config:
    camera_index: int = int(os.getenv("CAMERA_INDEX", "0"))
    frame_width: int = 1280
    frame_height: int = 720

    window_size_s: float = 3.0
    min_frames_to_classify: int = 15

    min_event_duration_s: float = 10.0

    show_preview: bool = os.getenv("SHOW_PREVIEW", "true").lower() == "true"
    privacy_mode: bool = os.getenv("PRIVACY_MODE", "false").lower() == "true"

    db_path: str = os.getenv("DB_PATH", os.path.expanduser("~/.desk-watcher/events.db"))
    model_path: str = os.getenv("MODEL_PATH", "models/activity_classifier.pkl")
    pose_model_path: str = os.getenv("POSE_MODEL_PATH", "models/pose_landmarker_lite.task")

    phone_model_path: str = os.getenv("PHONE_MODEL_PATH", "models/yolov8n.pt")
    phone_conf_threshold: float = float(os.getenv("PHONE_CONF_THRESHOLD", "0.35"))
    
    frames_between_phone_runs: int = int(os.getenv("PHONE_DETECT_EVERY_N_FRAMES", "6"))

    phone_visible_staleness_s: float = float(os.getenv("PHONE_VISIBLE_STALENESS_S", "1.5"))
 
    sustained_head_down_window_s: float = float(os.getenv("SUSTAINED_HEAD_DOWN_WINDOW_S", "30"))
