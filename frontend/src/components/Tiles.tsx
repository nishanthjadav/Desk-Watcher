/**
 * Tile components for the pinned-metric grid at the top of the dashboard.
 *
 * Two visual variants:
 *   - <MetricTile>   number tile  (label, big number, sub-line)
 *   - <SparklineTile> sparkline tile (label, big number, tiny line, sub-line)
 *
 * Both:
 *   - Are sortable via dnd-kit's useSortable hook
 *   - Show an X button on hover that calls onUnpin
 *   - Render the same outer shape so the row stays uniform
 *
 * The sparkline is a hand-rolled SVG instead of a recharts component.
 * Recharts is overkill for a 24-point line and would add ~30 KB to
 * the bundle for something that's three SVG primitives.
 *
 * The "+" tile that used to live here is gone — tiles are now added/
 * removed via the "Customize pins" link in the row's panel header,
 * which opens a multi-select picker. See TileGrid + TilePicker.
 */
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import type { TileDisplay } from "../metrics/catalog";

interface TileProps {
  id: string;
  label: string;
  display: TileDisplay;
  onUnpin: () => void;
}

// Shared outer shell: matches the look of the v0.x Metric component
// (border-r, padded, flex-1) so the grid still renders as a row of
// equal-width cells with separators.
function TileShell({
  id,
  children,
  onUnpin,
}: {
  id: string;
  children: React.ReactNode;
  onUnpin: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id });

  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
    zIndex: isDragging ? 10 : "auto",
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      // The whole tile is the drag handle. flex-1 spreads tiles evenly
      // across the row; border-r mimics the v0.x layout (last tile has no
      // border thanks to last:border-r-0).
      className="group relative px-4 py-3 border-r border-ink-700 last:border-r-0 flex-1 cursor-grab active:cursor-grabbing select-none"
      {...attributes}
      {...listeners}
    >
      {/* Unpin button — appears on hover. stopPropagation so clicking it
          doesn't also start a drag. */}
      <button
        type="button"
        onPointerDown={(e) => e.stopPropagation()}
        onClick={(e) => {
          e.stopPropagation();
          onUnpin();
        }}
        aria-label="Unpin tile"
        className="absolute top-1.5 right-1.5 w-4 h-4 flex items-center justify-center text-ink-400 hover:text-ink-100 opacity-0 group-hover:opacity-100 transition-opacity text-xs leading-none"
      >
        ×
      </button>
      {children}
    </div>
  );
}

export function MetricTile({ id, label, display, onUnpin }: TileProps) {
  return (
    <TileShell id={id} onUnpin={onUnpin}>
      <div className="text-2xs uppercase tracking-[0.16em] text-ink-400">{label}</div>
      <div className="mt-1 font-mono text-2xl text-ink-100 tabular">{display.value}</div>
      {display.sub && <div className="text-2xs text-ink-400 mt-0.5">{display.sub}</div>}
    </TileShell>
  );
}

export function SparklineTile({ id, label, display, onUnpin }: TileProps) {
  const points = display.spark ?? [];
  return (
    <TileShell id={id} onUnpin={onUnpin}>
      <div className="text-2xs uppercase tracking-[0.16em] text-ink-400">{label}</div>
      <div className="mt-1 font-mono text-2xl text-ink-100 tabular">{display.value}</div>
      <Spark points={points} />
      {display.sub && <div className="text-2xs text-ink-400 mt-0.5">{display.sub}</div>}
    </TileShell>
  );
}

// Minimal sparkline. Plots `points` as a continuous line scaled to its own
// min/max, with a 1px-amber stroke. Empty array renders an empty box so
// the tile keeps the same height as a populated one (no layout jump
// when data arrives).
function Spark({ points }: { points: number[] }) {
  const W = 100;
  const H = 14;
  if (points.length < 2) {
    return <svg width={W} height={H} className="mt-1 block" />;
  }
  // Scale Y to the visible band with a small inset so peaks/troughs don't
  // touch the edges. Constant-value series collapses to a flat midline.
  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;
  const pad = 1;
  const step = (W - pad * 2) / (points.length - 1);
  const d = points
    .map((v, i) => {
      const x = pad + i * step;
      const y = pad + (H - pad * 2) * (1 - (v - min) / range);
      return `${i === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="mt-1 block">
      <path d={d} fill="none" stroke="#f5a623" strokeWidth="1" />
    </svg>
  );
}
