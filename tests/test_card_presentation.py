from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
WORKERS = ROOT / "workers"
if str(WORKERS) not in sys.path:
    sys.path.insert(0, str(WORKERS))

from acg.presentation import (  # noqa: E402
    HighlightSpan,
    build_card_presentation,
    render_highlighted_text,
    resolve_example_spans,
    resolve_source_spans,
    split_transfer_examples,
)


def test_source_prefers_verified_offsets_for_repeated_target() -> None:
    text = "Common sense matters; common sense can be learned."
    start = text.index("common sense")
    card = {
        "exact_span": "common sense",
        "exact_span_start": start,
        "exact_span_end": start + len("common sense"),
    }

    spans = resolve_source_spans(text, card)

    assert [(span.start, span.end, span.source) for span in spans] == [
        (start, start + len("common sense"), "exact_span")
    ]


def test_invalid_or_ambiguous_source_offsets_do_not_guess() -> None:
    text = "common sense and common sense"
    card = {
        "exact_span": "common sense",
        "exact_span_start": 99,
        "exact_span_end": 111,
    }

    assert resolve_source_spans(text, card) == []


def test_example_highlights_all_exact_occurrences_case_insensitively() -> None:
    spans = resolve_example_spans(
        "Common sense is useful; common sense is learned.",
        {"answer_core": "common sense"},
    )

    assert len(spans) == 2
    assert all(span.source == "exact_match" for span in spans)


def test_grammar_pattern_requires_all_ordered_anchors() -> None:
    spans = resolve_example_spans(
        "She not only listened but also took careful notes.",
        {"answer_core": "not only ... but also"},
    )

    assert [span.text for span in spans] == ["not only", "but also"]
    assert (
        resolve_example_spans(
            "She listened carefully but also took notes.",
            {"answer_core": "not only ... but also"},
        )
        == []
    )


def test_unicode_apostrophe_and_dash_are_preserved() -> None:
    text = "Don\u2019t guess\u2014use common sense."
    start = text.index("common sense")
    spans = resolve_source_spans(
        text,
        {
            "exact_span": "common sense",
            "exact_span_start": start,
            "exact_span_end": start + len("common sense"),
        },
    )

    assert render_highlighted_text(text, spans).startswith("Don\u2019t guess\u2014use ")


def test_example_matches_straight_and_curly_apostrophes_without_fuzzy_guessing() -> (
    None
):
    spans = resolve_example_spans(
        "Don\u2019t give up when the task is hard.",
        {"answer_core": "don't give up"},
    )

    assert [span.text for span in spans] == ["Don\u2019t give up"]
    assert all(span.source == "exact_match" for span in spans)


def test_renderer_escapes_untrusted_html_and_rejects_overlap() -> None:
    text = '<script>alert("x")</script> common sense'
    start = text.index("common sense")
    safe = render_highlighted_text(
        text,
        [
            HighlightSpan(
                start, start + len("common sense"), "common sense", "exact_match"
            )
        ],
    )

    assert "<script>" not in safe
    assert "&lt;script&gt;" in safe
    assert safe.endswith('<mark class="target-expression">common sense</mark>')
    assert "<mark" not in render_highlighted_text(
        "abcdef",
        [
            HighlightSpan(0, 4, "abcd", "exact_match"),
            HighlightSpan(2, 6, "cdef", "exact_match"),
        ],
    )


def test_transfer_examples_split_only_explicit_delimiters_and_dedupe() -> None:
    items = split_transfer_examples(
        "Use common sense. / Use common sense.\nKeep the door locked；and/or stay nearby",
        limit=3,
    )

    assert items == ["Use common sense.", "Keep the door locked", "and/or stay nearby"]


def test_presentation_keeps_plain_fallback_and_reports_unresolved_targets() -> None:
    presentation = build_card_presentation(
        {"answer_core": "missing target", "exact_span": "missing target"},
        source_text="A safe original sentence.",
        example_values=["A separate safe example. / Another example."],
    )

    assert presentation.source_html == ""
    assert presentation.example_items_html == (
        '<ul class="v11-example-list"><li>A separate safe example.</li><li>Another example.</li></ul>'
    )
    assert presentation.warnings == (
        "source_target_unresolved",
        "example_target_unresolved:2",
    )


def test_presentation_highlights_verified_target_across_back_sections() -> None:
    presentation = build_card_presentation(
        {"answer_core": "in good shape", "exact_span": "in good shape"},
        source_text="The laptop is still in good shape.",
        meaning_text="in good shape 表示状态良好。",
        answer_note_text="口语里常用 in good shape。",
        pronunciation_note_text="连读 in good shape 时保持重音。",
        source_translation_text="这台电脑仍然 in good shape。",
        usage_text="健身后可以说 I'm finally in good shape again.",
        misuse_text="<img src=x onerror=alert(1)> 不要把 in good shape 只理解成身材好。",
        example_values=[
            "She's in good shape after training. / The apartment is in good shape."
        ],
    )

    display_fields = (
        presentation.source_html,
        presentation.meaning_html,
        presentation.answer_note_html,
        presentation.pronunciation_note_html,
        presentation.source_translation_html,
        presentation.usage_html,
        presentation.misuse_html,
    )
    assert all(
        '<mark class="target-expression">in good shape</mark>' in value
        for value in display_fields
    )
    assert "<img" not in presentation.misuse_html
    assert "&lt;img" in presentation.misuse_html
    assert (
        presentation.example_items_html.count(
            '<mark class="target-expression">in good shape</mark>'
        )
        == 2
    )
