"""
Record a session of pose keypoints to CSV for later labeling.
Usage: python collect_data.py --duration 60 --output ../data/samples/session_001.csv
"""
import argparse
import csv
import sys
import time
from pathlib import Path

import cv2
import mediapipe as mp

mp_pose = mp.solutions.pose
LANDMARK_COUNT = 33


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--duration", type=int, default=60, help="Recording duration in seconds")
    p.add_argument("--output", required=True, help="Output CSV path")
    p.add_argument("--camera", type=int, default=0)
    return p.parse_args()


def main():
    args = parse_args()
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    header = ["timestamp"] + [
        f"lm{i}_{axis}" for i in range(LANDMARK_COUNT) for axis in ("x", "y", "v")
    ]

    cap = cv2.VideoCapture(args.camera)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    start = time.time()
    rows_written = 0

    with open(out_path, "w", newline="") as f, mp_pose.Pose(model_complexity=1) as pose:
        writer = csv.writer(f)
        writer.writerow(header)
        print(f"Recording for {args.duration}s → {out_path}")

        while cap.isOpened():
            elapsed = time.time() - start
            if elapsed >= args.duration:
                break

            ret, frame = cap.read()
            if not ret:
                break

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = pose.process(rgb)

            if results.pose_landmarks:
                lm = results.pose_landmarks.landmark
                row = [elapsed] + [
                    val for point in lm for val in (point.x, point.y, point.visibility)
                ]
                writer.writerow(row)
                rows_written += 1

            remaining = int(args.duration - elapsed)
            cv2.putText(frame, f"Recording: {remaining}s", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            cv2.imshow("Recording", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    cap.release()
    cv2.destroyAllWindows()
    print(f"Done. Wrote {rows_written} frames to {out_path}")


if __name__ == "__main__":
    main()
