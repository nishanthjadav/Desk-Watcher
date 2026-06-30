/**
 * Multi-select metric picker.
 *
 * Opens when the user clicks "Customize pins" in the tile-row header.
 * Every catalog entry is shown with a checkbox; currently-pinned ones
 * are pre-checked. User checks/unchecks any number, clicks Apply, and
 * the new set replaces the pinned ids.
 *
 * Apply policy: tiles that were pinned AND stay checked keep their
 * existing position; newly-checked tiles append in catalog order.
 * Unchecking and re-checking a tile sends it to the end. This matches
 * the mental model that re-pinning is "add it back," not "restore the
 * old slot."
 */
import { useEffect, useMemo, useState } from "react";
import type { MetricDef, MetricGroup } from "../metrics/catalog";

const GROUP_LABELS: Record<MetricGroup, string> = {
  activity: "Activity counts",
  time: "Time totals",
  pace: "Pace & focus",
};

const GROUP_ORDER: MetricGroup[] = ["time", "activity", "pace"];

interface Props {
  catalog: MetricDef[];
  currentPinnedIds: string[];
  onApply: (nextIds: string[]) => void;
  onClose: () => void;
}

export function TilePicker({ catalog, currentPinnedIds, onApply, onClose }: Props) {
  // Working draft of the checked set. Initialized from the live pinned
  // ids; user toggles freely until they hit Apply or Cancel.
  const [checked, setChecked] = useState<Set<string>>(() => new Set(currentPinnedIds));

  // If the modal is re-opened with a different pinned set, reset.
  // (Today the modal unmounts on close so this isn't strictly needed,
  // but it makes the component robust to a future "modal stays mounted"
  // pattern.)
  useEffect(() => {
    setChecked(new Set(currentPinnedIds));
  }, [currentPinnedIds]);

  // Esc closes without applying.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const toggle = (id: string) => {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // Group the catalog for display.
  const grouped: Record<MetricGroup, MetricDef[]> = useMemo(() => {
    const g: Record<MetricGroup, MetricDef[]> = { activity: [], time: [], pace: [] };
    for (const m of catalog) g[m.group].push(m);
    return g;
  }, [catalog]);

  const apply = () => {
    // Order policy: keep currently-pinned-and-still-checked tiles in
    // their existing order, then append newly-checked tiles in catalog
    // order. This makes Apply non-destructive to layout when the user
    // only adds tiles, which is the common case.
    const kept = currentPinnedIds.filter((id) => checked.has(id));
    const added = catalog
      .map((m) => m.id)
      .filter((id) => checked.has(id) && !currentPinnedIds.includes(id));
    onApply([...kept, ...added]);
  };

  const checkedCount = checked.size;
  const dirty =
    checkedCount !== currentPinnedIds.length ||
    currentPinnedIds.some((id) => !checked.has(id));

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={onClose}
    >
      <div
        className="bg-ink-900 border border-ink-700 w-full max-w-md max-h-[80vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="px-4 py-3 border-b border-ink-700 flex items-center justify-between shrink-0">
          <h2 className="text-2xs uppercase tracking-[0.18em] text-ink-300 font-medium">
            Customize pins
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close picker"
            className="text-ink-400 hover:text-ink-100 text-lg leading-none"
          >
            ×
          </button>
        </header>

        <div className="overflow-y-auto flex-1 divide-y divide-ink-800">
          {GROUP_ORDER.map((g) => {
            const items = grouped[g];
            if (items.length === 0) return null;
            return (
              <div key={g}>
                <div className="px-4 py-2 text-2xs uppercase tracking-[0.16em] text-ink-500 bg-ink-850">
                  {GROUP_LABELS[g]}
                </div>
                {items.map((opt) => {
                  const isChecked = checked.has(opt.id);
                  return (
                    <label
                      key={opt.id}
                      className="flex items-start gap-3 px-4 py-3 hover:bg-ink-850 transition-colors cursor-pointer"
                    >
                      <input
                        type="checkbox"
                        checked={isChecked}
                        onChange={() => toggle(opt.id)}
                        // Custom-styled checkbox: amber square that fills
                        // when checked, neutral border when not. Slightly
                        // larger than the default browser checkbox so it
                        // reads as a deliberate tap target.
                        className="mt-0.5 w-4 h-4 shrink-0 accent-amber-500"
                      />
                      <div className="flex-1">
                        <div className="text-sm text-ink-100">{opt.label}</div>
                        <div className="text-2xs text-ink-400 mt-0.5">{opt.description}</div>
                      </div>
                    </label>
                  );
                })}
              </div>
            );
          })}
        </div>

        <footer className="px-4 py-3 border-t border-ink-700 flex items-center justify-between shrink-0">
          <span className="text-2xs text-ink-400 tabular">
            {checkedCount} pinned
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-1.5 text-xs uppercase tracking-[0.14em] text-ink-300 hover:text-ink-100 hover:bg-ink-850 transition-colors"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={apply}
              disabled={!dirty}
              className={
                "px-3 py-1.5 text-xs uppercase tracking-[0.14em] transition-colors " +
                (dirty
                  ? "bg-amber-600 text-ink-950 hover:bg-amber-500"
                  : "bg-ink-800 text-ink-500 cursor-not-allowed")
              }
            >
              Apply
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}
