/**
 * Shared API response types. Mirror the backend's JSON shapes — when
 * an endpoint changes, change the type here too.
 *
 * These were originally inline in App.tsx; extracted so the metric
 * catalog and any future shared module can use them without
 * importing from App.tsx.
 */

export type Category = "short_break" | "long_break" | "lunch";

export interface Absence {
  start: string;
  end: string;
  duration_min: number;
  category: Category;
}

export interface Lunch {
  start: string;
  end: string;
  duration_min: number;
}

export interface Summary {
  date: string;
  sip_count: number;
  phone_count: number;
  phone_min: number;
  phone_avg_session_min: number;
  short_break_count: number;
  long_break_count: number;
  break_count: number;
  avg_break_duration_min: number;
  lunch: Lunch | null;
  absences: Absence[];
  total_events: number;
}

export interface WeekDay {
  date: string;
  sip_count: number;
  short_break_count: number;
  long_break_count: number;
  break_count: number;
  lunch_duration_min: number | null;
}

export interface Segment {
  activity: string;
  start: string;
  end: string;
  duration_s: number;
}

export interface TimelineResp {
  date: string;
  segments: Segment[];
}

export interface ProductivityDay {
  date: string;
  break_count: number;
  short_break_count: number;
  long_break_count: number;
  lunch_duration_min: number | null;
  at_desk_min: number;
  break_total_min: number;   // sum of all real (non-noise) absence durations
  phone_min: number;
}

// Watcher health, from GET /status. Surfaced as a banner when something is
// wrong (camera busy, watcher not running). `camera_ok` is null when the
// watcher hasn't reported yet (still starting up).
export interface WatcherStatus {
  camera_ok: boolean | null;
  detail: string;
  updated_at: string | null;
  stale: boolean;
}
