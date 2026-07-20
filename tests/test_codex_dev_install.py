from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from card_service.development_runtime import (
    APP_FOLDER,
    INSTALL_IDENTITY_NAME,
    MANIFEST_NAME,
    PLUGIN_FOLDER,
    PLUGIN_SNAPSHOT_MANIFEST_NAME,
    RUNTIME_FOLDER,
    STATE_FOLDER,
    DevelopmentPluginSnapshot,
    DevelopmentRuntimeError,
    DevelopmentRuntimeSnapshot,
    _trusted_owner,
    build_development_plugin_snapshot,
    build_development_runtime,
    read_install_identity,
    verify_development_runtime,
    verify_development_plugin_snapshot,
    verify_readonly_dependency_root,
)
from card_service.mcp_stdio import MCP_PROTOCOL_VERSION
from card_service.trusted_mcp_audience import create_development_mcp_audience
from card_service.windows_sandbox_acl import (
    FILE_FULL_CONTROL,
    SE_DACL_PROTECTED,
    TRUSTED_INSTALLER_SID,
    apply_exact_dacl,
    current_user_sid,
    read_dacl,
    read_security_descriptor_identity,
    service_root_grants,
)
from scripts.install_codex_study_plugin_dev import (
    MCP_NAME,
    PLUGIN_SELECTOR,
    CommandResult,
    DevelopmentInstallError,
    _owned_mcp_details,
    install_or_upgrade,
    parse_marketplace_roots,
    register_development_mcp,
    uninstall,
    verify_codex_version,
)
from scripts.run_codex_study_mcp_dev import development_service_arguments


ROOT = Path(__file__).resolve().parents[1]
SOURCE_LAUNCHER = ROOT / "scripts" / "run_codex_study_mcp_dev.py"


def test_only_exact_trusted_installer_service_sid_is_a_trusted_owner() -> None:
    current = "S-1-5-21-1-2-3-1001"

    assert _trusted_owner(TRUSTED_INSTALLER_SID, current) is True
    assert _trusted_owner("S-1-5-80-111-222-333-444-555", current) is False


@pytest.fixture
def secure_profile() -> Path:
    root = Path(tempfile.mkdtemp(prefix="anki-dev-profile-", dir=Path.home()))
    apply_exact_dacl(root, service_root_grants(), inherit_to_children=True)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


@pytest.fixture(scope="module")
def real_secure_snapshot() -> tuple[Path, DevelopmentRuntimeSnapshot]:
    profile = Path(tempfile.mkdtemp(prefix="anki-dev-real-", dir=Path.home()))
    apply_exact_dacl(profile, service_root_grants(), inherit_to_children=True)
    snapshot = build_development_runtime(
        repository_root=ROOT,
        launcher_source=SOURCE_LAUNCHER,
        python_executable=Path(sys.executable),
        user_profile=profile,
        include_tools=False,
    )
    try:
        yield profile, snapshot
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def _minimal_repository(root: Path) -> tuple[Path, Path]:
    repository = root / "repo"
    (repository / "card_service").mkdir(parents=True)
    (repository / "workers").mkdir()
    (repository / "card_service" / "module.py").write_text(
        "VALUE = 1\n", encoding="utf-8"
    )
    (repository / "workers" / "anki_worker.py").write_text(
        "VALUE = 2\n", encoding="utf-8"
    )
    launcher = repository / "bootstrap.py"
    launcher.write_text("print('fixture')\n", encoding="utf-8")
    return repository, launcher


def _minimal_snapshot(profile: Path) -> DevelopmentRuntimeSnapshot:
    repository, launcher = _minimal_repository(profile / "sources")
    return build_development_runtime(
        repository_root=repository,
        launcher_source=launcher,
        python_executable=Path(sys.executable),
        user_profile=profile,
        include_tools=False,
    )


def _mcp_result(
    snapshot: DevelopmentRuntimeSnapshot, *, port: str = "8765", extra=()
) -> CommandResult:
    return CommandResult(
        0,
        json.dumps(
            {
                "transport": {
                    "type": "stdio",
                    "command": str(Path(sys.executable).resolve()),
                    "args": [
                        "-I",
                        "-S",
                        "-B",
                        str(snapshot.launcher),
                        "--anki-connect-port",
                        port,
                        *extra,
                    ],
                    "env": None,
                    "cwd": None,
                }
            }
        ),
        "",
    )


def test_marketplace_listing_parser_uses_codex_json_and_extended_paths() -> None:
    parsed = parse_marketplace_roots(
        json.dumps(
            {
                "marketplaces": [
                    {"name": "anki-study-agent-local", "root": "\\\\?\\E:\\ANKI"}
                ]
            }
        )
    )
    assert parsed == {"anki-study-agent-local": Path("E:/ANKI").resolve()}


def test_source_launcher_refuses_to_run_outside_an_installed_snapshot() -> None:
    completed = subprocess.run(
        [sys.executable, "-I", "-S", "-B", str(SOURCE_LAUNCHER)],
        cwd=Path.home(),
        input="",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert completed.returncode != 0
    assert "private installed runtime snapshot" in completed.stderr


def test_private_snapshot_is_content_addressed_exact_and_protected(
    secure_profile: Path,
) -> None:
    snapshot = _minimal_snapshot(secure_profile)
    payload = verify_development_runtime(
        snapshot.root, expected_python=Path(sys.executable), verify_acl=True
    )
    manifest = (snapshot.root / MANIFEST_NAME).read_bytes()
    assert snapshot.root.name == snapshot.manifest_sha256
    assert payload["cardServiceProtocolVersion"] == 1
    assert {item["role"] for item in payload["resources"]} >= {
        "development-launcher",
        "card-service-module",
        "worker-entry",
    }
    assert manifest == json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    for path in [snapshot.root, *snapshot.root.rglob("*")]:
        identity = read_security_descriptor_identity(path)
        assert identity.control & SE_DACL_PROTECTED
        assert identity.owner_sid in {
            current_user_sid(),
            "S-1-5-18",
            "S-1-5-32-544",
        }
        assert {entry.sid for entry in read_dacl(path)} == {
            current_user_sid(),
            "S-1-5-18",
            "S-1-5-32-544",
        }


def test_snapshot_tampering_and_extra_files_fail_closed(secure_profile: Path) -> None:
    snapshot = _minimal_snapshot(secure_profile)
    target = snapshot.root / "card_service" / "module.py"
    original = target.read_bytes()
    target.write_bytes(original + b"# tampered\n")
    with pytest.raises(DevelopmentRuntimeError, match="integrity"):
        verify_development_runtime(snapshot.root, expected_python=Path(sys.executable))
    target.write_bytes(original)
    (snapshot.root / "unexpected.txt").write_text("unexpected", encoding="utf-8")
    apply_exact_dacl(
        snapshot.root / "unexpected.txt",
        service_root_grants(),
        inherit_to_children=False,
    )
    with pytest.raises(DevelopmentRuntimeError, match="unexpected or missing"):
        verify_development_runtime(snapshot.root, expected_python=Path(sys.executable))


def test_snapshot_acl_widening_fails_closed(secure_profile: Path) -> None:
    snapshot = _minimal_snapshot(secure_profile)
    users_sid = "S-1-5-32-545"
    apply_exact_dacl(
        snapshot.launcher,
        (*service_root_grants(), (users_sid, FILE_FULL_CONTROL)),
        inherit_to_children=False,
    )
    with pytest.raises(DevelopmentRuntimeError, match="DACL"):
        verify_development_runtime(snapshot.root, expected_python=Path(sys.executable))


def test_private_root_rejects_parent_delete_child_permission() -> None:
    parent = Path(tempfile.mkdtemp(prefix="anki-dev-parent-", dir=Path.home()))
    profile = parent / "profile"
    profile.mkdir()
    apply_exact_dacl(profile, service_root_grants(), inherit_to_children=True)
    apply_exact_dacl(
        parent,
        (*service_root_grants(), ("S-1-5-32-545", 0x00000040)),
        inherit_to_children=True,
    )
    try:
        with pytest.raises(DevelopmentRuntimeError, match="mutable"):
            _minimal_snapshot(profile)
    finally:
        apply_exact_dacl(parent, service_root_grants(), inherit_to_children=True)
        shutil.rmtree(parent, ignore_errors=True)


def test_python_dependency_explicit_writable_file_is_rejected() -> None:
    root = Path(tempfile.mkdtemp(prefix="anki-dev-python-", dir=Path.home()))
    apply_exact_dacl(root, service_root_grants(), inherit_to_children=True)
    dependency = root / "dependency.py"
    dependency.write_text("VALUE = 1\n", encoding="utf-8")
    apply_exact_dacl(
        dependency,
        (*service_root_grants(), ("S-1-5-32-545", FILE_FULL_CONTROL)),
        inherit_to_children=False,
    )
    try:
        with pytest.raises(DevelopmentRuntimeError, match="mutable"):
            verify_readonly_dependency_root(root, required_paths=[dependency])
    finally:
        apply_exact_dacl(root, service_root_grants(), inherit_to_children=True)
        shutil.rmtree(root, ignore_errors=True)


def test_private_plugin_snapshot_is_content_addressed_passive_and_protected(
    secure_profile: Path,
) -> None:
    snapshot = build_development_plugin_snapshot(
        repository_root=ROOT, user_profile=secure_profile
    )
    payload = verify_development_plugin_snapshot(snapshot.root, verify_acl=True)
    assert snapshot.root.parent == secure_profile / APP_FOLDER / PLUGIN_FOLDER
    assert snapshot.root.name == snapshot.manifest_sha256
    assert payload["pluginVersion"] == snapshot.version
    assert snapshot.plugin_root == snapshot.root / "plugins" / "anki-study-agent"
    assert not (snapshot.plugin_root / ".mcp.json").exists()
    assert not (snapshot.plugin_root / ".app.json").exists()
    assert (snapshot.root / PLUGIN_SNAPSHOT_MANIFEST_NAME).is_file()
    source_skill = (
        ROOT
        / "plugins"
        / "anki-study-agent"
        / "skills"
        / "anki-study-agent"
        / "SKILL.md"
    )
    copied_skill = snapshot.plugin_root / "skills" / "anki-study-agent" / "SKILL.md"
    assert copied_skill.read_bytes() == source_skill.read_bytes()


def test_private_plugin_snapshot_tamper_and_extra_files_fail_closed(
    secure_profile: Path,
) -> None:
    snapshot = build_development_plugin_snapshot(
        repository_root=ROOT, user_profile=secure_profile
    )
    skill = snapshot.plugin_root / "skills" / "anki-study-agent" / "SKILL.md"
    original = skill.read_bytes()
    skill.write_bytes(original + b"\n# tampered\n")
    with pytest.raises(DevelopmentRuntimeError, match="integrity"):
        verify_development_plugin_snapshot(snapshot.root)
    skill.write_bytes(original)
    extra = snapshot.plugin_root / "unexpected.txt"
    extra.write_text("unexpected", encoding="utf-8")
    apply_exact_dacl(extra, service_root_grants(), inherit_to_children=False)
    with pytest.raises(DevelopmentRuntimeError, match="unexpected or missing"):
        verify_development_plugin_snapshot(snapshot.root)


def test_source_byte_change_creates_a_new_digest(secure_profile: Path) -> None:
    repository, launcher = _minimal_repository(secure_profile / "sources")
    first = build_development_runtime(
        repository_root=repository,
        launcher_source=launcher,
        python_executable=Path(sys.executable),
        user_profile=secure_profile,
        include_tools=False,
    )
    module = repository / "card_service" / "module.py"
    module.write_text("VALUE = 99\n", encoding="utf-8")
    second = build_development_runtime(
        repository_root=repository,
        launcher_source=launcher,
        python_executable=Path(sys.executable),
        user_profile=secure_profile,
        include_tools=False,
    )
    assert first.manifest_sha256 != second.manifest_sha256


def test_hardlinked_source_is_rejected(secure_profile: Path) -> None:
    repository, launcher = _minimal_repository(secure_profile / "sources")
    os.link(
        repository / "card_service" / "module.py",
        repository / "card_service" / "module-copy.py",
    )
    with pytest.raises(DevelopmentRuntimeError, match="hard-linked"):
        build_development_runtime(
            repository_root=repository,
            launcher_source=launcher,
            python_executable=Path(sys.executable),
            user_profile=secure_profile,
            include_tools=False,
        )


def test_install_identity_keeps_host_scope_stable_but_sessions_rotate(
    secure_profile: Path,
) -> None:
    snapshot = _minimal_snapshot(secure_profile)
    identity = read_install_identity(snapshot.state_root)
    first = create_development_mcp_audience(installation_identity=identity).audience
    second = create_development_mcp_audience(installation_identity=identity).audience
    other = create_development_mcp_audience(installation_identity="f" * 64).audience
    assert first.host_id == second.host_id
    assert first.session_id != second.session_id
    assert first.host_id != other.host_id
    assert (snapshot.state_root / INSTALL_IDENTITY_NAME).is_file()


def test_installed_launcher_serves_the_real_trusted_mcp(
    real_secure_snapshot: tuple[Path, DevelopmentRuntimeSnapshot],
) -> None:
    profile, snapshot = real_secure_snapshot
    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "pytest-private-launcher", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "system.get_capabilities", "arguments": {}},
        },
    ]
    environment = dict(os.environ)
    environment["USERPROFILE"] = str(profile)
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            str(snapshot.launcher),
            "--anki-connect-port",
            "8785",
        ],
        cwd=profile,
        env=environment,
        input="".join(json.dumps(request) + "\n" for request in requests),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        timeout=90,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    responses = [json.loads(line) for line in completed.stdout.splitlines()]
    assert [response["id"] for response in responses] == [1, 2, 3]
    assert len(responses[1]["result"]["tools"]) == 38
    bridge = responses[2]["result"]["structuredContent"]["mcpBridge"]
    assert bridge["audienceBinding"]["available"] is True
    assert bridge["audienceBinding"]["mode"] == "development_explicit"


def test_development_service_arguments_never_fall_back_to_worktree(
    real_secure_snapshot: tuple[Path, DevelopmentRuntimeSnapshot],
) -> None:
    profile, snapshot = real_secure_snapshot
    arguments = development_service_arguments(
        runtime_root=snapshot.root,
        python_executable=sys.executable,
        anki_connect_port=8785,
        environment={"USERPROFILE": str(profile)},
    )
    assert arguments[arguments.index("--worker") + 1] == str(
        snapshot.root / "workers" / "anki_worker.py"
    )
    assert arguments[arguments.index("--state-dir") + 1] == str(
        profile / APP_FOLDER / STATE_FOLDER
    )
    assert str(ROOT) not in "\n".join(arguments)


@pytest.mark.parametrize(
    ("port", "extra"),
    [("0", ()), ("08765", ()), ("8765", ("--extra",))],
)
def test_mcp_ownership_requires_exact_arguments(
    real_secure_snapshot: tuple[Path, DevelopmentRuntimeSnapshot],
    port: str,
    extra: tuple[str, ...],
) -> None:
    profile, snapshot = real_secure_snapshot
    assert (
        _owned_mcp_details(
            _mcp_result(snapshot, port=port, extra=extra),
            python=Path(sys.executable),
            user_profile=profile,
        )
        is None
    )


def test_mcp_ownership_accepts_only_a_verified_private_snapshot(
    real_secure_snapshot: tuple[Path, DevelopmentRuntimeSnapshot],
) -> None:
    profile, snapshot = real_secure_snapshot
    assert _owned_mcp_details(
        _mcp_result(snapshot), python=Path(sys.executable), user_profile=profile
    ) == (snapshot.launcher, 8765)


def test_mcp_ownership_can_replace_a_snapshot_polluted_only_by_bytecode_cache(
    secure_profile: Path,
) -> None:
    profile = secure_profile
    snapshot = _minimal_snapshot(profile)
    cache_dir = snapshot.root / "card_service" / "__pycache__"
    cache_dir.mkdir()
    (cache_dir / "trusted_surface_ui.cpython-313.pyc").write_bytes(b"old-cache")

    with pytest.raises(DevelopmentRuntimeError, match="unexpected or missing file"):
        verify_development_runtime(
            snapshot.root,
            expected_python=Path(sys.executable),
            verify_acl=True,
        )
    assert _owned_mcp_details(
        _mcp_result(snapshot), python=Path(sys.executable), user_profile=profile
    ) == (snapshot.launcher, 8765)


def test_mcp_ownership_rejects_other_unexpected_snapshot_files(
    secure_profile: Path,
) -> None:
    profile = secure_profile
    snapshot = _minimal_snapshot(profile)
    (snapshot.root / "unrelated.py").write_text("VALUE = 1\n", encoding="utf-8")

    assert (
        _owned_mcp_details(
            _mcp_result(snapshot),
            python=Path(sys.executable),
            user_profile=profile,
        )
        is None
    )


def test_registration_refuses_an_unrelated_existing_name(
    real_secure_snapshot: tuple[Path, DevelopmentRuntimeSnapshot],
) -> None:
    profile, snapshot = real_secure_snapshot
    calls: list[tuple[str, ...]] = []

    def runner(arguments):
        values = tuple(str(value) for value in arguments)
        calls.append(values)
        if values[1:4] == ("mcp", "get", MCP_NAME):
            return CommandResult(
                0,
                json.dumps(
                    {
                        "transport": {
                            "type": "stdio",
                            "command": "unrelated.exe",
                            "args": [],
                            "env": None,
                            "cwd": None,
                        }
                    }
                ),
                "",
            )
        return CommandResult(0, "{}", "")

    with pytest.raises(DevelopmentInstallError, match="unrelated MCP server"):
        register_development_mcp(
            codex="codex",
            python=Path(sys.executable),
            launcher=snapshot.launcher,
            user_profile=profile,
            anki_connect_port=8765,
            runner=runner,
        )
    assert not any(values[1:3] == ("mcp", "remove") for values in calls)


def test_registration_restores_an_owned_previous_snapshot_on_add_failure(
    real_secure_snapshot: tuple[Path, DevelopmentRuntimeSnapshot],
) -> None:
    profile, snapshot = real_secure_snapshot
    calls: list[tuple[str, ...]] = []
    add_attempts = 0
    existing = _mcp_result(snapshot, port="8765")

    def runner(arguments):
        nonlocal add_attempts
        values = tuple(str(value) for value in arguments)
        calls.append(values)
        if values[1:4] == ("mcp", "get", MCP_NAME):
            return existing
        if values[1:4] == ("mcp", "add", MCP_NAME):
            add_attempts += 1
            if add_attempts == 1:
                return CommandResult(1, "", "simulated add failure")
        return CommandResult(0, "{}", "")

    with pytest.raises(
        DevelopmentInstallError, match="previous registration was restored"
    ):
        register_development_mcp(
            codex="codex",
            python=Path(sys.executable),
            launcher=snapshot.launcher,
            user_profile=profile,
            anki_connect_port=8785,
            runner=runner,
        )
    assert add_attempts == 2
    assert calls[-1][-1] == "8765"


def test_development_install_rejects_old_codex_before_mutation() -> None:
    calls: list[tuple[str, ...]] = []

    def runner(arguments):
        values = tuple(str(value) for value in arguments)
        calls.append(values)
        return CommandResult(0, "codex-cli 0.143.9\n", "")

    with pytest.raises(DevelopmentInstallError, match="0.144.1 or newer"):
        verify_codex_version("codex", runner)
    assert calls == [("codex", "--version")]


def _fake_snapshot(profile: Path) -> DevelopmentRuntimeSnapshot:
    root = profile / APP_FOLDER / RUNTIME_FOLDER / ("a" * 64)
    return DevelopmentRuntimeSnapshot(
        root=root,
        launcher=root / "launcher.py",
        state_root=profile / APP_FOLDER / STATE_FOLDER,
        manifest_sha256="a" * 64,
        resource_count=3,
        tools=(),
        missing_tools=(),
    )


def _fake_plugin_snapshot(
    profile: Path, version: str, *, digest_character: str = "b"
) -> DevelopmentPluginSnapshot:
    root = profile / APP_FOLDER / PLUGIN_FOLDER / (digest_character * 64)
    return DevelopmentPluginSnapshot(
        root=root,
        plugin_root=root / "plugins" / "anki-study-agent",
        manifest_sha256=digest_character * 64,
        resource_count=6,
        version=version,
    )


def _patch_plugin_snapshot_ownership(
    monkeypatch: pytest.MonkeyPatch,
    *snapshots: DevelopmentPluginSnapshot,
) -> None:
    by_root = {snapshot.root.resolve(): snapshot for snapshot in snapshots}
    by_plugin = {snapshot.plugin_root.resolve(): snapshot for snapshot in snapshots}
    monkeypatch.setattr(
        "scripts.install_codex_study_plugin_dev._owned_marketplace_root",
        lambda root, *, user_profile: Path(root).resolve() in by_root,
    )

    def details(row, *, user_profile):
        if row is None:
            return None
        source = row.get("source")
        path = source.get("path") if isinstance(source, dict) else None
        if not isinstance(path, str):
            return None
        snapshot = by_plugin.get(Path(path).resolve())
        if snapshot is None or row.get("version") != snapshot.version:
            return None
        return snapshot.root, snapshot.plugin_root, snapshot.version

    monkeypatch.setattr(
        "scripts.install_codex_study_plugin_dev._owned_plugin_details", details
    )


def test_install_rolls_back_new_mcp_and_marketplace_when_plugin_add_fails(
    secure_profile: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin_snapshot = _fake_plugin_snapshot(
        secure_profile,
        json.loads(
            (
                ROOT / "plugins" / "anki-study-agent" / ".codex-plugin" / "plugin.json"
            ).read_text(encoding="utf-8")
        )["version"],
    )
    marketplace: Path | None = None
    mcp: dict[str, object] | None = None
    calls: list[tuple[str, ...]] = []

    def runner(arguments):
        nonlocal marketplace, mcp
        values = tuple(str(value) for value in arguments)
        calls.append(values)
        if values[1:] == ("--version",):
            return CommandResult(0, "codex-cli 0.144.1\n", "")
        if values[1:] == ("plugin", "marketplace", "list", "--json"):
            rows = (
                [{"name": "anki-study-agent-local", "root": str(marketplace)}]
                if marketplace is not None
                else []
            )
            return CommandResult(0, json.dumps({"marketplaces": rows}), "")
        if values[1:] == ("plugin", "list", "--json"):
            return CommandResult(0, json.dumps({"installed": [], "available": []}), "")
        if values[1:4] == ("mcp", "get", MCP_NAME):
            if mcp is None:
                return CommandResult(1, "", "not found")
            return CommandResult(0, json.dumps(mcp), "")
        if values[1:4] == ("plugin", "marketplace", "add"):
            marketplace = Path(values[4])
            return CommandResult(0, "{}", "")
        if values[1:4] == ("plugin", "marketplace", "remove"):
            marketplace = None
            return CommandResult(0, "{}", "")
        if values[1:4] == ("mcp", "add", MCP_NAME):
            separator = values.index("--")
            mcp = {
                "transport": {
                    "type": "stdio",
                    "command": values[separator + 1],
                    "args": list(values[separator + 2 :]),
                    "env": None,
                    "cwd": None,
                }
            }
            return CommandResult(0, "{}", "")
        if values[1:3] == ("mcp", "remove"):
            mcp = None
            return CommandResult(0, "{}", "")
        if values[1:3] == ("plugin", "add"):
            return CommandResult(1, "", "simulated plugin failure")
        if values[1:3] == ("plugin", "remove"):
            return CommandResult(0, "{}", "")
        return CommandResult(0, "{}", "")

    monkeypatch.setattr(
        "scripts.install_codex_study_plugin_dev.build_development_runtime",
        lambda **_: _fake_snapshot(secure_profile),
    )
    monkeypatch.setattr(
        "scripts.install_codex_study_plugin_dev.build_development_plugin_snapshot",
        lambda **_: plugin_snapshot,
    )
    _patch_plugin_snapshot_ownership(monkeypatch, plugin_snapshot)
    with pytest.raises(DevelopmentInstallError, match="plugin failure") as caught:
        install_or_upgrade(
            action="install",
            codex="codex",
            python=Path(sys.executable),
            anki_connect_port=8785,
            stage_tools=False,
            runner=runner,
            user_profile=secure_profile,
        )
    assert caught.value.partial is False
    assert caught.value.failed_step == "plugin_add"
    assert marketplace is None
    assert mcp is None


def test_install_preserves_inner_mcp_partial_failure(
    real_secure_snapshot: tuple[Path, DevelopmentRuntimeSnapshot],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile, snapshot = real_secure_snapshot
    plugin_snapshot = _fake_plugin_snapshot(
        profile,
        json.loads(
            (
                ROOT / "plugins" / "anki-study-agent" / ".codex-plugin" / "plugin.json"
            ).read_text(encoding="utf-8")
        )["version"],
    )
    mcp: CommandResult | None = _mcp_result(snapshot, port="8765")
    add_attempts = 0

    def runner(arguments):
        nonlocal add_attempts, mcp
        values = tuple(str(value) for value in arguments)
        if values[1:] == ("--version",):
            return CommandResult(0, "codex-cli 0.144.1\n", "")
        if values[1:] == ("plugin", "marketplace", "list", "--json"):
            return CommandResult(
                0,
                json.dumps(
                    {
                        "marketplaces": [
                            {
                                "name": "anki-study-agent-local",
                                "root": str(plugin_snapshot.root),
                            }
                        ]
                    }
                ),
                "",
            )
        if values[1:] == ("plugin", "list", "--json"):
            return CommandResult(0, json.dumps({"installed": []}), "")
        if values[1:4] == ("mcp", "get", MCP_NAME):
            return mcp or CommandResult(1, "", "not found")
        if values[1:3] == ("mcp", "remove"):
            mcp = None
            return CommandResult(0, "{}", "")
        if values[1:4] == ("mcp", "add", MCP_NAME):
            add_attempts += 1
            return CommandResult(1, "", "simulated add failure")
        return CommandResult(0, "{}", "")

    monkeypatch.setattr(
        "scripts.install_codex_study_plugin_dev.build_development_runtime",
        lambda **_: snapshot,
    )
    monkeypatch.setattr(
        "scripts.install_codex_study_plugin_dev.build_development_plugin_snapshot",
        lambda **_: plugin_snapshot,
    )
    _patch_plugin_snapshot_ownership(monkeypatch, plugin_snapshot)
    with pytest.raises(DevelopmentInstallError) as caught:
        install_or_upgrade(
            action="install",
            codex="codex",
            python=Path(sys.executable),
            anki_connect_port=8785,
            stage_tools=False,
            runner=runner,
            user_profile=profile,
        )
    assert add_attempts == 2
    assert caught.value.partial is True
    assert caught.value.failed_step == "mcp_add"
    assert MCP_NAME in caught.value.unrecovered


def test_install_rollback_never_removes_concurrently_replaced_marketplace(
    secure_profile: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin_snapshot = _fake_plugin_snapshot(
        secure_profile,
        json.loads(
            (
                ROOT / "plugins" / "anki-study-agent" / ".codex-plugin" / "plugin.json"
            ).read_text(encoding="utf-8")
        )["version"],
    )
    marketplace_root: Path | None = None
    mcp: dict[str, object] | None = None
    marketplace_remove_calls = 0

    def runner(arguments):
        nonlocal marketplace_root, marketplace_remove_calls, mcp
        values = tuple(str(value) for value in arguments)
        if values[1:] == ("--version",):
            return CommandResult(0, "codex-cli 0.144.1\n", "")
        if values[1:] == ("plugin", "marketplace", "list", "--json"):
            rows = (
                [{"name": "anki-study-agent-local", "root": str(marketplace_root)}]
                if marketplace_root is not None
                else []
            )
            return CommandResult(0, json.dumps({"marketplaces": rows}), "")
        if values[1:] == ("plugin", "list", "--json"):
            return CommandResult(0, json.dumps({"installed": []}), "")
        if values[1:4] == ("plugin", "marketplace", "add"):
            marketplace_root = Path(values[4])
            return CommandResult(0, "{}", "")
        if values[1:4] == ("plugin", "marketplace", "remove"):
            marketplace_remove_calls += 1
            marketplace_root = None
            return CommandResult(0, "{}", "")
        if values[1:4] == ("mcp", "get", MCP_NAME):
            return (
                CommandResult(0, json.dumps(mcp), "")
                if mcp is not None
                else CommandResult(1, "", "not found")
            )
        if values[1:4] == ("mcp", "add", MCP_NAME):
            separator = values.index("--")
            mcp = {
                "transport": {
                    "type": "stdio",
                    "command": values[separator + 1],
                    "args": list(values[separator + 2 :]),
                    "env": None,
                    "cwd": None,
                }
            }
            return CommandResult(0, "{}", "")
        if values[1:3] == ("mcp", "remove"):
            mcp = None
            return CommandResult(0, "{}", "")
        if values[1:3] == ("plugin", "add"):
            marketplace_root = secure_profile
            return CommandResult(1, "", "simulated plugin failure")
        return CommandResult(0, "{}", "")

    monkeypatch.setattr(
        "scripts.install_codex_study_plugin_dev.build_development_runtime",
        lambda **_: _fake_snapshot(secure_profile),
    )
    monkeypatch.setattr(
        "scripts.install_codex_study_plugin_dev.build_development_plugin_snapshot",
        lambda **_: plugin_snapshot,
    )
    _patch_plugin_snapshot_ownership(monkeypatch, plugin_snapshot)
    with pytest.raises(DevelopmentInstallError) as caught:
        install_or_upgrade(
            action="install",
            codex="codex",
            python=Path(sys.executable),
            anki_connect_port=8785,
            stage_tools=False,
            runner=runner,
            user_profile=secure_profile,
        )
    assert caught.value.partial is True
    assert "marketplace" in caught.value.unrecovered
    assert marketplace_root == secure_profile
    assert marketplace_remove_calls == 0


def test_install_requires_upgrade_when_plugin_is_already_installed(
    secure_profile: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin_snapshot = _fake_plugin_snapshot(secure_profile, "0.1.0")
    plugin_row = {
        "pluginId": PLUGIN_SELECTOR,
        "installed": True,
        "enabled": True,
        "version": "0.1.0",
        "source": {
            "source": "local",
            "path": str(plugin_snapshot.plugin_root),
        },
    }

    def runner(arguments):
        values = tuple(str(value) for value in arguments)
        if values[1:] == ("--version",):
            return CommandResult(0, "codex-cli 0.144.1\n", "")
        if values[1:] == ("plugin", "marketplace", "list", "--json"):
            return CommandResult(
                0,
                json.dumps(
                    {
                        "marketplaces": [
                            {
                                "name": "anki-study-agent-local",
                                "root": str(plugin_snapshot.root),
                            }
                        ]
                    }
                ),
                "",
            )
        if values[1:] == ("plugin", "list", "--json"):
            return CommandResult(0, json.dumps({"installed": [plugin_row]}), "")
        return CommandResult(1, "", "not found")

    built = False

    def build_snapshot(**_):
        nonlocal built
        built = True
        return _fake_snapshot(secure_profile)

    monkeypatch.setattr(
        "scripts.install_codex_study_plugin_dev.build_development_runtime",
        build_snapshot,
    )
    _patch_plugin_snapshot_ownership(monkeypatch, plugin_snapshot)
    with pytest.raises(DevelopmentInstallError, match="use upgrade"):
        install_or_upgrade(
            action="install",
            codex="codex",
            python=Path(sys.executable),
            anki_connect_port=8785,
            stage_tools=False,
            runner=runner,
            user_profile=secure_profile,
        )
    assert built is False


def test_upgrade_uses_cachebuster_and_keeps_changed_manifest_on_success(
    secure_profile: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    old_snapshot = _fake_plugin_snapshot(secure_profile, "0.1.0", digest_character="c")
    new_snapshot = _fake_plugin_snapshot(
        secure_profile, "0.1.0+codex.test", digest_character="d"
    )
    plugin_root = tmp_path / "plugin"
    manifest = plugin_root / ".codex-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        '{"name":"anki-study-agent","version":"0.1.0"}\n', encoding="utf-8"
    )
    plugin_row = {
        "pluginId": PLUGIN_SELECTOR,
        "installed": True,
        "enabled": True,
        "version": "0.1.0",
        "source": {"source": "local", "path": str(old_snapshot.plugin_root)},
    }

    def runner(arguments):
        values = tuple(str(value) for value in arguments)
        if values[1:] == ("--version",):
            return CommandResult(0, "codex-cli 0.144.1\n", "")
        if values[1:] == ("plugin", "marketplace", "list", "--json"):
            return CommandResult(
                0,
                json.dumps(
                    {
                        "marketplaces": [
                            {
                                "name": "anki-study-agent-local",
                                "root": str(old_snapshot.root),
                            }
                        ]
                    }
                ),
                "",
            )
        if values[1:] == ("plugin", "list", "--json"):
            return CommandResult(
                0, json.dumps({"installed": [plugin_row], "available": []}), ""
            )
        if values[1:4] == ("mcp", "get", MCP_NAME):
            return CommandResult(1, "", "not found")
        return CommandResult(0, "{}", "")

    def cachebuster(_: Path) -> CommandResult:
        manifest.write_text(
            '{"name":"anki-study-agent","version":"0.1.0+codex.test"}\n',
            encoding="utf-8",
        )
        plugin_row["version"] = "0.1.0+codex.test"
        return CommandResult(0, "updated", "")

    monkeypatch.setattr(
        "scripts.install_codex_study_plugin_dev.PLUGIN_ROOT", plugin_root
    )
    monkeypatch.setattr(
        "scripts.install_codex_study_plugin_dev.PLUGIN_MANIFEST", manifest
    )
    monkeypatch.setattr(
        "scripts.install_codex_study_plugin_dev._ensure_repository_shape", lambda: None
    )
    monkeypatch.setattr(
        "scripts.install_codex_study_plugin_dev.build_development_runtime",
        lambda **_: _fake_snapshot(secure_profile),
    )
    monkeypatch.setattr(
        "scripts.install_codex_study_plugin_dev.build_development_plugin_snapshot",
        lambda **_: new_snapshot,
    )
    monkeypatch.setattr(
        "scripts.install_codex_study_plugin_dev.register_development_marketplace",
        lambda **_: ("already_configured", old_snapshot.root),
    )
    _patch_plugin_snapshot_ownership(monkeypatch, old_snapshot, new_snapshot)
    monkeypatch.setattr(
        "scripts.install_codex_study_plugin_dev._verify_installed_state",
        lambda **_: None,
    )
    result = install_or_upgrade(
        action="upgrade",
        codex="codex",
        python=Path(sys.executable),
        anki_connect_port=8785,
        stage_tools=False,
        runner=runner,
        cachebuster_updater=cachebuster,
        user_profile=secure_profile,
    )
    assert result["pluginVersion"] == "0.1.0+codex.test"
    assert (
        json.loads(manifest.read_text(encoding="utf-8"))["version"]
        == "0.1.0+codex.test"
    )


def test_upgrade_restores_manifest_when_mcp_registration_fails(
    secure_profile: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    old_snapshot = _fake_plugin_snapshot(secure_profile, "0.1.0", digest_character="c")
    new_snapshot = _fake_plugin_snapshot(
        secure_profile, "0.1.0+codex.failed", digest_character="d"
    )
    plugin_root = tmp_path / "plugin"
    manifest = plugin_root / ".codex-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    original = b'{"name":"anki-study-agent","version":"0.1.0"}\n'
    manifest.write_bytes(original)
    plugin_row = {
        "pluginId": PLUGIN_SELECTOR,
        "installed": True,
        "enabled": True,
        "version": "0.1.0",
        "source": {"source": "local", "path": str(old_snapshot.plugin_root)},
    }

    def runner(arguments):
        values = tuple(str(value) for value in arguments)
        if values[1:] == ("--version",):
            return CommandResult(0, "codex-cli 0.144.1\n", "")
        if values[1:] == ("plugin", "marketplace", "list", "--json"):
            return CommandResult(
                0,
                json.dumps(
                    {
                        "marketplaces": [
                            {
                                "name": "anki-study-agent-local",
                                "root": str(old_snapshot.root),
                            }
                        ]
                    }
                ),
                "",
            )
        if values[1:] == ("plugin", "list", "--json"):
            return CommandResult(
                0, json.dumps({"installed": [plugin_row], "available": []}), ""
            )
        if values[1:4] == ("mcp", "get", MCP_NAME):
            return CommandResult(1, "", "not found")
        if values[1:4] == ("mcp", "add", MCP_NAME):
            return CommandResult(1, "", "simulated MCP failure")
        return CommandResult(0, "{}", "")

    def cachebuster(_: Path) -> CommandResult:
        manifest.write_text(
            '{"name":"anki-study-agent","version":"0.1.0+codex.failed"}\n',
            encoding="utf-8",
        )
        return CommandResult(0, "updated", "")

    monkeypatch.setattr(
        "scripts.install_codex_study_plugin_dev.PLUGIN_ROOT", plugin_root
    )
    monkeypatch.setattr(
        "scripts.install_codex_study_plugin_dev.PLUGIN_MANIFEST", manifest
    )
    monkeypatch.setattr(
        "scripts.install_codex_study_plugin_dev._ensure_repository_shape", lambda: None
    )
    monkeypatch.setattr(
        "scripts.install_codex_study_plugin_dev.build_development_runtime",
        lambda **_: _fake_snapshot(secure_profile),
    )
    monkeypatch.setattr(
        "scripts.install_codex_study_plugin_dev.build_development_plugin_snapshot",
        lambda **_: new_snapshot,
    )
    monkeypatch.setattr(
        "scripts.install_codex_study_plugin_dev.register_development_marketplace",
        lambda **_: ("already_configured", old_snapshot.root),
    )
    _patch_plugin_snapshot_ownership(monkeypatch, old_snapshot, new_snapshot)
    with pytest.raises(DevelopmentInstallError, match="Registering"):
        install_or_upgrade(
            action="upgrade",
            codex="codex",
            python=Path(sys.executable),
            anki_connect_port=8785,
            stage_tools=False,
            runner=runner,
            cachebuster_updater=cachebuster,
            user_profile=secure_profile,
        )
    assert manifest.read_bytes() == original


def test_upgrade_restores_manifest_when_cachebuster_corrupts_then_fails(
    secure_profile: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    old_snapshot = _fake_plugin_snapshot(secure_profile, "0.1.0", digest_character="c")
    plugin_root = tmp_path / "plugin"
    manifest = plugin_root / ".codex-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    original = b'{"name":"anki-study-agent","version":"0.1.0"}\n'
    manifest.write_bytes(original)
    plugin_row = {
        "pluginId": PLUGIN_SELECTOR,
        "installed": True,
        "enabled": True,
        "version": "0.1.0",
        "source": {"source": "local", "path": str(old_snapshot.plugin_root)},
    }

    def runner(arguments):
        values = tuple(str(value) for value in arguments)
        if values[1:] == ("--version",):
            return CommandResult(0, "codex-cli 0.144.1\n", "")
        if values[1:] == ("plugin", "marketplace", "list", "--json"):
            return CommandResult(
                0,
                json.dumps(
                    {
                        "marketplaces": [
                            {
                                "name": "anki-study-agent-local",
                                "root": str(old_snapshot.root),
                            }
                        ]
                    }
                ),
                "",
            )
        if values[1:] == ("plugin", "list", "--json"):
            return CommandResult(0, json.dumps({"installed": [plugin_row]}), "")
        if values[1:4] == ("mcp", "get", MCP_NAME):
            return CommandResult(1, "", "not found")
        return CommandResult(0, "{}", "")

    def cachebuster(_: Path) -> CommandResult:
        manifest.write_bytes(b"{")
        return CommandResult(1, "", "simulated cachebuster failure")

    monkeypatch.setattr(
        "scripts.install_codex_study_plugin_dev.PLUGIN_ROOT", plugin_root
    )
    monkeypatch.setattr(
        "scripts.install_codex_study_plugin_dev.PLUGIN_MANIFEST", manifest
    )
    monkeypatch.setattr(
        "scripts.install_codex_study_plugin_dev._ensure_repository_shape", lambda: None
    )
    _patch_plugin_snapshot_ownership(monkeypatch, old_snapshot)
    monkeypatch.setattr(
        "scripts.install_codex_study_plugin_dev.build_development_runtime",
        lambda **_: _fake_snapshot(secure_profile),
    )
    with pytest.raises(DevelopmentInstallError) as caught:
        install_or_upgrade(
            action="upgrade",
            codex="codex",
            python=Path(sys.executable),
            anki_connect_port=8785,
            stage_tools=False,
            runner=runner,
            cachebuster_updater=cachebuster,
            user_profile=secure_profile,
        )
    assert caught.value.failed_step == "cachebuster"
    assert caught.value.partial is False
    assert manifest.read_bytes() == original


def test_uninstall_refuses_unrelated_mcp_before_any_mutation(
    secure_profile: Path,
) -> None:
    calls: list[tuple[str, ...]] = []

    def runner(arguments):
        values = tuple(str(value) for value in arguments)
        calls.append(values)
        if values[1:] == ("plugin", "marketplace", "list", "--json"):
            return CommandResult(0, json.dumps({"marketplaces": []}), "")
        if values[1:] == ("plugin", "list", "--json"):
            return CommandResult(0, json.dumps({"installed": [], "available": []}), "")
        if values[1:4] == ("mcp", "get", MCP_NAME):
            return CommandResult(
                0,
                json.dumps(
                    {
                        "transport": {
                            "type": "stdio",
                            "command": "cmd.exe",
                            "args": ["/c", "exit"],
                            "env": None,
                            "cwd": None,
                        }
                    }
                ),
                "",
            )
        return CommandResult(0, "{}", "")

    with pytest.raises(DevelopmentInstallError, match="nothing was removed"):
        uninstall(
            codex="codex",
            python=Path(sys.executable),
            remove_marketplace=True,
            runner=runner,
            user_profile=secure_profile,
        )
    assert not any("remove" in values for values in calls)


def test_uninstall_refuses_same_marketplace_name_with_another_root(
    secure_profile: Path,
) -> None:
    calls: list[tuple[str, ...]] = []

    def runner(arguments):
        values = tuple(str(value) for value in arguments)
        calls.append(values)
        if values[1:] == ("plugin", "marketplace", "list", "--json"):
            return CommandResult(
                0,
                json.dumps(
                    {
                        "marketplaces": [
                            {
                                "name": "anki-study-agent-local",
                                "root": str(secure_profile),
                            }
                        ]
                    }
                ),
                "",
            )
        return CommandResult(0, json.dumps({"installed": [], "available": []}), "")

    with pytest.raises(DevelopmentInstallError, match="unrelated source"):
        uninstall(
            codex="codex",
            python=Path(sys.executable),
            remove_marketplace=True,
            runner=runner,
            user_profile=secure_profile,
        )
    assert not any("remove" in values for values in calls)


def test_uninstall_reports_partial_when_marketplace_changes_after_removals(
    real_secure_snapshot: tuple[Path, DevelopmentRuntimeSnapshot],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile, snapshot = real_secure_snapshot
    plugin_snapshot = _fake_plugin_snapshot(profile, "0.1.0")
    foreign_root = profile / "foreign-marketplace"
    marketplace_root: Path | None = plugin_snapshot.root
    plugin_row: dict[str, object] | None = {
        "pluginId": PLUGIN_SELECTOR,
        "installed": True,
        "enabled": True,
        "version": "0.1.0",
        "source": {
            "source": "local",
            "path": str(plugin_snapshot.plugin_root),
        },
    }
    mcp: CommandResult | None = _mcp_result(snapshot)

    def runner(arguments):
        nonlocal marketplace_root, plugin_row, mcp
        values = tuple(str(value) for value in arguments)
        if values[1:] == ("plugin", "marketplace", "list", "--json"):
            rows = (
                [{"name": "anki-study-agent-local", "root": str(marketplace_root)}]
                if marketplace_root is not None
                else []
            )
            return CommandResult(0, json.dumps({"marketplaces": rows}), "")
        if values[1:] == ("plugin", "list", "--json"):
            rows = [plugin_row] if plugin_row is not None else []
            return CommandResult(0, json.dumps({"installed": rows}), "")
        if values[1:3] == ("plugin", "remove"):
            plugin_row = None
            return CommandResult(0, "{}", "")
        if values[1:3] == ("plugin", "add"):
            return CommandResult(1, "", "foreign marketplace")
        if values[1:4] == ("mcp", "get", MCP_NAME):
            return mcp or CommandResult(1, "", "not found")
        if values[1:3] == ("mcp", "remove"):
            mcp = None
            return CommandResult(0, "{}", "")
        if values[1:4] == ("mcp", "add", MCP_NAME):
            separator = values.index("--")
            mcp = CommandResult(
                0,
                json.dumps(
                    {
                        "transport": {
                            "type": "stdio",
                            "command": values[separator + 1],
                            "args": list(values[separator + 2 :]),
                            "env": None,
                            "cwd": None,
                        }
                    }
                ),
                "",
            )
            return CommandResult(0, "{}", "")
        if values[1:4] == ("plugin", "marketplace", "remove"):
            marketplace_root = foreign_root
            return CommandResult(1, "", "simulated concurrent replacement")
        return CommandResult(0, "{}", "")

    _patch_plugin_snapshot_ownership(monkeypatch, plugin_snapshot)
    with pytest.raises(DevelopmentInstallError) as caught:
        uninstall(
            codex="codex",
            python=Path(sys.executable),
            remove_marketplace=True,
            runner=runner,
            user_profile=profile,
        )
    assert caught.value.failed_step == "marketplace_remove"
    assert caught.value.partial is True
    assert set(caught.value.unrecovered) == {"marketplace", "plugin"}
    assert mcp is not None
    assert plugin_row is None
    assert marketplace_root == foreign_root
