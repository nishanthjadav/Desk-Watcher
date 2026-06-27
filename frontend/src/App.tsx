import { useEffect, useMemo, useState } from "react";

const API = "http://localhost:8000";
const POLL_MS = 30_000;

type Category = "bathroom" | "short_break" | "long_break" | "lunch";

interface Absence {
  start: string;
  end: string;
  duration_min: number;
  category: Category;
}

interface Lunch {
  start: string;
  end: string;
  duration_min: number;
}

interface Summary {
  date: string;
  sip_count: number;
  bathroom_count: number;
  short_break_count: number;
  long_break_count: number;
  break_count: number;
  avg_break_duration_min: number;
  lunch: Lunch | null;
  absences: Absence[];
  total_events: number;
}

interface WeekDay {
  date: string;
  sip_count: number;
  bathroom_count: number;
  short_break_count: number;
  long_break_count: number;
  break_count: number;
  lunch_duration_min: number | null;
}

interface Segment {
  activity: string;
  start: string;
  end: string;
  duration_s: number;
}

interface TimelineResp {
  date: string;
  segments: Segment[];
}

interface HourCell {
  hour: number;
  at_desk_s: number;
  away_s: number;
  sip_count: number;
}

interface HeatmapDay {
  date: string;
  hours: HourCell[];
}

interface ProductivityDay {
  date: string;
  break_count: number;
  bathroom_count: number;
  short_break_count: number;
  long_break_count: number;
  lunch_duration_min: number | null;
  at_desk_min: number;
}

const ACTIVITY_COLOR: Record<string, string> = {
  at_desk: "#e08a0c",
  sipping: "#f7c04a",
  stretching: "#8a5106",
  away: "#33302a",
  unknown: "#26231f",
};

const CATEGORY_LABEL: Record<Category, string> = {
  bathroom: "Bathroom",
  short_break: "Short break",
  long_break: "Long break",
  lunch: "Lunch",
};

const CATEGORY_COLOR: Record<Category, string> = {
  bathroom: "#6b655d",
  short_break: "#b5afa4",
  long_break: "#f5a623",
  lunch: "#e08a0c",
};

function fmtClock(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}

function fmtHour12(h: number): string {
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

function Panel({ title, right, children, className = "" }: {
  title?: string; right?: React.ReactNode; children: React.ReactNode; className?: string;
}) {
  return (
    <section className={`border border-ink-700 bg-ink-900 ${className}`}>
      {title && (
        <header className="flex items-center justify-between px-4 py-2 border-b border-ink-700">
          <h2 className="text-2xs uppercase tracking-[0.18em] text-ink-300 font-medium">{title}</h2>
          {right && <div className="text-2xs text-ink-400 tabular">{right}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

function Metric({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="px-4 py-3 border-r border-ink-700 last:border-r-0 flex-1">
      <div className="text-2xs uppercase tracking-[0.16em] text-ink-400">{label}</div>
      <div className="mt-1 font-mono text-2xl text-ink-100 tabular">{value}</div>
      {sub && <div className="text-2xs text-ink-400 mt-0.5">{sub}</div>}
    </div>
  );
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
  const totals: Record<string, number> = { at_desk: 0, away: 0, sipping: 0, stretching: 0 };
  for (const s of data.segments) {
    totals[s.activity] = (totals[s.activity] ?? 0) + s.duration_s;
  }

  const todayIso = new Date().toISOString().slice(0, 10);
  const isToday = data.date === todayIso;
  const nowMs = Date.now();
  const nowPct = isToday && nowMs >= windowStart && nowMs <= windowEnd ? msToPct(nowMs) : null;

  return (
    <div className="px-4 py-4">
      <div className="flex items-baseline justify-between mb-2 text-2xs text-ink-400">
        <span>
          {fmtHour12(startHour)} <span className="text-ink-500">→</span> {fmtHour12(endHour)}
        </span>
        <span className="tabular">
          <span className="text-ink-300">{fmtDuration(totals.at_desk / 60)}</span> at desk
          <span className="text-ink-500 mx-2">·</span>
          <span className="text-ink-300">{fmtDuration(totals.away / 60)}</span> away
        </span>
      </div>

      <div className="relative h-8 bg-ink-850 border border-ink-700 overflow-hidden">
        {data.segments.map((s, i) => {
          const start = new Date(s.start).getTime();
          const end = new Date(s.end).getTime();
          // Clip the segment to the visible window so nothing renders past 4p.
          const clippedStart = Math.max(start, windowStart);
          const clippedEnd = Math.min(end, windowEnd);
          if (clippedEnd <= clippedStart) return null;
          const left = msToPct(clippedStart);
          const width = msToPct(clippedEnd) - left;
          const color = ACTIVITY_COLOR[s.activity] ?? ACTIVITY_COLOR.unknown;
          return (
            <div
              key={i}
              className="absolute top-0 bottom-0"
              style={{ left: `${left}%`, width: `${Math.max(width, 0.08)}%`, backgroundColor: color }}
              title={`${s.activity} · ${fmtClock(s.start)}–${fmtClock(s.end)} · ${fmtDuration(s.duration_s / 60)}`}
            />
          );
        })}
        {nowPct != null && (
          <div
            className="absolute top-0 bottom-0 w-px bg-amber-200"
            style={{ left: `${nowPct}%` }}
            title="Now"
          />
        )}
      </div>

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
      <div className="text-center text-2xs text-ink-500 uppercase tracking-[0.18em] mt-2">
        Time of day
      </div>

      <div className="flex flex-wrap gap-x-4 gap-y-1 mt-3 text-2xs text-ink-300">
        {(["at_desk", "sipping", "stretching", "away"] as const).map((a) => (
          <span key={a} className="inline-flex items-center gap-1.5">
            <span className="w-2 h-2" style={{ backgroundColor: ACTIVITY_COLOR[a] }} />
            <span className="capitalize">{a.replace("_", " ")}</span>
            <span className="text-ink-500 tabular">{fmtDuration((totals[a] ?? 0) / 60)}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

function ProductivityHeatmap({ data }: { data: ProductivityDay[] | null }) {
  if (!data) return <div className="px-4 py-6 text-ink-400 text-sm">Loading…</div>;

  // Filter to "tracked" days only (>= 30 min of at-desk time) for the average
  // and the legend scale. Untracked days render as a neutral "no data" cell.
  const tracked = data.filter((d) => d.at_desk_min >= 30);
  if (tracked.length === 0) {
    return <div className="px-4 py-6 text-ink-400 text-sm">Not enough data yet — run the watcher for a full workday.</div>;
  }

  const counts = tracked.map((d) => d.break_count).sort((a, b) => a - b);
  const minCount = counts[0];
  const maxCount = counts[counts.length - 1];
  const avgCount = tracked.reduce((s, d) => s + d.break_count, 0) / tracked.length;

  // Five buckets: 0 = fewest breaks (most focused / brightest amber),
  // 4 = most breaks (darkest). Single hue ramp.
  const ramp = ["#f5a623", "#b86d07", "#5c3604", "#3a2202", "#1c1a17"];
  const noData = "#0a0908";

  const bucket = (n: number): number => {
    if (maxCount === minCount) return 0;
    const t = (n - minCount) / (maxCount - minCount);
    return Math.min(ramp.length - 1, Math.floor(t * ramp.length));
  };

  // Build a calendar-year grid: Jan 1 → Dec 31 of the current year, so
  // January is always on the far left and December on the far right.
  const byDate: Record<string, ProductivityDay> = {};
  for (const d of data) byDate[d.date] = d;

  const localIso = (d: Date) => {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  };

  const year = new Date().getFullYear();
  const yearStart = new Date(year, 0, 1);
  const yearEnd = new Date(year, 11, 31);

  // Align grid start to the Sunday on or before Jan 1 (so each column is
  // a full Sun..Sat week, with leading non-year days rendered as blanks).
  const gridStart = new Date(yearStart);
  gridStart.setDate(gridStart.getDate() - gridStart.getDay());

  const weeks: { date: string | null; day: ProductivityDay | null }[][] = [];
  const cursor = new Date(gridStart);
  while (cursor <= yearEnd) {
    const week: { date: string | null; day: ProductivityDay | null }[] = [];
    for (let dow = 0; dow < 7; dow++) {
      const inYear = cursor >= yearStart && cursor <= yearEnd;
      const iso = inYear ? localIso(cursor) : null;
      const day = iso ? (byDate[iso] ?? null) : null;
      week.push({ date: iso, day });
      cursor.setDate(cursor.getDate() + 1);
    }
    weeks.push(week);
  }

  // Month labels: anchor each month to the column containing its 1st day.
  const monthLabels: { col: number; label: string }[] = [];
  for (let m = 0; m < 12; m++) {
    const firstOfMonth = new Date(year, m, 1);
    const firstIso = localIso(firstOfMonth);
    const col = weeks.findIndex((w) => w.some((c) => c.date === firstIso));
    if (col === -1) continue;
    monthLabels.push({
      col,
      label: firstOfMonth.toLocaleDateString([], { month: "short" }),
    });
  }

  const dowLabels = ["", "Mon", "", "Wed", "", "Fri", ""];

  return (
    <div className="px-4 py-4">


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
            so labels align with their columns no matter the panel width. */}
        <div
          className="flex-1 grid gap-[2px]"
          style={{ gridTemplateColumns: `repeat(${weeks.length}, minmax(0, 1fr))` }}
        >
          {/* Month strip spans all columns */}
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
                const b = bucket(cell.day.break_count);
                return (
                  <div
                    key={di}
                    className={common}
                    style={{ backgroundColor: ramp[b] }}
                    title={`${cell.date} · ${cell.day.break_count} break${cell.day.break_count === 1 ? "" : "s"} · ${fmtDuration(cell.day.at_desk_min)} at desk`}
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
          <span>Fewer breaks</span>
          {ramp.map((c) => (
            <span key={c} className="w-3 h-3" style={{ backgroundColor: c }} />
          ))}
          <span>More breaks</span>
        </span>
        <span className="text-ink-500">
          range {minCount}–{maxCount} · avg {avgCount.toFixed(1)}/day
        </span>
        <span className="inline-flex items-center gap-2">
          <span className="w-3 h-3 border border-ink-800" style={{ backgroundColor: noData }} />
          <span>no data</span>
        </span>
      </div>
    </div>
  );
}

function LunchChart({ data }: { data: WeekDay[] | null }) {
  if (!data || data.length === 0) {
    return <div className="px-4 py-6 text-ink-400 text-sm">No weekly data.</div>;
  }

  const todayIso = new Date().toISOString().slice(0, 10);
  const durations = data.map((d) => d.lunch_duration_min).filter((v): v is number => v != null);
  const hasAny = durations.length > 0;
  const avg = hasAny ? durations.reduce((s, v) => s + v, 0) / durations.length : 0;
  const max = Math.max(60, ...durations); // give the axis at least a 60-min ceiling
  const niceMax = Math.ceil(max / 15) * 15;
  const ticks = [0, niceMax / 2, niceMax];

  return (
    <div className="px-4 py-4">
      <div className="text-2xs text-ink-300 mb-3">
        Lunch duration per day
        <span className="text-ink-500 ml-2">
          · {hasAny ? `avg ${fmtDuration(avg)} over ${durations.length}d` : "no lunches detected yet"}
        </span>
      </div>

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

        {/* Bars + gridlines + average line */}
        <div className="relative flex-1 border-l border-b border-ink-700">
          {ticks.slice(1).map((t) => (
            <div
              key={t}
              className="absolute left-0 right-0 border-t border-ink-800"
              style={{ top: `${100 - (t / niceMax) * 100}%` }}
            />
          ))}

          {hasAny && (
            <div
              className="absolute left-0 right-0 border-t border-dashed border-amber-400/60"
              style={{ top: `${100 - (avg / niceMax) * 100}%` }}
              title={`Avg ${fmtDuration(avg)}`}
            >
              <span className="absolute -top-3.5 right-1 text-2xs text-amber-400 tabular bg-ink-900 px-1">
                avg {Math.round(avg)}m
              </span>
            </div>
          )}

          <div className="absolute inset-0 flex items-end gap-2 px-1">
            {data.map((d) => {
              const v = d.lunch_duration_min;
              const isToday = d.date === todayIso;
              const h = v != null ? (v / niceMax) * 100 : 0;
              return (
                <div key={d.date} className="flex-1 flex flex-col items-center justify-end h-full">
                  <div className="text-2xs text-ink-200 tabular mb-0.5">
                    {v != null ? Math.round(v) : ""}
                  </div>
                  <div
                    className="w-full"
                    style={{
                      height: v != null ? `${h}%` : 0,
                      minHeight: v != null ? 2 : 0,
                      backgroundColor: isToday ? "#f5a623" : "#b86d07",
                    }}
                    title={
                      v != null
                        ? `${d.date} · lunch ${fmtDuration(v)}`
                        : `${d.date} · no lunch detected`
                    }
                  />
                  <div className={`mt-1 text-2xs tabular ${isToday ? "text-amber-400" : "text-ink-400"}`}>
                    {new Date(d.date + "T00:00:00").toLocaleDateString([], { weekday: "short" })}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-2xs text-ink-300">
        <span className="inline-flex items-center gap-1.5">
          <span className="w-2 h-2 bg-amber-600" />
          <span>Lunch (min)</span>
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="w-2 h-2 bg-amber-400" />
          <span>Today</span>
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
  const summary = useFetch<Summary>(`${API}/summary`, POLL_MS);
  const weekly = useFetch<WeekDay[]>(`${API}/weekly`, POLL_MS);
  const timeline = useFetch<TimelineResp>(`${API}/timeline`, POLL_MS);
  const productivity = useFetch<ProductivityDay[]>(`${API}/productivity?days=365`, POLL_MS);

  const atDeskHours = useMemo(() => {
    if (!timeline) return null;
    const s = timeline.segments
      .filter((seg) => seg.activity === "at_desk" || seg.activity === "sipping" || seg.activity === "stretching")
      .reduce((acc, seg) => acc + seg.duration_s, 0);
    return s / 3600;
  }, [timeline]);

  const today = summary?.date ? new Date(summary.date + "T00:00:00") : new Date();
  const dateLabel = today.toLocaleDateString([], { weekday: "long", month: "short", day: "numeric" });
  const clock = useClock();
  const clockLabel = clock.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });

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
        {/* Metric strip */}
        <Panel>
          <div className="flex">
            <Metric
              label="At desk"
              value={atDeskHours != null ? fmtDuration(atDeskHours * 60) : "—"}
              sub="active today"
            />
            <Metric
              label="Sips"
              value={String(summary?.sip_count ?? "—")}
              sub="hydration"
            />
            <Metric
              label="Bathroom"
              value={String(summary?.bathroom_count ?? "—")}
              sub="< 6 min"
            />
            <Metric
              label="Short breaks"
              value={String(summary?.short_break_count ?? "—")}
              sub={summary ? `avg ${fmtDuration(summary.avg_break_duration_min)}` : "—"}
            />
            <Metric
              label="Lunch"
              value={summary?.lunch ? fmtDuration(summary.lunch.duration_min) : "—"}
              sub={summary?.lunch ? `${fmtClock(summary.lunch.start)}–${fmtClock(summary.lunch.end)}` : "not yet"}
            />
          </div>
        </Panel>

        {/* Timeline */}
        <Panel title="Today" right={timeline?.date}>
          <DayTimeline data={timeline} />
        </Panel>

        {/* Two-column row */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <Panel title="Productivity" right="last 12 months" className="lg:col-span-2">
            <ProductivityHeatmap data={productivity} />
          </Panel>
          <Panel title="Lunch by day" right="last 7 days">
            <LunchChart data={weekly} />
          </Panel>
        </div>

        {/* Breaks list */}
        <Panel title="Breaks today" right={summary ? `${summary.break_count} total` : ""}>
          <BreaksList absences={summary?.absences ?? []} />
        </Panel>


      </main>
    </div>
  );
}
