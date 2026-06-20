import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = ROOT / "workers" / "anki_worker.py"


def load_worker():
    spec = importlib.util.spec_from_file_location("anki_worker_for_phrase_discovery_tests", WORKER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


worker = load_worker()


class PhraseDiscoveryBoundaryTests(unittest.TestCase):
    def test_phrase_pool_and_normalization_match_legacy_wrappers(self):
        from acg import phrase_discovery

        legacy = worker._legacy_worker
        pool_samples = [
            ("A1", None),
            ("B2", None),
            ("C1", ["A2", "B2", "A2"]),
            ("unknown", None),
        ]
        normalize_samples = [
            "  kind of... ",
            "“such a big”",
            "feel   like",
            "",
            None,
        ]

        for level, collection_levels in pool_samples:
            with self.subTest(level=level, collection_levels=collection_levels):
                self.assertEqual(
                    phrase_discovery.phrase_pool(level, collection_levels),
                    legacy.phrase_pool(level, collection_levels),
                )

        for value in normalize_samples:
            with self.subTest(value=value):
                self.assertEqual(
                    phrase_discovery.normalize_phrase_candidate(value),
                    legacy.normalize_phrase_candidate(value),
                )

    def test_discovery_phrase_structure_helpers_match_legacy_wrappers(self):
        from acg import phrase_discovery

        legacy = worker._legacy_worker
        word_samples = [
            ["go", "through", "this"],
            ["come", "up"],
            ["very", "very"],
            ["such", "a", "big"],
            [],
        ]
        phrase_samples = [
            "go through",
            "go through this",
            "such a big",
            "very very",
            "because",
            "as small as possible",
            "key expression",
        ]

        for words in word_samples:
            with self.subTest(words=words):
                self.assertEqual(
                    phrase_discovery.has_adjacent_duplicate_words(words),
                    legacy.has_adjacent_duplicate_words(words),
                )
                self.assertEqual(
                    phrase_discovery.trim_discovery_phrase_words(words),
                    legacy.trim_discovery_phrase_words(words),
                )
                if words:
                    self.assertEqual(
                        phrase_discovery.discovery_ngram_has_signal(words),
                        legacy.discovery_ngram_has_signal(words),
                    )

        for phrase in phrase_samples:
            with self.subTest(phrase=phrase):
                self.assertEqual(
                    phrase_discovery.structurally_safe_discovery_phrase(phrase),
                    legacy.structurally_safe_discovery_phrase(phrase),
                )

    def test_candidate_discovery_and_fallback_match_legacy_wrappers(self):
        from acg import phrase_discovery

        legacy = worker._legacy_worker
        text_samples = [
            "It feels like we are going through the same thing over time.",
            "I have no idea what happens next, but at least we can figure it out.",
            "This is such a big deal and more than just a quick fix.",
            "AI model price can we figure",
            "",
        ]
        find_samples = [
            ("Could you figure this out before tomorrow?", "B1", None),
            ("I am not really in the mood for another meeting.", "B2", ["A2", "B2"]),
            ("AI model price can we figure", "C1", None),
            ("", "B1", None),
        ]

        for text in text_samples:
            with self.subTest(text=text):
                self.assertEqual(
                    phrase_discovery.candidate_phrases_from_text(text),
                    legacy.candidate_phrases_from_text(text),
                )

        for text, level, collection_levels in find_samples:
            with self.subTest(text=text, level=level, collection_levels=collection_levels):
                self.assertEqual(
                    phrase_discovery.find_phrase(text, level, collection_levels),
                    legacy.find_phrase(text, level, collection_levels),
                )

    def test_phrase_usability_helpers_match_legacy_wrappers(self):
        from acg import phrase_discovery

        legacy = worker._legacy_worker
        phrase_samples = [
            "welcome back to the channel",
            "key expression",
            "kind of",
            "in the mood for",
            "what do you think about",
            "learn english",
            "",
        ]
        usable_samples = [
            ("I am not really in the mood for another meeting.", "in the mood for"),
            ("Could you figure this out before tomorrow?", "figure this out"),
            ("Welcome back to the channel and today we will learn English.", "welcome back to the channel"),
            ("I want to talk about this in detail.", "talk about"),
            ("The whole sentence should not be a phrase.", "the whole sentence should not be"),
        ]
        choose_samples = [
            (
                "I am not really in the mood for another meeting.",
                "in the mood for",
                "another meeting",
                "B2",
                ["A2", "B2"],
            ),
            (
                "Could you figure this out before tomorrow?",
                "key expression",
                "figure this out",
                "B1",
                None,
            ),
            (
                "Welcome back to the channel and today we will learn English.",
                "welcome back to the channel",
                "learn english",
                "B1",
                None,
            ),
        ]

        for phrase in phrase_samples:
            with self.subTest(phrase=phrase):
                self.assertEqual(
                    phrase_discovery.is_non_transferable_phrase(phrase),
                    legacy.is_non_transferable_phrase(phrase),
                )
                self.assertEqual(
                    phrase_discovery.is_low_value_standalone_phrase(phrase),
                    legacy.is_low_value_standalone_phrase(phrase),
                )

        for text, phrase in usable_samples:
            with self.subTest(text=text, phrase=phrase):
                self.assertEqual(
                    phrase_discovery.usable_phrase(text, phrase),
                    legacy.usable_phrase(text, phrase),
                )

        for text, proposed, fallback, level, collection_levels in choose_samples:
            with self.subTest(text=text, proposed=proposed, fallback=fallback, level=level):
                self.assertEqual(
                    phrase_discovery.choose_best_phrase(text, proposed, fallback, level, collection_levels),
                    legacy.choose_best_phrase(text, proposed, fallback, level, collection_levels),
                )


if __name__ == "__main__":
    unittest.main()
