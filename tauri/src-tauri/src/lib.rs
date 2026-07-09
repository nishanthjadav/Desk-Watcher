// Desk Watcher — Rust process supervisor.
//
// Responsibilities:
//   1. On app setup: spawn `watcher.exe` and `api.exe` sidecars from the
//      installed resource directory. Both are PyInstaller onedir builds;
//      each sits in its own subfolder with a sibling `_internal/` full of
//      DLLs and data — see packaging/build.ps1 for staging and
//      tauri.conf.json → bundle.resources for the install-time copy.
//   2. Poll http://127.0.0.1:8765/healthz until the api sidecar answers
//      (or we hit the retry budget). Only then reveal the main window,
//      so the user never sees a "Failed to fetch" flash.
//   3. On window CloseRequested / RunEvent::Exit: drop the sidecar handles.
//      On Windows, both children are assigned to a Job Object with
//      KILL_ON_JOB_CLOSE, so dropping our handle to the job terminates
//      them (and any grandchildren) even if we didn't get a clean shutdown.
//
// All app logic lives in Python. This file is deliberately dumb.

use std::fs;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

use tauri::menu::{CheckMenuItemBuilder, MenuBuilder, MenuItemBuilder};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{Manager, RunEvent, WindowEvent};
use tauri_plugin_autostart::{ManagerExt, MacosLauncher};
use tauri_plugin_dialog::DialogExt;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

// Windows-only: Job Object handle wrapper. Assigning both sidecars to a
// job with KILL_ON_JOB_CLOSE means Windows kernel-cleans them when this
// handle drops, no matter how we exit.
#[cfg(windows)]
mod job {
    use std::mem::size_of;
    use windows::Win32::Foundation::HANDLE;
    use windows::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, SetInformationJobObject,
        JobObjectExtendedLimitInformation, JOBOBJECT_BASIC_LIMIT_INFORMATION,
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };
    use windows::Win32::System::Threading::{OpenProcess, PROCESS_ALL_ACCESS};
    use windows::Win32::Foundation::CloseHandle;

    pub struct Job(HANDLE);

    // SAFETY: HANDLE is a raw pointer wrapper but is thread-safe for our
    // usage — we only ever call AssignProcessToJobObject on it from the
    // setup thread and drop it from Tauri's event loop thread.
    unsafe impl Send for Job {}
    unsafe impl Sync for Job {}

    impl Job {
        pub fn new() -> Result<Self, String> {
            unsafe {
                let handle = CreateJobObjectW(None, None)
                    .map_err(|e| format!("CreateJobObjectW: {e}"))?;

                // Configure the job so closing our handle kills every
                // process still assigned to it. Without this flag, Windows
                // keeps the job alive until the last member exits.
                let mut info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION {
                    BasicLimitInformation: JOBOBJECT_BASIC_LIMIT_INFORMATION {
                        LimitFlags: JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
                        ..Default::default()
                    },
                    ..Default::default()
                };

                SetInformationJobObject(
                    handle,
                    JobObjectExtendedLimitInformation,
                    &mut info as *mut _ as *mut _,
                    size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
                )
                .map_err(|e| format!("SetInformationJobObject: {e}"))?;

                Ok(Job(handle))
            }
        }

        pub fn assign(&self, pid: u32) -> Result<(), String> {
            unsafe {
                let proc = OpenProcess(PROCESS_ALL_ACCESS, false, pid)
                    .map_err(|e| format!("OpenProcess({pid}): {e}"))?;
                let res = AssignProcessToJobObject(self.0, proc)
                    .map_err(|e| format!("AssignProcessToJobObject({pid}): {e}"));
                let _ = CloseHandle(proc);
                res
            }
        }
    }

    impl Drop for Job {
        fn drop(&mut self) {
            unsafe { let _ = CloseHandle(self.0); }
        }
    }
}

// Handles to the spawned sidecar processes. Wrapped in a Mutex so we can
// take() them on shutdown from Tauri's event handlers without violating
// Send/Sync bounds on Child.
struct SidecarState {
    watcher: Mutex<Option<Child>>,
    api: Mutex<Option<Child>>,
    // The Job Object outlives both children. Dropping it (in on_window_event
    // or RunEvent::Exit) triggers KILL_ON_JOB_CLOSE. Held in an Option so
    // we can .take() and explicitly drop it during shutdown.
    #[cfg(windows)]
    job: Mutex<Option<job::Job>>,
    // Whether the system tray built successfully. If it did, closing the
    // window HIDES to tray (sidecars keep running); if it didn't, we fall
    // back to close = full shutdown so the user is never stuck with an
    // unquittable hidden process (no tray = no way to quit or reopen).
    tray_ok: Mutex<bool>,
}

// Resolve the on-disk path of a sidecar exe inside the installed app's
// resource directory. During `tauri dev` the resource dir is
// `src-tauri/target/<profile>/`, so we tell the developer to run
// `packaging/build.ps1` first — the staged `binaries/{name}/` folders are
// copied there by Tauri's dev-mode resource resolution.
fn sidecar_path(app: &tauri::AppHandle, name: &str) -> Result<PathBuf, String> {
    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|e| format!("resource_dir(): {e}"))?;
    let exe = resource_dir
        .join("binaries")
        .join(name)
        .join(format!("{name}.exe"));
    if !exe.exists() {
        return Err(format!(
            "sidecar exe not found: {}",
            exe.display()
        ));
    }
    Ok(exe)
}

fn spawn_sidecar(app: &tauri::AppHandle, name: &str) -> Result<Child, String> {
    let exe = sidecar_path(app, name)?;

    // The PyInstaller onedir loader locates `_internal/` relative to the
    // exe on disk (not relative to cwd), so `current_dir` here is mostly
    // cosmetic — but it does give the sidecar a sane cwd for any relative
    // paths it happens to use.
    let cwd = exe.parent().expect("sidecar exe has a parent").to_path_buf();

    let mut cmd = Command::new(&exe);
    cmd.current_dir(&cwd).stdin(Stdio::null());

    // Redirect stdout+stderr to a per-sidecar log file so a failed install
    // on someone else's machine leaves a diagnostic trail. Without this the
    // sidecars' output went to the void and a crash was undebuggable. Falls
    // back to null if the log file can't be opened — logging must never
    // prevent the sidecar from launching.
    match open_log_file(name) {
        Ok(log) => {
            // stderr needs its own handle; the two streams can't share one
            // File (each Stdio takes ownership), so clone the OS handle.
            let err = log.try_clone().map_err(|e| format!("clone log handle: {e}"));
            cmd.stdout(Stdio::from(log));
            match err {
                Ok(err_file) => {
                    cmd.stderr(Stdio::from(err_file));
                }
                Err(_) => {
                    cmd.stderr(Stdio::null());
                }
            }
        }
        Err(e) => {
            eprintln!("could not open {name} log ({e}); discarding sidecar output");
            cmd.stdout(Stdio::null()).stderr(Stdio::null());
        }
    }

    // Windows: CREATE_NO_WINDOW hides the sidecar's console popup. The
    // .spec files still have console=True (useful for `tauri dev` in a
    // terminal), but in the release build we don't want a black cmd
    // window flashing every time the user opens the app.
    #[cfg(windows)]
    {
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    cmd.spawn()
        .map_err(|e| format!("spawn {name}: {e}"))
}

// Open (truncating) the log file for a sidecar at
// %APPDATA%\desk-watcher\logs\{name}.log — the same desk-watcher appdata
// folder the Python side uses for its DB and status file, so all diagnostics
// live in one place. Truncate-on-open keeps logs to one session's worth
// rather than growing unbounded across launches.
fn log_dir() -> Result<PathBuf, String> {
    // Match backend/config.py: Windows -> %APPDATA%, else a sensible home
    // fallback. dirs/appdata via std env keeps us free of an extra crate.
    #[cfg(windows)]
    let base = std::env::var_os("APPDATA")
        .map(PathBuf::from)
        .ok_or_else(|| "APPDATA not set".to_string())?;
    #[cfg(not(windows))]
    let base = std::env::var_os("HOME")
        .map(|h| PathBuf::from(h).join(".local/share"))
        .ok_or_else(|| "HOME not set".to_string())?;

    Ok(base.join("desk-watcher").join("logs"))
}

fn open_log_file(name: &str) -> Result<fs::File, String> {
    let dir = log_dir()?;
    fs::create_dir_all(&dir).map_err(|e| format!("create log dir: {e}"))?;
    let path = dir.join(format!("{name}.log"));
    fs::OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(true)
        .open(&path)
        .map_err(|e| format!("open {}: {e}", path.display()))
}

// Path to the small UI-state marker used for one-time prompts. Lives in the
// same %APPDATA%\desk-watcher\ folder as the DB, logs, and status file.
fn ui_state_dir() -> Result<PathBuf, String> {
    #[cfg(windows)]
    let base = std::env::var_os("APPDATA")
        .map(PathBuf::from)
        .ok_or_else(|| "APPDATA not set".to_string())?;
    #[cfg(not(windows))]
    let base = std::env::var_os("HOME")
        .map(|h| PathBuf::from(h).join(".local/share"))
        .ok_or_else(|| "HOME not set".to_string())?;
    Ok(base.join("desk-watcher"))
}

// Has the "we keep running in the tray" hint been shown before? We use a
// sentinel file rather than a config store to stay dependency-free — its
// mere existence is the flag.
fn close_hint_shown() -> bool {
    match ui_state_dir() {
        Ok(dir) => dir.join(".close_hint_shown").exists(),
        Err(_) => true, // if we can't tell, err toward NOT nagging
    }
}

fn mark_close_hint_shown() {
    if let Ok(dir) = ui_state_dir() {
        let _ = fs::create_dir_all(&dir);
        let _ = fs::write(dir.join(".close_hint_shown"), b"1");
    }
}

fn shutdown(state: &SidecarState) {
    // Kill sidecars best-effort. On Windows, dropping the Job Object below
    // is the real cleanup — this just gets us a tidy exit path in the
    // common case where the process is cooperative.
    if let Ok(mut guard) = state.watcher.lock() {
        if let Some(mut child) = guard.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
    if let Ok(mut guard) = state.api.lock() {
        if let Some(mut child) = guard.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }

    // Drop the job handle last. KILL_ON_JOB_CLOSE fires here and takes
    // out any grandchildren that survived the parent's kill().
    #[cfg(windows)]
    if let Ok(mut guard) = state.job.lock() {
        let _ = guard.take();
    }
}

fn wait_for_api_ready() -> bool {
    // 30 attempts × 500ms = 15 seconds. uvicorn+starlette cold start on
    // a spinning disk can take a couple seconds; 15s is generous but
    // still short enough that a broken install fails fast.
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_millis(300))
        .build()
        .expect("reqwest client builds");

    for _ in 0..30 {
        if let Ok(resp) = client.get("http://127.0.0.1:8765/healthz").send() {
            if resp.status().is_success() {
                return true;
            }
        }
        thread::sleep(Duration::from_millis(500));
    }
    false
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // Create the Job Object up front so it exists before we spawn anything.
    #[cfg(windows)]
    let job = job::Job::new().expect("CreateJobObjectW must succeed");

    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        // Autostart: the `--hidden` arg is what a login-launched instance
        // passes to itself, letting us detect "started at boot" and skip
        // showing the window (see the readiness thread below).
        .plugin(tauri_plugin_autostart::init(
            MacosLauncher::LaunchAgent,
            Some(vec!["--hidden"]),
        ))
        .manage(SidecarState {
            watcher: Mutex::new(None),
            api: Mutex::new(None),
            #[cfg(windows)]
            job: Mutex::new(Some(job)),
            tray_ok: Mutex::new(false),
        })
        .setup(|app| {
            let handle = app.handle().clone();

            // Kick off the api sidecar first so its port is bound before
            // the frontend loads and starts firing requests.
            let api_child = spawn_sidecar(&handle, "api")
                .map_err(|e| format!("failed to spawn api sidecar: {e}"))?;
            let watcher_child = spawn_sidecar(&handle, "watcher")
                .map_err(|e| format!("failed to spawn watcher sidecar: {e}"))?;

            // Assign both to the Job Object BEFORE we hand ownership off
            // to the state Mutex. On Windows a child inherits its parent's
            // job when spawned via CreateProcess, but we didn't set
            // CREATE_BREAKAWAY_FROM_JOB either way — explicit assignment
            // is the reliable path.
            #[cfg(windows)]
            {
                let state = handle.state::<SidecarState>();
                if let Ok(guard) = state.job.lock() {
                    if let Some(job) = guard.as_ref() {
                        if let Err(e) = job.assign(api_child.id()) {
                            eprintln!("job.assign(api): {e}");
                        }
                        if let Err(e) = job.assign(watcher_child.id()) {
                            eprintln!("job.assign(watcher): {e}");
                        }
                    }
                };
            }

            let state = handle.state::<SidecarState>();
            *state.watcher.lock().unwrap() = Some(watcher_child);
            *state.api.lock().unwrap() = Some(api_child);

            // ── System tray ────────────────────────────────────────────
            // Build the tray icon + menu. If this fails, we record tray_ok
            // = false so the close handler falls back to full shutdown
            // instead of hiding into an unquittable state.
            match build_tray(&handle) {
                Ok(()) => {
                    *state.tray_ok.lock().unwrap() = true;
                }
                Err(e) => {
                    eprintln!("tray build failed ({e}); close will exit the app instead of hiding");
                }
            }

            // ── Window reveal ──────────────────────────────────────────
            // A login-launched instance passes `--hidden`; keep the window
            // hidden (sidecars still run headless). Otherwise show it once
            // the API is healthy so the user never sees a "failed to fetch"
            // flash.
            let launched_hidden = std::env::args().any(|a| a == "--hidden");
            let show_handle = handle.clone();
            thread::spawn(move || {
                let ready = wait_for_api_ready();
                if !ready {
                    eprintln!("api sidecar never returned healthy — showing window anyway");
                }
                if launched_hidden {
                    return; // stay in the tray; user opens from the menu
                }
                if let Some(win) = show_handle.get_webview_window("main") {
                    let _ = win.show();
                    let _ = win.set_focus();
                }
            });

            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                let state = window.state::<SidecarState>();
                let tray_ok = state.tray_ok.lock().map(|g| *g).unwrap_or(false);

                if tray_ok {
                    // Close-to-background: keep the sidecars tracking, just
                    // hide the window. Quit is explicit via the tray menu.
                    api.prevent_close();
                    let _ = window.hide();

                    // First time only: tell the user it's still running so
                    // they aren't surprised the camera stays active.
                    if !close_hint_shown() {
                        mark_close_hint_shown();
                        window.app_handle().dialog()
                            .message(
                                "Desk Watcher keeps running in the background to track your day. \
                                 Right-click the tray icon to open it again or to quit.",
                            )
                            .title("Still running in the tray")
                            .blocking_show();
                    }
                } else {
                    // No tray → hiding would strand the process. Full quit.
                    shutdown(&state);
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            // Belt-and-suspenders: if the app is exiting for any reason
            // other than the window close (e.g. system shutdown or a
            // Ctrl-C during dev), still clean up the sidecars.
            if matches!(event, RunEvent::ExitRequested { .. } | RunEvent::Exit) {
                let state = app.state::<SidecarState>();
                shutdown(&state);
            }
        });
}

// Build the system tray icon and its menu. Returns Err if the tray can't be
// created — the caller falls back to close-to-exit so the app is never
// unquittable.
fn build_tray(app: &tauri::AppHandle) -> Result<(), String> {
    let open = MenuItemBuilder::with_id("open", "Open Dashboard")
        .build(app)
        .map_err(|e| format!("open item: {e}"))?;

    // Reflect the current autostart state in the checkbox.
    let autostart_enabled = app.autolaunch().is_enabled().unwrap_or(false);
    let autostart = CheckMenuItemBuilder::with_id("autostart", "Start on login")
        .checked(autostart_enabled)
        .build(app)
        .map_err(|e| format!("autostart item: {e}"))?;

    let quit = MenuItemBuilder::with_id("quit", "Quit Desk Watcher")
        .build(app)
        .map_err(|e| format!("quit item: {e}"))?;

    let menu = MenuBuilder::new(app)
        .item(&open)
        .item(&autostart)
        .separator()
        .item(&quit)
        .build()
        .map_err(|e| format!("menu: {e}"))?;

    let icon = app
        .default_window_icon()
        .cloned()
        .ok_or_else(|| "no default window icon for tray".to_string())?;

    TrayIconBuilder::with_id("main-tray")
        .icon(icon)
        .tooltip("Desk Watcher")
        .menu(&menu)
        .on_menu_event(move |app, event| match event.id().as_ref() {
            "open" => show_main_window(app),
            "quit" => {
                let state = app.state::<SidecarState>();
                shutdown(&state);
                app.exit(0);
            }
            "autostart" => {
                let mgr = app.autolaunch();
                let now_enabled = mgr.is_enabled().unwrap_or(false);
                let result = if now_enabled { mgr.disable() } else { mgr.enable() };
                if let Err(e) = result {
                    eprintln!("toggle autostart: {e}");
                }
                // Sync the checkbox to the real post-toggle state.
                let _ = autostart.set_checked(mgr.is_enabled().unwrap_or(false));
            }
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            // Left-click the icon → open the dashboard (Windows convention).
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                show_main_window(tray.app_handle());
            }
        })
        .build(app)
        .map_err(|e| format!("tray build: {e}"))?;

    Ok(())
}

// Show, unminimize, and focus the main window — used by the tray "Open"
// item and left-click.
fn show_main_window(app: &tauri::AppHandle) {
    if let Some(win) = app.get_webview_window("main") {
        let _ = win.show();
        let _ = win.unminimize();
        let _ = win.set_focus();
    }
}
