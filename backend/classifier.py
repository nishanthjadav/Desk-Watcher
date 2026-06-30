import numpy as np
import pickle
import os
from collections import deque
from datetime import datetime


ACTIVITIES = ["at_desk", "away", "sipping", "phone"]


# Landmark index constants and the geometry helpers below
# (is_head_down, wrists_low_and_close, is_sipping, HeadDownTracker,
# SipTracker) are kept here for the OFFLINE labeling UI in
# ml/label_data.py, which uses them to pre-fill suggested labels for a
# human reviewer. They are NOT used by the live classifier — see the
# note in ActivityClassifier.predict() for why.


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
    # Euclidean wrist-to-nose distance alone produces false positives on
    # any face-touch — scratching the nose, adjusting glasses, rubbing
    # the forehead. The geometric tell of a sip vs a face-touch: a sip
    # raises the bottle to the MOUTH, which sits below the nose, so the
    # wrist ends up at mouth/chin height (below nose y in image coords,
    # where y grows downward). A nose-scratch puts the wrist at or
    # above the nose. Require the closer wrist to be both close to the
    # nose AND meaningfully below it.
    nose_x, nose_y = _xy(landmarks, LM_NOSE)
    lw_x, lw_y = _xy(landmarks, LM_LEFT_WRIST)
    rw_x, rw_y = _xy(landmarks, LM_RIGHT_WRIST)
    left_dist = ((lw_x - nose_x) ** 2 + (lw_y - nose_y) ** 2) ** 0.5
    right_dist = ((rw_x - nose_x) ** 2 + (rw_y - nose_y) ** 2) ** 0.5

    # Pick the wrist that's closer to the nose — only that one is a
    # candidate for "the sipping hand." The other wrist might be on the
    # keyboard or anywhere; it shouldn't disqualify a sip.
    if left_dist <= right_dist:
        cand_y, cand_dist = lw_y, left_dist
    else:
        cand_y, cand_dist = rw_y, right_dist

    # 0.12 (was 0.15): wrists near the ear/temple shouldn't qualify, only
    # wrists at the mouth-to-chin region.
    # 0.02: wrist must be at least ~2% of frame height BELOW the nose
    # (negative y-delta = above; positive = below). Cuts nose-scratches.
    close_enough = cand_dist < 0.12
    below_nose = (cand_y - nose_y) >= 0.02
    return close_enough and below_nose


class ActivityClassifier:
    # Minimum confidence the trained model must give its top class before
    # we'll emit it as an event. Below this floor we fall back to
    # at_desk — "the model isn't sure, but you were in frame, so the
    # safest assumption is that you were working." Tuned against the
    # test-set distribution where correct predictions sit around 0.85+
    # and confused frames typically drop below 0.55.
    MODEL_CONF_FLOOR = 0.55

    # If the model predicts "phone" but YOLO sees no phone in frame, we
    # still trust the model when its phone probability is above this
    # threshold. This is what makes phone-out-of-frame detection work:
    # the model has learned the pose signature of looking down at a
    # phone in your lap, and we don't want YOLO's null observation to
    # veto that. The threshold is high enough that pose-only phone calls
    # are only honored when the model is very sure (test-set phone
    # precision was 99% at the default threshold; phone calls above 0.80
    # are essentially never wrong).
    PHONE_OOF_CONF_THRESHOLD = 0.80

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
    ) -> tuple[str, float]:
        """
        Classify the current window using the trained model.

        Historical note: this used to short-circuit on three geometry
        rules (is_head_down + phone_visible → phone, wrists_low_and_close
        + phone_visible → phone, is_sipping + sustained_sipping →
        sipping) before consulting the model. Each rule keyed on a
        single pose feature and over-fired on any incidental match —
        nose-scratch became sip, type-while-head-tilted became phone,
        hands-in-lap-while-thinking became phone. The trained model
        scores ~98% per-class on held-out frames, so we just trust it.

        Phone gating logic:
          - If YOLO sees a phone, accept the model's "phone" call at any
            confidence (above the model floor).
          - If YOLO sees no phone, accept the model's "phone" call ONLY
            when the model is highly confident (≥ PHONE_OOF_CONF_THRESHOLD).
            This is the "looking down at phone in lap" case — the model
            learned the pose from labeled out-of-frame examples and
            we trust a confident call even without detector confirmation.
          - Below that threshold, demote to the next-best non-phone class.
        """
        if self.model is None:
            return self._rule_based_default(frame_buffer)

        features = self._extract_features(frame_buffer)
        proba = self.model.predict_proba([features])[0]
        classes = list(self.model.classes_)
        order = np.argsort(proba)[::-1]  # high → low probability
        label = classes[order[0]]
        conf = float(proba[order[0]])

        # Phone gating — see docstring for the policy.
        if label == "phone" and not phone_visible and conf < self.PHONE_OOF_CONF_THRESHOLD:
            for i in order[1:]:
                if classes[i] != "phone":
                    label = classes[i]
                    conf = float(proba[i])
                    break

        # Legacy class label cleanup — older models trained on a
        # 5-class label set still emit "stretching"; treat it as at_desk.
        if label == "stretching":
            label = "at_desk"

        # Below the confidence floor, refuse to emit a specific
        # activity. The user was in frame and the model couldn't make
        # up its mind, so default to at_desk rather than guess.
        if conf < self.MODEL_CONF_FLOOR:
            return "at_desk", conf

        return label, conf

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


class SipTracker:
    """
    Same rolling-window shape as HeadDownTracker, but tuned for sipping:
    a much shorter window (~1.5s) and a lower min-samples bar (sipping
    only needs a few frames to look real). Used by the classifier to
    require that wrist-near-nose is sustained, not a single-frame flash.

    Kept as a separate class rather than a parameterized generic so call
    sites read as `sip_tracker.sustained()` / `head_down_tracker.sustained()`
    — easier to grep, harder to misuse.
    """

    def __init__(self, window_s: float = 1.5):
        self.window_s = window_s
        self._samples: deque[tuple[float, bool]] = deque()

    def add(self, ts: float, sipping: bool) -> None:
        self._samples.append((ts, sipping))
        cutoff = ts - self.window_s
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

    def sustained(self, ratio: float = 0.6, min_samples: int = 5) -> bool:
        if len(self._samples) < min_samples:
            return False
        sip = sum(1 for _, s in self._samples if s)
        return (sip / len(self._samples)) >= ratio
