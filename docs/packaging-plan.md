# Packaging plan: Desk Watcher as a Tauri desktop app

**Status:** Decided, not started. Written 2026-06-30 after the v0.x classifier overhaul landed.

This is the migration plan from "dev setup with three terminals" to "one signed installer that puts a tray icon on your taskbar."

## Decision

Ship as a **Tauri 2.x desktop application** with a system tray icon. Skip the Chrome extension route entirely. Skip Electron.

### What this preserves

Everything. The current architecture — Python backend, SQLite DB, React frontend talking to localhost — already IS a desktop app split into pieces. The migration packages those pieces; it does not rewrite them.

Specifically, these stay as-is:

- `backend/api.py` — FastAPI service on `localhost:8000`
- `backend/watcher.py` — camera loop, MediaPipe, YOLO, classifier
- `backend/database.py` — SQLAlchemy + SQLite at `~/.desk-watcher/events.db`
- `backend/classifier.py` — the trained pose model + YOLO gate
- `frontend/` — React + Vite. Talks to `http://localhost:8000`. Hardcoded URL works in production because the bundled API runs on the same port.
- The trained model `backend/models/activity_classifier.pkl` and the labeled session CSVs.
- All 122 backend tests.

### Why not Chrome extension

Considered, rejected. The dealbreakers, in order:

1. **MV3 offscreen documents are not designed for 8-hour continuous camera capture.** Chrome can kill them under memory pressure. Recovery requires user interaction. Untenable for a background productivity tracker.
2. **TF.js + ONNX.js performance is hardware-dependent in ways we can't control.** 15-30% of users on weak GPUs would see degraded detection. The native Python pipeline is uniform across hardware.
3. **scikit-learn → ONNX export adds a fragile step.** The current classifier ships as a `.pkl`; in-browser would need `sklearn-onnx` conversion every retrain.
4. **Chrome Web Store review for camera extensions is hostile.** Multiple rounds of back-and-forth, privacy-policy requirements, every release scrutinized.
5. **Tying to Chrome alienates Edge / Firefox / Brave / Arc users.** Desktop app is browser-agnostic.

### Why not Electron

Considered, rejected. Tauri wins on:

- **Install size:** ~30-50 MB vs Electron's ~120-200 MB.
- **Runtime memory:** ~50 MB shell vs ~150-300 MB Chromium.
- **Cleaner native integration** (system tray, autostart, file system APIs) — first-class Rust APIs vs Electron's various community plugins.

Electron's only real advantage (broader ecosystem, JS-only build) doesn't outweigh shipping a 200 MB blob for a productivity tool.

## Architecture in production

```
┌────────────────────────────────────────────────┐
│                Tauri shell (Rust)              │
│                                                │
│  ┌────────────────────┐    ┌────────────────┐  │
│  │  WebView           │    │  Sidecar       │  │
│  │  ─────────         │    │  processes     │  │
│  │  React frontend    │◄──►│                │  │
│  │  (built static)    │    │  • api.exe    │  │
│  │  served by Tauri   │    │  • watcher.exe│  │
│  │  fetches           │    │                │  │
│  │  localhost:8000    │    │  Spawned at   │  │
│  └────────────────────┘    │  app launch,  │  │
│                            │  SIGTERMed at │  │
│  ┌────────────────────┐    │  app quit     │  │
│  │  System tray       │    │                │  │
│  │  • Open dashboard  │    │                │  │
│  │  • Quit            │    └────────────────┘  │
│  └────────────────────┘                        │
└────────────────────────────────────────────────┘
            │                          │
            └──── %APPDATA% ────────────┘
                  • events.db (SQLite)
                  • logs/
```

- The user opens the app from the tray icon.
- A native window with the WebView opens. WebView loads the bundled React build from a `tauri://localhost` URL.
- React fetches `http://localhost:8000/summary` etc. — same code as today.
- `api.exe` (PyInstaller-bundled FastAPI) listens on 8000.
- `watcher.exe` (PyInstaller-bundled camera loop) runs in the background, writes events to the DB.
- Both processes start with the app and stop when the user quits via the tray.

## Migration plan, in order

### Phase 1 — get it running locally (one weekend)

Goal: `tauri dev` opens a window showing the working dashboard with live data.

1. **Add a `desktop/` directory at the repo root.** Tauri project, scaffolded with `npm create tauri-app@latest`. Tauri's "create app" wizard asks for the frontend dir — point it at `../frontend`. Tauri will set up `desktop/src-tauri/` (Rust) and use the existing frontend for the WebView.

2. **Configure Tauri to spawn the Python services as sidecars.** Two binary targets:
   - `api.exe` — PyInstaller bundle of `backend/api.py` invoking `uvicorn`.
   - `watcher.exe` — PyInstaller bundle of `backend/watcher.py`.

   Tauri's `bundle.externalBin` config in `tauri.conf.json` registers them. The Rust `main.rs` uses `tauri::async_runtime::spawn` + `Command::new_sidecar` to start them on app launch.

3. **Bundle the model files.** Three files copied into the resource bundle:
   - `backend/models/pose_landmarker_lite.task`
   - `backend/models/yolov8n.pt`
   - `backend/models/activity_classifier.pkl`

   They need to be resolvable from the PyInstaller'd binaries. Easiest path: set `MODEL_PATH`, `POSE_MODEL_PATH`, `PHONE_MODEL_PATH` env vars from the Rust shell before spawning the sidecar, pointing into Tauri's resource directory (`tauri::api::path::resource_dir()`).

4. **Handle the startup race.** Frontend mounts before `api.exe` finishes initializing. Add a small "connecting…" state in `App.tsx` that retries `/summary` until it succeeds. ~10 lines of code; or use a Tauri event from Rust to the WebView when the API health-checks green.

5. **Window lifecycle:**
   - On close: hide the window, do NOT exit the app. (Tauri's `tauri::WindowEvent::CloseRequested` with `api.prevent_close()`.)
   - On tray "Quit": SIGTERM both sidecars, then exit the Rust shell.
   - On tray "Open dashboard": show the window.

6. **Sanity test:** `cargo tauri dev`. Click tray. See dashboard. See live phone/sip events as you use the app.

### Phase 2 — make it installable (one weekend)

Goal: someone other than you can install and run a `.msi`.

1. **PyInstaller bundling.** Two `.spec` files (one per binary). Include the `--collect-all=mediapipe` and `--collect-all=ultralytics` flags (these libraries have data files PyInstaller doesn't auto-detect). Expect 200-300 MB per binary because of mediapipe+ultralytics+opencv+torch. This is the painful part of packaging Python; budget a full day for the first successful build.

2. **Verify binary works standalone.** Run `dist/api.exe` from a clean shell with no Python installed. If it serves on 8000, you're done.

3. **Verify the watcher binary works standalone.** Same.

4. **Test on a clean Windows machine** (a VM or a friend's laptop). Install path:
   - Run `.msi` installer that Tauri generates.
   - Launch from start menu.
   - Tray icon appears.
   - Camera permission dialog appears on first watcher activation.
   - Dashboard opens, shows data.

5. **First-run onboarding window.** Tauri opens a small window once on first launch: "Desk Watcher needs camera access. The app does not record video; only activity labels are stored on your device." One screen, one OK button. Set a flag in app config so it doesn't show again.

6. **Logs to disk.** `%APPDATA%/desk-watcher/logs/{api,watcher}.log`. Pipe stdout/stderr from sidecars. "Open logs folder" menu item in the tray.

### Phase 3 — publishable (couple of days)

Goal: shippable to strangers without warnings or trust issues.

1. **Code signing certificate.** ~$80/year from a CA like Sectigo. Sign the `.msi` and the bundled binaries. SmartScreen warnings go away after the cert builds reputation (~50 installs).

2. **Auto-update.** Tauri's updater plugin polls a `latest.json` you host (on GitHub Releases or a static site). On new version: downloads, verifies signature, installs on next launch.

3. **Privacy policy + landing page.** A `desk-watcher.app` (or whatever) with one page explaining what the app does. Link to it from the installer and the in-app About.

4. **macOS port.** Same Tauri code, different sidecar binaries (PyInstaller on macOS). Notarization required (`xcrun notarytool`). $99/year Apple Developer membership. Probably a v0.2 thing, not v0.1.

## Open questions to resolve before Phase 1

These are the things I want to know before writing code, in priority order:

1. **PyInstaller binary size.** mediapipe + ultralytics + opencv + torch might exceed 500 MB combined. If the installer ends up over 500 MB, we revisit (drop ultralytics in favor of an ONNX runtime export, use opencv-headless, etc.). The right Phase 0 task is an isolated PyInstaller experiment with just `watcher.py` to measure binary size honestly.

2. **DB location.** Currently `~/.desk-watcher/events.db` (hardcoded in `backend/config.py:19`). Should become `%APPDATA%/desk-watcher/events.db` on Windows, `~/Library/Application Support/desk-watcher/events.db` on Mac. The change is one line in `config.py` using `platformdirs.user_data_dir()`. Do this before Phase 1 so we don't ship with the wrong path.

3. **Auto-start on login.** Default-on or default-off? Default-on maximizes data captured but is invasive. Default-off requires the user to set it via a tray menu item, but more respectful. **Recommend default-off**, opt-in via tray menu.

4. **What happens if the camera is in use by another app?** Currently `watcher.py` will fail silently or crash. Need a friendly error in the dashboard ("Camera busy — close [other app] and click Retry") and a retry button. Today this is a non-issue because the user starts the watcher manually; in a desktop app it's a real failure mode.

## What this does NOT solve

These are out of scope for the migration. They're separate work after:

- **Pinning UI in the dashboard.** Frontend-only work. Independent of how the app is packaged.

## Time estimate

- **Phase 1:** 1 weekend (10-15 hours).
- **Phase 2:** 1 weekend (10-15 hours).
- **Phase 3:** scattered over a week of evenings (~10 hours), most of it waiting for cert issuance and Web Store policy reads.

**Total:** ~2-3 weekends from start to a publishable v0.1. Less if Phase 0 (the PyInstaller binary-size experiment) reveals the bundles work cleanly first try.

## What to do first

Phase 0: PyInstaller experiment. Before committing any of the above, validate that mediapipe + ultralytics actually PyInstaller-bundles to a working binary. The most common way this migration fails is at this step. One afternoon's work to either confirm or learn we need to pre-export models to ONNX.

If Phase 0 works, scaffold Phase 1 with confidence. If Phase 0 reveals a 1.2 GB binary, the plan adjusts.
