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
use windows_sys::Win32::{
    Foundation::LocalFree,
    Security::Cryptography::{
        CryptProtectData, CryptUnprotectData, CRYPTPROTECT_UI_FORBIDDEN, CRYPT_INTEGER_BLOB,
    },
};

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;
const WORKER_PROGRESS_PREFIX: &str = "__ANKI_CARD_PROGRESS__";
const WORKER_ERROR_PREFIX: &str = "__ANKI_CARD_ERROR__";
const SECRET_SERVICE: &str = "Anki Card Generator";
const SECRET_FALLBACK_DIR: &str = "com.ankicard.generator";
const ALLOWED_SECRET_KEYS: &[&str] = &["model_api_key", "tts_api_key"];
const ALLOWED_SECRET_KEY_PREFIXES: &[&str] = &["model_profile_key_", "tts_profile_key_"];
const MIN_WINDOW_WIDTH: f64 = 1180.0;
const MIN_WINDOW_HEIGHT: f64 = 780.0;

fn hide_console_window(command: &mut Command) {
    #[cfg(windows)]
    {
        command.creation_flags(CREATE_NO_WINDOW);
    }
}

#[derive(Clone, Default)]
struct WorkerJobs {
    jobs: Arc<Mutex<HashMap<String, RunningJob>>>,
}

#[derive(Clone)]
struct RunningJob {
    pid: u32,
    cancel_requested: bool,
    failure_message: Option<String>,
}

#[derive(Serialize)]
struct WorkerJobStart {
    job_id: String,
}

#[derive(Serialize)]
struct WorkerCancelResult {
    cancelled: bool,
}

#[derive(Serialize)]
struct BootstrapRepairAction {
    id: String,
    label: String,
    status: String,
    detail: String,
    command: Option<String>,
    next_step: Option<String>,
}

#[derive(Serialize)]
struct BootstrapRepairResult {
    ok: bool,
    target: String,
    summary: String,
    actions: Vec<BootstrapRepairAction>,
}

fn validate_secret_key(key: &str) -> Result<(), String> {
    let known_key = ALLOWED_SECRET_KEYS.contains(&key);
    let known_prefix = ALLOWED_SECRET_KEY_PREFIXES
        .iter()
        .any(|prefix| key.starts_with(prefix));
    let safe_chars = key
        .chars()
        .all(|value| value.is_ascii_alphanumeric() || value == '_' || value == '-');
    if known_key || (known_prefix && safe_chars && key.len() <= 96) {
        return Ok(());
    }
    Err(format!("不允许保存这个凭据键：{key}"))
}

fn save_keyring_secret(key: &str, value: &str) -> Result<(), String> {
    let entry = keyring::Entry::new(SECRET_SERVICE, key)
        .map_err(|err| format!("无法打开系统凭据：{err}"))?;
    entry
        .set_password(value)
        .map_err(|err| format!("无法保存系统凭据：{err}"))?;
    match entry.get_password() {
        Ok(loaded) if loaded == value => Ok(()),
        Ok(_) => Err("系统凭据写入后校验失败。".to_string()),
        Err(err) => Err(format!("系统凭据写入后无法读回：{err}")),
    }
}

fn load_keyring_secret(key: &str) -> Result<Option<String>, String> {
    match keyring::Entry::new(SECRET_SERVICE, key)
        .map_err(|err| format!("无法打开系统凭据：{err}"))?
        .get_password()
    {
        Ok(value) => Ok(Some(value)),
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(err) => Err(format!("无法读取系统凭据：{err}")),
    }
}

fn delete_keyring_secret(key: &str) -> Result<(), String> {
    match keyring::Entry::new(SECRET_SERVICE, key)
        .map_err(|err| format!("无法打开系统凭据：{err}"))?
        .delete_credential()
    {
        Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
        Err(err) => Err(format!("无法删除系统凭据：{err}")),
    }
}

fn secret_fallback_path(key: &str) -> Result<PathBuf, String> {
    validate_secret_key(key)?;
    let root = env::var_os("LOCALAPPDATA")
        .or_else(|| env::var_os("APPDATA"))
        .map(PathBuf::from)
        .ok_or_else(|| "无法定位当前用户 AppData 目录。".to_string())?;
    Ok(root
        .join(SECRET_FALLBACK_DIR)
        .join("secrets")
        .join(format!("{key}.dpapi")))
}

fn encode_hex(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut result = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        result.push(HEX[(byte >> 4) as usize] as char);
        result.push(HEX[(byte & 0x0f) as usize] as char);
    }
    result
}

fn decode_hex(text: &str) -> Result<Vec<u8>, String> {
    let trimmed = text.trim();
    if trimmed.len() % 2 != 0 {
        return Err("加密凭据文件格式不完整。".to_string());
    }
    let mut bytes = Vec::with_capacity(trimmed.len() / 2);
    for index in (0..trimmed.len()).step_by(2) {
        let byte = u8::from_str_radix(&trimmed[index..index + 2], 16)
            .map_err(|err| format!("加密凭据文件格式无效：{err}"))?;
        bytes.push(byte);
    }
    Ok(bytes)
}

#[cfg(windows)]
fn protect_secret(value: &str) -> Result<Vec<u8>, String> {
    let bytes = value.as_bytes();
    let input = CRYPT_INTEGER_BLOB {
        cbData: bytes.len() as u32,
        pbData: bytes.as_ptr() as *mut u8,
    };
    let mut output = CRYPT_INTEGER_BLOB {
        cbData: 0,
        pbData: std::ptr::null_mut(),
    };
    let ok = unsafe {
        CryptProtectData(
            &input,
            std::ptr::null(),
            std::ptr::null(),
            std::ptr::null(),
            std::ptr::null(),
            CRYPTPROTECT_UI_FORBIDDEN,
            &mut output,
        )
    };
    if ok == 0 {
        return Err(format!(
            "DPAPI 加密失败：{}",
            std::io::Error::last_os_error()
        ));
    }
    let encrypted =
        unsafe { std::slice::from_raw_parts(output.pbData, output.cbData as usize).to_vec() };
    unsafe {
        let _ = LocalFree(output.pbData.cast());
    }
    Ok(encrypted)
}

#[cfg(windows)]
fn unprotect_secret(bytes: &[u8]) -> Result<String, String> {
    let input = CRYPT_INTEGER_BLOB {
        cbData: bytes.len() as u32,
        pbData: bytes.as_ptr() as *mut u8,
    };
    let mut output = CRYPT_INTEGER_BLOB {
        cbData: 0,
        pbData: std::ptr::null_mut(),
    };
    let ok = unsafe {
        CryptUnprotectData(
            &input,
            std::ptr::null_mut(),
            std::ptr::null(),
            std::ptr::null(),
            std::ptr::null(),
            CRYPTPROTECT_UI_FORBIDDEN,
            &mut output,
        )
    };
    if ok == 0 {
        return Err(format!(
            "DPAPI 解密失败：{}",
            std::io::Error::last_os_error()
        ));
    }
    let decrypted =
        unsafe { std::slice::from_raw_parts(output.pbData, output.cbData as usize).to_vec() };
    unsafe {
        let _ = LocalFree(output.pbData.cast());
    }
    String::from_utf8(decrypted).map_err(|err| format!("DPAPI 凭据不是有效 UTF-8：{err}"))
}

#[cfg(not(windows))]
fn protect_secret(_value: &str) -> Result<Vec<u8>, String> {
    Err("当前平台不支持 DPAPI 凭据兜底。".to_string())
}

#[cfg(not(windows))]
fn unprotect_secret(_bytes: &[u8]) -> Result<String, String> {
    Err("当前平台不支持 DPAPI 凭据兜底。".to_string())
}

fn save_secret_fallback(key: &str, value: &str) -> Result<(), String> {
    let path = secret_fallback_path(key)?;
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|err| format!("无法创建凭据目录：{err}"))?;
    }
    let encrypted = protect_secret(value)?;
    fs::write(path, encode_hex(&encrypted)).map_err(|err| format!("无法写入 DPAPI 凭据：{err}"))
}

fn load_secret_fallback(key: &str) -> Result<Option<String>, String> {
    let path = secret_fallback_path(key)?;
    if !path.exists() {
        return Ok(None);
    }
    let raw = fs::read_to_string(path).map_err(|err| format!("无法读取 DPAPI 凭据：{err}"))?;
    let encrypted = decode_hex(&raw)?;
    unprotect_secret(&encrypted).map(Some)
}

fn delete_secret_fallback(key: &str) -> Result<(), String> {
    let path = secret_fallback_path(key)?;
    match fs::remove_file(path) {
        Ok(()) => Ok(()),
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(err) => Err(format!("无法删除 DPAPI 凭据：{err}")),
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
        "check_env"
            | "repair_env"
            | "generate"
            | "export"
            | "test_api"
            | "test_tts"
            | "verify_anki_import"
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

    #[cfg(windows)]
    {
        if let Ok(local_app_data) = env::var("LOCALAPPDATA") {
            let base = PathBuf::from(local_app_data).join("Programs").join("Python");
            candidates.push(base.join("Python312").join("python.exe"));
            candidates.push(base.join("Python313").join("python.exe"));
        }
        if let Ok(program_files) = env::var("ProgramFiles") {
            let base = PathBuf::from(program_files);
            candidates.push(base.join("Python312").join("python.exe"));
            candidates.push(base.join("Python313").join("python.exe"));
        }
    }

    candidates.push(PathBuf::from("python"));
    candidates.push(PathBuf::from("python3"));
    candidates
}

fn command_first_line(mut command: Command) -> Option<String> {
    hide_console_window(&mut command);
    command
        .output()
        .ok()
        .filter(|output| output.status.success())
        .and_then(|output| {
            let stdout_text = String::from_utf8_lossy(&output.stdout);
            if let Some(line) = stdout_text.lines().map(str::trim).find(|value| !value.is_empty()) {
                return Some(line.to_string());
            }
            let stderr_text = String::from_utf8_lossy(&output.stderr);
            stderr_text
                .lines()
                .map(str::trim)
                .find(|value| !value.is_empty())
                .map(str::to_string)
        })
}

fn python_version(python: &Path) -> Option<String> {
    let mut command = Command::new(python);
    command.arg("--version");
    command_first_line(command)
}

fn find_available_python(worker: &Path) -> Option<(PathBuf, String)> {
    python_candidates(worker)
        .into_iter()
        .find_map(|path| python_version(&path).map(|version| (path, version)))
}

fn find_python(worker: &Path) -> PathBuf {
    find_available_python(worker)
        .map(|(path, _)| path)
        .or_else(|| {
            python_candidates(worker)
                .into_iter()
                .find(|path| path.exists() || path.components().count() == 1)
        })
        .unwrap_or_else(|| PathBuf::from("python"))
}

fn command_path(name: &str) -> Option<String> {
    #[cfg(windows)]
    let command = {
        let mut command = Command::new("where");
        command.arg(name);
        command
    };

    #[cfg(not(windows))]
    let command = {
        let mut command = Command::new("which");
        command.arg(name);
        command
    };

    command_first_line(command)
}

fn command_version(name: &str, args: &[&str]) -> Option<String> {
    let mut command = Command::new(name);
    command.args(args);
    command_first_line(command)
}

fn native_status_item(id: &str, label: &str, status: &str, detail: String, fix: &str) -> Value {
    json!({
        "id": id,
        "label": label,
        "status": status,
        "detail": detail,
        "fix": fix,
    })
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

    hide_console_window(&mut worker_command);

    worker_command
}

fn make_job_id(command: &str) -> String {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    format!("{command}-{millis}-{}", std::process::id())
}

fn worker_idle_timeout(command: &str) -> Duration {
    match command {
        "generate" | "export" => Duration::from_secs(300),
        "test_api" | "test_tts" | "verify_anki_import" => Duration::from_secs(120),
        _ => Duration::from_secs(180),
    }
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
        hide_console_window(&mut command);
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
        return Err(worker_failure_message(
            &stderr,
            &stdout_text,
            error_details.as_ref(),
        ));
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
                failure_message: None,
            },
        );
    }

    let stderr_text = Arc::new(Mutex::new(String::new()));
    let stderr_sink = Arc::clone(&stderr_text);
    let stderr_error = Arc::new(Mutex::new(None::<Value>));
    let stderr_error_sink = Arc::clone(&stderr_error);
    let last_progress = Arc::new(Mutex::new(Instant::now()));
    let last_progress_sink = Arc::clone(&last_progress);
    let app_for_progress = app.clone();
    let progress_job_id = job_id.clone();
    let progress_thread = thread::spawn(move || {
        let reader = BufReader::new(stderr);
        let mut last_emit = Instant::now() - Duration::from_millis(100);
        for line in reader.lines().map_while(Result::ok) {
            if let Some(payload) = line.strip_prefix(WORKER_PROGRESS_PREFIX) {
                if let Ok(mut seen_at) = last_progress_sink.lock() {
                    *seen_at = Instant::now();
                }
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

    let watchdog_jobs = Arc::clone(&jobs.jobs);
    let watchdog_job_id = job_id.clone();
    let watchdog_command = command.clone();
    let watchdog_last_progress = Arc::clone(&last_progress);
    thread::spawn(move || {
        let timeout = worker_idle_timeout(&watchdog_command);
        loop {
            thread::sleep(Duration::from_secs(5));
            let should_stop = watchdog_jobs
                .lock()
                .ok()
                .and_then(|jobs| jobs.get(&watchdog_job_id).cloned())
                .map(|job| job.cancel_requested || job.failure_message.is_some())
                .unwrap_or(true);
            if should_stop {
                break;
            }
            let idle_for = watchdog_last_progress
                .lock()
                .map(|seen_at| seen_at.elapsed())
                .unwrap_or_default();
            if idle_for >= timeout {
                let message = format!(
                    "worker 超过 {} 秒没有任何进度更新，已自动终止。通常是网络/API 请求卡住；请稍后重试，或检查代理、Base URL 和模型服务状态。",
                    timeout.as_secs()
                );
                if let Ok(mut jobs) = watchdog_jobs.lock() {
                    if let Some(job) = jobs.get_mut(&watchdog_job_id) {
                        job.failure_message = Some(message);
                    }
                }
                let _ = kill_process_tree(pid);
                break;
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
        let job_state = jobs_for_finish
            .lock()
            .ok()
            .and_then(|mut jobs| jobs.remove(&finish_job_id));
        let cancelled = job_state
            .as_ref()
            .map(|job| job.cancel_requested)
            .unwrap_or(false);
        let failure_message = job_state.and_then(|job| job.failure_message);

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
            Ok(_) if failure_message.is_some() => emit_worker_finished(
                &app_for_finish,
                &finish_job_id,
                &finish_command,
                false,
                None,
                failure_message,
                false,
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

fn process_running(image_name: &str) -> bool {
    #[cfg(windows)]
    {
        let mut command = Command::new("tasklist");
        command.args(["/FI", &format!("IMAGENAME eq {image_name}")]);
        hide_console_window(&mut command);
        return command
            .output()
            .ok()
            .filter(|output| output.status.success())
            .map(|output| {
                String::from_utf8_lossy(&output.stdout)
                    .to_lowercase()
                    .contains(&image_name.to_lowercase())
            })
            .unwrap_or(false);
    }

    #[cfg(not(windows))]
    {
        let mut command = Command::new("pgrep");
        command.args(["-f", image_name]);
        return command
            .output()
            .ok()
            .filter(|output| output.status.success())
            .map(|output| !output.stdout.is_empty())
            .unwrap_or(false);
    }
}

fn bootstrap_worker_path(app: &tauri::AppHandle) -> PathBuf {
    find_worker(app).unwrap_or_else(|_| {
        env::current_dir()
            .unwrap_or_default()
            .join("workers")
            .join("anki_worker.py")
    })
}

#[tauri::command]
fn check_bootstrap_env(app: tauri::AppHandle) -> Result<Value, String> {
    let worker = bootstrap_worker_path(&app);
    let python = find_available_python(&worker);
    let ffmpeg_path = command_path("ffmpeg").unwrap_or_default();
    let ffmpeg_version = if ffmpeg_path.is_empty() {
        String::new()
    } else {
        command_version("ffmpeg", &["-version"]).unwrap_or_default()
    };
    let js_runtime = if command_path("deno").is_some() {
        "deno"
    } else if command_path("node").is_some() {
        "node"
    } else {
        ""
    };
    let anki_path = find_anki().ok();
    let anki_running = process_running("anki.exe") || process_running("anki");
    let python_status = python
        .as_ref()
        .map(|(path, version)| {
            native_status_item(
                "python",
                "Python 运行环境",
                "ok",
                format!("{version} · {}", path.display()),
                "",
            )
        })
        .unwrap_or_else(|| {
            native_status_item(
                "python",
                "Python 运行环境",
                "blocked",
                "没有找到可用 Python；worker 无法启动。".to_string(),
                "点击一键修复安装推荐 Python 3.12。",
            )
        });

    let anki_detail = match &anki_path {
        Some(path) if anki_running => format!("已安装并正在运行：{}", path.display()),
        Some(path) => format!("已安装但未打开：{}", path.display()),
        None => "未找到 Anki 桌面端。".to_string(),
    };

    let status_items = vec![
        python_status,
        native_status_item(
            "venv",
            "项目私有 venv",
            if python.is_some() { "action" } else { "blocked" },
            if python.is_some() {
                "Python 可用；点击一键修复后会创建项目 .venv 并安装依赖。".to_string()
            } else {
                "需要先安装 Python，才能创建项目 .venv。".to_string()
            },
            "点击一键修复。",
        ),
        native_status_item(
            "ffmpeg",
            "FFmpeg 视频切片",
            if ffmpeg_path.is_empty() { "blocked" } else { "ok" },
            if ffmpeg_path.is_empty() {
                "未在 PATH 找到 ffmpeg；本地视频导出会失败。".to_string()
            } else {
                ffmpeg_version
            },
            "点击一键修复尝试通过 winget 安装 FFmpeg。",
        ),
        native_status_item(
            "genanki",
            "genanki APKG 导出",
            if python.is_some() { "action" } else { "blocked" },
            "需要 Python worker 运行后安装/检查。".to_string(),
            "点击一键修复安装 Python 依赖。",
        ),
        native_status_item(
            "yt_dlp",
            "yt-dlp URL 导入",
            if python.is_some() { "action" } else { "blocked" },
            "需要 Python worker 运行后安装/检查。".to_string(),
            "点击一键修复安装 Python 依赖。",
        ),
        native_status_item(
            "js_runtime",
            "Deno / Node challenge solver",
            if js_runtime.is_empty() { "action" } else { "ok" },
            if js_runtime.is_empty() {
                "YouTube n challenge 可能失败。".to_string()
            } else {
                js_runtime.to_string()
            },
            "点击一键修复尝试安装 Deno。",
        ),
        native_status_item(
            "anki",
            "Anki 桌面端",
            if anki_path.is_some() { "ok" } else { "blocked" },
            anki_detail,
            "点击一键修复尝试安装 Anki。",
        ),
        native_status_item(
            "anki_connect",
            "AnkiConnect 导入核验",
            if anki_path.is_some() { "action" } else { "blocked" },
            if anki_path.is_some() {
                "需要打开 Anki 并安装/启用 AnkiConnect 插件。".to_string()
            } else {
                "需要先安装 Anki 桌面端。".to_string()
            },
            "插件代码 2055492159。",
        ),
    ];

    let (python_version, python_executable) = python
        .map(|(path, version)| {
            (
                version.trim_start_matches("Python ").to_string(),
                path.display().to_string(),
            )
        })
        .unwrap_or_else(|| (String::new(), String::new()));

    Ok(json!({
        "python": python_version,
        "python_executable": python_executable,
        "venv": false,
        "ffmpeg": !ffmpeg_path.is_empty(),
        "ffmpeg_path": ffmpeg_path,
        "ffmpeg_version": status_items.get(2).and_then(|item| item.get("detail")).and_then(Value::as_str).unwrap_or(""),
        "genanki": false,
        "yt_dlp": false,
        "yt_dlp_version": "",
        "yt_dlp_js_runtime": js_runtime,
        "anki_installed": anki_path.is_some(),
        "anki_path": anki_path.map(|path| path.display().to_string()).unwrap_or_default(),
        "anki_running": anki_running,
        "anki_connect": false,
        "anki_connect_detail": "需要 Python worker 或 AnkiConnect 端口检查。",
        "packages": {},
        "status_items": status_items,
        "worker": worker.display().to_string(),
    }))
}

fn summarize_native_output(output: &std::process::Output) -> String {
    let text = [
        String::from_utf8_lossy(&output.stdout).to_string(),
        String::from_utf8_lossy(&output.stderr).to_string(),
    ]
    .join("\n")
    .replace("\r\n", "\n")
    .replace('\r', "\n");
    let lines: Vec<&str> = text.lines().map(str::trim).filter(|line| !line.is_empty()).collect();
    if lines.is_empty() {
        return format!("退出码 {}", output.status.code().unwrap_or(-1));
    }
    lines
        .iter()
        .rev()
        .take(8)
        .copied()
        .collect::<Vec<&str>>()
        .into_iter()
        .rev()
        .collect::<Vec<&str>>()
        .join("\n")
}

fn native_action(
    id: &str,
    label: &str,
    status: &str,
    detail: String,
    command: Option<String>,
    next_step: Option<String>,
) -> BootstrapRepairAction {
    BootstrapRepairAction {
        id: id.to_string(),
        label: label.to_string(),
        status: status.to_string(),
        detail,
        command,
        next_step,
    }
}

#[tauri::command]
fn repair_bootstrap_env(app: tauri::AppHandle, target: String) -> Result<BootstrapRepairResult, String> {
    let normalized_target = if ["all", "python_runtime"].contains(&target.as_str()) {
        target
    } else {
        "python_runtime".to_string()
    };
    let worker = bootstrap_worker_path(&app);
    let mut actions = Vec::new();

    if normalized_target == "all" || normalized_target == "python_runtime" {
        if let Some((path, version)) = find_available_python(&worker) {
            actions.push(native_action(
                "python_runtime",
                "Python 运行环境",
                "skipped",
                format!("已找到 {version}：{}", path.display()),
                None,
                None,
            ));
        } else if let Some(winget) = command_path("winget") {
            let command_args = [
                "install",
                "--id",
                "Python.Python.3.12",
                "-e",
                "--accept-package-agreements",
                "--accept-source-agreements",
            ];
            let command_text = format!("{} {}", winget, command_args.join(" "));
            let mut command = Command::new(&winget);
            command.args(command_args);
            hide_console_window(&mut command);
            match command.output() {
                Ok(output) => {
                    let installed = find_available_python(&worker);
                    let success = output.status.success() && installed.is_some();
                    let detail = installed
                        .map(|(path, version)| {
                            format!("已安装并找到 {version}：{}", path.display())
                        })
                        .unwrap_or_else(|| summarize_native_output(&output));
                    actions.push(native_action(
                        "python_runtime",
                        "通过 winget 安装推荐 Python 3.12",
                        if success { "success" } else if output.status.success() { "manual" } else { "failed" },
                        detail,
                        Some(command_text),
                        if success {
                            None
                        } else {
                            Some("安装后如果仍未识别，请重启应用；也可以设置 ANKI_CARD_GENERATOR_PYTHON 指向 python.exe。".to_string())
                        },
                    ));
                }
                Err(err) => actions.push(native_action(
                    "python_runtime",
                    "通过 winget 安装推荐 Python 3.12",
                    "failed",
                    format!("无法执行 winget：{err}"),
                    Some(command_text),
                    Some("请手动安装 Python 3.12，或设置 ANKI_CARD_GENERATOR_PYTHON 指向 python.exe。".to_string()),
                )),
            }
        } else {
            actions.push(native_action(
                "python_runtime",
                "安装推荐 Python 3.12",
                "manual",
                "本机没有 winget，无法自动安装 Python。".to_string(),
                None,
                Some("请从 https://www.python.org/downloads/windows/ 安装 Python 3.12，并勾选 Add python.exe to PATH。".to_string()),
            ));
        }
    }

    let failed = actions.iter().filter(|action| action.status == "failed").count();
    let manual = actions.iter().filter(|action| action.status == "manual").count();
    Ok(BootstrapRepairResult {
        ok: failed == 0,
        target: normalized_target,
        summary: format!(
            "原生修复执行 {} 个步骤；失败 {} 个，需手动处理 {} 个。",
            actions.len(),
            failed,
            manual
        ),
        actions,
    })
}

fn clean_user_path(value: &str) -> String {
    value
        .trim()
        .trim_matches('"')
        .trim_matches('\'')
        .to_string()
}

fn compact_match_text(value: &str) -> String {
    value
        .to_ascii_lowercase()
        .chars()
        .filter(|ch| ch.is_ascii_alphanumeric())
        .collect()
}

fn language_code(language: &str) -> &str {
    match language.to_ascii_lowercase().as_str() {
        "english" | "en" => "en",
        "chinese" | "zh" | "zh-cn" => "zh",
        "japanese" | "ja" => "ja",
        "korean" | "ko" => "ko",
        "spanish" | "es" => "es",
        "french" | "fr" => "fr",
        "german" | "de" => "de",
        _ => "en",
    }
}

fn subtitle_language_markers(language: &str) -> Vec<String> {
    let code = language_code(language);
    let mut markers = vec![
        format!(".{code}"),
        format!("-{code}"),
        format!("_{code}"),
        format!(" {code}"),
        format!(".{code}-"),
        format!(".{code}_"),
    ];
    if code == "en" {
        markers.extend(
            ["english", ".eng", "-eng", "_eng", " eng"]
                .iter()
                .map(|value| value.to_string()),
        );
    }
    markers
}

#[tauri::command]
fn suggest_subtitle_path(video_path: String, language: String) -> Result<Option<String>, String> {
    let video = PathBuf::from(clean_user_path(&video_path));
    let Some(directory) = video.parent() else {
        return Ok(None);
    };
    if !directory.exists() {
        return Ok(None);
    }

    let mut subtitles = Vec::new();
    for entry in fs::read_dir(directory).map_err(|err| format!("无法读取视频目录：{err}"))?
    {
        let path = entry
            .map_err(|err| format!("无法读取视频目录项：{err}"))?
            .path();
        let extension = path
            .extension()
            .and_then(|value| value.to_str())
            .unwrap_or_default()
            .to_ascii_lowercase();
        if path.is_file() && matches!(extension.as_str(), "srt" | "vtt") {
            subtitles.push(path);
        }
    }
    if subtitles.is_empty() {
        return Ok(None);
    }

    let video_stem = video
        .file_stem()
        .and_then(|value| value.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase();
    let compact_video = compact_match_text(&video_stem);
    let markers = subtitle_language_markers(&language);
    let single_subtitle = subtitles.len() == 1;

    let mut scored = subtitles
        .into_iter()
        .filter_map(|path| {
            let stem = path.file_stem()?.to_str()?.to_ascii_lowercase();
            let compact_stem = compact_match_text(&stem);
            let has_language_marker = markers.iter().any(|marker| stem.contains(marker));
            let bucket = if compact_stem == compact_video {
                0
            } else if !compact_video.is_empty()
                && compact_stem.starts_with(&compact_video)
                && has_language_marker
            {
                1
            } else if !compact_video.is_empty()
                && compact_stem.contains(&compact_video)
                && has_language_marker
            {
                2
            } else if !compact_video.is_empty() && compact_stem.starts_with(&compact_video) {
                3
            } else if single_subtitle {
                4
            } else {
                9
            };
            if bucket >= 9 {
                return None;
            }
            let size = path.metadata().map(|meta| meta.len()).unwrap_or_default();
            let name = path
                .file_name()
                .and_then(|value| value.to_str())
                .unwrap_or_default()
                .to_ascii_lowercase();
            Some((bucket, size, name, path))
        })
        .collect::<Vec<_>>();

    scored.sort_by(|left, right| {
        left.0
            .cmp(&right.0)
            .then_with(|| right.1.cmp(&left.1))
            .then_with(|| left.2.cmp(&right.2))
    });

    Ok(scored
        .first()
        .map(|(_, _, _, path)| path.display().to_string()))
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
        for root in [
            cwd.join("projects"),
            cwd.join("release"),
            cwd.join("anki_live_e2e"),
        ] {
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
    let mut command = Command::new(anki);
    command.arg(apkg);
    hide_console_window(&mut command);
    command
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
        let mut command = Command::new("explorer");
        command.arg(arg);
        hide_console_window(&mut command);
        command
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
    let keyring_result = save_keyring_secret(&key, &value);
    let fallback_result = save_secret_fallback(&key, &value);
    if keyring_result.is_ok() || fallback_result.is_ok() {
        Ok(())
    } else {
        Err(format!(
            "{}；{}",
            keyring_result.unwrap_err(),
            fallback_result.unwrap_err()
        ))
    }
}

#[tauri::command]
fn load_secret(key: String) -> Result<Option<String>, String> {
    validate_secret_key(&key)?;
    match load_keyring_secret(&key) {
        Ok(Some(value)) => Ok(Some(value)),
        Ok(None) => load_secret_fallback(&key),
        Err(keyring_error) => match load_secret_fallback(&key) {
            Ok(Some(value)) => Ok(Some(value)),
            Ok(None) => Err(keyring_error),
            Err(fallback_error) => Err(format!("{keyring_error}；{fallback_error}")),
        },
    }
}

#[tauri::command]
fn delete_secret(key: String) -> Result<(), String> {
    validate_secret_key(&key)?;
    let keyring_result = delete_keyring_secret(&key);
    let fallback_result = delete_secret_fallback(&key);
    if keyring_result.is_ok() || fallback_result.is_ok() {
        Ok(())
    } else {
        Err(format!(
            "{}；{}",
            keyring_result.unwrap_err(),
            fallback_result.unwrap_err()
        ))
    }
}

pub fn run() {
    tauri::Builder::default()
        .manage(WorkerJobs::default())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            run_worker,
            check_bootstrap_env,
            repair_bootstrap_env,
            start_worker_job,
            cancel_worker_job,
            suggest_subtitle_path,
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    #[ignore = "writes a temporary credential to the local OS keyring"]
    fn secret_keyring_round_trip() {
        let key = "model_api_key".to_string();
        let value = format!("codex-test-{}", std::process::id());

        save_secret(key.clone(), value.clone()).expect("save test credential");
        let loaded = load_secret(key.clone()).expect("load test credential");
        delete_secret(key).expect("delete test credential");

        assert_eq!(loaded, Some(value));
    }
}
