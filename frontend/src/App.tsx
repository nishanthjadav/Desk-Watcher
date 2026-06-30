import { useEffect, useMemo, useState } from "react";

import { Panel } from "./components/Panel";
import { PinPicker, TileGrid, usePinControls } from "./components/TileGrid";
import type {
  Absence,
  Category,
  Lunch,
  ProductivityDay,
  Segment,
  Summary,
  TimelineResp,
} from "./types";

const API = "http://localhost:8000";
const POLL_MS = 30_000;

type HeatmapRange = "year" | "6m" | "month";

const HEATMAP_RANGES: { value: HeatmapRange; label: string; days: number; right: string }[] = [
  { value: "month", label: "Month", days: 31, right: "this month" },
  { value: "6m", label: "6m", days: 26 * 7, right: "last 6 months" },
  { value: "year", label: "Year", days: 365, right: "this year" },
];

// Lunch chart ranges. "week" shows the last 7 days as one bar per day,
// "month" shows the current calendar month as one bar per day, and "6m"
// aggregates to weekly averages (26 bars) since 180 daily bars would be
// unreadable in the panel's width.
type LunchRange = "week" | "month" | "6m";

const LUNCH_RANGES: { value: LunchRange; label: string; days: number; right: string }[] = [
  { value: "week", label: "Week", days: 7, right: "this week" },
  { value: "month", label: "Month", days: 31, right: "this month" },
  { value: "6m", label: "6m", days: 26 * 7, right: "last 6 months" },
];

// Timeline palette — deliberately distinct from the heatmap convention.
// The timeline tells a "where were the gaps in your workday" story, so
// at-desk is a muted canvas and breaks read as neutral notches cut into it.
const TL_AT_DESK = "#7a4a08";        // muted amber — the workday baseline
const TL_PHONE = "#a04020";          // rust — anti-productivity, reads as a warning band
const TL_BREAK = "#4a4640";          // neutral slate — break notch
const TL_BG = "#1a1815";             // unrecorded portion of the visible window
const TL_NOW = "#7dd3fc";            // cool blue cursor — pops against warm palette
const TL_SIP = "#f5a623";            // sip pip color

const CATEGORY_LABEL: Record<Category, string> = {
  short_break: "Short break",
  long_break: "Long break",
  lunch: "Lunch",
};

const CATEGORY_COLOR: Record<Category, string> = {
  short_break: "#b5afa4",
  long_break: "#f5a623",
  lunch: "#e08a0c",
};

function fmtClock(iso: string): string {
  // 12-hour with lowercase a/p suffix. Browsers' Intl AM/PM strings are
  // not customizable, so we format ourselves: "8:13a", "12:00p", "3:30p".
  const d = new Date(iso);
  const h = d.getHours();
  const m = d.getMinutes();
  const suffix = h < 12 ? "a" : "p";
  const h12 = h === 0 ? 12 : h > 12 ? h - 12 : h;
  return `${h12}:${m.toString().padStart(2, "0")}${suffix}`;
}

function fmtHour12(h: number): string {
  // Hour-only labels for timeline tick marks. "8a" / "12p" — compact
  // single-letter suffix so labels stay narrow on the ruler.
  if (h === 0) return "12a";
  if (h === 12) return "12p";
  return h < 12 ? `${h}a` : `${h - 12}p`;
}

function fmtDuration(min: number): string {
  if (min < 1) return "<1m";
  if (min < 60) return `${Math.round(min)}m`;
  const h = Math.floor(min / 60);
  const m = Math.round(min - h * 60);
  return m === 0 ? `${h}h` : `${h}h ${m}m`;
}

function startOfDayMs(iso: string): number {
  const d = new Date(iso);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

function useClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return now;
}

function useFetch<T>(url: string, pollMs?: number) {
  const [data, setData] = useState<T | null>(null);
  useEffect(() => {
    let cancelled = false;
    const tick = () => {
      fetch(url)
        .then((r) => r.json())
        .then((d) => { if (!cancelled) setData(d); })
        .catch(() => {});
    };
    tick();
    if (pollMs) {
      const id = setInterval(tick, pollMs);
      return () => { cancelled = true; clearInterval(id); };
    }
    return () => { cancelled = true; };
  }, [url, pollMs]);
  return data;
}

function CategoryBadge({ category }: { category: Category }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 text-2xs uppercase tracking-wider text-ink-200"
    >
      <span className="w-2 h-2" style={{ backgroundColor: CATEGORY_COLOR[category] }} />
      {CATEGORY_LABEL[category]}
    </span>
  );
}

function DayTimeline({ data }: { data: TimelineResp | null }) {
  if (!data || data.segments.length === 0) {
    return <div className="px-4 py-6 text-ink-400 text-sm">No activity recorded yet.</div>;
  }

  // Hard-pin the visible window to the workday: 8a–4p local time. Period.
  const startHour = 8;
  const endHour = 16;
  const visibleHours = endHour - startHour;

  // Local midnight for the day this timeline is showing (derived from the
  // YYYY-MM-DD string the backend gives us so it is independent of any
  // UTC↔local shift in the segment timestamps).
  const localMidnight = new Date(data.date + "T00:00:00").getTime();
  const windowStart = localMidnight + startHour * 3600 * 1000;
  const windowEnd = localMidnight + endHour * 3600 * 1000;
  const windowSpanMs = windowEnd - windowStart;

  const ticks: number[] = [];
  for (let h = startHour; h <= endHour; h++) ticks.push(h);

  const hourToPct = (h: number) => ((h - startHour) / visibleHours) * 100;
  const msToPct = (ms: number) => ((ms - windowStart) / windowSpanMs) * 100;

  // Per-activity totals across all segments (not clipped to window — these
  // are summary numbers, useful even if you started before 8a).
  const totals: Record<string, number> = { at_desk: 0, away: 0, sipping: 0, phone: 0 };
  for (const s of data.segments) {
    totals[s.activity] = (totals[s.activity] ?? 0) + s.duration_s;
  }
  const breakCount = data.segments.filter((s) => s.activity === "away").length;

  // Coalesce raw sip segments into distinct drinks. Mirrors the backend's
  // _coalesce_sips so the pip lane and legend total match summary.sip_count
  // exactly.
  //
  // Algorithm note: the backend compares each sip to the IMMEDIATELY
  // PREVIOUS sip's timestamp (chain semantics). We must do the same here.
  // A slow drumbeat of sips ~60s apart should chain into one drink
  // because each step is < 90s, not split into multiple drinks because
  // each is > 90s from the FIRST sip.
  const SIP_COALESCE_GAP_MS = 90_000;
  const rawSips = data.segments.filter((s) => s.activity === "sipping");
  const sipSegments: typeof rawSips = [];
  let prevSipMs: number | null = null;
  for (const seg of rawSips) {
    const segMs = new Date(seg.start).getTime();
    if (prevSipMs !== null && segMs - prevSipMs <= SIP_COALESCE_GAP_MS) {
      // Part of the same drink chain — don't push a new pip, but DO
      // advance the chain reference so the next sip is measured against
      // this one, not the original.
      prevSipMs = segMs;
      continue;
    }
    sipSegments.push(seg);
    prevSipMs = segMs;
  }

  const todayIso = new Date().toISOString().slice(0, 10);
  const isToday = data.date === todayIso;
  const nowMs = Date.now();
  const nowPct = isToday && nowMs >= windowStart && nowMs <= windowEnd ? msToPct(nowMs) : null;

  // Map a segment to its rendered band color. Sipping reads as "still at
  // desk" on the main bar (the sip pip lane below carries the count).
  // Phone is full-height — it's a distinct state, not a modifier.
  const bandColor = (activity: string): string | null => {
    if (activity === "at_desk" || activity === "sipping") return TL_AT_DESK;
    if (activity === "phone") return TL_PHONE;
    if (activity === "away") return TL_BREAK;
    return null;
  };

  return (
    <div className="px-4 py-4">
      {/* Main bar */}
      <div
        className="relative h-9 border border-ink-700 overflow-hidden"
        style={{ backgroundColor: TL_BG }}
      >
        {/* Hour gridlines (behind segments) */}
        {ticks.slice(1, -1).map((h) => (
          <div
            key={`grid-${h}`}
            className="absolute top-0 bottom-0 w-px"
            style={{ left: `${hourToPct(h)}%`, backgroundColor: "#26231f" }}
          />
        ))}

        {data.segments.map((s, i) => {
          const start = new Date(s.start).getTime();
          const end = new Date(s.end).getTime();
          const clippedStart = Math.max(start, windowStart);
          const clippedEnd = Math.min(end, windowEnd);
          if (clippedEnd <= clippedStart) return null;
          const color = bandColor(s.activity);
          if (!color) return null;
          const left = msToPct(clippedStart);
          const width = msToPct(clippedEnd) - left;
          const isBreak = s.activity === "away";
          return (
            <div
              key={i}
              className="absolute"
              style={{
                left: `${left}%`,
                width: `${Math.max(width, 0.08)}%`,
                // Notch breaks inward by 4px top/bottom so they read as
                // "cuts" in the work bar rather than equal-weight bands.
                top: isBreak ? 4 : 0,
                bottom: isBreak ? 4 : 0,
                backgroundColor: color,
              }}
              title={`${s.activity} · ${fmtClock(s.start)}–${fmtClock(s.end)} · ${fmtDuration(s.duration_s / 60)}`}
            />
          );
        })}

        {nowPct != null && (
          <div
            className="absolute top-0 bottom-0"
            style={{ left: `calc(${nowPct}% - 1px)`, width: 2, backgroundColor: TL_NOW }}
            title="Now"
          />
        )}
      </div>

      {/* Sip pip lane — one tick per sip event so they're countable. */}
      <div className="relative h-3 mt-1">
        {sipSegments.map((s, i) => {
          const t = new Date(s.start).getTime();
          if (t < windowStart || t > windowEnd) return null;
          return (
            <div
              key={i}
              className="absolute top-0 bottom-0 w-px"
              style={{ left: `${msToPct(t)}%`, backgroundColor: TL_SIP }}
              title={`sip · ${fmtClock(s.start)}`}
            />
          );
        })}
      </div>

      {/* Hour ruler */}
      <div className="relative h-4 mt-1 text-2xs text-ink-400 tabular">
        {ticks.map((h) => (
          <span
            key={h}
            className="absolute -translate-x-1/2"
            style={{ left: `${hourToPct(h)}%` }}
          >
            {fmtHour12(h)}
          </span>
        ))}
      </div>

      {/* Legend — collapsed to the four states that actually carry meaning. */}
      <div className="flex flex-wrap gap-x-4 gap-y-1 mt-3 text-2xs text-ink-300">
        <span className="inline-flex items-center gap-1.5">
          <span className="w-3 h-2" style={{ backgroundColor: TL_AT_DESK }} />
          <span>At desk</span>
          <span className="text-ink-500 tabular">{fmtDuration((totals.at_desk + totals.sipping) / 60)}</span>
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="w-3 h-1" style={{ backgroundColor: TL_BREAK }} />
          <span>Break</span>
          <span className="text-ink-500 tabular">{fmtDuration(totals.away / 60)}</span>
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="w-3 h-2" style={{ backgroundColor: TL_PHONE }} />
          <span>On phone</span>
          <span className="text-ink-500 tabular">{fmtDuration(totals.phone / 60)}</span>
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="w-px h-3" style={{ backgroundColor: TL_SIP }} />
          <span>Sip</span>
          <span className="text-ink-500 tabular">{sipSegments.length}</span>
        </span>
        {nowPct != null && (
          <span className="inline-flex items-center gap-1.5">
            <span className="w-px h-3" style={{ backgroundColor: TL_NOW }} />
            <span>Now</span>
          </span>
        )}
      </div>
    </div>
  );
}

function ProductivityHeatmap({ data, range }: { data: ProductivityDay[] | null; range: HeatmapRange }) {
  if (!data) return <div className="px-4 py-6 text-ink-400 text-sm">Loading…</div>;

  // Filter to "tracked" days only (>= 30 min of at-desk time) for the
  // average and the legend stats. Untracked days render as "no data".
  const tracked = data.filter((d) => d.at_desk_min >= 30);
  if (tracked.length === 0) {
    return <div className="px-4 py-6 text-ink-400 text-sm">Not enough data yet — run the watcher for a full workday.</div>;
  }

  // Focus ratio per day:
  //   at_desk / (at_desk + break + PHONE_WEIGHT * phone)
  //
  // Phone is weighted at HALF compared to being away from the desk. A
  // glance at your phone while a build runs is meaningfully different
  // from disappearing for 30 minutes — both count against focus, but
  // not equally. (Phone events are also still over-counted somewhat by
  // the detector, so this also gives the formula a buffer against that.)
  // This measures how much of your tracked time you actually spent at
  // your desk doing work. It's bounded 0..1 and inherently normalized —
  // a half-day and a full-day score on the same scale. Lunch counts
  // against the ratio (it's time off your desk, however justified).
  const PHONE_WEIGHT = 0.5;
  function focusRatio(d: ProductivityDay): number {
    const denom = d.at_desk_min + d.break_total_min + PHONE_WEIGHT * d.phone_min;
    if (denom <= 0) return 0;
    return d.at_desk_min / denom;
  }

  const avgRatio = tracked.reduce((s, d) => s + focusRatio(d), 0) / tracked.length;
  const minRatio = Math.min(...tracked.map(focusRatio));
  const maxRatio = Math.max(...tracked.map(focusRatio));

  // Five FIXED buckets keyed to focus ratio. Brightest amber = most
  // focused day; darkest = least focused. These thresholds are tuned
  // for a normal workday (typing/reading with occasional breaks) and
  // are intentionally forgiving — a real workday with lunch + a couple
  // of meetings + bathroom breaks + some phone time can dip below 50%
  // and still represent solid work, so the top bucket starts at 65%
  // and the "barely worked" floor isn't reached until ~15%.
  // 0 → brightest (most focused), 4 → darkest (least focused).
  const ramp = ["#f5a623", "#b86d07", "#5c3604", "#3a2202", "#1c1a17"];
  const RATIO_THRESHOLDS = [0.65, 0.45, 0.30, 0.15]; // descending
  const noData = "#0a0908";

  const bucket = (ratio: number): number => {
    // 0 = highest ratio (brightest), 4 = lowest.
    for (let i = 0; i < RATIO_THRESHOLDS.length; i++) {
      if (ratio >= RATIO_THRESHOLDS[i]) return i;
    }
    return ramp.length - 1;
  };

  const fmtPct = (r: number): string => `${Math.round(r * 100)}%`;

  const byDate: Record<string, ProductivityDay> = {};
  for (const d of data) byDate[d.date] = d;

  const localIso = (d: Date) => {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  };

  // Decide the visible window based on `range`. All ranges render as
  // columns-of-weeks so the markup stays the same.
  const today = new Date();
  let rangeStart: Date;
  let rangeEnd: Date;
  let showMonthLabels = true;

  if (range === "year") {
    rangeStart = new Date(today.getFullYear(), 0, 1);
    rangeEnd = new Date(today.getFullYear(), 11, 31);
  } else if (range === "6m") {
    // Rolling 26 weeks ending this week's Saturday.
    rangeEnd = new Date(today);
    rangeEnd.setDate(rangeEnd.getDate() + (6 - rangeEnd.getDay()));
    rangeStart = new Date(rangeEnd);
    rangeStart.setDate(rangeStart.getDate() - (26 * 7 - 1));
  } else {
    // Current calendar month.
    rangeStart = new Date(today.getFullYear(), today.getMonth(), 1);
    rangeEnd = new Date(today.getFullYear(), today.getMonth() + 1, 0);
    showMonthLabels = false;
  }

  // Align grid start to the Sunday on or before rangeStart so each column is
  // a full Sun..Sat week, with out-of-range days rendered as blanks.
  const gridStart = new Date(rangeStart);
  gridStart.setDate(gridStart.getDate() - gridStart.getDay());

  const weeks: { date: string | null; day: ProductivityDay | null }[][] = [];
  const cursor = new Date(gridStart);
  while (cursor <= rangeEnd) {
    const week: { date: string | null; day: ProductivityDay | null }[] = [];
    for (let dow = 0; dow < 7; dow++) {
      const inRange = cursor >= rangeStart && cursor <= rangeEnd;
      const iso = inRange ? localIso(cursor) : null;
      const day = iso ? (byDate[iso] ?? null) : null;
      week.push({ date: iso, day });
      cursor.setDate(cursor.getDate() + 1);
    }
    weeks.push(week);
  }

  // Month labels: anchor each month to the column containing its 1st day.
  // Skip months whose 1st falls outside the visible range.
  const monthLabels: { col: number; label: string }[] = [];
  if (showMonthLabels) {
    const startMonth = new Date(rangeStart.getFullYear(), rangeStart.getMonth(), 1);
    const endMonth = new Date(rangeEnd.getFullYear(), rangeEnd.getMonth(), 1);
    const m = new Date(startMonth);
    while (m <= endMonth) {
      const firstIso = localIso(m);
      const col = weeks.findIndex((w) => w.some((c) => c.date === firstIso));
      if (col !== -1) {
        monthLabels.push({
          col,
          label: m.toLocaleDateString([], { month: "short" }),
        });
      }
      m.setMonth(m.getMonth() + 1);
    }
  }

  const dowLabels = ["", "Mon", "", "Wed", "", "Fri", ""];

  return (
    // h-full + justify-center so the heatmap floats vertically centered
    // inside whatever height the panel takes from its sibling (Lunch
    // chart), rather than hugging the top and leaving dead space below.
    <div className="px-4 py-4 h-full flex flex-col justify-center">


      <div className="flex gap-1">
        {/* Day-of-week labels (column for the labels themselves) */}
        <div
          className="grid gap-[2px] text-2xs text-ink-400 tabular w-7 pt-[18px]"
          style={{ gridTemplateRows: "repeat(7, 1fr)" }}
        >
          {dowLabels.map((d, i) => (
            <div key={i} className="leading-none flex items-center">{d}</div>
          ))}
        </div>

        {/* Grid: month strip on top, weeks × days below — same column tracks
            so labels align with their columns no matter the panel width.
            Cap column width so few-column views (month, 6m) don't stretch
            cells into giant squares that blow up the panel height. */}
        <div
          className="flex-1 grid gap-[2px]"
          style={{
            gridTemplateColumns: `repeat(${weeks.length}, minmax(0, 1fr))`,
            maxWidth: `${weeks.length * 22}px`,
          }}
        >
          {/* Month strip spans all columns (only when there's >1 month) */}
          {showMonthLabels && (
            <div
              className="relative h-4 mb-1 text-2xs text-ink-400"
              style={{ gridColumn: `1 / span ${weeks.length}` }}
            >
              {monthLabels.map((m) => (
                <span
                  key={`${m.col}-${m.label}`}
                  className="absolute"
                  style={{ left: `${(m.col / weeks.length) * 100}%` }}
                >
                  {m.label}
                </span>
              ))}
            </div>
          )}

          {/* One column per week, each is a 7-row grid */}
          {weeks.map((week, wi) => (
            <div
              key={wi}
              className="grid gap-[2px]"
              style={{ gridTemplateRows: "repeat(7, 1fr)" }}
            >
              {week.map((cell, di) => {
                const common = "w-full aspect-square";
                if (!cell.date) {
                  return <div key={di} className={common} />;
                }
                if (!cell.day || cell.day.at_desk_min < 30) {
                  return (
                    <div
                      key={di}
                      className={`${common} border border-ink-800`}
                      style={{ backgroundColor: noData }}
                      title={`${cell.date} · no data`}
                    />
                  );
                }
                const ratio = focusRatio(cell.day);
                const b = bucket(ratio);
                return (
                  <div
                    key={di}
                    className={common}
                    style={{ backgroundColor: ramp[b] }}
                    title={`${cell.date} · ${fmtPct(ratio)} focused`}
                  />
                );
              })}
            </div>
          ))}
        </div>
      </div>

      {/* Legend */}
      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-2xs text-ink-400">
        <span className="inline-flex items-center gap-2">
          <span>More focused</span>
          {ramp.map((c) => (
            <span key={c} className="w-3 h-3" style={{ backgroundColor: c }} />
          ))}
          <span>Less focused</span>
        </span>
        <span className="text-ink-500">
          range {fmtPct(minRatio)}–{fmtPct(maxRatio)} · avg {fmtPct(avgRatio)}
        </span>
        <span className="inline-flex items-center gap-2">
          <span className="w-3 h-3 border border-ink-800" style={{ backgroundColor: noData }} />
          <span>no data</span>
        </span>
        {/* Muted text affordance — explains the focus_ratio formula and
            bucket thresholds on hover. Plain underlined text reads cleaner
            here than a chip-bordered icon next to the legend swatches. */}
        <span
          className="ml-auto underline decoration-dotted underline-offset-2 text-ink-500 cursor-help"
          title={
            "Focus ratio = at-desk / (at-desk + breaks + 0.5 × phone)\n" +
            "Phone is half-weighted: a glance during a build is meaningfully\n" +
            "different from disappearing for 30 minutes. Bounded 0–100% and\n" +
            "inherently normalized (a half-day and a full-day score on the\n" +
            "same scale). Lunch counts against the ratio (it's time off your\n" +
            "desk, however justified).\n\n" +
            "Color buckets:\n" +
            "  ≥ 65%   brightest amber: mostly focused\n" +
            "  ≥ 45%   bright: focused with normal breaks\n" +
            "  ≥ 30%   mid: meaningful break/phone time\n" +
            "  ≥ 15%   dark: mostly off-task\n" +
            "  < 15%   darkest: barely worked at desk\n\n" +
            "Days with <30 min of at-desk time render as 'no data'."
          }
        >
          how this is calculated
        </span>
      </div>
    </div>
  );
}

// A single bar in the LunchChart — the data is the same shape regardless
// of whether it's a per-day bar or a weekly-average bar. `label` is the
// short label under the bar; `tooltip` is the hover string.
interface LunchBar {
  key: string;
  label: string;
  tooltip: string;
  lunch_min: number | null;
  isToday: boolean;
}

// Local-date YYYY-MM-DD for `Date`. Avoids the timezone wobble that
// toISOString() can introduce when crossing midnight in some zones.
function localIso(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function buildLunchBars(data: ProductivityDay[], range: LunchRange): LunchBar[] {
  const todayIso = localIso(new Date());
  const byDate: Record<string, ProductivityDay> = {};
  for (const d of data) byDate[d.date] = d;

  if (range === "week") {
    // Fixed Mon–Fri row, in that order. Sat/Sun deliberately omitted —
    // the user asked for "Monday far left fixed, Friday far right fixed."
    // We pick whichever Mon–Fri belongs to the current week (where the
    // week contains today). Days the watcher didn't run still get a
    // bar slot, just with no value.
    const now = new Date();
    // Find this week's Monday. JS getDay(): 0=Sun..6=Sat → Monday is
    // (date - dow + 1) when dow > 0; for Sunday we go back 6 days.
    const dow = now.getDay();
    const monday = new Date(now);
    monday.setDate(now.getDate() - (dow === 0 ? 6 : dow - 1));
    const weekdayNames = ["Mon", "Tue", "Wed", "Thu", "Fri"];
    return weekdayNames.map((wd, i) => {
      const date = new Date(monday);
      date.setDate(monday.getDate() + i);
      const iso = localIso(date);
      const day = byDate[iso];
      return {
        key: iso,
        label: wd,
        tooltip:
          day?.lunch_duration_min != null
            ? `${iso} (${wd}) · lunch ${Math.round(day.lunch_duration_min)}m`
            : `${iso} (${wd}) · no lunch detected`,
        lunch_min: day?.lunch_duration_min ?? null,
        isToday: iso === todayIso,
      };
    });
  }

  if (range === "month") {
    // One bar per calendar week within the current month. The label is
    // the date range that week covers, clamped to the month boundaries
    // — e.g. for August: "Aug 1–4", "5–11", "12–18", "19–25", "26–31".
    // Weeks run Mon–Sun; week N is the week containing the day (N*7 - 6)
    // counting from the 1st. Simpler: walk the month day-by-day and
    // group into Mon-anchored buckets.
    const now = new Date();
    const year = now.getFullYear();
    const month = now.getMonth();
    const lastDay = new Date(year, month + 1, 0).getDate();

    // Build the buckets: each entry is an array of ISO dates in that week.
    const buckets: { startDay: number; endDay: number; isos: string[] }[] = [];
    let currentBucket: { startDay: number; endDay: number; isos: string[] } | null = null;
    for (let d = 1; d <= lastDay; d++) {
      const dt = new Date(year, month, d);
      const iso = localIso(dt);
      const isMonday = dt.getDay() === 1;
      if (currentBucket === null || isMonday) {
        // Close previous bucket (its endDay is the previous d).
        if (currentBucket !== null) buckets.push(currentBucket);
        currentBucket = { startDay: d, endDay: d, isos: [iso] };
      } else {
        currentBucket.endDay = d;
        currentBucket.isos.push(iso);
      }
    }
    if (currentBucket !== null) buckets.push(currentBucket);

    const monthShort = now.toLocaleDateString([], { month: "short" });
    return buckets.map((b, i) => {
      const lunches: number[] = [];
      for (const iso of b.isos) {
        const day = byDate[iso];
        if (day?.lunch_duration_min != null) lunches.push(day.lunch_duration_min);
      }
      const avg =
        lunches.length > 0 ? lunches.reduce((s, v) => s + v, 0) / lunches.length : null;
      // Label: "Week N · Aug 1–4". Keeping both the ordinal and the
      // date range so the user sees BOTH abstractions the user asked for
      // ("week 1, week 2, …") AND the concrete dates that week covers.
      const dateRange =
        b.startDay === b.endDay
          ? `${monthShort} ${b.startDay}`
          : `${monthShort} ${b.startDay}–${b.endDay}`;
      const containsToday =
        now.getMonth() === month && b.startDay <= now.getDate() && now.getDate() <= b.endDay;
      return {
        key: `wk${i}`,
        label: dateRange,
        tooltip:
          avg != null
            ? `Week ${i + 1} (${dateRange}) · avg lunch ${Math.round(avg)}m (${lunches.length} day${lunches.length === 1 ? "" : "s"})`
            : `Week ${i + 1} (${dateRange}) · no lunches detected`,
        lunch_min: avg,
        isToday: containsToday,
      };
    });
  }

  // 6m — one bar per calendar month, ending with the current month.
  // Label: short month name (Jan, Feb, ...). Bucket = average detected
  // lunch across the month's days.
  const now = new Date();
  const months: { year: number; month: number; label: string }[] = [];
  for (let i = 5; i >= 0; i--) {
    const dt = new Date(now.getFullYear(), now.getMonth() - i, 1);
    months.push({
      year: dt.getFullYear(),
      month: dt.getMonth(),
      label: dt.toLocaleDateString([], { month: "short" }),
    });
  }
  return months.map((m) => {
    const lastDay = new Date(m.year, m.month + 1, 0).getDate();
    const lunches: number[] = [];
    for (let d = 1; d <= lastDay; d++) {
      const iso = localIso(new Date(m.year, m.month, d));
      const day = byDate[iso];
      if (day?.lunch_duration_min != null) lunches.push(day.lunch_duration_min);
    }
    const avg =
      lunches.length > 0 ? lunches.reduce((s, v) => s + v, 0) / lunches.length : null;
    const isCurrentMonth = m.year === now.getFullYear() && m.month === now.getMonth();
    return {
      key: `${m.year}-${m.month}`,
      label: m.label,
      tooltip:
        avg != null
          ? `${m.label} ${m.year} · avg lunch ${Math.round(avg)}m (${lunches.length} day${lunches.length === 1 ? "" : "s"})`
          : `${m.label} ${m.year} · no lunches detected`,
      lunch_min: avg,
      isToday: isCurrentMonth,
    };
  });
}

function LunchChart({ data, range }: { data: ProductivityDay[] | null; range: LunchRange }) {
  if (!data || data.length === 0) {
    return <div className="px-4 py-6 text-ink-400 text-sm">No lunch data yet.</div>;
  }

  const bars = buildLunchBars(data, range);
  const durations = bars.map((b) => b.lunch_min).filter((v): v is number => v != null);
  const hasAny = durations.length > 0;
  if (!hasAny) {
    return (
      <div className="px-4 py-6 text-ink-400 text-sm">
        No lunches detected in this range.
      </div>
    );
  }

  const avg = durations.reduce((s, v) => s + v, 0) / durations.length;
  const max = Math.max(60, ...durations); // axis ceiling at least 60m
  const niceMax = Math.ceil(max / 15) * 15;
  const ticks = [0, niceMax / 2, niceMax];

  // Caption above the chart adapts to the range. The "avg over N
  // days/weeks/months" suffix tells the user what the dashed line means.
  const unitLabel = range === "week" ? "day" : range === "month" ? "week" : "month";
  const caption =
    range === "week"
      ? "Lunch duration per day this week"
      : range === "month"
        ? "Average lunch per week this month"
        : "Average lunch per month — last 6 months";

  return (
    <div className="px-4 py-4">


      <div className="flex gap-2 h-36">
        {/* Y axis */}
        <div className="relative w-8 text-2xs text-ink-400 tabular">
          {ticks.map((t) => (
            <span
              key={t}
              className="absolute right-0 -translate-y-1/2"
              style={{ top: `${100 - (t / niceMax) * 100}%` }}
            >
              {t}m
            </span>
          ))}
        </div>

        {/* Bars + gridlines + average line. Critical: the bar heights and
            the average line MUST share the exact same vertical space —
            both `(v / niceMax) * 100%` of THIS container — or the avg
            line drifts above/below the bars. That's why the value/day
            labels are rendered OUTSIDE this box, in the row below. */}
        <div className="relative flex-1 border-l border-b border-ink-700">
          {ticks.slice(1).map((t) => (
            <div
              key={t}
              className="absolute left-0 right-0 border-t border-ink-800"
              style={{ top: `${100 - (t / niceMax) * 100}%` }}
            />
          ))}

          <div
            className="absolute left-0 right-0 border-t border-dashed border-amber-400/60"
            style={{ top: `${100 - (avg / niceMax) * 100}%` }}
            title={`Avg ${fmtDuration(avg)}`}
          >
            <span className="absolute -top-3.5 right-1 text-2xs text-amber-400 tabular bg-ink-900 px-1">
              avg {Math.round(avg)}m
            </span>
          </div>

          {/* Bars only — each column fills the chart vertically, bar grows
              from the bottom to its scaled height. All ranges produce
              ≤6 bars, so a comfortable gap and per-bar value labels
              stay readable. */}
          <div className="absolute inset-0 flex items-end px-1 gap-2">
            {bars.map((b) => {
              const h = b.lunch_min != null ? (b.lunch_min / niceMax) * 100 : 0;
              const showValue = b.lunch_min != null;
              return (
                <div key={b.key} className="flex-1 relative h-full flex items-end">
                  {showValue && (
                    <div className="absolute -top-4 left-0 right-0 text-center text-2xs text-ink-200 tabular">
                      {Math.round(b.lunch_min!)}
                    </div>
                  )}
                  <div
                    className="w-full"
                    style={{
                      height: `${h}%`,
                      minHeight: b.lunch_min != null ? 2 : 0,
                      backgroundColor: b.isToday ? "#f5a623" : "#b86d07",
                    }}
                    title={b.tooltip}
                  />
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* X-axis labels. Rendered OUTSIDE the chart box so they don't
          push the bar tops down relative to the axis. The left padding
          (w-8 + gap-2 = ~40px) matches the y-axis column so columns line
          up with the bars above.

          Month range: each label is anchored at the top-center of its
          column, then rotated -45° around its top-right corner. The
          translateX(-50%) puts the label's right edge on the column
          center BEFORE the rotation pivots around that same point —
          so the result is a label whose right end touches the column
          line and the rest of the text trails down-and-to-the-left
          at 45°. Standard tilted-axis-label convention. Other ranges
          (Week, 6m) keep the horizontal layout. */}
      <div className={`flex gap-2 mt-1 ${range === "month" ? "mb-8" : ""}`}>
        <div className="w-8" />
        <div className="flex-1 flex gap-2 px-1">
          {bars.map((b) => (
            <div
              key={b.key}
              className={
                "flex-1 text-2xs tabular " +
                (range === "month"
                  ? "relative h-3 overflow-visible"
                  : "text-center") +
                " " +
                (b.isToday ? "text-amber-400" : "text-ink-400")
              }
            >
              {range === "month" ? (
                // Geometry: anchor the span at left-1/2 of the column
                // (its left edge sits ON the column center line).
                // translateX(-100%) shifts the span left by its full
                // width, so the RIGHT edge of the span lands on the
                // column center. transform-origin: top right then pivots
                // the rotation around that same point — the column
                // center — so the rotated text trails down-and-to-the-
                // left at 45°. Each label's right end touches its
                // column line; the text reads upward-toward-the-right.
                <span
                  className="absolute left-1/2 top-0 whitespace-nowrap"
                  style={{
                    transform: "translateX(-100%) rotate(-45deg)",
                    transformOrigin: "top right",
                  }}
                >
                  {b.label}
                </span>
              ) : (
                b.label
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-2xs text-ink-300">
        <span className="inline-flex items-center gap-1.5">
          <span className="w-2 h-2 bg-amber-600" />
          <span>Lunch (min)</span>
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="w-2 h-2 bg-amber-400" />
          <span>{range === "week" ? "Today" : range === "month" ? "This week" : "This month"}</span>
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="w-4 border-t border-dashed border-amber-400/60" />
          <span>Average</span>
        </span>
      </div>
    </div>
  );
}

function BreaksList({ absences }: { absences: Absence[] }) {
  if (absences.length === 0) {
    return <div className="px-4 py-6 text-ink-400 text-sm">No breaks logged today.</div>;
  }
  const sorted = [...absences].sort((a, b) => a.start.localeCompare(b.start));
  return (
    <div>
      <div className="px-4 py-2 flex items-center gap-4 text-2xs uppercase tracking-[0.16em] text-ink-400 border-b border-ink-700 bg-ink-850">
        <span className="w-32">When</span>
        <span className="w-16">Duration</span>
        <span>Category</span>
      </div>
      <div className="divide-y divide-ink-800">
        {sorted.map((a, i) => (
          <div key={i} className="px-4 py-2.5 flex items-center gap-4 text-sm">
            <span className="font-mono text-ink-200 tabular w-32">
              {fmtClock(a.start)}<span className="text-ink-500"> → </span>{fmtClock(a.end)}
            </span>
            <span className="font-mono text-ink-100 tabular w-16">{fmtDuration(a.duration_min)}</span>
            <CategoryBadge category={a.category} />
          </div>
        ))}
      </div>
    </div>
  );
}

export default function App() {
  const [heatmapRange, setHeatmapRange] = useState<HeatmapRange>("year");
  const heatmapCfg = HEATMAP_RANGES.find((r) => r.value === heatmapRange)!;
  const [lunchRange, setLunchRange] = useState<LunchRange>("week");
  const lunchCfg = LUNCH_RANGES.find((r) => r.value === lunchRange)!;
  const pinControls = usePinControls();

  // The heatmap and the lunch chart both consume `/productivity`. Fetch
  // ONCE with the larger window so neither ends up data-starved when the
  // user changes a range. The endpoint clamps days to 365 internally, so
  // the worst case is two consumers fighting over a year of data.
  const productivityDays = Math.max(heatmapCfg.days, lunchCfg.days);

  const summary = useFetch<Summary>(`${API}/summary`, POLL_MS);
  const timeline = useFetch<TimelineResp>(`${API}/timeline`, POLL_MS);
  const productivity = useFetch<ProductivityDay[]>(`${API}/productivity?days=${productivityDays}`, POLL_MS);

  const today = summary?.date ? new Date(summary.date + "T00:00:00") : new Date();
  const dateLabel = today.toLocaleDateString([], { weekday: "long", month: "short", day: "numeric" });
  const clock = useClock();
  // Live clock in the header — 12-hour with seconds, lowercase a/p suffix.
  const ch = clock.getHours();
  const cm = clock.getMinutes();
  const cs = clock.getSeconds();
  const csuf = ch < 12 ? "a" : "p";
  const ch12 = ch === 0 ? 12 : ch > 12 ? ch - 12 : ch;
  const clockLabel = `${ch12}:${cm.toString().padStart(2, "0")}:${cs.toString().padStart(2, "0")}${csuf}`;

  return (
    <div className="min-h-screen text-ink-100 font-sans">
      <header className="border-b border-ink-700 bg-ink-950">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-baseline justify-between">
          <div className="flex items-baseline gap-4">
            <h1 className="text-amber-400 font-semibold tracking-wide text-lg">DESK WATCHER</h1>
            <span className="text-ink-300 text-sm">{dateLabel}</span>
          </div>
          <span className="font-mono text-ink-200 tabular text-sm">{clockLabel}</span>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-6 space-y-6">
        {/* Metric strip — user-pinnable tiles from the metric catalog.
            Default set matches the v0.x five tiles for migrating users.
            "customize pins" is rendered as plain text above the rightmost
            tile (no panel header, no chip) so it reads as an offer, not
            a control. */}
        <div>
          <div className="flex justify-end mb-1.5">
            <button
              type="button"
              onClick={pinControls.openPicker}
              className="text-2xs lowercase text-ink-400 hover:text-amber-400 transition-colors"
            >
              customize pins
            </button>
          </div>
          <section className="border border-ink-700 bg-ink-900">
            <TileGrid inputs={{ summary, timeline, productivity }} controls={pinControls} />
          </section>
        </div>

        {/* Timeline */}
        <Panel title="Today" right={timeline?.date} collapsibleId="timeline">
          <DayTimeline data={timeline} />
        </Panel>

        {/* Two-column row: heatmap (2/3) + lunch chart (1/3) side by side. */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <Panel
            title="Productivity"
            right={
              <div className="inline-flex border border-ink-700">
                {HEATMAP_RANGES.map((r) => {
                  const active = r.value === heatmapRange;
                  return (
                    <button
                      key={r.value}
                      type="button"
                      onClick={() => setHeatmapRange(r.value)}
                      className={
                        "px-2 py-0.5 text-2xs uppercase tracking-[0.16em] tabular border-r border-ink-700 last:border-r-0 transition-colors " +
                        (active
                          ? "bg-amber-600 text-ink-950"
                          : "text-ink-300 hover:text-ink-100 hover:bg-ink-800")
                      }
                    >
                      {r.label}
                    </button>
                  );
                })}
              </div>
            }
            className="lg:col-span-2"
            collapsibleId="productivity"
          >
            <ProductivityHeatmap data={productivity} range={heatmapRange} />
          </Panel>

          <Panel
            title="Lunch by day"
            right={
              <div className="inline-flex border border-ink-700">
                {LUNCH_RANGES.map((r) => {
                  const active = r.value === lunchRange;
                  return (
                    <button
                      key={r.value}
                      type="button"
                      onClick={() => setLunchRange(r.value)}
                      className={
                        "px-2 py-0.5 text-2xs uppercase tracking-[0.16em] tabular border-r border-ink-700 last:border-r-0 transition-colors " +
                        (active
                          ? "bg-amber-600 text-ink-950"
                          : "text-ink-300 hover:text-ink-100 hover:bg-ink-800")
                      }
                    >
                      {r.label}
                    </button>
                  );
                })}
              </div>
            }
            collapsibleId="lunch"
          >
            <LunchChart data={productivity} range={lunchRange} />
          </Panel>
        </div>

        {/* Breaks list */}
        <Panel
          title="Breaks today"
          right={summary ? `${summary.break_count} total` : ""}
          collapsibleId="breaks"
        >
          <BreaksList absences={summary?.absences ?? []} />
        </Panel>


      </main>

      {/* Pin picker modal — rendered at the App root so it overlays
          the entire dashboard, not just a single panel. */}
      <PinPicker controls={pinControls} />
    </div>
  );
}
