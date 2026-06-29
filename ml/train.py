"""
Train an activity classifier on labeled CSV data.

Label sources
-------------
Labels are read from a SIDECAR file alongside each session CSV:
    session_001.csv          -- raw pose recording from collect_data.py
    session_001.labels.csv   -- (row, label) pairs from label_data.py

The sidecar pattern keeps the raw recording immutable. If a labeling
pass goes wrong, delete the sidecar and start over — the original
pose data is never touched.

Featurization (Phase 1)
-----------------------
For now we slide a fixed-width window over each session and aggregate
each window into mean + std per landmark coord (99 landmarks × 2 stats
= 198 features). This throws away the temporal signal and serves as
the baseline. The sequence-model replacement (1D-CNN over the raw
30×99 sequence) comes in a later phase.

Usage:
    python train.py --data ../data/labeled/ --output ../backend/models/activity_classifier.pkl
"""
from __future__ import annotations

import argparse
import csv
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


# Must stay in sync with backend/classifier.py ACTIVITIES.
ACTIVITIES = ["at_desk", "sipping", "phone", "away"]

WINDOW_SIZE = 30   # frames per window (~3 seconds at 10fps)
STRIDE = 10        # frames to advance each window


def load_sidecar_labels(labels_path: Path, n_frames: int) -> list[str | None]:
    """Read the sidecar produced by ml/label_data.py."""
    labels: list[str | None] = [None] * n_frames
    if not labels_path.exists():
        return labels
    rejected = 0
    with open(labels_path, newline="") as f:
        reader = csv.reader(f)
        next(reader, None)  # header
        for row in reader:
            if len(row) < 2:
                continue
            try:
                idx = int(row[0])
            except ValueError:
                continue
            if not (0 <= idx < n_frames):
                continue
            if row[1] not in ACTIVITIES:
                rejected += 1
                continue
            labels[idx] = row[1]
    if rejected:
        print(f"  {labels_path.name}: dropped {rejected} rows with unknown labels")
    return labels


def load_labeled_data(data_dir: Path) -> tuple[np.ndarray, np.ndarray]:
    """
    For each session CSV in `data_dir`, look for a matching .labels.csv,
    apply a sliding window, and emit (mean+std feature vector, majority
    label) per window.
    """
    X_list, y_list = [], []

    for csv_path in sorted(data_dir.glob("*.csv")):
        # Skip sidecars themselves — they have ".labels.csv" suffix.
        if csv_path.name.endswith(".labels.csv"):
            continue

        df = pd.read_csv(csv_path)
        feature_cols = [c for c in df.columns if c.startswith("lm")]
        if not feature_cols:
            print(f"  {csv_path.name}: no landmark columns, skipping")
            continue

        labels_path = csv_path.with_suffix(".labels.csv")
        labels = load_sidecar_labels(labels_path, len(df))
        n_labeled = sum(1 for lbl in labels if lbl is not None)
        if n_labeled == 0:
            print(f"  {csv_path.name}: no sidecar / no labels, skipping")
            continue

        features = df[feature_cols].values
        n_before = len(X_list)

        # Sliding window with majority-vote label.
        for start in range(0, len(features) - WINDOW_SIZE, STRIDE):
            window_feats = features[start : start + WINDOW_SIZE]
            window_labels = [labels[start + i] for i in range(WINDOW_SIZE)]
            # Drop windows where most frames are unlabeled — they'd pollute
            # the training set with noise.
            labeled_in_window = [lbl for lbl in window_labels if lbl is not None]
            if len(labeled_in_window) < WINDOW_SIZE // 2:
                continue

            unique, counts = np.unique(labeled_in_window, return_counts=True)
            majority_label = unique[int(np.argmax(counts))]

            mean = window_feats.mean(axis=0)
            std = window_feats.std(axis=0)
            X_list.append(np.concatenate([mean, std]))
            y_list.append(majority_label)

        print(f"  {csv_path.name}: {len(X_list) - n_before} windows (from {n_labeled} labeled frames)")

    return np.array(X_list), np.array(y_list)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data", required=True, help="Directory containing session CSVs + sidecar labels")
    p.add_argument("--output", required=True, help="Output .pkl path")
    p.add_argument("--model", choices=["rf", "gb"], default="rf")
    args = p.parse_args()

    data_dir = Path(args.data)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print("Loading data...")
    X, y = load_labeled_data(data_dir)
    print(f"\nTotal windows: {len(X)}")
    if len(X) == 0:
        print("No labeled windows found. Run label_data.py on a recorded session first.")
        return
    print(f"Class distribution: {dict(zip(*np.unique(y, return_counts=True)))}")

    if len(X) < 20:
        print("Not enough data to train (< 20 windows). Collect and label more sessions.")
        return

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=42
    )

    if args.model == "rf":
        clf = RandomForestClassifier(n_estimators=200, max_depth=15, random_state=42, n_jobs=-1)
    else:
        clf = GradientBoostingClassifier(n_estimators=100, max_depth=5, random_state=42)

    pipeline = Pipeline([("scaler", StandardScaler()), ("clf", clf)])

    print(f"\nTraining {args.model.upper()}...")
    cv_scores = cross_val_score(pipeline, X_train, y_train, cv=5, scoring="f1_weighted")
    print(f"CV F1 (5-fold): {cv_scores.mean():.3f} ± {cv_scores.std():.3f}")

    pipeline.fit(X_train, y_train)
    y_pred = pipeline.predict(X_test)

    print("\nTest set results:")
    print(classification_report(y_test, y_pred))
    print("Confusion matrix (rows = true, cols = pred):")
    classes = sorted(set(list(y_test) + list(y_pred)))
    print("classes:", classes)
    print(confusion_matrix(y_test, y_pred, labels=classes))

    with open(out_path, "wb") as f:
        pickle.dump(pipeline, f)
    print(f"\nModel saved to {out_path}")


if __name__ == "__main__":
    main()
