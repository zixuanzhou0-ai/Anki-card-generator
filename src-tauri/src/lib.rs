#[cfg_attr(mobile, tauri::mobile_entry_point)]
use std::{
    collections::HashMap,
    env, fs,
    io::{BufRead, BufReader, Read, Write},
    path::{Path, PathBuf},
    process::{Command, Stdio},
    sync::{Arc, Mutex},
    thread,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

use serde::Serialize;
use serde_json::{json, Value};
use tauri::{Emitter, LogicalSize, Manager, Size, State};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;
const WORKER_PROGRESS_PREFIX: &str = "__ANKI_CARD_PROGRESS__";
const WORKER_ERROR_PREFIX: &str = "__ANKI_CARD_ERROR__";
const SECRET_SERVICE: &str = "Anki Card Generator";
const ALLOWED_SECRET_KEYS: &[&str] = &["model_api_key", "tts_api_key"];
const MIN_WINDOW_WIDTH: f64 = 1360.0;
const MIN_WINDOW_HEIGHT: f64 = 1040.0;

#[derive(Clone, Default)]
struct WorkerJobs {
    jobs: Arc<Mutex<HashMap<String, RunningJob>>>,
}

#[derive(Clone)]
struct RunningJob {
    pid: u32,
    cancel_requested: bool,
}

#[derive(Serialize)]
struct WorkerJobStart {
    job_id: String,
}

#[derive(Serialize)]
struct WorkerCancelResult {
    cancelled: bool,
}

fn validate_secret_key(key: &str) -> Result<(), String> {
    if ALLOWED_SECRET_KEYS.contains(&key) {
        Ok(())
    } else {
        Err(format!("不允许保存这个凭据键：{key}"))
    }
}

fn worker_candidates(app: &tauri::AppHandle) -> Vec<PathBuf> {
    let mut candidates = Vec::new();

    // Release builds should only trust files shipped as app resources. Searching the
    // current directory or arbitrary executable ancestors makes it too easy to run a
    // spoofed workers/anki_worker.py when the app is launched from an unsafe folder.
    if let Ok(resource_dir) = app.path().resource_dir() {
        candidates.push(resource_dir.join("workers").join("anki_worker.py"));
    }

    if cfg!(debug_assertions) {
        if let Ok(cwd) = env::current_dir() {
            candidates.push(cwd.join("workers").join("anki_worker.py"));
            candidates.push(cwd.join("..").join("workers").join("anki_worker.py"));
        }
    }

    candidates
}

fn find_worker(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    worker_candidates(app)
        .into_iter()
        .find(|path| path.is_file())
        .ok_or_else(|| "找不到 Python worker：workers/anki_worker.py".to_string())
}

fn worker_command_allowed(command: &str) -> bool {
    matches!(
        command,
        "check_env" | "generate" | "export" | "test_api" | "test_tts" | "verify_anki_import"
    )
}

fn project_root_from_worker(worker: &Path) -> PathBuf {
    worker
        .parent()
        .and_then(|path| path.parent())
        .map(Path::to_path_buf)
        .unwrap_or_else(|| env::current_dir().unwrap_or_default())
}

fn worker_work_dir(app: &tauri::AppHandle, worker: &Path) -> PathBuf {
    if cfg!(debug_assertions) {
        return project_root_from_worker(worker);
    }

    if let Ok(path) = app.path().app_local_data_dir() {
        let _ = fs::create_dir_all(&path);
        return path;
    }

    project_root_from_worker(worker)
}

fn python_candidates(worker: &Path) -> Vec<PathBuf> {
    let mut candidates = Vec::new();

    if let Ok(path) = env::var("ANKI_CARD_GENERATOR_PYTHON") {
        candidates.push(PathBuf::from(path));
    }

    for ancestor in worker.ancestors().take(8) {
        #[cfg(windows)]
        candidates.push(ancestor.join(".venv").join("Scripts").join("python.exe"));

        #[cfg(not(windows))]
        candidates.push(ancestor.join(".venv").join("bin").join("python"));
    }

    candidates.push(PathBuf::from("python"));
    candidates.push(PathBuf::from("python3"));
    candidates
}

fn find_python(worker: &Path) -> PathBuf {
    python_candidates(worker)
        .into_iter()
        .find(|path| path.exists() || path.components().count() == 1)
        .unwrap_or_else(|| PathBuf::from("python"))
}

fn build_worker_command(
    python: PathBuf,
    worker: &Path,
    command: &str,
    work_dir: PathBuf,
) -> Command {
    let mut worker_command = Command::new(python);
    worker_command
        .arg(worker)
        .arg(command)
        .current_dir(work_dir)
        .env("PYTHONIOENCODING", "utf-8")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    #[cfg(windows)]
    worker_command.creation_flags(CREATE_NO_WINDOW);

    worker_command
}

fn make_job_id(command: &str) -> String {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    format!("{command}-{millis}-{}", std::process::id())
}

fn parse_worker_error_line(line: &str) -> Option<Value> {
    line.strip_prefix(WORKER_ERROR_PREFIX)
        .and_then(|payload| serde_json::from_str::<Value>(payload).ok())
}

fn worker_failure_message(stderr: &str, stdout: &str, error_details: Option<&Value>) -> String {
    if let Some(message) = error_details
        .and_then(|details| details.get("message"))
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|message| !message.is_empty())
    {
        return message.to_string();
    }

    let fallback = if stderr.trim().is_empty() {
        stdout.trim()
    } else {
        stderr.trim()
    };
    fallback.to_string()
}

fn apply_worker_error_payload(
    payload: &mut Value,
    error: Option<String>,
    error_details: Option<Value>,
) {
    if let Some(details) = error_details {
        if let Some(message) = details
            .get("message")
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|message| !message.is_empty())
        {
            payload["error"] = json!(message);
        } else if let Some(error) = error {
            payload["error"] = json!(error);
        }

        for key in ["error_code", "stage", "retryable", "fallbacks"] {
            if let Some(value) = details.get(key) {
                payload[key] = value.clone();
            }
        }
    } else if let Some(error) = error {
        payload["error"] = json!(error);
    }
}

fn emit_worker_finished_with_error(
    app: &tauri::AppHandle,
    job_id: &str,
    command: &str,
    ok: bool,
    result: Option<serde_json::Value>,
    error: Option<String>,
    error_details: Option<Value>,
    cancelled: bool,
) {
    let mut payload = json!({
      "job_id": job_id,
      "command": command,
      "ok": ok,
      "cancelled": cancelled,
    });
    if let Some(result) = result {
        payload["result"] = result;
    }
    apply_worker_error_payload(&mut payload, error, error_details);
    let _ = app.emit("worker-finished", payload);
}

fn emit_worker_finished(
    app: &tauri::AppHandle,
    job_id: &str,
    command: &str,
    ok: bool,
    result: Option<serde_json::Value>,
    error: Option<String>,
    cancelled: bool,
) {
    emit_worker_finished_with_error(app, job_id, command, ok, result, error, None, cancelled);
}

fn kill_process_tree(pid: u32) -> Result<(), String> {
    #[cfg(windows)]
    {
        let mut command = Command::new("taskkill");
        command.args(["/PID", &pid.to_string(), "/T", "/F"]);
        command.creation_flags(CREATE_NO_WINDOW);
        let _ = command
            .status()
            .map_err(|err| format!("无法取消任务进程：{err}"))?;
        Ok(())
    }

    #[cfg(not(windows))]
    {
        let _ = Command::new("kill")
            .args(["-TERM", &pid.to_string()])
            .status()
            .map_err(|err| format!("无法取消任务进程：{err}"))?;
        Ok(())
    }
}

#[tauri::command]
fn run_worker(
    app: tauri::AppHandle,
    command: String,
    payload: serde_json::Value,
) -> Result<serde_json::Value, String> {
    if !worker_command_allowed(&command) {
        return Err(format!("不允许的 worker 命令：{command}"));
    }

    let worker = find_worker(&app)?;
    let python = find_python(&worker);
    let input = serde_json::to_vec(&payload).map_err(|err| err.to_string())?;
    let work_dir = worker_work_dir(&app, &worker);

    let mut child = build_worker_command(python, &worker, &command, work_dir)
        .spawn()
        .map_err(|err| format!("无法启动 Python worker：{err}"))?;

    let stderr = child
        .stderr
        .take()
        .ok_or_else(|| "无法读取 worker 错误输出。".to_string())?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "无法读取 worker 输出。".to_string())?;
    let stderr_text = Arc::new(Mutex::new(String::new()));
    let stderr_sink = Arc::clone(&stderr_text);
    let stderr_error = Arc::new(Mutex::new(None::<Value>));
    let stderr_error_sink = Arc::clone(&stderr_error);
    let app_for_progress = app.clone();
    let progress_thread = thread::spawn(move || {
        let reader = BufReader::new(stderr);
        for line in reader.lines().map_while(Result::ok) {
            if let Some(payload) = line.strip_prefix(WORKER_PROGRESS_PREFIX) {
                if let Ok(value) = serde_json::from_str::<serde_json::Value>(payload) {
                    let _ = app_for_progress.emit("worker-progress", value);
                }
            } else if let Some(error) = parse_worker_error_line(&line) {
                if let Ok(mut value) = stderr_error_sink.lock() {
                    *value = Some(error);
                }
            } else if let Ok(mut text) = stderr_sink.lock() {
                text.push_str(&line);
                text.push('\n');
            }
        }
    });

    if let Some(stdin) = child.stdin.as_mut() {
        stdin
            .write_all(&input)
            .map_err(|err| format!("无法写入 worker 输入：{err}"))?;
    }
    drop(child.stdin.take());

    let mut stdout_text = String::new();
    BufReader::new(stdout)
        .read_to_string(&mut stdout_text)
        .map_err(|err| format!("无法读取 worker JSON 输出：{err}"))?;

    let status = child
        .wait()
        .map_err(|err| format!("worker 执行失败：{err}"))?;
    let _ = progress_thread.join();

    if !status.success() {
        let stderr = stderr_text
            .lock()
            .map(|text| text.clone())
            .unwrap_or_default();
        let error_details = stderr_error.lock().ok().and_then(|value| value.clone());
        return Err(worker_failure_message(&stderr, &stdout_text, error_details.as_ref()));
    }

    serde_json::from_str(&stdout_text).map_err(|err| format!("worker 输出不是有效 JSON：{err}"))
}

#[tauri::command]
fn start_worker_job(
    app: tauri::AppHandle,
    jobs: State<WorkerJobs>,
    command: String,
    payload: serde_json::Value,
) -> Result<WorkerJobStart, String> {
    if !worker_command_allowed(&command) {
        return Err(format!("不允许的 worker 命令：{command}"));
    }

    {
        let jobs = jobs
            .jobs
            .lock()
            .map_err(|_| "无法读取当前任务状态。".to_string())?;
        if jobs.values().any(|job| !job.cancel_requested) {
            return Err("已有任务正在运行，请等待完成或先取消当前任务。".to_string());
        }
    }

    let worker = find_worker(&app)?;
    let python = find_python(&worker);
    let input = serde_json::to_vec(&payload).map_err(|err| err.to_string())?;
    let work_dir = worker_work_dir(&app, &worker);
    let job_id = make_job_id(&command);

    let mut child = build_worker_command(python, &worker, &command, work_dir)
        .spawn()
        .map_err(|err| format!("无法启动 Python worker：{err}"))?;
    let pid = child.id();
    let stderr = child
        .stderr
        .take()
        .ok_or_else(|| "无法读取 worker 错误输出。".to_string())?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "无法读取 worker 输出。".to_string())?;

    if let Some(stdin) = child.stdin.as_mut() {
        stdin
            .write_all(&input)
            .map_err(|err| format!("无法写入 worker 输入：{err}"))?;
    }
    drop(child.stdin.take());

    {
        let mut jobs = jobs
            .jobs
            .lock()
            .map_err(|_| "无法记录当前任务状态。".to_string())?;
        jobs.insert(
            job_id.clone(),
            RunningJob {
                pid,
                cancel_requested: false,
            },
        );
    }

    let stderr_text = Arc::new(Mutex::new(String::new()));
    let stderr_sink = Arc::clone(&stderr_text);
    let stderr_error = Arc::new(Mutex::new(None::<Value>));
    let stderr_error_sink = Arc::clone(&stderr_error);
    let app_for_progress = app.clone();
    let progress_job_id = job_id.clone();
    let progress_thread = thread::spawn(move || {
        let reader = BufReader::new(stderr);
        let mut last_emit = Instant::now() - Duration::from_millis(100);
        for line in reader.lines().map_while(Result::ok) {
            if let Some(payload) = line.strip_prefix(WORKER_PROGRESS_PREFIX) {
                if let Ok(mut value) = serde_json::from_str::<serde_json::Value>(payload) {
                    value["job_id"] = json!(progress_job_id);
                    let percent = value
                        .get("percent")
                        .and_then(|percent| percent.as_u64())
                        .unwrap_or_default();
                    if percent >= 100 || last_emit.elapsed() >= Duration::from_millis(100) {
                        let _ = app_for_progress.emit("worker-progress", value);
                        last_emit = Instant::now();
                    }
                }
            } else if let Some(error) = parse_worker_error_line(&line) {
                if let Ok(mut value) = stderr_error_sink.lock() {
                    *value = Some(error);
                }
            } else if let Ok(mut text) = stderr_sink.lock() {
                text.push_str(&line);
                text.push('\n');
            }
        }
    });

    let app_for_finish = app.clone();
    let jobs_for_finish = Arc::clone(&jobs.jobs);
    let finish_job_id = job_id.clone();
    let finish_command = command.clone();
    thread::spawn(move || {
        let mut stdout_text = String::new();
        let read_result = BufReader::new(stdout).read_to_string(&mut stdout_text);
        let wait_result = child.wait();
        let _ = progress_thread.join();
        let cancelled = jobs_for_finish
            .lock()
            .ok()
            .and_then(|mut jobs| jobs.remove(&finish_job_id))
            .map(|job| job.cancel_requested)
            .unwrap_or(false);

        if let Err(err) = read_result {
            emit_worker_finished(
                &app_for_finish,
                &finish_job_id,
                &finish_command,
                false,
                None,
                Some(format!("无法读取 worker JSON 输出：{err}")),
                cancelled,
            );
            return;
        }

        match wait_result {
            Ok(status) if status.success() && !cancelled => {
                match serde_json::from_str::<serde_json::Value>(&stdout_text) {
                    Ok(result) => emit_worker_finished(
                        &app_for_finish,
                        &finish_job_id,
                        &finish_command,
                        true,
                        Some(result),
                        None,
                        false,
                    ),
                    Err(err) => emit_worker_finished(
                        &app_for_finish,
                        &finish_job_id,
                        &finish_command,
                        false,
                        None,
                        Some(format!("worker 输出不是有效 JSON：{err}")),
                        false,
                    ),
                }
            }
            Ok(_) if cancelled => emit_worker_finished(
                &app_for_finish,
                &finish_job_id,
                &finish_command,
                false,
                None,
                Some("任务已取消。".to_string()),
                true,
            ),
            Ok(_) => {
                let stderr = stderr_text
                    .lock()
                    .map(|text| text.clone())
                    .unwrap_or_default();
                let error_details = stderr_error.lock().ok().and_then(|value| value.clone());
                let message = worker_failure_message(&stderr, &stdout_text, error_details.as_ref());
                emit_worker_finished_with_error(
                    &app_for_finish,
                    &finish_job_id,
                    &finish_command,
                    false,
                    None,
                    Some(message),
                    error_details,
                    false,
                );
            }
            Err(err) => emit_worker_finished(
                &app_for_finish,
                &finish_job_id,
                &finish_command,
                false,
                None,
                Some(format!("worker 执行失败：{err}")),
                cancelled,
            ),
        }
    });

    Ok(WorkerJobStart { job_id })
}

#[tauri::command]
fn cancel_worker_job(
    jobs: State<WorkerJobs>,
    job_id: String,
) -> Result<WorkerCancelResult, String> {
    let pid = {
        let mut jobs = jobs
            .jobs
            .lock()
            .map_err(|_| "无法读取当前任务状态。".to_string())?;
        if let Some(job) = jobs.get_mut(&job_id) {
            job.cancel_requested = true;
            Some(job.pid)
        } else {
            None
        }
    };

    if let Some(pid) = pid {
        kill_process_tree(pid)?;
        Ok(WorkerCancelResult { cancelled: true })
    } else {
        Ok(WorkerCancelResult { cancelled: false })
    }
}

fn anki_candidates() -> Vec<PathBuf> {
    let mut candidates = Vec::new();

    if let Ok(path) = env::var("ANKI_EXE") {
        candidates.push(PathBuf::from(path));
    }
    if let Ok(local_app_data) = env::var("LOCALAPPDATA") {
        let base = PathBuf::from(local_app_data);
        candidates.push(
            base.join("AnkiProgramFiles")
                .join(".venv")
                .join("Scripts")
                .join("anki.exe"),
        );
        candidates.push(base.join("Programs").join("Anki").join("anki.exe"));
    }
    candidates.push(PathBuf::from(r"C:\Program Files\Anki\anki.exe"));
    candidates.push(PathBuf::from(r"C:\Program Files (x86)\Anki\anki.exe"));

    candidates
}

fn find_anki() -> Result<PathBuf, String> {
    anki_candidates()
        .into_iter()
        .find(|path| path.exists())
        .ok_or_else(|| {
            "找不到 Anki。请确认已安装 Anki，或设置 ANKI_EXE 指向 anki.exe。".to_string()
        })
}

fn path_is_within(target: &Path, root: &Path) -> bool {
    let Ok(target) = target.canonicalize() else {
        return false;
    };
    let Ok(root) = root.canonicalize() else {
        return false;
    };
    target == root || target.starts_with(root)
}

fn reveal_path_allowed(app: &tauri::AppHandle, target: &Path) -> bool {
    if let Ok(app_data) = app.path().app_local_data_dir() {
        if path_is_within(target, &app_data) {
            return true;
        }
    }

    if let Ok(cwd) = env::current_dir() {
        for root in [cwd.join("projects"), cwd.join("release"), cwd.join("anki_live_e2e")] {
            if root.exists() && path_is_within(target, &root) {
                return true;
            }
        }

        if cfg!(debug_assertions) && path_is_within(target, &cwd) {
            return true;
        }
    }

    false
}

#[tauri::command]
fn open_anki_import(apkg_path: String) -> Result<(), String> {
    let apkg = PathBuf::from(apkg_path);
    if !apkg.exists() {
        return Err(format!("apkg 文件不存在：{}", apkg.display()));
    }
    if !apkg.is_file() || apkg.extension().and_then(|value| value.to_str()) != Some("apkg") {
        return Err("只能导入 .apkg 文件。".to_string());
    }

    let anki = find_anki()?;
    Command::new(anki)
        .arg(apkg)
        .spawn()
        .map_err(|err| format!("无法启动 Anki：{err}"))?;
    Ok(())
}

#[tauri::command]
fn reveal_path(app: tauri::AppHandle, path: String) -> Result<(), String> {
    let target = PathBuf::from(path);
    if !target.exists() {
        return Err(format!("路径不存在：{}", target.display()));
    }
    if !reveal_path_allowed(&app, &target) {
        return Err("只能打开本应用生成或管理的输出路径。".to_string());
    }

    #[cfg(target_os = "windows")]
    {
        let arg = if target.is_file() {
            format!("/select,{}", target.display())
        } else {
            target.display().to_string()
        };
        Command::new("explorer")
            .arg(arg)
            .spawn()
            .map_err(|err| format!("无法打开资源管理器：{err}"))?;
    }

    #[cfg(not(target_os = "windows"))]
    {
        Command::new("open")
            .arg(if target.is_file() {
                target.parent().unwrap_or(&target)
            } else {
                &target
            })
            .spawn()
            .map_err(|err| format!("无法打开路径：{err}"))?;
    }

    Ok(())
}

#[tauri::command]
fn save_secret(key: String, value: String) -> Result<(), String> {
    validate_secret_key(&key)?;
    keyring::Entry::new(SECRET_SERVICE, &key)
        .map_err(|err| format!("无法打开系统凭据：{err}"))?
        .set_password(&value)
        .map_err(|err| format!("无法保存系统凭据：{err}"))?;
    Ok(())
}

#[tauri::command]
fn load_secret(key: String) -> Result<Option<String>, String> {
    validate_secret_key(&key)?;
    match keyring::Entry::new(SECRET_SERVICE, &key)
        .map_err(|err| format!("无法打开系统凭据：{err}"))?
        .get_password()
    {
        Ok(value) => Ok(Some(value)),
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(err) => Err(format!("无法读取系统凭据：{err}")),
    }
}

#[tauri::command]
fn delete_secret(key: String) -> Result<(), String> {
    validate_secret_key(&key)?;
    match keyring::Entry::new(SECRET_SERVICE, &key)
        .map_err(|err| format!("无法打开系统凭据：{err}"))?
        .delete_credential()
    {
        Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
        Err(err) => Err(format!("无法删除系统凭据：{err}")),
    }
}

pub fn run() {
    tauri::Builder::default()
        .manage(WorkerJobs::default())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            run_worker,
            start_worker_job,
            cancel_worker_job,
            reveal_path,
            open_anki_import,
            save_secret,
            load_secret,
            delete_secret
        ])
        .setup(|app| {
            if let Some(window) = app.get_webview_window("main") {
                window.set_min_size(Some(Size::Logical(LogicalSize {
                    width: MIN_WINDOW_WIDTH,
                    height: MIN_WINDOW_HEIGHT,
                })))?;
            }

            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
