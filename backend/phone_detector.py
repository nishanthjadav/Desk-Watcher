"""
YOLOv8n-based phone detector. Wraps ultralytics to answer one question:
"is there a cell phone visible in this frame, and where is it?"

Phones in COCO are class 67. We keep the API narrow so the watcher loop
stays simple and the heavy import (`ultralytics`) only happens here.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


# COCO class id for "cell phone".
PHONE_CLASS_ID = 67


@dataclass
class PhoneDetection:
    visible: bool
    # Bounding box in normalized image coords (0..1), (x1, y1, x2, y2) or None.
    bbox: tuple[float, float, float, float] | None
    confidence: float  # 0.0 when not visible


class PhoneDetector:
    """
    Thin wrapper around an ultralytics YOLO model. Loads lazily so that
    importing this module doesn't pay the torch startup cost up front.

    Detection cadence is the caller's job — running YOLO on every frame
    is wasteful since phones don't move that fast. The watcher throttles
    via `frames_between_runs` and reuses the last detection in between.
    """

    def __init__(self, model_path: str, conf_threshold: float = 0.35):
        self.model_path = model_path
        self.conf_threshold = conf_threshold
        self._model = None  # lazy

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(
                f"YOLO model not found at {self.model_path}. "
                f"Run: python download_models.py"
            )
        # Import inside the function so callers that never use the detector
        # don't pay the torch/ultralytics import cost.
        from ultralytics import YOLO
        self._model = YOLO(self.model_path)
        print(f"Loaded phone detector from {self.model_path}")

    def detect(self, frame_bgr) -> PhoneDetection:
        """
        Run inference on a single BGR frame (the raw OpenCV format).
        Returns the highest-confidence cell-phone detection above threshold,
        or PhoneDetection(visible=False, ...) if nothing was found.
        """
        self._ensure_loaded()
        assert self._model is not None

        h, w = frame_bgr.shape[:2]
        # `verbose=False` keeps ultralytics from printing on every call.
        results = self._model.predict(
            frame_bgr,
            classes=[PHONE_CLASS_ID],
            conf=self.conf_threshold,
            verbose=False,
        )
        if not results:
            return PhoneDetection(visible=False, bbox=None, confidence=0.0)

        boxes = results[0].boxes
        if boxes is None or len(boxes) == 0:
            return PhoneDetection(visible=False, bbox=None, confidence=0.0)

        # Pick the most confident phone box. boxes.xyxy / boxes.conf are torch tensors;
        # we move to CPU + python floats to keep the rest of the code numpy-free.
        conf_tensor = boxes.conf.cpu().tolist()
        xyxy_tensor = boxes.xyxy.cpu().tolist()
        best_idx = int(max(range(len(conf_tensor)), key=lambda i: conf_tensor[i]))
        best_conf = float(conf_tensor[best_idx])
        x1, y1, x2, y2 = xyxy_tensor[best_idx]

        # Normalize to 0..1 so downstream code is resolution-independent.
        bbox = (x1 / w, y1 / h, x2 / w, y2 / h)
        return PhoneDetection(visible=True, bbox=bbox, confidence=best_conf)
