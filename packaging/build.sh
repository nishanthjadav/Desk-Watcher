#!/usr/bin/env bash
# One-shot Python+frontend prep for a LOCAL macOS build.
#
# The macOS counterpart of build.ps1. As with Windows, Tauri's
# `beforeBuildCommand` only builds the frontend — sidecar freezing is driven
# explicitly (locally by this script, in CI by .github/workflows/release.yml).
# So the local macOS flow is two commands from the repo root:
#
#   ./packaging/build.sh              # freeze + stage the sidecars
#   cd tauri && npm run tauri build   # builds frontend (beforeBuildCommand) + .app/.dmg
#
# This script also builds the frontend (step 1) so a standalone run is
# self-contained, but the authoritative frontend build for the bundle is the
# one Tauri runs via beforeBuildCommand.
#
# Order of operations matches build.ps1:
#   1. Frontend build (also done by Tauri; harmless to repeat here).
#   2. PyInstaller must run BEFORE `tauri build`, because both sidecar `onedir`
#      trees (the bare exe + _internal/ full of .dylibs) get staged into
#      tauri/src-tauri/binaries/ before Tauri copies them into the .app as
#      bundle resources.
#
# Sidecar packaging note (same rationale as Windows): we do NOT use Tauri's
# `externalBin`. It bundles a single file per entry and does not preserve the
# `_internal/` sibling directory PyInstaller's onedir loader needs. We ship
# each onedir tree via `bundle.resources` (tauri.conf.json) and spawn the bare
# executable from Rust via the installed app's resource_dir(). PyInstaller emits
# `{name}` (no extension) on macOS — see sidecar_path() in lib.rs.
#
# Verbose about which step failed, for the same reason build.ps1 is: the first
# macOS builds will hit missing hidden imports / native-lib collection gaps, and
# knowing whether step 2 or step 3 failed is what tells us where to look.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo -e "\033[36m=== [1/4] Frontend build ===\033[0m"
(
    cd "$REPO_ROOT/frontend"
    # VITE_API_URL is baked into the bundle at build time. In the packaged app
    # the api sidecar listens on 127.0.0.1:8765 (see backend/api_entry.py).
    # Setting it inline here beats maintaining a separate .env.production.
    export VITE_API_URL="http://127.0.0.1:8765"
    npm run build
)

echo -e "\033[36m=== [2/4] PyInstaller: watcher sidecar ===\033[0m"
(
    cd "$REPO_ROOT/packaging"
    python3 -m PyInstaller --noconfirm --clean watcher.spec
)

echo -e "\033[36m=== [3/4] PyInstaller: api sidecar ===\033[0m"
(
    cd "$REPO_ROOT/packaging"
    python3 -m PyInstaller --noconfirm --clean api.spec
)

echo -e "\033[36m=== [4/4] Stage sidecars for Tauri ===\033[0m"
# Copy each PyInstaller onedir tree wholesale under tauri/src-tauri/binaries/.
# tauri.conf.json declares these directories as `bundle.resources` so the .app
# carries them under Contents/Resources/. The Rust supervisor resolves them via
# resource_dir()/binaries/{name}/{name} at runtime.
BIN_DIR="$REPO_ROOT/tauri/src-tauri/binaries"
rm -rf "$BIN_DIR"
mkdir -p "$BIN_DIR"

echo -e "  \033[90m→ copying watcher onedir...\033[0m"
cp -R "$REPO_ROOT/packaging/dist/watcher" "$BIN_DIR/watcher"

echo -e "  \033[90m→ copying api onedir...\033[0m"
cp -R "$REPO_ROOT/packaging/dist/api" "$BIN_DIR/api"

# ── Staging verification ────────────────────────────────────────────────────
# A killed/interrupted run can leave the freeze done but staging incomplete —
# Tauri would then silently archive STALE binaries into the .app. Fail loudly
# here if the staged executables are missing or OLDER than the .spec that
# produced them (a sign the freeze didn't actually re-run for a spec change).
echo -e "\033[36m=== [verify] Checking staged sidecars are fresh ===\033[0m"

verify() {
    local name="$1" exe="$2" spec="$3"
    if [[ ! -f "$exe" ]]; then
        echo "STAGING FAILED: $name sidecar missing at $exe." >&2
        echo "The freeze or copy did not complete — do NOT build the app, it would ship stale/absent binaries." >&2
        exit 1
    fi
    # Fresh check: exe must be newer than its spec. `find -newer` avoids the
    # portability minefield of parsing `stat` mtimes across BSD/GNU.
    if [[ -z "$(find "$exe" -newer "$spec" 2>/dev/null)" ]]; then
        echo "STALE BINARY: $name ($exe) is not newer than $name.spec ($spec)." >&2
        echo "The freeze did not pick up the spec change. Re-run this script and let it finish." >&2
        exit 1
    fi
    echo -e "  \033[32m✓ $name is present and newer than its spec\033[0m"
}

verify "watcher" "$BIN_DIR/watcher/watcher" "$REPO_ROOT/packaging/watcher.spec"
verify "api"     "$BIN_DIR/api/api"         "$REPO_ROOT/packaging/api.spec"

echo ""
echo -e "\033[32m=== [done] Sidecars staged and verified. Tauri will now archive them into the .app. ===\033[0m"
echo "Bundle will land under: tauri/src-tauri/target/release/bundle/{dmg,macos}/"
