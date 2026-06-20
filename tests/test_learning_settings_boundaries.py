import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = ROOT / "workers" / "anki_worker.py"


def load_worker():
    spec = importlib.util.spec_from_file_location("anki_worker_for_learning_settings_tests", WORKER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


worker = load_worker()


class LearningSettingsBoundaryTests(unittest.TestCase):
    def test_collection_level_helpers_match_legacy_wrappers(self):
        from acg import learning_settings

        legacy = worker._legacy_worker
        samples = [
            (["C1", "A2", "B2", "A2"], "B2"),
            (["bad", "B1"], "C1"),
            ([], "C1"),
            (None, "B2"),
            ("B1", "B2"),
        ]
        payloads = [
            {"level_mode": "auto", "collection_levels": ["A1"], "level": "C2"},
            {"level_mode": "manual", "collection_levels": ["B2", "A2"]},
            {"level_mode": "bad", "collection_levels": ["C1"]},
        ]

        for value, current_level in samples:
            with self.subTest(value=value, current_level=current_level):
                self.assertEqual(
                    learning_settings.normalize_collection_levels(value, current_level),
                    legacy.normalize_collection_levels(value, current_level),
                )

        for payload in payloads:
            with self.subTest(payload=payload):
                self.assertEqual(learning_settings.normalized_level_mode(payload), legacy.normalized_level_mode(payload))
                self.assertEqual(
                    learning_settings.collection_levels_from_payload(payload, "B2"),
                    legacy.collection_levels_from_payload(payload, "B2"),
                )

    def test_language_focus_helpers_match_legacy_wrappers(self):
        from acg import learning_settings

        legacy = worker._legacy_worker
        samples = [
            {},
            {"language_focus": ["grammar", "phrases", "bad", "grammar"]},
            {"language_focus": []},
            {"language_focus": "phrases"},
        ]

        for payload in samples:
            with self.subTest(payload=payload):
                self.assertEqual(learning_settings.normalized_language_focus(payload), legacy.normalized_language_focus(payload))
                self.assertEqual(
                    learning_settings.normalized_document_reading_focus(payload),
                    legacy.normalized_document_reading_focus(payload),
                )
                self.assertEqual(
                    learning_settings.language_focus_instruction(payload),
                    legacy.language_focus_instruction(payload),
                )

    def test_selection_and_expansion_helpers_match_legacy_wrappers(self):
        from acg import learning_settings

        legacy = worker._legacy_worker
        samples = [
            {},
            {"selection_strategy": "catch_all", "source_expansion_mode": "full", "max_source_expansion_groups": 200},
            {"selection_strategy": "curated", "level_mode": "manual", "collection_levels": ["B2"], "catch_all_expansion": "off"},
            {"selection_strategy": "bad", "source_expansion_mode": "bad", "max_source_expansion_groups": "3"},
            {"max_source_expansion_groups": "bad"},
        ]

        for payload in samples:
            with self.subTest(payload=payload):
                self.assertEqual(learning_settings.normalized_study_depth(payload), legacy.normalized_study_depth(payload))
                self.assertEqual(
                    learning_settings.normalized_selection_strategy(payload),
                    legacy.normalized_selection_strategy(payload),
                )
                self.assertEqual(
                    learning_settings.discovery_collection_levels(payload, "B2"),
                    legacy.discovery_collection_levels(payload, "B2"),
                )
                self.assertEqual(
                    learning_settings.normalized_source_expansion_mode(payload),
                    legacy.normalized_source_expansion_mode(payload),
                )
                self.assertEqual(
                    learning_settings.max_source_expansion_groups(payload),
                    legacy.max_source_expansion_groups(payload),
                )

    def test_fixed_limits_match_legacy_wrappers(self):
        from acg import learning_settings

        legacy = worker._legacy_worker
        payload = {"anything": "ignored"}

        self.assertEqual(learning_settings.selection_candidate_multiplier(payload), legacy.selection_candidate_multiplier(payload))
        self.assertEqual(learning_settings.max_learning_points_per_source(payload), legacy.max_learning_points_per_source(payload))
        self.assertEqual(learning_settings.max_reviewable_cards_per_source(payload), legacy.max_reviewable_cards_per_source(payload))

    def test_learning_point_confidence_matches_legacy_wrapper(self):
        from acg import learning_settings

        legacy = worker._legacy_worker
        samples = [(4.2, "medium"), (3.0, "low"), (2.2, "low"), ("bad", "high"), (None, "invalid")]

        for value, default in samples:
            with self.subTest(value=value, default=default):
                self.assertEqual(
                    learning_settings.learning_point_confidence(value, default),
                    legacy.learning_point_confidence(value, default),
                )


if __name__ == "__main__":
    unittest.main()
