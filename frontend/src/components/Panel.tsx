/**
 * Panel — the standard container for a dashboard section.
 *
 * Optional collapsible mode: pass `collapsibleId` and the panel grows
 * a chevron in its header that toggles the body. Collapsed state is
 * persisted to localStorage per-id, so each panel remembers its state
 * independently across page reloads.
 *
 * Non-collapsible panels (no `collapsibleId`) behave exactly like the
 * original v0.x Panel — visible always, no chevron.
 */
import { useCallback, useState } from "react";

const COLLAPSED_KEY = "deskwatcher.panels.collapsed.v1";

// localStorage holds a JSON object: { [panelId]: true }. Missing key =
// expanded (the default).
function loadCollapsedSet(): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw = window.localStorage.getItem(COLLAPSED_KEY);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return new Set();
    return new Set(Object.keys(parsed).filter((k) => parsed[k] === true));
  } catch {
    return new Set();
  }
}

function saveCollapsedSet(s: Set<string>): void {
  try {
    const obj: Record<string, true> = {};
    for (const k of s) obj[k] = true;
    window.localStorage.setItem(COLLAPSED_KEY, JSON.stringify(obj));
  } catch {
    // see TileGrid.savePinnedIds — non-critical
  }
}

export function Panel({
  title,
  right,
  children,
  className = "",
  collapsibleId,
}: {
  title?: string;
  right?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  // If provided, panel is collapsible and uses this id as the localStorage key.
  collapsibleId?: string;
}) {
  // Lazy initial state from localStorage. We re-read once per mount;
  // siblings reading the same key won't see each other's changes
  // mid-session, but since each id is unique, that's fine.
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    if (!collapsibleId) return false;
    return loadCollapsedSet().has(collapsibleId);
  });

  const toggle = useCallback(() => {
    if (!collapsibleId) return;
    setCollapsed((prev) => {
      const next = !prev;
      const s = loadCollapsedSet();
      if (next) s.add(collapsibleId);
      else s.delete(collapsibleId);
      saveCollapsedSet(s);
      return next;
    });
  }, [collapsibleId]);

  const headerClickable = !!collapsibleId;
  // Render the header whenever EITHER a title or a right-side widget is
  // present. Letting `right` alone trigger the header lets callers add
  // controls (e.g. "Customize pins") to an otherwise-untitled panel
  // without inventing a placeholder title.
  const renderHeader = !!title || !!right;

  return (
    // When the panel is collapsed, opt out of CSS-grid row-stretching
    // (`self-start`) so it shrinks to header-height even if a sibling
    // in the same grid row is still expanded. Without this, the
    // collapsed panel inflates to match the tallest sibling because
    // the default grid-item alignment is `stretch`.
    <section
      className={`border border-ink-700 bg-ink-900 flex flex-col ${collapsed ? "self-start" : ""} ${className}`}
    >
      {renderHeader && (
        <header
          className={
            "flex items-center justify-between px-4 py-2 border-b border-ink-700 shrink-0 " +
            (headerClickable ? "cursor-pointer hover:bg-ink-850 transition-colors" : "")
          }
          onClick={headerClickable ? toggle : undefined}
          role={headerClickable ? "button" : undefined}
          aria-expanded={headerClickable ? !collapsed : undefined}
          tabIndex={headerClickable ? 0 : undefined}
          onKeyDown={
            headerClickable
              ? (e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    toggle();
                  }
                }
              : undefined
          }
        >
          <div className="flex items-center gap-2">
            {collapsibleId && (
              <span
                aria-hidden="true"
                className={
                  "inline-block text-ink-400 text-xs transition-transform " +
                  (collapsed ? "-rotate-90" : "rotate-0")
                }
              >
                ▾
              </span>
            )}
            {title && (
              <h2 className="text-2xs uppercase tracking-[0.18em] text-ink-300 font-medium">
                {title}
              </h2>
            )}
          </div>
          {right && (
            <div
              className="text-2xs text-ink-400 tabular"
              // Clicking widgets inside `right` (e.g. range-selector buttons)
              // must not also toggle the collapse.
              onClick={(e) => e.stopPropagation()}
            >
              {right}
            </div>
          )}
        </header>
      )}
      {!collapsed && children}
    </section>
  );
}
