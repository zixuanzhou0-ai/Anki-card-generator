from __future__ import annotations

from dataclasses import dataclass
import html
import re
import unicodedata
from typing import Any, Iterable

from acg.text_cleaning import clean_study_text


@dataclass(frozen=True)
class HighlightSpan:
    start: int
    end: int
    text: str
    source: str


@dataclass(frozen=True)
class CardPresentationMarkup:
    source_html: str
    meaning_html: str
    answer_note_html: str
    pronunciation_note_html: str
    source_translation_html: str
    usage_html: str
    misuse_html: str
    example_items_html: str
    warnings: tuple[str, ...]


_GRAMMAR_SEPARATOR_RE = re.compile(r"(?:\.{2,}|…+|_{2,}|\{[^{}]*\}|<[^<>]*>)")
_TRANSFER_SEPARATOR_RE = re.compile(r"(?:[\r\n]+|\s+/\s+|；+)")


def _normalized_match_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", clean_study_text(value))
    text = text.translate(
        str.maketrans(
            {
                "’": "'",
                "‘": "'",
                "‐": "-",
                "‑": "-",
                "‒": "-",
                "–": "-",
                "—": "-",
            }
        )
    )
    return re.sub(r"\s+", " ", text).strip().casefold()


def _canonical_surface(value: Any) -> str:
    return "".join(
        unicodedata.normalize("NFKC", character).translate(
            str.maketrans(
                {
                    "’": "'",
                    "‘": "'",
                    "‐": "-",
                    "‑": "-",
                    "‒": "-",
                    "–": "-",
                    "—": "-",
                }
            )
        ).casefold()
        for character in clean_study_text(value)
    )


def _dedupe_marker(value: Any) -> str:
    return re.sub(r"[\s\W_]+", "", _normalized_match_text(value), flags=re.UNICODE)


def _valid_span(text: str, span: HighlightSpan) -> bool:
    if span.start < 0 or span.end <= span.start or span.end > len(text):
        return False
    return _normalized_match_text(text[span.start : span.end]) == _normalized_match_text(span.text)


def _offset_span(text: str, target: str, start: Any, end: Any) -> HighlightSpan | None:
    if isinstance(start, bool) or isinstance(end, bool):
        return None
    try:
        start_index = int(start)
        end_index = int(end)
    except (TypeError, ValueError):
        return None
    span = HighlightSpan(start_index, end_index, text[start_index:end_index], "exact_span") if 0 <= start_index <= end_index <= len(text) else None
    if span is None or not _valid_span(text, span):
        return None
    if _normalized_match_text(span.text) != _normalized_match_text(target):
        return None
    return span


def _boundary_pattern(target: str) -> re.Pattern[str] | None:
    clean_target = clean_study_text(target)
    if not clean_target:
        return None
    prefix = r"(?<!\w)" if clean_target[0].isalnum() else ""
    suffix = r"(?!\w)" if clean_target[-1].isalnum() else ""
    return re.compile(prefix + re.escape(clean_target) + suffix, flags=re.IGNORECASE | re.UNICODE)


def _exact_match_spans(text: str, target: str, *, all_matches: bool) -> list[HighlightSpan]:
    pattern = _boundary_pattern(target)
    if pattern is None:
        return []
    matches = [
        HighlightSpan(match.start(), match.end(), text[match.start() : match.end()], "exact_match")
        for match in pattern.finditer(text)
    ]
    if not matches:
        canonical_text = _canonical_surface(text)
        canonical_target = _canonical_surface(target)
        if len(canonical_text) == len(text) and len(canonical_target) == len(clean_study_text(target)):
            canonical_pattern = _boundary_pattern(canonical_target)
            if canonical_pattern is not None:
                matches = [
                    HighlightSpan(match.start(), match.end(), text[match.start() : match.end()], "exact_match")
                    for match in canonical_pattern.finditer(canonical_text)
                ]
    if not all_matches and len(matches) != 1:
        return []
    return matches if all_matches else matches[:1]


def _useful_grammar_anchor(value: str) -> bool:
    words = re.findall(r"[^\W_]+", value, flags=re.UNICODE)
    return len(words) >= 2 or (len(words) == 1 and len(words[0]) >= 4)


def _grammar_anchor_spans(text: str, target: str) -> list[HighlightSpan]:
    if not _GRAMMAR_SEPARATOR_RE.search(target):
        return []
    anchors = [part.strip(" \t,;:，；：") for part in _GRAMMAR_SEPARATOR_RE.split(target)]
    anchors = [anchor for anchor in anchors if anchor and _useful_grammar_anchor(anchor)]
    if len(anchors) < 2:
        return []
    spans: list[HighlightSpan] = []
    cursor = 0
    for anchor in anchors:
        pattern = _boundary_pattern(anchor)
        match = pattern.search(text, cursor) if pattern else None
        if match is None:
            return []
        spans.append(
            HighlightSpan(match.start(), match.end(), text[match.start() : match.end()], "grammar_anchor")
        )
        cursor = match.end()
    return spans


def resolve_source_spans(text: Any, card: dict[str, Any]) -> list[HighlightSpan]:
    source_text = clean_study_text(text)
    exact_span = clean_study_text(card.get("exact_span") or card.get("phrase") or card.get("answer_core"))
    if not source_text or not exact_span:
        return []
    offset_span = _offset_span(
        source_text,
        exact_span,
        card.get("exact_span_start"),
        card.get("exact_span_end"),
    )
    if offset_span is not None:
        return [offset_span]
    exact_matches = _exact_match_spans(source_text, exact_span, all_matches=False)
    if exact_matches:
        return exact_matches
    return _grammar_anchor_spans(source_text, exact_span)


def resolve_example_spans(text: Any, card: dict[str, Any]) -> list[HighlightSpan]:
    example_text = clean_study_text(text)
    if not example_text:
        return []
    seen: set[str] = set()
    targets: list[str] = []
    for value in (card.get("answer_core"), card.get("exact_span"), card.get("phrase")):
        target = clean_study_text(value)
        marker = _normalized_match_text(target)
        if target and marker not in seen:
            targets.append(target)
            seen.add(marker)
    for target in targets:
        exact_matches = _exact_match_spans(example_text, target, all_matches=True)
        if exact_matches:
            return exact_matches
    for target in targets:
        grammar_matches = _grammar_anchor_spans(example_text, target)
        if grammar_matches:
            return grammar_matches
    return []


def render_highlighted_text(text: Any, spans: Iterable[HighlightSpan]) -> str:
    source_text = clean_study_text(text)
    ordered = sorted(spans, key=lambda item: (item.start, item.end))
    if not source_text or not ordered:
        return html.escape(source_text, quote=False)
    cursor = 0
    parts: list[str] = []
    for span in ordered:
        if span.start < cursor or not _valid_span(source_text, span):
            return html.escape(source_text, quote=False)
        parts.append(html.escape(source_text[cursor : span.start], quote=False))
        parts.append(
            '<mark class="target-expression">'
            + html.escape(source_text[span.start : span.end], quote=False)
            + "</mark>"
        )
        cursor = span.end
    parts.append(html.escape(source_text[cursor:], quote=False))
    return "".join(parts)


def render_target_display(text: Any, card: dict[str, Any]) -> str:
    """Return safe display HTML only when the current target is verified in text.

    Empty output intentionally tells the Anki template to use its original plain
    field. This keeps presentation markup separate from source, TTS, and audit
    data while allowing every verified back-side occurrence to share one style.
    """

    clean_text = clean_study_text(text)
    if not clean_text:
        return ""
    spans = resolve_example_spans(clean_text, card)
    return render_highlighted_text(clean_text, spans) if spans else ""


def split_transfer_examples(*values: Any, limit: int = 3) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for value in values:
        raw_values = value if isinstance(value, (list, tuple)) else [value]
        for raw_value in raw_values:
            raw_text = str(raw_value or "")
            if not raw_text.strip():
                continue
            for raw_item in _TRANSFER_SEPARATOR_RE.split(raw_text):
                item = raw_item.strip(" \t；;")
                item = clean_study_text(item)
                marker = _dedupe_marker(item)
                if not item or not marker or marker in seen:
                    continue
                seen.add(marker)
                items.append(item)
                if len(items) >= limit:
                    return items
    return items


def build_card_presentation(
    card: dict[str, Any],
    *,
    source_text: Any,
    meaning_text: Any = "",
    answer_note_text: Any = "",
    pronunciation_note_text: Any = "",
    source_translation_text: Any = "",
    usage_text: Any = "",
    misuse_text: Any = "",
    example_values: Iterable[Any],
) -> CardPresentationMarkup:
    warnings: list[str] = []
    clean_source = clean_study_text(source_text)
    source_spans = resolve_source_spans(clean_source, card)
    source_html = render_highlighted_text(clean_source, source_spans) if source_spans else ""
    if clean_source and not source_spans:
        warnings.append("source_target_unresolved")

    examples = split_transfer_examples(*list(example_values), limit=3)
    example_items: list[str] = []
    unresolved_examples = 0
    for example in examples:
        spans = resolve_example_spans(example, card)
        if not spans:
            unresolved_examples += 1
        example_items.append("<li>" + render_highlighted_text(example, spans) + "</li>")
    if unresolved_examples:
        warnings.append(f"example_target_unresolved:{unresolved_examples}")
    example_items_html = (
        '<ul class="v11-example-list">' + "".join(example_items) + "</ul>" if example_items else ""
    )
    return CardPresentationMarkup(
        source_html=source_html,
        meaning_html=render_target_display(meaning_text, card),
        answer_note_html=render_target_display(answer_note_text, card),
        pronunciation_note_html=render_target_display(pronunciation_note_text, card),
        source_translation_html=render_target_display(source_translation_text, card),
        usage_html=render_target_display(usage_text, card),
        misuse_html=render_target_display(misuse_text, card),
        example_items_html=example_items_html,
        warnings=tuple(warnings),
    )
