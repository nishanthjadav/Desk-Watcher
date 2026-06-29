# ML pipeline

This directory holds the data-collection, labeling, and training scripts.

## Workflow

```
1. record           collect_data.py    →  session_xxx.csv          (raw pose, no labels)
2. label            label_data.py      →  session_xxx.labels.csv   (sidecar with row,label)
3. train            train.py           →  activity_classifier.pkl  (sklearn pipeline)
4. deploy           (auto-loaded by backend/classifier.py)
```

The raw CSV is **immutable**. Labels live in a sidecar file so a botched labeling pass can be deleted without losing the recording.

---

## Record a session

```bash
python collect_data.py --duration 600 --output ../data/sessions/session_001.csv
```

Records 10 minutes of pose landmarks (no video) to a CSV at the given path. Press `q` to stop early.

## Label a session

```bash
python label_data.py ../data/sessions/session_001.csv
```

Opens a pose-only viewer with a timeline strip and keyboard-driven labeling.

### Hotkeys

| Key | Action |
|---|---|
| `1` / `2` / `3` / `4` | Set or commit a range — `at_desk` / `sipping` / `phone` / `away` |
| `0` | Clear the label on the current frame |
| `u` | Undo last label commit |
| `s` | Save (also happens automatically after every commit) |
| `←` / `→` (or `a` / `d`) | Step back / forward one frame |
| `Shift+←` / `Shift+→` | Jump 30 frames (~3 seconds) |
| `Home` / `End` | Jump to first / last frame |
| `PgUp` / `PgDn` | Jump to previous / next label boundary |
| `q` | Quit (saves on exit) |
| `Esc` | Cancel the current anchor |

### Range-labeling pattern ("anchor then commit")

Most labeling work is long at-desk runs broken by short sip/phone bursts. The tool is built for one keystroke per state boundary, not per frame:

1. Scrub to where a state begins. Press the label key (e.g. `1` for at_desk) — this drops an **anchor**.
2. Scrub to where the state ends.
3. Press the same key again to **commit** the range as that activity, OR press a different key to commit the range and immediately start a new anchor for the new activity (the "quick chain" path).

In practice: `1` → scrub to first sip → `2` → scrub to end of sip → `1` → scrub to next event → `2` → ... and so on. Two keystrokes per boundary.

## Train

```bash
python train.py --data ../data/sessions/ --output ../backend/models/activity_classifier.pkl
```

Walks every `session_*.csv` in the data directory, reads its sidecar, slides a 30-frame window across the labeled frames, and trains a classifier. Reports 5-fold CV F1, then a classification report and confusion matrix on a held-out 20% test split.

Aim for at least 20 minutes of labeled data per activity class before training — fewer samples and the model overfits to your specific desk setup.

---

## File format

**Raw CSV** (`session_xxx.csv`)

```
timestamp, lm0_x, lm0_y, lm0_v, lm1_x, ..., lm32_v
0.000,     0.51,  0.30,  0.99,  0.50,  ..., 0.95
0.083,     0.51,  0.30,  0.99,  0.51,  ..., 0.96
...
```

One row per frame, 33 MediaPipe pose landmarks × (x, y, visibility) = 99 floats plus the timestamp.

**Sidecar** (`session_xxx.labels.csv`)

```
row, label
142,  at_desk
143,  at_desk
...
781,  sipping
782,  sipping
```

Only labeled rows appear. Unlabeled rows are absent entirely.
