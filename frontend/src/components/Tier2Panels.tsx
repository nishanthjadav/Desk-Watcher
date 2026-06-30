/**
 * WPM-over-day chart and Yawn-energy heatmap.
 *
 * Both are stub-data Tier-2 panels right now. They render with
 * deterministic synthetic data so the dashboard layout is complete and
 * styled, and so the eventual pipeline wiring is a 5-line change (swap
 * the data source).
 *
 * To plug in real data:
 *   - WpmChart: replace `useStubWpm()` with a real fetch hook against
 *     /wpm-today or similar, returning `{ minute: number; wpm: number }[]`.
 *   - YawnHeatmap: replace `useStubYawns()` with a real fetch returning
 *     `{ hour: number; yawn_count: number; date: string }[]` for the
 *     last 14 days.
 */
import { useMemo } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

// ── WPM over the day ───────────────────────────────────────────────────────

export type WpmRange = "today" | "week" | "month";

export const WPM_RANGES: { value: WpmRange; label: string }[] = [
  { value: "today", label: "Today" },
  { value: "week", label: "Week" },
  { value: "month", label: "Month" },
];

interface WpmPoint {
  // Horizontal axis value:
  //   - today: minutes since midnight (8 * 60 .. 16 * 60)
  //   - week:  day index 0..6 (Mon..Sun)
  //   - month: day index 0..29
  x: number;
  // Human-readable tick label for that x value.
  tick: string;
  // WPM. For week/month this is the day's average; for today it's a
  // single 5-minute snapshot.
  wpm: number;
}

// Deterministic synthetic WPM for one workday (8a–4p). Reads as a
// plausible day: low at first coffee, peak mid-morning, dip at lunch,
// rebound, fade in the afternoon. No randomness — same shape every time.
function buildToday(): WpmPoint[] {
  const start = 8 * 60;
  const end = 16 * 60;
  const points: WpmPoint[] = [];
  for (let m = start; m <= end; m += 5) {
    const hour = m / 60;
    let wpm = 0;
    if (hour < 10) wpm = 30 + (hour - 8) * 25;
    else if (hour < 12) wpm = 80 - (hour - 10) * 2;
    else if (hour < 13) wpm = 75 - (hour - 12) * 70;
    else if (hour < 15) wpm = 5 + (hour - 13) * 35;
    else wpm = 75 - (hour - 15) * 20;
    wpm += Math.sin(m * 0.07) * 4;
    // Major-hour ticks only.
    const onTheHour = m % 60 === 0;
    const h = Math.floor(m / 60);
    const suffix = h < 12 ? "a" : "p";
    const h12 = h === 0 ? 12 : h > 12 ? h - 12 : h;
    points.push({
      x: m,
      tick: onTheHour ? `${h12}${suffix}` : "",
      wpm: Math.max(0, Math.round(wpm)),
    });
  }
  return points;
}

// Deterministic synthetic week: Mon..Sun, daily averages.
function buildWeek(): WpmPoint[] {
  const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  // Stronger Mon-Wed, dip Thu, recovery Fri, weekends low.
  const base = [62, 71, 74, 58, 65, 28, 22];
  return days.map((d, i) => ({ x: i, tick: d, wpm: base[i] }));
}

// Deterministic synthetic month: 30 days of daily averages.
function buildMonth(): WpmPoint[] {
  const out: WpmPoint[] = [];
  for (let i = 0; i < 30; i++) {
    // Weekly rhythm: weekdays higher, weekends lower (i % 7).
    const dow = i % 7;
    const weekend = dow === 5 || dow === 6;
    const base = weekend ? 25 : 60;
    // Slow upward trend across the month + small per-day variation.
    const trend = i * 0.4;
    const wiggle = Math.sin(i * 1.13) * 8;
    const wpm = Math.max(0, Math.round(base + trend + wiggle));
    // Show every 5th day's label
    const tick = i % 5 === 0 ? `d${i + 1}` : "";
    out.push({ x: i, tick, wpm });
  }
  return out;
}

function useStubWpm(range: WpmRange): WpmPoint[] {
  return useMemo(() => {
    if (range === "today") return buildToday();
    if (range === "week") return buildWeek();
    return buildMonth();
  }, [range]);
}

export function WpmChart({ range }: { range: WpmRange }) {
  const data = useStubWpm(range);
  const avg = useMemo(
    () => Math.round(data.reduce((s, p) => s + p.wpm, 0) / data.length),
    [data]
  );
  const peak = useMemo(() => Math.max(...data.map((p) => p.wpm)), [data]);

  const rangeWord =
    range === "today" ? "by time of day" : range === "week" ? "by day of week" : "by day";

  return (
    <div className="px-4 py-4">
      <div className="text-2xs text-ink-300 mb-3">
        Typing pace {rangeWord}
        <span className="text-ink-500 ml-2">
          · avg {avg} wpm · peak {peak} wpm
        </span>
        <span className="text-ink-600 ml-3 italic">stub data — pipeline pending</span>
      </div>
      <div className="h-40">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
            <defs>
              <linearGradient id="wpm-fill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#f5a623" stopOpacity={0.35} />
                <stop offset="100%" stopColor="#f5a623" stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="#26231f" strokeDasharray="2 4" vertical={false} />
            <XAxis
              dataKey="x"
              type="number"
              domain={["dataMin", "dataMax"]}
              tickFormatter={(v: number) => {
                const p = data.find((d) => d.x === v);
                return p?.tick ?? "";
              }}
              stroke="#7a7468"
              tick={{ fontSize: 10, fill: "#a8a194" }}
              tickLine={false}
              axisLine={{ stroke: "#3a3631" }}
            />
            <YAxis
              stroke="#7a7468"
              tick={{ fontSize: 10, fill: "#a8a194" }}
              tickLine={false}
              axisLine={{ stroke: "#3a3631" }}
              width={42}
            />
            <Tooltip
              contentStyle={{
                background: "#1a1815",
                border: "1px solid #3a3631",
                fontSize: 12,
                color: "#f4f0e8",
              }}
              labelFormatter={(v) => {
                const p = data.find((d) => d.x === v);
                return p?.tick || (range === "today" ? `${Math.floor((v as number) / 60)}:${String((v as number) % 60).padStart(2, "0")}` : `d${(v as number) + 1}`);
              }}
              formatter={(v: number) => [`${v} wpm`, "WPM"]}
            />
            <Area
              type="monotone"
              dataKey="wpm"
              stroke="#f5a623"
              strokeWidth={1.5}
              fill="url(#wpm-fill)"
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// ── Yawn heatmap — mirrors the Productivity heatmap layout ──────────────
//
// Deliberate visual parity with ProductivityHeatmap: same calendar grid,
// same Year/6m/Month range buttons, same legend shape, same color ramp.
// Users only need to learn ONE heatmap-reading mental model and every
// per-day metric they pin can be read at a glance. If the two diverged
// (e.g., hour-of-day on one, calendar on the other) every glance would
// require a brief re-orient.

export type YawnRange = "year" | "6m" | "month";

export const YAWN_RANGES: { value: YawnRange; label: string; days: number }[] = [
  { value: "month", label: "Month", days: 31 },
  { value: "6m", label: "6m", days: 26 * 7 },
  { value: "year", label: "Year", days: 365 },
];

interface YawnDay {
  date: string;       // YYYY-MM-DD local
  yawn_count: number; // total yawns that day
}

// Deterministic stub: ~365 days of plausible yawn counts. Weekdays
// slightly more (work fatigue), weekends slightly less, gentle upward
// trend through the year, a Sin wave for variety. Same shape every render.
function useStubYawnDays(): YawnDay[] {
  return useMemo(() => {
    const out: YawnDay[] = [];
    const today = new Date();
    // Render the full year so the Year range has content; smaller ranges
    // just slice the tail.
    const startOfYear = new Date(today.getFullYear(), 0, 1);
    const cursor = new Date(startOfYear);
    let i = 0;
    while (cursor <= today) {
      const dow = cursor.getDay();
      const weekend = dow === 0 || dow === 6;
      const base = weekend ? 2 : 6;
      // Slow upward trend day-of-year (people get more tired as the year
      // grinds on — totally arbitrary but reads as a real signal).
      const trend = i * 0.005;
      const wiggle = Math.sin(i * 0.31) * 2;
      const count = Math.max(0, Math.round(base + trend + wiggle));
      const y = cursor.getFullYear();
      const m = String(cursor.getMonth() + 1).padStart(2, "0");
      const d = String(cursor.getDate()).padStart(2, "0");
      out.push({ date: `${y}-${m}-${d}`, yawn_count: count });
      cursor.setDate(cursor.getDate() + 1);
      i++;
    }
    return out;
  }, []);
}

export function YawnHeatmap({ range }: { range: YawnRange }) {
  const data = useStubYawnDays();

  // Filter to "tracked" days (any yawns recorded). With stub data this
  // is every day, but mirrors the ProductivityHeatmap pattern so the
  // real-data swap-in is a single-line change.
  const tracked = data.filter((d) => d.yawn_count > 0);
  if (tracked.length === 0) {
    return (
      <div className="px-4 py-6 text-ink-400 text-sm">
        Not enough data yet — yawn detection pipeline pending.
      </div>
    );
  }

  const avg = tracked.reduce((s, d) => s + d.yawn_count, 0) / tracked.length;
  const min = Math.min(...tracked.map((d) => d.yawn_count));
  const max = Math.max(...tracked.map((d) => d.yawn_count));

  // Five FIXED buckets keyed to yawn count. Brightest amber = MOST
  // yawns (lowest energy), darkest = fewest yawns (highest energy).
  // Note the direction: in the productivity heatmap, brighter = better;
  // in the yawn heatmap, brighter = more tired. We keep the SAME color
  // ramp so users don't have to learn a new palette, and rely on the
  // legend ("Fewer yawns" / "More yawns") to disambiguate direction.
  // 0 → brightest (most yawns), 4 → darkest (fewest yawns).
  const ramp = ["#f5a623", "#b86d07", "#5c3604", "#3a2202", "#1c1a17"];
  const COUNT_THRESHOLDS = [10, 7, 4, 2]; // descending
  const noData = "#0a0908";

  const bucket = (count: number): number => {
    for (let i = 0; i < COUNT_THRESHOLDS.length; i++) {
      if (count >= COUNT_THRESHOLDS[i]) return i;
    }
    return ramp.length - 1;
  };

  const byDate: Record<string, YawnDay> = {};
  for (const d of data) byDate[d.date] = d;

  const localIso = (d: Date) => {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  };

  // Same range-window logic as the productivity heatmap.
  const today = new Date();
  let rangeStart: Date;
  let rangeEnd: Date;
  let showMonthLabels = true;

  if (range === "year") {
    rangeStart = new Date(today.getFullYear(), 0, 1);
    rangeEnd = new Date(today.getFullYear(), 11, 31);
  } else if (range === "6m") {
    rangeEnd = new Date(today);
    rangeEnd.setDate(rangeEnd.getDate() + (6 - rangeEnd.getDay()));
    rangeStart = new Date(rangeEnd);
    rangeStart.setDate(rangeStart.getDate() - (26 * 7 - 1));
  } else {
    rangeStart = new Date(today.getFullYear(), today.getMonth(), 1);
    rangeEnd = new Date(today.getFullYear(), today.getMonth() + 1, 0);
    showMonthLabels = false;
  }

  const gridStart = new Date(rangeStart);
  gridStart.setDate(gridStart.getDate() - gridStart.getDay());

  const weeks: { date: string | null; day: YawnDay | null }[][] = [];
  const cursor = new Date(gridStart);
  while (cursor <= rangeEnd) {
    const week: { date: string | null; day: YawnDay | null }[] = [];
    for (let dow = 0; dow < 7; dow++) {
      const inRange = cursor >= rangeStart && cursor <= rangeEnd;
      const iso = inRange ? localIso(cursor) : null;
      const day = iso ? (byDate[iso] ?? null) : null;
      week.push({ date: iso, day });
      cursor.setDate(cursor.getDate() + 1);
    }
    weeks.push(week);
  }

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
    <div className="px-4 py-4 h-full flex flex-col justify-center">
      <div className="text-2xs text-ink-300 mb-3">
        Yawns per day
        <span className="text-ink-500 ml-2">
          · range {min}–{max} · avg {avg.toFixed(1)}/day
        </span>
        <span className="text-ink-600 ml-3 italic">stub data — pipeline pending</span>
      </div>

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

        {/* Grid: month strip on top, weeks × days below */}
        <div
          className="flex-1 grid gap-[2px]"
          style={{
            gridTemplateColumns: `repeat(${weeks.length}, minmax(0, 1fr))`,
            maxWidth: `${weeks.length * 22}px`,
          }}
        >
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
                if (!cell.day) {
                  return (
                    <div
                      key={di}
                      className={`${common} border border-ink-800`}
                      style={{ backgroundColor: noData }}
                      title={`${cell.date} · no data`}
                    />
                  );
                }
                const b = bucket(cell.day.yawn_count);
                return (
                  <div
                    key={di}
                    className={common}
                    style={{ backgroundColor: ramp[b] }}
                    title={`${cell.date} · ${cell.day.yawn_count} yawn${cell.day.yawn_count === 1 ? "" : "s"}`}
                  />
                );
              })}
            </div>
          ))}
        </div>
      </div>

      {/* Legend — mirrors the productivity heatmap. Direction inverted in
          labels: "Fewer yawns" on the dark end, "More yawns" on bright. */}
      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-2xs text-ink-400">
        <span className="inline-flex items-center gap-2">
          <span>More yawns</span>
          {ramp.map((c) => (
            <span key={c} className="w-3 h-3" style={{ backgroundColor: c }} />
          ))}
          <span>Fewer yawns</span>
        </span>
        <span className="text-ink-500">
          range {min}–{max} · avg {avg.toFixed(1)}
        </span>
        <span className="inline-flex items-center gap-2">
          <span className="w-3 h-3 border border-ink-800" style={{ backgroundColor: noData }} />
          <span>no data</span>
        </span>
        <span
          className="ml-auto underline decoration-dotted underline-offset-2 text-ink-500 cursor-help"
          title={
            "Yawn count per day. Brighter = more yawns (lower energy);\n" +
            "darker = fewer yawns (higher energy).\n\n" +
            "Color buckets:\n" +
            "  ≥ 10   brightest amber: very tired day\n" +
            "  ≥ 7    bright: notably tired\n" +
            "  ≥ 4    mid: moderate fatigue\n" +
            "  ≥ 2    dark: light fatigue\n" +
            "  < 2    darkest: high-energy day\n\n" +
            "Stub data shown until the yawn-detection pipeline is built.\n" +
            "Plan: add a yawn label key to collect_data.py, record a\n" +
            "session_004 with deliberate yawn examples, retrain the\n" +
            "classifier with yawn as a fifth class."
          }
        >
          how this is calculated
        </span>
      </div>
    </div>
  );
}
