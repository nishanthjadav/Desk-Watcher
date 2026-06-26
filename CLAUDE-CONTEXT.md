# Desk Watcher

A real-time activity recognition system that uses your laptop camera to track desk behaviors throughout the workday — hydration, breaks, and lunch — and surfaces productivity analytics via a live dashboard.

## What It Does

Desk Watcher runs in the background while you work. It watches for specific behaviors using pose estimation and computer vision, logs timestamped events to a local SQLite database, and serves a React dashboard showing your daily patterns.

**Tracked behaviors:**
- 💧 Water/drink sips (cup raised to face)
- 🚶 Away from desk (short break vs. bathroom vs. lunch)
- 📊 Break duration and frequency
- 🍽️ Lunch break detection and average duration

**Dashboard shows:**
- Today's timeline (when you were at desk, away, eating, drinking)
- Hydration count and frequency
- Break count and average duration
- Lunch start/end time and duration
- Weekly trends

---

## Architecture

```
Camera Feed (OpenCV)
    ↓
Person Detection (YOLOv8 / MediaPipe)
    ↓
Pose Estimation (MediaPipe Holistic)
    ↓
Activity Classifier (custom trained on self-labeled data)
    ↓
Event Logger (SQLite)
    ↓
FastAPI backend ──→ React dashboard
```

### Key Technical Components

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Camera feed | OpenCV | Capture and preprocess frames |
| Person/pose detection | MediaPipe Holistic + YOLOv8 | Detect presence and body keypoints |
| Activity classification | scikit-learn / PyTorch LSTM | Classify behavior from keypoint sequences |
| Object detection | YOLOv8 | Detect cup/bottle raised to face (sip detection) |
| Event logging | SQLite + SQLAlchemy | Local, private timestamped activity log |
| Backend API | FastAPI | Serve data to dashboard |
| Dashboard | React + TypeScript + Recharts | Visualize daily/weekly patterns |

---

## Project Phases

### Phase 1 — Core Pipeline (Weeks 1–3)
Get the camera feed working with presence detection and basic event logging. No ML yet — rule-based logic only.

- [ ] OpenCV camera feed with configurable resolution
- [ ] MediaPipe pose detection (are you in frame?)
- [ ] Basic presence/absence event logger (SQLite)
- [ ] Away duration heuristics (short < 5min, long > 15min = lunch candidate)
- [ ] FastAPI skeleton with `/events` and `/summary` endpoints

### Phase 2 — Activity Classification (Weeks 4–9)
The core ML work. Record and label your own data, train a sequence classifier.

- [ ] Data collection script (record pose keypoints to CSV with timestamps)
- [ ] Labeling tool / labeling notebook (label activity type per window)
- [ ] Feature engineering (normalize keypoints, sliding window over sequences)
- [ ] Train baseline classifier (Random Forest or SVM on windowed features)
- [ ] Sip detection: YOLOv8 fine-tuned to detect cup/bottle at face level
- [ ] Classify: at_desk | away_short | away_long | sipping | standing
- [ ] Confusion matrix, per-class accuracy, deploy to live feed

### Phase 3 — Dashboard & Polish (Weeks 10–12)
Full React dashboard, confidence scores, real accuracy metrics.

- [ ] React + Vite + TypeScript frontend
- [ ] Recharts timeline view (Gantt-style day view)
- [ ] Daily stats cards (sip count, break count, avg break duration, lunch duration)
- [ ] Weekly trend charts
- [ ] Confidence scores shown on event log
- [ ] README with demo screenshots/GIF

---

## Activity Labels

| Label | Description | Detection method |
|-------|-------------|-----------------|
| `at_desk` | Sitting at desk, working | Pose present, minimal movement |
| `sipping` | Drinking from cup/bottle | Object detection + pose (wrist raised to face) |
| `away_short` | Left desk briefly (< 10 min) | Absence duration heuristic |
| `away_long` | Extended absence (10–60 min) | Absence duration heuristic |
| `lunch` | Midday break (11am–2pm, > 20 min) | Time-of-day + duration heuristic |
| `stretching` | Standing/moving at desk | Pose keypoint velocity spike |

---

## Privacy

All processing is **fully local** — no video is stored, no data leaves your machine.

- Camera feed is processed frame-by-frame in memory; no video recording
- Only pose keypoints (x,y coordinates) and activity labels are saved to SQLite
- SQLite database is stored at `~/.desk-watcher/events.db` by default
- Config supports a `privacy_mode` that blurs the preview window

---

## Stack

**Backend / ML:**
- Python 3.11+
- OpenCV (`opencv-python`)
- MediaPipe
- YOLOv8 (`ultralytics`)
- scikit-learn / PyTorch
- FastAPI + Uvicorn
- SQLite + SQLAlchemy
- pandas / numpy

**Frontend:**
- React 19 + TypeScript
- Vite
- Recharts (charts/timelines)
- TailwindCSS

---

## Getting Started

### Prerequisites
- Python 3.11+
- Node.js 18+
- Webcam

### Install

```bash
# Backend
cd backend
pip install -r requirements.txt

# Frontend
cd frontend
npm install
```

### Run

```bash
# Terminal 1 — start the watcher (camera + classifier + event logger)
cd backend
python watcher.py

# Terminal 2 — start the API server
cd backend
uvicorn api:app --reload --port 8000

# Terminal 3 — start the dashboard
cd frontend
npm run dev
```

Then open `http://localhost:5173` to see your dashboard.

---

## Data Collection & Labeling (Phase 2)

To train your own activity classifier:

```bash
# Record a session (saves pose keypoints to CSV, not video)
python ml/collect_data.py --duration 60 --output data/samples/session_001.csv

# Label the CSV (opens interactive labeling tool)
python ml/label_data.py data/samples/session_001.csv

# Train the classifier
python ml/train.py --data data/labeled/ --output models/activity_classifier.pkl
```

The more labeled sessions you record, the better the classifier gets. Aim for at least 20 minutes of labeled data per activity type before training.

---

## Resume Bullets (target)

> *"Built a real-time activity recognition system using YOLOv8 and MediaPipe pose estimation to classify desk behaviors (hydration, breaks, lunch) from a live camera feed"*

> *"Designed a temporal classification pipeline using sliding windows over 33-keypoint pose sequences to distinguish activity types, trained on self-labeled data"*

> *"Engineered a FastAPI + SQLite event logging backend and React/Recharts dashboard surfacing daily productivity analytics and weekly trend visualizations"*

> *"Collected and labeled N minutes of personal activity data to fine-tune classification beyond off-the-shelf MediaPipe defaults"*
