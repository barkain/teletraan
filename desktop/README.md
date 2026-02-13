# Teletraan Desktop

Package Teletraan (FastAPI backend + Next.js frontend) as a native desktop application using **Tauri v2** with a Python sidecar.

## Architecture

```
 Tauri shell (Rust / WebView)
   |
   +-- Next.js static export  (loaded into webview)
   |
   +-- Python backend sidecar  (spawned on startup, killed on exit)
         |
         +-- FastAPI / uvicorn on 127.0.0.1:8000
         +-- SQLite DB at <app data>/market-analyzer.db
```

On launch the Rust host:
1. Spawns the bundled `teletraan-backend` binary as a sidecar process.
2. Polls `GET /api/v1/health` every 500 ms (up to 30 s).
3. Once the backend reports healthy, the main window becomes visible.
4. On quit the sidecar is sent SIGKILL / TerminateProcess.

## Prerequisites

| Dependency | Version | Notes |
|------------|---------|-------|
| **Rust** | latest stable | `rustup update` |
| **Node.js** | >= 18 | for Next.js + Tauri CLI |
| **Python** | >= 3.12 | backend runtime |
| **uv** | latest | Python package manager |
| **PyInstaller** | latest | `pip install pyinstaller` or `uv pip install pyinstaller` |

### macOS extras

- Xcode Command Line Tools (`xcode-select --install`)

### Windows extras

- Visual Studio Build Tools with C++ workload
- WebView2 runtime (ships with Windows 10+)

## Development mode

Run the backend and frontend separately, then launch Tauri in dev mode pointing at the running frontend dev server.

```bash
# Terminal 1 -- backend
cd ../backend
uv run uvicorn main:app --reload --port 8000

# Terminal 2 -- frontend
cd ../frontend
npm run dev          # http://localhost:3000

# Terminal 3 -- Tauri dev shell
cd desktop
npm install
npm run dev          # opens a native window pointing at localhost:3000
```

In dev mode the sidecar is **not** spawned automatically (the `devUrl` in `tauri.conf.json` points directly at the Next.js dev server). You must start the backend manually.

## Production build

### macOS

```bash
cd desktop
./build.sh
```

The script will:
1. Build the Next.js frontend as a static export (`output: 'export'`).
2. Bundle the Python backend into a single binary with PyInstaller.
3. Copy the binary into `src-tauri/binaries/` with the correct target-triple suffix.
4. Run `tauri build` to produce a `.dmg` / `.app` bundle.

Output: `src-tauri/target/release/bundle/`

### Windows

```powershell
cd desktop
.\build.ps1
```

Same steps, producing an NSIS installer.

Output: `src-tauri\target\release\bundle\`

## CI / GitHub Actions builds

The repository includes a GitHub Actions workflow (`.github/workflows/build-desktop.yml`) that builds desktop binaries for three targets:

| Target | Runner | Artifact |
|--------|--------|----------|
| macOS ARM64 (`aarch64-apple-darwin`) | `macos-latest` | `.dmg` |
| macOS x64 (`x86_64-apple-darwin`) | `macos-latest` | `.dmg` |
| Windows x64 (`x86_64-pc-windows-msvc`) | `windows-latest` | `.exe` (NSIS) / `.msi` |

### Triggering a build

**Manual (workflow_dispatch):**
1. Go to **Actions** > **Build Desktop App** on GitHub.
2. Click **Run workflow**, select the branch, and click the green button.

**Automatic (tag push):**
```bash
git tag v0.1.0
git push origin v0.1.0
```
Pushing a `v*` tag triggers the build and creates a draft GitHub Release with all platform binaries attached.

### Downloading built binaries

1. Go to the completed workflow run under **Actions** > **Build Desktop App**.
2. Scroll to the **Artifacts** section at the bottom of the run summary.
3. Download the artifact for your platform:
   - `teletraan-macOS-arm64` -- Apple Silicon `.dmg`
   - `teletraan-macOS-x64` -- Intel Mac `.dmg`
   - `teletraan-Windows-x64` -- Windows NSIS installer (`.exe`) and MSI

For tagged builds, the binaries are also attached to the **Releases** page as a draft release.

### What the CI does

1. Checks out the repo and sets up Node.js 20, Python 3.12, Rust stable, and uv.
2. Builds the Next.js frontend as a static export using `next.config.desktop.mjs`.
3. Installs backend dependencies with `uv sync` and bundles the Python backend into a single binary with PyInstaller.
4. Copies the sidecar binary to `desktop/src-tauri/binaries/teletraan-backend-<target-triple>[.exe]`.
5. Runs `tauri-apps/tauri-action` to compile the Rust shell and produce platform installers.
6. Uploads platform-specific artifacts (`.dmg`, `.app`, `.exe`, `.msi`).
7. On tag pushes, creates a draft GitHub Release with all artifacts attached.

## Project structure

```
desktop/
  package.json              Tauri CLI dependency + npm scripts
  build.sh                  macOS / Linux build script
  build.ps1                 Windows build script
  dist/                     (generated) Next.js static export
  src-tauri/
    Cargo.toml              Rust dependencies
    tauri.conf.json          Tauri configuration
    build.rs                Tauri build hook
    capabilities/
      default.json          Permission grants (sidecar execution)
    binaries/               Sidecar binaries (populated by build script)
    icons/                  App icons (add before production build)
    src/
      main.rs               Minimal entry point
      lib.rs                App logic: sidecar lifecycle, health check
```

## LLM Provider Configuration

The desktop app uses the same LLM provider configuration as the web version. See the [LLM Providers](../README.md#llm-providers) section in the main README for setup instructions. Configure providers via `backend/.env` before building.

## Known limitations

- **Icons**: The `icons/` directory is empty. Before a production release, generate icons with `npx @tauri-apps/cli icon <path-to-1024x1024.png>`.
- **Code signing**: macOS builds are unsigned. For distribution outside the App Store, you need an Apple Developer certificate and notarisation.
- **Windows Defender**: The PyInstaller-bundled backend may trigger false-positive AV warnings. Signing the `.exe` with an EV certificate resolves this.
- **Database location**: The sidecar currently writes `market-analyzer.db` relative to its working directory. A future improvement should use Tauri's `app_data_dir` and pass the path as a CLI arg to the backend.
- **Auto-update**: Not configured. Tauri v2 supports the `tauri-plugin-updater` plugin if needed.
- **Static export caveats**: Any Next.js features that require a Node server (ISR, API routes, middleware) are unavailable in the desktop build. The app must use the FastAPI backend for all server-side logic.
- **First launch latency**: PyInstaller one-file binaries unpack to a temp directory on first run, adding 3-10 s of startup time. Using `--onedir` instead of `--onefile` would eliminate this but complicates the sidecar setup.
