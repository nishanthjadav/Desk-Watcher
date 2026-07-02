import os
import sys
from dataclasses import dataclass, field


def _resource_dir() -> str:
    """
    Directory that holds runtime resources (model weights, etc.).

    When we're running from a PyInstaller-frozen build, PyInstaller unpacks
    bundled data files to a temp dir and sets `sys._MEIPASS` to it — the
    models/ directory is shipped as a data file so it lives there.

    When we're running from source (dev / tests / CI), the models live in
    `backend/` relative to this file — same as before the packaging work,
    so all 128 existing tests keep passing byte-for-byte.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return meipass
    return os.path.dirname(os.path.abspath(__file__))


def _resource(*parts: str) -> str:
    return os.path.join(_resource_dir(), *parts)


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
    # Model paths default to <resource_dir>/models/... which resolves to
    # backend/models/ in dev and sys._MEIPASS/models/ in frozen builds.
    # An explicit env-var override still wins for both source and frozen
    # (e.g. tests pass MODEL_PATH to point at a fixture).
    model_path: str = os.getenv("MODEL_PATH", _resource("models", "activity_classifier.pkl"))
    pose_model_path: str = os.getenv("POSE_MODEL_PATH", _resource("models", "pose_landmarker_lite.task"))

    phone_model_path: str = os.getenv("PHONE_MODEL_PATH", _resource("models", "yolov8n.pt"))
    phone_conf_threshold: float = float(os.getenv("PHONE_CONF_THRESHOLD", "0.40"))
    
    frames_between_phone_runs: int = int(os.getenv("PHONE_DETECT_EVERY_N_FRAMES", "6"))

    phone_visible_staleness_s: float = float(os.getenv("PHONE_VISIBLE_STALENESS_S", "1.5"))
 
    sustained_head_down_window_s: float = float(os.getenv("SUSTAINED_HEAD_DOWN_WINDOW_S", "30"))

    # Rolling window for the sustained-sip check. A sip should look like
    # one for at least this long before we'll classify it — kills the
    # one-frame false positives from gestures (scratching nose, adjusting
    # glasses, etc.).
    sustained_sip_window_s: float = float(os.getenv("SUSTAINED_SIP_WINDOW_S", "1.5"))
