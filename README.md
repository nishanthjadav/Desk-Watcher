# Desk Watcher

A background app that uses your laptop camera to track what you're doing at your desk throughout the day and shows it on a live dashboard.

Everything runs locally. No video is ever saved, and nothing leaves your machine.

## Download

Grab the installer for your platform from the [latest release](https://github.com/nishanthjadav/Desk-Watcher/releases/latest):

- **Windows 10/11** (64-bit): the `.msi` installer.
- **macOS** (Apple Silicon, M1 or newer): the `.dmg`.

The installers are not yet code-signed, so you will see a first-launch warning:

- On Windows, SmartScreen may show a "protected your PC" screen. Click **More info**, then **Run anyway**.
- On macOS, right-click the app and choose **Open** to get past Gatekeeper.

Prefer to run from source? See [Getting started](#getting-started) below.

## What it tracks

- Drink/water sips (cup raised to face)
- Phone usage (phone in frame + head down, or sustained head-down even when the phone is out of sight)
- Time away from desk, classified by duration and time of day: short break, long break, lunch
- Break frequency, average break length, lunch start/end

## How it works

A watcher loop runs in the background. Each camera frame passes through MediaPipe pose detection to extract joint keypoints, and a trained classifier scores short windows of those keypoints into one of four activity labels: at desk, sipping, on phone, away. A YOLOv8n object detector runs in parallel to cross-check the phone calls. Events get logged to a local SQLite database and served to a React dashboard.

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

Events get written to a local SQLite file, created automatically on first run:

- Windows: `%APPDATA%\desk-watcher\events.db`
- macOS: `~/Library/Application Support/desk-watcher/events.db`
- Linux: `$XDG_DATA_HOME/desk-watcher/events.db` (or `~/.local/share/desk-watcher/events.db`)

## Tests

```bash
pip install -r backend/requirements-dev.txt
python -m pytest
```

Covers the pose geometry helpers, absence categorization, timeline merging, timezone boundary logic, and the FastAPI endpoints. The heavy ML deps (torch, mediapipe, opencv, ultralytics) aren't needed for unit tests, so the suite runs in ~2 seconds. CI runs on every push and PR via GitHub Actions.

## Status

Packaged as a single-install [Tauri](https://tauri.app) desktop app. The Python watcher and API are frozen into sidecar binaries with PyInstaller and bundled into the app, so end users do not need Python or Node installed.

Installers are built per OS in CI (`.github/workflows/release.yml`) on a version tag and published to [GitHub Releases](https://github.com/nishanthjadav/Desk-Watcher/releases). The current release is **v0.1.0** (Windows `.msi` and macOS Apple Silicon `.dmg`).

Not yet done: code signing / notarization (installers show a first-launch warning), an Intel/universal macOS build, and auto-update.
