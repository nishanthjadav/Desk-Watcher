import numpy as np
import pickle
import os
from datetime import datetime


ACTIVITIES = ["at_desk", "away", "sipping", "stretching"]


class ActivityClassifier:
    """
    Wraps a trained sklearn classifier. Falls back to rule-based logic
    when no trained model exists yet (Phase 1).
    """

    def __init__(self, model_path: str):
        self.model = None
        if os.path.exists(model_path):
            with open(model_path, "rb") as f:
                self.model = pickle.load(f)
            print(f"Loaded classifier from {model_path}")
        else:
            print("No trained model found — using rule-based fallback.")

    def predict(self, frame_buffer: list[tuple[float, list]]) -> tuple[str, float]:
        """
        frame_buffer: list of (timestamp, landmarks) where landmarks is 99 floats
        Returns (activity_label, confidence)
        """
        if self.model is not None:
            features = self._extract_features(frame_buffer)
            proba = self.model.predict_proba([features])[0]
            idx = int(np.argmax(proba))
            return self.model.classes_[idx], float(proba[idx])

        return self._rule_based(frame_buffer)

    def _extract_features(self, frame_buffer: list[tuple[float, list]]) -> list[float]:
        """
        Aggregate a window of pose frames into a fixed-length feature vector.
        Strategy: mean + std of each landmark coordinate across all frames.
        99 landmarks * 2 stats = 198 features.
        """
        frames = np.array([lm for _, lm in frame_buffer])  # shape: (n_frames, 99)
        mean = frames.mean(axis=0)
        std = frames.std(axis=0)
        return np.concatenate([mean, std]).tolist()

    def _rule_based(self, frame_buffer: list[tuple[float, list]]) -> tuple[str, float]:
        """
        Phase 1 fallback: simple heuristic based on wrist-to-nose distance.
        If either wrist is close to the nose landmark, classify as sipping.
        """
        # MediaPipe landmark indices: nose=0, left_wrist=15, right_wrist=16
        # Each landmark: (x, y, visibility) → indices 0,1,2 / 45,46,47 / 48,49,50
        latest_landmarks = frame_buffer[-1][1]

        nose_x, nose_y = latest_landmarks[0], latest_landmarks[1]
        left_wrist_x, left_wrist_y = latest_landmarks[45], latest_landmarks[46]
        right_wrist_x, right_wrist_y = latest_landmarks[48], latest_landmarks[49]

        left_dist = ((left_wrist_x - nose_x) ** 2 + (left_wrist_y - nose_y) ** 2) ** 0.5
        right_dist = ((right_wrist_x - nose_x) ** 2 + (right_wrist_y - nose_y) ** 2) ** 0.5

        if min(left_dist, right_dist) < 0.15:
            return "sipping", 0.7

        # Check for lunch by time of day
        hour = datetime.now().hour
        if 11 <= hour <= 14:
            return "at_desk", 0.6  # could be lunch if away; handled in watcher

        return "at_desk", 0.8
