import os
import sys
import urllib.request

MODELS = {
    "models/pose_landmarker_lite.task": (
        "https://storage.googleapis.com/mediapipe-models/"
        "pose_landmarker/pose_landmarker_lite/float16/latest/"
        "pose_landmarker_lite.task"
    ),

    "models/yolov8n.pt": (
        "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8n.pt"
    ),
}


def download(path: str, url: str) -> None:
    if os.path.exists(path):
        print(f"[skip] {path} already exists")
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    print(f"[get]  {url}\n   -> {path}")
    urllib.request.urlretrieve(url, path)
    size_mb = os.path.getsize(path) / (1024 * 1024)
    print(f"[ok]   {path} ({size_mb:.1f} MB)")


def main() -> int:
    for path, url in MODELS.items():
        try:
            download(path, url)
        except Exception as e:
            print(f"[fail] {path}: {e}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
