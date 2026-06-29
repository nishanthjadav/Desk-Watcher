# Desk Watcher

A background app that uses your laptop camera to track what you're doing at your desk throughout the day and shows it on a live dashboard.

## What it tracks

- Drink/water sips (cup raised to face)
- Phone usage (phone in frame + head down, or sustained head-down even when the phone is out of sight)
- Time away from desk, classified by duration and time of day: short break, long break, lunch
- Break frequency, average break length, lunch start/end

## How it works

A watcher loop runs in the background and feeds each camera frame through MediaPipe pose detection + a YOLOv8n object detector (cell phone only). A rule-based classifier composes the two signals (pose geometry plus phone visibility) into an activity label. Events get logged to a local SQLite database and served to a React dashboard.

No video is ever saved. Only pose keypoints and activity labels hit the database, and nothing leaves your machine.

## Stack

**Backend / ML:** Python, OpenCV, MediaPipe Pose, YOLOv8n (ultralytics), FastAPI, SQLAlchemy + SQLite

**Frontend:** React 19 + TypeScript, Vite, TailwindCSS

## Getting started

### Prerequisites
- Python 3.11+
- Node.js 18+
- Webcam

### Install

```bash
# Backend
cd backend
pip install -r requirements.txt
python download_models.py   # one-time, fetches the MediaPipe pose model and YOLOv8n weights

# Frontend
cd frontend
npm install
```

### Run

```bash
# Terminal 1 - watcher (camera + classifier + event logger)
cd backend
python watcher.py

# Terminal 2 - API server
cd backend
uvicorn api:app --reload --port 8000

# Terminal 3 - dashboard
cd frontend
npm run dev
```

Open `http://localhost:5173` to see the dashboard.

Events get written to `~/.desk-watcher/events.db` (a local SQLite file, created automatically on first run).

## Tests

```bash
pip install -r backend/requirements-dev.txt
python -m pytest
```

Covers the pose geometry helpers, absence categorization, timeline merging, timezone boundary logic, and the FastAPI endpoints. The heavy ML deps (torch, mediapipe, opencv, ultralytics) aren't needed for unit tests, so the suite runs in ~2 seconds. CI runs on every push and PR via GitHub Actions.

## Status

Phone detection, dashboard, and test suite are in. To-do: close the ML loop, labeling tool, self-labeled training data, and a sequence model (LSTM or 1D-CNN) to replace the rule-based classifier as the primary path. Aside from ML stuff, want to add mouse tracking + calendar syncing for improved productivity accuracy.
