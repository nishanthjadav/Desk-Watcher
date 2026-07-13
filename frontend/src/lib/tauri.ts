/**
 * Thin typed bridge to the native (Rust) side.
 *
 * The app enables `withGlobalTauri` (see tauri.conf.json), so the Tauri
 * runtime injects `window.__TAURI__.core.invoke` into the webview. We call
 * the custom `#[tauri::command]` functions defined in src-tauri/src/lib.rs
 * through it — no `@tauri-apps/api` npm dependency needed.
 *
 * Graceful degradation: when the dashboard runs in a plain browser
 * (`npm run dev` without the Tauri shell), `window.__TAURI__` is undefined.
 * `isTauri()` reports that, and every helper below resolves to a safe default
 * / no-op instead of throwing, so the dev dashboard still renders and the
 * Settings page shows a "desktop app only" state.
 */

// Minimal shape of the global the runtime injects. We only use core.invoke.
interface TauriGlobal {
  core: {
    invoke: <T>(cmd: string, args?: Record<string, unknown>) => Promise<T>;
  };
}

declare global {
  interface Window {
    __TAURI__?: TauriGlobal;
  }
}

export function isTauri(): boolean {
  return typeof window !== "undefined" && !!window.__TAURI__?.core?.invoke;
}

async function invoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  if (!isTauri()) {
    throw new Error(`invoke(${cmd}) called outside the Tauri runtime`);
  }
  return window.__TAURI__!.core.invoke<T>(cmd, args);
}

// ── Typed command helpers ────────────────────────────────────────────────
// Each mirrors a #[tauri::command] in lib.rs. Names/args must match exactly
// (Tauri lower-snake-cases the JS arg keys → Rust params, so we pass the
// snake_case names the commands declare).

export type CloseAction = "tray" | "quit";

export interface AppSettings {
  close_action: CloseAction;
}

export async function getSettings(): Promise<AppSettings> {
  return invoke<AppSettings>("get_settings");
}

export async function setCloseAction(action: CloseAction): Promise<void> {
  await invoke<void>("set_close_action", { action });
}

export async function getAutostartEnabled(): Promise<boolean> {
  return invoke<boolean>("get_autostart_enabled");
}

export async function setAutostartEnabled(enabled: boolean): Promise<boolean> {
  // Returns the real post-toggle state from the OS.
  return invoke<boolean>("set_autostart_enabled", { enabled });
}

export async function openDataDir(): Promise<void> {
  await invoke<void>("open_data_dir");
}

export async function getAppVersion(): Promise<string> {
  return invoke<string>("get_app_version");
}

export async function quitApp(): Promise<void> {
  // Never resolves in practice — the app exits. Await it anyway for symmetry.
  await invoke<void>("quit_app");
}
