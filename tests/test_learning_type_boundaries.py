import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = ROOT / "workers" / "anki_worker.py"


def load_worker():
    spec = importlib.util.spec_from_file_location("anki_worker_for_learning_type_tests", WORKER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


worker = load_worker()


class LearningTypeBoundaryTests(unittest.TestCase):
    def test_card_label_helpers_match_legacy_wrappers(self):
        from acg import learning_types

        legacy = worker._legacy_worker
        phrase_type_samples = ["spoken_phrase", "listening_sentence", "vocabulary_usage", "unknown", "", None]
        learning_card_samples = [
            ("spoken_phrase", "phrase"),
            ("listening_sentence", "phrase"),
            ("unknown", "vocabulary"),
            ("unknown", "listening"),
            ("unknown", "phrase"),
            ("", ""),
        ]

        for value in phrase_type_samples:
            with self.subTest(phrase_type=value):
                self.assertEqual(
                    learning_types.card_label_for_phrase_type(value, "fallback"),
                    legacy.card_label_for_phrase_type(value, "fallback"),
                )

        for phrase_type, content_kind in learning_card_samples:
            with self.subTest(phrase_type=phrase_type, content_kind=content_kind):
                self.assertEqual(
                    learning_types.card_label_for_learning_card(phrase_type, content_kind, "fallback"),
                    legacy.card_label_for_learning_card(phrase_type, content_kind, "fallback"),
                )

    def test_learning_card_label_is_unified_for_all_content_kinds(self):
        from acg import learning_types

        samples = [
            ("spoken_phrase", "phrase"),
            ("vocabulary_usage", "vocabulary"),
            ("listening_sentence", "listening"),
            ("grammar_pattern", "grammar"),
            ("unknown", "phrase"),
        ]

        for phrase_type, content_kind in samples:
            with self.subTest(phrase_type=phrase_type, content_kind=content_kind):
                self.assertEqual(
                    learning_types.card_label_for_learning_card(phrase_type, content_kind, "fallback"),
                    "学习卡",
                )
    def test_content_kind_for_phrase_type_matches_legacy_wrapper(self):
        from acg import learning_types

        legacy = worker._legacy_worker
        samples = ["spoken_phrase", "sentence_frame", "vocabulary_usage", "listening_sentence", "unknown", "", None]

        for value in samples:
            with self.subTest(value=value):
                self.assertEqual(
                    learning_types.content_kind_for_phrase_type(value, "fallback"),
                    legacy.content_kind_for_phrase_type(value, "fallback"),
                )

    def test_candidate_kind_for_phrase_type_matches_legacy_wrapper(self):
        from acg import learning_types

        legacy = worker._legacy_worker
        samples = ["spoken_phrase", "grammar_pattern", "vocabulary_usage", "listening_sentence", "unknown", "", None]

        for value in samples:
            with self.subTest(value=value):
                self.assertEqual(
                    learning_types.candidate_kind_for_phrase_type(value, "fallback"),
                    legacy.candidate_kind_for_phrase_type(value, "fallback"),
                )

    def test_phrase_type_for_candidate_kind_matches_legacy_wrapper(self):
        from acg import learning_types

        legacy = worker._legacy_worker
        samples = ["expression", "contextual_vocab", "grammar_pattern", "listening_feature", "pragmatic_risk", "", None]

        for value in samples:
            with self.subTest(value=value):
                self.assertEqual(
                    learning_types.phrase_type_for_candidate_kind(value, "fallback"),
                    legacy.phrase_type_for_candidate_kind(value, "fallback"),
                )

    def test_candidate_kind_for_segment_matches_legacy_wrapper(self):
        from acg import learning_types

        legacy = worker._legacy_worker
        samples = [
            {"candidate_kind": "custom_kind", "content_kind": "vocabulary", "phrase_type": "spoken_phrase"},
            {"content_kind": "vocabulary"},
            {"content_kind": "grammar"},
            {"content_kind": "listening"},
            {"phrase_type": "vocabulary_usage"},
            {"phrase_type": "unknown"},
            {},
        ]

        for value in samples:
            with self.subTest(value=value):
                self.assertEqual(
                    learning_types.candidate_kind_for_segment(value),
                    legacy.candidate_kind_for_segment(value),
                )

    def test_normalizers_match_legacy_wrappers(self):
        from acg import learning_types

        legacy = worker._legacy_worker
        candidate_samples = ["expression", "contextual_vocab", "unknown", "", None]
        phrase_samples = [
            ("spoken_phrase", "expression"),
            ("vocabulary_usage", "expression"),
            ("unknown", "contextual_vocab"),
            ("", "grammar_pattern"),
            (None, "listening_feature"),
        ]

        for value in candidate_samples:
            with self.subTest(candidate_kind=value):
                self.assertEqual(
                    learning_types.normalize_candidate_kind(value, "fallback"),
                    legacy.normalize_candidate_kind(value, "fallback"),
                )

        for value, candidate_kind in phrase_samples:
            with self.subTest(phrase_type=value, candidate_kind=candidate_kind):
                self.assertEqual(
                    learning_types.normalize_phrase_type(value, candidate_kind),
                    legacy.normalize_phrase_type(value, candidate_kind),
                )

    def test_candidate_kind_allowed_by_focus_matches_legacy_wrapper(self):
        from acg import learning_types

        legacy = worker._legacy_worker
        payloads = [
            {},
            {"language_focus": ["phrases"]},
            {"language_focus": ["vocabulary"]},
            {"language_focus": ["listening"]},
            {"language_focus": ["grammar"]},
            {"language_focus": ["phrases", "grammar"]},
            {"language_focus": ["unknown"]},
        ]
        kinds = [
            "expression",
            "pragmatic_risk",
            "contextual_vocab",
            "listening_feature",
            "grammar_pattern",
            "unknown_kind",
        ]

        for payload in payloads:
            for kind in kinds:
                with self.subTest(payload=payload, kind=kind):
                    self.assertEqual(
                        learning_types.candidate_kind_allowed_by_focus(kind, payload),
                        legacy.candidate_kind_allowed_by_focus(kind, payload),
                    )

    def test_learning_action_key_for_contract_matches_legacy_wrapper(self):
        from acg import learning_types

        legacy = worker._legacy_worker
        samples = [
            {
                "candidate_kind": "expression",
                "normalized_answer": "turn it around",
                "learning_action": "Train the expression in this sentence.",
            },
            {
                "kind": "grammar_pattern",
                "answer_core": "the more, the more",
                "phrase_card_focus": "Notice the comparison frame.",
            },
            {
                "candidate_kind": "contextual_vocab",
                "exact_span": "tangible",
                "card_focus": "Use this word in context.",
            },
            {
                "candidate_kind": "unknown_kind",
                "phrase": "kind of",
                "reason": "Natural spoken softener.",
            },
            {},
        ]

        for item in samples:
            with self.subTest(item=item):
                self.assertEqual(
                    learning_types.learning_action_key_for_contract(item),
                    legacy.learning_action_key_for_contract(item),
                )


if __name__ == "__main__":
    unittest.main()
