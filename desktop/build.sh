#!/usr/bin/env bash
#
# build.sh -- Build Teletraan as a macOS desktop app (Tauri + PyInstaller sidecar)
#
# Prerequisites:
#   - Rust toolchain (rustup)
#   - Node.js >= 18
#   - Python >= 3.12  +  uv
#   - PyInstaller (pip install pyinstaller)
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DESKTOP_DIR="$SCRIPT_DIR"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
BINARIES_DIR="$DESKTOP_DIR/src-tauri/binaries"

# Detect the Rust host triple (e.g. aarch64-apple-darwin)
TARGET_TRIPLE="$(rustc --print host-tuple)"
echo "==> Target triple: $TARGET_TRIPLE"

# ────────────────────────────────────────────────────────────
# 1. Build the Next.js frontend as a static export
# ────────────────────────────────────────────────────────────
echo "==> Building Next.js static export..."
cd "$FRONTEND_DIR"
npm ci --prefer-offline

# Use the desktop-specific Next.js config for static export
NEXT_CONFIG_FILE="next.config.desktop.mjs"
if [ ! -f "$NEXT_CONFIG_FILE" ]; then
    echo "ERROR: $FRONTEND_DIR/$NEXT_CONFIG_FILE not found" >&2
    exit 1
fi

# Next.js 14+ uses `output: 'export'` in next.config -- the export
# directory defaults to "out".  We copy it to desktop/dist afterwards.
npx next build --config "$NEXT_CONFIG_FILE"

rm -rf "$DESKTOP_DIR/dist"
cp -r out "$DESKTOP_DIR/dist"
echo "    Frontend exported to $DESKTOP_DIR/dist"

# ────────────────────────────────────────────────────────────
# 2. Bundle the Python backend with PyInstaller
# ────────────────────────────────────────────────────────────
echo "==> Bundling Python backend with PyInstaller..."
cd "$BACKEND_DIR"

# Ensure dependencies are installed
uv sync

# Run PyInstaller inside the uv venv
uv run pyinstaller \
    --onefile \
    --name teletraan-backend \
    --hidden-import uvicorn.logging \
    --hidden-import uvicorn.loops.auto \
    --hidden-import uvicorn.protocols.http.auto \
    --hidden-import uvicorn.protocols.websockets.auto \
    --hidden-import uvicorn.lifespan.on \
    --hidden-import aiosqlite \
    --collect-data sqlalchemy \
    main.py

# ────────────────────────────────────────────────────────────
# 3. Copy the backend binary into the Tauri sidecar location
#    Tauri expects: binaries/teletraan-backend-<target_triple>
# ────────────────────────────────────────────────────────────
echo "==> Copying backend binary to sidecar location..."
mkdir -p "$BINARIES_DIR"
cp "$BACKEND_DIR/dist/teletraan-backend" \
   "$BINARIES_DIR/teletraan-backend-${TARGET_TRIPLE}"
chmod +x "$BINARIES_DIR/teletraan-backend-${TARGET_TRIPLE}"
echo "    Sidecar binary: $BINARIES_DIR/teletraan-backend-${TARGET_TRIPLE}"

# ────────────────────────────────────────────────────────────
# 4. Build the Tauri desktop app
# ────────────────────────────────────────────────────────────
echo "==> Building Tauri desktop app..."
cd "$DESKTOP_DIR"
npm ci --prefer-offline
npm run build

echo ""
echo "==> Build complete!"
echo "    Look for the .dmg / .app in:"
echo "    $DESKTOP_DIR/src-tauri/target/release/bundle/"
