#!/usr/bin/env bash
#
# build.sh -- Build Teletraan as a macOS desktop app (Tauri + PyInstaller bundled backend)
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
RESOURCES_DIR="$DESKTOP_DIR/src-tauri/resources"

# Detect the Rust host triple (e.g. aarch64-apple-darwin)
TARGET_TRIPLE="$(rustc --print host-tuple)"
echo "==> Target triple: $TARGET_TRIPLE"

# ────────────────────────────────────────────────────────────
# 1. Build the Next.js frontend as a static export
# ────────────────────────────────────────────────────────────
echo "==> Building Next.js static export..."
cd "$FRONTEND_DIR"
npm ci --prefer-offline

# Use the desktop-specific Next.js config for static export.
# Next.js doesn't support --config, so we temporarily swap config files.
NEXT_CONFIG_DESKTOP="next.config.desktop.mjs"
NEXT_CONFIG_ORIGINAL="next.config.ts"
NEXT_CONFIG_BACKUP="next.config.ts.bak"

if [ ! -f "$NEXT_CONFIG_DESKTOP" ]; then
    echo "ERROR: $FRONTEND_DIR/$NEXT_CONFIG_DESKTOP not found" >&2
    exit 1
fi

# Back up the original config and swap in the desktop version
cp "$NEXT_CONFIG_ORIGINAL" "$NEXT_CONFIG_BACKUP"
cp "$NEXT_CONFIG_DESKTOP" "$NEXT_CONFIG_ORIGINAL"

# Ensure we restore the original config even on failure
restore_config() {
    cd "$FRONTEND_DIR"
    if [ -f "$NEXT_CONFIG_BACKUP" ]; then
        mv "$NEXT_CONFIG_BACKUP" "$NEXT_CONFIG_ORIGINAL"
    fi
}
trap restore_config EXIT

# Next.js 14+ uses `output: 'export'` in next.config -- the export
# directory defaults to "out".  We copy it to desktop/dist afterwards.
npx next build

# Restore original config immediately (trap will also run, but that's safe)
restore_config

rm -rf "$DESKTOP_DIR/dist"
cp -r out "$DESKTOP_DIR/dist"
echo "    Frontend exported to $DESKTOP_DIR/dist"

# ────────────────────────────────────────────────────────────
# 2. Bundle the Python backend with PyInstaller
# ────────────────────────────────────────────────────────────
echo "==> Bundling Python backend with PyInstaller..."
cd "$BACKEND_DIR"

# Ensure dependencies are installed (including PyInstaller for bundling)
uv sync
uv pip install pyinstaller

# Run PyInstaller inside the uv venv
uv run pyinstaller \
    --onedir -y \
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
    --hidden-import numpy \
    --hidden-import numpy.core \
    --hidden-import numpy.core._methods \
    --hidden-import numpy.lib \
    --hidden-import numpy.linalg \
    --hidden-import pandas \
    --hidden-import pandas.core.arrays \
    --hidden-import pandas._libs \
    --hidden-import pandas_ta \
    --hidden-import scipy \
    --hidden-import scipy.stats \
    --hidden-import scipy.signal \
    --hidden-import scipy.special \
    --hidden-import requests \
    --hidden-import bs4 \
    --hidden-import peewee \
    --hidden-import platformdirs \
    --hidden-import multitasking \
    --hidden-import frozendict \
    --hidden-import pytz \
    --hidden-import tzlocal \
    --hidden-import dateutil \
    --hidden-import six \
    --hidden-import charset_normalizer \
    --hidden-import urllib3 \
    --hidden-import sqlalchemy.dialects.sqlite \
    --hidden-import sqlalchemy.dialects.postgresql \
    --hidden-import google.protobuf \
    --collect-data sqlalchemy \
    --collect-data pytz \
    --collect-data certifi \
    --collect-submodules fastapi \
    --collect-submodules starlette \
    --collect-submodules pydantic \
    --collect-submodules pydantic_core \
    --collect-submodules uvicorn \
    --collect-submodules numpy \
    --collect-submodules scipy \
    --collect-submodules pandas \
    --collect-submodules yfinance \
    --collect-submodules requests \
    --collect-submodules bs4 \
    main.py

# ────────────────────────────────────────────────────────────
# 3. Copy the backend directory into Tauri resources
#    --onedir produces: dist/teletraan-backend/ (directory with
#    the main binary + all shared libraries / data files).
#    Tauri's `bundle.resources` will embed the directory inside
#    Contents/Resources/ on macOS.
# ────────────────────────────────────────────────────────────
echo "==> Copying backend directory to Tauri resources..."
rm -rf "$RESOURCES_DIR/teletraan-backend"
mkdir -p "$RESOURCES_DIR"
cp -r "$BACKEND_DIR/dist/teletraan-backend" "$RESOURCES_DIR/teletraan-backend"

# Codesign the main binary with entitlements
codesign --force --sign - --entitlements "$DESKTOP_DIR/src-tauri/Entitlements.plist" \
    "$RESOURCES_DIR/teletraan-backend/teletraan-backend"

echo "    Backend directory: $RESOURCES_DIR/teletraan-backend/"

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
