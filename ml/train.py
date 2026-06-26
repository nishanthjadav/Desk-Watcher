"""
Train an activity classifier on labeled CSV data.
Usage: python train.py --data ../data/labeled/ --output ../backend/models/activity_classifier.pkl
"""
import argparse
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline


WINDOW_SIZE = 30   # frames per window (~3 seconds at 10fps)
STRIDE = 10        # frames to advance each window


def load_labeled_data(data_dir: Path) -> tuple[np.ndarray, np.ndarray]:
    """
    Expects CSV files with columns: timestamp, lm0_x, lm0_y, lm0_v, ..., label
    Returns X (feature matrix) and y (labels).
    """
    X_list, y_list = [], []

    for csv_path in sorted(data_dir.glob("*.csv")):
        df = pd.read_csv(csv_path)
        if "label" not in df.columns:
            print(f"Skipping {csv_path.name} — no 'label' column")
            continue

        # Drop rows with no label
        df = df.dropna(subset=["label"])
        feature_cols = [c for c in df.columns if c.startswith("lm")]
        features = df[feature_cols].values
        labels = df["label"].values

        # Sliding window: majority vote label for the window
        for start in range(0, len(features) - WINDOW_SIZE, STRIDE):
            window = features[start : start + WINDOW_SIZE]
            window_labels = labels[start : start + WINDOW_SIZE]

            # Majority label
            unique, counts = np.unique(window_labels, return_counts=True)
            majority_label = unique[np.argmax(counts)]

            # Feature vector: mean + std per landmark coordinate
            mean = window.mean(axis=0)
            std = window.std(axis=0)
            X_list.append(np.concatenate([mean, std]))
            y_list.append(majority_label)

        print(f"  {csv_path.name}: {len(X_list)} windows so far")

    return np.array(X_list), np.array(y_list)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data", required=True, help="Directory of labeled CSVs")
    p.add_argument("--output", required=True, help="Output .pkl path")
    p.add_argument("--model", choices=["rf", "gb"], default="rf")
    args = p.parse_args()

    data_dir = Path(args.data)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print("Loading data...")
    X, y = load_labeled_data(data_dir)
    print(f"Total samples: {len(X)}")
    print(f"Class distribution: {dict(zip(*np.unique(y, return_counts=True)))}")

    if len(X) < 20:
        print("Not enough data to train. Collect and label more sessions first.")
        return

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, stratify=y, random_state=42)

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
    print("Confusion matrix:")
    print(confusion_matrix(y_test, y_pred))

    with open(out_path, "wb") as f:
        pickle.dump(pipeline, f)
    print(f"\nModel saved to {out_path}")


if __name__ == "__main__":
    main()
