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
    --hidden-import uvicorn.protocols.http.h11_impl \
    --hidden-import uvicorn.protocols.http.httptools_impl \
    --hidden-import uvicorn.protocols.websockets.wsproto_impl \
    --hidden-import uvicorn.protocols.websockets.websockets_impl \
    --hidden-import uvicorn.loops.uvloop \
    --hidden-import uvicorn.loops.asyncio \
    --hidden-import aiosqlite \
    --hidden-import fastapi \
    --hidden-import fastapi.middleware \
    --hidden-import fastapi.middleware.cors \
    --hidden-import fastapi.responses \
    --hidden-import fastapi.routing \
    --hidden-import fastapi.security \
    --hidden-import fastapi.websockets \
    --hidden-import pydantic \
    --hidden-import pydantic.deprecated.decorator \
    --hidden-import pydantic._internal._generate_schema \
    --hidden-import pydantic._internal._validators \
    --hidden-import pydantic_settings \
    --hidden-import pydantic_core \
    --hidden-import starlette \
    --hidden-import starlette.middleware \
    --hidden-import starlette.middleware.cors \
    --hidden-import starlette.routing \
    --hidden-import starlette.responses \
    --hidden-import starlette.websockets \
    --hidden-import starlette.formparsers \
    --hidden-import starlette.concurrency \
    --hidden-import starlette.status \
    --hidden-import httpx \
    --hidden-import httpcore \
    --hidden-import h11 \
    --hidden-import anyio \
    --hidden-import anyio._backends._asyncio \
    --hidden-import sniffio \
    --hidden-import certifi \
    --hidden-import idna \
    --hidden-import aiohttp \
    --hidden-import multidict \
    --hidden-import yarl \
    --hidden-import async_timeout \
    --hidden-import frozenlist \
    --hidden-import aiosignal \
    --hidden-import yfinance \
    --hidden-import apscheduler \
    --hidden-import apscheduler.schedulers.asyncio \
    --hidden-import apscheduler.triggers.cron \
    --hidden-import fredapi \
    --hidden-import dotenv \
    --hidden-import python_dotenv \
    --collect-data sqlalchemy \
    --collect-submodules fastapi \
    --collect-submodules starlette \
    --collect-submodules pydantic \
    --collect-submodules pydantic_core \
    --collect-submodules uvicorn \
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
