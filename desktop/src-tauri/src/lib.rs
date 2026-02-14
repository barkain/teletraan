use std::io::{BufRead, BufReader, Write};
use std::process::{Child, Command as StdCommand, Stdio};
use std::sync::Mutex;
use std::time::Duration;

use tauri::{AppHandle, Emitter, Manager, RunEvent};

/// State container for the backend child process.
/// Wrapped in Mutex so it can be safely accessed from multiple async contexts.
struct BackendProcess(Mutex<Option<Child>>);

/// Subset of the backend health check JSON response.
#[derive(serde::Deserialize)]
struct HealthResponse {
    status: String,
}

/// Resolve the persistent data directory for the backend.
///
/// Uses Tauri's `app_data_dir()` which resolves to platform-appropriate paths:
/// - macOS: ~/Library/Application Support/com.teletraan.app/
/// - Linux: ~/.local/share/com.teletraan.app/
/// - Windows: C:\Users\<User>\AppData\Roaming\com.teletraan.app\
///
/// Creates the directory (and `data/` subdirectory) if they don't exist.
fn resolve_data_dir(app: &AppHandle) -> Result<std::path::PathBuf, String> {
    let data_dir = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("Failed to resolve app data directory: {e}"))?;

    // Ensure the directory tree exists
    std::fs::create_dir_all(&data_dir)
        .map_err(|e| format!("Failed to create app data directory {}: {e}", data_dir.display()))?;

    // Also pre-create the data/ subdirectory that the backend expects
    let db_subdir = data_dir.join("data");
    std::fs::create_dir_all(&db_subdir)
        .map_err(|e| format!("Failed to create data subdirectory {}: {e}", db_subdir.display()))?;

    log::info!("Backend data directory: {}", data_dir.display());
    Ok(data_dir)
}

/// Spawn the Python backend as a child process from the bundled resources.
///
/// The window is visible immediately (configured in tauri.conf.json) so
/// the frontend `BackendReadinessGate` can show a splash screen while the
/// backend starts up.  A background health-check loop logs when the backend
/// becomes healthy but does **not** block the window from appearing.
async fn start_backend(app: &AppHandle) -> Result<(), String> {
    log::info!("Starting Teletraan backend...");

    // Resolve persistent data directory for the bundled app.
    let data_dir = resolve_data_dir(app)?;

    // Build the DATABASE_URL pointing into the app data directory.
    let db_path = data_dir.join("data").join("market-analyzer.db");
    let database_url = format!(
        "sqlite+aiosqlite:///{}",
        db_path.display()
    );

    // Locate the bundled backend binary inside the app's Resources directory.
    // Tauri bundles files listed in `bundle.resources` into Contents/Resources/ on macOS.
    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|e| format!("Failed to resolve resource directory: {e}"))?;
    let backend_bin = resource_dir
        .join("resources")
        .join("teletraan-backend")
        .join("teletraan-backend");

    log::info!("Backend binary: {}", backend_bin.display());
    log::info!("Backend DATABASE_URL: {database_url}");

    // Spawn the backend as a regular child process.
    // Remove CLAUDECODE / CLAUDE_CODE_ENTRYPOINT so the backend's
    // claude-agent-sdk doesn't think it's running inside Claude Code
    // (which would cause "cannot be launched inside another session" errors).
    let mut child = StdCommand::new(&backend_bin)
        .args(["--host", "127.0.0.1", "--port", "8000"])
        .current_dir(&data_dir)
        .env("DATABASE_URL", &database_url)
        .env_remove("CLAUDECODE")
        .env_remove("CLAUDE_CODE_ENTRYPOINT")
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("Failed to spawn backend process: {e}"))?;

    log::info!("Backend process spawned (pid: {})", child.id());

    // ---- Capture stdout/stderr to backend.log and Tauri console ----
    let log_path = data_dir.join("backend.log");
    log::info!("Backend log file: {}", log_path.display());

    // Take the stdout/stderr handles before stashing the child.
    let child_stdout = child.stdout.take();
    let child_stderr = child.stderr.take();

    // Helper: spawn a thread that reads lines and writes to the shared log file + Tauri log.
    fn spawn_output_reader(
        stream: impl std::io::Read + Send + 'static,
        log_path: std::path::PathBuf,
        label: &'static str,
    ) {
        std::thread::spawn(move || {
            let reader = BufReader::new(stream);
            // Open log file in append mode (create if missing).
            let mut log_file = match std::fs::OpenOptions::new()
                .create(true)
                .append(true)
                .open(&log_path)
            {
                Ok(f) => f,
                Err(e) => {
                    log::error!("Failed to open backend log file {}: {e}", log_path.display());
                    return;
                }
            };

            for line in reader.lines() {
                match line {
                    Ok(text) => {
                        // Write to Tauri console via log crate.
                        if label == "stderr" {
                            log::error!("[backend {label}] {text}");
                        } else {
                            log::info!("[backend {label}] {text}");
                        }
                        // Append to log file.
                        let _ = writeln!(log_file, "[{label}] {text}");
                    }
                    Err(e) => {
                        log::warn!("Error reading backend {label}: {e}");
                        break;
                    }
                }
            }
        });
    }

    if let Some(stdout) = child_stdout {
        spawn_output_reader(stdout, log_path.clone(), "stdout");
    }
    if let Some(stderr) = child_stderr {
        spawn_output_reader(stderr, log_path, "stderr");
    }

    // Stash the child handle so we can kill it later.
    let state = app.state::<BackendProcess>();
    *state.0.lock().unwrap() = Some(child);

    // ---- background health-check (non-blocking, for logging only) ----
    let app_for_health = app.clone();
    tauri::async_runtime::spawn(async move {
        let client = match reqwest::Client::builder()
            .timeout(Duration::from_secs(2))
            .build()
        {
            Ok(c) => c,
            Err(e) => {
                log::error!("Failed to build HTTP client for health check: {e}");
                return;
            }
        };

        let health_url = "http://127.0.0.1:8000/api/v1/health";
        let max_attempts: u32 = 300; // 300 x 500 ms = 150 s
        let interval = Duration::from_millis(500);

        for attempt in 1..=max_attempts {
            match client.get(health_url).send().await {
                Ok(resp) if resp.status().is_success() => {
                    if let Ok(body) = resp.json::<HealthResponse>().await {
                        if body.status == "healthy" {
                            log::info!(
                                "Backend healthy after {attempt} attempts ({:.1}s)",
                                attempt as f64 * 0.5,
                            );
                            let _ = app_for_health.emit("backend-ready", ());
                            return;
                        }
                    }
                }
                Ok(resp) => {
                    log::debug!("Health attempt {attempt}/{max_attempts}: HTTP {}", resp.status());
                }
                Err(e) => {
                    log::debug!("Health attempt {attempt}/{max_attempts}: {e}");
                }
            }
            tokio::time::sleep(interval).await;
        }

        log::error!("Backend did not become healthy within 150s");
        let _ = app_for_health.emit("backend-error", "Backend did not become healthy within 150s".to_string());
    });

    Ok(())
}

/// Kill the backend child process (called on app exit).
fn stop_backend(app: &AppHandle) {
    let state = app.state::<BackendProcess>();
    let mut guard = state.0.lock().unwrap();
    if let Some(mut child) = guard.take() {
        log::info!("Shutting down backend process (pid: {})...", child.id());
        match child.kill() {
            Ok(()) => {
                // Wait briefly for the process to fully exit
                let _ = child.wait();
                log::info!("Backend process terminated.");
            }
            Err(e) => log::error!("Failed to kill backend process: {e}"),
        }
    }
}

/// Tauri command exposed to the frontend: returns whether the backend is reachable.
#[tauri::command]
async fn check_backend_health() -> Result<bool, String> {
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .map_err(|e| format!("{e}"))?;

    match client.get("http://127.0.0.1:8000/api/v1/health").send().await {
        Ok(resp) => Ok(resp.status().is_success()),
        Err(_) => Ok(false),
    }
}

/// Application entry point.
#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    env_logger::Builder::from_env(
        env_logger::Env::default().default_filter_or("info"),
    )
    .init();

    let app = tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .manage(BackendProcess(Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![check_backend_health])
        .setup(|app| {
            let handle = app.handle().clone();

            // Window is visible immediately (configured in tauri.conf.json).
            // The frontend BackendReadinessGate shows a splash screen while
            // the backend starts up.
            tauri::async_runtime::spawn(async move {
                if let Err(e) = start_backend(&handle).await {
                    log::error!("Backend startup failed: {e}");
                    let _ = handle.emit("backend-error", e);
                }
            });

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build Tauri application");

    app.run(|app_handle, event| {
        if let RunEvent::Exit = event {
            stop_backend(app_handle);
        }
    });
}
