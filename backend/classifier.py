import numpy as np
import pickle
import os
from collections import deque
from datetime import datetime


ACTIVITIES = ["at_desk", "away", "sipping", "phone"]

.
LM_NOSE = 0
LM_LEFT_EAR = 7
LM_RIGHT_EAR = 8
LM_LEFT_SHOULDER = 11
LM_RIGHT_SHOULDER = 12
LM_LEFT_WRIST = 15
LM_RIGHT_WRIST = 16


def _xy(landmarks: list[float], idx: int) -> tuple[float, float]:
    base = idx * 3
    return landmarks[base], landmarks[base + 1]


def is_head_down(landmarks: list[float]) -> bool:

    nose_x, nose_y = _xy(landmarks, LM_NOSE)
    lear_x, lear_y = _xy(landmarks, LM_LEFT_EAR)
    rear_x, rear_y = _xy(landmarks, LM_RIGHT_EAR)
    lsh_x, lsh_y = _xy(landmarks, LM_LEFT_SHOULDER)
    rsh_x, rsh_y = _xy(landmarks, LM_RIGHT_SHOULDER)

    ear_y = (lear_y + rear_y) / 2.0
    shoulder_y = (lsh_y + rsh_y) / 2.0

    nose_below_ears = (nose_y - ear_y) > 0.025

    nose_near_shoulders = (shoulder_y - nose_y) < 0.18

    return nose_below_ears and nose_near_shoulders


def wrists_low_and_close(landmarks: list[float]) -> bool:
    lw_x, lw_y = _xy(landmarks, LM_LEFT_WRIST)
    rw_x, rw_y = _xy(landmarks, LM_RIGHT_WRIST)
    _, lsh_y = _xy(landmarks, LM_LEFT_SHOULDER)
    _, rsh_y = _xy(landmarks, LM_RIGHT_SHOULDER)
    shoulder_y = (lsh_y + rsh_y) / 2.0

    both_low = (lw_y - shoulder_y) > 0.15 and (rw_y - shoulder_y) > 0.15
    horizontally_close = abs(lw_x - rw_x) < 0.15
    return both_low and horizontally_close


def is_sipping(landmarks: list[float]) -> bool:
    nose_x, nose_y = _xy(landmarks, LM_NOSE)
    lw_x, lw_y = _xy(landmarks, LM_LEFT_WRIST)
    rw_x, rw_y = _xy(landmarks, LM_RIGHT_WRIST)
    left_dist = ((lw_x - nose_x) ** 2 + (lw_y - nose_y) ** 2) ** 0.5
    right_dist = ((rw_x - nose_x) ** 2 + (rw_y - nose_y) ** 2) ** 0.5
    return min(left_dist, right_dist) < 0.15


class ActivityClassifier:
    def __init__(self, model_path: str):
        self.model = None
        if os.path.exists(model_path):
            with open(model_path, "rb") as f:
                self.model = pickle.load(f)
            print(f"Loaded classifier from {model_path}")
        else:
            print("No trained model found — using rule-based fallback.")

    def predict(
        self,
        frame_buffer: list[tuple[float, list]],
        phone_visible: bool = False,
        sustained_head_down: bool = False,
    ) -> tuple[str, float]:
        latest = frame_buffer[-1][1]
        if phone_visible and is_head_down(latest):
            return "phone", 0.90
        if phone_visible and wrists_low_and_close(latest):
            return "phone", 0.78
        if not phone_visible and sustained_head_down:
    
            return "phone", 0.55


        if is_sipping(latest):
            return "sipping", 0.75

        # ── Trained classifier ─────────────────────────────────────────────
        if self.model is not None:
            features = self._extract_features(frame_buffer)
            proba = self.model.predict_proba([features])[0]
            idx = int(np.argmax(proba))
            label = self.model.classes_[idx]
            if label == "stretching":
                label = "at_desk"
            return label, float(proba[idx])

        return self._rule_based_default(frame_buffer)

    def _extract_features(self, frame_buffer: list[tuple[float, list]]) -> list[float]:
        frames = np.array([lm for _, lm in frame_buffer])  # shape: (n_frames, 99)
        mean = frames.mean(axis=0)
        std = frames.std(axis=0)
        return np.concatenate([mean, std]).tolist()

    def _rule_based_default(self, frame_buffer: list[tuple[float, list]]) -> tuple[str, float]:
        hour = datetime.now().hour
        if 11 <= hour <= 14:
            return "at_desk", 0.6
        return "at_desk", 0.8


class HeadDownTracker:
    def __init__(self, window_s: float = 30.0):
        self.window_s = window_s
        self._samples: deque[tuple[float, bool]] = deque()

    def add(self, ts: float, head_down: bool) -> None:
        self._samples.append((ts, head_down))
        cutoff = ts - self.window_s
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

    def sustained(self, ratio: float = 0.8, min_samples: int = 10) -> bool:
        if len(self._samples) < min_samples:
            return False
        down = sum(1 for _, hd in self._samples if hd)
        return (down / len(self._samples)) >= ratio
