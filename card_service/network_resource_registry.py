from __future__ import annotations

import base64
import hashlib
import hmac
import http.client
import ipaddress
import json
import os
import re
import secrets
import socket
import ssl
import stat
import threading
import urllib.parse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

from .artifact_registry import ArtifactAudienceBinding, canonical_json_bytes
from .source_acquisition import (
    SourceAcquisitionError,
    YOUTUBE_SOURCE_HOSTS,
    youtube_video_id,
)


MAX_RECORD_BYTES = 1024 * 1024
MAX_URL_CHARS = 16 * 1024
MAX_PATH_CHARS = 8 * 1024
MAX_QUERY_CHARS = 8 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024 * 1024
MAX_USES = 256
MAX_REDIRECTS = 5
MAX_LIFETIME = timedelta(hours=24)
MAX_SAFE_INTEGER = 9_007_199_254_740_991

SOURCE_KINDS = frozenset({"public_video", "web", "podcast", "other"})
REDIRECT_POLICIES = frozenset({"none", "same_origin"})
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_NETWORK_REF_RE = re.compile(r"^network_[A-Za-z0-9_-]{43}$")
_PERCENT_ESCAPE_RE = re.compile(r"%(?![0-9A-Fa-f]{2})")
_SECRET_VALUE_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~-]{20,}\b", re.IGNORECASE),
)
_SENSITIVE_QUERY_KEYS = frozenset(
    {
        "access_token", "api_key", "apikey", "auth", "authorization", "awsaccesskeyid",
        "code", "credential", "key", "password", "policy", "secret", "sig", "signature",
        "token", "x-amz-credential", "x-amz-security-token", "x-goog-credential",
        "x-goog-signature",
    }
)
_BLOCKED_HOSTS = frozenset(
    {
        "localhost", "localhost.localdomain", "metadata", "metadata.google.internal",
        "instance-data", "169.254.169.254",
    }
)
_UNRESERVED = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)


class NetworkResourceRegistryError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class _CanonicalTarget:
    canonical_url: str
    approved_input: str
    host: str
    port: int
    display_origin: str
    adapter: str
    public_identity: str | None
    query_present: bool
    sensitive_query: bool


@dataclass(frozen=True)
class _InMemoryLocator:
    target: _CanonicalTarget
    canonical_request_digest: str
    query_redaction_digest: str


@dataclass(frozen=True)
class ResolvedNetworkResource:
    network_resource_ref: str
    grant_id: str
    source_kind: str
    adapter: str
    canonical_url: str
    approved_input: str
    display_origin: str
    canonical_request_digest: str
    query_redaction_digest: str
    resource_revision_digest: str
    revocation_epoch: int
    constraints: Mapping[str, Any]
    addresses: tuple[str, ...]
    redirect_count: int
    resolution_proof: str

    def legacy_binding(self, *, json_pointer: str, raw_project_value: str):
        from .legacy_project_projection import LegacyResourceBinding

        if (
            not isinstance(raw_project_value, str)
            or raw_project_value.strip() != self.approved_input
            or self.redirect_count != 0
        ):
            raise NetworkResourceRegistryError(
                "NETWORK_VALUE_MISMATCH", "legacy Project URL does not match the approved network input"
            )
        return LegacyResourceBinding(
            slot_id="slot-" + self.grant_id.rsplit("_", 1)[-1][:24],
            json_pointer=json_pointer,
            kind="source_network",
            internal_resource_binding_id=self.grant_id,
            resource_revision_digest=self.resource_revision_digest,
            resource_value_digest=hashlib.sha256(raw_project_value.encode("utf-8")).hexdigest(),
            canonical_request_digest=self.canonical_request_digest,
            display_origin=self.display_origin,
            query_redaction_digest=self.query_redaction_digest,
        )


@dataclass(frozen=True)
class NetworkFetchResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes
    peer_ip: str
    redirect_location: str | None


AddressResolver = Callable[..., list[tuple[Any, ...]]]
GestureVerifier = Callable[[str, str, str, str], bool]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise NetworkResourceRegistryError("NETWORK_TIME_INVALID", "timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise NetworkResourceRegistryError("NETWORK_TIME_INVALID", f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise NetworkResourceRegistryError("NETWORK_TIME_INVALID", f"{label} is invalid") from error
    return parsed.astimezone(timezone.utc)


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise NetworkResourceRegistryError("NETWORK_SCHEMA_INVALID", f"{label} is invalid")
    return value


def _require_digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise NetworkResourceRegistryError(
            "NETWORK_SCHEMA_INVALID", f"{label} must be a lowercase SHA-256 digest"
        )
    return value


def _require_integer(value: Any, label: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise NetworkResourceRegistryError(
            "NETWORK_SCHEMA_INVALID", f"{label} is outside its allowed range"
        )
    return value


def _exact(value: Any, required: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != required:
        raise NetworkResourceRegistryError("NETWORK_SCHEMA_INVALID", f"{label} fields are invalid")
    return dict(value)


def _opaque_input(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 512
        or any(ord(character) < 0x20 for character in value)
        or any(pattern.search(value) for pattern in _SECRET_VALUE_PATTERNS)
    ):
        raise NetworkResourceRegistryError("NETWORK_REQUEST_INVALID", f"{label} is invalid")
    return value


def _validate_audience(audience: ArtifactAudienceBinding) -> None:
    if not isinstance(audience, ArtifactAudienceBinding):
        raise NetworkResourceRegistryError("NETWORK_AUDIENCE_INVALID", "trusted audience is required")
    _require_digest(audience.owner_digest, "ownerDigest")
    _require_id(audience.host_id, "hostInstanceId")
    _require_id(audience.plugin_id, "pluginInstanceId")
    _require_id(audience.session_id, "sessionId")


def _validate_ref(value: Any) -> str:
    if not isinstance(value, str) or not _NETWORK_REF_RE.fullmatch(value):
        raise NetworkResourceRegistryError("NETWORK_REF_INVALID", "network resource reference is invalid")
    return value


def _normalize_component(value: str, *, safe: str, maximum: int, label: str) -> str:
    if len(value) > maximum or any(ord(character) < 0x20 for character in value):
        raise NetworkResourceRegistryError("NETWORK_URL_INVALID", f"network URL {label} is invalid")
    if "\\" in value or _PERCENT_ESCAPE_RE.search(value):
        raise NetworkResourceRegistryError("NETWORK_URL_INVALID", f"network URL {label} is invalid")
    encoded = urllib.parse.quote(value, safe=safe, encoding="utf-8", errors="strict")
    output: list[str] = []
    index = 0
    while index < len(encoded):
        if encoded[index] != "%":
            output.append(encoded[index])
            index += 1
            continue
        byte = int(encoded[index + 1 : index + 3], 16)
        character = chr(byte)
        output.append(character if character in _UNRESERVED else f"%{byte:02X}")
        index += 3
    return "".join(output)


def _normalize_host(parsed: urllib.parse.SplitResult) -> tuple[str, int]:
    try:
        port = parsed.port
    except ValueError as error:
        raise NetworkResourceRegistryError("NETWORK_URL_INVALID", "network URL port is invalid") from error
    if (
        parsed.scheme.casefold() != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
    ):
        raise NetworkResourceRegistryError(
            "NETWORK_URL_BLOCKED", "only credential-free public HTTPS URLs are supported"
        )
    raw_host = parsed.hostname
    if not isinstance(raw_host, str) or not raw_host:
        raise NetworkResourceRegistryError("NETWORK_URL_INVALID", "network URL host is invalid")
    raw_host = raw_host.rstrip(".")
    try:
        address = ipaddress.ip_address(raw_host)
    except ValueError:
        try:
            host = raw_host.encode("idna").decode("ascii").casefold()
        except UnicodeError as error:
            raise NetworkResourceRegistryError(
                "NETWORK_URL_INVALID", "network URL host is invalid"
            ) from error
    else:
        host = address.compressed
    if (
        not host
        or len(host) > 253
        or host in _BLOCKED_HOSTS
        or host.endswith((".local", ".localhost", ".internal", ".home", ".lan"))
        or (":" not in host and any(not label or len(label) > 63 for label in host.split(".")))
    ):
        raise NetworkResourceRegistryError("NETWORK_HOST_BLOCKED", "network URL host is blocked")
    return host, 443


def _sensitive_query(query: str) -> bool:
    if not query:
        return False
    try:
        pairs = urllib.parse.parse_qsl(query, keep_blank_values=True, strict_parsing=False)
    except ValueError:
        return True
    for key, value in pairs:
        normalized = key.casefold().replace("-", "_")
        if normalized in _SENSITIVE_QUERY_KEYS or any(pattern.search(value) for pattern in _SECRET_VALUE_PATTERNS):
            return True
    return True


def _canonical_target(raw_url: Any, source_kind: str) -> _CanonicalTarget:
    if source_kind not in SOURCE_KINDS:
        raise NetworkResourceRegistryError("NETWORK_SOURCE_KIND_INVALID", "network source kind is unsupported")
    if not isinstance(raw_url, str):
        raise NetworkResourceRegistryError("NETWORK_URL_INVALID", "network URL is invalid")
    raw = raw_url.strip()
    if (
        not raw
        or len(raw) > MAX_URL_CHARS
        or any(ord(character) < 0x20 or character.isspace() for character in raw)
    ):
        raise NetworkResourceRegistryError("NETWORK_URL_INVALID", "network URL is invalid")
    try:
        parsed = urllib.parse.urlsplit(raw)
    except ValueError as error:
        raise NetworkResourceRegistryError("NETWORK_URL_INVALID", "network URL is invalid") from error
    host, port = _normalize_host(parsed)
    if parsed.fragment:
        raise NetworkResourceRegistryError("NETWORK_FRAGMENT_BLOCKED", "URL fragments are not accepted")

    adapter = "generic_https"
    public_identity: str | None = None
    if host in YOUTUBE_SOURCE_HOSTS:
        try:
            public_identity = youtube_video_id(raw)
        except SourceAcquisitionError as error:
            raise NetworkResourceRegistryError("NETWORK_URL_INVALID", "YouTube URL is invalid") from error
        adapter = "youtube"
        host = "www.youtube.com"
        path = "/watch"
        query = urllib.parse.urlencode({"v": public_identity})
    else:
        path = _normalize_component(
            parsed.path or "/",
            safe="/:@!$&'()*+,;=-._~%",
            maximum=MAX_PATH_CHARS,
            label="path",
        )
        if any(segment in {".", ".."} for segment in path.split("/")):
            raise NetworkResourceRegistryError("NETWORK_PATH_BLOCKED", "network URL path is ambiguous")
        query = _normalize_component(
            parsed.query,
            safe=":/?@!$&'()*+,;=-._~%",
            maximum=MAX_QUERY_CHARS,
            label="query",
        )
    netloc = f"[{host}]" if ":" in host else host
    display_origin = f"https://{netloc}"
    canonical_url = urllib.parse.urlunsplit(("https", netloc, path, query, ""))
    return _CanonicalTarget(
        canonical_url=canonical_url,
        approved_input=raw,
        host=host,
        port=port,
        display_origin=display_origin,
        adapter=adapter,
        public_identity=public_identity,
        query_present=bool(query),
        sensitive_query=_sensitive_query(query) and adapter != "youtube",
    )

def _is_public_address(address: ipaddress._BaseAddress) -> bool:
    return bool(
        address.is_global
        and not address.is_private
        and not address.is_loopback
        and not address.is_link_local
        and not address.is_multicast
        and not address.is_reserved
        and not address.is_unspecified
    )


def resolve_public_network_addresses(
    host: str,
    *,
    resolver: AddressResolver = socket.getaddrinfo,
) -> tuple[str, ...]:
    try:
        records = resolver(host, 443, type=socket.SOCK_STREAM)
    except OSError as error:
        raise NetworkResourceRegistryError("NETWORK_DNS_FAILED", "network host DNS lookup failed") from error
    addresses: set[str] = set()
    for record in records:
        try:
            raw = str(record[4][0]).split("%", 1)[0]
            address = ipaddress.ip_address(raw)
        except (IndexError, TypeError, ValueError) as error:
            raise NetworkResourceRegistryError(
                "NETWORK_DNS_INVALID", "network host returned an invalid address"
            ) from error
        if not _is_public_address(address):
            raise NetworkResourceRegistryError(
                "NETWORK_DNS_PRIVATE_BLOCKED", "network host resolved to a non-public address"
            )
        addresses.add(address.compressed)
    if not addresses:
        raise NetworkResourceRegistryError("NETWORK_DNS_FAILED", "network host has no public address")
    return tuple(sorted(addresses))


def _default_constraints(source_kind: str, adapter: str) -> dict[str, Any]:
    maximum = {
        "public_video": 512 * 1024 * 1024,
        "web": 32 * 1024 * 1024,
        "podcast": 1024 * 1024 * 1024,
        "other": 64 * 1024 * 1024,
    }[source_kind]
    return {
        "actions": ["fetch"],
        "methods": ["GET"],
        "maxResponseBytes": maximum,
        "timeoutSeconds": 60,
        "redirectPolicy": "none" if adapter == "youtube" else "same_origin",
        "maxRedirects": 0 if adapter == "youtube" else 3,
    }


def _normalize_constraints(
    source_kind: str,
    adapter: str,
    value: Mapping[str, Any] | None,
) -> dict[str, Any]:
    defaults = _default_constraints(source_kind, adapter)
    if value is None:
        return defaults
    source = _exact(
        value,
        {
            "actions", "methods", "maxResponseBytes", "timeoutSeconds",
            "redirectPolicy", "maxRedirects",
        },
        "network constraints",
    )
    if source["actions"] != ["fetch"] or source["methods"] != ["GET"]:
        raise NetworkResourceRegistryError(
            "NETWORK_CONSTRAINT_INVALID", "network actions and methods are fixed"
        )
    maximum_bytes = _require_integer(
        source["maxResponseBytes"],
        "maxResponseBytes",
        minimum=1,
        maximum=defaults["maxResponseBytes"],
    )
    timeout = _require_integer(
        source["timeoutSeconds"], "timeoutSeconds", minimum=1, maximum=defaults["timeoutSeconds"]
    )
    policy = source["redirectPolicy"]
    if policy not in REDIRECT_POLICIES:
        raise NetworkResourceRegistryError(
            "NETWORK_CONSTRAINT_INVALID", "network redirect policy is invalid"
        )
    if defaults["redirectPolicy"] == "none" and policy != "none":
        raise NetworkResourceRegistryError(
            "NETWORK_CONSTRAINT_INVALID", "redirect policy exceeds the adapter policy"
        )
    redirects = _require_integer(
        source["maxRedirects"], "maxRedirects", minimum=0, maximum=defaults["maxRedirects"]
    )
    if policy == "none" and redirects != 0:
        raise NetworkResourceRegistryError(
            "NETWORK_CONSTRAINT_INVALID", "redirect count must be zero when redirects are disabled"
        )
    return {
        "actions": ["fetch"],
        "methods": ["GET"],
        "maxResponseBytes": maximum_bytes,
        "timeoutSeconds": timeout,
        "redirectPolicy": policy,
        "maxRedirects": redirects,
    }


def _constraints_are_narrower(candidate: Mapping[str, Any], granted: Mapping[str, Any]) -> bool:
    if candidate["actions"] != ["fetch"] or candidate["methods"] != ["GET"]:
        return False
    if candidate["maxResponseBytes"] > granted["maxResponseBytes"]:
        return False
    if candidate["timeoutSeconds"] > granted["timeoutSeconds"]:
        return False
    if candidate["maxRedirects"] > granted["maxRedirects"]:
        return False
    return (
        candidate["redirectPolicy"] == granted["redirectPolicy"]
        or (
            granted["redirectPolicy"] == "same_origin"
            and candidate["redirectPolicy"] == "none"
            and candidate["maxRedirects"] == 0
        )
    )


def _ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    info = path.lstat()
    attributes = getattr(info, "st_file_attributes", 0)
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or attributes & 0x400:
        raise NetworkResourceRegistryError(
            "NETWORK_STORAGE_UNSAFE", "network registry contains a link or reparse directory"
        )
    return path


def _temporary_file(path: Path, data: bytes) -> Path:
    temporary = path.parent / f".{path.name}.{secrets.token_hex(12)}.partial"
    with temporary.open("xb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    return temporary


def _file_identity(info: os.stat_result) -> tuple[int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _record_state(record: Mapping[str, Any], now: datetime, *, locator_available: bool) -> str:
    if record["revoked"]:
        return "revoked"
    if now >= _parse_timestamp(record["expiresAt"], "expiresAt"):
        return "expired"
    if record["useCount"] >= record["maxUses"]:
        return "exhausted"
    if not locator_available:
        return "reauthorization_required"
    return "active"


def _public_summary(
    record: Mapping[str, Any],
    network_resource_ref: str,
    now: datetime,
    *,
    locator_available: bool,
) -> dict[str, Any]:
    return {
        "schema": "study.network-resource.summary",
        "schemaVersion": 1,
        "networkResourceRef": network_resource_ref,
        "sourceKind": record["sourceKind"],
        "adapter": record["adapter"],
        "displayOrigin": record["displayOrigin"],
        "publicIdentity": record["publicIdentity"],
        "queryPresent": record["queryPresent"],
        "sensitiveQuery": record["sensitiveQuery"],
        "constraints": json.loads(json.dumps(record["constraints"])),
        "resourceRevisionDigest": record["resourceRevisionDigest"],
        "expiresAt": record["expiresAt"],
        "state": _record_state(record, now, locator_available=locator_available),
        "revocationEpoch": record["revocationEpoch"],
        "remainingUses": max(0, record["maxUses"] - record["useCount"]),
    }


class _PinnedHttpsConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        host: str,
        address: str,
        *,
        timeout: float,
        context: ssl.SSLContext,
    ) -> None:
        super().__init__(host, 443, timeout=timeout, context=context)
        self._address = address

    def connect(self) -> None:
        raw = socket.create_connection((self._address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise


class PinnedNetworkFetcher:
    """HTTPS GET transport that never consults ambient proxies, cookies, or credentials."""

    _PUBLIC_HEADERS = frozenset({"content-type", "content-length", "etag", "last-modified"})

    def __init__(
        self,
        *,
        ssl_context: ssl.SSLContext | None = None,
        connection_factory: Callable[..., http.client.HTTPSConnection] = _PinnedHttpsConnection,
    ) -> None:
        self._ssl_context = ssl_context or ssl.create_default_context()
        self._connection_factory = connection_factory

    def fetch(
        self,
        resource: ResolvedNetworkResource,
        *,
        maximum_bytes: int | None = None,
        timeout_seconds: int | None = None,
    ) -> NetworkFetchResponse:
        if not isinstance(resource, ResolvedNetworkResource):
            raise NetworkResourceRegistryError(
                "NETWORK_RESOLUTION_INVALID", "resolved network resource is required"
            )
        limit = resource.constraints["maxResponseBytes"] if maximum_bytes is None else _require_integer(
            maximum_bytes,
            "maximumBytes",
            minimum=1,
            maximum=resource.constraints["maxResponseBytes"],
        )
        timeout = resource.constraints["timeoutSeconds"] if timeout_seconds is None else _require_integer(
            timeout_seconds,
            "timeoutSeconds",
            minimum=1,
            maximum=resource.constraints["timeoutSeconds"],
        )
        parsed = urllib.parse.urlsplit(resource.canonical_url)
        target = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
        last_error: Exception | None = None
        for address in resource.addresses:
            connection = self._connection_factory(
                parsed.hostname,
                address,
                timeout=float(timeout),
                context=self._ssl_context,
            )
            try:
                connection.request(
                    "GET",
                    target,
                    headers={
                        "Accept": "*/*",
                        "Accept-Encoding": "identity",
                        "Connection": "close",
                        "User-Agent": "CodexStudy/1.0 (+network resource broker)",
                    },
                )
                response = connection.getresponse()
                length_header = response.getheader("Content-Length")
                if length_header:
                    try:
                        declared = int(length_header)
                    except ValueError as error:
                        raise NetworkResourceRegistryError(
                            "NETWORK_RESPONSE_INVALID", "network response length is invalid"
                        ) from error
                    if declared < 0 or declared > limit:
                        raise NetworkResourceRegistryError(
                            "NETWORK_RESPONSE_LIMIT", "network response exceeds its byte limit"
                        )
                body = response.read(limit + 1)
                if len(body) > limit:
                    raise NetworkResourceRegistryError(
                        "NETWORK_RESPONSE_LIMIT", "network response exceeds its byte limit"
                    )
                headers = {
                    name.casefold(): value
                    for name, value in response.getheaders()
                    if name.casefold() in self._PUBLIC_HEADERS
                }
                return NetworkFetchResponse(
                    status=int(response.status),
                    headers=headers,
                    body=body,
                    peer_ip=address,
                    redirect_location=response.getheader("Location"),
                )
            except NetworkResourceRegistryError:
                raise
            except (OSError, ssl.SSLError, http.client.HTTPException) as error:
                last_error = error
            finally:
                connection.close()
        raise NetworkResourceRegistryError(
            "NETWORK_FETCH_FAILED", "pinned HTTPS request failed"
        ) from last_error


class NetworkResourceGrantRegistry:
    """Session-scoped URL grants with authenticated metadata and memory-only locators."""

    def __init__(
        self,
        root: Path,
        *,
        authentication_key: bytes,
        service_instance_id: str,
        key_id: str = "study-network-resource-v1",
        gesture_verifier: GestureVerifier | None = None,
        resolver: AddressResolver = socket.getaddrinfo,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        if not isinstance(authentication_key, bytes) or len(authentication_key) < 32:
            raise NetworkResourceRegistryError(
                "NETWORK_AUTH_KEY_INVALID", "network authentication key must contain at least 256 bits"
            )
        if gesture_verifier is not None and not callable(gesture_verifier):
            raise NetworkResourceRegistryError(
                "NETWORK_GESTURE_VERIFIER_INVALID", "trusted gesture verifier is invalid"
            )
        if not callable(resolver) or not callable(clock):
            raise NetworkResourceRegistryError(
                "NETWORK_DEPENDENCY_INVALID", "network resolver or clock is invalid"
            )
        self._authentication_key = bytes(authentication_key)
        self._service_instance_id = _require_id(service_instance_id, "serviceInstanceId")
        self._key_id = _require_id(key_id, "keyId")
        self._gesture_verifier = gesture_verifier
        self._resolver = resolver
        self._clock = clock
        self._root = _ensure_directory(Path(root).absolute())
        self._records_root = _ensure_directory(self._root / "records")
        self._bindings_root = _ensure_directory(self._root / "bindings")
        self._lock_path = self._root / "network-resources.lock"
        try:
            with self._lock_path.open("xb") as output:
                output.write(b"\x00")
                output.flush()
                os.fsync(output.fileno())
        except FileExistsError:
            pass
        self._thread_lock = threading.RLock()
        self._locators: dict[str, _InMemoryLocator] = {}

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise NetworkResourceRegistryError(
                "NETWORK_CLOCK_INVALID", "network clock returned an invalid time"
            )
        return value.astimezone(timezone.utc)

    def _ensure_parent(self, path: Path) -> None:
        try:
            relative = path.absolute().relative_to(self._root)
        except ValueError as error:
            raise NetworkResourceRegistryError(
                "NETWORK_STORAGE_UNSAFE", "network registry path escapes its root"
            ) from error
        current = _ensure_directory(self._root)
        for part in relative.parts:
            current = _ensure_directory(current / part)

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        with self._thread_lock:
            info = self._lock_path.lstat()
            attributes = getattr(info, "st_file_attributes", 0)
            if (
                not stat.S_ISREG(info.st_mode)
                or stat.S_ISLNK(info.st_mode)
                or attributes & 0x400
                or info.st_nlink != 1
            ):
                raise NetworkResourceRegistryError(
                    "NETWORK_STORAGE_UNSAFE", "network registry lock is not a private regular file"
                )
            with self._lock_path.open("r+b") as lock_file:
                lock_file.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
                    try:
                        yield
                    finally:
                        lock_file.seek(0)
                        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                    try:
                        yield
                    finally:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _mac(self, domain: str, value: Mapping[str, Any] | bytes) -> str:
        payload = value if isinstance(value, bytes) else canonical_json_bytes(dict(value))
        return hmac.new(
            self._authentication_key,
            domain.encode("ascii") + b"\x00" + payload,
            hashlib.sha256,
        ).hexdigest()

    def _audience_digest(self, audience: ArtifactAudienceBinding) -> str:
        _validate_audience(audience)
        return _sha(canonical_json_bytes(audience.audience(self._service_instance_id)))

    def _opaque_digest(self, domain: str, value: str) -> str:
        return self._mac(domain, value.encode("utf-8"))

    def _derive_grant_id(self, audience_digest: str, request_id: str) -> str:
        digest = self._mac(
            "study.network-resource.grant-id.v1",
            audience_digest.encode("ascii") + b"\x00" + request_id.encode("utf-8"),
        )
        return "networkgrant_" + digest[:48]

    def _derive_ref(self, grant_id: str) -> str:
        digest = hmac.new(
            self._authentication_key,
            b"study.network-resource.ref.v1\x00" + grant_id.encode("ascii"),
            hashlib.sha256,
        ).digest()
        return "network_" + base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    def _record_path(self, grant_id: str) -> Path:
        identity = _sha(_require_id(grant_id, "grantId").encode("ascii"))
        return self._records_root / identity[:2] / f"{identity}.json"

    def _binding_path(self, network_resource_ref: str) -> Path:
        identity = _sha(_validate_ref(network_resource_ref).encode("ascii"))
        return self._bindings_root / identity[:2] / f"{identity}.json"

    def _safe_read(self, path: Path) -> bytes:
        self._ensure_parent(path.parent)
        try:
            info = path.lstat()
        except FileNotFoundError as error:
            raise NetworkResourceRegistryError(
                "NETWORK_RESOURCE_NOT_FOUND", "network resource grant was not found"
            ) from error
        attributes = getattr(info, "st_file_attributes", 0)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or attributes & 0x400
            or info.st_nlink != 1
            or info.st_size > MAX_RECORD_BYTES
        ):
            raise NetworkResourceRegistryError(
                "NETWORK_STORAGE_UNSAFE", "network registry entry is unsafe or too large"
            )
        raw = path.read_bytes()
        after = path.lstat()
        if len(raw) != info.st_size or _file_identity(info) != _file_identity(after):
            raise NetworkResourceRegistryError(
                "NETWORK_RECORD_CHANGED", "network registry entry changed while being read"
            )
        return raw

    def _decode_json(self, raw: bytes) -> dict[str, Any]:
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise NetworkResourceRegistryError(
                "NETWORK_RECORD_INVALID", "network registry entry is not valid JSON"
            ) from error
        if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
            raise NetworkResourceRegistryError(
                "NETWORK_RECORD_INVALID", "network registry entry is not canonical JSON"
            )
        return value

    def _authenticate_record(self, value: Mapping[str, Any]) -> dict[str, Any]:
        unsigned = {**dict(value), "authKeyId": self._key_id}
        return {**unsigned, "authTag": self._mac("study.network-resource.record.v1", unsigned)}

    def _authenticate_binding(self, value: Mapping[str, Any]) -> dict[str, Any]:
        unsigned = {**dict(value), "authKeyId": self._key_id}
        return {**unsigned, "authTag": self._mac("study.network-resource.binding.v1", unsigned)}

    def _validate_record(self, value: Mapping[str, Any]) -> dict[str, Any]:
        record = _exact(
            value,
            {
                "schema", "schemaVersion", "grantId", "audienceDigest", "sourceKind",
                "adapter", "displayOrigin", "publicIdentity", "queryPresent",
                "sensitiveQuery", "canonicalRequestDigest", "queryRedactionDigest",
                "resourceRevisionDigest", "initialAddressSetDigest", "constraints",
                "requestDigest", "attestationDigest", "issuedAt", "expiresAt",
                "maxUses", "useCount", "useHistory", "revoked", "revocationEpoch",
                "revokeDigest", "revokeAttestationDigest", "revokedAt", "revision",
                "authKeyId", "authTag",
            },
            "network resource record",
        )
        if record["schema"] != "study.network-resource.record" or record["schemaVersion"] != 1:
            raise NetworkResourceRegistryError(
                "NETWORK_RECORD_INVALID", "network resource record schema is invalid"
            )
        tag = record["authTag"]
        unsigned = dict(record)
        unsigned.pop("authTag")
        if (
            record["authKeyId"] != self._key_id
            or not isinstance(tag, str)
            or not _SHA256_RE.fullmatch(tag)
            or not hmac.compare_digest(tag, self._mac("study.network-resource.record.v1", unsigned))
        ):
            raise NetworkResourceRegistryError(
                "NETWORK_RECORD_CORRUPT", "network resource record authentication failed"
            )
        _require_id(record["grantId"], "grantId")
        _require_digest(record["audienceDigest"], "audienceDigest")
        if record["sourceKind"] not in SOURCE_KINDS or record["adapter"] not in {
            "youtube", "generic_https"
        }:
            raise NetworkResourceRegistryError(
                "NETWORK_RECORD_INVALID", "network source identity is invalid"
            )
        try:
            display = urllib.parse.urlsplit(record["displayOrigin"])
            display_port = display.port
        except (TypeError, ValueError) as error:
            raise NetworkResourceRegistryError(
                "NETWORK_RECORD_INVALID", "network display origin is invalid"
            ) from error
        if (
            display.scheme != "https"
            or not display.hostname
            or display.username is not None
            or display.password is not None
            or display.path not in {"", "/"}
            or display.query
            or display.fragment
            or display_port not in {None, 443}
        ):
            raise NetworkResourceRegistryError(
                "NETWORK_RECORD_INVALID", "network display origin is invalid"
            )
        identity = record["publicIdentity"]
        if identity is not None and (
            not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", identity)
        ):
            raise NetworkResourceRegistryError(
                "NETWORK_RECORD_INVALID", "network public identity is invalid"
            )
        if record["adapter"] == "youtube" and not isinstance(identity, str):
            raise NetworkResourceRegistryError(
                "NETWORK_RECORD_INVALID", "YouTube public identity is missing"
            )
        if not isinstance(record["queryPresent"], bool) or not isinstance(record["sensitiveQuery"], bool):
            raise NetworkResourceRegistryError(
                "NETWORK_RECORD_INVALID", "network query classification is invalid"
            )
        for field in (
            "canonicalRequestDigest", "queryRedactionDigest", "resourceRevisionDigest",
            "initialAddressSetDigest", "requestDigest", "attestationDigest",
        ):
            _require_digest(record[field], field)
        normalized_constraints = _normalize_constraints(
            record["sourceKind"], record["adapter"], record["constraints"]
        )
        if normalized_constraints != record["constraints"]:
            raise NetworkResourceRegistryError(
                "NETWORK_RECORD_INVALID", "network constraints are not canonical"
            )
        issued = _parse_timestamp(record["issuedAt"], "issuedAt")
        expires = _parse_timestamp(record["expiresAt"], "expiresAt")
        if not issued < expires or expires - issued > MAX_LIFETIME:
            raise NetworkResourceRegistryError(
                "NETWORK_RECORD_INVALID", "network grant lifetime is invalid"
            )
        maximum_uses = _require_integer(record["maxUses"], "maxUses", minimum=1, maximum=MAX_USES)
        use_count = _require_integer(record["useCount"], "useCount", minimum=0, maximum=maximum_uses)
        history = record["useHistory"]
        if not isinstance(history, list) or len(history) != use_count:
            raise NetworkResourceRegistryError(
                "NETWORK_RECORD_INVALID", "network use history is invalid"
            )
        seen: set[str] = set()
        previous = issued
        for entry in history:
            item = _exact(
                entry,
                {"useDigest", "requestDigest", "usedAt"},
                "network use record",
            )
            use_digest = _require_digest(item["useDigest"], "useDigest")
            _require_digest(item["requestDigest"], "use.requestDigest")
            used_at = _parse_timestamp(item["usedAt"], "usedAt")
            if use_digest in seen or used_at < previous or used_at >= expires:
                raise NetworkResourceRegistryError(
                    "NETWORK_RECORD_INVALID", "network use record is duplicated or out of order"
                )
            seen.add(use_digest)
            previous = used_at
        if not isinstance(record["revoked"], bool):
            raise NetworkResourceRegistryError(
                "NETWORK_RECORD_INVALID", "network revocation state is invalid"
            )
        epoch = _require_integer(record["revocationEpoch"], "revocationEpoch", minimum=0, maximum=1)
        if record["revoked"] != (epoch == 1):
            raise NetworkResourceRegistryError(
                "NETWORK_RECORD_INVALID", "network revocation state is inconsistent"
            )
        if record["revoked"]:
            _require_digest(record["revokeDigest"], "revokeDigest")
            _require_digest(record["revokeAttestationDigest"], "revokeAttestationDigest")
            revoked_at = _parse_timestamp(record["revokedAt"], "revokedAt")
            if revoked_at < issued:
                raise NetworkResourceRegistryError(
                    "NETWORK_RECORD_INVALID", "network revocation time is invalid"
                )
        elif any(
            record[field] is not None
            for field in ("revokeDigest", "revokeAttestationDigest", "revokedAt")
        ):
            raise NetworkResourceRegistryError(
                "NETWORK_RECORD_INVALID", "network revocation audit is invalid"
            )
        revision = _require_integer(record["revision"], "revision", minimum=1, maximum=MAX_SAFE_INTEGER)
        if revision != 1 + use_count + epoch:
            raise NetworkResourceRegistryError(
                "NETWORK_RECORD_INVALID", "network resource revision is inconsistent"
            )
        return record

    def _validate_binding(
        self,
        value: Mapping[str, Any],
        network_resource_ref: str,
        audience_digest: str,
    ) -> dict[str, Any]:
        binding = _exact(
            value,
            {
                "schema", "schemaVersion", "networkResourceRefDigest", "grantId",
                "audienceDigest", "authKeyId", "authTag",
            },
            "network resource binding",
        )
        if binding["schema"] != "study.network-resource.binding" or binding["schemaVersion"] != 1:
            raise NetworkResourceRegistryError(
                "NETWORK_BINDING_INVALID", "network resource binding schema is invalid"
            )
        tag = binding["authTag"]
        unsigned = dict(binding)
        unsigned.pop("authTag")
        if (
            binding["authKeyId"] != self._key_id
            or not isinstance(tag, str)
            or not _SHA256_RE.fullmatch(tag)
            or not hmac.compare_digest(tag, self._mac("study.network-resource.binding.v1", unsigned))
        ):
            raise NetworkResourceRegistryError(
                "NETWORK_BINDING_CORRUPT", "network resource binding authentication failed"
            )
        if binding["networkResourceRefDigest"] != _sha(network_resource_ref.encode("ascii")):
            raise NetworkResourceRegistryError(
                "NETWORK_BINDING_MISMATCH", "network resource reference binding is invalid"
            )
        if binding["audienceDigest"] != audience_digest:
            raise NetworkResourceRegistryError(
                "NETWORK_AUDIENCE_MISMATCH", "network grant belongs to another trusted session"
            )
        _require_id(binding["grantId"], "grantId")
        return binding

    def _load_record(self, grant_id: str) -> tuple[dict[str, Any], bytes]:
        raw = self._safe_read(self._record_path(grant_id))
        return self._validate_record(self._decode_json(raw)), raw

    def _load_binding(self, network_resource_ref: str, audience_digest: str) -> dict[str, Any]:
        raw = self._safe_read(self._binding_path(network_resource_ref))
        return self._validate_binding(
            self._decode_json(raw), network_resource_ref, audience_digest
        )

    def _publish_new(self, path: Path, raw: bytes) -> None:
        self._ensure_parent(path.parent)
        temporary = _temporary_file(path, raw)
        try:
            try:
                os.link(temporary, path)
            except FileExistsError as error:
                raise NetworkResourceRegistryError(
                    "NETWORK_RESOURCE_ALREADY_EXISTS", "network registry entry already exists"
                ) from error
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def _replace(self, path: Path, raw: bytes, previous_raw: bytes) -> None:
        self._ensure_parent(path.parent)
        backup = path.with_suffix(path.suffix + ".bak")
        backup_temp = _temporary_file(backup, previous_raw)
        current_temp = _temporary_file(path, raw)
        try:
            os.replace(backup_temp, backup)
            os.replace(current_temp, path)
        finally:
            for temporary in (backup_temp, current_temp):
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass

    def _verify_gesture(
        self,
        *,
        audience_digest: str,
        request_digest: str,
        attestation_ref: str,
        action: str,
    ) -> str:
        attestation_ref = _opaque_input(attestation_ref, "attestationRef")
        if self._gesture_verifier is None:
            raise NetworkResourceRegistryError(
                "NETWORK_GESTURE_REQUIRED", "trusted user gesture verification is unavailable"
            )
        try:
            accepted = self._gesture_verifier(
                audience_digest, request_digest, attestation_ref, action
            )
        except Exception as error:
            raise NetworkResourceRegistryError(
                "NETWORK_GESTURE_FAILED", "trusted user gesture verification failed"
            ) from error
        if accepted is not True:
            raise NetworkResourceRegistryError(
                "NETWORK_GESTURE_REQUIRED", "a current trusted user gesture is required"
            )
        return self._opaque_digest("study.network-resource.attestation.v1", attestation_ref)

    @staticmethod
    def _authorize(record: Mapping[str, Any], audience_digest: str) -> None:
        if record["audienceDigest"] != audience_digest:
            raise NetworkResourceRegistryError(
                "NETWORK_AUDIENCE_MISMATCH", "network grant belongs to another trusted session"
            )

    def _resolve_record(
        self,
        network_resource_ref: str,
        audience: ArtifactAudienceBinding,
    ) -> tuple[str, dict[str, Any], bytes]:
        normalized_ref = _validate_ref(network_resource_ref)
        audience_digest = self._audience_digest(audience)
        binding = self._load_binding(normalized_ref, audience_digest)
        record, raw = self._load_record(binding["grantId"])
        self._authorize(record, audience_digest)
        return normalized_ref, record, raw


    def _request_digests(self, target: _CanonicalTarget) -> tuple[str, str]:
        parsed = urllib.parse.urlsplit(target.canonical_url)
        return (
            self._opaque_digest(
                "study.network-resource.canonical-request.v1", target.canonical_url
            ),
            self._opaque_digest(
                "study.network-resource.query-redaction.v1", parsed.query
            ),
        )

    def _resolution_proof(
        self,
        *,
        grant_id: str,
        canonical_request_digest: str,
        resource_revision_digest: str,
        constraints: Mapping[str, Any],
        redirect_count: int,
    ) -> str:
        return self._mac(
            "study.network-resource.resolution.v1",
            {
                "grantId": grant_id,
                "canonicalRequestDigest": canonical_request_digest,
                "resourceRevisionDigest": resource_revision_digest,
                "constraints": dict(constraints),
                "redirectCount": redirect_count,
            },
        )

    def _resolved(
        self,
        *,
        network_resource_ref: str,
        record: Mapping[str, Any],
        locator: _InMemoryLocator,
        target: _CanonicalTarget,
        addresses: tuple[str, ...],
        constraints: Mapping[str, Any],
        redirect_count: int,
    ) -> ResolvedNetworkResource:
        canonical_digest, query_digest = self._request_digests(target)
        proof = self._resolution_proof(
            grant_id=record["grantId"],
            canonical_request_digest=canonical_digest,
            resource_revision_digest=record["resourceRevisionDigest"],
            constraints=constraints,
            redirect_count=redirect_count,
        )
        return ResolvedNetworkResource(
            network_resource_ref=network_resource_ref,
            grant_id=record["grantId"],
            source_kind=record["sourceKind"],
            adapter=record["adapter"],
            canonical_url=target.canonical_url,
            approved_input=locator.target.approved_input,
            display_origin=record["displayOrigin"],
            canonical_request_digest=canonical_digest,
            query_redaction_digest=query_digest,
            resource_revision_digest=record["resourceRevisionDigest"],
            revocation_epoch=record["revocationEpoch"],
            constraints=json.loads(json.dumps(constraints)),
            addresses=addresses,
            redirect_count=redirect_count,
            resolution_proof=proof,
        )

    def _verify_resolution(self, resource: ResolvedNetworkResource) -> None:
        if not isinstance(resource, ResolvedNetworkResource):
            raise NetworkResourceRegistryError(
                "NETWORK_RESOLUTION_INVALID", "resolved network resource is invalid"
            )
        expected = self._resolution_proof(
            grant_id=resource.grant_id,
            canonical_request_digest=resource.canonical_request_digest,
            resource_revision_digest=resource.resource_revision_digest,
            constraints=resource.constraints,
            redirect_count=resource.redirect_count,
        )
        if not hmac.compare_digest(resource.resolution_proof, expected):
            raise NetworkResourceRegistryError(
                "NETWORK_RESOLUTION_INVALID", "resolved network resource proof is invalid"
            )

    def issue_grant(
        self,
        *,
        audience: ArtifactAudienceBinding,
        grant_request_id: str,
        raw_url: str,
        source_kind: str,
        attestation_ref: str,
        constraints: Mapping[str, Any] | None = None,
        expires_at: datetime | str | None = None,
        max_uses: int = 1,
    ) -> dict[str, Any]:
        audience_digest = self._audience_digest(audience)
        request_id = _opaque_input(grant_request_id, "grantRequestId")
        target = _canonical_target(raw_url, source_kind)
        addresses = resolve_public_network_addresses(target.host, resolver=self._resolver)
        canonical_digest, query_digest = self._request_digests(target)
        normalized_constraints = _normalize_constraints(source_kind, target.adapter, constraints)
        maximum_uses = _require_integer(max_uses, "maxUses", minimum=1, maximum=MAX_USES)
        grant_id = self._derive_grant_id(audience_digest, request_id)
        network_resource_ref = self._derive_ref(grant_id)
        now = self._now()

        existing: dict[str, Any] | None = None
        with self._transaction():
            try:
                existing, _ = self._load_record(grant_id)
                self._authorize(existing, audience_digest)
            except NetworkResourceRegistryError as error:
                if error.code != "NETWORK_RESOURCE_NOT_FOUND":
                    raise
        if expires_at is None and existing is not None:
            expires = _parse_timestamp(existing["expiresAt"], "expiresAt")
        elif expires_at is None:
            expires = now + timedelta(minutes=15)
        elif isinstance(expires_at, str):
            expires = _parse_timestamp(expires_at, "expiresAt")
        elif isinstance(expires_at, datetime) and expires_at.tzinfo is not None:
            expires = expires_at.astimezone(timezone.utc)
        else:
            raise NetworkResourceRegistryError("NETWORK_TIME_INVALID", "expiresAt is invalid")
        if existing is None and (expires <= now or expires - now > MAX_LIFETIME):
            raise NetworkResourceRegistryError(
                "NETWORK_TIME_INVALID", "network grant must expire within the next 24 hours"
            )
        expires_text = _timestamp(expires)
        address_digest = _sha(canonical_json_bytes(list(addresses)))
        revision_manifest = {
            "schema": "study.network-resource.revision",
            "schemaVersion": 1,
            "sourceKind": source_kind,
            "adapter": target.adapter,
            "canonicalRequestDigest": canonical_digest,
            "queryRedactionDigest": query_digest,
            "constraints": normalized_constraints,
        }
        resource_revision_digest = _sha(canonical_json_bytes(revision_manifest))
        request_manifest = {
            "schema": "study.network-resource.grant-request",
            "schemaVersion": 1,
            "audienceDigest": audience_digest,
            "grantId": grant_id,
            "resourceRevisionDigest": resource_revision_digest,
            "expiresAt": expires_text,
            "maxUses": maximum_uses,
        }
        request_digest = _sha(canonical_json_bytes(request_manifest))
        locator = _InMemoryLocator(
            target=target,
            canonical_request_digest=canonical_digest,
            query_redaction_digest=query_digest,
        )

        if existing is not None:
            if existing["requestDigest"] != request_digest:
                raise NetworkResourceRegistryError(
                    "NETWORK_IDEMPOTENCY_CONFLICT",
                    "grantRequestId was already used for a different network grant",
                )
            with self._transaction():
                current, _ = self._load_record(grant_id)
                self._authorize(current, audience_digest)
                if current["requestDigest"] != request_digest:
                    raise NetworkResourceRegistryError(
                        "NETWORK_IDEMPOTENCY_CONFLICT",
                        "grantRequestId was already used for a different network grant",
                    )
                if grant_id not in self._locators:
                    raise NetworkResourceRegistryError(
                        "NETWORK_REAUTHORIZATION_REQUIRED",
                        "network locator was intentionally not restored; create a new trusted grant",
                    )
                self._load_binding(network_resource_ref, audience_digest)
                return _public_summary(
                    current,
                    network_resource_ref,
                    now,
                    locator_available=True,
                )

        attestation_digest = self._verify_gesture(
            audience_digest=audience_digest,
            request_digest=request_digest,
            attestation_ref=attestation_ref,
            action="approve_network_resource",
        )
        display_origin = target.display_origin
        if any(pattern.search(target.host) for pattern in _SECRET_VALUE_PATTERNS):
            display_origin = "https://redacted.invalid"
        unsigned_record = {
            "schema": "study.network-resource.record",
            "schemaVersion": 1,
            "grantId": grant_id,
            "audienceDigest": audience_digest,
            "sourceKind": source_kind,
            "adapter": target.adapter,
            "displayOrigin": display_origin,
            "publicIdentity": target.public_identity,
            "queryPresent": target.query_present,
            "sensitiveQuery": target.sensitive_query,
            "canonicalRequestDigest": canonical_digest,
            "queryRedactionDigest": query_digest,
            "resourceRevisionDigest": resource_revision_digest,
            "initialAddressSetDigest": address_digest,
            "constraints": normalized_constraints,
            "requestDigest": request_digest,
            "attestationDigest": attestation_digest,
            "issuedAt": _timestamp(now),
            "expiresAt": expires_text,
            "maxUses": maximum_uses,
            "useCount": 0,
            "useHistory": [],
            "revoked": False,
            "revocationEpoch": 0,
            "revokeDigest": None,
            "revokeAttestationDigest": None,
            "revokedAt": None,
            "revision": 1,
        }
        record = self._authenticate_record(unsigned_record)
        self._validate_record(record)
        binding = self._authenticate_binding(
            {
                "schema": "study.network-resource.binding",
                "schemaVersion": 1,
                "networkResourceRefDigest": _sha(network_resource_ref.encode("ascii")),
                "grantId": grant_id,
                "audienceDigest": audience_digest,
            }
        )
        with self._transaction():
            try:
                current, _ = self._load_record(grant_id)
            except NetworkResourceRegistryError as error:
                if error.code != "NETWORK_RESOURCE_NOT_FOUND":
                    raise
            else:
                self._authorize(current, audience_digest)
                if current["requestDigest"] != request_digest:
                    raise NetworkResourceRegistryError(
                        "NETWORK_IDEMPOTENCY_CONFLICT",
                        "grantRequestId was already used for a different network grant",
                    )
                if grant_id not in self._locators:
                    raise NetworkResourceRegistryError(
                        "NETWORK_REAUTHORIZATION_REQUIRED",
                        "network locator was intentionally not restored; create a new trusted grant",
                    )
                return _public_summary(
                    current, network_resource_ref, now, locator_available=True
                )
            self._publish_new(
                self._record_path(grant_id), canonical_json_bytes(record)
            )
            self._publish_new(
                self._binding_path(network_resource_ref), canonical_json_bytes(binding)
            )
            self._locators[grant_id] = locator
        return _public_summary(record, network_resource_ref, now, locator_available=True)

    def inspect(
        self,
        network_resource_ref: str,
        audience: ArtifactAudienceBinding,
    ) -> dict[str, Any]:
        with self._transaction():
            normalized_ref, record, _ = self._resolve_record(network_resource_ref, audience)
            now = self._now()
            state = _record_state(
                record, now, locator_available=record["grantId"] in self._locators
            )
            if state in {"expired", "revoked"}:
                self._locators.pop(record["grantId"], None)
            return _public_summary(
                record,
                normalized_ref,
                now,
                locator_available=record["grantId"] in self._locators,
            )

    def consume(
        self,
        network_resource_ref: str,
        audience: ArtifactAudienceBinding,
        *,
        use_id: str,
        expected_resource_revision_digest: str,
        expected_revocation_epoch: int,
        requested_constraints: Mapping[str, Any] | None = None,
    ) -> ResolvedNetworkResource:
        use_id = _opaque_input(use_id, "useId")
        expected_digest = _require_digest(
            expected_resource_revision_digest, "expectedResourceRevisionDigest"
        )
        expected_epoch = _require_integer(
            expected_revocation_epoch, "expectedRevocationEpoch", minimum=0, maximum=1
        )
        audience_digest = self._audience_digest(audience)
        with self._transaction():
            normalized_ref, record, previous_raw = self._resolve_record(
                network_resource_ref, audience
            )
            now = self._now()
            locator = self._locators.get(record["grantId"])
            state = _record_state(record, now, locator_available=locator is not None)
            if state == "revoked":
                self._locators.pop(record["grantId"], None)
                raise NetworkResourceRegistryError(
                    "NETWORK_RESOURCE_REVOKED", "network resource grant has been revoked"
                )
            if state == "expired":
                self._locators.pop(record["grantId"], None)
                raise NetworkResourceRegistryError(
                    "NETWORK_RESOURCE_EXPIRED", "network resource grant has expired"
                )
            if state == "reauthorization_required" or locator is None:
                raise NetworkResourceRegistryError(
                    "NETWORK_REAUTHORIZATION_REQUIRED",
                    "network URL must be re-entered through the trusted local surface",
                )
            if record["revocationEpoch"] != expected_epoch:
                raise NetworkResourceRegistryError(
                    "NETWORK_REVOCATION_CHANGED", "network revocation epoch changed"
                )
            if record["resourceRevisionDigest"] != expected_digest:
                raise NetworkResourceRegistryError(
                    "NETWORK_REVISION_MISMATCH", "network resource revision is stale"
                )
            effective_constraints = (
                json.loads(json.dumps(record["constraints"]))
                if requested_constraints is None
                else _normalize_constraints(
                    record["sourceKind"], record["adapter"], requested_constraints
                )
            )
            if not _constraints_are_narrower(effective_constraints, record["constraints"]):
                raise NetworkResourceRegistryError(
                    "NETWORK_CONSTRAINT_FORBIDDEN",
                    "requested network constraints exceed the approved grant",
                )
            addresses = resolve_public_network_addresses(
                locator.target.host, resolver=self._resolver
            )
            use_digest = self._mac(
                "study.network-resource.use-id.v1",
                audience_digest.encode("ascii") + b"\x00" + use_id.encode("utf-8"),
            )
            request_digest = _sha(
                canonical_json_bytes(
                    {
                        "schema": "study.network-resource.use-request",
                        "schemaVersion": 1,
                        "grantId": record["grantId"],
                        "useDigest": use_digest,
                        "resourceRevisionDigest": expected_digest,
                        "revocationEpoch": expected_epoch,
                        "constraints": effective_constraints,
                    }
                )
            )
            for item in record["useHistory"]:
                if item["useDigest"] == use_digest:
                    if item["requestDigest"] != request_digest:
                        raise NetworkResourceRegistryError(
                            "NETWORK_USE_ID_CONFLICT",
                            "useId was reused for a different network request",
                        )
                    return self._resolved(
                        network_resource_ref=normalized_ref,
                        record=record,
                        locator=locator,
                        target=locator.target,
                        addresses=addresses,
                        constraints=effective_constraints,
                        redirect_count=0,
                    )
            if state == "exhausted":
                raise NetworkResourceRegistryError(
                    "NETWORK_USES_EXHAUSTED", "network resource grant has no remaining uses"
                )
            unsigned = dict(record)
            unsigned.pop("authKeyId")
            unsigned.pop("authTag")
            unsigned.update(
                {
                    "useCount": record["useCount"] + 1,
                    "useHistory": [
                        *record["useHistory"],
                        {
                            "useDigest": use_digest,
                            "requestDigest": request_digest,
                            "usedAt": _timestamp(now),
                        },
                    ],
                    "revision": record["revision"] + 1,
                }
            )
            updated = self._authenticate_record(unsigned)
            self._validate_record(updated)
            self._replace(
                self._record_path(record["grantId"]),
                canonical_json_bytes(updated),
                previous_raw,
            )
            return self._resolved(
                network_resource_ref=normalized_ref,
                record=updated,
                locator=locator,
                target=locator.target,
                addresses=addresses,
                constraints=effective_constraints,
                redirect_count=0,
            )

    def authorize_redirect(
        self,
        resource: ResolvedNetworkResource,
        audience: ArtifactAudienceBinding,
        *,
        location: str,
        redirect_index: int,
    ) -> ResolvedNetworkResource:
        self._assert_resolution_active(resource, audience)
        index = _require_integer(
            redirect_index, "redirectIndex", minimum=1, maximum=MAX_REDIRECTS
        )
        if index != resource.redirect_count + 1:
            raise NetworkResourceRegistryError(
                "NETWORK_REDIRECT_ORDER_INVALID", "network redirect order is invalid"
            )
        policy = resource.constraints["redirectPolicy"]
        if policy == "none" or index > resource.constraints["maxRedirects"]:
            raise NetworkResourceRegistryError(
                "NETWORK_REDIRECT_BLOCKED", "network redirects are not approved"
            )
        if (
            not isinstance(location, str)
            or not location
            or len(location) > MAX_URL_CHARS
            or any(ord(character) < 0x20 for character in location)
        ):
            raise NetworkResourceRegistryError(
                "NETWORK_REDIRECT_INVALID", "network redirect target is invalid"
            )
        joined = urllib.parse.urljoin(resource.canonical_url, location)
        target = _canonical_target(joined, resource.source_kind)
        current = urllib.parse.urlsplit(resource.canonical_url)
        redirected = urllib.parse.urlsplit(target.canonical_url)
        if (
            current.scheme,
            current.hostname,
            current.port or 443,
        ) != (
            redirected.scheme,
            redirected.hostname,
            redirected.port or 443,
        ):
            raise NetworkResourceRegistryError(
                "NETWORK_REDIRECT_ORIGIN_BLOCKED",
                "network redirect attempted to leave the approved origin",
            )
        addresses = resolve_public_network_addresses(target.host, resolver=self._resolver)
        locator = _InMemoryLocator(
            target=_CanonicalTarget(
                canonical_url=target.canonical_url,
                approved_input=resource.approved_input,
                host=target.host,
                port=target.port,
                display_origin=target.display_origin,
                adapter=target.adapter,
                public_identity=target.public_identity,
                query_present=target.query_present,
                sensitive_query=target.sensitive_query,
            ),
            canonical_request_digest=self._request_digests(target)[0],
            query_redaction_digest=self._request_digests(target)[1],
        )
        record = {
            "grantId": resource.grant_id,
            "sourceKind": resource.source_kind,
            "adapter": resource.adapter,
            "displayOrigin": resource.display_origin,
            "resourceRevisionDigest": resource.resource_revision_digest,
            "revocationEpoch": resource.revocation_epoch,
        }
        return self._resolved(
            network_resource_ref=resource.network_resource_ref,
            record=record,
            locator=locator,
            target=target,
            addresses=addresses,
            constraints=resource.constraints,
            redirect_count=index,
        )

    def revoke(
        self,
        network_resource_ref: str,
        audience: ArtifactAudienceBinding,
        *,
        revocation_id: str,
        expected_revocation_epoch: int,
        attestation_ref: str,
    ) -> dict[str, Any]:
        revocation_id = _opaque_input(revocation_id, "revocationId")
        expected_epoch = _require_integer(
            expected_revocation_epoch, "expectedRevocationEpoch", minimum=0, maximum=1
        )
        audience_digest = self._audience_digest(audience)
        revocation_digest = self._mac(
            "study.network-resource.revocation-id.v1",
            audience_digest.encode("ascii") + b"\x00" + revocation_id.encode("utf-8"),
        )
        with self._transaction():
            normalized_ref, record, _ = self._resolve_record(
                network_resource_ref, audience
            )
            if record["revoked"]:
                if record["revokeDigest"] == revocation_digest:
                    return _public_summary(
                        record,
                        normalized_ref,
                        self._now(),
                        locator_available=False,
                    )
                raise NetworkResourceRegistryError(
                    "NETWORK_ALREADY_REVOKED", "network resource grant was already revoked"
                )
            if record["revocationEpoch"] != expected_epoch:
                raise NetworkResourceRegistryError(
                    "NETWORK_REVOCATION_CHANGED", "network revocation epoch changed"
                )
            request_digest = _sha(
                canonical_json_bytes(
                    {
                        "schema": "study.network-resource.revoke-request",
                        "schemaVersion": 1,
                        "grantId": record["grantId"],
                        "networkResourceRefDigest": _sha(normalized_ref.encode("ascii")),
                        "revocationDigest": revocation_digest,
                        "expectedRevocationEpoch": expected_epoch,
                    }
                )
            )
        revocation_attestation_digest = self._verify_gesture(
            audience_digest=audience_digest,
            request_digest=request_digest,
            attestation_ref=attestation_ref,
            action="revoke_network_resource",
        )
        with self._transaction():
            normalized_ref, current, previous_raw = self._resolve_record(
                network_resource_ref, audience
            )
            if current["revoked"]:
                if current["revokeDigest"] == revocation_digest:
                    return _public_summary(
                        current,
                        normalized_ref,
                        self._now(),
                        locator_available=False,
                    )
                raise NetworkResourceRegistryError(
                    "NETWORK_ALREADY_REVOKED", "network resource grant was already revoked"
                )
            if current["revocationEpoch"] != expected_epoch:
                raise NetworkResourceRegistryError(
                    "NETWORK_REVOCATION_CHANGED", "network revocation epoch changed"
                )
            now = self._now()
            unsigned = dict(current)
            unsigned.pop("authKeyId")
            unsigned.pop("authTag")
            unsigned.update(
                {
                    "revoked": True,
                    "revocationEpoch": current["revocationEpoch"] + 1,
                    "revokeDigest": revocation_digest,
                    "revokeAttestationDigest": revocation_attestation_digest,
                    "revokedAt": _timestamp(now),
                    "revision": current["revision"] + 1,
                }
            )
            updated = self._authenticate_record(unsigned)
            self._validate_record(updated)
            self._replace(
                self._record_path(current["grantId"]),
                canonical_json_bytes(updated),
                previous_raw,
            )
            self._locators.pop(current["grantId"], None)
            return _public_summary(
                updated,
                normalized_ref,
                now,
                locator_available=False,
            )


    def _assert_resolution_active(
        self,
        resource: ResolvedNetworkResource,
        audience: ArtifactAudienceBinding,
    ) -> None:
        self._verify_resolution(resource)
        with self._transaction():
            normalized_ref, record, _ = self._resolve_record(
                resource.network_resource_ref, audience
            )
            if (
                normalized_ref != resource.network_resource_ref
                or record["grantId"] != resource.grant_id
                or record["resourceRevisionDigest"] != resource.resource_revision_digest
            ):
                raise NetworkResourceRegistryError(
                    "NETWORK_RESOLUTION_INVALID", "network resolution no longer matches its grant"
                )
            if record["revocationEpoch"] != resource.revocation_epoch:
                raise NetworkResourceRegistryError(
                    "NETWORK_REVOCATION_CHANGED", "network revocation epoch changed"
                )
            state = _record_state(
                record,
                self._now(),
                locator_available=record["grantId"] in self._locators,
            )
            if state == "revoked":
                raise NetworkResourceRegistryError(
                    "NETWORK_RESOURCE_REVOKED", "network resource grant has been revoked"
                )
            if state == "expired":
                self._locators.pop(record["grantId"], None)
                raise NetworkResourceRegistryError(
                    "NETWORK_RESOURCE_EXPIRED", "network resource grant has expired"
                )
            if state == "reauthorization_required":
                raise NetworkResourceRegistryError(
                    "NETWORK_REAUTHORIZATION_REQUIRED",
                    "network URL must be re-entered through the trusted local surface",
                )

    def fetch(
        self,
        resource: ResolvedNetworkResource,
        audience: ArtifactAudienceBinding,
        *,
        maximum_bytes: int | None = None,
        timeout_seconds: int | None = None,
        fetcher: PinnedNetworkFetcher | None = None,
    ) -> NetworkFetchResponse:
        self._assert_resolution_active(resource, audience)
        transport = fetcher or PinnedNetworkFetcher()
        if not isinstance(transport, PinnedNetworkFetcher):
            raise NetworkResourceRegistryError(
                "NETWORK_FETCHER_INVALID", "trusted pinned network fetcher is required"
            )
        return transport.fetch(
            resource,
            maximum_bytes=maximum_bytes,
            timeout_seconds=timeout_seconds,
        )
