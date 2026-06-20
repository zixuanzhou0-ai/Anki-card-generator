from __future__ import annotations

import html
import re
from typing import Any

from acg.text_cleaning import clean_study_text


def anki_text(value: Any) -> str:
    return html.escape(str(value or ""), quote=False)


def audit_text_excerpt(value: Any, limit: int = 96) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "\u2026"


def anki_study_text(value: Any) -> str:
    return anki_text(clean_study_text(value))
