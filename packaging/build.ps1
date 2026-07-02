# One-shot end-to-end build. Run from repo root:
#
#   pwsh packaging/build.ps1
#
# Order of operations matters:
#   1. Frontend must build BEFORE Tauri, because Tauri bundles frontend/dist/.
#   2. PyInstaller must run BEFORE Tauri, because both sidecar `onedir` trees
#      (exe + _internal/ full of DLLs) get staged into
#      tauri/src-tauri/binaries/ before `tauri build` archives them as MSI
#      resources.
#
# Sidecar packaging note: we do NOT use Tauri's `externalBin` mechanism.
# `externalBin` bundles a single file per entry and does not preserve the
# `_internal/` sibling directory that PyInstaller's onedir loader needs.
# Instead we ship each onedir tree via `bundle.resources` (see
# tauri.conf.json) and spawn the exe from Rust via the installed app's
# resource_dir(). See tauri/src-tauri/src/lib.rs for the runtime side.
#
# This script is deliberately verbose about which step failed — the first
# few builds will hit missing hidden imports and the diff between "step 2
# failed" and "step 4 failed" is what tells us where to look.

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "=== [1/4] Frontend build ===" -ForegroundColor Cyan
Push-Location "$RepoRoot\frontend"
try {
    # VITE_API_URL is baked into the bundle at build time. In the packaged
    # app the api sidecar listens on 127.0.0.1:8765 (see backend/api_entry.py).
    # Setting it inline here beats maintaining a separate .env.production.
    $env:VITE_API_URL = "http://127.0.0.1:8765"
    npm run build
} finally {
    Pop-Location
}

Write-Host "=== [2/4] PyInstaller: watcher sidecar ===" -ForegroundColor Cyan
Push-Location "$RepoRoot\packaging"
try {
    python -m PyInstaller --noconfirm --clean watcher.spec
} finally {
    Pop-Location
}

Write-Host "=== [3/4] PyInstaller: api sidecar ===" -ForegroundColor Cyan
Push-Location "$RepoRoot\packaging"
try {
    python -m PyInstaller --noconfirm --clean api.spec
} finally {
    Pop-Location
}

Write-Host "=== [4/4] Stage sidecars for Tauri ===" -ForegroundColor Cyan
# Copy each PyInstaller onedir tree wholesale under tauri/src-tauri/binaries/.
# tauri.conf.json declares these directories as `bundle.resources` so the
# MSI installer drops them next to the main app exe. The Rust supervisor
# resolves them via resource_dir()/binaries/{name}/{name}.exe at runtime.
$BinDir = "$RepoRoot\tauri\src-tauri\binaries"
if (Test-Path $BinDir) { Remove-Item -Recurse -Force $BinDir }
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null

Write-Host "  → copying watcher onedir..." -ForegroundColor DarkGray
Copy-Item -Recurse "$RepoRoot\packaging\dist\watcher" "$BinDir\watcher"

Write-Host "  → copying api onedir..." -ForegroundColor DarkGray
Copy-Item -Recurse "$RepoRoot\packaging\dist\api" "$BinDir\api"

Write-Host ""
Write-Host "=== [done] Sidecars staged. Next: cd tauri && npm run tauri build ===" -ForegroundColor Green
Write-Host "MSI will land at: tauri\src-tauri\target\release\bundle\msi\*.msi"
