// Windows: hide the console window that appears behind Tauri apps in
// release mode. In dev builds we keep it (via the attribute check) so
// stderr from the Rust supervisor is visible.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    desk_watcher_lib::run()
}
