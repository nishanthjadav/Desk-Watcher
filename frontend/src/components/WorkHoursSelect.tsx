/**
 * Two hour pickers for choosing start-of-day and end-of-day, rendered as
 * a compact "9a – 5p" control. Lives to the left of the date in the
 * "Today" panel header.
 *
 * We use a custom popup (not native `<select>`) for one reason: the
 * user wants the dropdown to show ~7 options at a time and scroll,
 * which native `<select>` doesn't reliably support cross-browser
 * (Firefox sizes by option count, Chrome sizes by viewport). A tiny
 * absolute-positioned listbox gives us hard control over MAX_VISIBLE.
 *
 * Reads/writes via the useWorkHours hook — this component just renders
 * the controls and forwards changes.
 */
import { useEffect, useRef, useState } from "react";
import type { WorkHours } from "../hooks/useWorkHours";

function fmtHour12(h: number): string {
  // Match the ruler in DayTimeline. Special-case the two 12s. Anything
  // reaching 24 is midnight tomorrow, which we render as "12a" (matches
  // "end of day" reading).
  if (h === 0 || h === 24) return "12a";
  if (h === 12) return "12p";
  return h < 12 ? `${h}a` : `${h - 12}p`;
}

// Height of one option row and the number of rows visible before the
// popup starts scrolling. 7 * ~24px = 168px of visible list. Any more
// options are reachable by scrolling.
const OPTION_HEIGHT_PX = 24;
const MAX_VISIBLE_OPTIONS = 7;

function HourSelect({
  value,
  options,
  onChange,
  ariaLabel,
}: {
  value: number;
  options: number[];
  onChange: (h: number) => void;
  ariaLabel: string;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  // Close on outside click. The popup renders inside the same root so
  // clicks inside stay open.
  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (!rootRef.current) return;
      if (!rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  // When opening, scroll the selected option into view so users start
  // near their current value instead of always seeing 12a at the top.
  useEffect(() => {
    if (!open || !listRef.current) return;
    const idx = options.indexOf(value);
    if (idx < 0) return;
    listRef.current.scrollTop = Math.max(0, (idx - 1) * OPTION_HEIGHT_PX);
  }, [open, value, options]);

  return (
    <div ref={rootRef} className="relative inline-block">
      <button
        type="button"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        className={
          "bg-ink-900 border border-ink-700 text-ink-200 text-xs font-mono tabular " +
          "px-1.5 py-0.5 hover:border-ink-600 focus:outline-none focus:border-amber-500 " +
          "transition-colors cursor-pointer"
        }
      >
        {fmtHour12(value)}
      </button>
      {open && (
        <ul
          ref={listRef}
          role="listbox"
          aria-label={ariaLabel}
          className={
            "thin-scroll absolute z-30 mt-1 right-0 bg-ink-900 border border-ink-700 " +
            "text-xs font-mono tabular shadow-lg overflow-y-auto"
          }
          style={{
            maxHeight: OPTION_HEIGHT_PX * MAX_VISIBLE_OPTIONS,
            // Match the trigger width (a hair wider so the scrollbar
            // doesn't clip the "12a" glyphs) — kept minimal on purpose.
            minWidth: "3.25rem",
          }}
        >
          {options.map((h) => {
            const selected = h === value;
            return (
              <li
                key={h}
                role="option"
                aria-selected={selected}
                onClick={() => {
                  onChange(h);
                  setOpen(false);
                }}
                style={{ height: OPTION_HEIGHT_PX }}
                className={
                  "px-2 flex items-center cursor-pointer transition-colors " +
                  (selected
                    ? "bg-amber-600 text-ink-950"
                    : "text-ink-200 hover:bg-ink-800")
                }
              >
                {fmtHour12(h)}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

export function WorkHoursSelect({
  hours,
  onChange,
}: {
  hours: WorkHours;
  onChange: (h: WorkHours) => void;
}) {
  // Start hour options: 0..23. End hour options: (startHour + 1)..24.
  const startOptions: number[] = Array.from({ length: 24 }, (_, i) => i);
  const endOptions: number[] = Array.from(
    { length: 24 - hours.startHour },
    (_, i) => hours.startHour + 1 + i
  );

  return (
    <span className="inline-flex items-center gap-1 text-ink-400 text-xs">
      <HourSelect
        ariaLabel="Start of work hours"
        value={hours.startHour}
        options={startOptions}
        onChange={(s) => {
          // If the new start pushes end <= start, snap end to s + 1.
          const nextEnd = hours.endHour > s ? hours.endHour : Math.min(24, s + 1);
          onChange({ startHour: s, endHour: nextEnd });
        }}
      />
      <span className="text-ink-500">–</span>
      <HourSelect
        ariaLabel="End of work hours"
        value={hours.endHour}
        options={endOptions}
        onChange={(e) => onChange({ startHour: hours.startHour, endHour: e })}
      />
    </span>
  );
}
