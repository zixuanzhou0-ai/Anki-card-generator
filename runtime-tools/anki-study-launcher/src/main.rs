mod release_verifier;

use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::{HashMap, HashSet};
use std::env;
use std::ffi::{OsStr, OsString};
use std::fs::{self, File, Metadata};
use std::io::{Read, Write};
use std::path::{Component, Path, PathBuf};
use std::process::{self, Command, Stdio};

const EXIT_LAUNCHER_FAILURE: i32 = 125;
const MAX_MANIFEST_BYTES: u64 = 4 * 1024 * 1024;
const MAX_TRUST_POLICY_BYTES: u64 = 256 * 1024;
const MAX_RUNTIME_FILES: usize = 50_000;
const MAX_RUNTIME_DEPTH: usize = 32;
const MANIFEST_NAME: &str = "runtime-package-v1.json";
const SIGNATURE_NAME: &str = "runtime-package-v1.sig.json";
const TRUST_POLICY_NAME: &str = "runtime-publisher-trust-v1.json";
const EXPECTED_RUNTIME_MANIFEST_SHA256: Option<&str> =
    option_env!("ANKI_STUDY_RUNTIME_MANIFEST_SHA256");
const EXPECTED_RUNTIME_TRUST_POLICY_SHA256: Option<&str> =
    option_env!("ANKI_STUDY_RUNTIME_TRUST_POLICY_SHA256");
const EXPECTED_PLUGIN_INSTALL_TRUST_POLICY_SHA256: Option<&str> =
    option_env!("ANKI_STUDY_PLUGIN_INSTALL_TRUST_POLICY_SHA256");

#[derive(Debug)]
struct LauncherLayout {
    plugin_root: PathBuf,
    runtime_root: PathBuf,
    trust_policy: PathBuf,
}

fn trace(message: &str) {
    if env::var_os("ANKI_STUDY_LAUNCHER_TRACE").as_deref() == Some(OsStr::new("1")) {
        eprintln!("[anki-study-launcher] {message}");
    }
}

fn is_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn expected_digest<'a>(value: Option<&'a str>, label: &str) -> Result<&'a str, String> {
    let value =
        value.ok_or_else(|| format!("{label} was not pinned when the launcher was built"))?;
    if !is_sha256(value) {
        return Err(format!("{label} pin is invalid"));
    }
    Ok(value)
}

fn hex_digest(value: impl AsRef<[u8]>) -> String {
    value
        .as_ref()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn has_reparse_attribute(metadata: &Metadata) -> bool {
    if metadata.file_type().is_symlink() {
        return true;
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        metadata.file_attributes() & 0x400 != 0
    }
    #[cfg(not(windows))]
    {
        false
    }
}

fn assert_no_reparse_ancestors(path: &Path) -> Result<(), String> {
    if !path.is_absolute() {
        return Err("launcher path must be absolute".to_owned());
    }
    let mut current = PathBuf::new();
    for component in path.components() {
        current.push(component.as_os_str());
        if matches!(component, Component::Prefix(_)) {
            continue;
        }
        let metadata = fs::symlink_metadata(&current)
            .map_err(|_| "launcher path is unavailable".to_owned())?;
        if has_reparse_attribute(&metadata) {
            return Err("launcher path contains a reparse point".to_owned());
        }
    }
    Ok(())
}

fn stable_file_within(root: &Path, relative: &Path) -> Result<PathBuf, String> {
    let candidate = root.join(relative);
    let mut current = root.to_path_buf();
    for component in relative.components() {
        if !matches!(component, Component::Normal(_)) {
            return Err("runtime resource path is unsafe".to_owned());
        }
        current.push(component.as_os_str());
        let metadata = fs::symlink_metadata(&current)
            .map_err(|_| "runtime resource is unavailable".to_owned())?;
        if has_reparse_attribute(&metadata) {
            return Err("runtime resource path contains a reparse point".to_owned());
        }
    }
    let resolved = candidate
        .canonicalize()
        .map_err(|_| "runtime resource cannot be resolved".to_owned())?;
    if !resolved.starts_with(root) || !resolved.is_file() {
        return Err("runtime resource escaped its package root".to_owned());
    }
    Ok(resolved)
}

fn sha256_file(path: &Path) -> Result<(u64, String), String> {
    let mut file = File::open(path).map_err(|_| "trusted file cannot be opened".to_owned())?;
    let size = file
        .metadata()
        .map_err(|_| "trusted file metadata is unavailable".to_owned())?
        .len();
    let mut digest = Sha256::new();
    let mut buffer = vec![0_u8; 1024 * 1024];
    loop {
        let count = file
            .read(&mut buffer)
            .map_err(|_| "trusted file cannot be read".to_owned())?;
        if count == 0 {
            break;
        }
        digest.update(&buffer[..count]);
    }
    Ok((size, hex_digest(digest.finalize())))
}

fn read_bounded(path: &Path, maximum: u64, label: &str) -> Result<Vec<u8>, String> {
    let size = path
        .metadata()
        .map_err(|_| format!("{label} metadata is unavailable"))?
        .len();
    if size == 0 || size > maximum {
        return Err(format!("{label} is empty or too large"));
    }
    let file = File::open(path).map_err(|_| format!("{label} cannot be opened"))?;
    let mut source = Vec::with_capacity(size as usize);
    file.take(maximum + 1)
        .read_to_end(&mut source)
        .map_err(|_| format!("{label} cannot be read"))?;
    if source.is_empty() || source.len() as u64 > maximum {
        return Err(format!("{label} is empty or too large"));
    }
    Ok(source)
}

fn windows_reserved_name(part: &str) -> bool {
    let stem = part
        .trim_end_matches([' ', '.'])
        .split('.')
        .next()
        .unwrap_or("");
    let upper = stem.to_ascii_uppercase();
    matches!(upper.as_str(), "CON" | "PRN" | "AUX" | "NUL" | "CLOCK$")
        || (upper.len() == 4
            && (upper.starts_with("COM") || upper.starts_with("LPT"))
            && matches!(upper.as_bytes()[3], b'1'..=b'9'))
}

fn runtime_relative_path(value: &str) -> Result<(String, PathBuf), String> {
    if value.is_empty()
        || value.contains('\\')
        || value.contains(':')
        || value.contains('\0')
        || value.starts_with('/')
    {
        return Err("runtime manifest contains an invalid path".to_owned());
    }
    let mut path = PathBuf::new();
    let mut normalized = Vec::new();
    for part in value.split('/') {
        if part.is_empty()
            || part == "."
            || part == ".."
            || part != part.trim_end_matches([' ', '.'])
            || windows_reserved_name(part)
        {
            return Err("runtime manifest contains an unsafe path component".to_owned());
        }
        path.push(part);
        normalized.push(part);
    }
    Ok((normalized.join("/"), path))
}

fn relative_utf8(root: &Path, path: &Path) -> Result<String, String> {
    let relative = path
        .strip_prefix(root)
        .map_err(|_| "runtime file escaped its package root".to_owned())?;
    let mut parts = Vec::new();
    for component in relative.components() {
        let Component::Normal(part) = component else {
            return Err("runtime file path is invalid".to_owned());
        };
        parts.push(
            part.to_str()
                .ok_or_else(|| "runtime file path is not UTF-8".to_owned())?,
        );
    }
    Ok(parts.join("/"))
}

fn collect_runtime_files(
    root: &Path,
    directory: &Path,
    depth: usize,
    files: &mut HashSet<String>,
) -> Result<(), String> {
    if depth > MAX_RUNTIME_DEPTH {
        return Err("runtime package directory depth exceeds the launcher limit".to_owned());
    }
    let mut entries = fs::read_dir(directory)
        .map_err(|_| "runtime package directory cannot be read".to_owned())?
        .collect::<Result<Vec<_>, _>>()
        .map_err(|_| "runtime package directory entry is unavailable".to_owned())?;
    entries.sort_by_key(|entry| entry.file_name());
    for entry in entries {
        let path = entry.path();
        let metadata = fs::symlink_metadata(&path)
            .map_err(|_| "runtime package entry metadata is unavailable".to_owned())?;
        if has_reparse_attribute(&metadata) {
            return Err("runtime package contains a reparse point".to_owned());
        }
        if metadata.is_dir() {
            collect_runtime_files(root, &path, depth + 1, files)?;
        } else if metadata.is_file() {
            let relative = relative_utf8(root, &path)?;
            if !files.insert(relative.to_ascii_lowercase()) || files.len() > MAX_RUNTIME_FILES {
                return Err("runtime package contains duplicate or too many files".to_owned());
            }
        } else {
            return Err("runtime package contains an unsupported entry".to_owned());
        }
    }
    Ok(())
}

fn verify_runtime_package(root: &Path, expected_manifest_sha256: &str) -> Result<PathBuf, String> {
    trace("verifying runtime root");
    assert_no_reparse_ancestors(root)?;
    let root = root
        .canonicalize()
        .map_err(|_| "runtime package root cannot be resolved".to_owned())?;
    if !root.is_dir() {
        return Err("runtime package root is not a directory".to_owned());
    }
    let manifest_path = stable_file_within(&root, Path::new(MANIFEST_NAME))?;
    let manifest_source = read_bounded(&manifest_path, MAX_MANIFEST_BYTES, "runtime manifest")?;
    let manifest_digest = hex_digest(Sha256::digest(&manifest_source));
    if manifest_digest != expected_manifest_sha256 {
        return Err("runtime manifest does not match the launcher pin".to_owned());
    }
    let manifest: Value = serde_json::from_slice(&manifest_source)
        .map_err(|_| "runtime manifest is not valid JSON".to_owned())?;
    trace("runtime manifest parsed");
    let object = manifest
        .as_object()
        .ok_or_else(|| "runtime manifest is not an object".to_owned())?;
    if object.get("schemaVersion").and_then(Value::as_u64) != Some(1)
        || object.get("packageId").and_then(Value::as_str) != Some("anki-study-managed-runtime")
    {
        return Err("runtime manifest identity is invalid".to_owned());
    }
    let resources = object
        .get("resources")
        .and_then(Value::as_array)
        .ok_or_else(|| "runtime manifest resources are missing".to_owned())?;
    if resources.is_empty() || resources.len() > MAX_RUNTIME_FILES {
        return Err("runtime manifest resource count is invalid".to_owned());
    }

    let mut expected_paths = HashSet::new();
    let mut resource_ids = HashSet::new();
    let mut resources_by_id = HashMap::new();
    for (index, resource) in resources.iter().enumerate() {
        if index % 500 == 0 {
            trace(&format!(
                "verifying runtime resource {index}/{}",
                resources.len()
            ));
        }
        let entry = resource
            .as_object()
            .ok_or_else(|| "runtime manifest resource is invalid".to_owned())?;
        if entry.len() != 4 {
            return Err("runtime manifest resource shape is invalid".to_owned());
        }
        let resource_id = entry
            .get("resourceId")
            .and_then(Value::as_str)
            .ok_or_else(|| "runtime resource id is invalid".to_owned())?;
        let relative_source = entry
            .get("relativePath")
            .and_then(Value::as_str)
            .ok_or_else(|| "runtime resource path is invalid".to_owned())?;
        let size = entry
            .get("size")
            .and_then(Value::as_u64)
            .ok_or_else(|| "runtime resource size is invalid".to_owned())?;
        let sha256 = entry
            .get("sha256")
            .and_then(Value::as_str)
            .ok_or_else(|| "runtime resource digest is invalid".to_owned())?;
        if resource_id.is_empty()
            || !resource_ids.insert(resource_id.to_owned())
            || !is_sha256(sha256)
        {
            return Err("runtime manifest resource identity is invalid".to_owned());
        }
        let (normalized, relative) = runtime_relative_path(relative_source)?;
        if !expected_paths.insert(normalized.to_ascii_lowercase()) {
            return Err("runtime manifest resource paths collide".to_owned());
        }
        let path = stable_file_within(&root, &relative)?;
        let (actual_size, actual_sha256) = sha256_file(&path)?;
        if actual_size != size || actual_sha256 != sha256 {
            return Err("runtime resource does not match the pinned manifest".to_owned());
        }
        resources_by_id.insert(resource_id.to_owned(), path);
    }
    for required in [
        "managed-python:executable",
        "card-service:worker-bootstrap",
        "metadata:python-runtime-lock",
        "managed-python:build-metadata",
    ] {
        if !resources_by_id.contains_key(required) {
            return Err("runtime package is missing a launcher-required resource".to_owned());
        }
    }

    expected_paths.insert(MANIFEST_NAME.to_ascii_lowercase());
    expected_paths.insert(SIGNATURE_NAME.to_ascii_lowercase());
    stable_file_within(&root, Path::new(SIGNATURE_NAME))?;
    trace("collecting runtime file inventory");
    let mut actual_paths = HashSet::new();
    collect_runtime_files(&root, &root, 0, &mut actual_paths)?;
    trace("runtime file inventory collected");
    if actual_paths != expected_paths {
        return Err("runtime package contains missing or unlisted files".to_owned());
    }
    resources_by_id
        .remove("managed-python:executable")
        .ok_or_else(|| "managed Python is unavailable".to_owned())
}

fn resolve_layout(executable: &Path) -> Result<LauncherLayout, String> {
    assert_no_reparse_ancestors(executable)?;
    let executable = executable
        .canonicalize()
        .map_err(|_| "launcher executable cannot be resolved".to_owned())?;
    let launcher_directory = executable
        .parent()
        .ok_or_else(|| "launcher directory is unavailable".to_owned())?;
    if launcher_directory.file_name() != Some(OsStr::new("launcher")) {
        return Err("launcher is not installed in server/launcher".to_owned());
    }
    let server = launcher_directory
        .parent()
        .ok_or_else(|| "plugin server directory is unavailable".to_owned())?;
    if server.file_name() != Some(OsStr::new("server")) {
        return Err("launcher is not installed under the plugin server directory".to_owned());
    }
    let plugin_root = server
        .parent()
        .ok_or_else(|| "plugin root is unavailable".to_owned())?
        .to_path_buf();
    let runtime_root = server.join("runtime");
    let trust_policy = server.join(TRUST_POLICY_NAME);
    if !runtime_root.is_dir() || !trust_policy.is_file() {
        return Err("plugin runtime or publisher trust policy is missing".to_owned());
    }
    Ok(LauncherLayout {
        plugin_root,
        runtime_root,
        trust_policy,
    })
}

fn parse_arguments(arguments: impl Iterator<Item = OsString>) -> Result<(), String> {
    let values: Vec<OsString> = arguments.collect();
    if values.len() != 1 || values[0] != OsStr::new("--stdio") {
        return Err("launcher only accepts the fixed --stdio mode".to_owned());
    }
    Ok(())
}

fn state_directory() -> Result<PathBuf, String> {
    #[cfg(windows)]
    let base = env::var_os("LOCALAPPDATA")
        .map(PathBuf::from)
        .ok_or_else(|| "LOCALAPPDATA is unavailable".to_owned())?;
    #[cfg(not(windows))]
    let base = env::var_os("XDG_STATE_HOME")
        .map(PathBuf::from)
        .ok_or_else(|| "XDG_STATE_HOME is unavailable".to_owned())?;
    if !base.is_absolute() {
        return Err("application state root is not absolute".to_owned());
    }
    let state = base.join("AnkiStudyAgent").join("card-service");
    fs::create_dir_all(&state)
        .map_err(|_| "Card Service state directory cannot be created".to_owned())?;
    assert_no_reparse_ancestors(&state)?;
    if !state.is_dir() {
        return Err("Card Service state path is not a directory".to_owned());
    }
    Ok(state)
}

fn run() -> Result<i32, String> {
    trace("starting");
    parse_arguments(env::args_os().skip(1))?;
    let expected_manifest =
        expected_digest(EXPECTED_RUNTIME_MANIFEST_SHA256, "runtime manifest SHA-256")?;
    let expected_trust = expected_digest(
        EXPECTED_RUNTIME_TRUST_POLICY_SHA256,
        "runtime trust policy SHA-256",
    )?;
    let executable =
        env::current_exe().map_err(|_| "launcher executable is unavailable".to_owned())?;
    let layout = resolve_layout(&executable)?;
    trace("plugin layout resolved");
    if let Some(install_trust_digest) = EXPECTED_PLUGIN_INSTALL_TRUST_POLICY_SHA256 {
        let install_trust_digest = expected_digest(
            Some(install_trust_digest),
            "plugin install trust policy SHA-256",
        )?;
        release_verifier::verify_installed_plugin(
            &layout.plugin_root,
            install_trust_digest,
            expected_manifest,
            expected_trust,
            std::time::SystemTime::now(),
        )?;
        trace("signed install manifest verified");
    } else {
        release_verifier::assert_passive_plugin(&layout.plugin_root)?;
        trace("passive plugin layout verified");
    }
    let trust_policy = stable_file_within(
        &layout.plugin_root,
        layout
            .trust_policy
            .strip_prefix(&layout.plugin_root)
            .map_err(|_| "publisher trust policy escaped the plugin root".to_owned())?,
    )?;
    let trust_source = read_bounded(
        &trust_policy,
        MAX_TRUST_POLICY_BYTES,
        "publisher trust policy",
    )?;
    if hex_digest(Sha256::digest(&trust_source)) != expected_trust {
        return Err("publisher trust policy does not match the launcher pin".to_owned());
    }
    trace("publisher trust policy pin verified");
    let python = verify_runtime_package(&layout.runtime_root, expected_manifest)?;
    trace("runtime package verified");
    let runtime_root = layout
        .runtime_root
        .canonicalize()
        .map_err(|_| "runtime package root cannot be resolved".to_owned())?;
    let state = state_directory()?;
    let mut command = Command::new(&python);
    command
        .arg("-E")
        .arg("-s")
        .arg("-B")
        .arg("-m")
        .arg("card_service.mcp_stdio")
        .arg("--state-dir")
        .arg(state)
        .arg("--runtime-package")
        .arg(&runtime_root)
        .arg("--runtime-trust-policy")
        .arg(&trust_policy)
        .current_dir(&runtime_root)
        .env_remove("PYTHONHOME")
        .env_remove("PYTHONPATH")
        .env_remove("PYTHONSTARTUP")
        .env("PYTHONDONTWRITEBYTECODE", "1")
        .stdin(Stdio::inherit())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());
    #[cfg(windows)]
    command
        .env("PROCESSOR_ARCHITECTURE", "AMD64")
        .env_remove("PROCESSOR_ARCHITEW6432");
    let status = command
        .status()
        .map_err(|_| "managed Card Service could not start".to_owned())?;
    Ok(status.code().unwrap_or(EXIT_LAUNCHER_FAILURE))
}

fn main() {
    match run() {
        Ok(code) => process::exit(code),
        Err(message) => {
            let _ = writeln!(std::io::stderr(), "{message}");
            process::exit(EXIT_LAUNCHER_FAILURE);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{
        assert_no_reparse_ancestors, hex_digest, is_sha256, parse_arguments, runtime_relative_path,
        sha256_file, windows_reserved_name,
    };
    use sha2::{Digest, Sha256};
    use std::env;
    use std::ffi::OsString;
    use std::fs;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn accepts_only_the_fixed_stdio_mode() {
        assert!(parse_arguments([OsString::from("--stdio")].into_iter()).is_ok());
        assert!(parse_arguments([].into_iter()).is_err());
        assert!(parse_arguments(
            [OsString::from("--stdio"), OsString::from("--other")].into_iter()
        )
        .is_err());
        assert!(parse_arguments([OsString::from("--runtime-package")].into_iter()).is_err());
    }

    #[test]
    fn validates_digest_and_windows_reserved_names() {
        assert!(is_sha256(&"a".repeat(64)));
        assert!(!is_sha256(&"A".repeat(64)));
        assert!(!is_sha256(&"a".repeat(63)));
        assert!(windows_reserved_name("CON.txt"));
        assert!(windows_reserved_name("LPT9"));
        assert!(!windows_reserved_name("runtime.json"));
    }

    #[test]
    fn runtime_paths_are_relative_portable_and_collision_safe() {
        assert_eq!(
            runtime_relative_path("python/Lib/site.py").unwrap().0,
            "python/Lib/site.py"
        );
        for blocked in [
            "",
            "/python.exe",
            "../python.exe",
            "python\\python.exe",
            "python/CLOCK$.txt",
            "python/trailing. ",
            "C:/python.exe",
        ] {
            assert!(runtime_relative_path(blocked).is_err(), "{blocked}");
        }
    }

    #[test]
    fn hashes_files_larger_than_the_streaming_buffer() {
        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = env::temp_dir().join(format!(
            "anki-study-launcher-hash-{}-{unique}",
            std::process::id()
        ));
        fs::create_dir(&root).unwrap();
        let path = root.join("large.bin");
        let source = vec![0x5a_u8; 2 * 1024 * 1024 + 17];
        fs::write(&path, &source).unwrap();

        let (size, digest) = sha256_file(&path).unwrap();

        assert_eq!(size, source.len() as u64);
        assert_eq!(digest, hex_digest(Sha256::digest(&source)));
        fs::remove_file(path).unwrap();
        fs::remove_dir(root).unwrap();
    }

    #[test]
    fn current_executable_has_a_stable_absolute_ancestor_chain() {
        let executable = env::current_exe().unwrap();
        assert!(assert_no_reparse_ancestors(&executable).is_ok());
    }
}
