# Desk Watcher — Deployment Status

Snapshot of the Tauri desktop packaging effort. Read this before
picking the work back up.

## TL;DR

Everything is wired up and the build **succeeds through the PyInstaller
stage** on the SAP-issued work laptop. The final `tauri build` step is
blocked by a corporate Defender **Attack Surface Reduction (ASR) policy**
that denies execution of freshly-compiled Cargo `build-script-build.exe`
files under the user profile — elevating the shell does **not** bypass
ASR. Plan is to push the code changes and run the build end-to-end on a
personal (unmanaged) laptop.

## Where each piece stands

| Step                                           | State  | Notes |
| ---------------------------------------------- | ------ | ----- |
| 1. Frontend build (`npm run build`)            | ✅     | `VITE_API_URL=http://127.0.0.1:8765` baked in at build time |
| 2. PyInstaller `watcher.exe` (onedir, 1.3 GB)  | ✅     | `packaging/dist/watcher/` |
| 3. PyInstaller `api.exe` (onedir, 85 MB)       | ✅     | `packaging/dist/api/` |
| 4. Stage sidecars → `tauri/src-tauri/binaries/`| ✅     | Both onedir trees copied wholesale |
| 5. `cargo build` → MSI                         | ❌     | Blocked by ASR on the work laptop |

## Architecture — how the packaged app is glued together

```
Desk Watcher.exe  (Tauri Rust supervisor, ~5 MB)
├── frontend bundle (webview loads from tauri://localhost)
└── binaries/               (resource_dir(), populated from bundle.resources)
    ├── watcher/
    │   ├── watcher.exe     ← spawned by lib.rs at startup
    │   └── _internal/      ← PyInstaller DLLs + models (torch, mediapipe, ultralytics)
    └── api/
        ├── api.exe         ← spawned first, health-polled on 127.0.0.1:8765
        └── _internal/      ← uvicorn + fastapi + pydantic
```

- The Rust supervisor (`tauri/src-tauri/src/lib.rs`) uses
  `std::process::Command` (not the `tauri-plugin-shell` sidecar API — see
  Design decisions below) and resolves each exe under
  `app.path().resource_dir().join("binaries").join(name).join(name + ".exe")`.
- On startup it spawns `api` first, then `watcher`, then polls
  `http://127.0.0.1:8765/healthz` up to 30× (500 ms each) before showing
  the main window. The window starts `visible: false` in
  `tauri.conf.json` so the user never sees a "Failed to fetch" flash.
- Both children are assigned to a Windows **Job Object** with
  `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. When the parent dies (clean exit
  or crash), the kernel reaps the sidecars and any grandchildren. This
  is critical for PyInstaller onedir because its bootloader spawns a
  child Python process that would otherwise survive the parent on
  Windows.
- Sidecars are launched with `CREATE_NO_WINDOW` so their consoles do
  not flash on release builds. Their `.spec` files still have
  `console=True` so `tauri dev` in a terminal can show their output.

## Files changed / created (relative to `main`)

**New:**
- `backend/api_entry.py` — PyInstaller entry point. Imports `app` from
  `api.py` and runs `uvicorn.run(app, ...)` on port **8765**. Uses
  the object directly (not the string `"api:app"`) because string
  discovery breaks in frozen builds.
- `packaging/build.ps1` — end-to-end build script. Runs frontend →
  watcher spec → api spec → stages sidecars into
  `tauri/src-tauri/binaries/`. Verbose so failures are easy to locate.
- `packaging/watcher.spec` — PyInstaller spec. `onedir`, ships model
  weights (`activity_classifier.pkl`, `pose_landmarker_lite.task`,
  `yolov8n.pt`), collects mediapipe/ultralytics/torch data & DLLs,
  excludes matplotlib/IPython/jupyter/pytest to save ~100 MB.
- `packaging/api.spec` — PyInstaller spec for the api sidecar.
  Excludes torch/mediapipe/ultralytics/cv2 (~90 % dist size cut vs
  including them by accident via transitive imports).
- `packaging/requirements-build.txt` — `pyinstaller>=6.11,<7`.
- `tauri/` — full Tauri v2 wrapper:
  - `package.json` — dev dep `@tauri-apps/cli ^2.1.0`.
  - `src-tauri/Cargo.toml` — `tauri 2.11`, `reqwest` for the health
    poll, `windows 0.58` (JobObjects + Threading) for the cleanup
    guarantee. `tauri-plugin-shell` intentionally NOT used.
  - `src-tauri/tauri.conf.json` — MSI target, `bundle.resources` map
    that ships `binaries/watcher/**/*` and `binaries/api/**/*`,
    window starts `visible: false`.
  - `src-tauri/src/{main.rs, lib.rs}` — supervisor described above.
  - `src-tauri/capabilities/default.json` — just `core:default`
    (we're not using shell:allow-execute).
  - `src-tauri/icons/icon.ico` — 6-resolution ICO, verified valid.
  - `src-tauri/build.rs` — stock `tauri_build::build()`.

**Modified:**
- `backend/api.py` — added `/healthz` endpoint (readiness probe) and
  CORS origins `tauri://localhost` + `http://tauri.localhost` (the
  schemes the Tauri webview uses).
- `backend/config.py` — `_resource_dir()` returns `sys._MEIPASS` when
  frozen, `backend/` in dev. Model paths resolve through it. Env-var
  overrides (`MODEL_PATH`, etc.) still win.
- `frontend/src/App.tsx` — `const API = import.meta.env.VITE_API_URL ?? "http://localhost:8000";`.
  Dev falls back to `:8000` (existing uvicorn source workflow); the
  packaged frontend has `http://127.0.0.1:8765` baked in.
- `frontend/src/vite-env.d.ts` — declares `VITE_API_URL` for TS.
- `.gitignore` — added `tauri/node_modules/`, `tauri/src-tauri/target/`,
  `tauri/src-tauri/binaries/`, `packaging/build/`, `packaging/dist/`.

## Design decisions (and things I considered but rejected)

**Why `std::process::Command` instead of `tauri-plugin-shell`'s
`app.shell().sidecar(name)`?**
`externalBin` in Tauri v2 handles exactly one file per entry and
ignores siblings. PyInstaller `onedir` produces a directory with a
sibling `_internal/` full of DLLs — the bootloader locates them
relative to the exe on disk. Two options exist to solve this in a
Tauri-native way:

1. Switch PyInstaller to `--onefile`. Rejected: mediapipe and torch
   both `dlopen` native libs, and `onefile`'s temp-dir unpack trips
   the discovery logic intermittently. `onedir` behaves like a normal
   Python install, which is what the ML deps expect.
2. Use `externalBin` for the exe **and** `bundle.resources` for
   `_internal/`. Rejected: the exe would land in the resource dir
   with the triple stripped, but the `_internal/` sibling would end
   up at a different install-time path depending on Tauri's flattening
   rules. Fragile.

The chosen path — pure `bundle.resources` for both directories, plus
`std::process::Command` to spawn — is fewer moving parts, doesn't
depend on the shell plugin's scope allowlist, and lets us attach a
Windows Job Object (which the shell plugin doesn't expose).

**Why port 8765 and not 8000?**
So a running packaged app doesn't collide with a dev-mode `uvicorn
api:app --port 8000` when both are open. Also gives us an obvious
"which one am I hitting" signal in netstat.

**Why is `frontend/dist/` still git-tracked?**
Historically committed. The personal-laptop build will overwrite it
before `tauri build` runs, so it's not a correctness issue. Leaving
it tracked means the repo works out of the box for someone who wants
to inspect the frontend without running `npm install`. Not worth a
churny commit right now.

**Bundle size.**
- Uncompressed staged: watcher **1.3 GB** + api **85 MB** = ~1.4 GB.
- Expected MSI (WiX LZX-21 compression, 40–60 % ratio): **600–800 MB**.
- Non-negotiable without dropping torch/ultralytics.

## Blocker on this machine

`cargo build --release` fails at the first `build-script-build.exe`
invocation with `Access is denied. (os error 5)`. The binaries exist
and are readable, but every attempt to execute them — from Cargo, from
bash, or from PowerShell — is denied.

Diagnosis:
- **AppLocker**: `AuditOnly` with dummy rules. Not the culprit.
- **Defender ASR**: 16 rules enabled, most in Block mode. One of the
  Block-mode rules is almost certainly
  `BE9BA2D9-53EA-4CDC-84E5-9B1EEEE46550` ("Block executable files from
  running unless they meet a prevalence, age, or trusted list criterion")
  — fresh Cargo-emitted PE files have zero prevalence and no signature,
  so ASR blocks them from executing.
- Elevation does not bypass ASR (ASR is a kernel-level Defender feature,
  not a UAC-tier check).

Escape hatches, in rough order of preference:
1. Build on a personal (unmanaged) laptop. **← chosen path**
2. Ask IT to add a per-folder ASR exclusion for `C:\SAPDevelop\` or
   the specific `target/` path (`Add-MpPreference -AttackSurfaceReductionOnlyExclusions`).
3. Move the entire repo under `%LOCALAPPDATA%` or `%ProgramData%\Docker`
   — sometimes those are excluded by default in corporate images.
4. Build with `CARGO_TARGET_DIR` pointing at a WSL2 path
   (Windows Defender does not scan `\\wsl$\...` PE files) — but Tauri
   MSI bundling itself needs to run under Windows for WiX.

## Personal-laptop run recipe

Assumes fresh clone.

```powershell
# One-time toolchain
rustup toolchain install stable-x86_64-pc-windows-msvc
# Install Visual Studio Build Tools 2022 "Desktop development with C++"
# Install Node 20+ and Python 3.11+ (3.14 works — that's what I used)
python -m pip install -r backend/requirements.txt
python -m pip install -r packaging/requirements-build.txt
cd tauri && npm install && cd ..

# Build
pwsh packaging/build.ps1
cd tauri && npm run tauri build
# → tauri/src-tauri/target/release/bundle/msi/Desk Watcher_0.1.0_x64_en-US.msi
```

WiX toolset auto-downloads on first `tauri build`. Needs internet.

## Post-install user flow (unverified — no MSI yet)

1. User double-clicks the MSI. Installs to
   `C:\Program Files\Desk Watcher\`.
2. Start menu shortcut launches `Desk Watcher.exe`.
3. Supervisor spawns `api.exe` and `watcher.exe` from
   `C:\Program Files\Desk Watcher\binaries\{api,watcher}\`.
4. Windows may prompt for **webcam access** — Settings → Privacy &
   Security → Camera → "Let desktop apps access your camera". If the
   user says no, `watcher.exe` will silently fail to grab frames but
   the dashboard still loads (backed by whatever's in
   `~/.desk-watcher/events.db`). Worth surfacing this in a README
   before shipping.
5. SQLite DB lives at `%USERPROFILE%\.desk-watcher\events.db`,
   auto-created on first run.

## Things I'd verify before calling it shipped

- [ ] MSI install actually places files where `resource_dir()` expects
      them (should — Tauri's install layout is stable, but confirm).
- [ ] `api.exe` binds 8765 on first run; frontend can hit `/healthz`.
- [ ] `watcher.exe` opens the default webcam, writes rows to
      `~/.desk-watcher/events.db`.
- [ ] Closing the main window terminates BOTH sidecar processes (check
      Task Manager). Job Object should guarantee this, but verify.
- [ ] Force-killing `Desk Watcher.exe` from Task Manager also kills the
      sidecars (this is what the Job Object is really for).
- [ ] Uninstall via Control Panel removes `C:\Program Files\Desk Watcher\`
      cleanly.
- [ ] Reboot survivability — DB path is under `%USERPROFILE%` so it
      persists across sessions.

## Nice-to-haves that are NOT in this build

- Auto-start on login. Not wired. Add a Start Menu → Startup shortcut in
  the WiX transform, or teach the app to write a Run-key entry on first
  launch behind a settings toggle.
- Code signing. The MSI is unsigned, so SmartScreen will warn on first
  launch. A one-and-done personal build isn't worth $250/yr for an EV
  cert; users can click "More info → Run anyway" once.
- Auto-update. Tauri has an updater plugin, but "one and done, no v0.2"
  means we skip it entirely.
