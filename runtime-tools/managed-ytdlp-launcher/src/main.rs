use std::env;
use std::ffi::OsString;
use std::path::{Path, PathBuf};
use std::process::{self, Command};

const EXIT_LAUNCHER_FAILURE: i32 = 125;

fn packaged_python_path(launcher: &Path) -> Result<PathBuf, &'static str> {
    let tools = launcher
        .parent()
        .ok_or("managed yt-dlp launcher has no tools directory")?;
    let root = tools
        .parent()
        .ok_or("managed yt-dlp launcher has no runtime root")?;
    #[cfg(windows)]
    let python = root.join("python").join("python.exe");
    #[cfg(not(windows))]
    let python = root.join("python").join("python");
    Ok(python)
}

fn run() -> Result<i32, String> {
    let launcher = env::current_exe()
        .map_err(|error| format!("managed yt-dlp launcher path is unavailable: {error}"))?
        .canonicalize()
        .map_err(|error| format!("managed yt-dlp launcher path is unsafe: {error}"))?;
    let python = packaged_python_path(&launcher)?;
    let python = python
        .canonicalize()
        .map_err(|error| format!("packaged Python is unavailable: {error}"))?;
    let root = launcher
        .parent()
        .and_then(Path::parent)
        .ok_or_else(|| "managed runtime root is unavailable".to_owned())?;
    if !python.is_file() || !python.starts_with(root) {
        return Err("packaged Python escaped the managed runtime root".to_owned());
    }

    let arguments: Vec<OsString> = env::args_os().skip(1).collect();
    let status = Command::new(&python)
        .arg("-I")
        .arg("-B")
        .arg("-m")
        .arg("yt_dlp")
        .args(arguments)
        .env_remove("PYTHONHOME")
        .env_remove("PYTHONPATH")
        .env_remove("PYTHONSTARTUP")
        .env("PYTHONDONTWRITEBYTECODE", "1")
        .status()
        .map_err(|error| format!("packaged yt-dlp could not start: {error}"))?;
    Ok(status.code().unwrap_or(EXIT_LAUNCHER_FAILURE))
}

fn main() {
    match run() {
        Ok(code) => process::exit(code),
        Err(message) => {
            eprintln!("{message}");
            process::exit(EXIT_LAUNCHER_FAILURE);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::packaged_python_path;
    use std::path::Path;

    #[test]
    fn resolves_python_only_from_the_sibling_runtime_directory() {
        #[cfg(windows)]
        assert_eq!(
            packaged_python_path(Path::new(r"C:\runtime\tools\yt-dlp.exe")).unwrap(),
            Path::new(r"C:\runtime\python\python.exe")
        );
        #[cfg(not(windows))]
        assert_eq!(
            packaged_python_path(Path::new("/runtime/tools/yt-dlp")).unwrap(),
            Path::new("/runtime/python/python")
        );
    }

    #[test]
    fn rejects_a_launcher_without_the_runtime_layout() {
        assert!(packaged_python_path(Path::new("yt-dlp.exe")).is_err());
    }
}
