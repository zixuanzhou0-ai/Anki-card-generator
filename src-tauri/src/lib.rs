#[cfg_attr(mobile, tauri::mobile_entry_point)]
use std::{
  env,
  fs,
  io::{BufRead, BufReader, Read, Write},
  path::{Path, PathBuf},
  process::{Command, Stdio},
  sync::{Arc, Mutex},
  thread,
};

use tauri::{Emitter, Manager};

fn worker_candidates(app: &tauri::AppHandle) -> Vec<PathBuf> {
  let mut candidates = Vec::new();

  if let Ok(cwd) = env::current_dir() {
    candidates.push(cwd.join("workers").join("anki_worker.py"));
    candidates.push(cwd.join("..").join("workers").join("anki_worker.py"));
  }

  if let Ok(resource_dir) = app.path().resource_dir() {
    candidates.push(resource_dir.join("workers").join("anki_worker.py"));
    candidates.push(resource_dir.join("..").join("workers").join("anki_worker.py"));
  }

  if let Ok(exe) = env::current_exe() {
    for ancestor in exe.ancestors().take(8) {
      candidates.push(ancestor.join("workers").join("anki_worker.py"));
      candidates.push(ancestor.join("..").join("workers").join("anki_worker.py"));
      candidates.push(ancestor.join("..").join("..").join("workers").join("anki_worker.py"));
    }
  }

  candidates
}

fn find_worker(app: &tauri::AppHandle) -> Result<PathBuf, String> {
  worker_candidates(app)
    .into_iter()
    .find(|path| path.exists())
    .ok_or_else(|| "找不到 Python worker：workers/anki_worker.py".to_string())
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

#[tauri::command]
fn run_worker(
  app: tauri::AppHandle,
  command: String,
  payload: serde_json::Value,
) -> Result<serde_json::Value, String> {
  let worker = find_worker(&app)?;
  let input = serde_json::to_vec(&payload).map_err(|err| err.to_string())?;
  let work_dir = worker_work_dir(&app, &worker);

  let mut child = Command::new("python")
    .arg(&worker)
    .arg(command)
    .current_dir(work_dir)
    .env("PYTHONIOENCODING", "utf-8")
    .stdin(Stdio::piped())
    .stdout(Stdio::piped())
    .stderr(Stdio::piped())
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
  let app_for_progress = app.clone();
  let progress_thread = thread::spawn(move || {
    let reader = BufReader::new(stderr);
    for line in reader.lines().map_while(Result::ok) {
      if let Some(payload) = line.strip_prefix("__ANKI_CARD_PROGRESS__") {
        if let Ok(value) = serde_json::from_str::<serde_json::Value>(payload) {
          let _ = app_for_progress.emit("worker-progress", value);
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
    let message = if stderr.trim().is_empty() {
      stdout_text
    } else {
      stderr
    };
    return Err(message.trim().to_string());
  }

  serde_json::from_str(&stdout_text)
    .map_err(|err| format!("worker 输出不是有效 JSON：{err}"))
}

fn anki_candidates() -> Vec<PathBuf> {
  let mut candidates = Vec::new();

  if let Ok(path) = env::var("ANKI_EXE") {
    candidates.push(PathBuf::from(path));
  }
  if let Ok(local_app_data) = env::var("LOCALAPPDATA") {
    let base = PathBuf::from(local_app_data);
    candidates.push(base.join("AnkiProgramFiles").join(".venv").join("Scripts").join("anki.exe"));
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
    .ok_or_else(|| "找不到 Anki。请确认已安装 Anki，或设置 ANKI_EXE 指向 anki.exe。".to_string())
}

#[tauri::command]
fn open_anki_import(apkg_path: String) -> Result<(), String> {
  let apkg = PathBuf::from(apkg_path);
  if !apkg.exists() {
    return Err(format!("apkg 文件不存在：{}", apkg.display()));
  }

  let anki = find_anki()?;
  Command::new(anki)
    .arg(apkg)
    .spawn()
    .map_err(|err| format!("无法启动 Anki：{err}"))?;
  Ok(())
}

#[tauri::command]
fn reveal_path(path: String) -> Result<(), String> {
  let target = PathBuf::from(path);
  if !target.exists() {
    return Err(format!("路径不存在：{}", target.display()));
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

pub fn run() {
  tauri::Builder::default()
    .plugin(tauri_plugin_dialog::init())
    .invoke_handler(tauri::generate_handler![run_worker, reveal_path, open_anki_import])
    .setup(|app| {
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
