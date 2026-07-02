/**
 * Pure transforms that apply the user's refutations to freshly-fetched
 * API data. Every downstream consumer (top-bar tiles, timeline, breaks
 * list, heatmap, focus sparkline) reads from these transformed values
 * so refutations propagate everywhere without special-casing.
 *
 * Refutations are scoped to a single date on the read side (see
 * useRefutations). These transforms trust the scoping and only look
 * at the `start` key to identify absences.
 */
import type { Refutation } from "./hooks/useRefutations";
import type {
  ProductivityDay,
  Segment,
  Summary,
  TimelineResp,
} from "./types";

/**
 * Rebuild a Summary as if the refuted absences never happened.
 *
 * - Filter refuted rows out of `absences`.
 * - Decrement `break_count` and `long_break_count` by the number dropped.
 *   (Short breaks and lunch are not refutable in the current UI, but the
 *   filter is category-agnostic so future changes don't miss anything.)
 * - Recompute `avg_break_duration_min` as the mean of the remaining
 *   short_break | long_break durations. The `absences` array is the
 *   authoritative source for this — we can't derive it from the
 *   previous average.
 */
export function applySummaryRefutations(
  summary: Summary | null,
  refutations: Refutation[]
): Summary | null {
  if (!summary) return summary;
  if (refutations.length === 0) return summary;

  const refutedStarts = new Set(refutations.map((r) => r.start));
  const nextAbsences = summary.absences.filter((a) => !refutedStarts.has(a.start));

  let droppedShort = 0;
  let droppedLong = 0;
  for (const a of summary.absences) {
    if (!refutedStarts.has(a.start)) continue;
    if (a.category === "short_break") droppedShort++;
    else if (a.category === "long_break") droppedLong++;
  }

  const realBreaks = nextAbsences.filter(
    (a) => a.category === "short_break" || a.category === "long_break"
  );
  const avgBreakDurationMin =
    realBreaks.length > 0
      ? realBreaks.reduce((s, a) => s + a.duration_min, 0) / realBreaks.length
      : 0;

  return {
    ...summary,
    absences: nextAbsences,
    short_break_count: Math.max(0, summary.short_break_count - droppedShort),
    long_break_count: Math.max(0, summary.long_break_count - droppedLong),
    break_count: Math.max(0, summary.break_count - droppedShort - droppedLong),
    avg_break_duration_min: Math.round(avgBreakDurationMin * 10) / 10,
  };
}

/**
 * Rewrite `away` segments that fall inside a refuted absence so they
 * render as productive at-desk time.
 *
 * Matching rule: overlap-inclusive. The /timeline endpoint's noise-
 * floor pass merges sub-60s away blips into their preceding segment,
 * so a single timeline `away` segment can be a superset of what
 * _classify_absences saw. Strict "inside" matching would miss those
 * merged supersets. Any overlap → the whole timeline segment is
 * treated as at-desk (which is the visually correct outcome: the
 * user said "I was working then").
 *
 * Adjacent-same-activity segments are NOT re-merged. The renderer
 * handles them fine and re-merging would fight with sip pip / notch
 * rendering that keys off segment boundaries.
 */
export function applyTimelineRefutations(
  timeline: TimelineResp | null,
  refutations: Refutation[]
): TimelineResp | null {
  if (!timeline) return timeline;
  if (refutations.length === 0) return timeline;

  // Precompute epoch bounds for each refutation for O(N*R) overlap check.
  const bounds = refutations.map((r) => ({
    start: new Date(r.start).getTime(),
    end: new Date(r.end).getTime(),
  }));

  const segments: Segment[] = timeline.segments.map((s) => {
    if (s.activity !== "away") return s;
    const segStart = new Date(s.start).getTime();
    const segEnd = new Date(s.end).getTime();
    const overlaps = bounds.some((b) => segStart < b.end && segEnd > b.start);
    if (!overlaps) return s;
    return { ...s, activity: "at_desk" };
  });

  return { ...timeline, segments };
}

/**
 * Adjust today's ProductivityDay entry: move refuted duration from
 * `break_total_min` into `at_desk_min`, and decrement the long-break
 * counts. All other days pass through unchanged — refutations are a
 * "this happened today" acknowledgement, not a retroactive edit.
 */
export function applyTodayProductivityRefutations(
  productivity: ProductivityDay[] | null,
  refutations: Refutation[],
  todayDate: string | undefined
): ProductivityDay[] | null {
  if (!productivity) return productivity;
  if (refutations.length === 0 || !todayDate) return productivity;

  const refutedTotalMin = refutations.reduce((s, r) => s + r.duration_min, 0);
  const refutedCount = refutations.length;

  return productivity.map((d) => {
    if (d.date !== todayDate) return d;
    const nextBreakTotal = Math.max(0, d.break_total_min - refutedTotalMin);
    const nextLong = Math.max(0, d.long_break_count - refutedCount);
    const nextTotal = Math.max(0, d.break_count - refutedCount);
    return {
      ...d,
      at_desk_min: Math.round((d.at_desk_min + refutedTotalMin) * 10) / 10,
      break_total_min: Math.round(nextBreakTotal * 10) / 10,
      long_break_count: nextLong,
      break_count: nextTotal,
    };
  });
}
