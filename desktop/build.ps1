#
# build.ps1 -- Build Teletraan as a Windows desktop app (Tauri + PyInstaller sidecar)
#
# Prerequisites:
#   - Rust toolchain (rustup)
#   - Node.js >= 18
#   - Python >= 3.12  +  uv
#   - PyInstaller (pip install pyinstaller)
#   - Visual Studio Build Tools (for Tauri / WiX / NSIS)
#

$ErrorActionPreference = "Stop"

$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$DesktopDir  = $ScriptDir
$BackendDir  = Join-Path $ProjectRoot "backend"
$FrontendDir = Join-Path $ProjectRoot "frontend"
$ResourcesDir = Join-Path $DesktopDir  "src-tauri\resources"

# Detect the Rust host triple
$TargetTriple = (rustc --print host-tuple).Trim()
Write-Host "==> Target triple: $TargetTriple"

# ────────────────────────────────────────────────────────────
# 1. Build the Next.js frontend as a static export
# ────────────────────────────────────────────────────────────
Write-Host "==> Building Next.js static export..."
Set-Location $FrontendDir
npm ci --prefer-offline

$NextConfig = "next.config.desktop.mjs"
if (-not (Test-Path $NextConfig)) {
    Write-Error "ERROR: $FrontendDir\$NextConfig not found"
    exit 1
}

npx next build --config $NextConfig

$DistDir = Join-Path $DesktopDir "dist"
if (Test-Path $DistDir) { Remove-Item -Recurse -Force $DistDir }
Copy-Item -Recurse -Path "out" -Destination $DistDir
Write-Host "    Frontend exported to $DistDir"

# ────────────────────────────────────────────────────────────
# 2. Bundle the Python backend with PyInstaller
# ────────────────────────────────────────────────────────────
Write-Host "==> Bundling Python backend with PyInstaller..."
Set-Location $BackendDir

uv sync

uv run pyinstaller `
    --onedir -y `
    --name teletraan-backend `
    --hidden-import uvicorn.logging `
    --hidden-import uvicorn.loops.auto `
    --hidden-import uvicorn.protocols.http.auto `
    --hidden-import uvicorn.protocols.websockets.auto `
    --hidden-import uvicorn.lifespan.on `
    --hidden-import aiosqlite `
    --collect-data sqlalchemy `
    main.py

# ────────────────────────────────────────────────────────────
# 3. Copy the backend directory into Tauri resources
#    --onedir produces: dist/teletraan-backend/ (directory with
#    the main binary + all shared libraries / data files).
#    Tauri's `bundle.resources` will embed the directory inside
#    Contents/Resources/ on macOS and equivalent on Windows.
# ────────────────────────────────────────────────────────────
Write-Host "==> Copying backend directory to Tauri resources..."
if (Test-Path (Join-Path $ResourcesDir "teletraan-backend")) {
    Remove-Item -Recurse -Force (Join-Path $ResourcesDir "teletraan-backend")
}
if (-not (Test-Path $ResourcesDir)) { New-Item -ItemType Directory -Path $ResourcesDir | Out-Null }

$SrcDir  = Join-Path $BackendDir "dist\teletraan-backend"
$DestDir = Join-Path $ResourcesDir "teletraan-backend"
Copy-Item -Recurse -Force -Path $SrcDir -Destination $DestDir
Write-Host "    Backend directory: $DestDir"

# ────────────────────────────────────────────────────────────
# 4. Build the Tauri desktop app
# ────────────────────────────────────────────────────────────
Write-Host "==> Building Tauri desktop app..."
Set-Location $DesktopDir
npm ci --prefer-offline
npm run build

Write-Host ""
Write-Host "==> Build complete!"
Write-Host "    Look for the installer in:"
Write-Host "    $DesktopDir\src-tauri\target\release\bundle\"
