from __future__ import annotations

import hashlib
import json
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from card_service.artifact_registry import ArtifactAudienceBinding
from card_service.network_resource_registry import (
    NetworkResourceGrantRegistry,
    NetworkResourceRegistryError,
    PinnedNetworkFetcher,
)


AUTH_KEY = b"network-resource-registry-test-key-32"
OWNER = hashlib.sha256(b"network-resource-owner").hexdigest()
PUBLIC_V4 = "93.184.216.34"
PUBLIC_V6 = "2606:2800:220:1:248:1893:25c8:1946"
VIDEO_ID = "dQw4w9WgXcQ"


def audience(
    *,
    owner: str = OWNER,
    host: str = "codex-desktop",
    plugin: str = "speakright.study",
    session: str = "network-session",
) -> ArtifactAudienceBinding:
    return ArtifactAudienceBinding(
        owner_digest=owner,
        host_id=host,
        plugin_id=plugin,
        session_id=session,
    )


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 7, 18, 10, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


class Gestures:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str]] = []

    def __call__(self, audience_digest: str, request_digest: str, attestation: str, action: str) -> bool:
        self.calls.append((audience_digest, request_digest, attestation, action))
        return attestation == "trusted-gesture"


class Resolver:
    def __init__(self, *addresses: str) -> None:
        self.addresses = list(addresses or (PUBLIC_V4,))
        self.calls: list[str] = []

    def __call__(self, host: str, _port: int, **_kwargs):
        self.calls.append(host)
        records = []
        for address in self.addresses:
            family = socket.AF_INET6 if ":" in address else socket.AF_INET
            endpoint = (address, 443, 0, 0) if family == socket.AF_INET6 else (address, 443)
            records.append((family, socket.SOCK_STREAM, 6, "", endpoint))
        return records


def constraints(**overrides):
    value = {
        "actions": ["fetch"],
        "methods": ["GET"],
        "maxResponseBytes": 1024 * 1024,
        "timeoutSeconds": 30,
        "redirectPolicy": "same_origin",
        "maxRedirects": 2,
    }
    value.update(overrides)
    return value


def make_registry(
    tmp_path: Path,
    *,
    gestures=None,
    resolver=None,
    clock=None,
    service_instance_id: str = "card-service-network",
) -> NetworkResourceGrantRegistry:
    return NetworkResourceGrantRegistry(
        (tmp_path / "registry").resolve(),
        authentication_key=AUTH_KEY,
        service_instance_id=service_instance_id,
        gesture_verifier=gestures,
        resolver=resolver or Resolver(),
        clock=clock or Clock(),
    )


def issue_web(
    registry: NetworkResourceGrantRegistry,
    raw_url: str,
    *,
    request_id: str = "network-grant-1",
    max_uses: int = 1,
    grant_constraints=None,
    bound_audience: ArtifactAudienceBinding | None = None,
):
    return registry.issue_grant(
        audience=bound_audience or audience(),
        grant_request_id=request_id,
        raw_url=raw_url,
        source_kind="web",
        attestation_ref="trusted-gesture",
        constraints=grant_constraints or constraints(),
        max_uses=max_uses,
    )


def consume(
    registry: NetworkResourceGrantRegistry,
    summary,
    *,
    use_id: str = "network-use-1",
    requested_constraints=None,
    bound_audience: ArtifactAudienceBinding | None = None,
):
    return registry.consume(
        summary["networkResourceRef"],
        bound_audience or audience(),
        use_id=use_id,
        expected_resource_revision_digest=summary["resourceRevisionDigest"],
        expected_revocation_epoch=0,
        requested_constraints=requested_constraints,
    )


def test_signed_url_is_memory_only_and_public_summary_is_redacted(tmp_path: Path) -> None:
    gestures = Gestures()
    registry = make_registry(tmp_path, gestures=gestures)
    raw = (
        "https://media.example/private/episode.mp3?"
        "X-Amz-Credential=AKIA-CANARY&X-Amz-Signature=secret-query-canary"
    )
    summary = issue_web(registry, raw)
    public = json.dumps(summary, ensure_ascii=False)
    persisted = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / "registry").rglob("*.json")
    )
    assert summary["displayOrigin"] == "https://media.example"
    assert summary["queryPresent"] is True
    assert summary["sensitiveQuery"] is True
    assert "/private/episode.mp3" not in public
    assert "secret-query-canary" not in public
    assert raw not in persisted
    assert "/private/episode.mp3" not in persisted
    assert "secret-query-canary" not in persisted
    assert summary["networkResourceRef"] not in persisted
    assert "network-grant-1" not in persisted
    assert "trusted-gesture" not in persisted
    assert gestures.calls[-1][3] == "approve_network_resource"

    resolved = consume(registry, summary)
    assert resolved.canonical_url == raw
    assert resolved.addresses == (PUBLIC_V4,)
    binding = resolved.legacy_binding(
        json_pointer="#/source_url",
        raw_project_value=raw,
    )
    assert binding.canonical_request_digest == resolved.canonical_request_digest
    assert binding.query_redaction_digest == resolved.query_redaction_digest
    assert binding.display_origin == "https://media.example"


def test_youtube_is_reduced_to_public_video_identity_without_tracking_query(tmp_path: Path) -> None:
    registry = make_registry(tmp_path, gestures=Gestures())
    raw = f"https://youtu.be/{VIDEO_ID}?si=tracking-canary"
    summary = registry.issue_grant(
        audience=audience(),
        grant_request_id="youtube-grant",
        raw_url=raw,
        source_kind="public_video",
        attestation_ref="trusted-gesture",
    )
    assert summary["adapter"] == "youtube"
    assert summary["publicIdentity"] == VIDEO_ID
    assert summary["sensitiveQuery"] is False
    resolved = consume(registry, summary)
    assert resolved.canonical_url == f"https://www.youtube.com/watch?v={VIDEO_ID}"
    persisted = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / "registry").rglob("*.json")
    )
    assert "tracking-canary" not in persisted


@pytest.mark.parametrize(
    "raw_url",
    [
        "http://example.com/source",
        "https://user:pass@example.com/source",
        "https://example.com:444/source",
        "https://example.com/source#fragment",
        "https://localhost/source",
        "https://metadata.google.internal/computeMetadata/v1/",
        "https://example.com/a/../secret",
        "https://example.com/a/%2e%2e/secret",
        "https://example.com/a\\b",
        "https://example.com/%ZZ",
        "https://example.com/white space",
    ],
)
def test_unsafe_url_shapes_fail_before_persistence(tmp_path: Path, raw_url: str) -> None:
    registry = make_registry(tmp_path, gestures=Gestures())
    with pytest.raises(NetworkResourceRegistryError):
        issue_web(registry, raw_url)
    assert not list((tmp_path / "registry" / "records").rglob("*.json"))


@pytest.mark.parametrize(
    "addresses",
    [
        ("127.0.0.1",),
        ("10.0.0.10",),
        ("169.254.169.254",),
        ("::1",),
        (PUBLIC_V4, "127.0.0.1"),
    ],
)
def test_any_non_public_dns_answer_blocks_the_grant(tmp_path: Path, addresses: tuple[str, ...]) -> None:
    registry = make_registry(
        tmp_path,
        gestures=Gestures(),
        resolver=Resolver(*addresses),
    )
    with pytest.raises(NetworkResourceRegistryError) as blocked:
        issue_web(registry, "https://example.com/source")
    assert blocked.value.code == "NETWORK_DNS_PRIVATE_BLOCKED"
    assert not list((tmp_path / "registry" / "records").rglob("*.json"))


def test_dns_is_rechecked_at_consumption_and_rebinding_fails_closed(tmp_path: Path) -> None:
    resolver = Resolver(PUBLIC_V4)
    registry = make_registry(tmp_path, gestures=Gestures(), resolver=resolver)
    summary = issue_web(registry, "https://example.com/source")
    resolver.addresses = ["127.0.0.1"]
    with pytest.raises(NetworkResourceRegistryError) as rebound:
        consume(registry, summary)
    assert rebound.value.code == "NETWORK_DNS_PRIVATE_BLOCKED"


@pytest.mark.parametrize(
    "other",
    [
        audience(owner=hashlib.sha256(b"other-owner").hexdigest()),
        audience(host="other-host"),
        audience(plugin="other-plugin"),
        audience(session="other-session"),
    ],
)
def test_network_ref_cannot_cross_audience_boundaries(
    tmp_path: Path,
    other: ArtifactAudienceBinding,
) -> None:
    registry = make_registry(tmp_path, gestures=Gestures())
    summary = issue_web(registry, "https://example.com/source")
    with pytest.raises(NetworkResourceRegistryError) as mismatch:
        registry.inspect(summary["networkResourceRef"], other)
    assert mismatch.value.code == "NETWORK_AUDIENCE_MISMATCH"


def test_service_instance_and_process_memory_are_both_required(tmp_path: Path) -> None:
    registry = make_registry(tmp_path, gestures=Gestures())
    summary = issue_web(registry, "https://example.com/source")
    other_service = make_registry(
        tmp_path,
        gestures=Gestures(),
        service_instance_id="different-service",
    )
    with pytest.raises(NetworkResourceRegistryError) as mismatch:
        other_service.inspect(summary["networkResourceRef"], audience())
    assert mismatch.value.code == "NETWORK_AUDIENCE_MISMATCH"

    restarted = make_registry(tmp_path, gestures=Gestures())
    state = restarted.inspect(summary["networkResourceRef"], audience())
    assert state["state"] == "reauthorization_required"
    with pytest.raises(NetworkResourceRegistryError) as unavailable:
        consume(restarted, summary)
    assert unavailable.value.code == "NETWORK_REAUTHORIZATION_REQUIRED"
    with pytest.raises(NetworkResourceRegistryError) as replay:
        issue_web(restarted, "https://example.com/source")
    assert replay.value.code == "NETWORK_REAUTHORIZATION_REQUIRED"


def test_gesture_verification_is_fail_closed(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    with pytest.raises(NetworkResourceRegistryError) as missing:
        issue_web(registry, "https://example.com/source")
    assert missing.value.code == "NETWORK_GESTURE_REQUIRED"
    assert not list((tmp_path / "registry" / "records").rglob("*.json"))

    denied = make_registry(tmp_path / "denied", gestures=lambda *_: False)
    with pytest.raises(NetworkResourceRegistryError) as rejected:
        issue_web(denied, "https://example.com/source")
    assert rejected.value.code == "NETWORK_GESTURE_REQUIRED"


def test_issue_and_use_are_idempotent_but_scope_changes_conflict(tmp_path: Path) -> None:
    gestures = Gestures()
    registry = make_registry(tmp_path, gestures=gestures)
    summary = issue_web(registry, "https://example.com/source", max_uses=1)
    assert issue_web(registry, "https://example.com/source", max_uses=1) == summary
    assert len(gestures.calls) == 1
    with pytest.raises(NetworkResourceRegistryError) as conflict:
        issue_web(
            registry,
            "https://example.com/other",
            max_uses=1,
        )
    assert conflict.value.code == "NETWORK_IDEMPOTENCY_CONFLICT"

    first = consume(registry, summary, use_id="same-use")
    replay = consume(registry, summary, use_id="same-use")
    assert replay.resolution_proof == first.resolution_proof
    with pytest.raises(NetworkResourceRegistryError) as exhausted:
        consume(registry, summary, use_id="other-use")
    assert exhausted.value.code == "NETWORK_USES_EXHAUSTED"


def test_constraints_can_only_be_reduced(tmp_path: Path) -> None:
    registry = make_registry(tmp_path, gestures=Gestures())
    summary = issue_web(
        registry,
        "https://example.com/source",
        max_uses=2,
        grant_constraints=constraints(maxResponseBytes=4096, timeoutSeconds=20),
    )
    narrowed = constraints(
        maxResponseBytes=1024,
        timeoutSeconds=10,
        redirectPolicy="none",
        maxRedirects=0,
    )
    resolved = consume(
        registry,
        summary,
        use_id="narrow-use",
        requested_constraints=narrowed,
    )
    assert resolved.constraints == narrowed
    with pytest.raises(NetworkResourceRegistryError) as widened:
        consume(
            registry,
            summary,
            use_id="wide-use",
            requested_constraints=constraints(maxResponseBytes=8192, timeoutSeconds=20),
        )
    assert widened.value.code in {
        "NETWORK_SCHEMA_INVALID",
        "NETWORK_CONSTRAINT_FORBIDDEN",
    }


def test_redirects_are_ordered_same_origin_public_and_bounded(tmp_path: Path) -> None:
    resolver = Resolver(PUBLIC_V4)
    registry = make_registry(tmp_path, gestures=Gestures(), resolver=resolver)
    summary = issue_web(
        registry,
        "https://example.com/start?token=memory-only",
        grant_constraints=constraints(maxRedirects=2),
    )
    resolved = consume(registry, summary)
    redirected = registry.authorize_redirect(
        resolved,
        audience(),
        location="/next?signature=redirect-secret",
        redirect_index=1,
    )
    assert redirected.canonical_url == "https://example.com/next?signature=redirect-secret"
    assert redirected.redirect_count == 1
    with pytest.raises(NetworkResourceRegistryError) as cross_origin:
        registry.authorize_redirect(
            redirected,
            audience(),
            location="https://evil.example/next",
            redirect_index=2,
        )
    assert cross_origin.value.code == "NETWORK_REDIRECT_ORIGIN_BLOCKED"
    with pytest.raises(NetworkResourceRegistryError) as order:
        registry.authorize_redirect(
            redirected,
            audience(),
            location="/later",
            redirect_index=3,
        )
    assert order.value.code == "NETWORK_REDIRECT_ORDER_INVALID"

    second = registry.authorize_redirect(
        redirected,
        audience(),
        location="/final",
        redirect_index=2,
    )
    with pytest.raises(NetworkResourceRegistryError) as limit:
        registry.authorize_redirect(
            second,
            audience(),
            location="/too-far",
            redirect_index=3,
        )
    assert limit.value.code == "NETWORK_REDIRECT_BLOCKED"


def test_redirect_dns_rebinding_and_youtube_redirects_fail_closed(tmp_path: Path) -> None:
    resolver = Resolver(PUBLIC_V4)
    registry = make_registry(tmp_path, gestures=Gestures(), resolver=resolver)
    summary = issue_web(registry, "https://example.com/start")
    resolved = consume(registry, summary)
    resolver.addresses = ["127.0.0.1"]
    with pytest.raises(NetworkResourceRegistryError) as rebound:
        registry.authorize_redirect(
            resolved,
            audience(),
            location="/next",
            redirect_index=1,
        )
    assert rebound.value.code == "NETWORK_DNS_PRIVATE_BLOCKED"

    youtube_registry = make_registry(tmp_path / "youtube", gestures=Gestures())
    youtube = youtube_registry.issue_grant(
        audience=audience(),
        grant_request_id="youtube-no-redirect",
        raw_url=f"https://www.youtube.com/watch?v={VIDEO_ID}",
        source_kind="public_video",
        attestation_ref="trusted-gesture",
    )
    youtube_resolved = consume(youtube_registry, youtube)
    with pytest.raises(NetworkResourceRegistryError) as blocked:
        youtube_registry.authorize_redirect(
            youtube_resolved,
            audience(),
            location="/another",
            redirect_index=1,
        )
    assert blocked.value.code == "NETWORK_REDIRECT_BLOCKED"


class FakeResponse:
    def __init__(self, *, status=200, body=b"payload", headers=None) -> None:
        self.status = status
        self._body = body
        self._headers = list(
            (headers or {
                "Content-Type": "text/plain",
                "Set-Cookie": "secret-cookie",
                "Location": "/redirect?token=secret",
            }).items()
        )

    def getheader(self, name: str):
        for key, value in self._headers:
            if key.casefold() == name.casefold():
                return value
        return None

    def getheaders(self):
        return list(self._headers)

    def read(self, amount: int):
        return self._body[:amount]


class FakeConnection:
    instances = []
    response = FakeResponse()

    def __init__(self, host, address, *, timeout, context) -> None:
        self.host = host
        self.address = address
        self.timeout = timeout
        self.context = context
        self.request_data = None
        self.__class__.instances.append(self)

    def request(self, method, target, headers) -> None:
        self.request_data = (method, target, dict(headers))

    def getresponse(self):
        return self.__class__.response

    def close(self) -> None:
        pass


def test_registry_fetch_uses_only_pinned_address_and_fixed_headers(tmp_path: Path) -> None:
    FakeConnection.instances = []
    registry = make_registry(tmp_path, gestures=Gestures())
    summary = issue_web(
        registry,
        "https://example.com/source?signature=memory-secret",
        grant_constraints=constraints(maxResponseBytes=64, timeoutSeconds=10),
        max_uses=2,
    )
    resolved = consume(registry, summary)
    fetcher = PinnedNetworkFetcher(connection_factory=FakeConnection)
    response = registry.fetch(
        resolved,
        audience(),
        maximum_bytes=32,
        timeout_seconds=5,
        fetcher=fetcher,
    )
    connection = FakeConnection.instances[-1]
    assert connection.address == PUBLIC_V4
    assert connection.request_data[0] == "GET"
    assert connection.request_data[1] == "/source?signature=memory-secret"
    sent_headers = {key.casefold() for key in connection.request_data[2]}
    assert "authorization" not in sent_headers
    assert "cookie" not in sent_headers
    assert "proxy-authorization" not in sent_headers
    assert response.headers == {"content-type": "text/plain"}
    assert response.redirect_location == "/redirect?token=secret"
    assert "set-cookie" not in response.headers

    registry.revoke(
        summary["networkResourceRef"],
        audience(),
        revocation_id="revoke-after-resolve",
        expected_revocation_epoch=0,
        attestation_ref="trusted-gesture",
    )
    with pytest.raises(NetworkResourceRegistryError) as revoked:
        registry.fetch(resolved, audience(), fetcher=fetcher)
    assert revoked.value.code == "NETWORK_REVOCATION_CHANGED"
    assert len(FakeConnection.instances) == 1


def test_response_byte_limit_is_enforced(tmp_path: Path) -> None:
    FakeConnection.instances = []
    FakeConnection.response = FakeResponse(
        body=b"x" * 65,
        headers={"Content-Length": "65"},
    )
    registry = make_registry(tmp_path, gestures=Gestures())
    summary = issue_web(
        registry,
        "https://example.com/source",
        grant_constraints=constraints(maxResponseBytes=64),
    )
    resolved = consume(registry, summary)
    with pytest.raises(NetworkResourceRegistryError) as oversized:
        registry.fetch(
            resolved,
            audience(),
            fetcher=PinnedNetworkFetcher(connection_factory=FakeConnection),
        )
    assert oversized.value.code == "NETWORK_RESPONSE_LIMIT"
    FakeConnection.response = FakeResponse()


def test_revoke_expiry_and_record_tamper_fail_closed(tmp_path: Path) -> None:
    clock = Clock()
    gestures = Gestures()
    registry = make_registry(tmp_path, gestures=gestures, clock=clock)
    summary = issue_web(registry, "https://example.com/source", max_uses=2)
    revoked = registry.revoke(
        summary["networkResourceRef"],
        audience(),
        revocation_id="network-revoke",
        expected_revocation_epoch=0,
        attestation_ref="trusted-gesture",
    )
    assert revoked["state"] == "revoked"
    assert gestures.calls[-1][3] == "revoke_network_resource"
    assert registry.revoke(
        summary["networkResourceRef"],
        audience(),
        revocation_id="network-revoke",
        expected_revocation_epoch=0,
        attestation_ref="not-needed-on-replay",
    ) == revoked

    expiring = make_registry(tmp_path / "expiry", gestures=Gestures(), clock=clock)
    short = expiring.issue_grant(
        audience=audience(),
        grant_request_id="short-network",
        raw_url="https://example.com/short",
        source_kind="web",
        attestation_ref="trusted-gesture",
        constraints=constraints(),
        expires_at=clock.value + timedelta(seconds=1),
    )
    clock.advance(seconds=2)
    assert expiring.inspect(short["networkResourceRef"], audience())["state"] == "expired"
    with pytest.raises(NetworkResourceRegistryError) as expired:
        consume(expiring, short)
    assert expired.value.code == "NETWORK_RESOURCE_EXPIRED"

    tampered = make_registry(tmp_path / "tamper", gestures=Gestures())
    tampered_summary = issue_web(tampered, "https://example.com/source")
    record = next((tmp_path / "tamper" / "registry" / "records").rglob("*.json"))
    value = json.loads(record.read_text(encoding="utf-8"))
    value["maxUses"] = 100
    record.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")
    with pytest.raises(NetworkResourceRegistryError) as corrupt:
        tampered.inspect(tampered_summary["networkResourceRef"], audience())
    assert corrupt.value.code == "NETWORK_RECORD_CORRUPT"


def test_public_ipv6_literal_is_canonical_but_private_ipv6_is_blocked(tmp_path: Path) -> None:
    public = make_registry(
        tmp_path / "public",
        gestures=Gestures(),
        resolver=Resolver(PUBLIC_V6),
    )
    summary = issue_web(public, f"https://[{PUBLIC_V6}]/source")
    assert summary["displayOrigin"] == f"https://[{PUBLIC_V6}]"
    assert consume(public, summary).addresses == (PUBLIC_V6,)

    private = make_registry(
        tmp_path / "private",
        gestures=Gestures(),
        resolver=Resolver("::1"),
    )
    with pytest.raises(NetworkResourceRegistryError) as blocked:
        issue_web(private, "https://[::1]/source")
    assert blocked.value.code in {"NETWORK_HOST_BLOCKED", "NETWORK_DNS_PRIVATE_BLOCKED"}
