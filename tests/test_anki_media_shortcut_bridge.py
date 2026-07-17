from __future__ import annotations

import importlib.util
import hashlib
import json
import sys
import zipfile
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
BRIDGE_PATH = (
    ROOT
    / "anki-addon"
    / "anki_card_generator_media_shortcut_bridge"
    / "bridge.py"
)
SPEC = importlib.util.spec_from_file_location("acg_media_shortcut_bridge", BRIDGE_PATH)
assert SPEC is not None and SPEC.loader is not None
bridge = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bridge
SPEC.loader.exec_module(bridge)


class FakeWeb:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Callable[[Any], None]]] = []
        self.raise_on_eval = False

    def evalWithCallback(self, script: str, callback: Callable[[Any], None]) -> None:
        if self.raise_on_eval:
            raise RuntimeError("webview unavailable")
        self.calls.append((script, callback))

    def reply(self, result: Any, index: int = 0) -> None:
        _script, callback = self.calls[index]
        callback(result)


def frozen_note_type(note_model_id: int = 1028904201) -> dict[str, Any]:
    contract = bridge.SUPPORTED_NOTE_MODEL_CONTRACTS[note_model_id]
    workers = ROOT / "workers"
    if str(workers) not in sys.path:
        sys.path.insert(0, str(workers))
    from acg.legacy_worker import anki_template_assets

    review_density = "fast" if note_model_id == 5074019806 else "full"
    template_name, css, qfmt, afmt = anki_template_assets(
        "immersive_v11",
        "video_language",
        "warm_paper",
        review_density,
    )
    assert template_name == contract["template_name"]
    return {
        "id": note_model_id,
        "name": contract["model_name"],
        "css": css,
        "tmpls": [
            {
                "name": contract["template_name"],
                "qfmt": qfmt,
                "afmt": afmt,
            }
        ],
    }


class FakeCard:
    def __init__(
        self,
        card_id: int = 7,
        note_model_id: int = 1028904201,
        note_type_override: dict[str, Any] | None = None,
    ) -> None:
        self.id = card_id
        self.note_model_id = note_model_id
        self.note_type_override = note_type_override

    def note_type(self) -> dict[str, Any]:
        if self.note_type_override is not None:
            return self.note_type_override
        if self.note_model_id in bridge.SUPPORTED_NOTE_MODEL_IDS:
            return frozen_note_type(self.note_model_id)
        return {"id": self.note_model_id}


class FakeReviewer:
    def __init__(self, note_model_id: int = 1028904201) -> None:
        self.card = FakeCard(note_model_id=note_model_id)
        self.state = "question"
        self.web = FakeWeb()


class Harness:
    def __init__(self, note_model_id: int = 1028904201) -> None:
        self.reviewer = FakeReviewer(note_model_id)
        self.messages: list[str] = []
        self.timers: list[Callable[[], None]] = []
        self.router = bridge.MediaShortcutRouter(
            lambda: self.reviewer,
            self.messages.append,
            lambda _delay, callback: self.timers.append(callback),
        )


def test_exact_v15_model_ids_are_frozen() -> None:
    assert bridge.SUPPORTED_NOTE_MODEL_IDS == {1028904201, 5074019806}


def test_exact_v15_runtime_templates_are_required() -> None:
    for note_model_id in bridge.SUPPORTED_NOTE_MODEL_IDS:
        note_type = frozen_note_type(note_model_id)
        assert bridge.note_type_matches_runtime_contract(note_type)

        tampered = json.loads(json.dumps(note_type))
        tampered["tmpls"][0]["afmt"] += "<!-- tampered -->"
        assert not bridge.note_type_matches_runtime_contract(tampered)


def test_only_review_activation_shortcuts_are_wrapped() -> None:
    harness = Harness()
    callbacks = [lambda: None, lambda: None, lambda: None]
    shortcuts = [(" ", callbacks[0]), ("enter", callbacks[1]), ("x", callbacks[2])]
    harness.router.wrap_shortcuts(
        "review",
        shortcuts,
        lambda key: key in {" ", "enter"},
    )

    assert shortcuts[0][1] is not callbacks[0]
    assert shortcuts[1][1] is not callbacks[1]
    assert shortcuts[2][1] is callbacks[2]

    before = list(shortcuts)
    harness.router.wrap_shortcuts(
        "review",
        shortcuts,
        lambda key: key in {" ", "enter"},
    )
    assert shortcuts == before


def test_non_review_state_is_untouched() -> None:
    harness = Harness()
    callback = lambda: None
    shortcuts = [(" ", callback)]
    harness.router.wrap_shortcuts("deckBrowser", shortcuts, lambda _key: True)
    assert shortcuts == [(" ", callback)]


def test_non_v15_card_calls_original_synchronously() -> None:
    harness = Harness(note_model_id=3157735470)
    original_calls: list[str] = []
    harness.router.route_or_fallback(lambda: original_calls.append("original"))
    assert original_calls == ["original"]
    assert harness.reviewer.web.calls == []


def test_v15_runtime_contract_mismatch_fails_closed() -> None:
    harness = Harness()
    tampered = frozen_note_type()
    tampered["tmpls"][0]["qfmt"] += "<!-- tampered -->"
    harness.reviewer.card = FakeCard(note_type_override=tampered)
    original_calls: list[str] = []

    harness.router.route_or_fallback(lambda: original_calls.append("original"))

    assert original_calls == []
    assert harness.reviewer.web.calls == []
    assert harness.messages == ["卡片运行时合同不匹配；本次没有翻面或评分。"]


def test_blank_card_focus_delegates_to_anki_once() -> None:
    harness = Harness()
    original_calls: list[str] = []
    harness.router.route_or_fallback(lambda: original_calls.append("original"))
    assert harness.router.pending
    assert len(harness.reviewer.web.calls) == 1

    harness.reviewer.web.reply({"state": "pass"})
    assert original_calls == ["original"]
    assert not harness.router.pending
    harness.timers[0]()
    assert original_calls == ["original"]
    assert harness.messages == []


def test_focused_media_uses_two_phase_activation_without_flipping() -> None:
    harness = Harness()
    original_calls: list[str] = []
    harness.router.route_or_fallback(lambda: original_calls.append("original"))
    probe_script = harness.reviewer.web.calls[0][0]
    assert "document.activeElement" in probe_script
    assert "data-acg-shortcut-token" in probe_script

    harness.reviewer.web.reply({"state": "focused_media", "role": "video"})
    assert len(harness.reviewer.web.calls) == 2
    activation_script = harness.reviewer.web.calls[1][0]
    assert "querySelectorAll('[data-acg-shortcut-token]')" in activation_script
    assert "getAttribute('data-acg-shortcut-token') ===" in activation_script
    assert "querySelector('[data-acg-shortcut-token='" not in activation_script
    assert ".click()" in activation_script
    harness.reviewer.web.reply({"state": "handled"}, index=1)

    assert original_calls == []
    assert harness.messages == []
    assert not harness.router.pending


def test_rapid_double_press_is_single_flight() -> None:
    harness = Harness()
    original_calls: list[str] = []
    original = lambda: original_calls.append("original")
    harness.router.route_or_fallback(original)
    harness.router.route_or_fallback(original)
    assert len(harness.reviewer.web.calls) == 1
    assert original_calls == []


def test_stale_card_or_side_never_calls_old_shortcut() -> None:
    harness = Harness()
    original_calls: list[str] = []
    harness.router.route_or_fallback(lambda: original_calls.append("original"))
    harness.reviewer.card = FakeCard(card_id=8)
    harness.reviewer.web.reply({"state": "pass"})
    assert original_calls == []
    assert not harness.router.pending


def test_probe_and_activation_fail_closed() -> None:
    probe = Harness()
    probe_calls: list[str] = []
    probe.router.route_or_fallback(lambda: probe_calls.append("original"))
    probe.reviewer.web.reply({"state": "blocked"})
    assert probe_calls == []
    assert probe.messages == ["媒体控件当前不可用；本次没有翻面或评分。"]

    activation = Harness()
    activation_calls: list[str] = []
    activation.router.route_or_fallback(lambda: activation_calls.append("original"))
    activation.reviewer.web.reply({"state": "focused_media"})
    activation.reviewer.web.reply({"state": "stale"}, index=1)
    assert activation_calls == []
    assert activation.messages == ["媒体焦点已经变化；本次没有翻面或评分。"]


def test_eval_exception_and_timeout_fail_closed_but_recover() -> None:
    harness = Harness()
    harness.reviewer.web.raise_on_eval = True
    original_calls: list[str] = []
    harness.router.route_or_fallback(lambda: original_calls.append("original"))
    assert original_calls == []
    assert harness.messages == ["媒体快捷键检查失败；本次没有翻面或评分。"]
    assert not harness.router.pending

    harness.reviewer.web.raise_on_eval = False
    harness.router.route_or_fallback(lambda: original_calls.append("original"))
    harness.timers[-1]()
    assert not harness.router.pending
    assert harness.messages[-1] == "媒体快捷键响应超时；本次没有翻面或评分。"

    harness.router.route_or_fallback(lambda: original_calls.append("original"))
    assert len(harness.reviewer.web.calls) == 2


def test_bridge_has_no_network_or_collection_write_surface() -> None:
    source = BRIDGE_PATH.read_text(encoding="utf-8")
    forbidden = (
        "requests",
        "urllib",
        "socket",
        "anki_connect",
        "mw.col",
        ".write(",
        "open(",
        "subprocess",
    )
    assert all(token not in source for token in forbidden)


def test_addon_installs_once_on_non_iterable_anki_hook(monkeypatch) -> None:
    class NonIterableHook:
        def __init__(self) -> None:
            self.callbacks: list[Callable[..., None]] = []

        def append(self, callback: Callable[..., None]) -> None:
            self.callbacks.append(callback)

    hook = NonIterableHook()
    aqt_module = ModuleType("aqt")
    aqt_module.gui_hooks = SimpleNamespace(state_shortcuts_will_change=hook)
    aqt_module.mw = SimpleNamespace(
        reviewer=None,
        progress=SimpleNamespace(single_shot=lambda _delay, _callback: None),
    )
    qt_module = ModuleType("aqt.qt")
    qt_module.Qt = SimpleNamespace(Key=SimpleNamespace(Key_Return=1, Key_Enter=2))
    utils_module = ModuleType("aqt.utils")
    utils_module.tooltip = lambda _message: None
    monkeypatch.setitem(sys.modules, "aqt", aqt_module)
    monkeypatch.setitem(sys.modules, "aqt.qt", qt_module)
    monkeypatch.setitem(sys.modules, "aqt.utils", utils_module)

    package_name = "acg_media_shortcut_addon_test"
    package_root = BRIDGE_PATH.parent
    package_spec = importlib.util.spec_from_file_location(
        package_name,
        package_root / "__init__.py",
        submodule_search_locations=[str(package_root)],
    )
    assert package_spec is not None and package_spec.loader is not None
    package = importlib.util.module_from_spec(package_spec)
    monkeypatch.setitem(sys.modules, package_name, package)
    package_spec.loader.exec_module(package)
    package_spec.loader.exec_module(package)

    assert len(hook.callbacks) == 1


def test_manifest_and_runtime_contract_are_exact_and_hash_bound() -> None:
    package_root = BRIDGE_PATH.parent
    manifest = json.loads((package_root / "manifest.json").read_text(encoding="utf-8"))
    contract = json.loads(
        (package_root / "runtime-contract.v1.json").read_text(encoding="utf-8")
    )

    assert manifest["package"] == "anki_card_generator_media_shortcut_bridge"
    assert manifest["min_point_version"] == 260500
    assert manifest["max_point_version"] == 260500
    assert manifest["human_version"] == bridge.ADDON_VERSION
    assert contract["schema_version"] == 1
    assert contract["supported_anki_point_versions"] == [260500]
    assert contract["permissions"] == {
        "network": False,
        "collection_read": False,
        "collection_write": False,
        "media_write": False,
    }
    assert {item["note_model_id"] for item in contract["supported_note_models"]} == set(
        bridge.SUPPORTED_NOTE_MODEL_IDS
    )
    for item in contract["supported_note_models"]:
        runtime = bridge.SUPPORTED_NOTE_MODEL_CONTRACTS[item["note_model_id"]]
        assert item["model_name"] == runtime["model_name"]
        assert item["template_name"] == runtime["template_name"]
        assert item["qfmt_sha256"] == runtime["qfmt_sha256"]
        assert item["afmt_sha256"] == runtime["afmt_sha256"]
        assert item["css_sha256"] == runtime["css_sha256"]
    for name, expected in contract["implementation_sha256"].items():
        actual = hashlib.sha256((package_root / name).read_bytes()).hexdigest()
        assert actual == expected


def test_runtime_contract_matches_current_v15_note_model_registry() -> None:
    workers = ROOT / "workers"
    if str(workers) not in sys.path:
        sys.path.insert(0, str(workers))
    from acg.anki_model_contracts import CONTRACTS_BY_MODEL_ID

    contract = json.loads(
        (BRIDGE_PATH.parent / "runtime-contract.v1.json").read_text(encoding="utf-8")
    )
    for item in contract["supported_note_models"]:
        model = CONTRACTS_BY_MODEL_ID[item["note_model_id"]]
        assert model.template_schema == item["template_schema"]
        assert model.template_family == item["template_family"]
        assert model.contract_digest == item["note_model_contract_digest"]
        assert model.qfmt_sha256 == item["qfmt_sha256"]
        assert model.afmt_sha256 == item["afmt_sha256"]
        assert model.css_sha256 == item["css_sha256"]


def test_built_addon_archive_has_only_contract_files(tmp_path: Path) -> None:
    package = tmp_path / "bridge.ankiaddon"
    required = ["__init__.py", "bridge.py", "manifest.json", "runtime-contract.v1.json"]
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in required:
            archive.write(BRIDGE_PATH.parent / name, name)

    with zipfile.ZipFile(package) as archive:
        assert sorted(archive.namelist()) == sorted(required)
        assert all(not name.startswith("anki_card_generator_media_shortcut_bridge/") for name in archive.namelist())
