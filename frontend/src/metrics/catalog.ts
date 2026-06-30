/**
 * Catalog of every metric that can appear as a pinnable tile in the top bar.
 *
 * Each entry knows how to derive its display props (value, sub-line,
 * sparkline data) from the three live data sources the dashboard polls:
 * `summary`, `timeline`, and `productivity`. The TileGrid in App.tsx
 * reads its pinned list from localStorage, looks each up by id, and
 * renders the variant the catalog declares.
 *
 * To add a new pinnable metric: add an entry here. No other file
 * usually needs to change. The picker UI auto-populates from
 * `METRIC_CATALOG`.
 *
 * To plug a stub metric into a real pipeline: change its `selector`
 * to derive from the appropriate API response (and add that response
 * to the `MetricInputs` type if it's a new endpoint).
 */
import type { Summary, TimelineResp, ProductivityDay } from "../types";

// ── Display props returned by each selector ───────────────────────────────

export interface TileDisplay {
  value: string;            // the headline number/duration, already formatted
  sub?: string;             // small sub-line under the number
  spark?: number[];         // sparkline points (only for variant: 'sparkline')
}

// ── The data sources every selector can read ──────────────────────────────

export interface MetricInputs {
  summary: Summary | null;
  timeline: TimelineResp | null;
  productivity: ProductivityDay[] | null;
}

// ── Metric definition ──────────────────────────────────────────────────────

export type MetricVariant = "number" | "sparkline";
export type MetricGroup =
  | "activity"     // sips, breaks, lunch, yawns — counter-shaped
  | "time"         // at-desk, on-phone — duration-shaped
  | "pace";        // WPM, focus ratio — rate/ratio-shaped

export interface MetricDef {
  id: string;
  label: string;             // shown on the tile label and in the picker
  description: string;       // longer text in the picker modal
  group: MetricGroup;
  variant: MetricVariant;
  selector: (inputs: MetricInputs) => TileDisplay;
}

// ── Helpers shared across selectors ────────────────────────────────────────

function fmtDuration(min: number): string {
  if (min < 1) return "<1m";
  if (min < 60) return `${Math.round(min)}m`;
  const h = Math.floor(min / 60);
  const m = Math.round(min - h * 60);
  return m === 0 ? `${h}h` : `${h}h ${m}m`;
}

function fmtClock(iso: string): string {
  const d = new Date(iso);
  const h = d.getHours();
  const m = d.getMinutes();
  const suffix = h < 12 ? "a" : "p";
  const h12 = h === 0 ? 12 : h > 12 ? h - 12 : h;
  return `${h12}:${m.toString().padStart(2, "0")}${suffix}`;
}

// "—" is the universal "data not loaded yet" placeholder. We never show
// "0" before data has arrived because 0 looks like a real measurement.
const EMPTY = "—";

// ── Catalog ────────────────────────────────────────────────────────────────

export const METRIC_CATALOG: MetricDef[] = [
  // The original five — kept as the default pinned set.

  {
    id: "at_desk",
    label: "At desk",
    description: "Total time today with you visible at the camera and not on your phone.",
    group: "time",
    variant: "number",
    selector: ({ timeline }) => {
      if (!timeline) return { value: EMPTY, sub: "active today" };
      const s = timeline.segments
        .filter((seg) => seg.activity === "at_desk" || seg.activity === "sipping")
        .reduce((acc, seg) => acc + seg.duration_s, 0);
      return { value: fmtDuration(s / 60), sub: "active today" };
    },
  },

  {
    id: "sips",
    label: "Sips",
    description: "How many distinct drinks the camera saw you take today.",
    group: "activity",
    variant: "number",
    selector: ({ summary }) => ({
      value: summary ? String(summary.sip_count) : EMPTY,
      sub: "hydration",
    }),
  },

  {
    id: "on_phone",
    label: "On phone",
    description: "Time spent on your phone today, in or out of the camera frame.",
    group: "time",
    variant: "number",
    selector: ({ summary }) => {
      if (!summary) return { value: EMPTY, sub: EMPTY };
      const val = fmtDuration(summary.phone_min);
      const sub =
        summary.phone_count === 0
          ? "no sessions"
          : `${summary.phone_count} session${summary.phone_count === 1 ? "" : "s"} · avg ${fmtDuration(summary.phone_avg_session_min)}`;
      return { value: val, sub };
    },
  },

  {
    id: "short_breaks",
    label: "Short breaks",
    description: "Brief absences from your desk (under 20 min, outside the lunch window).",
    group: "activity",
    variant: "number",
    selector: ({ summary }) => {
      if (!summary) return { value: EMPTY, sub: EMPTY };
      return {
        value: String(summary.short_break_count),
        sub: `avg ${fmtDuration(summary.avg_break_duration_min)}`,
      };
    },
  },

  {
    id: "lunch",
    label: "Lunch",
    description: "Today's detected lunch break and its time range.",
    group: "time",
    variant: "number",
    selector: ({ summary }) => {
      if (!summary) return { value: EMPTY, sub: EMPTY };
      if (!summary.lunch) return { value: EMPTY, sub: "not yet" };
      return {
        value: fmtDuration(summary.lunch.duration_min),
        sub: `${fmtClock(summary.lunch.start)}–${fmtClock(summary.lunch.end)}`,
      };
    },
  },

  // ── Additional pinnable metrics — available in the picker. ──────────────

  {
    id: "long_breaks",
    label: "Long breaks",
    description: "Absences longer than 20 minutes (outside the lunch window).",
    group: "activity",
    variant: "number",
    selector: ({ summary }) => ({
      value: summary ? String(summary.long_break_count) : EMPTY,
      sub: "today",
    }),
  },

  {
    id: "yawns",
    label: "Yawns",
    description: "Yawns detected today. (Pipeline pending — requires labeled yawn training data.)",
    group: "activity",
    variant: "number",
    selector: () => ({ value: EMPTY, sub: "pending detection" }),
  },

  {
    id: "wpm",
    label: "WPM",
    description: "Your current typing pace, with a five-minute trace. (Pipeline pending — requires keystroke instrumentation.)",
    group: "pace",
    variant: "sparkline",
    selector: () => ({ value: EMPTY, sub: "pending instrumentation", spark: [] }),
  },

  {
    id: "focus_ratio",
    label: "Focus",
    description:
      "Today's focus ratio: at-desk time vs at-desk + breaks + (½ × phone time). Sparkline shows the last two weeks.",
    group: "pace",
    variant: "sparkline",
    selector: ({ productivity }) => {
      if (!productivity || productivity.length === 0) {
        return { value: EMPTY, sub: "no data yet", spark: [] };
      }
      // Use the same focus_ratio formula as the productivity heatmap so
      // the tile and the heatmap can never disagree.
      const focusRatio = (d: ProductivityDay) => {
        const denom = d.at_desk_min + d.break_total_min + 0.5 * d.phone_min;
        return denom > 0 ? d.at_desk_min / denom : 0;
      };
      // Today is the last entry — productivity is returned chronologically.
      const today = productivity[productivity.length - 1];
      const todayRatio = focusRatio(today);
      // Trailing 14 days for the sparkline (clamped if fewer days exist).
      const window = productivity.slice(-14);
      const spark = window
        .filter((d) => d.at_desk_min >= 30)
        .map((d) => focusRatio(d) * 100);
      return {
        value: today.at_desk_min < 30 ? EMPTY : `${Math.round(todayRatio * 100)}%`,
        sub: "vs last 2 weeks",
        spark,
      };
    },
  },
];

// ── Helpers used by App.tsx / picker ──────────────────────────────────────

export function metricById(id: string): MetricDef | undefined {
  return METRIC_CATALOG.find((m) => m.id === id);
}

// First-run default pinned set. Same five metrics as the v0.x top bar so
// migrating users see no change unless they explicitly customize.
export const DEFAULT_PINNED_IDS: string[] = [
  "at_desk",
  "sips",
  "on_phone",
  "short_breaks",
  "lunch",
];
