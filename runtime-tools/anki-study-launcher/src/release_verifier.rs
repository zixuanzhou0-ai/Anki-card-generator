use ed25519_dalek::{Signature, VerifyingKey};
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use std::collections::{HashMap, HashSet};
use std::fs::{self, File, Metadata};
use std::io::Read;
use std::path::{Component, Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

const INSTALL_MANIFEST: &str = "install-package-v1.json";
const INSTALL_SIGNATURE: &str = "install-package-v1.sig.json";
const INSTALL_POLICY: &str = "server/plugin-publisher-trust-v1.json";
const PLUGIN_MANIFEST: &str = ".codex-plugin/plugin.json";
const MCP_CONFIG: &str = ".mcp.json";
const LAUNCHER: &str = "server/launcher/anki-study-agent.exe";
const RUNTIME_ROOT: &str = "server/runtime";
const RUNTIME_POLICY: &str = "server/runtime-publisher-trust-v1.json";
const SBOM: &str = "SBOM.spdx.json";
const DOMAIN: &str = "study.plugin-install-manifest.v1";
const MAX_MANIFEST: u64 = 8 * 1024 * 1024;
const MAX_POLICY: u64 = 256 * 1024;
const MAX_SIGNATURE: u64 = 32 * 1024;
const MAX_METADATA: u64 = 256 * 1024;
const MAX_FILES: usize = 60_000;
const MAX_DEPTH: usize = 40;

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct InstallAuthorization {
    pub(crate) package_id: String,
    pub(crate) plugin_version: String,
    pub(crate) manifest_sha256: String,
    pub(crate) authority: String,
    pub(crate) key_id: String,
    pub(crate) key_epoch: u64,
    pub(crate) trust_sequence: u64,
    pub(crate) trust_policy_sha256: String,
}

#[derive(Debug, Clone)]
struct TrustedKey {
    public_key: [u8; 32],
    public_key_sha256: String,
    status: String,
}

#[derive(Debug)]
struct TrustPolicy {
    authority: String,
    sequence: u64,
    minimum_version: (u64, u64, u64),
    maximum_lifetime: u64,
    keys: HashMap<(String, u64), TrustedKey>,
    revoked_versions: HashSet<String>,
    revoked_manifests: HashSet<String>,
    digest: String,
}

fn hex(value: impl AsRef<[u8]>) -> String {
    value
        .as_ref()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn is_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn is_identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value.bytes().enumerate().all(|(index, byte)| {
            byte.is_ascii_lowercase()
                || byte.is_ascii_digit()
                || (index > 0 && matches!(byte, b'.' | b'_' | b'-'))
        })
}

fn is_resource_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 512
        && value.bytes().enumerate().all(|(index, byte)| {
            byte.is_ascii_alphanumeric()
                || (index > 0 && matches!(byte, b':' | b'.' | b'_' | b'/' | b'+' | b'-'))
        })
}

fn exact_keys(object: &Map<String, Value>, expected: &[&str]) -> bool {
    object.len() == expected.len() && expected.iter().all(|name| object.contains_key(*name))
}

fn canonical(source: &[u8], maximum: u64, label: &str) -> Result<Value, String> {
    if source.is_empty() || source.len() as u64 > maximum {
        return Err(format!("{label} is empty or too large"));
    }
    let value: Value =
        serde_json::from_slice(source).map_err(|_| format!("{label} is not valid JSON"))?;
    if serde_json::to_vec(&value).map_err(|_| format!("{label} cannot be canonicalized"))? != source
    {
        return Err(format!("{label} must use canonical JSON"));
    }
    Ok(value)
}

fn has_reparse(metadata: &Metadata) -> bool {
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

fn stable_root(path: &Path) -> Result<PathBuf, String> {
    if !path.is_absolute() {
        return Err("plugin root must be absolute".to_owned());
    }
    let mut current = PathBuf::new();
    for component in path.components() {
        current.push(component.as_os_str());
        if matches!(component, Component::Prefix(_)) {
            continue;
        }
        let metadata =
            fs::symlink_metadata(&current).map_err(|_| "plugin root is unavailable".to_owned())?;
        if has_reparse(&metadata) {
            return Err("plugin root contains a reparse point".to_owned());
        }
    }
    let resolved = path
        .canonicalize()
        .map_err(|_| "plugin root cannot be resolved".to_owned())?;
    if !resolved.is_dir() {
        return Err("plugin root is not a directory".to_owned());
    }
    Ok(resolved)
}

fn reserved(part: &str) -> bool {
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

fn relative_path(value: &str) -> Result<PathBuf, String> {
    if value.is_empty()
        || !value.is_ascii()
        || value.contains('\\')
        || value.contains(':')
        || value.contains('\0')
        || value.starts_with('/')
    {
        return Err("install manifest contains an invalid path".to_owned());
    }
    let mut path = PathBuf::new();
    for part in value.split('/') {
        if part.is_empty()
            || matches!(part, "." | "..")
            || part != part.trim_end_matches([' ', '.'])
            || reserved(part)
        {
            return Err("install manifest contains an unsafe path component".to_owned());
        }
        path.push(part);
    }
    Ok(path)
}

fn stable_file(root: &Path, relative: &str) -> Result<PathBuf, String> {
    let relative = relative_path(relative)?;
    let mut current = root.to_path_buf();
    for component in relative.components() {
        let Component::Normal(part) = component else {
            return Err("install resource path is unsafe".to_owned());
        };
        current.push(part);
        let metadata = fs::symlink_metadata(&current)
            .map_err(|_| "install resource is unavailable".to_owned())?;
        if has_reparse(&metadata) {
            return Err("install resource path contains a reparse point".to_owned());
        }
    }
    let resolved = current
        .canonicalize()
        .map_err(|_| "install resource cannot be resolved".to_owned())?;
    if !resolved.starts_with(root) || !resolved.is_file() {
        return Err("install resource escaped its plugin root".to_owned());
    }
    Ok(resolved)
}

fn read_bounded(path: &Path, maximum: u64, label: &str) -> Result<Vec<u8>, String> {
    let metadata = fs::symlink_metadata(path).map_err(|_| format!("{label} is unavailable"))?;
    if has_reparse(&metadata)
        || !metadata.is_file()
        || metadata.len() == 0
        || metadata.len() > maximum
    {
        return Err(format!("{label} is unavailable or invalid"));
    }
    let mut source = Vec::with_capacity(metadata.len() as usize);
    File::open(path)
        .map_err(|_| format!("{label} cannot be opened"))?
        .take(maximum + 1)
        .read_to_end(&mut source)
        .map_err(|_| format!("{label} cannot be read"))?;
    if source.is_empty() || source.len() as u64 > maximum {
        return Err(format!("{label} is empty or too large"));
    }
    Ok(source)
}

fn sha256_file(path: &Path) -> Result<(u64, String), String> {
    let mut file = File::open(path).map_err(|_| "install resource cannot be opened".to_owned())?;
    let before = file
        .metadata()
        .map_err(|_| "install resource metadata is unavailable".to_owned())?;
    let mut digest = Sha256::new();
    let mut buffer = vec![0_u8; 1024 * 1024];
    loop {
        let count = file
            .read(&mut buffer)
            .map_err(|_| "install resource cannot be read".to_owned())?;
        if count == 0 {
            break;
        }
        digest.update(&buffer[..count]);
    }
    let after = path
        .metadata()
        .map_err(|_| "install resource metadata changed".to_owned())?;
    if before.len() != after.len() || before.modified().ok() != after.modified().ok() {
        return Err("install resource changed while it was verified".to_owned());
    }
    Ok((before.len(), hex(digest.finalize())))
}

fn decode_base64url(value: &str, expected: usize) -> Result<Vec<u8>, String> {
    if value.is_empty() || value.contains('=') || !value.is_ascii() {
        return Err("install trust encoding is invalid".to_owned());
    }
    let mut output = Vec::with_capacity(value.len() * 3 / 4 + 3);
    let mut accumulator = 0_u32;
    let mut bits = 0_u8;
    for byte in value.bytes() {
        let digit = match byte {
            b'A'..=b'Z' => byte - b'A',
            b'a'..=b'z' => byte - b'a' + 26,
            b'0'..=b'9' => byte - b'0' + 52,
            b'-' => 62,
            b'_' => 63,
            _ => return Err("install trust encoding is invalid".to_owned()),
        };
        accumulator = (accumulator << 6) | u32::from(digit);
        bits += 6;
        if bits >= 8 {
            bits -= 8;
            output.push(((accumulator >> bits) & 0xff) as u8);
        }
    }
    if bits >= 6
        || (bits > 0 && accumulator & ((1_u32 << bits) - 1) != 0)
        || output.len() != expected
    {
        return Err("install trust encoding is invalid".to_owned());
    }
    Ok(output)
}

fn stable_semver(value: &str) -> Result<(u64, u64, u64), String> {
    let parts: Vec<&str> = value.split('.').collect();
    if parts.len() != 3 {
        return Err("install version must use stable semantic version syntax".to_owned());
    }
    let mut parsed = [0_u64; 3];
    for (index, part) in parts.iter().enumerate() {
        if part.is_empty()
            || (part.len() > 1 && part.starts_with('0'))
            || !part.bytes().all(|byte| byte.is_ascii_digit())
        {
            return Err("install version must use stable semantic version syntax".to_owned());
        }
        parsed[index] = part
            .parse()
            .map_err(|_| "install version is out of range".to_owned())?;
    }
    Ok((parsed[0], parsed[1], parsed[2]))
}

fn days_in_month(year: i64, month: i64) -> i64 {
    match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        2 if year % 400 == 0 || (year % 4 == 0 && year % 100 != 0) => 29,
        2 => 28,
        _ => 0,
    }
}

fn days_from_civil(year: i64, month: i64, day: i64) -> i64 {
    let year = year - i64::from(month <= 2);
    let era = if year >= 0 { year } else { year - 399 } / 400;
    let year_of_era = year - era * 400;
    let month = month + if month > 2 { -3 } else { 9 };
    let day_of_year = (153 * month + 2) / 5 + day - 1;
    era * 146_097 + year_of_era * 365 + year_of_era / 4 - year_of_era / 100 + day_of_year - 719_468
}

fn utc_seconds(value: &str) -> Result<u64, String> {
    let bytes = value.as_bytes();
    if bytes.len() != 20
        || bytes[4] != b'-'
        || bytes[7] != b'-'
        || bytes[10] != b'T'
        || bytes[13] != b':'
        || bytes[16] != b':'
        || bytes[19] != b'Z'
        || bytes.iter().enumerate().any(|(index, byte)| {
            !matches!(index, 4 | 7 | 10 | 13 | 16 | 19) && !byte.is_ascii_digit()
        })
    {
        return Err("install signature time is invalid".to_owned());
    }
    let number = |start, end| {
        value[start..end]
            .parse::<i64>()
            .map_err(|_| "install signature time is invalid".to_owned())
    };
    let year = number(0, 4)?;
    let month = number(5, 7)?;
    let day = number(8, 10)?;
    let hour = number(11, 13)?;
    let minute = number(14, 16)?;
    let second = number(17, 19)?;
    if !(1970..=9999).contains(&year)
        || !(1..=12).contains(&month)
        || day < 1
        || day > days_in_month(year, month)
        || !(0..=23).contains(&hour)
        || !(0..=59).contains(&minute)
        || !(0..=59).contains(&second)
    {
        return Err("install signature time is invalid".to_owned());
    }
    u64::try_from(days_from_civil(year, month, day) * 86_400 + hour * 3_600 + minute * 60 + second)
        .map_err(|_| "install signature time is invalid".to_owned())
}

fn string_set(value: &Value, label: &str, sha256: bool) -> Result<HashSet<String>, String> {
    let values = value
        .as_array()
        .ok_or_else(|| format!("{label} is invalid"))?;
    let mut observed = Vec::with_capacity(values.len());
    let mut unique = HashSet::new();
    for child in values {
        let text = child
            .as_str()
            .ok_or_else(|| format!("{label} is invalid"))?;
        if (sha256 && !is_sha256(text))
            || (!sha256 && stable_semver(text).is_err())
            || !unique.insert(text.to_owned())
        {
            return Err(format!("{label} is invalid"));
        }
        observed.push(text.to_owned());
    }
    let mut sorted = observed.clone();
    sorted.sort_by(|left, right| left.as_bytes().cmp(right.as_bytes()));
    if observed != sorted {
        return Err(format!("{label} must be sorted"));
    }
    Ok(unique)
}

fn parse_policy(source: &[u8], expected_digest: &str) -> Result<TrustPolicy, String> {
    if !is_sha256(expected_digest) || hex(Sha256::digest(source)) != expected_digest {
        return Err("plugin install trust policy does not match the launcher pin".to_owned());
    }
    let value = canonical(source, MAX_POLICY, "plugin install trust policy")?;
    let object = value
        .as_object()
        .ok_or_else(|| "plugin install trust policy is invalid".to_owned())?;
    if !exact_keys(
        object,
        &[
            "schemaVersion",
            "authority",
            "sequence",
            "minimumPluginVersion",
            "maximumSignatureLifetimeSeconds",
            "keys",
            "revokedPluginVersions",
            "revokedManifestSha256",
        ],
    ) || object.get("schemaVersion").and_then(Value::as_u64) != Some(1)
    {
        return Err("plugin install trust policy shape is invalid".to_owned());
    }
    let authority = object
        .get("authority")
        .and_then(Value::as_str)
        .filter(|value| is_identifier(value))
        .ok_or_else(|| "plugin install trust authority is invalid".to_owned())?
        .to_owned();
    let sequence = object
        .get("sequence")
        .and_then(Value::as_u64)
        .ok_or_else(|| "plugin install trust sequence is invalid".to_owned())?;
    let minimum_version = stable_semver(
        object
            .get("minimumPluginVersion")
            .and_then(Value::as_str)
            .ok_or_else(|| "plugin install minimum version is invalid".to_owned())?,
    )?;
    let maximum_lifetime = object
        .get("maximumSignatureLifetimeSeconds")
        .and_then(Value::as_u64)
        .filter(|value| *value > 0 && *value <= 366 * 24 * 60 * 60)
        .ok_or_else(|| "plugin install signature lifetime policy is invalid".to_owned())?;
    let revoked_versions = string_set(
        object
            .get("revokedPluginVersions")
            .ok_or_else(|| "revoked install versions are missing".to_owned())?,
        "revoked install versions",
        false,
    )?;
    let revoked_manifests = string_set(
        object
            .get("revokedManifestSha256")
            .ok_or_else(|| "revoked install manifests are missing".to_owned())?,
        "revoked install manifests",
        true,
    )?;
    let raw_keys = object
        .get("keys")
        .and_then(Value::as_array)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| "plugin install trust keys are invalid".to_owned())?;
    let mut keys = HashMap::new();
    let mut ordering = Vec::with_capacity(raw_keys.len());
    let mut public_key_digests = HashSet::new();
    for raw in raw_keys {
        let key = raw
            .as_object()
            .ok_or_else(|| "plugin install trust key is invalid".to_owned())?;
        if !exact_keys(
            key,
            &[
                "keyId",
                "keyEpoch",
                "publicKey",
                "publicKeySha256",
                "status",
            ],
        ) {
            return Err("plugin install trust key shape is invalid".to_owned());
        }
        let key_id = key
            .get("keyId")
            .and_then(Value::as_str)
            .filter(|value| is_identifier(value))
            .ok_or_else(|| "plugin install trust key id is invalid".to_owned())?
            .to_owned();
        let key_epoch = key
            .get("keyEpoch")
            .and_then(Value::as_u64)
            .filter(|value| *value > 0)
            .ok_or_else(|| "plugin install trust key epoch is invalid".to_owned())?;
        let encoded = key
            .get("publicKey")
            .and_then(Value::as_str)
            .ok_or_else(|| "plugin install public key is invalid".to_owned())?;
        let public_key: [u8; 32] = decode_base64url(encoded, 32)?
            .try_into()
            .map_err(|_| "plugin install public key is invalid".to_owned())?;
        let public_key_sha256 = key
            .get("publicKeySha256")
            .and_then(Value::as_str)
            .filter(|value| is_sha256(value))
            .ok_or_else(|| "plugin install public key digest is invalid".to_owned())?
            .to_owned();
        if hex(Sha256::digest(public_key)) != public_key_sha256
            || !public_key_digests.insert(public_key_sha256.clone())
        {
            return Err("plugin install public key digest does not match".to_owned());
        }
        let status = key
            .get("status")
            .and_then(Value::as_str)
            .filter(|value| matches!(*value, "active" | "revoked"))
            .ok_or_else(|| "plugin install trust key status is invalid".to_owned())?
            .to_owned();
        if keys
            .insert(
                (key_id.clone(), key_epoch),
                TrustedKey {
                    public_key,
                    public_key_sha256,
                    status,
                },
            )
            .is_some()
        {
            return Err("plugin install trust key is duplicated".to_owned());
        }
        ordering.push((key_id, key_epoch));
    }
    let mut sorted = ordering.clone();
    sorted.sort_by(|left, right| {
        left.0
            .as_bytes()
            .cmp(right.0.as_bytes())
            .then(left.1.cmp(&right.1))
    });
    if ordering != sorted {
        return Err("plugin install trust keys must be sorted".to_owned());
    }
    Ok(TrustPolicy {
        authority,
        sequence,
        minimum_version,
        maximum_lifetime,
        keys,
        revoked_versions,
        revoked_manifests,
        digest: expected_digest.to_owned(),
    })
}

fn manifest_identity(
    value: &Value,
    expected_runtime_manifest: &str,
    expected_runtime_trust: &str,
) -> Result<(String, String), String> {
    let object = value
        .as_object()
        .ok_or_else(|| "plugin install manifest is invalid".to_owned())?;
    if !exact_keys(
        object,
        &[
            "schemaVersion",
            "packageId",
            "version",
            "createdAt",
            "releaseState",
            "delegatedComponents",
            "sbom",
            "resources",
        ],
    ) || object.get("schemaVersion").and_then(Value::as_u64) != Some(1)
    {
        return Err("plugin install manifest shape is invalid".to_owned());
    }
    let package_id = object
        .get("packageId")
        .and_then(Value::as_str)
        .filter(|value| *value == "anki-study-agent-plugin")
        .ok_or_else(|| "plugin install package identity is invalid".to_owned())?
        .to_owned();
    let version = object
        .get("version")
        .and_then(Value::as_str)
        .ok_or_else(|| "plugin install version is invalid".to_owned())?
        .to_owned();
    stable_semver(&version)?;
    utc_seconds(
        object
            .get("createdAt")
            .and_then(Value::as_str)
            .ok_or_else(|| "plugin install creation time is invalid".to_owned())?,
    )?;
    let state = object
        .get("releaseState")
        .and_then(Value::as_object)
        .ok_or_else(|| "plugin install release state is invalid".to_owned())?;
    if !exact_keys(
        state,
        &[
            "channel",
            "installable",
            "mcpDeclared",
            "outerSignatureVerified",
            "publisherKeyManaged",
        ],
    ) || state.get("channel").and_then(Value::as_str) != Some("advanced-preview")
        || state.get("installable").and_then(Value::as_bool) != Some(true)
        || state.get("mcpDeclared").and_then(Value::as_bool) != Some(true)
        || state.get("outerSignatureVerified").and_then(Value::as_bool) != Some(true)
        || state.get("publisherKeyManaged").and_then(Value::as_bool) != Some(true)
    {
        return Err("plugin install release state is not authorized".to_owned());
    }
    let sbom = object
        .get("sbom")
        .and_then(Value::as_object)
        .ok_or_else(|| "plugin install SBOM declaration is invalid".to_owned())?;
    if !exact_keys(sbom, &["format", "resourceId"])
        || sbom.get("format").and_then(Value::as_str) != Some("SPDX-2.3")
        || sbom.get("resourceId").and_then(Value::as_str) != Some("metadata:sbom-spdx")
    {
        return Err("plugin install SBOM declaration is invalid".to_owned());
    }
    let components = object
        .get("delegatedComponents")
        .and_then(Value::as_array)
        .filter(|value| value.len() == 1)
        .ok_or_else(|| "plugin install delegated runtime is invalid".to_owned())?;
    let component = components[0]
        .as_object()
        .ok_or_else(|| "plugin install delegated runtime is invalid".to_owned())?;
    if !exact_keys(
        component,
        &[
            "componentId",
            "root",
            "manifestPath",
            "manifestSha256",
            "signaturePath",
            "trustPolicyPath",
            "trustPolicySha256",
        ],
    ) || component.get("componentId").and_then(Value::as_str) != Some("managed-runtime")
        || component.get("root").and_then(Value::as_str) != Some(RUNTIME_ROOT)
        || component.get("manifestPath").and_then(Value::as_str) != Some("runtime-package-v1.json")
        || component.get("manifestSha256").and_then(Value::as_str)
            != Some(expected_runtime_manifest)
        || component.get("signaturePath").and_then(Value::as_str)
            != Some("runtime-package-v1.sig.json")
        || component.get("trustPolicyPath").and_then(Value::as_str) != Some(RUNTIME_POLICY)
        || component.get("trustPolicySha256").and_then(Value::as_str)
            != Some(expected_runtime_trust)
    {
        return Err("plugin install delegated runtime does not match launcher pins".to_owned());
    }
    Ok((package_id, version))
}

fn metadata_files(root: &Path, version: &str) -> Result<(), String> {
    let plugin_source = read_bounded(
        &stable_file(root, PLUGIN_MANIFEST)?,
        MAX_METADATA,
        "plugin manifest",
    )?;
    let plugin = canonical(&plugin_source, MAX_METADATA, "plugin manifest")?;
    let plugin = plugin
        .as_object()
        .ok_or_else(|| "plugin manifest is invalid".to_owned())?;
    if plugin.get("name").and_then(Value::as_str) != Some("anki-study-agent")
        || plugin.get("version").and_then(Value::as_str) != Some(version)
        || plugin.get("mcpServers").and_then(Value::as_str) != Some("./.mcp.json")
    {
        return Err("plugin manifest is not wired to the signed MCP config".to_owned());
    }
    let mcp_source = read_bounded(
        &stable_file(root, MCP_CONFIG)?,
        MAX_METADATA,
        "plugin MCP config",
    )?;
    let mcp = canonical(&mcp_source, MAX_METADATA, "plugin MCP config")?;
    let mcp = mcp
        .as_object()
        .filter(|value| exact_keys(value, &["mcpServers"]))
        .ok_or_else(|| "plugin MCP config shape is invalid".to_owned())?;
    let servers = mcp
        .get("mcpServers")
        .and_then(Value::as_object)
        .filter(|value| exact_keys(value, &["anki-study-agent"]))
        .ok_or_else(|| "plugin MCP server declaration is invalid".to_owned())?;
    let server = servers
        .get("anki-study-agent")
        .and_then(Value::as_object)
        .ok_or_else(|| "plugin MCP server declaration is invalid".to_owned())?;
    let args_ok = server
        .get("args")
        .and_then(Value::as_array)
        .is_some_and(|args| args.len() == 1 && args[0].as_str() == Some("--stdio"));
    if !exact_keys(server, &["command", "args", "cwd", "tool_timeout_sec"])
        || server.get("command").and_then(Value::as_str)
            != Some("./server/launcher/anki-study-agent.exe")
        || server.get("cwd").and_then(Value::as_str) != Some(".")
        || server.get("tool_timeout_sec").and_then(Value::as_u64) != Some(900)
        || !args_ok
    {
        return Err("plugin MCP server command is not the fixed native launcher".to_owned());
    }
    Ok(())
}

fn collect_outer_files(
    root: &Path,
    directory: &Path,
    depth: usize,
    files: &mut HashSet<String>,
) -> Result<(), String> {
    if depth > MAX_DEPTH {
        return Err("plugin install directory depth exceeds its limit".to_owned());
    }
    let mut entries = fs::read_dir(directory)
        .map_err(|_| "plugin install directory cannot be read".to_owned())?
        .collect::<Result<Vec<_>, _>>()
        .map_err(|_| "plugin install directory entry is unavailable".to_owned())?;
    entries.sort_by_key(|entry| entry.file_name());
    for entry in entries {
        let path = entry.path();
        let metadata = fs::symlink_metadata(&path)
            .map_err(|_| "plugin install entry metadata is unavailable".to_owned())?;
        if has_reparse(&metadata) {
            return Err("plugin install directory contains a reparse point".to_owned());
        }
        let relative = path
            .strip_prefix(root)
            .map_err(|_| "plugin install entry escaped its root".to_owned())?;
        let relative = relative
            .components()
            .map(|component| {
                let Component::Normal(value) = component else {
                    return Err("plugin install path is invalid".to_owned());
                };
                value
                    .to_str()
                    .filter(|part| part.is_ascii())
                    .ok_or_else(|| "plugin install path is not portable ASCII".to_owned())
            })
            .collect::<Result<Vec<_>, _>>()?
            .join("/");
        if relative.eq_ignore_ascii_case(RUNTIME_ROOT) {
            if !metadata.is_dir() {
                return Err("delegated runtime root is not a directory".to_owned());
            }
            continue;
        }
        if metadata.is_dir() {
            collect_outer_files(root, &path, depth + 1, files)?;
        } else if metadata.is_file() {
            if !files.insert(relative.to_ascii_lowercase()) || files.len() > MAX_FILES {
                return Err("plugin install contains duplicate or too many files".to_owned());
            }
        } else {
            return Err("plugin install contains an unsupported entry".to_owned());
        }
    }
    Ok(())
}

fn resources(root: &Path, manifest: &Value) -> Result<(), String> {
    let resources = manifest
        .get("resources")
        .and_then(Value::as_array)
        .filter(|value| !value.is_empty() && value.len() <= MAX_FILES)
        .ok_or_else(|| "plugin install resources are invalid".to_owned())?;
    let mut expected_paths = HashSet::new();
    let mut resource_ids = HashSet::new();
    let mut ordering = Vec::with_capacity(resources.len());
    let mut sbom_path = None;
    for raw in resources {
        let resource = raw
            .as_object()
            .ok_or_else(|| "plugin install resource is invalid".to_owned())?;
        if !exact_keys(resource, &["resourceId", "relativePath", "size", "sha256"]) {
            return Err("plugin install resource shape is invalid".to_owned());
        }
        let resource_id = resource
            .get("resourceId")
            .and_then(Value::as_str)
            .filter(|value| is_resource_id(value))
            .ok_or_else(|| "plugin install resource id is invalid".to_owned())?;
        if !resource_ids.insert(resource_id.to_owned()) {
            return Err("plugin install resource id is duplicated".to_owned());
        }
        ordering.push(resource_id.to_owned());
        let relative = resource
            .get("relativePath")
            .and_then(Value::as_str)
            .ok_or_else(|| "plugin install resource path is invalid".to_owned())?;
        let lower = relative.to_ascii_lowercase();
        if lower == INSTALL_MANIFEST
            || lower == INSTALL_SIGNATURE
            || lower == RUNTIME_ROOT
            || lower.starts_with(&format!("{RUNTIME_ROOT}/"))
        {
            return Err(
                "plugin install resource overlaps reserved or delegated metadata".to_owned(),
            );
        }
        let normalized = relative_path(relative)?
            .components()
            .map(|component| component.as_os_str().to_str().unwrap_or_default())
            .collect::<Vec<_>>()
            .join("/");
        if !expected_paths.insert(normalized.to_ascii_lowercase()) {
            return Err("plugin install resource paths collide".to_owned());
        }
        let expected_size = resource
            .get("size")
            .and_then(Value::as_u64)
            .ok_or_else(|| "plugin install resource size is invalid".to_owned())?;
        let expected_sha256 = resource
            .get("sha256")
            .and_then(Value::as_str)
            .filter(|value| is_sha256(value))
            .ok_or_else(|| "plugin install resource digest is invalid".to_owned())?;
        let (size, sha256) = sha256_file(&stable_file(root, &normalized)?)?;
        if size != expected_size || sha256 != expected_sha256 {
            return Err("plugin install resource does not match the signed manifest".to_owned());
        }
        if resource_id == "metadata:sbom-spdx" {
            sbom_path = Some(normalized);
        }
    }
    let mut sorted = ordering.clone();
    sorted.sort_by(|left, right| left.as_bytes().cmp(right.as_bytes()));
    if ordering != sorted {
        return Err("plugin install resources must be sorted".to_owned());
    }
    for required in [
        MCP_CONFIG,
        PLUGIN_MANIFEST,
        LAUNCHER,
        INSTALL_POLICY,
        RUNTIME_POLICY,
    ] {
        if !expected_paths.contains(&required.to_ascii_lowercase()) {
            return Err("plugin install manifest is missing a required outer resource".to_owned());
        }
    }
    if sbom_path.as_deref() != Some(SBOM) {
        return Err("plugin install manifest is missing the declared SBOM".to_owned());
    }
    expected_paths.insert(INSTALL_MANIFEST.to_owned());
    expected_paths.insert(INSTALL_SIGNATURE.to_owned());
    let mut actual_paths = HashSet::new();
    collect_outer_files(root, root, 0, &mut actual_paths)?;
    if actual_paths != expected_paths {
        return Err("plugin install contains missing or unlisted outer files".to_owned());
    }
    Ok(())
}

fn verify_signature(
    source: &[u8],
    manifest_sha256: &str,
    package_id: &str,
    plugin_version: &str,
    policy: &TrustPolicy,
    now: u64,
) -> Result<(String, u64), String> {
    let value = canonical(source, MAX_SIGNATURE, "plugin install signature")?;
    let object = value
        .as_object()
        .ok_or_else(|| "plugin install signature is invalid".to_owned())?;
    if !exact_keys(
        object,
        &[
            "schemaVersion",
            "algorithm",
            "domain",
            "authority",
            "packageId",
            "pluginVersion",
            "keyId",
            "keyEpoch",
            "signedAt",
            "expiresAt",
            "manifestSha256",
            "signature",
        ],
    ) || object.get("schemaVersion").and_then(Value::as_u64) != Some(1)
        || object.get("algorithm").and_then(Value::as_str) != Some("Ed25519")
        || object.get("domain").and_then(Value::as_str) != Some(DOMAIN)
        || object.get("authority").and_then(Value::as_str) != Some(&policy.authority)
        || object.get("packageId").and_then(Value::as_str) != Some(package_id)
        || object.get("pluginVersion").and_then(Value::as_str) != Some(plugin_version)
        || object.get("manifestSha256").and_then(Value::as_str) != Some(manifest_sha256)
    {
        return Err("plugin install signature binding is invalid".to_owned());
    }
    let signed_at = utc_seconds(
        object
            .get("signedAt")
            .and_then(Value::as_str)
            .ok_or_else(|| "plugin install signature start time is invalid".to_owned())?,
    )?;
    let expires_at = utc_seconds(
        object
            .get("expiresAt")
            .and_then(Value::as_str)
            .ok_or_else(|| "plugin install signature expiry is invalid".to_owned())?,
    )?;
    if expires_at <= signed_at
        || expires_at - signed_at > policy.maximum_lifetime
        || now < signed_at
        || now >= expires_at
    {
        return Err("plugin install signature is expired or has an invalid lifetime".to_owned());
    }
    let version = stable_semver(plugin_version)?;
    if version < policy.minimum_version
        || policy.revoked_versions.contains(plugin_version)
        || policy.revoked_manifests.contains(manifest_sha256)
    {
        return Err("plugin install version or manifest is revoked".to_owned());
    }
    let key_id = object
        .get("keyId")
        .and_then(Value::as_str)
        .filter(|value| is_identifier(value))
        .ok_or_else(|| "plugin install signature key id is invalid".to_owned())?
        .to_owned();
    let key_epoch = object
        .get("keyEpoch")
        .and_then(Value::as_u64)
        .filter(|value| *value > 0)
        .ok_or_else(|| "plugin install signature key epoch is invalid".to_owned())?;
    let key = policy
        .keys
        .get(&(key_id.clone(), key_epoch))
        .ok_or_else(|| "plugin install signing key is untrusted".to_owned())?;
    if key.status != "active" {
        return Err("plugin install signing key is revoked".to_owned());
    }
    if hex(Sha256::digest(key.public_key)) != key.public_key_sha256 {
        return Err("plugin install signing key pin changed".to_owned());
    }
    let signature: [u8; 64] = decode_base64url(
        object
            .get("signature")
            .and_then(Value::as_str)
            .ok_or_else(|| "plugin install signature encoding is invalid".to_owned())?,
        64,
    )?
    .try_into()
    .map_err(|_| "plugin install signature encoding is invalid".to_owned())?;
    let mut unsigned = object.clone();
    unsigned.remove("signature");
    let unsigned = serde_json::to_vec(&Value::Object(unsigned))
        .map_err(|_| "plugin install signature payload cannot be canonicalized".to_owned())?;
    let digest = Sha256::digest(unsigned);
    let mut message = Vec::with_capacity(DOMAIN.len() + 1 + digest.len());
    message.extend_from_slice(DOMAIN.as_bytes());
    message.push(0);
    message.extend_from_slice(&digest);
    VerifyingKey::from_bytes(&key.public_key)
        .map_err(|_| "plugin install public key is invalid".to_owned())?
        .verify_strict(&message, &Signature::from_bytes(&signature))
        .map_err(|_| "plugin install signature verification failed".to_owned())?;
    Ok((key_id, key_epoch))
}

pub(crate) fn assert_passive_plugin(root: &Path) -> Result<(), String> {
    let root = stable_root(root)?;
    for forbidden in [
        MCP_CONFIG,
        INSTALL_MANIFEST,
        INSTALL_SIGNATURE,
        INSTALL_POLICY,
    ] {
        if root
            .join(forbidden.replace('/', std::path::MAIN_SEPARATOR_STR))
            .exists()
        {
            return Err("passive launcher cannot run an installable plugin layout".to_owned());
        }
    }
    let source = read_bounded(
        &stable_file(&root, PLUGIN_MANIFEST)?,
        MAX_METADATA,
        "passive plugin manifest",
    )?;
    let value: Value = serde_json::from_slice(&source)
        .map_err(|_| "passive plugin manifest is invalid".to_owned())?;
    if value.get("mcpServers").is_some() || value.get("apps").is_some() {
        return Err("passive launcher cannot run a plugin that declares MCP or apps".to_owned());
    }
    Ok(())
}

pub(crate) fn verify_installed_plugin(
    root: &Path,
    expected_policy_digest: &str,
    expected_runtime_manifest: &str,
    expected_runtime_trust: &str,
    now: SystemTime,
) -> Result<InstallAuthorization, String> {
    if !is_sha256(expected_runtime_manifest) || !is_sha256(expected_runtime_trust) {
        return Err("runtime pins are invalid during install verification".to_owned());
    }
    let root = stable_root(root)?;
    let policy_source = read_bounded(
        &stable_file(&root, INSTALL_POLICY)?,
        MAX_POLICY,
        "plugin install trust policy",
    )?;
    let policy = parse_policy(&policy_source, expected_policy_digest)?;
    let manifest_source = read_bounded(
        &stable_file(&root, INSTALL_MANIFEST)?,
        MAX_MANIFEST,
        "plugin install manifest",
    )?;
    let manifest = canonical(&manifest_source, MAX_MANIFEST, "plugin install manifest")?;
    let (package_id, plugin_version) =
        manifest_identity(&manifest, expected_runtime_manifest, expected_runtime_trust)?;
    let manifest_sha256 = hex(Sha256::digest(&manifest_source));
    resources(&root, &manifest)?;
    metadata_files(&root, &plugin_version)?;
    let signature_source = read_bounded(
        &stable_file(&root, INSTALL_SIGNATURE)?,
        MAX_SIGNATURE,
        "plugin install signature",
    )?;
    let now = now
        .duration_since(UNIX_EPOCH)
        .map_err(|_| "system clock is before the Unix epoch".to_owned())?
        .as_secs();
    let (key_id, key_epoch) = verify_signature(
        &signature_source,
        &manifest_sha256,
        &package_id,
        &plugin_version,
        &policy,
        now,
    )?;
    Ok(InstallAuthorization {
        package_id,
        plugin_version,
        manifest_sha256,
        authority: policy.authority,
        key_id,
        key_epoch,
        trust_sequence: policy.sequence,
        trust_policy_sha256: policy.digest,
    })
}

#[cfg(test)]
mod tests {
    use super::{
        assert_passive_plugin, decode_base64url, hex, parse_policy, stable_semver, utc_seconds,
        verify_installed_plugin, verify_signature, DOMAIN, INSTALL_MANIFEST, INSTALL_POLICY,
        INSTALL_SIGNATURE, LAUNCHER, MCP_CONFIG, PLUGIN_MANIFEST, RUNTIME_POLICY, RUNTIME_ROOT,
        SBOM,
    };
    use ed25519_dalek::{Signer, SigningKey};
    use serde_json::{json, Value};
    use sha2::{Digest, Sha256};
    use std::fs;
    use std::path::{Path, PathBuf};
    use std::time::{Duration, SystemTime, UNIX_EPOCH};

    struct Fixture {
        root: PathBuf,
        policy_digest: String,
        runtime_manifest: String,
        runtime_trust: String,
        now: SystemTime,
    }

    impl Drop for Fixture {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.root);
        }
    }

    fn canonical(value: &Value) -> Vec<u8> {
        serde_json::to_vec(value).unwrap()
    }

    fn encode_base64url(source: &[u8]) -> String {
        const ALPHABET: &[u8; 64] =
            b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
        let mut output = String::new();
        for chunk in source.chunks(3) {
            let value = (u32::from(chunk[0]) << 16)
                | (u32::from(*chunk.get(1).unwrap_or(&0)) << 8)
                | u32::from(*chunk.get(2).unwrap_or(&0));
            output.push(ALPHABET[((value >> 18) & 63) as usize] as char);
            output.push(ALPHABET[((value >> 12) & 63) as usize] as char);
            if chunk.len() > 1 {
                output.push(ALPHABET[((value >> 6) & 63) as usize] as char);
            }
            if chunk.len() > 2 {
                output.push(ALPHABET[(value & 63) as usize] as char);
            }
        }
        output
    }

    fn write(root: &Path, relative: &str, source: &[u8]) {
        let path = root.join(relative.replace('/', std::path::MAIN_SEPARATOR_STR));
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(path, source).unwrap();
    }

    fn resource(root: &Path, resource_id: &str, relative: &str) -> Value {
        let path = root.join(relative.replace('/', std::path::MAIN_SEPARATOR_STR));
        let source = fs::read(path).unwrap();
        json!({
            "resourceId": resource_id,
            "relativePath": relative,
            "size": source.len(),
            "sha256": hex(Sha256::digest(source)),
        })
    }

    fn install_fixture() -> Fixture {
        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "anki-study-install-verifier-{}-{unique}",
            std::process::id()
        ));
        fs::create_dir(&root).unwrap();
        let signing_key = SigningKey::from_bytes(&[0x31; 32]);
        let public_key = signing_key.verifying_key().to_bytes();
        let policy = json!({
            "schemaVersion": 1,
            "authority": "anki-study-agent.install-test",
            "sequence": 7,
            "minimumPluginVersion": "0.1.0",
            "maximumSignatureLifetimeSeconds": 31_622_400,
            "keys": [{
                "keyId": "install-2026",
                "keyEpoch": 1,
                "publicKey": encode_base64url(&public_key),
                "publicKeySha256": hex(Sha256::digest(public_key)),
                "status": "active",
            }],
            "revokedPluginVersions": [],
            "revokedManifestSha256": [],
        });
        let policy_source = canonical(&policy);
        write(&root, INSTALL_POLICY, &policy_source);
        write(
            &root,
            PLUGIN_MANIFEST,
            &canonical(&json!({
                "name": "anki-study-agent",
                "version": "0.1.0",
                "description": "Test plugin",
                "author": {"name": "test"},
                "skills": "./skills/",
                "mcpServers": "./.mcp.json",
                "interface": {
                    "displayName": "Anki Study Agent",
                    "shortDescription": "Test",
                    "longDescription": "Test",
                    "developerName": "test",
                    "category": "Productivity",
                    "capabilities": ["Read", "Write"]
                }
            })),
        );
        write(
            &root,
            MCP_CONFIG,
            &canonical(&json!({
                "mcpServers": {
                    "anki-study-agent": {
                        "command": "./server/launcher/anki-study-agent.exe",
                        "args": ["--stdio"],
                        "cwd": ".",
                        "tool_timeout_sec": 900
                    }
                }
            })),
        );
        write(&root, LAUNCHER, b"MZ-test-launcher");
        write(&root, RUNTIME_POLICY, b"runtime-policy-test");
        write(&root, SBOM, &canonical(&json!({"spdxVersion": "SPDX-2.3"})));
        write(
            &root,
            &format!("{RUNTIME_ROOT}/runtime-package-v1.json"),
            b"{}",
        );
        write(
            &root,
            &format!("{RUNTIME_ROOT}/runtime-package-v1.sig.json"),
            b"{}",
        );
        let runtime_manifest = "a".repeat(64);
        let runtime_trust = "b".repeat(64);
        let resources = vec![
            resource(&root, "launcher:windows-x86_64", LAUNCHER),
            resource(&root, "metadata:plugin-publisher-trust", INSTALL_POLICY),
            resource(&root, "metadata:runtime-publisher-trust", RUNTIME_POLICY),
            resource(&root, "metadata:sbom-spdx", SBOM),
            resource(&root, "plugin:mcp-config", MCP_CONFIG),
            resource(&root, "plugin:plugin-manifest", PLUGIN_MANIFEST),
        ];
        let manifest = json!({
            "schemaVersion": 1,
            "packageId": "anki-study-agent-plugin",
            "version": "0.1.0",
            "createdAt": "2026-07-18T00:00:00Z",
            "releaseState": {
                "channel": "advanced-preview",
                "installable": true,
                "mcpDeclared": true,
                "outerSignatureVerified": true,
                "publisherKeyManaged": true
            },
            "delegatedComponents": [{
                "componentId": "managed-runtime",
                "root": RUNTIME_ROOT,
                "manifestPath": "runtime-package-v1.json",
                "manifestSha256": runtime_manifest,
                "signaturePath": "runtime-package-v1.sig.json",
                "trustPolicyPath": RUNTIME_POLICY,
                "trustPolicySha256": runtime_trust
            }],
            "sbom": {"format": "SPDX-2.3", "resourceId": "metadata:sbom-spdx"},
            "resources": resources
        });
        let manifest_source = canonical(&manifest);
        write(&root, INSTALL_MANIFEST, &manifest_source);
        let manifest_sha256 = hex(Sha256::digest(&manifest_source));
        let unsigned = json!({
            "schemaVersion": 1,
            "algorithm": "Ed25519",
            "domain": DOMAIN,
            "authority": "anki-study-agent.install-test",
            "packageId": "anki-study-agent-plugin",
            "pluginVersion": "0.1.0",
            "keyId": "install-2026",
            "keyEpoch": 1,
            "signedAt": "2026-07-18T00:00:00Z",
            "expiresAt": "2026-07-19T00:00:00Z",
            "manifestSha256": manifest_sha256,
        });
        let digest = Sha256::digest(canonical(&unsigned));
        let mut message = Vec::from(DOMAIN.as_bytes());
        message.push(0);
        message.extend_from_slice(&digest);
        let mut signature = unsigned.as_object().unwrap().clone();
        signature.insert(
            "signature".to_owned(),
            Value::String(encode_base64url(&signing_key.sign(&message).to_bytes())),
        );
        write(
            &root,
            INSTALL_SIGNATURE,
            &canonical(&Value::Object(signature)),
        );
        Fixture {
            root,
            policy_digest: hex(Sha256::digest(policy_source)),
            runtime_manifest,
            runtime_trust,
            now: UNIX_EPOCH + Duration::from_secs(utc_seconds("2026-07-18T12:00:00Z").unwrap()),
        }
    }

    #[test]
    fn parses_only_stable_semver() {
        assert_eq!(stable_semver("0.1.0").unwrap(), (0, 1, 0));
        for blocked in ["1.0", "01.0.0", "1.0.0-beta", "1.0.0+build", "1.a.0"] {
            assert!(stable_semver(blocked).is_err(), "{blocked}");
        }
    }

    #[test]
    fn parses_strict_utc_seconds() {
        assert_eq!(utc_seconds("1970-01-01T00:00:00Z").unwrap(), 0);
        assert_eq!(utc_seconds("2026-07-18T12:00:00Z").unwrap(), 1_784_376_000);
        for blocked in [
            "2026-07-18T12:00:00+00:00",
            "2026-02-29T00:00:00Z",
            "2026-13-01T00:00:00Z",
            "2026-01-01T24:00:00Z",
        ] {
            assert!(utc_seconds(blocked).is_err(), "{blocked}");
        }
    }

    #[test]
    fn decodes_strict_unpadded_base64url() {
        assert_eq!(decode_base64url("AAECAw", 4).unwrap(), vec![0, 1, 2, 3]);
        for blocked in ["AAECAw==", "AAECA+", "A", ""] {
            assert!(decode_base64url(blocked, 4).is_err(), "{blocked}");
        }
    }

    #[test]
    fn verifies_signed_install_layout_and_exact_outer_resources() {
        let fixture = install_fixture();
        let verified = verify_installed_plugin(
            &fixture.root,
            &fixture.policy_digest,
            &fixture.runtime_manifest,
            &fixture.runtime_trust,
            fixture.now,
        )
        .unwrap();
        assert_eq!(verified.package_id, "anki-study-agent-plugin");
        assert_eq!(verified.plugin_version, "0.1.0");
        assert_eq!(verified.authority, "anki-study-agent.install-test");
        assert_eq!(verified.key_id, "install-2026");
        assert_eq!(verified.key_epoch, 1);
        assert_eq!(verified.trust_sequence, 7);
        assert_eq!(verified.trust_policy_sha256, fixture.policy_digest);
    }

    #[test]
    fn rejects_tamper_extra_file_and_cross_domain_signature() {
        let fixture = install_fixture();
        fs::write(fixture.root.join(MCP_CONFIG), b"{}\n").unwrap();
        assert!(verify_installed_plugin(
            &fixture.root,
            &fixture.policy_digest,
            &fixture.runtime_manifest,
            &fixture.runtime_trust,
            fixture.now,
        )
        .unwrap_err()
        .contains("resource does not match"));

        let fixture = install_fixture();
        fs::write(fixture.root.join("unexpected.txt"), b"unexpected").unwrap();
        assert!(verify_installed_plugin(
            &fixture.root,
            &fixture.policy_digest,
            &fixture.runtime_manifest,
            &fixture.runtime_trust,
            fixture.now,
        )
        .unwrap_err()
        .contains("missing or unlisted"));

        let fixture = install_fixture();
        let signature_path = fixture.root.join(INSTALL_SIGNATURE);
        let mut signature: Value =
            serde_json::from_slice(&fs::read(&signature_path).unwrap()).unwrap();
        signature["domain"] = Value::String("study.plugin-release-manifest.v1".to_owned());
        fs::write(signature_path, canonical(&signature)).unwrap();
        assert!(verify_installed_plugin(
            &fixture.root,
            &fixture.policy_digest,
            &fixture.runtime_manifest,
            &fixture.runtime_trust,
            fixture.now,
        )
        .unwrap_err()
        .contains("signature binding"));
    }

    #[test]
    fn rejects_expired_revoked_and_downgraded_install_authority() {
        let fixture = install_fixture();
        let after_expiry = fixture.now + Duration::from_secs(2 * 24 * 60 * 60);
        assert!(verify_installed_plugin(
            &fixture.root,
            &fixture.policy_digest,
            &fixture.runtime_manifest,
            &fixture.runtime_trust,
            after_expiry,
        )
        .unwrap_err()
        .contains("expired"));

        let fixture = install_fixture();
        let policy_path = fixture.root.join(INSTALL_POLICY);
        let mut policy: Value = serde_json::from_slice(&fs::read(&policy_path).unwrap()).unwrap();
        policy["keys"][0]["status"] = Value::String("revoked".to_owned());
        let policy_source = canonical(&policy);
        fs::write(&policy_path, &policy_source).unwrap();
        let policy_digest = hex(Sha256::digest(&policy_source));
        let policy = parse_policy(&policy_source, &policy_digest).unwrap();
        let signature_source = fs::read(fixture.root.join(INSTALL_SIGNATURE)).unwrap();
        let manifest_source = fs::read(fixture.root.join(INSTALL_MANIFEST)).unwrap();
        let now = fixture.now.duration_since(UNIX_EPOCH).unwrap().as_secs();
        assert!(verify_signature(
            &signature_source,
            &hex(Sha256::digest(manifest_source)),
            "anki-study-agent-plugin",
            "0.1.0",
            &policy,
            now,
        )
        .unwrap_err()
        .contains("signing key is revoked"));

        let fixture = install_fixture();
        let policy_path = fixture.root.join(INSTALL_POLICY);
        let mut policy: Value = serde_json::from_slice(&fs::read(&policy_path).unwrap()).unwrap();
        policy["minimumPluginVersion"] = Value::String("0.2.0".to_owned());
        let policy_source = canonical(&policy);
        fs::write(&policy_path, &policy_source).unwrap();
        let policy_digest = hex(Sha256::digest(&policy_source));
        let policy = parse_policy(&policy_source, &policy_digest).unwrap();
        let signature_source = fs::read(fixture.root.join(INSTALL_SIGNATURE)).unwrap();
        let manifest_source = fs::read(fixture.root.join(INSTALL_MANIFEST)).unwrap();
        let now = fixture.now.duration_since(UNIX_EPOCH).unwrap().as_secs();
        assert!(verify_signature(
            &signature_source,
            &hex(Sha256::digest(manifest_source)),
            "anki-study-agent-plugin",
            "0.1.0",
            &policy,
            now,
        )
        .unwrap_err()
        .contains("version or manifest is revoked"));
    }

    #[test]
    fn passive_launcher_rejects_install_wiring() {
        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "anki-study-passive-verifier-{}-{unique}",
            std::process::id()
        ));
        fs::create_dir(&root).unwrap();
        write(
            &root,
            PLUGIN_MANIFEST,
            &canonical(&json!({"name": "anki-study-agent", "version": "0.1.0"})),
        );
        assert_passive_plugin(&root).unwrap();
        write(&root, MCP_CONFIG, b"{}");
        assert!(assert_passive_plugin(&root)
            .unwrap_err()
            .contains("passive launcher"));
        fs::remove_dir_all(root).unwrap();
    }
}
