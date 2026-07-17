from __future__ import annotations

from aqt import gui_hooks, mw
from aqt.qt import Qt
from aqt.utils import tooltip

from .bridge import MediaShortcutRouter


def _reviewer():
    return getattr(mw, "reviewer", None)


def _notify(message: str) -> None:
    tooltip(message)


def _schedule_timeout(delay_ms: int, callback) -> None:
    mw.progress.single_shot(delay_ms, callback)


def _is_media_activation_key(key) -> bool:
    return key == " " or key in {Qt.Key.Key_Return, Qt.Key.Key_Enter}


_router = MediaShortcutRouter(_reviewer, _notify, _schedule_timeout)


def _on_state_shortcuts_will_change(state, shortcuts) -> None:
    _router.wrap_shortcuts(state, shortcuts, _is_media_activation_key)


if not globals().get("_ACG_MEDIA_SHORTCUT_HOOK_INSTALLED", False):
    gui_hooks.state_shortcuts_will_change.append(_on_state_shortcuts_will_change)
    _ACG_MEDIA_SHORTCUT_HOOK_INSTALLED = True
