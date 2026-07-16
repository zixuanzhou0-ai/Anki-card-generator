#[cfg_attr(mobile, tauri::mobile_entry_point)]
use std::{
    collections::{HashMap, VecDeque},
    env, fs,
    io::{BufRead, BufReader, Read, Write},
    net::TcpStream,
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::{
        atomic::{AtomicBool, AtomicU64, Ordering},
        Arc, Mutex,
    },
    thread,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tauri::{Emitter, LogicalSize, Manager, Size, State, WebviewUrl, WebviewWindowBuilder};

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
#[cfg(windows)]
const CREATE_NEW_PROCESS_GROUP: u32 = 0x00000200;
#[cfg(windows)]
const DETACHED_PROCESS: u32 = 0x00000008;
const WORKER_PROGRESS_PREFIX: &str = "__ANKI_CARD_PROGRESS__";
const WORKER_ERROR_PREFIX: &str = "__ANKI_CARD_ERROR__";
const SECRET_SERVICE: &str = "Anki Card Generator";
const SECRET_FALLBACK_DIR: &str = "com.ankicard.generator";
const ALLOWED_SECRET_KEYS: &[&str] = &["model_api_key", "tts_api_key"];
const ALLOWED_SECRET_KEY_PREFIXES: &[&str] = &["model_profile_key_", "tts_profile_key_"];
const MIN_WINDOW_WIDTH: f64 = 1180.0;
const MIN_WINDOW_HEIGHT: f64 = 780.0;
const WORKER_INLINE_RESULT_LIMIT_BYTES: usize = 64 * 1024;
const GENERATE_WORKER_PAYLOAD_LIMIT_BYTES: usize = 1_500_000;
const COMPLETED_WORKER_JOB_LIMIT: usize = 20;
const DIRECTORY_LIST_MAX_FILES: usize = 2000;
const DIRECTORY_LIST_MAX_DEPTH: usize = 4;
const WORKFLOW_CHECKPOINT_FILE: &str = "workflow-checkpoint-v1.json";
const WORKFLOW_CHECKPOINT_BACKUP_FILE: &str = "workflow-checkpoint-v1.json.bak";
const WORKFLOW_CHECKPOINT_MAX_BYTES: u64 = 4 * 1024 * 1024;
const WORKFLOW_ARTIFACT_MAX_BYTES: u64 = 128 * 1024 * 1024;
const WORKER_TASK_SNAPSHOT_SCHEMA_VERSION: u8 = 1;
const WORKER_TASK_SNAPSHOT_MAX_BYTES: u64 = 256 * 1024;
static WORKFLOW_FILE_SEQUENCE: AtomicU64 = AtomicU64::new(0);
const HERMES_PROXY_HOST: &str = "127.0.0.1";
const HERMES_PROXY_PORT: u16 = 8645;
const HERMES_PROXY_BASE_URL: &str = "http://127.0.0.1:8645/v1";
const HERMES_PROXY_MODEL: &str = "grok-4.5";
const SUPPORTED_PREVIEW_VIDEO_EXTENSIONS: &[&str] = &["mp4", "mkv", "webm", "mov", "m4v", "avi"];
const SUPPORTED_BULK_FILE_EXTENSIONS: &[&str] = &[
    "mp4", "mkv", "webm", "mov", "m4v", "srt", "vtt", "txt", "md", "markdown", "docx", "epub",
    "pdf", "azw", "azw3", "mobi",
];
const SENSITIVE_DIRECTORY_NAMES: &[&str] = &[
    "windows",
    "program files",
    "program files (x86)",
    "programdata",
    "$recycle.bin",
    "system volume information",
];

fn hide_console_window(command: &mut Command) {
    #[cfg(windows)]
    {
        command.creation_flags(CREATE_NO_WINDOW);
    }
}

fn detach_gui_process(command: &mut Command) {
    #[cfg(windows)]
    {
        command.creation_flags(DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP);
    }
}

#[derive(Clone, Default)]
struct WorkerJobs {
    jobs: Arc<Mutex<HashMap<String, RunningJob>>>,
    completed: Arc<Mutex<CompletedWorkerJobs>>,
}

#[derive(Default)]
struct WindowCloseGuard {
    allow_next_close: AtomicBool,
}

#[derive(Default)]
struct HermesProxyRuntime {
    child: Mutex<Option<Child>>,
}

impl Drop for HermesProxyRuntime {
    fn drop(&mut self) {
        let _ = stop_managed_hermes(self);
    }
}

#[derive(Serialize)]
struct HermesProxyStatus {
    state: String,
    message: String,
    base_url: String,
    model: String,
    executable: Option<String>,
    managed: bool,
    authenticated: bool,
}

#[derive(Clone)]
struct RunningJob {
    pid: u32,
    command: String,
    cancel_requested: bool,
    failure_message: Option<String>,
    started_at_ms: u64,
    updated_at_ms: u64,
    progress: WorkerTaskProgressSnapshot,
    input_fingerprint: String,
}

#[derive(Clone, Default)]
struct CompletedWorkerJobs {
    entries: HashMap<String, CompletedWorkerJob>,
    order: VecDeque<String>,
}

#[derive(Clone)]
struct CompletedWorkerJob {
    status: WorkerJobStatus,
    snapshot: WorkerTaskSnapshot,
    result_path: Option<PathBuf>,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct WorkerTaskProgressSnapshot {
    phase: String,
    phase_label: String,
    phase_percent: Option<f64>,
    overall_percent: Option<f64>,
    completed_items: Option<u64>,
    total_items: Option<u64>,
    completed_batches: Option<u64>,
    total_batches: Option<u64>,
    message: String,
    last_progress_at: u64,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct WorkerTaskFailureSnapshot {
    code: String,
    message: String,
    retryable: bool,
    phase: Option<String>,
    detail: Option<String>,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct WorkerTaskSnapshot {
    schema_version: u8,
    id: String,
    command: String,
    state: String,
    started_at: u64,
    updated_at: u64,
    progress: WorkerTaskProgressSnapshot,
    cancellable: bool,
    input_fingerprint: String,
    result_ref: Option<String>,
    error: Option<WorkerTaskFailureSnapshot>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct RecoverableWorkerTasksResult {
    tasks: Vec<WorkerTaskSnapshot>,
    errors: Vec<String>,
}

#[derive(Clone, Serialize)]
struct WorkerJobStatus {
    job_id: String,
    command: String,
    ok: bool,
    cancelled: bool,
    result_ref: Option<String>,
    result_size_bytes: Option<u64>,
    result_summary: Option<Value>,
    error: Option<String>,
    error_code: Option<String>,
    stage: Option<String>,
    retryable: Option<bool>,
    fallbacks: Option<Vec<String>>,
    details: Option<Value>,
    finished_at_ms: u64,
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
#[serde(rename_all = "camelCase")]
struct WorkerForceCancelResult {
    found: bool,
    cancelled: bool,
    state: String,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct WorkerTaskResultAcknowledgement {
    acknowledged: bool,
    state: Option<String>,
}
#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct RecoveryFileInspectionError {
    code: String,
    message: String,
    retryable: bool,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct RecoveryFileInspection {
    ok: bool,
    exists: bool,
    is_file: bool,
    size: Option<u64>,
    modified_at_ms: Option<u64>,
    sha256: Option<String>,
    error: Option<RecoveryFileInspectionError>,
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

    if cfg!(debug_assertions) {
        if let Ok(cwd) = env::current_dir() {
            candidates.push(cwd.join("workers").join("anki_worker.py"));
            candidates.push(cwd.join("..").join("workers").join("anki_worker.py"));
        }
    }

    // Release builds should only trust files shipped as app resources. Searching the
    // current directory or arbitrary executable ancestors makes it too easy to run a
    // spoofed workers/anki_worker.py when the app is launched from an unsafe folder.
    // In dev, keep this as a fallback only: using the bundled target/debug worker
    // makes runtime caches land under src-tauri/target, which can destabilize the
    // Tauri dev watcher during large generation jobs.
    if let Ok(resource_dir) = app.path().resource_dir() {
        candidates.push(resource_dir.join("workers").join("anki_worker.py"));
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
            | "extract_learning_points"
            | "generate_cards_from_learning_points"
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

    let allow_custom_python =
        cfg!(debug_assertions) || env::var("ANKI_ALLOW_CUSTOM_PYTHON").ok().as_deref() == Some("1");
    if allow_custom_python {
        if let Ok(path) = env::var("ANKI_CARD_GENERATOR_PYTHON") {
            candidates.push(PathBuf::from(path));
        }
    } else if env::var("ANKI_CARD_GENERATOR_PYTHON").is_ok() {
        log::warn!(
            "Ignoring ANKI_CARD_GENERATOR_PYTHON in release mode; set ANKI_ALLOW_CUSTOM_PYTHON=1 to opt in."
        );
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
            let base = PathBuf::from(local_app_data)
                .join("Programs")
                .join("Python");
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
            if let Some(line) = stdout_text
                .lines()
                .map(str::trim)
                .find(|value| !value.is_empty())
            {
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

fn hermes_candidates() -> Vec<PathBuf> {
    let mut candidates = Vec::new();
    if let Ok(path) = env::var("HERMES_EXE") {
        push_unique_path(&mut candidates, PathBuf::from(path));
    }
    if let Some(path) = command_path("hermes") {
        push_unique_path(&mut candidates, PathBuf::from(path));
    }
    if let Ok(local_app_data) = env::var("LOCALAPPDATA") {
        push_unique_path(
            &mut candidates,
            PathBuf::from(local_app_data)
                .join("hermes")
                .join("hermes-agent")
                .join("venv")
                .join("Scripts")
                .join("hermes.exe"),
        );
    }
    candidates
}

fn find_hermes() -> Option<PathBuf> {
    hermes_candidates().into_iter().find(|path| path.exists())
}

fn parse_hermes_health_response(response: &str) -> Option<bool> {
    let (headers, body) = response.split_once("\r\n\r\n")?;
    if !headers.lines().next()?.contains(" 200 ") {
        return None;
    }
    let payload: Value = serde_json::from_str(body.trim()).ok()?;
    if payload.get("status").and_then(Value::as_str) != Some("ok") {
        return None;
    }
    let upstream = payload
        .get("upstream")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_ascii_lowercase();
    if !upstream.contains("xai") && !upstream.contains("grok") {
        return None;
    }
    Some(
        payload
            .get("authenticated")
            .and_then(Value::as_bool)
            .unwrap_or(false),
    )
}

enum HermesHealthProbe {
    NotListening,
    Hermes { authenticated: bool },
    OtherService,
}

fn probe_hermes_health() -> HermesHealthProbe {
    let address = format!("{HERMES_PROXY_HOST}:{HERMES_PROXY_PORT}");
    let Ok(socket_address) = address.parse() else {
        return HermesHealthProbe::NotListening;
    };
    let Ok(mut stream) = TcpStream::connect_timeout(&socket_address, Duration::from_millis(350))
    else {
        return HermesHealthProbe::NotListening;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(700)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(700)));
    let request = format!(
        "GET /health HTTP/1.1\r\nHost: {HERMES_PROXY_HOST}:{HERMES_PROXY_PORT}\r\nConnection: close\r\n\r\n"
    );
    if stream.write_all(request.as_bytes()).is_err() {
        return HermesHealthProbe::OtherService;
    }
    let mut response = String::new();
    if stream.read_to_string(&mut response).is_err() {
        return HermesHealthProbe::OtherService;
    }
    match parse_hermes_health_response(&response) {
        Some(authenticated) => HermesHealthProbe::Hermes { authenticated },
        None => HermesHealthProbe::OtherService,
    }
}

fn hermes_xai_auth_ready(executable: &Path) -> bool {
    let mut command = Command::new(executable);
    command.args(["proxy", "status"]);
    hide_console_window(&mut command);
    command
        .output()
        .ok()
        .filter(|output| output.status.success())
        .map(|output| {
            let text = format!(
                "{}\n{}",
                String::from_utf8_lossy(&output.stdout),
                String::from_utf8_lossy(&output.stderr)
            )
            .to_ascii_lowercase();
            text.lines()
                .any(|line| line.contains("[xai") && line.contains("ready"))
        })
        .unwrap_or(false)
}

fn hermes_managed_running(runtime: &HermesProxyRuntime) -> bool {
    let Ok(mut guard) = runtime.child.lock() else {
        return false;
    };
    let Some(child) = guard.as_mut() else {
        return false;
    };
    match child.try_wait() {
        Ok(None) => true,
        _ => {
            guard.take();
            false
        }
    }
}

fn stop_managed_hermes(runtime: &HermesProxyRuntime) -> Result<bool, String> {
    let mut guard = runtime
        .child
        .lock()
        .map_err(|_| "Hermes 代理状态锁不可用。".to_string())?;
    let Some(mut child) = guard.take() else {
        return Ok(false);
    };
    let pid = child.id();
    let tree_result = kill_process_tree(pid);
    if tree_result.is_err() {
        let _ = child.kill();
    }
    let _ = child.wait();
    tree_result.map(|_| true)
}

fn normalize_http_proxy_url(value: &str) -> Option<String> {
    let trimmed = value.trim();
    if trimmed.is_empty() || trimmed.chars().any(char::is_whitespace) {
        return None;
    }
    let lower = trimmed.to_ascii_lowercase();
    if lower.starts_with("http://") || lower.starts_with("https://") {
        return Some(trimmed.to_string());
    }
    if trimmed.contains("://") || !trimmed.contains(':') {
        return None;
    }
    Some(format!("http://{trimmed}"))
}

fn select_http_proxy_server(value: &str) -> Option<String> {
    let trimmed = value.trim();
    if !trimmed.contains('=') {
        return normalize_http_proxy_url(trimmed);
    }

    for wanted in ["https", "http"] {
        for entry in trimmed.split(';') {
            let Some((scheme, address)) = entry.split_once('=') else {
                continue;
            };
            if scheme.trim().eq_ignore_ascii_case(wanted) {
                if let Some(proxy) = normalize_http_proxy_url(address) {
                    return Some(proxy);
                }
            }
        }
    }
    None
}

#[cfg(windows)]
fn read_wininet_proxy_value(name: &str) -> Option<String> {
    let mut command = Command::new("reg.exe");
    command.args([
        "query",
        r"HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        "/v",
        name,
    ]);
    hide_console_window(&mut command);
    let output = command.output().ok()?.stdout;
    let text = String::from_utf8_lossy(&output);
    text.lines().find_map(|line| {
        let fields = line.split_whitespace().collect::<Vec<_>>();
        if fields
            .first()
            .is_some_and(|field| field.eq_ignore_ascii_case(name))
        {
            fields.last().map(|value| (*value).to_string())
        } else {
            None
        }
    })
}

#[cfg(windows)]
fn windows_system_proxy_url() -> Option<String> {
    let enabled = read_wininet_proxy_value("ProxyEnable")?;
    if enabled != "0x1" && enabled != "1" {
        return None;
    }
    select_http_proxy_server(&read_wininet_proxy_value("ProxyServer")?)
}

fn hermes_upstream_proxy_url() -> Option<String> {
    #[cfg(windows)]
    if let Some(proxy) = windows_system_proxy_url() {
        return Some(proxy);
    }

    ["HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"]
        .into_iter()
        .find_map(|name| env::var(name).ok())
        .and_then(|value| select_http_proxy_server(&value))
}

fn hermes_proxy_compat_dir(app: &tauri::AppHandle) -> Option<PathBuf> {
    let mut candidates = Vec::new();
    if let Ok(resource_dir) = app.path().resource_dir() {
        candidates.push(
            resource_dir
                .join("workers")
                .join("acg")
                .join("hermes_proxy_compat"),
        );
    }
    if let Ok(current_dir) = env::current_dir() {
        candidates.push(
            current_dir
                .join("workers")
                .join("acg")
                .join("hermes_proxy_compat"),
        );
    }
    candidates.into_iter().find(|path| path.is_dir())
}

fn configure_hermes_network_compat(command: &mut Command, app: &tauri::AppHandle) {
    let (Some(proxy), Some(compat_dir)) =
        (hermes_upstream_proxy_url(), hermes_proxy_compat_dir(app))
    else {
        return;
    };

    let mut python_paths = vec![compat_dir];
    if let Some(existing) = env::var_os("PYTHONPATH") {
        python_paths.extend(env::split_paths(&existing));
    }
    if let Ok(joined) = env::join_paths(python_paths) {
        command.env("PYTHONPATH", joined);
    }
    command.env("ANKI_CARD_HERMES_TRUST_ENV", "1");
    command.env("HTTPS_PROXY", &proxy);
    command.env("HTTP_PROXY", &proxy);
    command.env("https_proxy", &proxy);
    command.env("http_proxy", proxy);
}

fn hermes_proxy_status(runtime: &HermesProxyRuntime) -> HermesProxyStatus {
    let executable = find_hermes();
    let managed = hermes_managed_running(runtime);
    let executable_text = executable
        .as_ref()
        .map(|path| path.to_string_lossy().to_string());
    let status = |state: &str, message: &str, authenticated: bool| HermesProxyStatus {
        state: state.to_string(),
        message: message.to_string(),
        base_url: HERMES_PROXY_BASE_URL.to_string(),
        model: HERMES_PROXY_MODEL.to_string(),
        executable: executable_text.clone(),
        managed,
        authenticated,
    };

    let Some(executable) = executable else {
        return status(
            "missing",
            "未找到 Hermes。请先安装 Hermes，或设置 HERMES_EXE 指向 hermes.exe。",
            false,
        );
    };

    match probe_hermes_health() {
        HermesHealthProbe::Hermes {
            authenticated: true,
        } => status(
            "ready",
            if managed {
                "Hermes Grok 4.5 本机代理已由应用启动并通过 OAuth 健康检查。"
            } else {
                "检测到已运行的 Hermes Grok 4.5 本机代理，应用将直接复用。"
            },
            true,
        ),
        HermesHealthProbe::Hermes {
            authenticated: false,
        } => status(
            "oauth_unready",
            "Hermes 代理已运行，但 xAI OAuth 未就绪。请运行 hermes auth add xai-oauth。",
            false,
        ),
        HermesHealthProbe::OtherService => status(
            "port_conflict",
            "本机 8645 端口已被非 Hermes 服务占用；应用不会结束该进程。",
            false,
        ),
        HermesHealthProbe::NotListening if hermes_xai_auth_ready(&executable) => status(
            "stopped",
            "Hermes 与 xAI OAuth 已就绪，代理尚未启动。",
            true,
        ),
        HermesHealthProbe::NotListening => status(
            "oauth_unready",
            "Hermes 已安装，但 xAI OAuth 未就绪。请运行 hermes auth add xai-oauth。",
            false,
        ),
    }
}

#[tauri::command]
fn check_hermes_proxy(state: State<'_, HermesProxyRuntime>) -> Result<HermesProxyStatus, String> {
    Ok(hermes_proxy_status(&state))
}

#[tauri::command]
fn start_hermes_proxy(
    app: tauri::AppHandle,
    state: State<'_, HermesProxyRuntime>,
) -> Result<HermesProxyStatus, String> {
    let current = hermes_proxy_status(&state);
    if current.state == "ready"
        || current.state == "missing"
        || current.state == "oauth_unready"
        || current.state == "port_conflict"
    {
        return Ok(current);
    }

    let executable = find_hermes().ok_or_else(|| "未找到 Hermes 可执行文件。".to_string())?;
    let mut command = Command::new(&executable);
    command.args([
        "proxy",
        "start",
        "--provider",
        "xai",
        "--host",
        HERMES_PROXY_HOST,
        "--port",
        &HERMES_PROXY_PORT.to_string(),
    ]);
    configure_hermes_network_compat(&mut command, &app);
    command
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    hide_console_window(&mut command);
    let mut child = command
        .spawn()
        .map_err(|error| format!("Hermes 代理启动失败：{error}"))?;

    let deadline = Instant::now() + Duration::from_secs(20);
    while Instant::now() < deadline {
        if let Ok(Some(exit_status)) = child.try_wait() {
            return Ok(HermesProxyStatus {
                state: "error".to_string(),
                message: format!("Hermes 代理启动后提前退出：{exit_status}"),
                base_url: HERMES_PROXY_BASE_URL.to_string(),
                model: HERMES_PROXY_MODEL.to_string(),
                executable: Some(executable.to_string_lossy().to_string()),
                managed: false,
                authenticated: false,
            });
        }
        if matches!(
            probe_hermes_health(),
            HermesHealthProbe::Hermes {
                authenticated: true
            }
        ) {
            let mut guard = state
                .child
                .lock()
                .map_err(|_| "Hermes 代理状态锁不可用。".to_string())?;
            *guard = Some(child);
            drop(guard);
            return Ok(hermes_proxy_status(&state));
        }
        thread::sleep(Duration::from_millis(150));
    }

    let _ = child.kill();
    let _ = child.wait();
    Ok(HermesProxyStatus {
        state: "error".to_string(),
        message: "Hermes 代理在 20 秒内没有通过健康检查，已停止本次启动的进程。".to_string(),
        base_url: HERMES_PROXY_BASE_URL.to_string(),
        model: HERMES_PROXY_MODEL.to_string(),
        executable: Some(executable.to_string_lossy().to_string()),
        managed: false,
        authenticated: false,
    })
}

#[tauri::command]
fn stop_owned_hermes_proxy(
    state: State<'_, HermesProxyRuntime>,
) -> Result<HermesProxyStatus, String> {
    stop_managed_hermes(&state)?;
    Ok(hermes_proxy_status(&state))
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
        "check_env" => Duration::from_secs(60),
        "repair_env" => Duration::from_secs(15 * 60),
        "test_api" | "test_tts" | "verify_anki_import" => Duration::from_secs(120),
        "extract_learning_points" => Duration::from_secs(300),
        "generate_cards_from_learning_points" => Duration::from_secs(420),
        "generate" | "export" => Duration::from_secs(600),
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

        for key in ["error_code", "stage", "retryable", "fallbacks", "details"] {
            if let Some(value) = details.get(key) {
                payload[key] = value.clone();
            }
        }
    } else if let Some(error) = error {
        payload["error"] = json!(error);
    }
}

fn now_unix_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
        .min(u128::from(u64::MAX)) as u64
}

fn workspace_root_for_startup_diagnostics() -> PathBuf {
    let mut candidates = Vec::new();
    if let Ok(current_dir) = env::current_dir() {
        candidates.push(current_dir);
    }
    if let Ok(current_exe) = env::current_exe() {
        if let Some(parent) = current_exe.parent() {
            candidates.push(parent.to_path_buf());
        }
    }

    for candidate in candidates {
        for ancestor in candidate.ancestors() {
            if ancestor.join("package.json").is_file() && ancestor.join("src-tauri").is_dir() {
                return ancestor.to_path_buf();
            }
        }
    }

    env::current_dir().unwrap_or_else(|_| env::temp_dir())
}

fn write_startup_diagnostic(payload: Value) {
    let path = workspace_root_for_startup_diagnostics().join(".tauri-startup-current.json");
    if let Ok(content) = serde_json::to_vec_pretty(&payload) {
        let _ = fs::write(path, content);
    }
}

fn write_workspace_diagnostic_file(file_name: &str, payload: &Value) {
    let path = workspace_root_for_startup_diagnostics().join(file_name);
    if let Ok(content) = serde_json::to_vec_pretty(payload) {
        let _ = fs::write(path, content);
    }
}

fn append_workspace_text_file(file_name: &str, line: &str) {
    let path = workspace_root_for_startup_diagnostics().join(file_name);
    if let Ok(mut file) = fs::OpenOptions::new().create(true).append(true).open(path) {
        let _ = writeln!(file, "{line}");
    }
}

fn reset_workspace_text_file(file_name: &str) {
    let path = workspace_root_for_startup_diagnostics().join(file_name);
    let _ = fs::write(path, "");
}

fn write_app_local_diagnostic_file(app: &tauri::AppHandle, file_name: &str, payload: &Value) {
    if let Ok(dir) = app.path().app_local_data_dir() {
        let _ = fs::create_dir_all(&dir);
        if let Ok(content) = serde_json::to_vec_pretty(payload) {
            let _ = fs::write(dir.join(file_name), content);
        }
    }
}

fn write_dual_diagnostic_file(app: &tauri::AppHandle, file_name: &str, payload: Value) {
    write_workspace_diagnostic_file(file_name, &payload);
    write_app_local_diagnostic_file(app, file_name.trim_start_matches('.'), &payload);
}

fn append_app_local_text_file(app: &tauri::AppHandle, file_name: &str, line: &str) {
    if let Ok(dir) = app.path().app_local_data_dir() {
        let _ = fs::create_dir_all(&dir);
        if let Ok(mut file) = fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(dir.join(file_name))
        {
            let _ = writeln!(file, "{line}");
        }
    }
}

fn append_dual_text_file(app: &tauri::AppHandle, file_name: &str, line: &str) {
    append_workspace_text_file(file_name, line);
    append_app_local_text_file(app, file_name.trim_start_matches('.'), line);
}

fn reset_app_local_text_file(app: &tauri::AppHandle, file_name: &str) {
    if let Ok(dir) = app.path().app_local_data_dir() {
        let _ = fs::create_dir_all(&dir);
        let _ = fs::write(dir.join(file_name), "");
    }
}

fn reset_dual_text_file(app: &tauri::AppHandle, file_name: &str) {
    reset_workspace_text_file(file_name);
    reset_app_local_text_file(app, file_name.trim_start_matches('.'));
}

fn worker_payload_summary(command: &str, payload: &Value, input_size_bytes: usize) -> Value {
    let api = payload.get("api_config").and_then(Value::as_object);
    let selected_count = payload
        .get("selected_learning_point_ids")
        .and_then(Value::as_array)
        .map(Vec::len)
        .unwrap_or_default();
    let learning_point_count = payload
        .get("learning_points")
        .and_then(Value::as_array)
        .map(Vec::len)
        .unwrap_or_default();
    let source_sentence_count = payload
        .get("source_sentences")
        .and_then(Value::as_array)
        .map(Vec::len)
        .unwrap_or_default();
    json!({
        "command": command,
        "input_size_bytes": input_size_bytes,
        "selected_learning_point_count": selected_count,
        "learning_point_count": learning_point_count,
        "source_sentence_count": source_sentence_count,
        "source_mode": payload.get("source_mode").and_then(Value::as_str).unwrap_or_default(),
        "url_import_mode": payload.get("url_import_mode").and_then(Value::as_str).unwrap_or_default(),
        "has_source_url": payload.get("source_url").and_then(Value::as_str).map(|value| !value.is_empty()).unwrap_or(false),
        "has_video_path": payload.get("video_path").and_then(Value::as_str).map(|value| !value.is_empty()).unwrap_or(false),
        "has_subtitle_path": payload.get("subtitle_path").and_then(Value::as_str).map(|value| !value.is_empty()).unwrap_or(false),
        "provider": api
            .and_then(|api| api.get("provider"))
            .and_then(Value::as_str)
            .unwrap_or_default(),
        "model": api
            .and_then(|api| api.get("model"))
            .and_then(Value::as_str)
            .unwrap_or_default(),
    })
}

fn write_worker_job_breadcrumb(app: &tauri::AppHandle, payload: Value) {
    write_dual_diagnostic_file(app, ".tauri-job-current.json", payload);
}

fn unit_result_to_json<E: std::fmt::Display>(result: &Result<(), E>) -> Value {
    match result {
        Ok(()) => json!({
            "ok": true,
        }),
        Err(err) => json!({
            "ok": false,
            "error": err.to_string(),
        }),
    }
}

fn window_state_to_json(window: &tauri::WebviewWindow) -> Value {
    let inner_size = match window.inner_size() {
        Ok(size) => json!({
            "ok": true,
            "width": size.width,
            "height": size.height,
        }),
        Err(err) => json!({
            "ok": false,
            "error": err.to_string(),
        }),
    };
    let outer_position = match window.outer_position() {
        Ok(position) => json!({
            "ok": true,
            "x": position.x,
            "y": position.y,
        }),
        Err(err) => json!({
            "ok": false,
            "error": err.to_string(),
        }),
    };
    let visible = match window.is_visible() {
        Ok(value) => json!({
            "ok": true,
            "value": value,
        }),
        Err(err) => json!({
            "ok": false,
            "error": err.to_string(),
        }),
    };
    let minimized = match window.is_minimized() {
        Ok(value) => json!({
            "ok": true,
            "value": value,
        }),
        Err(err) => json!({
            "ok": false,
            "error": err.to_string(),
        }),
    };
    let focused = match window.is_focused() {
        Ok(value) => json!({
            "ok": true,
            "value": value,
        }),
        Err(err) => json!({
            "ok": false,
            "error": err.to_string(),
        }),
    };

    json!({
        "inner_size": inner_size,
        "outer_position": outer_position,
        "visible": visible,
        "minimized": minimized,
        "focused": focused,
    })
}

fn write_window_lifecycle_diagnostic(
    app: &tauri::AppHandle,
    window: &tauri::WebviewWindow,
    event_name: &str,
    event_debug: String,
) {
    write_dual_diagnostic_file(
        app,
        ".tauri-window-current.json",
        json!({
            "schema_version": 1,
            "source": "src-tauri/src/lib.rs window lifecycle",
            "recorded_at_ms": now_unix_ms(),
            "pid": std::process::id(),
            "window": {
                "label": window.label(),
                "title": window.title().unwrap_or_default(),
                "state": window_state_to_json(window),
            },
            "event": {
                "name": event_name,
                "debug": event_debug,
            },
        }),
    );
}

fn worker_job_result_dir(app: &tauri::AppHandle) -> PathBuf {
    app.path()
        .app_local_data_dir()
        .unwrap_or_else(|_| env::temp_dir().join(SECRET_FALLBACK_DIR))
        .join("worker-results")
}

fn worker_input_fingerprint(payload_summary: &Value) -> String {
    let bytes = serde_json::to_vec(payload_summary).unwrap_or_default();
    let mut hash = 0xcbf29ce484222325_u64;
    for byte in bytes {
        hash ^= u64::from(byte);
        hash = hash.wrapping_mul(0x100000001b3);
    }
    format!("summary-fnv1a64:{hash:016x}")
}

fn validated_worker_input_fingerprint(provided: Option<&str>, payload_summary: &Value) -> String {
    let fallback = || worker_input_fingerprint(payload_summary);
    let Some(candidate) = provided else {
        return fallback();
    };
    if !(8..=128).contains(&candidate.len())
        || !candidate
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b':' | b'.'))
    {
        return fallback();
    }
    candidate.to_string()
}

fn worker_task_initial_progress(started_at: u64) -> WorkerTaskProgressSnapshot {
    WorkerTaskProgressSnapshot {
        phase: "starting".to_string(),
        phase_label: "正在准备任务".to_string(),
        phase_percent: None,
        overall_percent: None,
        completed_items: None,
        total_items: None,
        completed_batches: None,
        total_batches: None,
        message: "任务已开始".to_string(),
        last_progress_at: started_at,
    }
}

fn worker_progress_number(value: &Value, keys: &[&str]) -> Option<f64> {
    keys.iter()
        .find_map(|key| value.get(*key).and_then(Value::as_f64))
        .filter(|number| number.is_finite())
}

fn worker_progress_count(value: &Value, keys: &[&str]) -> Option<u64> {
    keys.iter()
        .find_map(|key| value.get(*key).and_then(Value::as_u64))
}

fn update_worker_task_progress(
    current: &WorkerTaskProgressSnapshot,
    value: &Value,
    updated_at: u64,
) -> WorkerTaskProgressSnapshot {
    let phase = payload_string(value, "phase")
        .or_else(|| payload_string(value, "stage"))
        .unwrap_or_else(|| current.phase.clone());
    let phase_label = payload_string(value, "stage_label")
        .or_else(|| payload_string(value, "phase_label"))
        .unwrap_or_else(|| current.phase_label.clone());
    let phase_percent = worker_progress_number(value, &["phase_percent", "percent"])
        .map(|number| number.clamp(0.0, 100.0))
        .or(current.phase_percent);
    let candidate_overall = worker_progress_number(value, &["overall_percent", "percent"])
        .map(|number| number.clamp(0.0, 99.0));
    let overall_percent = match (current.overall_percent, candidate_overall) {
        (Some(previous), Some(candidate)) => Some(previous.max(candidate)),
        (previous, candidate) => previous.or(candidate),
    };

    WorkerTaskProgressSnapshot {
        phase,
        phase_label,
        phase_percent,
        overall_percent,
        completed_items: worker_progress_count(
            value,
            &["completed_items", "processed_count", "completed"],
        )
        .or(current.completed_items),
        total_items: worker_progress_count(value, &["total_items", "total_count", "total"])
            .or(current.total_items),
        completed_batches: worker_progress_count(value, &["completed_batches"])
            .or(current.completed_batches),
        total_batches: worker_progress_count(value, &["total_batches"]).or(current.total_batches),
        message: payload_string(value, "message").unwrap_or_else(|| current.message.clone()),
        last_progress_at: updated_at.max(current.last_progress_at),
    }
}

impl RunningJob {
    fn snapshot(&self, job_id: &str) -> WorkerTaskSnapshot {
        WorkerTaskSnapshot {
            schema_version: WORKER_TASK_SNAPSHOT_SCHEMA_VERSION,
            id: job_id.to_string(),
            command: self.command.clone(),
            state: if self.cancel_requested {
                "cancelling".to_string()
            } else {
                "running".to_string()
            },
            started_at: self.started_at_ms,
            updated_at: self.updated_at_ms,
            progress: self.progress.clone(),
            cancellable: !self.cancel_requested && self.failure_message.is_none(),
            input_fingerprint: self.input_fingerprint.clone(),
            result_ref: None,
            error: self
                .failure_message
                .as_ref()
                .map(|message| WorkerTaskFailureSnapshot {
                    code: "WORKER_TIMEOUT".to_string(),
                    message: message.clone(),
                    retryable: true,
                    phase: Some(self.progress.phase.clone()),
                    detail: None,
                }),
        }
    }
}

fn completed_worker_task_snapshot(
    status: &WorkerJobStatus,
    running: Option<&RunningJob>,
) -> WorkerTaskSnapshot {
    let state = if status.cancelled {
        "cancelled"
    } else if status.ok {
        "succeeded"
    } else {
        "failed"
    };
    let mut progress = running
        .map(|job| job.progress.clone())
        .unwrap_or_else(|| worker_task_initial_progress(status.finished_at_ms));
    progress.phase = state.to_string();
    progress.phase_label = match state {
        "succeeded" => "任务已完成",
        "cancelled" => "任务已取消",
        _ => "任务失败",
    }
    .to_string();
    progress.message = status
        .error
        .clone()
        .unwrap_or_else(|| progress.phase_label.clone());
    progress.last_progress_at = status.finished_at_ms;
    if status.ok {
        progress.phase_percent = Some(100.0);
        progress.overall_percent = Some(100.0);
    }

    WorkerTaskSnapshot {
        schema_version: WORKER_TASK_SNAPSHOT_SCHEMA_VERSION,
        id: status.job_id.clone(),
        command: status.command.clone(),
        state: state.to_string(),
        started_at: running
            .map(|job| job.started_at_ms)
            .unwrap_or(status.finished_at_ms),
        updated_at: status.finished_at_ms,
        progress,
        cancellable: false,
        input_fingerprint: running
            .map(|job| job.input_fingerprint.clone())
            .unwrap_or_else(|| format!("legacy:{}", status.job_id)),
        result_ref: status.result_ref.clone(),
        error: status
            .error
            .as_ref()
            .map(|message| WorkerTaskFailureSnapshot {
                code: status
                    .error_code
                    .clone()
                    .unwrap_or_else(|| "UNKNOWN_WORKER_ERROR".to_string()),
                message: message.clone(),
                retryable: status.retryable.unwrap_or(false),
                phase: status.stage.clone(),
                detail: None,
            }),
    }
}

fn worker_task_snapshot_dir(app: &tauri::AppHandle) -> PathBuf {
    worker_job_result_dir(app).join("task-snapshots")
}

fn safe_worker_task_id(job_id: &str) -> bool {
    if job_id.is_empty()
        || job_id.len() > 160
        || !job_id
            .chars()
            .all(|value| value.is_ascii_alphanumeric() || matches!(value, '-' | '_'))
    {
        return false;
    }
    let upper = job_id.to_ascii_uppercase();
    !matches!(upper.as_str(), "CON" | "PRN" | "AUX" | "NUL")
        && !(upper.len() == 4
            && (upper.starts_with("COM") || upper.starts_with("LPT"))
            && upper.as_bytes()[3].is_ascii_digit()
            && upper.as_bytes()[3] != b'0')
}

fn persisted_worker_result_path(result_dir: &Path, job_id: &str) -> Option<PathBuf> {
    safe_worker_task_id(job_id).then(|| result_dir.join(format!("{job_id}.json")))
}

fn resolve_worker_result_path(
    result_dir: &Path,
    job_id: &str,
    indexed_path: Option<PathBuf>,
) -> Result<PathBuf, String> {
    if !safe_worker_task_id(job_id) {
        return Err("无效的 worker 任务标识。".to_string());
    }
    if let Some(path) = indexed_path {
        return Ok(path);
    }
    let path = persisted_worker_result_path(result_dir, job_id)
        .ok_or_else(|| "无效的 worker 任务标识。".to_string())?;
    if !path.is_file() {
        return Err("后台任务结果不存在，可能需要重新运行。".to_string());
    }
    Ok(path)
}
fn worker_task_snapshot_path(app: &tauri::AppHandle, job_id: &str) -> Option<PathBuf> {
    safe_worker_task_id(job_id)
        .then(|| worker_task_snapshot_dir(app).join(format!("{job_id}.json")))
}

fn persist_worker_task_snapshot(
    app: &tauri::AppHandle,
    snapshot: &WorkerTaskSnapshot,
) -> Result<(), String> {
    let path = worker_task_snapshot_path(app, &snapshot.id)
        .ok_or_else(|| "Unsafe worker task identifier.".to_string())?;
    let payload = serde_json::to_value(snapshot)
        .map_err(|err| format!("Cannot serialize worker task snapshot: {err}"))?;
    write_json_with_backup(&path, None, &payload, WORKER_TASK_SNAPSHOT_MAX_BYTES)
}

fn load_persisted_worker_task_from_path(
    path: &Path,
    expected_job_id: &str,
) -> Result<WorkerTaskSnapshot, String> {
    if !safe_worker_task_id(expected_job_id) {
        return Err("Invalid persisted worker task identifier.".to_string());
    }
    let value = read_json_file_with_limit(path, WORKER_TASK_SNAPSHOT_MAX_BYTES)
        .map_err(|err| format!("Cannot read persisted worker task {expected_job_id}: {err}"))?;
    let snapshot: WorkerTaskSnapshot = serde_json::from_value(value)
        .map_err(|err| format!("Cannot decode persisted worker task {expected_job_id}: {err}"))?;
    if snapshot.schema_version != WORKER_TASK_SNAPSHOT_SCHEMA_VERSION {
        return Err(format!(
            "Persisted worker task {expected_job_id} uses unsupported schema version {}.",
            snapshot.schema_version
        ));
    }
    if snapshot.id != expected_job_id {
        return Err(format!(
            "Persisted worker task identifier mismatch: expected {expected_job_id}, found {}.",
            snapshot.id
        ));
    }
    Ok(snapshot)
}

fn load_persisted_worker_task(
    app: &tauri::AppHandle,
    job_id: &str,
) -> Result<Option<WorkerTaskSnapshot>, String> {
    let path = worker_task_snapshot_path(app, job_id)
        .ok_or_else(|| "Invalid persisted worker task identifier.".to_string())?;
    match fs::symlink_metadata(&path) {
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(err) => Err(format!(
            "Cannot inspect persisted worker task {job_id}: {err}"
        )),
        Ok(_) => load_persisted_worker_task_from_path(&path, job_id).map(Some),
    }
}

fn load_persisted_worker_tasks_from_dir(
    dir: &Path,
) -> Result<RecoverableWorkerTasksResult, String> {
    let entries = match fs::read_dir(dir) {
        Ok(entries) => entries,
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => {
            return Ok(RecoverableWorkerTasksResult {
                tasks: Vec::new(),
                errors: Vec::new(),
            })
        }
        Err(err) => {
            return Err(format!(
                "Cannot read persisted worker task directory: {err}"
            ))
        }
    };
    let mut snapshots = Vec::new();
    let mut errors = Vec::new();
    for entry in entries {
        let entry = match entry {
            Ok(entry) => entry,
            Err(err) => {
                errors.push(format!("Cannot enumerate persisted worker task: {err}"));
                continue;
            }
        };
        let path = entry.path();
        let file_name = match entry.file_name().into_string() {
            Ok(file_name) => file_name,
            Err(_) => {
                errors.push("Persisted worker task filename is not valid UTF-8.".to_string());
                continue;
            }
        };
        if file_name.contains(".tmp.") || file_name.contains(".rollback.") {
            continue;
        }
        if path.extension().and_then(|value| value.to_str()) != Some("json") {
            continue;
        }
        let Some(job_id) = path.file_stem().and_then(|value| value.to_str()) else {
            errors.push("Persisted worker task filename has no valid identifier.".to_string());
            continue;
        };
        match load_persisted_worker_task_from_path(&path, job_id) {
            Ok(snapshot) => snapshots.push(snapshot),
            Err(error) => errors.push(error),
        }
    }
    snapshots.sort_by(|left, right| right.updated_at.cmp(&left.updated_at));
    snapshots.truncate(COMPLETED_WORKER_JOB_LIMIT);
    errors.truncate(COMPLETED_WORKER_JOB_LIMIT);
    Ok(RecoverableWorkerTasksResult {
        tasks: snapshots,
        errors,
    })
}

fn load_persisted_worker_tasks(
    app: &tauri::AppHandle,
) -> Result<RecoverableWorkerTasksResult, String> {
    load_persisted_worker_tasks_from_dir(&worker_task_snapshot_dir(app))
}

fn mark_orphaned_worker_task_interrupted(mut snapshot: WorkerTaskSnapshot) -> WorkerTaskSnapshot {
    if matches!(snapshot.state.as_str(), "running" | "cancelling" | "queued") {
        snapshot.state = "interrupted".to_string();
        snapshot.cancellable = false;
        snapshot.progress.phase = "interrupted".to_string();
        snapshot.progress.phase_label = "任务已中断".to_string();
        snapshot.progress.message = "The previous app session ended before this task completed; resume from the last safe checkpoint.".to_string();
        snapshot.error = Some(WorkerTaskFailureSnapshot {
            code: "WORKER_INTERRUPTED".to_string(),
            message: snapshot.progress.message.clone(),
            retryable: true,
            phase: Some(snapshot.progress.phase.clone()),
            detail: None,
        });
    }
    snapshot
}

fn remove_worker_task_file_if_exists(path: &Path, label: &str) -> Result<(), String> {
    match fs::remove_file(path) {
        Ok(()) => Ok(()),
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(err) => Err(format!("Cannot acknowledge worker task {label}: {err}")),
    }
}

fn acknowledge_completed_worker_task(
    history: &mut CompletedWorkerJobs,
    job_id: &str,
    persisted_snapshot: Option<WorkerTaskSnapshot>,
    task_snapshot_path: &Path,
    result_path: &Path,
) -> Result<WorkerTaskResultAcknowledgement, String> {
    let in_memory = history.entries.get(job_id).cloned();
    let snapshot = in_memory
        .as_ref()
        .map(|entry| entry.snapshot.clone())
        .or(persisted_snapshot);
    let Some(snapshot) = snapshot else {
        return Ok(WorkerTaskResultAcknowledgement {
            acknowledged: false,
            state: None,
        });
    };
    let state = snapshot.state.clone();
    let successful = state == "succeeded"
        && in_memory
            .as_ref()
            .map(|entry| entry.status.ok && !entry.status.cancelled)
            .unwrap_or(true);
    if !successful {
        return Ok(WorkerTaskResultAcknowledgement {
            acknowledged: false,
            state: Some(state),
        });
    }

    // Delete the durable task index first. A crash after this point may leave an
    // orphan result file, but can never make the same successful task recoverable
    // again. The renderer only calls this after its artifact checkpoint is durable.
    remove_worker_task_file_if_exists(task_snapshot_path, "snapshot")?;
    remove_worker_task_file_if_exists(result_path, "result")?;
    history.entries.remove(job_id);
    history.order.retain(|entry| entry != job_id);
    Ok(WorkerTaskResultAcknowledgement {
        acknowledged: true,
        state: Some(state),
    })
}
fn worker_result_summary(command: &str, result: &Value) -> Option<Value> {
    let mut summary = json!({
        "command": command,
    });
    let keys = [
        "id",
        "title",
        "source_mode",
        "cards",
        "segments",
        "apkg_path",
        "learning_point_summary",
        "media_summary",
        "quality_funnel",
    ];
    let mut has_summary = false;
    for key in keys {
        if let Some(value) = result.get(key) {
            summary[key] = value.clone();
            has_summary = true;
        }
    }
    has_summary.then_some(summary)
}

fn store_worker_job_result_in_dir(
    dir: &Path,
    job_id: &str,
    result: &Value,
) -> Result<(String, PathBuf, u64), String> {
    fs::create_dir_all(dir).map_err(|err| format!("无法创建 worker 结果目录：{err}"))?;
    let result_path = persisted_worker_result_path(dir, job_id)
        .ok_or_else(|| "无效的 worker 任务标识。".to_string())?;
    let bytes =
        serde_json::to_vec(result).map_err(|err| format!("无法序列化 worker 结果：{err}"))?;
    let prepared = workflow_sibling_path(&result_path, "tmp")?;
    write_new_file(&prepared, &bytes)
        .and_then(|_| replace_prepared_file(&prepared, &result_path))
        .map_err(|err| format!("无法原子写入 worker 结果文件：{err}"))?;
    Ok((job_id.to_string(), result_path, bytes.len() as u64))
}

fn store_worker_job_result(
    app: &tauri::AppHandle,
    job_id: &str,
    result: &Value,
) -> Result<(String, PathBuf, u64), String> {
    store_worker_job_result_in_dir(&worker_job_result_dir(app), job_id, result)
}

fn payload_string(payload: &Value, key: &str) -> Option<String> {
    payload
        .get(key)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
}

fn payload_bool(payload: &Value, key: &str) -> Option<bool> {
    payload.get(key).and_then(Value::as_bool)
}

fn payload_string_list(payload: &Value, key: &str) -> Option<Vec<String>> {
    let values = payload.get(key)?.as_array()?;
    Some(
        values
            .iter()
            .filter_map(Value::as_str)
            .map(str::to_string)
            .collect(),
    )
}

fn remember_completed_worker_job(
    completed: &Arc<Mutex<CompletedWorkerJobs>>,
    status: WorkerJobStatus,
    snapshot: WorkerTaskSnapshot,
    result_path: Option<PathBuf>,
) -> bool {
    if let Ok(mut history) = completed.lock() {
        if history.entries.contains_key(&status.job_id) {
            return false;
        }
        history.order.push_back(status.job_id.clone());
        history.entries.insert(
            status.job_id.clone(),
            CompletedWorkerJob {
                status,
                snapshot,
                result_path,
            },
        );
        while history.order.len() > COMPLETED_WORKER_JOB_LIMIT {
            if let Some(old_job_id) = history.order.pop_front() {
                history.entries.remove(&old_job_id);
            }
        }
        true
    } else {
        false
    }
}

fn commit_completed_worker_job(
    running: &Arc<Mutex<HashMap<String, RunningJob>>>,
    completed: &Arc<Mutex<CompletedWorkerJobs>>,
    status: WorkerJobStatus,
    snapshot: WorkerTaskSnapshot,
    result_path: Option<PathBuf>,
) -> bool {
    let job_id = status.job_id.clone();
    if !remember_completed_worker_job(completed, status, snapshot, result_path) {
        return false;
    }
    if let Ok(mut active) = running.lock() {
        active.remove(&job_id);
    }
    true
}

fn complete_worker_job_and_emit(
    app: &tauri::AppHandle,
    running: &Arc<Mutex<HashMap<String, RunningJob>>>,
    completed: &Arc<Mutex<CompletedWorkerJobs>>,
    job_id: &str,
    command: &str,
    ok: bool,
    result: Option<serde_json::Value>,
    error: Option<String>,
    error_details: Option<Value>,
    cancelled: bool,
    running_job: Option<&RunningJob>,
) {
    let mut payload = json!({
      "job_id": job_id,
      "command": command,
      "ok": ok,
      "cancelled": cancelled,
    });
    let mut result_path = None;
    let mut result_ref = None;
    let mut result_size_bytes = None;
    let mut result_summary = None;
    if let Some(result) = result {
        result_summary = worker_result_summary(command, &result);
        let serialized_size = serde_json::to_vec(&result).map(|bytes| bytes.len()).ok();
        match store_worker_job_result(app, job_id, &result) {
            Ok((stored_ref, stored_path, stored_size)) => {
                payload["result_ref"] = json!(stored_ref);
                payload["result_size_bytes"] = json!(stored_size);
                result_ref = Some(job_id.to_string());
                result_size_bytes = Some(stored_size);
                result_path = Some(stored_path);
            }
            Err(err) => {
                eprintln!("worker result store failed for {job_id}: {err}");
                if let Some(size) = serialized_size {
                    payload["result_size_bytes"] = json!(size as u64);
                    result_size_bytes = Some(size as u64);
                }
            }
        }
        if let Some(summary) = result_summary.clone() {
            payload["result_summary"] = summary;
        }
        let should_inline = serialized_size
            .map(|size| size <= WORKER_INLINE_RESULT_LIMIT_BYTES)
            .unwrap_or(true)
            || result_ref.is_none();
        if should_inline {
            payload["result"] = result;
        }
    }
    apply_worker_error_payload(&mut payload, error, error_details);
    let status = WorkerJobStatus {
        job_id: job_id.to_string(),
        command: command.to_string(),
        ok,
        cancelled,
        result_ref,
        result_size_bytes,
        result_summary,
        error: payload_string(&payload, "error"),
        error_code: payload_string(&payload, "error_code"),
        stage: payload_string(&payload, "stage"),
        retryable: payload_bool(&payload, "retryable"),
        fallbacks: payload_string_list(&payload, "fallbacks"),
        details: payload.get("details").cloned(),
        finished_at_ms: now_unix_ms(),
    };
    let status_diagnostic = serde_json::to_value(&status)
        .unwrap_or_else(|err| json!({ "serialize_error": err.to_string() }));
    let task_snapshot = completed_worker_task_snapshot(&status, running_job);
    if !commit_completed_worker_job(
        running,
        completed,
        status.clone(),
        task_snapshot.clone(),
        result_path.clone(),
    ) {
        return;
    }
    if let Err(err) = persist_worker_task_snapshot(app, &task_snapshot) {
        eprintln!("worker task snapshot store failed for {job_id}: {err}");
    }
    write_worker_job_breadcrumb(
        app,
        json!({
            "schema_version": 1,
            "phase": "completed",
            "job_id": job_id,
            "command": command,
            "recorded_at_ms": now_unix_ms(),
            "status": status_diagnostic,
        }),
    );
    if let Err(err) = app.emit("worker-finished", payload) {
        eprintln!("worker-finished emit failed for {job_id}: {err}");
    }
}

fn kill_process_tree(pid: u32) -> Result<(), String> {
    #[cfg(windows)]
    {
        let mut command = Command::new("taskkill");
        command.args(["/PID", &pid.to_string(), "/T", "/F"]);
        hide_console_window(&mut command);
        let status = command
            .status()
            .map_err(|err| format!("无法取消任务进程：{err}"))?;
        validate_kill_command_status("taskkill", pid, status.success(), status.code())
    }

    #[cfg(not(windows))]
    {
        let status = Command::new("kill")
            .args(["-TERM", &pid.to_string()])
            .status()
            .map_err(|err| format!("无法取消任务进程：{err}"))?;
        validate_kill_command_status("kill", pid, status.success(), status.code())
    }
}

fn stop_unregistered_worker(child: &mut Child) {
    let pid = child.id();
    if kill_process_tree(pid).is_err() {
        let _ = child.kill();
    }
    let _ = child.wait();
}

fn validate_kill_command_status(
    command: &str,
    pid: u32,
    success: bool,
    exit_code: Option<i32>,
) -> Result<(), String> {
    if success {
        return Ok(());
    }
    Err(format!(
        "无法确认任务进程树已经停止：{command} PID {pid} 退出码 {}。",
        exit_code
            .map(|code| code.to_string())
            .unwrap_or_else(|| "unknown".to_string())
    ))
}

fn ensure_worker_start_slot(running: &HashMap<String, RunningJob>) -> Result<(), String> {
    if running.is_empty() {
        Ok(())
    } else {
        Err("已有任务正在运行，请等待完成或先取消当前任务。".to_string())
    }
}

fn mark_running_worker_force_cancelling(
    running: &Arc<Mutex<HashMap<String, RunningJob>>>,
    job_id: &str,
) -> Result<Option<RunningJob>, String> {
    let mut running_jobs = running
        .lock()
        .map_err(|_| "无法读取当前任务状态。".to_string())?;
    Ok(running_jobs.get_mut(job_id).map(|job| {
        let updated_at_ms = now_unix_ms();
        job.cancel_requested = true;
        job.updated_at_ms = updated_at_ms.max(job.updated_at_ms);
        job.progress.phase = "cancelling".to_string();
        job.progress.phase_label = "正在强制结束任务".to_string();
        job.progress.message = "正在再次终止任务进程树".to_string();
        job.progress.last_progress_at = job.updated_at_ms;
        job.clone()
    }))
}

fn forced_worker_status(
    job_id: &str,
    command: &str,
    cancelled: bool,
    error_code: &str,
    message: &str,
    stage: Option<String>,
    finished_at_ms: u64,
) -> WorkerJobStatus {
    WorkerJobStatus {
        job_id: job_id.to_string(),
        command: command.to_string(),
        ok: false,
        cancelled,
        result_ref: None,
        result_size_bytes: None,
        result_summary: None,
        error: Some(message.to_string()),
        error_code: Some(error_code.to_string()),
        stage,
        retryable: Some(true),
        fallbacks: None,
        details: None,
        finished_at_ms,
    }
}

fn forced_cancelled_worker_completion(
    job_id: &str,
    job: &RunningJob,
    finished_at_ms: u64,
) -> (WorkerJobStatus, WorkerTaskSnapshot) {
    let status = forced_worker_status(
        job_id,
        &job.command,
        true,
        "WORKER_FORCE_CANCELLED",
        "任务已强制取消，可从最后一个安全检查点继续。",
        Some(job.progress.phase.clone()),
        finished_at_ms,
    );
    let snapshot = completed_worker_task_snapshot(&status, Some(job));
    (status, snapshot)
}

fn forced_interrupted_worker_completion(
    mut snapshot: WorkerTaskSnapshot,
    finished_at_ms: u64,
    message: String,
) -> (WorkerJobStatus, WorkerTaskSnapshot) {
    let status = forced_worker_status(
        &snapshot.id,
        &snapshot.command,
        false,
        "WORKER_FORCE_CANCEL_INTERRUPTED",
        &message,
        Some(snapshot.progress.phase.clone()),
        finished_at_ms,
    );
    snapshot.state = "interrupted".to_string();
    snapshot.updated_at = finished_at_ms.max(snapshot.updated_at);
    snapshot.cancellable = false;
    snapshot.result_ref = None;
    snapshot.progress.phase = "interrupted".to_string();
    snapshot.progress.phase_label = "任务已中断".to_string();
    snapshot.progress.message = message.clone();
    snapshot.progress.last_progress_at = snapshot.updated_at;
    snapshot.error = Some(WorkerTaskFailureSnapshot {
        code: "WORKER_FORCE_CANCEL_INTERRUPTED".to_string(),
        message,
        retryable: true,
        phase: Some(snapshot.progress.phase.clone()),
        detail: None,
    });
    (status, snapshot)
}

fn worker_force_cancel_result(snapshot: Option<&WorkerTaskSnapshot>) -> WorkerForceCancelResult {
    match snapshot {
        Some(snapshot) => WorkerForceCancelResult {
            found: true,
            cancelled: snapshot.state == "cancelled",
            state: snapshot.state.clone(),
        },
        None => WorkerForceCancelResult {
            found: false,
            cancelled: false,
            state: "not_found".to_string(),
        },
    }
}

fn publish_forced_worker_terminal(
    app: &tauri::AppHandle,
    status: &WorkerJobStatus,
    snapshot: &WorkerTaskSnapshot,
) {
    if let Err(err) = persist_worker_task_snapshot(app, snapshot) {
        eprintln!(
            "worker force-cancel snapshot store failed for {}: {err}",
            status.job_id
        );
    }
    let status_diagnostic = serde_json::to_value(status)
        .unwrap_or_else(|err| json!({ "serialize_error": err.to_string() }));
    write_worker_job_breadcrumb(
        app,
        json!({
            "schema_version": 1,
            "phase": "force_cancel_terminal",
            "job_id": status.job_id,
            "command": status.command,
            "recorded_at_ms": status.finished_at_ms,
            "status": status_diagnostic,
        }),
    );
    let payload = json!({
        "job_id": status.job_id,
        "command": status.command,
        "ok": false,
        "cancelled": status.cancelled,
        "error": status.error,
        "error_code": status.error_code,
        "stage": status.stage,
        "retryable": status.retryable,
    });
    if let Err(err) = app.emit("worker-finished", payload) {
        eprintln!(
            "worker force-cancel finished emit failed for {}: {err}",
            status.job_id
        );
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

    let mut child = build_worker_command(python, &worker, &command, work_dir.clone())
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
fn allow_next_window_close(close_guard: State<WindowCloseGuard>) {
    close_guard.allow_next_close.store(true, Ordering::SeqCst);
}

#[tauri::command]
fn disallow_next_window_close(close_guard: State<WindowCloseGuard>) {
    close_guard.allow_next_close.store(false, Ordering::SeqCst);
}

#[tauri::command]
fn start_worker_job(
    app: tauri::AppHandle,
    jobs: State<WorkerJobs>,
    command: String,
    payload: serde_json::Value,
    input_fingerprint: Option<String>,
) -> Result<WorkerJobStart, String> {
    if !worker_command_allowed(&command) {
        return Err(format!("不允许的 worker 命令：{command}"));
    }

    let mut running_jobs = jobs
        .jobs
        .lock()
        .map_err(|_| "无法读取当前任务状态。".to_string())?;
    ensure_worker_start_slot(&running_jobs)?;

    let worker = find_worker(&app)?;
    let python = find_python(&worker);
    let input = serde_json::to_vec(&payload).map_err(|err| err.to_string())?;
    let work_dir = worker_work_dir(&app, &worker);
    let job_id = make_job_id(&command);
    let payload_summary = worker_payload_summary(&command, &payload, input.len());
    reset_dual_text_file(&app, ".worker-stderr-current.log");
    reset_dual_text_file(&app, ".worker-progress-current.log");
    reset_dual_text_file(&app, ".worker-stdout-current.log");

    if command == "generate_cards_from_learning_points"
        && input.len() > GENERATE_WORKER_PAYLOAD_LIMIT_BYTES
    {
        let diagnostic = json!({
            "schema_version": 1,
            "phase": "payload_rejected",
            "job_id": job_id.clone(),
            "recorded_at_ms": now_unix_ms(),
            "payload_summary": payload_summary.clone(),
            "limit_bytes": GENERATE_WORKER_PAYLOAD_LIMIT_BYTES,
        });
        write_worker_job_breadcrumb(&app, diagnostic);
        return Err(format!(
            "生成任务 payload 过大（{} bytes），已阻止启动以避免桌面端闪退。请减少本轮选择数量或使用分批生成。",
            input.len()
        ));
    }

    write_worker_job_breadcrumb(
        &app,
        json!({
            "schema_version": 1,
            "phase": "before_spawn",
            "job_id": job_id.clone(),
            "command": command.clone(),
            "recorded_at_ms": now_unix_ms(),
            "worker_path": worker.display().to_string(),
            "work_dir": work_dir.display().to_string(),
            "payload_summary": payload_summary.clone(),
        }),
    );

    let mut child = build_worker_command(python, &worker, &command, work_dir.clone())
        .spawn()
        .map_err(|err| format!("无法启动 Python worker：{err}"))?;
    let pid = child.id();
    write_worker_job_breadcrumb(
        &app,
        json!({
            "schema_version": 1,
            "phase": "spawned",
            "job_id": job_id.clone(),
            "command": command.clone(),
            "worker_pid": pid,
            "recorded_at_ms": now_unix_ms(),
            "worker_path": worker.display().to_string(),
            "work_dir": work_dir.display().to_string(),
            "payload_summary": payload_summary.clone(),
        }),
    );
    let stderr = match child.stderr.take() {
        Some(stderr) => stderr,
        None => {
            stop_unregistered_worker(&mut child);
            return Err("无法读取 worker 错误输出。".to_string());
        }
    };
    let stdout = match child.stdout.take() {
        Some(stdout) => stdout,
        None => {
            stop_unregistered_worker(&mut child);
            return Err("无法读取 worker 输出。".to_string());
        }
    };

    match child.stdin.as_mut() {
        Some(stdin) => {
            if let Err(err) = stdin.write_all(&input) {
                stop_unregistered_worker(&mut child);
                return Err(format!("无法写入 worker 输入：{err}"));
            }
        }
        None => {
            stop_unregistered_worker(&mut child);
            return Err("无法写入 worker 输入：stdin 不可用。".to_string());
        }
    }
    drop(child.stdin.take());
    let started_at_ms = now_unix_ms();

    running_jobs.insert(
        job_id.clone(),
        RunningJob {
            pid,
            command: command.clone(),
            cancel_requested: false,
            failure_message: None,
            started_at_ms,
            updated_at_ms: started_at_ms,
            progress: worker_task_initial_progress(started_at_ms),
            input_fingerprint: validated_worker_input_fingerprint(
                input_fingerprint.as_deref(),
                &payload_summary,
            ),
        },
    );
    drop(running_jobs);

    let running_snapshot = jobs
        .jobs
        .lock()
        .ok()
        .and_then(|jobs| jobs.get(&job_id).map(|job| job.snapshot(&job_id)));
    if let Some(snapshot) = running_snapshot {
        if let Err(err) = persist_worker_task_snapshot(&app, &snapshot) {
            eprintln!("worker task snapshot store failed for {job_id}: {err}");
        }
    }
    let stderr_text = Arc::new(Mutex::new(String::new()));
    let stderr_sink = Arc::clone(&stderr_text);
    let stderr_error = Arc::new(Mutex::new(None::<Value>));
    let stderr_error_sink = Arc::clone(&stderr_error);
    let last_progress = Arc::new(Mutex::new(Instant::now()));
    let last_progress_sink = Arc::clone(&last_progress);
    let app_for_progress = app.clone();
    let progress_job_id = job_id.clone();
    let progress_jobs = Arc::clone(&jobs.jobs);
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
                    let task_updated_at = now_unix_ms();
                    let task_snapshot = progress_jobs.lock().ok().and_then(|mut jobs| {
                        jobs.get_mut(&progress_job_id).map(|job| {
                            job.updated_at_ms = task_updated_at.max(job.updated_at_ms);
                            job.progress =
                                update_worker_task_progress(&job.progress, &value, task_updated_at);
                            job.snapshot(&progress_job_id)
                        })
                    });
                    let percent = value
                        .get("percent")
                        .and_then(|percent| percent.as_u64())
                        .unwrap_or_default();
                    if percent >= 100 || last_emit.elapsed() >= Duration::from_millis(100) {
                        let progress_value = value.clone();
                        if let Some(snapshot) = task_snapshot.as_ref() {
                            if let Err(err) =
                                persist_worker_task_snapshot(&app_for_progress, snapshot)
                            {
                                eprintln!(
                                    "worker task snapshot store failed for {}: {err}",
                                    progress_job_id
                                );
                            }
                        }
                        let _ = app_for_progress.emit("worker-progress", value);
                        append_dual_text_file(
                            &app_for_progress,
                            ".worker-progress-current.log",
                            &format!("[{}] {}", now_unix_ms(), progress_value),
                        );
                        write_worker_job_breadcrumb(
                            &app_for_progress,
                            json!({
                                "schema_version": 1,
                                "phase": "progress",
                                "job_id": progress_job_id.clone(),
                                "command": progress_value.get("command").and_then(Value::as_str).unwrap_or_default(),
                                "recorded_at_ms": now_unix_ms(),
                                "progress": progress_value,
                            }),
                        );
                        last_emit = Instant::now();
                    }
                }
            } else if let Some(error) = parse_worker_error_line(&line) {
                if let Ok(mut value) = stderr_error_sink.lock() {
                    *value = Some(error);
                }
                append_dual_text_file(
                    &app_for_progress,
                    ".worker-stderr-current.log",
                    &format!("[{}] structured_error {}", now_unix_ms(), line),
                );
            } else if let Ok(mut text) = stderr_sink.lock() {
                text.push_str(&line);
                text.push('\n');
                append_dual_text_file(
                    &app_for_progress,
                    ".worker-stderr-current.log",
                    &format!("[{}] {}", now_unix_ms(), line),
                );
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
                if let Err(err) = kill_process_tree(pid) {
                    eprintln!("worker watchdog could not stop process tree {pid}: {err}");
                }
                break;
            }
        }
    });

    let app_for_finish = app.clone();
    let jobs_for_finish = Arc::clone(&jobs.jobs);
    let completed_for_finish = Arc::clone(&jobs.completed);
    let finish_job_id = job_id.clone();
    let finish_command = command.clone();
    thread::spawn(move || {
        let mut stdout_text = String::new();
        let read_result = BufReader::new(stdout).read_to_string(&mut stdout_text);
        let wait_result = child.wait();
        let _ = progress_thread.join();
        append_dual_text_file(
            &app_for_finish,
            ".worker-stdout-current.log",
            &format!(
                "[{}] stdout_bytes={} read_stdout_ok={}",
                now_unix_ms(),
                stdout_text.len(),
                read_result.is_ok()
            ),
        );
        let job_state = jobs_for_finish
            .lock()
            .ok()
            .and_then(|jobs| jobs.get(&finish_job_id).cloned());
        let cancelled = job_state
            .as_ref()
            .map(|job| job.cancel_requested)
            .unwrap_or(false);
        let failure_message = job_state
            .as_ref()
            .and_then(|job| job.failure_message.clone());
        let exit_summary = match &wait_result {
            Ok(status) => json!({
                "ok": true,
                "success": status.success(),
                "code": status.code(),
            }),
            Err(err) => json!({
                "ok": false,
                "error": err.to_string(),
            }),
        };
        write_worker_job_breadcrumb(
            &app_for_finish,
            json!({
                "schema_version": 1,
                "phase": "worker_exited",
                "job_id": finish_job_id.clone(),
                "command": finish_command.clone(),
                "recorded_at_ms": now_unix_ms(),
                "cancelled": cancelled,
                "failure_message": failure_message.clone(),
                "stdout_bytes": stdout_text.len(),
                "read_stdout_ok": read_result.is_ok(),
                "exit": exit_summary,
            }),
        );

        if let Err(err) = read_result {
            complete_worker_job_and_emit(
                &app_for_finish,
                &jobs_for_finish,
                &completed_for_finish,
                &finish_job_id,
                &finish_command,
                false,
                None,
                Some(format!("无法读取 worker JSON 输出：{err}")),
                None,
                cancelled,
                job_state.as_ref(),
            );
            return;
        }

        match wait_result {
            Ok(status) if status.success() && !cancelled => {
                match serde_json::from_str::<serde_json::Value>(&stdout_text) {
                    Ok(result) => complete_worker_job_and_emit(
                        &app_for_finish,
                        &jobs_for_finish,
                        &completed_for_finish,
                        &finish_job_id,
                        &finish_command,
                        true,
                        Some(result),
                        None,
                        None,
                        false,
                        job_state.as_ref(),
                    ),
                    Err(err) => complete_worker_job_and_emit(
                        &app_for_finish,
                        &jobs_for_finish,
                        &completed_for_finish,
                        &finish_job_id,
                        &finish_command,
                        false,
                        None,
                        Some(format!("worker 输出不是有效 JSON：{err}")),
                        None,
                        false,
                        job_state.as_ref(),
                    ),
                }
            }
            Ok(_) if cancelled => complete_worker_job_and_emit(
                &app_for_finish,
                &jobs_for_finish,
                &completed_for_finish,
                &finish_job_id,
                &finish_command,
                false,
                None,
                Some("任务已取消。".to_string()),
                None,
                true,
                job_state.as_ref(),
            ),
            Ok(_) if failure_message.is_some() => complete_worker_job_and_emit(
                &app_for_finish,
                &jobs_for_finish,
                &completed_for_finish,
                &finish_job_id,
                &finish_command,
                false,
                None,
                failure_message,
                None,
                false,
                job_state.as_ref(),
            ),
            Ok(_) => {
                let stderr = stderr_text
                    .lock()
                    .map(|text| text.clone())
                    .unwrap_or_default();
                let error_details = stderr_error.lock().ok().and_then(|value| value.clone());
                let message = worker_failure_message(&stderr, &stdout_text, error_details.as_ref());
                complete_worker_job_and_emit(
                    &app_for_finish,
                    &jobs_for_finish,
                    &completed_for_finish,
                    &finish_job_id,
                    &finish_command,
                    false,
                    None,
                    Some(message),
                    error_details,
                    false,
                    job_state.as_ref(),
                );
            }
            Err(err) => complete_worker_job_and_emit(
                &app_for_finish,
                &jobs_for_finish,
                &completed_for_finish,
                &finish_job_id,
                &finish_command,
                false,
                None,
                Some(format!("worker 执行失败：{err}")),
                None,
                cancelled,
                job_state.as_ref(),
            ),
        }
    });

    Ok(WorkerJobStart { job_id })
}

#[tauri::command]
fn cancel_worker_job(
    app: tauri::AppHandle,
    jobs: State<WorkerJobs>,
    job_id: String,
) -> Result<WorkerCancelResult, String> {
    let (pid, snapshot) = {
        let mut jobs = jobs
            .jobs
            .lock()
            .map_err(|_| "无法读取当前任务状态。".to_string())?;
        if let Some(job) = jobs.get_mut(&job_id) {
            let updated_at = now_unix_ms();
            job.cancel_requested = true;
            job.updated_at_ms = updated_at.max(job.updated_at_ms);
            job.progress.phase = "cancelling".to_string();
            job.progress.phase_label = "正在取消任务".to_string();
            job.progress.message = "正在安全停止当前任务".to_string();
            job.progress.last_progress_at = job.updated_at_ms;
            (Some(job.pid), Some(job.snapshot(&job_id)))
        } else {
            (None, None)
        }
    };
    if let Some(snapshot) = snapshot.as_ref() {
        if let Err(err) = persist_worker_task_snapshot(&app, snapshot) {
            eprintln!("worker task snapshot store failed for {job_id}: {err}");
        }
    }

    if let Some(pid) = pid {
        kill_process_tree(pid)?;
        Ok(WorkerCancelResult { cancelled: true })
    } else {
        Ok(WorkerCancelResult { cancelled: false })
    }
}

#[tauri::command]
fn force_cancel_worker_job(
    app: tauri::AppHandle,
    jobs: State<WorkerJobs>,
    job_id: String,
) -> Result<WorkerForceCancelResult, String> {
    if !safe_worker_task_id(&job_id) {
        return Err("无效的 worker 任务标识。".to_string());
    }

    if let Some(snapshot) = jobs
        .completed
        .lock()
        .map_err(|_| "无法读取后台任务完成状态。".to_string())?
        .entries
        .get(&job_id)
        .map(|entry| entry.snapshot.clone())
    {
        return Ok(worker_force_cancel_result(Some(&snapshot)));
    }

    let active_job = mark_running_worker_force_cancelling(&jobs.jobs, &job_id)?;

    if let Some(job) = active_job {
        let cancelling_snapshot = job.snapshot(&job_id);
        if let Err(err) = persist_worker_task_snapshot(&app, &cancelling_snapshot) {
            eprintln!("worker task snapshot store failed for {job_id}: {err}");
        }
        if let Err(err) = kill_process_tree(job.pid) {
            if let Some(snapshot) = jobs
                .completed
                .lock()
                .map_err(|_| "无法读取后台任务完成状态。".to_string())?
                .entries
                .get(&job_id)
                .map(|entry| entry.snapshot.clone())
            {
                return Ok(worker_force_cancel_result(Some(&snapshot)));
            }
            return Err(format!(
                "强制结束任务失败，任务仍保留在取消中状态，尚未标记为终态：{err}"
            ));
        }

        let finished_at_ms = now_unix_ms();
        let (status, snapshot) = forced_cancelled_worker_completion(&job_id, &job, finished_at_ms);
        let remembered = commit_completed_worker_job(
            &jobs.jobs,
            &jobs.completed,
            status.clone(),
            snapshot.clone(),
            None,
        );
        if remembered {
            publish_forced_worker_terminal(&app, &status, &snapshot);
            return Ok(worker_force_cancel_result(Some(&snapshot)));
        }
        let winner = jobs
            .completed
            .lock()
            .map_err(|_| "无法读取后台任务完成状态。".to_string())?
            .entries
            .get(&job_id)
            .map(|entry| entry.snapshot.clone())
            .ok_or_else(|| "任务进程已停止，但无法写入最终任务状态。".to_string())?;
        return Ok(worker_force_cancel_result(Some(&winner)));
    }

    if let Some(snapshot) = jobs
        .completed
        .lock()
        .map_err(|_| "无法读取后台任务完成状态。".to_string())?
        .entries
        .get(&job_id)
        .map(|entry| entry.snapshot.clone())
    {
        return Ok(worker_force_cancel_result(Some(&snapshot)));
    }

    let Some(persisted) = load_persisted_worker_task(&app, &job_id)? else {
        return Ok(worker_force_cancel_result(None));
    };
    if !matches!(
        persisted.state.as_str(),
        "running" | "cancelling" | "queued"
    ) {
        return Ok(worker_force_cancel_result(Some(&persisted)));
    }

    let finished_at_ms = now_unix_ms();
    let (status, snapshot) = forced_interrupted_worker_completion(
        persisted,
        finished_at_ms,
        "任务进程不再受当前应用实例管理，已标记为中断；可以从最后一个安全检查点继续。".to_string(),
    );
    let remembered =
        remember_completed_worker_job(&jobs.completed, status.clone(), snapshot.clone(), None);
    if remembered {
        publish_forced_worker_terminal(&app, &status, &snapshot);
        return Ok(worker_force_cancel_result(Some(&snapshot)));
    }

    let winner = jobs
        .completed
        .lock()
        .map_err(|_| "无法读取后台任务完成状态。".to_string())?
        .entries
        .get(&job_id)
        .map(|entry| entry.snapshot.clone())
        .ok_or_else(|| "无法将失去管理的任务收敛到最终状态。".to_string())?;
    Ok(worker_force_cancel_result(Some(&winner)))
}

#[tauri::command]
fn get_worker_job_status(
    jobs: State<WorkerJobs>,
    job_id: String,
) -> Result<Option<WorkerJobStatus>, String> {
    let history = jobs
        .completed
        .lock()
        .map_err(|_| "无法读取后台任务完成状态。".to_string())?;
    Ok(history
        .entries
        .get(&job_id)
        .map(|entry| entry.status.clone()))
}

#[tauri::command]
fn get_worker_task(
    app: tauri::AppHandle,
    jobs: State<WorkerJobs>,
    job_id: String,
) -> Result<Option<WorkerTaskSnapshot>, String> {
    if !safe_worker_task_id(&job_id) {
        return Err("Invalid worker task identifier.".to_string());
    }

    if let Some(snapshot) = jobs
        .jobs
        .lock()
        .map_err(|_| "Cannot read running worker tasks.".to_string())?
        .get(&job_id)
        .map(|job| job.snapshot(&job_id))
    {
        return Ok(Some(snapshot));
    }

    if let Some(snapshot) = jobs
        .completed
        .lock()
        .map_err(|_| "Cannot read completed worker tasks.".to_string())?
        .entries
        .get(&job_id)
        .map(|entry| entry.snapshot.clone())
    {
        return Ok(Some(snapshot));
    }

    let snapshot =
        load_persisted_worker_task(&app, &job_id)?.map(mark_orphaned_worker_task_interrupted);
    if let Some(snapshot) = snapshot.as_ref() {
        if let Err(err) = persist_worker_task_snapshot(&app, snapshot) {
            eprintln!("worker task recovery snapshot store failed for {job_id}: {err}");
        }
    }
    Ok(snapshot)
}

#[tauri::command]
fn list_recoverable_worker_tasks(
    app: tauri::AppHandle,
    jobs: State<WorkerJobs>,
) -> Result<RecoverableWorkerTasksResult, String> {
    let mut snapshots = HashMap::<String, WorkerTaskSnapshot>::new();

    {
        let running = jobs
            .jobs
            .lock()
            .map_err(|_| "Cannot read running worker tasks.".to_string())?;
        for (job_id, job) in running.iter() {
            snapshots.insert(job_id.clone(), job.snapshot(job_id));
        }
    }

    {
        let completed = jobs
            .completed
            .lock()
            .map_err(|_| "Cannot read completed worker tasks.".to_string())?;
        for (job_id, entry) in completed.entries.iter() {
            snapshots
                .entry(job_id.clone())
                .or_insert_with(|| entry.snapshot.clone());
        }
    }

    let persisted_result = load_persisted_worker_tasks(&app)?;
    for persisted in persisted_result.tasks {
        let job_id = persisted.id.clone();
        snapshots
            .entry(job_id)
            .or_insert_with(|| mark_orphaned_worker_task_interrupted(persisted));
    }

    let mut values = snapshots.into_values().collect::<Vec<_>>();
    values.sort_by(|left, right| right.updated_at.cmp(&left.updated_at));
    values.truncate(COMPLETED_WORKER_JOB_LIMIT);
    Ok(RecoverableWorkerTasksResult {
        tasks: values,
        errors: persisted_result.errors,
    })
}

#[tauri::command]
fn read_worker_job_result(
    app: tauri::AppHandle,
    jobs: State<WorkerJobs>,
    job_id: String,
) -> Result<Value, String> {
    let indexed_path = {
        let history = jobs
            .completed
            .lock()
            .map_err(|_| "无法读取后台任务结果索引。".to_string())?;
        history
            .entries
            .get(&job_id)
            .and_then(|entry| entry.result_path.clone())
    };
    let result_path =
        resolve_worker_result_path(&worker_job_result_dir(&app), &job_id, indexed_path)?;
    let text = fs::read_to_string(&result_path)
        .map_err(|err| format!("无法读取后台任务结果文件：{err}"))?;
    serde_json::from_str(&text).map_err(|err| format!("后台任务结果不是有效 JSON：{err}"))
}

#[tauri::command]
fn acknowledge_worker_task_result(
    app: tauri::AppHandle,
    jobs: State<WorkerJobs>,
    job_id: String,
) -> Result<WorkerTaskResultAcknowledgement, String> {
    if !safe_worker_task_id(&job_id) {
        return Err("Invalid worker task identifier.".to_string());
    }
    if let Some(snapshot) = jobs
        .jobs
        .lock()
        .map_err(|_| "Cannot read running worker tasks.".to_string())?
        .get(&job_id)
        .map(|job| job.snapshot(&job_id))
    {
        return Ok(WorkerTaskResultAcknowledgement {
            acknowledged: false,
            state: Some(snapshot.state),
        });
    }

    let persisted_snapshot = load_persisted_worker_task(&app, &job_id)?;
    let task_path = worker_task_snapshot_path(&app, &job_id)
        .ok_or_else(|| "Invalid worker task identifier.".to_string())?;
    let result_path = persisted_worker_result_path(&worker_job_result_dir(&app), &job_id)
        .ok_or_else(|| "Invalid worker task identifier.".to_string())?;
    let mut history = jobs
        .completed
        .lock()
        .map_err(|_| "Cannot acknowledge completed worker task.".to_string())?;
    acknowledge_completed_worker_task(
        &mut history,
        &job_id,
        persisted_snapshot,
        &task_path,
        &result_path,
    )
}
fn workflow_storage_dir(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let dir = app
        .path()
        .app_local_data_dir()
        .map_err(|err| format!("无法定位工作流数据目录：{err}"))?;
    fs::create_dir_all(&dir).map_err(|err| format!("无法创建工作流数据目录：{err}"))?;
    Ok(dir)
}

fn workflow_checkpoint_path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    Ok(workflow_storage_dir(app)?.join(WORKFLOW_CHECKPOINT_FILE))
}

fn workflow_checkpoint_backup_path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    Ok(workflow_storage_dir(app)?.join(WORKFLOW_CHECKPOINT_BACKUP_FILE))
}

fn workflow_artifact_dir(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let storage_dir = workflow_storage_dir(app)?;
    let dir = storage_dir.join("workflow-artifacts");
    fs::create_dir_all(&dir).map_err(|err| format!("无法创建工作流产物目录：{err}"))?;

    let canonical_storage =
        fs::canonicalize(&storage_dir).map_err(|err| format!("无法校验工作流数据目录：{err}"))?;
    let canonical_dir =
        fs::canonicalize(&dir).map_err(|err| format!("无法校验工作流产物目录：{err}"))?;
    if !canonical_dir.starts_with(&canonical_storage) {
        return Err("工作流产物目录超出了应用数据目录。".to_string());
    }
    Ok(canonical_dir)
}

fn secret_field_has_value(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::String(text) => !text.trim().is_empty(),
        Value::Bool(flag) => *flag,
        Value::Number(_) => true,
        Value::Array(items) => !items.is_empty(),
        Value::Object(items) => !items.is_empty(),
    }
}

fn is_secret_field_name(key: &str) -> bool {
    let compact = key
        .chars()
        .filter(|character| character.is_ascii_alphanumeric())
        .flat_map(char::to_lowercase)
        .collect::<String>();

    let safe_metadata = compact.ends_with("exists")
        || compact.ends_with("revision")
        || compact.ends_with("source")
        || compact.ends_with("reference")
        || compact.ends_with("ref")
        || matches!(
            compact.as_str(),
            "hasapikey"
                | "hasmodelapikey"
                | "hasttsapikey"
                | "haspassword"
                | "hastoken"
                | "hascookie"
                | "hascredential"
        );
    if safe_metadata {
        return false;
    }

    compact.contains("apikey")
        || compact.contains("authorization")
        || compact.contains("accesstoken")
        || compact.contains("refreshtoken")
        || compact.contains("bearertoken")
        || compact.contains("oauthtoken")
        || compact.contains("oauthcode")
        || compact.contains("authorizationcode")
        || compact.contains("clientsecret")
        || compact.contains("privatekey")
        || (compact.starts_with("token")
            && !compact.ends_with("type")
            && !compact.ends_with("count")
            && !compact.ends_with("expiry"))
        || compact.ends_with("password")
        || compact.ends_with("passphrase")
        || compact.ends_with("token")
        || compact.ends_with("secret")
        || compact.ends_with("cookie")
        || compact.ends_with("credential")
        || compact.ends_with("credentials")
}
fn checkpoint_contains_secret(value: &Value) -> bool {
    let mut pending = vec![value];
    while let Some(current) = pending.pop() {
        match current {
            Value::Object(map) => {
                for (key, child) in map {
                    if is_secret_field_name(key) && secret_field_has_value(child) {
                        return true;
                    }
                    pending.push(child);
                }
            }
            Value::Array(items) => pending.extend(items),
            _ => {}
        }
    }
    false
}

fn workflow_file_suffix() -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    let sequence = WORKFLOW_FILE_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    format!("{}-{nanos}-{sequence}", std::process::id())
}

fn workflow_sibling_path(path: &Path, role: &str) -> Result<PathBuf, String> {
    let parent = path
        .parent()
        .ok_or_else(|| "工作流文件缺少父目录。".to_string())?;
    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("workflow");
    Ok(parent.join(format!(".{name}.{role}.{}", workflow_file_suffix())))
}

fn reject_unsafe_existing_file(path: &Path) -> Result<(), String> {
    match fs::symlink_metadata(path) {
        Ok(metadata) if metadata.file_type().is_symlink() => {
            Err("工作流文件不能是符号链接。".to_string())
        }
        Ok(metadata) if !metadata.is_file() => Err("工作流路径不是普通文件。".to_string()),
        Ok(_) => Ok(()),
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(err) => Err(format!("无法检查工作流文件：{err}")),
    }
}

fn write_new_file(path: &Path, bytes: &[u8]) -> Result<(), String> {
    let result = (|| {
        let mut file = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(path)
            .map_err(|err| format!("无法创建工作流临时文件：{err}"))?;
        file.write_all(bytes)
            .map_err(|err| format!("无法写入工作流临时文件：{err}"))?;
        file.sync_all()
            .map_err(|err| format!("无法同步工作流临时文件：{err}"))
    })();
    if result.is_err() {
        let _ = fs::remove_file(path);
    }
    result
}

fn replace_prepared_file(prepared: &Path, target: &Path) -> Result<(), String> {
    let result = (|| {
        reject_unsafe_existing_file(target)?;
        if !target.exists() {
            return fs::rename(prepared, target)
                .map_err(|err| format!("无法保存工作流文件：{err}"));
        }

        let rollback = workflow_sibling_path(target, "rollback")?;
        fs::rename(target, &rollback).map_err(|err| format!("无法保护旧工作流文件：{err}"))?;
        match fs::rename(prepared, target) {
            Ok(()) => {
                let _ = fs::remove_file(rollback);
                Ok(())
            }
            Err(save_error) => match fs::rename(&rollback, target) {
                Ok(()) => Err(format!("无法保存工作流文件，已恢复旧版本：{save_error}")),
                Err(restore_error) => Err(format!(
                    "无法保存工作流文件，旧版本位于同目录回滚文件中：{save_error}；恢复失败：{restore_error}"
                )),
            },
        }
    })();

    if result.is_err() {
        let _ = fs::remove_file(prepared);
    }
    result
}
fn read_json_file_with_limit(path: &Path, max_bytes: u64) -> Result<Value, String> {
    reject_unsafe_existing_file(path)?;
    let metadata = fs::metadata(path).map_err(|err| format!("无法读取工作流文件信息：{err}"))?;
    if metadata.len() > max_bytes {
        return Err("工作流文件超过允许大小。".to_string());
    }

    let parent = path
        .parent()
        .ok_or_else(|| "工作流文件缺少父目录。".to_string())?;
    let canonical_parent =
        fs::canonicalize(parent).map_err(|err| format!("无法校验工作流目录：{err}"))?;
    let canonical_path =
        fs::canonicalize(path).map_err(|err| format!("无法校验工作流文件：{err}"))?;
    if canonical_path.parent() != Some(canonical_parent.as_path()) {
        return Err("工作流文件超出了预期目录。".to_string());
    }

    let bytes = fs::read(&canonical_path).map_err(|err| format!("无法读取工作流文件：{err}"))?;
    serde_json::from_slice(&bytes).map_err(|err| format!("工作流文件不是有效 JSON：{err}"))
}

fn write_json_with_backup(
    path: &Path,
    backup_path: Option<&Path>,
    payload: &Value,
    max_bytes: u64,
) -> Result<(), String> {
    let parent = path
        .parent()
        .ok_or_else(|| "工作流文件缺少父目录。".to_string())?;
    fs::create_dir_all(parent).map_err(|err| format!("无法创建工作流文件目录：{err}"))?;
    reject_unsafe_existing_file(path)?;

    let bytes =
        serde_json::to_vec_pretty(payload).map_err(|err| format!("无法序列化工作流数据：{err}"))?;
    if bytes.len() as u64 > max_bytes {
        return Err("工作流数据超过允许大小。".to_string());
    }

    let prepared = workflow_sibling_path(path, "tmp")?;
    write_new_file(&prepared, &bytes)?;

    if let Some(backup_path) = backup_path {
        reject_unsafe_existing_file(backup_path)?;
        if path.is_file() {
            if let Ok(previous) = read_json_file_with_limit(path, max_bytes) {
                if !checkpoint_contains_secret(&previous) {
                    let previous_bytes =
                        fs::read(path).map_err(|err| format!("无法读取旧工作流文件：{err}"))?;
                    let prepared_backup = workflow_sibling_path(backup_path, "tmp")?;
                    if let Err(err) = write_new_file(&prepared_backup, &previous_bytes)
                        .and_then(|_| replace_prepared_file(&prepared_backup, backup_path))
                    {
                        let _ = fs::remove_file(&prepared);
                        return Err(format!("无法更新工作流备份：{err}"));
                    }
                }
            }
        }
    }

    replace_prepared_file(&prepared, path)
}

#[tauri::command]
fn save_workflow_checkpoint(app: tauri::AppHandle, checkpoint: Value) -> Result<(), String> {
    if checkpoint_contains_secret(&checkpoint) {
        return Err("检查点包含凭据或其他秘密，已拒绝保存。".to_string());
    }
    let path = workflow_checkpoint_path(&app)?;
    let backup = workflow_checkpoint_backup_path(&app)?;
    write_json_with_backup(
        &path,
        Some(&backup),
        &checkpoint,
        WORKFLOW_CHECKPOINT_MAX_BYTES,
    )
}

fn load_workflow_checkpoint_candidate(path: &Path, label: &str) -> Result<Option<Value>, String> {
    if !path.is_file() {
        return Ok(None);
    }
    let value = read_json_file_with_limit(path, WORKFLOW_CHECKPOINT_MAX_BYTES)?;
    if checkpoint_contains_secret(&value) {
        return Err(format!("{label}包含凭据或其他秘密，已拒绝加载。"));
    }
    Ok(Some(value))
}

#[tauri::command]
fn load_workflow_checkpoint(app: tauri::AppHandle) -> Result<Option<Value>, String> {
    let path = workflow_checkpoint_path(&app)?;
    let backup = workflow_checkpoint_backup_path(&app)?;
    if path.is_file() {
        match read_json_file_with_limit(&path, WORKFLOW_CHECKPOINT_MAX_BYTES) {
            Ok(value) if !checkpoint_contains_secret(&value) => return Ok(Some(value)),
            Ok(_) => return Err("检查点包含凭据或其他秘密，已拒绝加载。".to_string()),
            Err(_) if backup.is_file() => {}
            Err(err) => return Err(err),
        }
    }
    load_workflow_checkpoint_candidate(&backup, "检查点备份")
}

#[tauri::command]
fn load_workflow_checkpoint_backup(app: tauri::AppHandle) -> Result<Option<Value>, String> {
    let backup = workflow_checkpoint_backup_path(&app)?;
    load_workflow_checkpoint_candidate(&backup, "检查点备份")
}

#[tauri::command]
fn clear_workflow_checkpoint(app: tauri::AppHandle) -> Result<(), String> {
    let path = workflow_checkpoint_path(&app)?;
    let backup = workflow_checkpoint_backup_path(&app)?;
    for candidate in [path, backup] {
        if candidate.exists() {
            reject_unsafe_existing_file(&candidate)?;
            fs::remove_file(&candidate).map_err(|err| format!("无法清除工作流检查点：{err}"))?;
        }
    }
    Ok(())
}

fn is_windows_reserved_file_stem(stem: &str) -> bool {
    let stem = stem.to_ascii_lowercase();
    matches!(stem.as_str(), "con" | "prn" | "aux" | "nul" | "clock$")
        || stem
            .strip_prefix("com")
            .or_else(|| stem.strip_prefix("lpt"))
            .and_then(|suffix| suffix.parse::<u8>().ok())
            .is_some_and(|number| (1..=9).contains(&number))
}

fn validate_workflow_artifact_ref(reference: &str) -> Result<(), String> {
    let path = Path::new(reference);
    let safe_name = path.file_name().and_then(|value| value.to_str()) == Some(reference);
    let safe_chars = reference
        .chars()
        .all(|value| value.is_ascii_alphanumeric() || matches!(value, '-' | '_' | '.'));
    let stem = reference.strip_suffix(".json").unwrap_or_default();
    if safe_name
        && safe_chars
        && !stem.is_empty()
        && !stem.starts_with('.')
        && !is_windows_reserved_file_stem(stem.split('.').next().unwrap_or_default())
        && reference.ends_with(".json")
        && reference.len() <= 160
    {
        Ok(())
    } else {
        Err("工作流产物引用无效。".to_string())
    }
}

fn workflow_artifact_path(
    app: &tauri::AppHandle,
    reference: &str,
    must_exist: bool,
) -> Result<PathBuf, String> {
    validate_workflow_artifact_ref(reference)?;
    let root = workflow_artifact_dir(app)?;
    let candidate = root.join(reference);
    reject_unsafe_existing_file(&candidate)?;

    if must_exist {
        if !candidate.is_file() {
            return Err("工作流产物不存在。".to_string());
        }
        let canonical =
            fs::canonicalize(&candidate).map_err(|err| format!("无法校验工作流产物路径：{err}"))?;
        if !canonical.starts_with(&root) || canonical.parent() != Some(root.as_path()) {
            return Err("工作流产物超出了应用数据目录。".to_string());
        }
        Ok(canonical)
    } else {
        Ok(candidate)
    }
}

#[tauri::command]
fn write_workflow_artifact(
    app: tauri::AppHandle,
    kind: String,
    payload: Value,
) -> Result<String, String> {
    const ALLOWED_KINDS: &[&str] = &[
        "learning-points",
        "project",
        "generation-queue",
        "export-result",
        "anki-verification",
    ];
    if !ALLOWED_KINDS.contains(&kind.as_str()) {
        return Err("工作流产物类型不受支持。".to_string());
    }
    if checkpoint_contains_secret(&payload) {
        return Err("工作流产物包含凭据或其他秘密，已拒绝保存。".to_string());
    }

    let reference = format!("{kind}-{}.json", workflow_file_suffix());
    let path = workflow_artifact_path(&app, &reference, false)?;
    write_json_with_backup(&path, None, &payload, WORKFLOW_ARTIFACT_MAX_BYTES)?;
    Ok(reference)
}

#[tauri::command]
fn read_workflow_artifact(app: tauri::AppHandle, reference: String) -> Result<Value, String> {
    let path = workflow_artifact_path(&app, &reference, true)?;
    let value = read_json_file_with_limit(&path, WORKFLOW_ARTIFACT_MAX_BYTES)?;
    if checkpoint_contains_secret(&value) {
        return Err("工作流产物包含凭据或其他秘密，已拒绝加载。".to_string());
    }
    Ok(value)
}

#[tauri::command]
fn record_renderer_error(app: tauri::AppHandle, payload: Value) -> Result<(), String> {
    let diagnostic = json!({
        "schema_version": 1,
        "source": "renderer",
        "recorded_at_ms": now_unix_ms(),
        "payload": payload,
    });
    write_dual_diagnostic_file(&app, ".renderer-error-current.json", diagnostic);
    Ok(())
}

fn push_unique_path(candidates: &mut Vec<PathBuf>, path: PathBuf) {
    if !path.as_os_str().is_empty() && !candidates.iter().any(|candidate| candidate == &path) {
        candidates.push(path);
    }
}

fn parse_windows_open_command_executable(command: &str) -> Option<PathBuf> {
    let command = command.trim();
    if command.is_empty() {
        return None;
    }
    if let Some(rest) = command.strip_prefix('"') {
        let end = rest.find('"')?;
        return Some(PathBuf::from(&rest[..end]));
    }
    let lower = command.to_ascii_lowercase();
    let exe_end = lower.find(".exe").map(|index| index + 4)?;
    Some(PathBuf::from(command[..exe_end].trim()))
}

#[cfg(windows)]
fn registered_anki_candidates() -> Vec<PathBuf> {
    let script = r#"$class = (Get-ItemProperty -Path 'Registry::HKEY_CLASSES_ROOT\.apkg' -ErrorAction SilentlyContinue).'(default)'; if ($class) { (Get-ItemProperty -Path "Registry::HKEY_CLASSES_ROOT\$class\shell\open\command" -ErrorAction SilentlyContinue).'(default)' }"#;
    let mut command = Command::new("powershell.exe");
    command.args(["-NoProfile", "-NonInteractive", "-Command", script]);
    hide_console_window(&mut command);
    command
        .output()
        .ok()
        .filter(|output| output.status.success())
        .map(|output| {
            String::from_utf8_lossy(&output.stdout)
                .lines()
                .filter_map(parse_windows_open_command_executable)
                .collect()
        })
        .unwrap_or_default()
}

#[cfg(not(windows))]
fn registered_anki_candidates() -> Vec<PathBuf> {
    Vec::new()
}

fn anki_candidates_from_parts(
    env_anki_exe: Option<String>,
    local_app_data: Option<String>,
    registered_candidates: Vec<PathBuf>,
) -> Vec<PathBuf> {
    let mut candidates = Vec::new();

    if let Some(path) = env_anki_exe {
        push_unique_path(&mut candidates, PathBuf::from(path));
    }
    for path in registered_candidates {
        push_unique_path(&mut candidates, path);
    }
    if let Some(local_app_data) = local_app_data {
        let base = PathBuf::from(local_app_data);
        push_unique_path(
            &mut candidates,
            base.join("Programs").join("Anki").join("anki.exe"),
        );
        push_unique_path(
            &mut candidates,
            base.join("AnkiProgramFiles")
                .join(".venv")
                .join("Scripts")
                .join("ankiw.exe"),
        );
        push_unique_path(
            &mut candidates,
            base.join("AnkiProgramFiles")
                .join(".venv")
                .join("Scripts")
                .join("anki.exe"),
        );
    }
    for drive in ["C", "D", "E", "F", "G"] {
        push_unique_path(
            &mut candidates,
            PathBuf::from(format!(r"{drive}:\Anki\anki.exe")),
        );
    }
    push_unique_path(
        &mut candidates,
        PathBuf::from(r"C:\Program Files\Anki\anki.exe"),
    );
    push_unique_path(
        &mut candidates,
        PathBuf::from(r"C:\Program Files (x86)\Anki\anki.exe"),
    );

    candidates
}

fn anki_candidates() -> Vec<PathBuf> {
    anki_candidates_from_parts(
        env::var("ANKI_EXE").ok(),
        env::var("LOCALAPPDATA").ok(),
        registered_anki_candidates(),
    )
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
            if python.is_some() {
                "action"
            } else {
                "blocked"
            },
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
            if ffmpeg_path.is_empty() {
                "blocked"
            } else {
                "ok"
            },
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
            if python.is_some() {
                "action"
            } else {
                "blocked"
            },
            "需要 Python worker 运行后安装/检查。".to_string(),
            "点击一键修复安装 Python 依赖。",
        ),
        native_status_item(
            "yt_dlp",
            "yt-dlp URL 导入",
            if python.is_some() {
                "action"
            } else {
                "blocked"
            },
            "需要 Python worker 运行后安装/检查。".to_string(),
            "点击一键修复安装 Python 依赖。",
        ),
        native_status_item(
            "js_runtime",
            "Deno / Node challenge solver",
            if js_runtime.is_empty() {
                "action"
            } else {
                "ok"
            },
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
            if anki_path.is_some() {
                "action"
            } else {
                "blocked"
            },
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
    let lines: Vec<&str> = text
        .lines()
        .map(str::trim)
        .filter(|line| !line.is_empty())
        .collect();
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
fn repair_bootstrap_env(
    app: tauri::AppHandle,
    target: String,
) -> Result<BootstrapRepairResult, String> {
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

    let failed = actions
        .iter()
        .filter(|action| action.status == "failed")
        .count();
    let manual = actions
        .iter()
        .filter(|action| action.status == "manual")
        .count();
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

const SHA256_ROUND_CONSTANTS: [u32; 64] = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
];

struct LocalSha256 {
    state: [u32; 8],
    buffer: [u8; 64],
    buffer_len: usize,
    total_len: u64,
}

impl LocalSha256 {
    fn new() -> Self {
        Self {
            state: [
                0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab,
                0x5be0cd19,
            ],
            buffer: [0; 64],
            buffer_len: 0,
            total_len: 0,
        }
    }

    fn process_block(&mut self, block: &[u8; 64]) {
        let mut words = [0_u32; 64];
        for (index, bytes) in block.chunks_exact(4).take(16).enumerate() {
            words[index] = u32::from_be_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]);
        }
        for index in 16..64 {
            let sigma0 = words[index - 15].rotate_right(7)
                ^ words[index - 15].rotate_right(18)
                ^ (words[index - 15] >> 3);
            let sigma1 = words[index - 2].rotate_right(17)
                ^ words[index - 2].rotate_right(19)
                ^ (words[index - 2] >> 10);
            words[index] = words[index - 16]
                .wrapping_add(sigma0)
                .wrapping_add(words[index - 7])
                .wrapping_add(sigma1);
        }

        let mut a = self.state[0];
        let mut b = self.state[1];
        let mut c = self.state[2];
        let mut d = self.state[3];
        let mut e = self.state[4];
        let mut f = self.state[5];
        let mut g = self.state[6];
        let mut h = self.state[7];

        for index in 0..64 {
            let big_sigma1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let choose = (e & f) ^ ((!e) & g);
            let temporary1 = h
                .wrapping_add(big_sigma1)
                .wrapping_add(choose)
                .wrapping_add(SHA256_ROUND_CONSTANTS[index])
                .wrapping_add(words[index]);
            let big_sigma0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let majority = (a & b) ^ (a & c) ^ (b & c);
            let temporary2 = big_sigma0.wrapping_add(majority);

            h = g;
            g = f;
            f = e;
            e = d.wrapping_add(temporary1);
            d = c;
            c = b;
            b = a;
            a = temporary1.wrapping_add(temporary2);
        }

        self.state[0] = self.state[0].wrapping_add(a);
        self.state[1] = self.state[1].wrapping_add(b);
        self.state[2] = self.state[2].wrapping_add(c);
        self.state[3] = self.state[3].wrapping_add(d);
        self.state[4] = self.state[4].wrapping_add(e);
        self.state[5] = self.state[5].wrapping_add(f);
        self.state[6] = self.state[6].wrapping_add(g);
        self.state[7] = self.state[7].wrapping_add(h);
    }

    fn update(&mut self, bytes: &[u8]) {
        self.total_len = self.total_len.wrapping_add(bytes.len() as u64);
        let mut remaining = bytes;

        if self.buffer_len > 0 {
            let needed = 64 - self.buffer_len;
            let copied = needed.min(remaining.len());
            self.buffer[self.buffer_len..self.buffer_len + copied]
                .copy_from_slice(&remaining[..copied]);
            self.buffer_len += copied;
            remaining = &remaining[copied..];
            if self.buffer_len == 64 {
                let block = self.buffer;
                self.process_block(&block);
                self.buffer_len = 0;
            }
        }

        while remaining.len() >= 64 {
            let block: [u8; 64] = remaining[..64]
                .try_into()
                .expect("a 64-byte slice always converts to a SHA-256 block");
            self.process_block(&block);
            remaining = &remaining[64..];
        }

        if !remaining.is_empty() {
            self.buffer[..remaining.len()].copy_from_slice(remaining);
            self.buffer_len = remaining.len();
        }
    }

    fn finish(mut self) -> String {
        let bit_len = self.total_len.wrapping_mul(8);
        self.buffer[self.buffer_len] = 0x80;
        self.buffer_len += 1;

        if self.buffer_len > 56 {
            self.buffer[self.buffer_len..].fill(0);
            let block = self.buffer;
            self.process_block(&block);
            self.buffer = [0; 64];
            self.buffer_len = 0;
        }

        self.buffer[self.buffer_len..56].fill(0);
        self.buffer[56..64].copy_from_slice(&bit_len.to_be_bytes());
        let block = self.buffer;
        self.process_block(&block);

        self.state
            .iter()
            .map(|word| format!("{word:08x}"))
            .collect::<String>()
    }
}

fn sha256_file(path: &Path) -> Result<String, std::io::Error> {
    let file = fs::File::open(path)?;
    let mut reader = BufReader::new(file);
    let mut hasher = LocalSha256::new();
    let mut buffer = [0_u8; 64 * 1024];

    loop {
        let read = reader.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }

    Ok(hasher.finish())
}

fn recovery_file_failure(
    exists: bool,
    is_file: bool,
    size: Option<u64>,
    modified_at_ms: Option<u64>,
    code: &str,
    message: &str,
    retryable: bool,
) -> RecoveryFileInspection {
    RecoveryFileInspection {
        ok: false,
        exists,
        is_file,
        size,
        modified_at_ms,
        sha256: None,
        error: Some(RecoveryFileInspectionError {
            code: code.to_string(),
            message: message.to_string(),
            retryable,
        }),
    }
}

fn recovery_file_modified_at_ms(metadata: &fs::Metadata) -> Option<u64> {
    metadata
        .modified()
        .ok()?
        .duration_since(UNIX_EPOCH)
        .ok()
        .map(|duration| duration.as_millis().min(u128::from(u64::MAX)) as u64)
}

fn recovery_metadata_is_link_or_reparse(metadata: &fs::Metadata) -> bool {
    if metadata.file_type().is_symlink() {
        return true;
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x0000_0400;
        return metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0;
    }
    #[cfg(not(windows))]
    false
}

fn recovery_path_is_unsafe(path: &Path) -> bool {
    #[cfg(windows)]
    {
        let normalized = path
            .as_os_str()
            .to_string_lossy()
            .replace('/', "\\")
            .to_ascii_lowercase();
        if normalized.starts_with("\\\\.\\")
            || normalized.starts_with("\\\\?\\globalroot\\")
            || normalized.starts_with("\\\\?\\device\\")
            || normalized.starts_with("\\??\\")
        {
            return true;
        }

        let bytes = normalized.as_bytes();
        let allowed_colon = if bytes.len() >= 3
            && bytes[0].is_ascii_alphabetic()
            && bytes[1] == b':'
            && bytes[2] == b'\\'
        {
            Some(1)
        } else if bytes.len() >= 7
            && &bytes[..4] == b"\\\\?\\"
            && bytes[4].is_ascii_alphabetic()
            && bytes[5] == b':'
            && bytes[6] == b'\\'
        {
            Some(5)
        } else {
            None
        };
        if normalized
            .char_indices()
            .any(|(index, value)| value == ':' && Some(index) != allowed_colon)
        {
            return true;
        }

        if let Some(file_name) = path.file_name().and_then(|value| value.to_str()) {
            let normalized_name = file_name.trim_end_matches(|value| value == '.' || value == ' ');
            let stem = normalized_name.split('.').next().unwrap_or_default();
            if is_windows_reserved_file_stem(stem) {
                return true;
            }
        }
    }
    false
}
fn inspect_recovery_file_path(path: &Path, compute_sha256: bool) -> RecoveryFileInspection {
    if path.as_os_str().is_empty() || !path.is_absolute() {
        return recovery_file_failure(
            false,
            false,
            None,
            None,
            "INVALID_PATH",
            "Recovery evidence requires an absolute file path.",
            false,
        );
    }
    if recovery_path_is_unsafe(path) {
        return recovery_file_failure(
            false,
            false,
            None,
            None,
            "UNSAFE_PATH",
            "Device paths, alternate data streams, and reserved file names are not accepted.",
            false,
        );
    }

    let metadata = match fs::symlink_metadata(path) {
        Ok(metadata) => metadata,
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => {
            return RecoveryFileInspection {
                ok: true,
                exists: false,
                is_file: false,
                size: None,
                modified_at_ms: None,
                sha256: None,
                error: None,
            };
        }
        Err(_) => {
            return recovery_file_failure(
                false,
                false,
                None,
                None,
                "METADATA_UNAVAILABLE",
                "The file metadata could not be read.",
                true,
            );
        }
    };

    if recovery_metadata_is_link_or_reparse(&metadata) {
        return recovery_file_failure(
            true,
            false,
            None,
            None,
            "UNSAFE_FILE_TYPE",
            "Symbolic links and reparse links are not accepted as recovery evidence.",
            false,
        );
    }
    if !metadata.is_file() {
        return recovery_file_failure(
            true,
            false,
            None,
            None,
            "NOT_REGULAR_FILE",
            "Recovery evidence must be a regular file.",
            false,
        );
    }

    let size = metadata.len();
    let Some(modified_at_ms) = recovery_file_modified_at_ms(&metadata) else {
        return recovery_file_failure(
            true,
            true,
            Some(size),
            None,
            "MODIFIED_TIME_UNAVAILABLE",
            "The file modification time could not be read.",
            true,
        );
    };

    let sha256 = if compute_sha256 {
        match sha256_file(path) {
            Ok(digest) => Some(digest),
            Err(_) => {
                return recovery_file_failure(
                    true,
                    true,
                    Some(size),
                    Some(modified_at_ms),
                    "HASH_READ_FAILED",
                    "The file could not be read while calculating SHA-256.",
                    true,
                );
            }
        }
    } else {
        None
    };

    if compute_sha256 {
        let after = match fs::symlink_metadata(path) {
            Ok(metadata) => metadata,
            Err(_) => {
                return recovery_file_failure(
                    false,
                    false,
                    None,
                    None,
                    "FILE_CHANGED_DURING_INSPECTION",
                    "The file changed while it was being inspected.",
                    true,
                );
            }
        };
        if recovery_metadata_is_link_or_reparse(&after)
            || !after.is_file()
            || after.len() != size
            || recovery_file_modified_at_ms(&after) != Some(modified_at_ms)
        {
            return recovery_file_failure(
                true,
                after.is_file(),
                Some(after.len()),
                recovery_file_modified_at_ms(&after),
                "FILE_CHANGED_DURING_INSPECTION",
                "The file changed while it was being inspected.",
                true,
            );
        }
    }

    RecoveryFileInspection {
        ok: true,
        exists: true,
        is_file: true,
        size: Some(size),
        modified_at_ms: Some(modified_at_ms),
        sha256,
        error: None,
    }
}

#[tauri::command]
fn inspect_recovery_file(path: String, compute_sha256: bool) -> RecoveryFileInspection {
    let cleaned = clean_user_path(&path);
    inspect_recovery_file_path(Path::new(&cleaned), compute_sha256)
}
#[tauri::command]
fn check_output_directory(directory: String) -> Result<String, String> {
    let root = PathBuf::from(clean_user_path(&directory));
    if !root.exists() {
        return Ok("missing".to_string());
    }
    if !root.is_dir() {
        return Ok("not_writable".to_string());
    }

    let sequence = WORKFLOW_FILE_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let probe = root.join(format!(
        ".anki-card-generator-write-probe-{}-{}.tmp",
        std::process::id(),
        sequence
    ));
    let write_result = (|| -> Result<(), std::io::Error> {
        let mut file = fs::OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&probe)?;
        file.write_all(b"write-probe")?;
        file.sync_all()?;
        drop(file);
        fs::remove_file(&probe)?;
        Ok(())
    })();

    if write_result.is_err() {
        let _ = fs::remove_file(&probe);
        return Ok("not_writable".to_string());
    }
    Ok("writable".to_string())
}

#[tauri::command]
fn list_directory_files(directory: String) -> Result<Vec<String>, String> {
    let root = PathBuf::from(clean_user_path(&directory));
    if !root.exists() || !root.is_dir() {
        return Err(format!("目录不存在或不是文件夹：{}", root.display()));
    }
    let root = root
        .canonicalize()
        .map_err(|err| format!("无法解析目录 {}：{err}", root.display()))?;
    if directory_listing_root_blocked(&root) {
        return Err(
            "出于安全考虑，不能批量枚举系统根目录或敏感系统目录。请选择素材所在的普通文件夹。"
                .to_string(),
        );
    }
    let mut files = Vec::new();
    let mut stack = vec![(root.clone(), 0usize)];
    while let Some((current, depth)) = stack.pop() {
        let entries = fs::read_dir(&current)
            .map_err(|err| format!("无法读取目录 {}：{err}", current.display()))?;
        for entry in entries {
            let path = entry
                .map_err(|err| format!("无法读取目录项：{err}"))?
                .path();
            if path.is_dir() {
                if depth < DIRECTORY_LIST_MAX_DEPTH && !directory_listing_root_blocked(&path) {
                    stack.push((path, depth + 1));
                }
            } else if path.is_file() && file_extension_supported_for_bulk_import(&path) {
                files.push(path.display().to_string());
            }
            if files.len() > DIRECTORY_LIST_MAX_FILES {
                return Err(format!(
                    "文件夹内可导入文件超过 {} 个，请先拆成更小的学习包。",
                    DIRECTORY_LIST_MAX_FILES
                ));
            }
        }
    }
    files.sort_by(|left, right| left.to_lowercase().cmp(&right.to_lowercase()));
    Ok(files)
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

fn file_extension_supported_for_bulk_import(path: &Path) -> bool {
    path.extension()
        .and_then(|value| value.to_str())
        .map(|value| {
            SUPPORTED_BULK_FILE_EXTENSIONS
                .iter()
                .any(|allowed| value.eq_ignore_ascii_case(allowed))
        })
        .unwrap_or(false)
}

fn preview_video_extension_supported(path: &Path) -> bool {
    path.extension()
        .and_then(|value| value.to_str())
        .map(|value| {
            SUPPORTED_PREVIEW_VIDEO_EXTENSIONS
                .iter()
                .any(|allowed| value.eq_ignore_ascii_case(allowed))
        })
        .unwrap_or(false)
}

fn resolve_preview_asset_path(path: &Path) -> Result<PathBuf, String> {
    if !path.exists() || !path.is_file() {
        return Err(format!("预览媒体不存在或不是文件：{}", path.display()));
    }
    let resolved = path
        .canonicalize()
        .map_err(|err| format!("无法解析预览媒体 {}：{err}", path.display()))?;
    if !preview_video_extension_supported(&resolved) {
        return Err("只允许预览 mp4、mkv、webm、mov、m4v 或 avi 视频文件。".to_string());
    }
    Ok(resolved)
}

fn preview_asset_frontend_path(path: &Path) -> String {
    let value = path.to_string_lossy();
    #[cfg(windows)]
    {
        if let Some(stripped) = value.strip_prefix(r"\\?\UNC\") {
            return format!(r"\\{}", stripped);
        }
        if let Some(stripped) = value.strip_prefix(r"\\?\") {
            return stripped.to_string();
        }
    }
    value.into_owned()
}

#[tauri::command]
fn allow_preview_asset(app: tauri::AppHandle, path: String) -> Result<String, String> {
    let requested = PathBuf::from(clean_user_path(&path));
    let resolved = resolve_preview_asset_path(&requested)?;
    app.asset_protocol_scope()
        .allow_file(&resolved)
        .map_err(|err| format!("无法授权此预览媒体：{err}"))?;
    Ok(preview_asset_frontend_path(&resolved))
}
fn directory_listing_root_blocked(path: &Path) -> bool {
    let Ok(resolved) = path.canonicalize() else {
        return true;
    };
    if resolved.parent().is_none() || resolved.parent() == Some(resolved.as_path()) {
        return true;
    }
    let Some(name) = resolved.file_name().and_then(|value| value.to_str()) else {
        return true;
    };
    let lower = name.to_ascii_lowercase();
    SENSITIVE_DIRECTORY_NAMES
        .iter()
        .any(|blocked| lower == *blocked)
}

fn generated_apkg_directory(path: &Path) -> bool {
    let Some(parent) = path.parent() else {
        return false;
    };
    let parent_name = parent
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or_default();
    parent_name.starts_with("AnkiCard-")
        && (parent.join("audio_audit.json").is_file() || parent.join("audio_audit.md").is_file())
}

fn anki_import_path_allowed(app: &tauri::AppHandle, target: &Path) -> bool {
    if !target.is_file()
        || !target
            .extension()
            .and_then(|value| value.to_str())
            .map(|value| value.eq_ignore_ascii_case("apkg"))
            .unwrap_or(false)
    {
        return false;
    }

    if generated_apkg_directory(target) {
        return true;
    }

    if let Ok(app_data) = app.path().app_local_data_dir() {
        if path_is_within(target, &app_data) {
            return true;
        }
    }

    if let Ok(cwd) = env::current_dir() {
        for root in [
            cwd.join("release"),
            cwd.join("test_runs"),
            cwd.join("anki_live_e2e"),
        ] {
            if root.exists() && path_is_within(target, &root) {
                return true;
            }
        }
    }

    false
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

fn configure_anki_import_process(command: &mut Command, launch_dir: &Path) {
    command.current_dir(launch_dir);

    #[cfg(windows)]
    {
        // Anki's package importer persists extracted media with an atomic rename.
        // Keep every temporary-file convention, plus the process working directory,
        // on the same user-data volume so Windows does not raise ERROR_NOT_SAME_DEVICE
        // (os error 17) when the desktop app itself was launched from another drive.
        command.env("TEMP", launch_dir);
        command.env("TMP", launch_dir);
        command.env("TMPDIR", launch_dir);
    }
}

fn anki_import_runtime_dir(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let launch_dir = app
        .path()
        .app_local_data_dir()
        .map_err(|err| format!("无法确定 Anki 导入临时目录：{err}"))?
        .join("anki-import-runtime");
    fs::create_dir_all(&launch_dir).map_err(|err| format!("无法准备 Anki 导入临时目录：{err}"))?;
    Ok(launch_dir)
}

#[tauri::command]
fn ensure_anki_running(app: tauri::AppHandle) -> Result<(), String> {
    if process_running("anki.exe") {
        return Ok(());
    }

    let anki = find_anki()?;
    let launch_dir = anki_import_runtime_dir(&app)?;
    let mut command = Command::new(anki);
    configure_anki_import_process(&mut command, &launch_dir);
    detach_gui_process(&mut command);
    command
        .spawn()
        .map_err(|err| format!("无法启动 Anki：{err}"))?;
    Ok(())
}

#[tauri::command]
fn open_anki_import(app: tauri::AppHandle, apkg_path: String) -> Result<(), String> {
    let apkg = PathBuf::from(apkg_path);
    if !apkg.exists() {
        return Err(format!("apkg 文件不存在：{}", apkg.display()));
    }
    let apkg = apkg
        .canonicalize()
        .map_err(|err| format!("无法解析 apkg 路径：{err}"))?;
    if !anki_import_path_allowed(&app, &apkg) {
        return Err("只能导入本应用刚导出或测试目录中的 .apkg 文件。".to_string());
    }
    if !apkg.is_file()
        || !apkg
            .extension()
            .and_then(|value| value.to_str())
            .map(|value| value.eq_ignore_ascii_case("apkg"))
            .unwrap_or(false)
    {
        return Err("只能导入 .apkg 文件。".to_string());
    }

    let anki = find_anki()?;
    let launch_dir = anki_import_runtime_dir(&app)?;
    let mut command = Command::new(anki);
    command.arg(apkg);
    configure_anki_import_process(&mut command, &launch_dir);
    detach_gui_process(&mut command);
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
fn secret_exists(key: String) -> Result<bool, String> {
    Ok(load_secret(key)?
        .map(|value| !value.trim().is_empty())
        .unwrap_or(false))
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
    std::panic::set_hook(Box::new(|panic_info| {
        let payload = json!({
            "schema_version": 1,
            "source": "rust_panic_hook",
            "recorded_at_ms": now_unix_ms(),
            "thread": thread::current().name().unwrap_or("<unnamed>"),
            "message": panic_info.to_string(),
            "location": panic_info.location().map(|location| json!({
                "file": location.file(),
                "line": location.line(),
                "column": location.column(),
            })),
        });
        write_workspace_diagnostic_file(".tauri-panic-current.json", &payload);
    }));
    tauri::Builder::default()
        .manage(WorkerJobs::default())
        .manage(WindowCloseGuard::default())
        .manage(HermesProxyRuntime::default())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            run_worker,
            check_bootstrap_env,
            repair_bootstrap_env,
            start_worker_job,
            allow_next_window_close,
            disallow_next_window_close,
            cancel_worker_job,
            force_cancel_worker_job,
            get_worker_job_status,
            get_worker_task,
            list_recoverable_worker_tasks,
            read_worker_job_result,
            acknowledge_worker_task_result,
            check_output_directory,
            inspect_recovery_file,
            record_renderer_error,
            save_workflow_checkpoint,
            load_workflow_checkpoint,
            load_workflow_checkpoint_backup,
            clear_workflow_checkpoint,
            write_workflow_artifact,
            read_workflow_artifact,
            suggest_subtitle_path,
            list_directory_files,
            allow_preview_asset,
            reveal_path,
            ensure_anki_running,
            open_anki_import,
            check_hermes_proxy,
            start_hermes_proxy,
            stop_owned_hermes_proxy,
            save_secret,
            load_secret,
            secret_exists,
            delete_secret
        ])
        .setup(|app| {
            let mut built_new_window = false;
            let window = match app.get_webview_window("main") {
                Some(window) => window,
                None => {
                    built_new_window = true;
                    WebviewWindowBuilder::new(app, "main", WebviewUrl::App("/".into()))
                        .title("Anki 卡片生成器")
                        .inner_size(1540.0, 1080.0)
                        .min_inner_size(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
                        .resizable(true)
                        .decorations(false)
                        .visible(true)
                        .build()?
                }
            };
            let lifecycle_app = app.handle().clone();
            let lifecycle_window = window.clone();
            window.on_window_event(move |event| {
                if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                    let close_guard = lifecycle_app.state::<WindowCloseGuard>();
                    if close_guard.allow_next_close.swap(false, Ordering::SeqCst) {
                        let runtime = lifecycle_app.state::<HermesProxyRuntime>();
                        let _ = stop_managed_hermes(runtime.inner());
                    } else {
                        api.prevent_close();
                        let worker_active = lifecycle_app
                            .state::<WorkerJobs>()
                            .jobs
                            .lock()
                            .map(|jobs| !jobs.is_empty())
                            .unwrap_or(true);
                        let _ = lifecycle_window.emit(
                            "app-close-requested",
                            json!({ "workerActive": worker_active }),
                        );
                    }
                }
                let event_debug = format!("{event:?}");
                let event_name = event_debug
                    .split([' ', '{', '('])
                    .next()
                    .unwrap_or("unknown")
                    .to_string();
                write_window_lifecycle_diagnostic(
                    &lifecycle_app,
                    &lifecycle_window,
                    &event_name,
                    event_debug,
                );
            });
            let min_size_result = window.set_min_size(Some(Size::Logical(LogicalSize {
                width: MIN_WINDOW_WIDTH,
                height: MIN_WINDOW_HEIGHT,
            })));
            let unminimize_result = window.unminimize();
            let center_result = window.center();
            let show_result = window.show();
            let focus_result = window.set_focus();

            write_startup_diagnostic(json!({
                "schema_version": 1,
                "source": "src-tauri/src/lib.rs",
                "phase": "setup",
                "timestamp_ms": now_unix_ms(),
                "pid": std::process::id(),
                "workspace": workspace_root_for_startup_diagnostics(),
                "window": {
                    "label": "main",
                    "title": "Anki 卡片生成器",
                    "built_new_window": built_new_window,
                    "state": window_state_to_json(&window),
                },
                "operations": {
                    "set_min_size": unit_result_to_json(&min_size_result),
                    "unminimize": unit_result_to_json(&unminimize_result),
                    "center": unit_result_to_json(&center_result),
                    "show": unit_result_to_json(&show_result),
                    "set_focus": unit_result_to_json(&focus_result),
                }
            }));

            min_size_result?;
            if let Err(err) = unminimize_result {
                eprintln!("Window unminimize failed during startup: {err}");
            }
            if let Err(err) = center_result {
                eprintln!("Window center failed during startup: {err}");
            }
            show_result?;
            if let Err(err) = focus_result {
                eprintln!("Window focus failed during startup: {err}");
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
    fn parse_windows_open_command_extracts_registered_anki_executable() {
        assert_eq!(
            parse_windows_open_command_executable(r#"D:\Anki\anki.exe "%L""#),
            Some(PathBuf::from(r"D:\Anki\anki.exe")),
        );
        assert_eq!(
            parse_windows_open_command_executable(r#""C:\Program Files\Anki\anki.exe" "%1""#),
            Some(PathBuf::from(r"C:\Program Files\Anki\anki.exe")),
        );
    }

    #[test]
    fn anki_candidates_prefer_registered_launcher_over_embedded_venv_shim() {
        let candidates = anki_candidates_from_parts(
            None,
            Some(r"C:\Users\Example\AppData\Local".to_string()),
            vec![PathBuf::from(r"D:\Anki\anki.exe")],
        );

        let registered_index = candidates
            .iter()
            .position(|path| path == &PathBuf::from(r"D:\Anki\anki.exe"))
            .expect("registered launcher candidate");
        let embedded_shim_index = candidates
            .iter()
            .position(|path| {
                path == &PathBuf::from(
                    r"C:\Users\Example\AppData\Local\AnkiProgramFiles\.venv\Scripts\anki.exe",
                )
            })
            .expect("embedded venv shim candidate");

        assert!(registered_index < embedded_shim_index);
    }

    #[test]
    fn anki_candidates_include_common_drive_root_install() {
        let candidates = anki_candidates_from_parts(None, None, Vec::new());

        assert!(candidates.contains(&PathBuf::from(r"D:\Anki\anki.exe")));
    }

    #[test]
    fn anki_import_process_uses_isolated_working_and_temp_directory() {
        let launch_dir =
            PathBuf::from(r"C:\Users\Example\AppData\Local\AnkiCardGenerator\anki-import-runtime");
        let mut command = Command::new(r"C:\Program Files\Anki\anki.exe");

        configure_anki_import_process(&mut command, &launch_dir);

        assert_eq!(command.get_current_dir(), Some(launch_dir.as_path()));
        #[cfg(windows)]
        {
            let configured: std::collections::HashMap<_, _> = command
                .get_envs()
                .filter_map(|(name, value)| value.map(|value| (name.to_owned(), value.to_owned())))
                .collect();
            for name in ["TEMP", "TMP", "TMPDIR"] {
                assert_eq!(
                    configured
                        .get(std::ffi::OsStr::new(name))
                        .map(|value| value.as_os_str()),
                    Some(launch_dir.as_os_str()),
                );
            }
        }
    }

    #[test]
    fn hermes_health_parser_requires_xai_identity_and_reports_auth() {
        let ready = concat!(
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n",
            r#"{"status":"ok","upstream":"xAI Grok OAuth","authenticated":true}"#
        );
        let not_ready = concat!(
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n",
            r#"{"status":"ok","upstream":"xAI Grok OAuth","authenticated":false}"#
        );
        let unrelated = concat!(
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n",
            r#"{"status":"ok","upstream":"other","authenticated":true}"#
        );

        assert_eq!(parse_hermes_health_response(ready), Some(true));
        assert_eq!(parse_hermes_health_response(not_ready), Some(false));
        assert_eq!(parse_hermes_health_response(unrelated), None);
    }

    #[test]
    fn hermes_proxy_parser_prefers_https_and_rejects_non_http_schemes() {
        assert_eq!(
            select_http_proxy_server("http=127.0.0.1:8080;https=127.0.0.1:8443"),
            Some("http://127.0.0.1:8443".to_string())
        );
        assert_eq!(
            select_http_proxy_server("https://proxy.example:443"),
            Some("https://proxy.example:443".to_string())
        );
        assert_eq!(select_http_proxy_server("socks5://127.0.0.1:1080"), None);
        assert_eq!(select_http_proxy_server("not-a-proxy"), None);
    }

    #[test]
    fn bulk_directory_listing_only_accepts_supported_extensions() {
        assert!(file_extension_supported_for_bulk_import(Path::new(
            "clip.mp4"
        )));
        assert!(file_extension_supported_for_bulk_import(Path::new(
            "notes.MD"
        )));
        assert!(file_extension_supported_for_bulk_import(Path::new(
            "subs.srt"
        )));
        assert!(!file_extension_supported_for_bulk_import(Path::new(
            "secret.exe"
        )));
        assert!(!file_extension_supported_for_bulk_import(Path::new(
            "archive.zip"
        )));
    }

    #[test]
    fn preview_asset_only_accepts_supported_video_files() {
        assert!(preview_video_extension_supported(Path::new("lesson.MP4")));
        assert!(preview_video_extension_supported(Path::new("lesson.webm")));
        assert!(!preview_video_extension_supported(Path::new("lesson.html")));
        assert!(!preview_video_extension_supported(Path::new("lesson.apkg")));
    }

    #[test]
    fn preview_asset_resolver_rejects_non_video_files() {
        let root = env::temp_dir().join(format!(
            "anki_card_preview_asset_test_{}",
            std::process::id()
        ));
        fs::create_dir_all(&root).expect("create preview test dir");
        let text_file = root.join("not-video.txt");
        fs::write(&text_file, b"not a video").expect("write preview test file");

        let error = resolve_preview_asset_path(&text_file).expect_err("reject non-video file");
        assert!(error.contains("只允许预览"));

        let _ = fs::remove_dir_all(root);
    }
    #[test]
    fn generated_apkg_directory_requires_export_marker() {
        let root = env::temp_dir().join(format!(
            "anki_card_generated_apkg_test_{}",
            std::process::id()
        ));
        let export_dir = root.join("AnkiCard-unit-test");
        fs::create_dir_all(&export_dir).expect("create export test dir");
        let apkg = export_dir.join("deck.apkg");
        fs::write(&apkg, b"apkg").expect("write apkg");

        assert!(!generated_apkg_directory(&apkg));
        fs::write(export_dir.join("audio_audit.json"), "{}").expect("write marker");
        assert!(generated_apkg_directory(&apkg));

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn workflow_checkpoint_rejects_non_empty_secrets() {
        for payload in [
            json!({"api_key": "should-not-be-here"}),
            json!({"apiKey": "should-not-be-here"}),
            json!({"oauth_token": "secret"}),
            json!({"headers": {"Authorization": "Bearer secret"}}),
            json!({"client_secret": {"value": "secret"}}),
            json!({"token_value": "secret"}),
            json!({"private_key": "secret"}),
        ] {
            assert!(checkpoint_contains_secret(&payload));
        }

        assert!(!checkpoint_contains_secret(&json!({
            "request": {
                "api_config": {
                    "api_key": "",
                    "auth_mode": "oauth"
                }
            },
            "has_api_key": true,
            "credential_revision": 3,
            "client_secret_ref": "keyring:model"
        })));
    }

    #[test]
    fn workflow_artifact_reference_rejects_path_traversal_and_windows_devices() {
        assert!(validate_workflow_artifact_ref("project-123.json").is_ok());
        assert!(validate_workflow_artifact_ref("../project.json").is_err());
        assert!(validate_workflow_artifact_ref(r"C:\temp\project.json").is_err());
        assert!(validate_workflow_artifact_ref("nested/project.json").is_err());
        assert!(validate_workflow_artifact_ref("project.exe").is_err());
        assert!(validate_workflow_artifact_ref("CON.json").is_err());
        assert!(validate_workflow_artifact_ref("lpt1.json").is_err());
        assert!(validate_workflow_artifact_ref("CON.backup.json").is_err());
    }

    #[test]
    fn workflow_checkpoint_backup_candidate_keeps_size_and_secret_guards() {
        let root = env::temp_dir().join(format!(
            "anki_card_checkpoint_backup_candidate_{}",
            workflow_file_suffix()
        ));
        fs::create_dir_all(&root).expect("create checkpoint backup test dir");
        let backup = root.join("checkpoint.json.bak");

        fs::write(&backup, br#"{"schemaVersion":1}"#).expect("write valid backup");
        assert_eq!(
            load_workflow_checkpoint_candidate(&backup, "检查点备份")
                .expect("load valid backup")
                .expect("backup exists")["schemaVersion"],
            1
        );

        fs::write(&backup, br#"{"api_key":"secret"}"#).expect("write secret backup");
        assert!(load_workflow_checkpoint_candidate(&backup, "检查点备份").is_err());

        fs::write(
            &backup,
            vec![b' '; WORKFLOW_CHECKPOINT_MAX_BYTES as usize + 1],
        )
        .expect("write oversized backup");
        assert!(load_workflow_checkpoint_candidate(&backup, "检查点备份").is_err());

        let _ = fs::remove_dir_all(root);
    }
    #[test]
    fn workflow_checkpoint_write_keeps_previous_backup() {
        let root = env::temp_dir().join(format!(
            "anki_card_checkpoint_test_{}",
            workflow_file_suffix()
        ));
        fs::create_dir_all(&root).expect("create checkpoint test dir");
        let path = root.join("checkpoint.json");
        let backup = root.join("checkpoint.json.bak");

        write_json_with_backup(
            &path,
            Some(&backup),
            &json!({"version": 1}),
            WORKFLOW_CHECKPOINT_MAX_BYTES,
        )
        .expect("write first checkpoint");
        write_json_with_backup(
            &path,
            Some(&backup),
            &json!({"version": 2}),
            WORKFLOW_CHECKPOINT_MAX_BYTES,
        )
        .expect("write second checkpoint");

        assert_eq!(
            read_json_file_with_limit(&path, WORKFLOW_CHECKPOINT_MAX_BYTES)
                .expect("read checkpoint")["version"],
            2
        );
        assert_eq!(
            read_json_file_with_limit(&backup, WORKFLOW_CHECKPOINT_MAX_BYTES).expect("read backup")
                ["version"],
            1
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn workflow_checkpoint_does_not_replace_valid_backup_with_corrupt_primary() {
        let root = env::temp_dir().join(format!(
            "anki_card_checkpoint_corrupt_test_{}",
            workflow_file_suffix()
        ));
        fs::create_dir_all(&root).expect("create checkpoint test dir");
        let path = root.join("checkpoint.json");
        let backup = root.join("checkpoint.json.bak");

        write_json_with_backup(
            &path,
            Some(&backup),
            &json!({"version": 1}),
            WORKFLOW_CHECKPOINT_MAX_BYTES,
        )
        .expect("write first checkpoint");
        write_json_with_backup(
            &path,
            Some(&backup),
            &json!({"version": 2}),
            WORKFLOW_CHECKPOINT_MAX_BYTES,
        )
        .expect("write second checkpoint");
        fs::write(&path, b"corrupt").expect("corrupt current checkpoint");
        write_json_with_backup(
            &path,
            Some(&backup),
            &json!({"version": 3}),
            WORKFLOW_CHECKPOINT_MAX_BYTES,
        )
        .expect("replace corrupt checkpoint");

        assert_eq!(
            read_json_file_with_limit(&path, WORKFLOW_CHECKPOINT_MAX_BYTES)
                .expect("read repaired checkpoint")["version"],
            3
        );
        assert_eq!(
            read_json_file_with_limit(&backup, WORKFLOW_CHECKPOINT_MAX_BYTES)
                .expect("read preserved backup")["version"],
            1
        );
        let leftovers = fs::read_dir(&root)
            .expect("list checkpoint directory")
            .filter_map(Result::ok)
            .filter_map(|entry| entry.file_name().to_str().map(str::to_owned))
            .filter(|name| name.contains(".tmp.") || name.contains(".rollback."))
            .collect::<Vec<_>>();
        assert!(
            leftovers.is_empty(),
            "unexpected temporary files: {leftovers:?}"
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn worker_task_snapshot_exposes_running_and_cancelling_state() {
        let mut job = RunningJob {
            pid: 42,
            command: "extract_learning_points".to_string(),
            cancel_requested: false,
            failure_message: None,
            started_at_ms: 1_000,
            updated_at_ms: 1_000,
            progress: worker_task_initial_progress(1_000),
            input_fingerprint: "summary:test".to_string(),
        };
        job.progress = update_worker_task_progress(
            &job.progress,
            &json!({
                "stage": "extract",
                "stage_label": "Extracting",
                "percent": 45,
                "message": "Reading subtitles",
                "completed_batches": 1,
                "total_batches": 4
            }),
            2_000,
        );
        job.updated_at_ms = 2_000;

        let running = job.snapshot("extract-1");
        assert_eq!(running.state, "running");
        assert_eq!(running.progress.overall_percent, Some(45.0));
        assert_eq!(running.progress.completed_batches, Some(1));
        assert!(running.cancellable);

        job.cancel_requested = true;
        job.updated_at_ms = 3_000;
        let cancelling = job.snapshot("extract-1");
        assert_eq!(cancelling.state, "cancelling");
        assert!(!cancelling.cancellable);
        assert_eq!(cancelling.updated_at, 3_000);
    }

    #[test]
    fn persisted_worker_result_is_resolved_after_in_memory_index_is_lost() {
        let root = env::temp_dir().join(format!(
            "anki_card_worker_result_recovery_{}",
            workflow_file_suffix()
        ));
        fs::create_dir_all(&root).expect("create result recovery directory");
        let job_id = "verify_anki_import-123-safe";
        let result_path = root.join(format!("{job_id}.json"));
        fs::write(&result_path, br#"{"ok":true,"failed_checks":[]}"#)
            .expect("write persisted worker result");

        assert_eq!(
            resolve_worker_result_path(&root, job_id, None).expect("resolve persisted result"),
            result_path
        );
        assert!(resolve_worker_result_path(&root, "../escape", None).is_err());
        assert!(resolve_worker_result_path(&root, "CON", None).is_err());

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn persisted_worker_task_loader_distinguishes_missing_valid_and_corrupt_state() {
        let root = env::temp_dir().join(format!(
            "anki_card_worker_task_loader_{}",
            workflow_file_suffix()
        ));
        let missing = load_persisted_worker_tasks_from_dir(&root)
            .expect("missing task directory should be empty");
        assert!(missing.tasks.is_empty());
        assert!(missing.errors.is_empty());
        fs::create_dir_all(&root).expect("create worker task loader directory");

        let job_id = "recoverable-task-1";
        let snapshot = WorkerTaskSnapshot {
            schema_version: WORKER_TASK_SNAPSHOT_SCHEMA_VERSION,
            id: job_id.to_string(),
            command: "export".to_string(),
            state: "interrupted".to_string(),
            started_at: 1_000,
            updated_at: 2_000,
            progress: worker_task_initial_progress(1_000),
            cancellable: false,
            input_fingerprint: "request-v1-12ab34cd".to_string(),
            result_ref: None,
            error: None,
        };
        fs::write(
            root.join(format!("{job_id}.json")),
            serde_json::to_vec(&snapshot).expect("serialize worker task snapshot"),
        )
        .expect("write valid worker task snapshot");
        fs::write(root.join(".ignored.json.tmp.1"), b"not json")
            .expect("write ignored temporary snapshot");
        fs::write(root.join(".ignored.json.rollback.1"), b"not json")
            .expect("write ignored rollback snapshot");

        let loaded =
            load_persisted_worker_tasks_from_dir(&root).expect("load valid persisted worker task");
        assert_eq!(loaded.tasks.len(), 1);
        assert_eq!(loaded.tasks[0].id, job_id);
        assert!(loaded.errors.is_empty());

        fs::write(root.join("corrupt-task.json"), b"{not-json")
            .expect("write corrupt official task snapshot");
        let partially_loaded = load_persisted_worker_tasks_from_dir(&root)
            .expect("a corrupt snapshot must not hide valid recovery evidence");
        assert_eq!(partially_loaded.tasks.len(), 1);
        assert_eq!(partially_loaded.tasks[0].id, job_id);
        assert_eq!(partially_loaded.errors.len(), 1);
        assert!(partially_loaded.errors[0].contains("corrupt-task"));
        assert!(partially_loaded.errors[0].contains("Cannot read persisted worker task"));

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn worker_result_store_atomically_replaces_complete_json_without_leftovers() {
        let root = env::temp_dir().join(format!(
            "anki_card_worker_result_atomic_{}",
            workflow_file_suffix()
        ));
        fs::create_dir_all(&root).expect("create worker result directory");
        let job_id = "atomic-result-1";

        store_worker_job_result_in_dir(&root, job_id, &json!({"version": 1, "ok": true}))
            .expect("store first result");
        let (_, result_path, size) =
            store_worker_job_result_in_dir(&root, job_id, &json!({"version": 2, "ok": true}))
                .expect("atomically replace result");
        assert!(size > 0);
        let stored: Value = serde_json::from_slice(
            &fs::read(&result_path).expect("read atomically replaced result"),
        )
        .expect("result remains complete JSON");
        assert_eq!(stored["version"], 2);
        assert!(store_worker_job_result_in_dir(&root, "../escape", &json!({})).is_err());

        let leftovers = fs::read_dir(&root)
            .expect("list result directory")
            .filter_map(Result::ok)
            .filter_map(|entry| entry.file_name().to_str().map(str::to_owned))
            .filter(|name| name.contains(".tmp.") || name.contains(".rollback."))
            .collect::<Vec<_>>();
        assert!(
            leftovers.is_empty(),
            "unexpected temporary files: {leftovers:?}"
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn acknowledged_success_is_removed_from_memory_and_durable_recovery() {
        let root = env::temp_dir().join(format!(
            "anki_card_worker_ack_success_{}",
            workflow_file_suffix()
        ));
        fs::create_dir_all(&root).expect("create acknowledgement test directory");
        let job_id = "export-ack-success";
        let task_path = root.join("task.json");
        let result_path = root.join("result.json");
        fs::write(&task_path, b"task").expect("write task snapshot");
        fs::write(&result_path, br#"{"ok":true}"#).expect("write task result");
        let status = WorkerJobStatus {
            job_id: job_id.to_string(),
            command: "export".to_string(),
            ok: true,
            cancelled: false,
            result_ref: Some(job_id.to_string()),
            result_size_bytes: Some(11),
            result_summary: None,
            error: None,
            error_code: None,
            stage: None,
            retryable: None,
            fallbacks: None,
            details: None,
            finished_at_ms: 2_000,
        };
        let snapshot = completed_worker_task_snapshot(&status, None);
        let mut history = CompletedWorkerJobs::default();
        history.order.push_back(job_id.to_string());
        history.entries.insert(
            job_id.to_string(),
            CompletedWorkerJob {
                status,
                snapshot,
                result_path: Some(result_path.clone()),
            },
        );

        let acknowledged =
            acknowledge_completed_worker_task(&mut history, job_id, None, &task_path, &result_path)
                .expect("acknowledge successful result");
        assert!(acknowledged.acknowledged);
        assert_eq!(acknowledged.state.as_deref(), Some("succeeded"));
        assert!(!history.entries.contains_key(job_id));
        assert!(!history.order.iter().any(|entry| entry == job_id));
        assert!(!task_path.exists());
        assert!(!result_path.exists());

        let repeated =
            acknowledge_completed_worker_task(&mut history, job_id, None, &task_path, &result_path)
                .expect("idempotent acknowledgement");
        assert!(!repeated.acknowledged);
        assert!(repeated.state.is_none());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn acknowledgement_preserves_failed_and_running_task_diagnostics() {
        let root = env::temp_dir().join(format!(
            "anki_card_worker_ack_diagnostics_{}",
            workflow_file_suffix()
        ));
        fs::create_dir_all(&root).expect("create acknowledgement diagnostics directory");
        for state in ["failed", "running"] {
            let task_path = root.join(format!("{state}-task.json"));
            let result_path = root.join(format!("{state}-result.json"));
            fs::write(&task_path, b"task").expect("write diagnostic task snapshot");
            fs::write(&result_path, b"diagnostic").expect("write diagnostic result");
            let snapshot = WorkerTaskSnapshot {
                schema_version: WORKER_TASK_SNAPSHOT_SCHEMA_VERSION,
                id: format!("{state}-ack-diagnostic"),
                command: "export".to_string(),
                state: state.to_string(),
                started_at: 1_000,
                updated_at: 2_000,
                progress: worker_task_initial_progress(1_000),
                cancellable: state == "running",
                input_fingerprint: "request-v1-12ab34cd".to_string(),
                result_ref: None,
                error: (state == "failed").then(|| WorkerTaskFailureSnapshot {
                    code: "EXPORT_FAILED".to_string(),
                    message: "diagnostic must remain".to_string(),
                    retryable: true,
                    phase: Some("export".to_string()),
                    detail: None,
                }),
            };
            let mut history = CompletedWorkerJobs::default();
            let acknowledgement = acknowledge_completed_worker_task(
                &mut history,
                &snapshot.id,
                Some(snapshot.clone()),
                &task_path,
                &result_path,
            )
            .expect("reject non-success acknowledgement");
            assert!(!acknowledgement.acknowledged);
            assert_eq!(acknowledgement.state.as_deref(), Some(state));
            assert!(task_path.exists());
            assert!(result_path.exists());
        }
        let _ = fs::remove_dir_all(root);
    }
    #[test]
    fn worker_request_fingerprint_is_forwarded_only_when_safely_encoded() {
        let summary = json!({ "command": "extract_learning_points" });
        let fallback = worker_input_fingerprint(&summary);
        let request_fingerprint = "request-v1-12ab34cd";

        assert_eq!(
            validated_worker_input_fingerprint(Some(request_fingerprint), &summary),
            request_fingerprint
        );
        for invalid in [
            "short",
            "request-v1-12ab34cd\nforged",
            "request/v1/12ab34cd",
            "request v1 12ab34cd",
        ] {
            assert_eq!(
                validated_worker_input_fingerprint(Some(invalid), &summary),
                fallback
            );
        }
        assert_eq!(
            validated_worker_input_fingerprint(Some(&"a".repeat(129)), &summary),
            fallback
        );
        assert_eq!(validated_worker_input_fingerprint(None, &summary), fallback);
    }
    #[test]
    fn worker_task_progress_is_monotonic_and_terminal_success_reaches_one_hundred() {
        let initial = update_worker_task_progress(
            &worker_task_initial_progress(1_000),
            &json!({ "stage": "generate", "percent": 80, "message": "Batch 2" }),
            2_000,
        );
        let regressed = update_worker_task_progress(
            &initial,
            &json!({ "stage": "audio", "percent": 10, "message": "Audio" }),
            3_000,
        );
        assert_eq!(regressed.overall_percent, Some(80.0));
        assert_eq!(regressed.phase_percent, Some(10.0));

        let job = RunningJob {
            pid: 42,
            command: "generate_cards_from_learning_points".to_string(),
            cancel_requested: false,
            failure_message: None,
            started_at_ms: 1_000,
            updated_at_ms: 3_000,
            progress: regressed,
            input_fingerprint: "summary:test".to_string(),
        };
        let status = WorkerJobStatus {
            job_id: "generate-1".to_string(),
            command: job.command.clone(),
            ok: true,
            cancelled: false,
            result_ref: Some("generate-1".to_string()),
            result_size_bytes: Some(128),
            result_summary: None,
            error: None,
            error_code: None,
            stage: None,
            retryable: None,
            fallbacks: None,
            details: None,
            finished_at_ms: 4_000,
        };

        let completed = completed_worker_task_snapshot(&status, Some(&job));
        assert_eq!(completed.state, "succeeded");
        assert_eq!(completed.progress.overall_percent, Some(100.0));
        assert_eq!(completed.result_ref.as_deref(), Some("generate-1"));
        assert!(!completed.cancellable);
    }

    #[test]
    fn orphaned_running_worker_task_becomes_interrupted() {
        let job = RunningJob {
            pid: 42,
            command: "export".to_string(),
            cancel_requested: false,
            failure_message: None,
            started_at_ms: 1_000,
            updated_at_ms: 2_000,
            progress: worker_task_initial_progress(1_000),
            input_fingerprint: "summary:test".to_string(),
        };

        let interrupted = mark_orphaned_worker_task_interrupted(job.snapshot("export-1"));
        assert_eq!(interrupted.state, "interrupted");
        assert!(!interrupted.cancellable);
        assert_eq!(
            interrupted.error.as_ref().map(|error| error.code.as_str()),
            Some("WORKER_INTERRUPTED")
        );
    }

    #[test]
    fn kill_command_exit_status_is_not_silently_ignored() {
        assert!(validate_kill_command_status("taskkill", 42, true, Some(0)).is_ok());
        let error = validate_kill_command_status("taskkill", 42, false, Some(128))
            .expect_err("non-zero taskkill status must fail");
        assert!(error.contains("128"));
        assert!(error.contains("42"));
    }

    #[test]
    fn cancelling_job_still_blocks_start_and_kill_failure_keeps_it_running() {
        let running = Arc::new(Mutex::new(HashMap::<String, RunningJob>::new()));
        running.lock().expect("running worker jobs").insert(
            "export-1".to_string(),
            RunningJob {
                pid: 42,
                command: "export".to_string(),
                cancel_requested: false,
                failure_message: None,
                started_at_ms: 1_000,
                updated_at_ms: 2_000,
                progress: worker_task_initial_progress(1_000),
                input_fingerprint: "request-v1-12ab34cd".to_string(),
            },
        );

        let cancelling = mark_running_worker_force_cancelling(&running, "export-1")
            .expect("mark cancelling")
            .expect("running job");
        assert!(cancelling.cancel_requested);
        assert!(validate_kill_command_status("taskkill", cancelling.pid, false, Some(1)).is_err());

        let active = running.lock().expect("running worker jobs");
        assert!(active.contains_key("export-1"));
        assert!(active
            .get("export-1")
            .is_some_and(|job| job.cancel_requested));
        assert!(ensure_worker_start_slot(&active).is_err());
    }

    #[test]
    fn force_cancel_converges_active_job_and_rejects_late_completion() {
        let completed = Arc::new(Mutex::new(CompletedWorkerJobs::default()));
        let running = Arc::new(Mutex::new(HashMap::<String, RunningJob>::new()));
        let mut job = RunningJob {
            pid: 42,
            command: "generate_cards_from_learning_points".to_string(),
            cancel_requested: true,
            failure_message: None,
            started_at_ms: 1_000,
            updated_at_ms: 2_000,
            progress: worker_task_initial_progress(1_000),
            input_fingerprint: "summary:test".to_string(),
        };
        job.progress.phase = "cancelling".to_string();
        running
            .lock()
            .expect("running worker jobs")
            .insert("generate-1".to_string(), job.clone());

        let (forced_status, forced_snapshot) =
            forced_cancelled_worker_completion("generate-1", &job, 3_000);
        assert!(commit_completed_worker_job(
            &running,
            &completed,
            forced_status,
            forced_snapshot,
            None,
        ));
        assert!(!running
            .lock()
            .expect("running worker jobs")
            .contains_key("generate-1"));

        let late_success = WorkerJobStatus {
            job_id: "generate-1".to_string(),
            command: job.command.clone(),
            ok: true,
            cancelled: false,
            result_ref: Some("generate-1".to_string()),
            result_size_bytes: Some(128),
            result_summary: None,
            error: None,
            error_code: None,
            stage: None,
            retryable: None,
            fallbacks: None,
            details: None,
            finished_at_ms: 4_000,
        };
        let late_snapshot = completed_worker_task_snapshot(&late_success, Some(&job));
        assert!(!remember_completed_worker_job(
            &completed,
            late_success,
            late_snapshot,
            Some(PathBuf::from("late-result.json")),
        ));

        let history = completed.lock().expect("completed worker history");
        let terminal = history.entries.get("generate-1").expect("forced terminal");
        assert_eq!(terminal.snapshot.state, "cancelled");
        assert!(terminal.status.cancelled);
        assert!(!terminal.status.ok);
        assert!(terminal.result_path.is_none());
        assert_eq!(history.order.len(), 1);
    }

    #[test]
    fn force_cancel_marks_unmanaged_running_snapshot_interrupted() {
        let job = RunningJob {
            pid: 42,
            command: "export".to_string(),
            cancel_requested: true,
            failure_message: None,
            started_at_ms: 1_000,
            updated_at_ms: 2_000,
            progress: worker_task_initial_progress(1_000),
            input_fingerprint: "summary:test".to_string(),
        };
        let (status, snapshot) = forced_interrupted_worker_completion(
            job.snapshot("export-1"),
            3_000,
            "任务进程已经失去管理。".to_string(),
        );

        assert!(!status.cancelled);
        assert_eq!(
            status.error_code.as_deref(),
            Some("WORKER_FORCE_CANCEL_INTERRUPTED")
        );
        assert_eq!(snapshot.state, "interrupted");
        assert!(!snapshot.cancellable);
        assert_eq!(snapshot.updated_at, 3_000);
        assert_eq!(
            snapshot.error.as_ref().map(|error| error.code.as_str()),
            Some("WORKER_FORCE_CANCEL_INTERRUPTED")
        );
        let result = worker_force_cancel_result(Some(&snapshot));
        assert!(result.found);
        assert!(!result.cancelled);
        assert_eq!(result.state, "interrupted");
    }

    #[test]
    fn worker_idle_timeouts_match_the_product_contract() {
        assert_eq!(worker_idle_timeout("check_env").as_secs(), 60);
        assert_eq!(worker_idle_timeout("repair_env").as_secs(), 15 * 60);
        assert_eq!(worker_idle_timeout("test_api").as_secs(), 120);
        assert_eq!(worker_idle_timeout("test_tts").as_secs(), 120);
        assert_eq!(
            worker_idle_timeout("extract_learning_points").as_secs(),
            5 * 60
        );
        assert_eq!(
            worker_idle_timeout("generate_cards_from_learning_points").as_secs(),
            7 * 60
        );
        assert_eq!(worker_idle_timeout("generate").as_secs(), 10 * 60);
        assert_eq!(worker_idle_timeout("export").as_secs(), 10 * 60);
        assert_eq!(worker_idle_timeout("verify_anki_import").as_secs(), 2 * 60);
    }

    #[test]
    fn local_sha256_matches_known_vectors_and_fragmented_updates() {
        assert_eq!(
            LocalSha256::new().finish(),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );

        let mut fragmented = LocalSha256::new();
        fragmented.update(b"a");
        fragmented.update(b"b");
        fragmented.update(b"c");
        assert_eq!(
            fragmented.finish(),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
    }
    #[test]
    fn recovery_file_inspection_returns_streamed_sha256_and_file_identity() {
        let root = env::temp_dir().join(format!(
            "anki_recovery_evidence_test_{}_{}",
            std::process::id(),
            now_unix_ms()
        ));
        assert!(root.starts_with(env::temp_dir()));
        fs::create_dir_all(&root).expect("create recovery evidence test directory");
        let apkg = root.join("cards.apkg");
        fs::write(&apkg, b"abc").expect("write recovery evidence");

        let evidence = inspect_recovery_file_path(&apkg, true);
        assert!(evidence.ok);
        assert!(evidence.exists);
        assert!(evidence.is_file);
        assert_eq!(evidence.size, Some(3));
        assert!(evidence.modified_at_ms.is_some());
        assert_eq!(
            evidence.sha256.as_deref(),
            Some("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
        );
        assert!(evidence.error.is_none());
        let serialized = serde_json::to_value(&evidence).expect("serialize recovery evidence");
        assert_eq!(serialized["isFile"], true);
        assert_eq!(serialized["modifiedAtMs"].as_u64(), evidence.modified_at_ms);

        let identity_only = inspect_recovery_file_path(&apkg, false);
        assert!(identity_only.ok);
        assert_eq!(identity_only.size, Some(3));
        assert!(identity_only.sha256.is_none());

        let missing = inspect_recovery_file_path(&root.join("missing.mp4"), false);
        assert!(missing.ok);
        assert!(!missing.exists);
        assert!(!missing.is_file);

        let directory = inspect_recovery_file_path(&root, false);
        assert!(!directory.ok);
        assert_eq!(
            directory.error.as_ref().map(|error| error.code.as_str()),
            Some("NOT_REGULAR_FILE")
        );

        let relative = inspect_recovery_file_path(Path::new("relative.apkg"), true);
        assert!(!relative.ok);
        assert_eq!(
            relative.error.as_ref().map(|error| error.code.as_str()),
            Some("INVALID_PATH")
        );

        #[cfg(windows)]
        {
            for unsafe_path in [
                r"\\.\PhysicalDrive0",
                r"\\?\GLOBALROOT\Device\HarddiskVolumeShadowCopy1\cards.apkg",
                r"C:\safe\cards.apkg:stream",
                r"C:\safe\NUL.apkg",
            ] {
                let unsafe_evidence = inspect_recovery_file_path(Path::new(unsafe_path), true);
                assert!(
                    !unsafe_evidence.ok,
                    "path should be rejected: {unsafe_path}"
                );
                assert_eq!(
                    unsafe_evidence
                        .error
                        .as_ref()
                        .map(|error| error.code.as_str()),
                    Some("UNSAFE_PATH")
                );
            }
            use std::os::windows::fs::symlink_file;
            let link = root.join("cards-link.apkg");
            if symlink_file(&apkg, &link).is_ok() {
                let linked = inspect_recovery_file_path(&link, true);
                assert!(!linked.ok);
                assert_eq!(
                    linked.error.as_ref().map(|error| error.code.as_str()),
                    Some("UNSAFE_FILE_TYPE")
                );
                let _ = fs::remove_file(link);
            }
        }

        fs::remove_dir_all(root).expect("remove recovery evidence test directory");
    }

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
