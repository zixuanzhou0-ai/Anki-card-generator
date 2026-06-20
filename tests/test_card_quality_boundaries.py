import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = ROOT / "workers" / "anki_worker.py"


def load_worker():
    spec = importlib.util.spec_from_file_location("anki_worker_for_card_quality_tests", WORKER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


worker = load_worker()


class CardQualityBoundaryTests(unittest.TestCase):
    def test_generic_and_template_quality_helpers_match_legacy_wrappers(self):
        from acg import card_quality

        legacy = worker._legacy_worker
        samples = [
            "This phrase is useful in daily English.",
            "这个表达很常见",
            "真实口语常用。",
            "Use it in daily English.",
            "Train a specific contrast in this sentence.",
            "",
            None,
        ]

        for value in samples:
            with self.subTest(value=value):
                self.assertEqual(card_quality.has_generic_definition(value), legacy.has_generic_definition(value))
                self.assertEqual(card_quality.has_generic_teacher_note(value), legacy.has_generic_teacher_note(value))
                self.assertEqual(card_quality.has_template_noise(value), legacy.has_template_noise(value))
                self.assertEqual(card_quality.is_specific_study_text(value), legacy.is_specific_study_text(value))

    def test_action_text_and_level_helpers_match_legacy_wrappers(self):
        from acg import card_quality

        legacy = worker._legacy_worker
        action_samples = [
            ["train phrase", "", "notice tone"],
            {"why": "contrast", "empty": ""},
            " plain text ",
            None,
        ]
        level_samples = ["A1", "B1", "C2", "around b2", "unknown", ""]
        basic_samples = [
            ("go", "A2"),
            ("go", "B1"),
            ("thank you", "C1"),
            ("in the mood for", "B2"),
        ]

        for value in action_samples:
            with self.subTest(action=value):
                self.assertEqual(card_quality.normalized_action_text(value), legacy.normalized_action_text(value))

        for value in level_samples:
            with self.subTest(level=value):
                self.assertEqual(card_quality.cefr_rank(value), legacy.cefr_rank(value))

        for phrase, level in basic_samples:
            with self.subTest(phrase=phrase, level=level):
                self.assertEqual(
                    card_quality.is_too_basic_for_level(phrase, level),
                    legacy.is_too_basic_for_level(phrase, level),
                )

    def test_answer_key_and_phrase_guide_key_match_legacy_wrappers(self):
        from acg import card_quality

        legacy = worker._legacy_worker
        samples = [" what do you? ", "“kind of”", "in   the mood for", "", None]

        for value in samples:
            with self.subTest(value=value):
                self.assertEqual(card_quality.normalized_answer_key(value), legacy.normalized_answer_key(value))
                self.assertEqual(card_quality.phrase_guide_key(value), legacy.phrase_guide_key(value))

    def test_function_and_preposition_allow_lists_match_legacy_wrappers(self):
        from acg import card_quality

        legacy = worker._legacy_worker
        samples = [
            "what do you think about",
            "tell me about",
            "in the mood for",
            "because",
            "worked out of",
            "",
        ]

        for value in samples:
            with self.subTest(value=value):
                self.assertEqual(
                    card_quality.allows_function_start_phrase(value),
                    legacy.allows_function_start_phrase(value),
                )
                self.assertEqual(
                    card_quality.phrase_allows_trailing_preposition(value),
                    legacy.phrase_allows_trailing_preposition(value),
                )

    def test_incomplete_answer_fragment_matches_legacy_wrapper(self):
        from acg import card_quality

        legacy = worker._legacy_worker
        samples = [
            ("what do you", {"language_code": "en", "candidate_kind": "expression"}),
            ("what do you think about", {"language_code": "en", "candidate_kind": "expression"}),
            ("because", {"language_code": "en", "candidate_kind": "expression"}),
            ("because", {"language_code": "fr", "candidate_kind": "expression"}),
            ("what do you", {"language_code": "en", "candidate_kind": "contextual_vocab"}),
            ("in the mood for", {"language_code": "en", "candidate_kind": "expression"}),
            ("", {"language_code": "en", "candidate_kind": "expression"}),
        ]

        for value, card in samples:
            with self.subTest(value=value, card=card):
                self.assertEqual(
                    card_quality.looks_like_incomplete_answer_fragment(value, card),
                    legacy.looks_like_incomplete_answer_fragment(value, card),
                )

    def test_truncated_listening_answer_matches_legacy_wrapper(self):
        from acg import card_quality

        legacy = worker._legacy_worker
        source_text = "Where did you go after the meeting and what did you say?"
        samples = [
            "where did you",
            "what did you",
            "go after",
            "in the mood for",
            "",
        ]

        for value in samples:
            with self.subTest(value=value):
                self.assertEqual(
                    card_quality.looks_like_truncated_listening_answer(value, source_text),
                    legacy.looks_like_truncated_listening_answer(value, source_text),
                )


if __name__ == "__main__":
    unittest.main()
