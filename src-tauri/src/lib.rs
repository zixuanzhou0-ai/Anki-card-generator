#[cfg_attr(mobile, tauri::mobile_entry_point)]
use std::{
    collections::{HashMap, VecDeque},
    env, fs,
    io::{BufRead, BufReader, Read, Write},
    net::TcpStream,
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::{Arc, Mutex},
    thread,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

use serde::Serialize;
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
    cancel_requested: bool,
    failure_message: Option<String>,
}

#[derive(Clone, Default)]
struct CompletedWorkerJobs {
    entries: HashMap<String, CompletedWorkerJob>,
    order: VecDeque<String>,
}

#[derive(Clone)]
struct CompletedWorkerJob {
    status: WorkerJobStatus,
    result_path: Option<PathBuf>,
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
    let Ok(mut stream) = TcpStream::connect_timeout(&socket_address, Duration::from_millis(350)) else {
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
        HermesHealthProbe::Hermes { authenticated: true } => status(
            "ready",
            if managed {
                "Hermes Grok 4.5 本机代理已由应用启动并通过 OAuth 健康检查。"
            } else {
                "检测到已运行的 Hermes Grok 4.5 本机代理，应用将直接复用。"
            },
            true,
        ),
        HermesHealthProbe::Hermes { authenticated: false } => status(
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
    if current.state == "ready" || current.state == "missing" || current.state == "oauth_unready" || current.state == "port_conflict" {
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
    command.stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null());
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
            HermesHealthProbe::Hermes { authenticated: true }
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
fn stop_owned_hermes_proxy(state: State<'_, HermesProxyRuntime>) -> Result<HermesProxyStatus, String> {
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
        "extract_learning_points" => Duration::from_secs(300),
        "generate_cards_from_learning_points" => Duration::from_secs(420),
        "generate" | "export" => Duration::from_secs(600),
        "test_tts" => Duration::from_secs(75),
        "test_api" | "verify_anki_import" => Duration::from_secs(120),
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
    if let Ok(mut file) = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
    {
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

fn write_window_lifecycle_diagnostic(app: &tauri::AppHandle, window: &tauri::WebviewWindow, event_name: &str, event_debug: String) {
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

fn store_worker_job_result(
    app: &tauri::AppHandle,
    job_id: &str,
    result: &Value,
) -> Result<(String, PathBuf, u64), String> {
    let dir = worker_job_result_dir(app);
    fs::create_dir_all(&dir).map_err(|err| format!("无法创建 worker 结果目录：{err}"))?;
    let result_path = dir.join(format!("{job_id}.json"));
    let bytes =
        serde_json::to_vec(result).map_err(|err| format!("无法序列化 worker 结果：{err}"))?;
    fs::write(&result_path, &bytes).map_err(|err| format!("无法写入 worker 结果文件：{err}"))?;
    Ok((job_id.to_string(), result_path, bytes.len() as u64))
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
    result_path: Option<PathBuf>,
) {
    if let Ok(mut history) = completed.lock() {
        if !history.entries.contains_key(&status.job_id) {
            history.order.push_back(status.job_id.clone());
        }
        history.entries.insert(
            status.job_id.clone(),
            CompletedWorkerJob {
                status,
                result_path,
            },
        );
        while history.order.len() > COMPLETED_WORKER_JOB_LIMIT {
            if let Some(old_job_id) = history.order.pop_front() {
                history.entries.remove(&old_job_id);
            }
        }
    }
}

fn complete_worker_job_and_emit(
    app: &tauri::AppHandle,
    completed: &Arc<Mutex<CompletedWorkerJobs>>,
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
    let status_diagnostic =
        serde_json::to_value(&status).unwrap_or_else(|err| json!({ "serialize_error": err.to_string() }));
    remember_completed_worker_job(completed, status, result_path);
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
    let payload_summary = worker_payload_summary(&command, &payload, input.len());
    reset_dual_text_file(&app, ".worker-stderr-current.log");
    reset_dual_text_file(&app, ".worker-progress-current.log");
    reset_dual_text_file(&app, ".worker-stdout-current.log");

    if command == "generate_cards_from_learning_points" && input.len() > GENERATE_WORKER_PAYLOAD_LIMIT_BYTES {
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
                        let progress_value = value.clone();
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
                let _ = kill_process_tree(pid);
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
            .and_then(|mut jobs| jobs.remove(&finish_job_id));
        let cancelled = job_state
            .as_ref()
            .map(|job| job.cancel_requested)
            .unwrap_or(false);
        let failure_message = job_state.and_then(|job| job.failure_message);
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
                &completed_for_finish,
                &finish_job_id,
                &finish_command,
                false,
                None,
                Some(format!("无法读取 worker JSON 输出：{err}")),
                None,
                cancelled,
            );
            return;
        }

        match wait_result {
            Ok(status) if status.success() && !cancelled => {
                match serde_json::from_str::<serde_json::Value>(&stdout_text) {
                    Ok(result) => complete_worker_job_and_emit(
                        &app_for_finish,
                        &completed_for_finish,
                        &finish_job_id,
                        &finish_command,
                        true,
                        Some(result),
                        None,
                        None,
                        false,
                    ),
                    Err(err) => complete_worker_job_and_emit(
                        &app_for_finish,
                        &completed_for_finish,
                        &finish_job_id,
                        &finish_command,
                        false,
                        None,
                        Some(format!("worker 输出不是有效 JSON：{err}")),
                        None,
                        false,
                    ),
                }
            }
            Ok(_) if cancelled => complete_worker_job_and_emit(
                &app_for_finish,
                &completed_for_finish,
                &finish_job_id,
                &finish_command,
                false,
                None,
                Some("任务已取消。".to_string()),
                None,
                true,
            ),
            Ok(_) if failure_message.is_some() => complete_worker_job_and_emit(
                &app_for_finish,
                &completed_for_finish,
                &finish_job_id,
                &finish_command,
                false,
                None,
                failure_message,
                None,
                false,
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
                    &completed_for_finish,
                    &finish_job_id,
                    &finish_command,
                    false,
                    None,
                    Some(message),
                    error_details,
                    false,
                );
            }
            Err(err) => complete_worker_job_and_emit(
                &app_for_finish,
                &completed_for_finish,
                &finish_job_id,
                &finish_command,
                false,
                None,
                Some(format!("worker 执行失败：{err}")),
                None,
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
fn read_worker_job_result(jobs: State<WorkerJobs>, job_id: String) -> Result<Value, String> {
    let result_path = {
        let history = jobs
            .completed
            .lock()
            .map_err(|_| "无法读取后台任务结果索引。".to_string())?;
        history
            .entries
            .get(&job_id)
            .and_then(|entry| entry.result_path.clone())
            .ok_or_else(|| "后台任务结果不存在，可能需要重新运行。".to_string())?
    };
    let text = fs::read_to_string(&result_path)
        .map_err(|err| format!("无法读取后台任务结果文件：{err}"))?;
    serde_json::from_str(&text).map_err(|err| format!("后台任务结果不是有效 JSON：{err}"))
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
    push_unique_path(&mut candidates, PathBuf::from(r"C:\Program Files\Anki\anki.exe"));
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
        return Err("出于安全考虑，不能批量枚举系统根目录或敏感系统目录。请选择素材所在的普通文件夹。".to_string());
    }
    let mut files = Vec::new();
    let mut stack = vec![(root.clone(), 0usize)];
    while let Some((current, depth)) = stack.pop() {
        let entries = fs::read_dir(&current).map_err(|err| format!("无法读取目录 {}：{err}", current.display()))?;
        for entry in entries {
            let path = entry.map_err(|err| format!("无法读取目录项：{err}"))?.path();
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
    if !apkg.is_file() || !apkg.extension().and_then(|value| value.to_str()).map(|value| value.eq_ignore_ascii_case("apkg")).unwrap_or(false) {
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
        .manage(HermesProxyRuntime::default())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            run_worker,
            check_bootstrap_env,
            repair_bootstrap_env,
            start_worker_job,
            cancel_worker_job,
            get_worker_job_status,
            read_worker_job_result,
            record_renderer_error,
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
                if matches!(event, tauri::WindowEvent::CloseRequested { .. }) {
                    let runtime = lifecycle_app.state::<HermesProxyRuntime>();
                    let _ = stop_managed_hermes(runtime.inner());
                }
                let event_debug = format!("{event:?}");
                let event_name = event_debug
                    .split([' ', '{', '('])
                    .next()
                    .unwrap_or("unknown")
                    .to_string();
                write_window_lifecycle_diagnostic(&lifecycle_app, &lifecycle_window, &event_name, event_debug);
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
        assert!(file_extension_supported_for_bulk_import(Path::new("clip.mp4")));
        assert!(file_extension_supported_for_bulk_import(Path::new("notes.MD")));
        assert!(file_extension_supported_for_bulk_import(Path::new("subs.srt")));
        assert!(!file_extension_supported_for_bulk_import(Path::new("secret.exe")));
        assert!(!file_extension_supported_for_bulk_import(Path::new("archive.zip")));
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
