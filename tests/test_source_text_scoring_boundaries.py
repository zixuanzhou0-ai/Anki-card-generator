import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = ROOT / "workers" / "anki_worker.py"


def load_worker():
    spec = importlib.util.spec_from_file_location("anki_worker_for_source_text_scoring_tests", WORKER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


worker = load_worker()


class SourceTextScoringBoundaryTests(unittest.TestCase):
    def test_contains_and_content_allowed_match_legacy_wrappers(self):
        from acg.scoring import source_text

        legacy = worker._legacy_worker
        contains_samples = [
            ("This is kind of useful", ["kind of", "nope"]),
            ("Plain sentence", ["kind of", "nope"]),
            ("", ["kind of"]),
        ]
        content_samples = [
            ("What the hell is going on?", {}),
            ("What the hell is going on?", {"slang": False}),
            ("That sounds romantic.", {"romance": False}),
            ("Plain business meeting.", {"business": True}),
        ]

        for text, patterns in contains_samples:
            with self.subTest(text=text, patterns=patterns):
                self.assertEqual(source_text.contains_any(text, patterns), legacy.contains_any(text, patterns))

        for text, toggles in content_samples:
            with self.subTest(text=text, toggles=toggles):
                self.assertEqual(source_text.content_allowed(text, toggles), legacy.content_allowed(text, toggles))

    def test_video_intro_detection_matches_legacy_wrapper(self):
        from acg.scoring import source_text

        legacy = worker._legacy_worker
        samples = [
            "Welcome back to the channel.",
            "In this video, I am going to show you six things.",
            "I have no idea what happens next.",
            "",
        ]

        for text in samples:
            with self.subTest(text=text):
                self.assertEqual(source_text.looks_like_video_intro(text), legacy.looks_like_video_intro(text))

    def test_score_text_matches_legacy_wrapper(self):
        from acg.scoring import source_text

        legacy = worker._legacy_worker
        samples = [
            ("Could you figure this out before tomorrow?", "B1", {}, None),
            ("I am not really in the mood for another meeting.", "B2", {"slang": True}, ["A2", "B2"]),
            ("[Music] welcome back to the channel", "B1", {}, None),
            (
                "This sentence is intentionally long because it keeps adding words beyond the normal useful subtitle range.",
                "C1",
                {"business": True, "culture": True},
                None,
            ),
        ]

        for text, level, toggles, collection_levels in samples:
            with self.subTest(text=text, level=level, toggles=toggles, collection_levels=collection_levels):
                self.assertEqual(
                    source_text.score_text(text, level, toggles, collection_levels),
                    legacy.score_text(text, level, toggles, collection_levels),
                )


if __name__ == "__main__":
    unittest.main()
