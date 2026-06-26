# Desk Watcher

A background app that uses your laptop camera to track what you're doing at your desk throughout the day and shows it on a live dashboard.

## What it tracks

- Drink/water sips (cup raised to face)
- Time away from desk (short breaks, bathroom, lunch)
- Break frequency and duration
- Lunch start and end time

## How it works

It runs in the background and uses pose estimation + object detection to classify what you're doing in each frame. Events get logged to a local SQLite database and served to a React dashboard.

No video is ever saved. Only pose keypoints (x/y coordinates) and activity labels hit the database, and nothing leaves your machine.

## Stack

**Backend / ML:** Python, OpenCV, MediaPipe, YOLOv8, scikit-learn / PyTorch, FastAPI, SQLite

**Frontend:** React + TypeScript, Vite, Recharts, TailwindCSS

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

## Status

Work in progress. Currently building out the core camera pipeline and event logging before moving on to the ML classification layer.
