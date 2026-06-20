import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = ROOT / "workers" / "anki_worker.py"


def load_worker():
    spec = importlib.util.spec_from_file_location("anki_worker_for_learning_span_tests", WORKER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


worker = load_worker()


class LearningSpanBoundaryTests(unittest.TestCase):
    def test_normalize_candidate_span_matches_legacy_wrapper(self):
        from acg import learning_spans

        legacy = worker._legacy_worker
        samples = [
            '  "blend together,"  ',
            "“The more”",
            "you're feeling completely lost?!",
            "",
        ]

        for value in samples:
            with self.subTest(value=value):
                self.assertEqual(learning_spans.normalize_candidate_span(value), legacy.normalize_candidate_span(value))

    def test_normalized_phrase_key_matches_legacy_wrapper(self):
        from acg import learning_spans

        legacy = worker._legacy_worker
        samples = [
            "  Run   The Register  ",
            "you're feeling completely lost",
            "The more, the more",
            "",
            None,
        ]

        for value in samples:
            with self.subTest(value=value):
                self.assertEqual(learning_spans.normalized_phrase_key(value), legacy.normalized_phrase_key(value))

    def test_expression_span_from_text_matches_legacy_wrapper(self):
        from acg import learning_spans

        legacy = worker._legacy_worker
        text = "The more you live in English, the faster your brain rewires itself."
        patterns = [
            r"\bthe\s+more\b.+?\bthe\s+faster\b",
            r"\bbrain\s+rewires\s+itself\b",
            r"\bnot\s+present\b",
        ]

        for pattern in patterns:
            with self.subTest(pattern=pattern):
                self.assertEqual(
                    learning_spans.expression_span_from_text(text, pattern),
                    legacy.expression_span_from_text(text, pattern),
                )

    def test_exact_span_offsets_matches_legacy_wrapper(self):
        from acg import learning_spans

        legacy = worker._legacy_worker
        samples = [
            (
                "They speak so quickly words blend together, and suddenly you're feeling completely lost.",
                "blend together",
            ),
            (
                "The more you live in English,\n the faster your brain rewires itself.",
                "live in English, the faster",
            ),
            (
                "The more you live in English, the faster your brain rewires itself.",
                "not present",
            ),
            ("", "blend together"),
        ]

        for text, span in samples:
            with self.subTest(span=span):
                self.assertEqual(learning_spans.exact_span_offsets(text, span), legacy.exact_span_offsets(text, span))

    def test_phrase_in_text_matches_legacy_wrapper(self):
        from acg import learning_spans

        legacy = worker._legacy_worker
        samples = [
            (
                "They speak so quickly words blend together, and suddenly you're feeling completely lost.",
                "blend together",
            ),
            (
                "I am going to tell you something important.",
                "I'm going to",
            ),
            (
                "This can help you stay focused when the conversation gets fast.",
                "help ... stay focused",
            ),
            (
                "I need you to rewire it before the next conversation.",
                "rewire something",
            ),
            (
                "Can you tell me why this sounds natural?",
                "tell someone why",
            ),
            (
                "The subtitle does not contain that target.",
                "blend together",
            ),
            ("", "blend together"),
            ("They blend together.", ""),
        ]

        for text, phrase in samples:
            with self.subTest(phrase=phrase):
                self.assertEqual(learning_spans.phrase_in_text(text, phrase), legacy.phrase_in_text(text, phrase))


if __name__ == "__main__":
    unittest.main()
