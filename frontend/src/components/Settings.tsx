
import { useEffect, useState } from "react";

import { WorkHoursSelect } from "./WorkHoursSelect";
import { useWorkHours } from "../hooks/useWorkHours";
import {
  type CloseAction,
  getAppVersion,
  getAutostartEnabled,
  getSettings,
  isTauri,
  openDataDir,
  quitApp,
  setAutostartEnabled,
  setCloseAction,
} from "../lib/tauri";

function Row({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4 py-3">
      <div className="min-w-0">
        <div className="text-sm text-ink-100">{title}</div>
        {description && (
          <div className="text-2xs text-ink-400 mt-0.5 leading-relaxed">{description}</div>
        )}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

function Toggle({
  checked,
  disabled,
  onChange,
  ariaLabel,
}: {
  checked: boolean;
  disabled?: boolean;
  onChange: (next: boolean) => void;
  ariaLabel: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={
        "relative inline-flex h-5 w-9 items-center rounded-full transition-colors " +
        (disabled
          ? "bg-ink-800 cursor-not-allowed opacity-50"
          : checked
            ? "bg-amber-600 cursor-pointer"
            : "bg-ink-700 cursor-pointer")
      }
    >
      <span
        className={
          "inline-block h-4 w-4 transform rounded-full bg-ink-100 transition-transform " +
          (checked ? "translate-x-4" : "translate-x-0.5")
        }
      />
    </button>
  );
}

export function Settings({ open, onClose }: { open: boolean; onClose: () => void }) {
  const desktop = isTauri();
  const { hours, setHours } = useWorkHours();

  const [autostart, setAutostart] = useState<boolean>(false);
  const [closeAction, setCloseActionState] = useState<CloseAction>("tray");
  const [version, setVersion] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  
  useEffect(() => {
    if (!open || !desktop) return;
    let cancelled = false;
    (async () => {
      try {
        const [s, a, v] = await Promise.all([
          getSettings(),
          getAutostartEnabled(),
          getAppVersion(),
        ]);
        if (cancelled) return;
        setCloseActionState(s.close_action === "quit" ? "quit" : "tray");
        setAutostart(a);
        setVersion(v);
      } catch (e) {
        if (!cancelled) setError(String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, desktop]);

  if (!open) return null;

  async function onToggleAutostart(next: boolean) {
    setError(null);
    setBusy(true);
    const prev = autostart;
    setAutostart(next); 
    try {
      const real = await setAutostartEnabled(next);
      setAutostart(real);
    } catch (e) {
      setAutostart(prev); 
      setError(`Couldn't change startup setting: ${e}`);
    } finally {
      setBusy(false);
    }
  }

  async function onChangeCloseAction(next: CloseAction) {
    setError(null);
    const prev = closeAction;
    setCloseActionState(next); 
    try {
      await setCloseAction(next);
    } catch (e) {
      setCloseActionState(prev);
      setError(`Couldn't save close setting: ${e}`);
    }
  }

  async function onOpenFolder() {
    setError(null);
    try {
      await openDataDir();
    } catch (e) {
      setError(`Couldn't open the folder: ${e}`);
    }
  }

  async function onQuit() {
    if (!window.confirm("Quit Desk Watcher? This stops tracking until you reopen it.")) {
      return;
    }
    try {
      await quitApp();
    } catch (e) {
      setError(`Couldn't quit: ${e}`);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Settings"
    >
      <div
        className="w-[32rem] max-w-[92vw] max-h-[88vh] overflow-y-auto border border-ink-700 bg-ink-900 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between px-5 py-3 border-b border-ink-700">
          <h2 className="text-2xs uppercase tracking-[0.18em] text-ink-300 font-medium">
            Settings
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close settings"
            className="text-ink-400 hover:text-ink-100 transition-colors text-lg leading-none"
          >
            ✕
          </button>
        </header>

        <div className="px-5 py-2">
          {!desktop && (
            <div className="my-3 border border-ink-700 bg-ink-850 px-3 py-2 text-2xs text-ink-300">
              Startup, close behavior, and folder access are only available in the
              desktop app. Work hours still work here.
            </div>
          )}

          {error && (
            <div
              className="my-3 border border-ink-700 px-3 py-2 text-2xs text-ink-100"
              style={{ backgroundColor: "#a04020" }}
              role="status"
            >
              {error}
            </div>
          )}

          <div className="border-b border-ink-800">
            <Row
              title="Launch on startup"
              description="Start Desk Watcher automatically when you log in to Windows."
            >
              <Toggle
                ariaLabel="Launch on startup"
                checked={autostart}
                disabled={!desktop || busy}
                onChange={onToggleAutostart}
              />
            </Row>
          </div>

          <div className="border-b border-ink-800 py-3">
            <div className="text-sm text-ink-100">When I close the window</div>
            <div className="text-2xs text-ink-400 mt-0.5 leading-relaxed">
              Desk Watcher tracks your day in the background. Choose what the ✕
              button does.
            </div>
            <div className="mt-2 flex flex-col gap-1.5">
              {(
                [
                  {
                    value: "tray" as CloseAction,
                    label: "Keep running in the tray",
                    hint: "Tracking continues. Reopen from the tray icon.",
                  },
                  {
                    value: "quit" as CloseAction,
                    label: "Quit the app",
                    hint: "Stops tracking until you launch it again.",
                  },
                ]
              ).map((opt) => (
                <label
                  key={opt.value}
                  className={
                    "flex items-start gap-2.5 px-2.5 py-2 border cursor-pointer transition-colors " +
                    (closeAction === opt.value
                      ? "border-amber-600 bg-ink-850"
                      : "border-ink-800 hover:border-ink-700") +
                    (!desktop ? " opacity-50 cursor-not-allowed" : "")
                  }
                >
                  <input
                    type="radio"
                    name="close-action"
                    className="mt-0.5 accent-amber-600"
                    checked={closeAction === opt.value}
                    disabled={!desktop}
                    onChange={() => onChangeCloseAction(opt.value)}
                  />
                  <span className="min-w-0">
                    <span className="block text-sm text-ink-100">{opt.label}</span>
                    <span className="block text-2xs text-ink-400">{opt.hint}</span>
                  </span>
                </label>
              ))}
            </div>
          </div>

          <div className="border-b border-ink-800">
            <Row
              title="Work hours"
              description="Your workday window. Charts clip durations and detect lunch inside these hours."
            >
              <WorkHoursSelect hours={hours} onChange={setHours} />
            </Row>
          </div>

          <div className="border-b border-ink-800">
            <Row
              title="Data & logs"
              description="Your database, logs, and status file live in your app-data folder."
            >
              <button
                type="button"
                onClick={onOpenFolder}
                disabled={!desktop}
                className={
                  "text-2xs uppercase tracking-wider border border-ink-700 px-2.5 py-1 transition-colors " +
                  (desktop
                    ? "text-ink-200 hover:border-amber-500 hover:text-amber-400"
                    : "text-ink-500 opacity-50 cursor-not-allowed")
                }
              >
                Open folder
              </button>
            </Row>
          </div>

          {/* ── About ── */}
          <div className="py-3">
            <div className="text-sm text-ink-100">About</div>
            <div className="text-2xs text-ink-400 mt-1 leading-relaxed">
              A camera-driven dashboard of your desk activity: breaks, lunch, 
              phone use, and focus. Everything runs locally on your machine.
            </div>
          </div>
        </div>

        {/* ── Footer: quit ── */}
        <footer className="flex items-center justify-between px-5 py-3 border-t border-ink-700 bg-ink-950/40">
          <button
            type="button"
            onClick={onQuit}
            disabled={!desktop}
            className={
              "text-2xs uppercase tracking-wider px-3 py-1.5 border transition-colors " +
              (desktop
                ? "border-ink-700 text-ink-300 hover:text-white"
                : "border-ink-800 text-ink-600 opacity-50 cursor-not-allowed")
            }
            style={desktop ? { backgroundColor: "#a04020" } : undefined}
          >
            Quit Desk Watcher
          </button>
          <button
            type="button"
            onClick={onClose}
            className="text-2xs uppercase tracking-wider px-3 py-1.5 border border-ink-700 text-ink-200 hover:border-ink-500 transition-colors"
          >
            Done
          </button>
        </footer>
      </div>
    </div>
  );
}
