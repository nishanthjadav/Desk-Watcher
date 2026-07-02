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

use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

use tauri::{Manager, RunEvent, WindowEvent};

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
    cmd.current_dir(&cwd)
        // Suppress stdio: the sidecars print to their own console when
        // `console=True` in their .spec, which we may want to flip off
        // later. Piping to null keeps things quiet regardless.
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());

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
        .manage(SidecarState {
            watcher: Mutex::new(None),
            api: Mutex::new(None),
            #[cfg(windows)]
            job: Mutex::new(Some(job)),
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
                }
            }

            let state = handle.state::<SidecarState>();
            *state.watcher.lock().unwrap() = Some(watcher_child);
            *state.api.lock().unwrap() = Some(api_child);

            // Block on the readiness poll on a worker thread so we don't
            // stall Tauri's main event loop. When the api is up, show the
            // window; if it never comes up, show it anyway so the user can
            // at least see the failure.
            let show_handle = handle.clone();
            thread::spawn(move || {
                let ready = wait_for_api_ready();
                if !ready {
                    eprintln!("api sidecar never returned healthy — showing window anyway");
                }
                if let Some(win) = show_handle.get_webview_window("main") {
                    let _ = win.show();
                    let _ = win.set_focus();
                }
            });

            Ok(())
        })
        .on_window_event(|window, event| {
            if matches!(event, WindowEvent::CloseRequested { .. }) {
                let state = window.state::<SidecarState>();
                shutdown(&state);
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
