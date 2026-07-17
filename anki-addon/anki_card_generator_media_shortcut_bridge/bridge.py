from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from typing import Any, Callable, MutableSequence, Protocol


ADDON_VERSION = "1.0.0-m0"
REVIEW_STATE = "review"
SUPPORTED_NOTE_MODEL_CONTRACTS = {
    1028904201: {
        "model_name": "Anki Card Generator V15 - 沉浸复读 V11",
        "template_name": "沉浸复读 V11",
        "qfmt_sha256": "03fa14f4b922ef350a358d77c10548eb1b5b8206b22d61b62ce6db8c83f29b35",
        "afmt_sha256": "7037ae6a3a8b0f2a5237b65010ffdafabf0fb6c6cb2c45dcc7514c50f81fb0a5",
        "css_sha256": "ce67ba0760df2996366989d25196ccaf0d6f05d3da87e44a7b692676e795f8a4",
    },
    5074019806: {
        "model_name": "Anki Card Generator V15 - 沉浸复读 V11 · 快速复读",
        "template_name": "沉浸复读 V11 · 快速复读",
        "qfmt_sha256": "0c977481c6fa3aa5aa97c0c9d81d925e32f00dea135244ddae844206abbeedd9",
        "afmt_sha256": "9395ce09a444716a78ce363c8ebe88cd03409014f42f3ae62a56039eb5bf6bb7",
        "css_sha256": "3023d916bf3ad30182ffdacccec6d5d76c987478fbe667a9cca9451d63b177df",
    },
}
SUPPORTED_NOTE_MODEL_IDS = frozenset(SUPPORTED_NOTE_MODEL_CONTRACTS)
ROUTING_TIMEOUT_MS = 1500


class ReviewerWeb(Protocol):
    def evalWithCallback(self, script: str, callback: Callable[[Any], None]) -> None: ...


class ReviewerCard(Protocol):
    id: Any

    def note_type(self) -> dict[str, Any]: ...


class Reviewer(Protocol):
    card: ReviewerCard | None
    state: str | None
    web: ReviewerWeb


@dataclass(frozen=True)
class ReviewSnapshot:
    card_id: str
    side: str
    note_model_id: int
    runtime_contract_valid: bool


@dataclass(frozen=True)
class RoutingToken:
    sequence: int
    snapshot: ReviewSnapshot


def _probe_focused_media_script(sequence: int) -> str:
    token = json.dumps(str(sequence))
    return f"""
(() => {{
  const root = document.querySelector('.v11-card');
  const active = document.activeElement;
  if (!root || !(active instanceof Element)) return {{ state: 'pass' }};
  const control = active.closest('[data-media-selector], .v11-video-stage');
  if (!control || !root.contains(control)) return {{ state: 'pass' }};
  if (control.matches('[disabled], [aria-disabled="true"]')) return {{ state: 'blocked' }};
  control.setAttribute('data-acg-shortcut-token', {token});
  return {{
    state: 'focused_media',
    role: control.getAttribute('data-media-role') ||
      (control.classList.contains('v11-video-stage') ? 'video' : 'unknown')
  }};
}})()
""".strip()


def _activate_focused_media_script(sequence: int) -> str:
    token = json.dumps(str(sequence))
    return f"""
(() => {{
  const root = document.querySelector('.v11-card');
  if (!root) return {{ state: 'stale' }};
  const control = Array.from(root.querySelectorAll('[data-acg-shortcut-token]'))
    .find((candidate) => candidate.getAttribute('data-acg-shortcut-token') === {token});
  if (!control) return {{ state: 'stale' }};
  control.removeAttribute('data-acg-shortcut-token');
  control.click();
  return {{ state: 'handled' }};
}})()
""".strip()


def _text_sha256(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def note_type_matches_runtime_contract(note_type: Any) -> bool:
    if not isinstance(note_type, dict):
        return False
    try:
        note_model_id = int(note_type.get("id"))
    except (TypeError, ValueError):
        return False
    expected = SUPPORTED_NOTE_MODEL_CONTRACTS.get(note_model_id)
    if expected is None or note_type.get("name") != expected["model_name"]:
        return False
    if _text_sha256(note_type.get("css")) != expected["css_sha256"]:
        return False
    templates = note_type.get("tmpls")
    if not isinstance(templates, list) or len(templates) != 1:
        return False
    template = templates[0]
    if not isinstance(template, dict) or template.get("name") != expected["template_name"]:
        return False
    return (
        _text_sha256(template.get("qfmt")) == expected["qfmt_sha256"]
        and _text_sha256(template.get("afmt")) == expected["afmt_sha256"]
    )


class MediaShortcutRouter:
    def __init__(
        self,
        reviewer_provider: Callable[[], Reviewer | None],
        notify: Callable[[str], None],
        schedule_timeout: Callable[[int, Callable[[], None]], None],
    ) -> None:
        self._reviewer_provider = reviewer_provider
        self._notify = notify
        self._schedule_timeout = schedule_timeout
        self._sequence = 0
        self._pending: RoutingToken | None = None

    @property
    def pending(self) -> bool:
        return self._pending is not None

    def wrap_shortcuts(
        self,
        state: str,
        shortcuts: MutableSequence[tuple[Any, Callable[[], None]]],
        is_media_activation_key: Callable[[Any], bool],
    ) -> None:
        if state != REVIEW_STATE:
            return
        for index, (key, callback) in enumerate(tuple(shortcuts)):
            if not is_media_activation_key(key) or getattr(
                callback, "_acg_media_shortcut_wrapper", False
            ):
                continue

            def wrapped(
                original: Callable[[], None] = callback,
            ) -> None:
                self.route_or_fallback(original)

            setattr(wrapped, "_acg_media_shortcut_wrapper", True)
            shortcuts[index] = (key, wrapped)

    def route_or_fallback(self, original: Callable[[], None]) -> None:
        snapshot = self._current_snapshot()
        if snapshot is None or snapshot.note_model_id not in SUPPORTED_NOTE_MODEL_IDS:
            original()
            return
        if not snapshot.runtime_contract_valid:
            self._notify("卡片运行时合同不匹配；本次没有翻面或评分。")
            return
        if self._pending is not None:
            return

        reviewer = self._reviewer_provider()
        if reviewer is None:
            original()
            return
        self._sequence += 1
        token = RoutingToken(self._sequence, snapshot)
        self._pending = token
        self._schedule_timeout(
            ROUTING_TIMEOUT_MS,
            lambda: self._on_timeout(token),
        )
        try:
            reviewer.web.evalWithCallback(
                _probe_focused_media_script(token.sequence),
                lambda result: self._on_probe(token, original, result),
            )
        except Exception:
            self._fail_closed(token, "媒体快捷键检查失败；本次没有翻面或评分。")

    def _on_probe(
        self,
        token: RoutingToken,
        original: Callable[[], None],
        result: Any,
    ) -> None:
        if not self._is_current(token):
            self._clear_if_pending(token)
            return
        state = result.get("state") if isinstance(result, dict) else None
        if state == "pass":
            self._pending = None
            original()
            return
        if state != "focused_media":
            self._fail_closed(token, "媒体控件当前不可用；本次没有翻面或评分。")
            return

        reviewer = self._reviewer_provider()
        if reviewer is None:
            self._fail_closed(token, "Anki 复习页面已经变化；本次没有翻面或评分。")
            return
        try:
            reviewer.web.evalWithCallback(
                _activate_focused_media_script(token.sequence),
                lambda activation: self._on_activation(token, activation),
            )
        except Exception:
            self._fail_closed(token, "媒体快捷键执行失败；本次没有翻面或评分。")

    def _on_activation(self, token: RoutingToken, result: Any) -> None:
        if not self._is_current(token):
            self._clear_if_pending(token)
            return
        state = result.get("state") if isinstance(result, dict) else None
        if state == "handled":
            self._pending = None
            return
        self._fail_closed(token, "媒体焦点已经变化；本次没有翻面或评分。")

    def _on_timeout(self, token: RoutingToken) -> None:
        if self._pending != token:
            return
        self._pending = None
        self._notify("媒体快捷键响应超时；本次没有翻面或评分。")

    def _fail_closed(self, token: RoutingToken, message: str) -> None:
        self._clear_if_pending(token)
        self._notify(message)

    def _clear_if_pending(self, token: RoutingToken) -> None:
        if self._pending == token:
            self._pending = None

    def _is_current(self, token: RoutingToken) -> bool:
        return self._pending == token and self._current_snapshot() == token.snapshot

    def _current_snapshot(self) -> ReviewSnapshot | None:
        reviewer = self._reviewer_provider()
        if reviewer is None or reviewer.card is None:
            return None
        side = str(reviewer.state or "")
        if side not in {"question", "answer"}:
            return None
        try:
            note_type = reviewer.card.note_type()
            note_model_id = int(note_type.get("id"))
            card_id = str(reviewer.card.id)
        except (AttributeError, TypeError, ValueError):
            return None
        if not card_id:
            return None
        return ReviewSnapshot(
            card_id,
            side,
            note_model_id,
            note_type_matches_runtime_contract(note_type),
        )


__all__ = [
    "ADDON_VERSION",
    "MediaShortcutRouter",
    "REVIEW_STATE",
    "ROUTING_TIMEOUT_MS",
    "SUPPORTED_NOTE_MODEL_CONTRACTS",
    "SUPPORTED_NOTE_MODEL_IDS",
    "note_type_matches_runtime_contract",
]
