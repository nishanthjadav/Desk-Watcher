# ML pipeline

This directory holds the data-collection, labeling, and training scripts.

## Workflow

```
1. record           collect_data.py    →  session_xxx.csv          (pose + inline labels)
2. (optional) edit  label_data.py      →  session_xxx.labels.csv   (sidecar with row,label)
3. train            train.py           →  activity_classifier.pkl  (sklearn pipeline)
4. deploy           (auto-loaded by backend/classifier.py)
```

**The big win:** labels are captured *live* while you record, by pressing number keys to switch between activities. No post-hoc scrubbing through thousands of frames. The optional labeler step is only there if you want to correct mislabels after the fact.

The raw CSV is **immutable**. Sidecar edits never overwrite it — if a labeling pass goes wrong, delete the sidecar and the inline labels from the recording are still intact.

---

## Record a session (the main flow)

```bash
python collect_data.py --duration 900 --output ../data/sessions/session_001.csv
```

Records ~15 minutes of pose landmarks to CSV. While recording, hold up the activity you're doing using these keys:

| Key | Activity |
|---|---|
| `1` | **at_desk** (default at startup) |
| `2` | **sipping** |
| `3` | **phone** |
| `q` | stop early |

Each key press *toggles* the active label — press `2`, sip, press `1` when done. The active label is shown in a giant colored bar at the top of the preview window so you can never lose track. Per-class frame counts are shown at the bottom.

**`away` is NOT a key.** When you stand up and walk out of frame, MediaPipe stops detecting a pose and no rows are written for those frames. The live watcher handles `away` separately as the no-pose-found case. So the training data is intentionally **3-class** (`at_desk`, `sipping`, `phone`); the deployed system stitches in `away` at runtime.

### How much data should I collect?

Aim for ~5 minutes per active class — about 15 minutes total recording. Class balance matters far more than total volume for a small classifier. A balanced 15-minute dataset trains better than 2 hours of passive recording that's 95% at_desk.

Suggested breakdown:
- **5 min at_desk** — type, scroll, lean back, look around. Vary it.
- **5 min sipping** — take ~30 sips from a few different cups, both hands, vary the angle. Toggle to `2` for each sip and back to `1` between.
- **5 min phone** — phone visible, phone in lap, head-down, head-up. Mix it up.

---

## (Optional) Correct labels post-hoc

```bash
python label_data.py ../data/sessions/session_001.csv
```

Opens a pose-only viewer with the inline labels already loaded into the timeline. You can review and fix any mislabels — pose-aware scrubbing, range edits, undo, autosave.

The first time you open a hold-to-label recording, the inline labels get migrated to a sidecar file (`session_xxx.labels.csv`). All subsequent edits accumulate there; the original CSV stays untouched.

### Labeler hotkeys

| Key | Action |
|---|---|
| `1` / `2` / `3` / `4` | Set or commit a range — `at_desk` / `sipping` / `phone` / `away` |
| `0` | Clear the label on the current frame |
| `r` | Re-run the rule-based auto-labeler (single undo-able operation) |
| `u` | Undo last label commit |
| `s` | Save (also happens automatically after every commit) |
| `←` / `→` (or `a` / `d`) | Step back / forward one frame |
| `Shift+←` / `Shift+→` | Jump 30 frames (~3 seconds) |
| `Home` / `End` | Jump to first / last frame |
| `PgUp` / `PgDn` | Jump to previous / next label boundary |
| `q` | Quit (saves on exit) |
| `Esc` | Cancel the current anchor |

---

## Train

```bash
python train.py --data ../data/sessions/ --output ../backend/models/activity_classifier.pkl
```

Walks every `session_*.csv` in the data directory. For each one, prefers the sidecar's labels if present (latest edits); otherwise uses the inline `label` column from the live recording. Slides a 30-frame window over the labeled frames, trains a Random Forest, reports 5-fold CV F1 and a classification report + confusion matrix on a held-out 20% test split.

---

## File formats

**Recording with inline labels** (`session_xxx.csv` — written by `collect_data.py`)

```
timestamp, label,   lm0_x, lm0_y, lm0_v, lm1_x, ..., lm32_v
0.000,     at_desk, 0.51,  0.30,  0.99,  0.50,  ..., 0.95
0.083,     at_desk, 0.51,  0.30,  0.99,  0.51,  ..., 0.96
3.250,     sipping, 0.50,  0.31,  0.99,  0.50,  ..., 0.94
...
```

One row per frame. 33 MediaPipe landmarks × (x, y, visibility) = 99 floats. Frames where the user is away aren't in the file at all.

**Sidecar (post-hoc edits)** (`session_xxx.labels.csv` — written by `label_data.py`)

```
row, label
142,  at_desk
143,  at_desk
...
781,  sipping
```

Only labeled rows appear. Sidecar labels override inline labels when present.
