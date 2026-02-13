use std::sync::Mutex;
use std::time::Duration;

use tauri::{AppHandle, Emitter, Manager, RunEvent};
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

/// State container for the backend sidecar process.
/// Wrapped in Mutex so it can be safely accessed from multiple async contexts.
struct BackendProcess(Mutex<Option<CommandChild>>);

/// Subset of the backend health check JSON response.
#[derive(serde::Deserialize)]
struct HealthResponse {
    status: String,
}

/// Spawn the Python backend sidecar and poll until it reports healthy.
async fn start_backend(app: &AppHandle) -> Result<(), String> {
    log::info!("Starting Teletraan backend sidecar...");

    let shell = app.shell();

    // Build and spawn the sidecar command.
    // "teletraan-backend" resolves to src-tauri/binaries/teletraan-backend-<target_triple>.
    let (mut rx, child) = shell
        .sidecar("teletraan-backend")
        .map_err(|e| format!("Failed to create sidecar command: {e}"))?
        .args(["--host", "127.0.0.1", "--port", "8000"])
        .spawn()
        .map_err(|e| format!("Failed to spawn backend sidecar: {e}"))?;

    // Stash the child handle so we can kill it later.
    let state = app.state::<BackendProcess>();
    *state.0.lock().unwrap() = Some(child);

    // Forward stdout / stderr from the sidecar into the host log.
    let app_for_log = app.clone();
    tauri::async_runtime::spawn(async move {
        use tauri_plugin_shell::process::CommandEvent;
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(bytes) => {
                    let line = String::from_utf8_lossy(&bytes);
                    log::info!("[backend] {}", line.trim());
                }
                CommandEvent::Stderr(bytes) => {
                    let line = String::from_utf8_lossy(&bytes);
                    log::warn!("[backend] {}", line.trim());
                }
                CommandEvent::Terminated(payload) => {
                    log::warn!(
                        "[backend] Process terminated  code={:?}  signal={:?}",
                        payload.code,
                        payload.signal,
                    );
                    let _ = app_for_log.emit("backend-terminated", ());
                    break;
                }
                CommandEvent::Error(err) => {
                    log::error!("[backend] Error: {err}");
                }
                _ => {}
            }
        }
    });

    // ---- health-check polling ----
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .map_err(|e| format!("Failed to build HTTP client: {e}"))?;

    let health_url = "http://127.0.0.1:8000/api/v1/health";
    let max_attempts: u32 = 60; // 60 x 500 ms = 30 s
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
                        let _ = app.emit("backend-ready", ());
                        return Ok(());
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

    Err(format!(
        "Backend did not become healthy within {:.0}s",
        max_attempts as f64 * 0.5,
    ))
}

/// Kill the backend sidecar (called on app exit).
fn stop_backend(app: &AppHandle) {
    let state = app.state::<BackendProcess>();
    if let Some(child) = state.0.lock().unwrap().take() {
        log::info!("Shutting down backend sidecar...");
        match child.kill() {
            Ok(()) => log::info!("Backend sidecar terminated."),
            Err(e) => log::error!("Failed to kill backend sidecar: {e}"),
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
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_opener::init())
        .manage(BackendProcess(Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![check_backend_health])
        .setup(|app| {
            let handle = app.handle().clone();

            tauri::async_runtime::spawn(async move {
                match start_backend(&handle).await {
                    Ok(()) => {
                        log::info!("Backend ready -- showing main window");
                        if let Some(win) = handle.get_webview_window("main") {
                            let _ = win.show();
                        }
                    }
                    Err(e) => {
                        log::error!("Backend startup failed: {e}");
                        // Show window anyway so the user sees an error state.
                        if let Some(win) = handle.get_webview_window("main") {
                            let _ = win.show();
                        }
                        let _ = handle.emit("backend-error", e);
                    }
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
