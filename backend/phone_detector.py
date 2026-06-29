
from __future__ import annotations

import os
from dataclasses import dataclass


PHONE_CLASS_ID = 67


@dataclass
class PhoneDetection:
    visible: bool
    bbox: tuple[float, float, float, float] | None
    confidence: float  


class PhoneDetector:


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

        from ultralytics import YOLO
        self._model = YOLO(self.model_path)
        print(f"Loaded phone detector from {self.model_path}")

    def detect(self, frame_bgr) -> PhoneDetection:

        self._ensure_loaded()
        assert self._model is not None

        h, w = frame_bgr.shape[:2]
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

      
        conf_tensor = boxes.conf.cpu().tolist()
        xyxy_tensor = boxes.xyxy.cpu().tolist()
        best_idx = int(max(range(len(conf_tensor)), key=lambda i: conf_tensor[i]))
        best_conf = float(conf_tensor[best_idx])
        x1, y1, x2, y2 = xyxy_tensor[best_idx]

        bbox = (x1 / w, y1 / h, x2 / w, y2 / h)
        return PhoneDetection(visible=True, bbox=bbox, confidence=best_conf)
