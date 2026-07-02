/**
 * Client-side refutations of long-break absences.
 *
 * When the user marks an absence as "not really a break" (an in-person
 * meeting, for example), we remember that decision in localStorage. The
 * transforms in ../refutations then reclassify the interval as at-desk
 * time before it's rendered anywhere — top-bar tiles, timeline, focus
 * sparkline, today's heatmap cell, breaks list.
 *
 * Scope: refutations are keyed by the absence's `start` ISO string.
 * That key is stable across /summary polls because the backend computes
 * absences deterministically from the same raw event rows. Refutations
 * belong to a specific date; the hook takes the current `summary.date`
 * so past-day refutations don't accidentally apply to today's data with
 * a similarly-timed absence.
 *
 * Old refutations remain in storage indefinitely — cheap, and useful
 * if we later want to render a "your refutation history" panel. They
 * simply don't participate in today's transforms.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import type { Absence } from "../types";

export interface Refutation {
  start: string;         // ISO — the natural key
  end: string;           // ISO — kept for pretty rendering in the footer
  duration_min: number;  // snapshot at time of refutation
  refutedAt: string;     // ISO — when the user clicked
}

const REFUTED_KEY = "deskwatcher.refutedAbsences.v1";

function loadAll(): Refutation[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(REFUTED_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (r): r is Refutation =>
        r &&
        typeof r === "object" &&
        typeof r.start === "string" &&
        typeof r.end === "string" &&
        typeof r.duration_min === "number" &&
        typeof r.refutedAt === "string"
    );
  } catch {
    return [];
  }
}

function saveAll(rs: Refutation[]): void {
  try {
    window.localStorage.setItem(REFUTED_KEY, JSON.stringify(rs));
  } catch {
    // non-critical
  }
}

function dateOf(iso: string): string {
  // The refutation's date is the *local* date of the absence start.
  // We compare against summary.date, which is also local (backend uses
  // LOCAL_TZ when it computes the day bounds).
  return new Date(iso).toISOString().slice(0, 10);
}

export function useRefutations(currentDate: string | undefined): {
  refutations: Refutation[];
  isRefuted: (start: string) => boolean;
  refute: (a: Absence) => void;
  unrefute: (start: string) => void;
} {
  // All stored refutations, regardless of date. Persistence layer.
  const [all, setAll] = useState<Refutation[]>(loadAll);

  // Sync to storage on every change. Kept as an effect so React 18/19
  // strict-mode double-invocation of state setters is safe.
  useEffect(() => {
    saveAll(all);
  }, [all]);

  // The list surfaced to callers is scoped to the current date so the
  // transforms don't reach across days.
  const refutations = useMemo(() => {
    if (!currentDate) return [];
    return all.filter((r) => dateOf(r.start) === currentDate);
  }, [all, currentDate]);

  const refutedSet = useMemo(
    () => new Set(refutations.map((r) => r.start)),
    [refutations]
  );

  const isRefuted = useCallback(
    (start: string) => refutedSet.has(start),
    [refutedSet]
  );

  const refute = useCallback((a: Absence) => {
    setAll((prev) => {
      if (prev.some((r) => r.start === a.start)) return prev;
      const next: Refutation = {
        start: a.start,
        end: a.end,
        duration_min: a.duration_min,
        refutedAt: new Date().toISOString(),
      };
      return [...prev, next];
    });
  }, []);

  const unrefute = useCallback((start: string) => {
    setAll((prev) => prev.filter((r) => r.start !== start));
  }, []);

  return { refutations, isRefuted, refute, unrefute };
}
