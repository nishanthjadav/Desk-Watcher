/**
 * The pinned-tile row at the top of the dashboard.
 *
 * Exports two things:
 *   - <TileGrid> the visible row of sortable tiles
 *   - usePinControls() a hook for the parent to drive open/close of the
 *     picker modal and the modal element itself
 *
 * The split exists because the "Customize pins" link sits in the panel
 * header (the parent), not inside the tile row. The hook owns the
 * pin-state + picker-open state so both consumers stay in sync without
 * prop-drilling through the panel.
 */
import { useCallback, useMemo, useState } from "react";
import {
  DndContext,
  DragEndEvent,
  PointerSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  horizontalListSortingStrategy,
} from "@dnd-kit/sortable";

import {
  DEFAULT_PINNED_IDS,
  METRIC_CATALOG,
  MetricInputs,
  metricById,
} from "../metrics/catalog";
import { MetricTile, SparklineTile } from "./Tiles";
import { TilePicker } from "./TilePicker";

// localStorage schema:
//   key:   PIN_KEY (versioned so we can rev the schema later without
//          tripping over old values from previous releases)
//   value: JSON-encoded string[] of metric ids in display order
const PIN_KEY = "deskwatcher.tiles.pinned.v1";

function loadPinnedIds(): string[] {
  if (typeof window === "undefined") return DEFAULT_PINNED_IDS;
  try {
    const raw = window.localStorage.getItem(PIN_KEY);
    if (!raw) return DEFAULT_PINNED_IDS;
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return DEFAULT_PINNED_IDS;
    const valid = parsed.filter(
      (id): id is string => typeof id === "string" && !!metricById(id)
    );
    return valid.length > 0 ? valid : DEFAULT_PINNED_IDS;
  } catch {
    return DEFAULT_PINNED_IDS;
  }
}

function savePinnedIds(ids: string[]): void {
  try {
    window.localStorage.setItem(PIN_KEY, JSON.stringify(ids));
  } catch {
    // see TileGrid.savePinnedIds — non-critical
  }
}

// ── Public hook ────────────────────────────────────────────────────────────

export interface PinControls {
  pinnedIds: string[];
  setPinnedIds: (ids: string[]) => void;
  pickerOpen: boolean;
  openPicker: () => void;
  closePicker: () => void;
}

export function usePinControls(): PinControls {
  const [pinnedIds, setIds] = useState<string[]>(loadPinnedIds);
  const [pickerOpen, setPickerOpen] = useState(false);

  const setPinnedIds = useCallback((next: string[]) => {
    setIds(next);
    savePinnedIds(next);
  }, []);

  return {
    pinnedIds,
    setPinnedIds,
    pickerOpen,
    openPicker: () => setPickerOpen(true),
    closePicker: () => setPickerOpen(false),
  };
}

// ── Picker modal — rendered by parent when controls.pickerOpen is true ────

export function PinPicker({ controls }: { controls: PinControls }) {
  if (!controls.pickerOpen) return null;
  return (
    <TilePicker
      catalog={METRIC_CATALOG}
      currentPinnedIds={controls.pinnedIds}
      onApply={(next) => {
        controls.setPinnedIds(next);
        controls.closePicker();
      }}
      onClose={controls.closePicker}
    />
  );
}

// ── The visible tile row ──────────────────────────────────────────────────

export function TileGrid({
  inputs,
  controls,
}: {
  inputs: MetricInputs;
  controls: PinControls;
}) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } })
  );

  const handleUnpin = useCallback(
    (id: string) => {
      controls.setPinnedIds(controls.pinnedIds.filter((x) => x !== id));
    },
    [controls]
  );

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { active, over } = event;
      if (!over || active.id === over.id) return;
      const oldIndex = controls.pinnedIds.indexOf(String(active.id));
      const newIndex = controls.pinnedIds.indexOf(String(over.id));
      if (oldIndex === -1 || newIndex === -1) return;
      controls.setPinnedIds(arrayMove(controls.pinnedIds, oldIndex, newIndex));
    },
    [controls]
  );

  const pinned = useMemo(
    () =>
      controls.pinnedIds
        .map((id) => metricById(id))
        .filter((m): m is NonNullable<typeof m> => !!m),
    [controls.pinnedIds]
  );

  // Empty state — no tiles pinned. Show a small prompt so the row isn't
  // a confusing zero-height void.
  if (pinned.length === 0) {
    return (
      <div className="px-4 py-6 text-2xs text-ink-400">
        No tiles pinned. Click <span className="text-amber-400">Customize pins</span> above to add some.
      </div>
    );
  }

  return (
    <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
      <SortableContext
        items={controls.pinnedIds}
        strategy={horizontalListSortingStrategy}
      >
        <div className="flex">
          {pinned.map((metric) => {
            const display = metric.selector(inputs);
            const onUnpin = () => handleUnpin(metric.id);
            if (metric.variant === "sparkline") {
              return (
                <SparklineTile
                  key={metric.id}
                  id={metric.id}
                  label={metric.label}
                  display={display}
                  onUnpin={onUnpin}
                />
              );
            }
            return (
              <MetricTile
                key={metric.id}
                id={metric.id}
                label={metric.label}
                display={display}
                onUnpin={onUnpin}
              />
            );
          })}
        </div>
      </SortableContext>
    </DndContext>
  );
}
