/**
 * User-configurable "work hours" for the dashboard.
 *
 * The selector on the top bar reads/writes this hook. Downstream, the
 * chosen hours drive:
 *   - the visible band of DayTimeline
 *   - the ?start_hour=&end_hour= query params on /summary, /timeline,
 *     and /productivity — the backend clips durations and shifts the
 *     lunch detection window accordingly
 *
 * Persistence: localStorage under WORK_HOURS_KEY (versioned envelope
 * so future migrations don't trip over old shapes).
 */
import { useCallback, useState } from "react";

export interface WorkHours {
  startHour: number;
  endHour: number;
}

// v1: { v: 1, startHour, endHour }
const WORK_HOURS_KEY = "deskwatcher.workHours.v1";

// 9-to-5 is the sensible default. Reproduces the previous behavior of
// the 8-16 hardcoded timeline within one hour, and matches what most
// users would type if asked.
export const DEFAULT_WORK_HOURS: WorkHours = { startHour: 9, endHour: 17 };

function loadWorkHours(): WorkHours {
  if (typeof window === "undefined") return DEFAULT_WORK_HOURS;
  try {
    const raw = window.localStorage.getItem(WORK_HOURS_KEY);
    if (!raw) return DEFAULT_WORK_HOURS;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return DEFAULT_WORK_HOURS;
    const s = Number(parsed.startHour);
    const e = Number(parsed.endHour);
    if (!Number.isInteger(s) || !Number.isInteger(e)) return DEFAULT_WORK_HOURS;
    if (s < 0 || s > 23 || e < 1 || e > 24) return DEFAULT_WORK_HOURS;
    if (e <= s) return DEFAULT_WORK_HOURS;
    return { startHour: s, endHour: e };
  } catch {
    return DEFAULT_WORK_HOURS;
  }
}

function saveWorkHours(h: WorkHours): void {
  try {
    window.localStorage.setItem(
      WORK_HOURS_KEY,
      JSON.stringify({ v: 1, startHour: h.startHour, endHour: h.endHour })
    );
  } catch {
    // non-critical — same treatment as the pinned-tiles hook
  }
}

export function useWorkHours(): {
  hours: WorkHours;
  setHours: (h: WorkHours) => void;
} {
  const [hours, setState] = useState<WorkHours>(loadWorkHours);
  const setHours = useCallback((h: WorkHours) => {
    // Guard: ignore obviously bad values. The select UI filters options
    // to prevent this in the first place, but callers get the same
    // defensive check.
    if (
      !Number.isInteger(h.startHour) ||
      !Number.isInteger(h.endHour) ||
      h.endHour <= h.startHour ||
      h.startHour < 0 ||
      h.endHour > 24
    ) {
      return;
    }
    setState(h);
    saveWorkHours(h);
  }, []);
  return { hours, setHours };
}
