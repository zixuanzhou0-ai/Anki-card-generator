import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = ROOT / "workers" / "anki_worker.py"


def load_worker():
    spec = importlib.util.spec_from_file_location("anki_worker_for_card_planning_tests", WORKER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


worker = load_worker()


class CardPlanningBoundaryTests(unittest.TestCase):
    def test_requested_and_training_value_helpers_match_legacy_wrappers(self):
        from acg import card_planning

        legacy = worker._legacy_worker
        requested_samples = [
            [],
            ["phrase"],
            ["listening", "phrase", "cloze"],
            ["unknown", "phrase"],
        ]
        listening_samples = [
            "I don't know what you're doing, but let's figure this out together right now.",
            "This is a short sentence.",
            "",
        ]
        output_samples = [
            ("figure out", "B1"),
            ("by the way", "B2"),
            ("make sense", "C1"),
            ("talk about", "B2"),
        ]

        for values in requested_samples:
            with self.subTest(values=values):
                self.assertEqual(card_planning.requested_card_types(values), legacy.requested_card_types(values))

        for text in listening_samples:
            with self.subTest(text=text):
                self.assertEqual(
                    card_planning.has_listening_training_value(text),
                    legacy.has_listening_training_value(text),
                )

        for phrase, level in output_samples:
            with self.subTest(phrase=phrase, level=level):
                self.assertEqual(
                    card_planning.has_output_training_value(phrase, level),
                    legacy.has_output_training_value(phrase, level),
                )

    def test_usable_learning_point_span_matches_legacy_wrapper(self):
        from acg import card_planning

        legacy = worker._legacy_worker
        samples = [
            (
                "They speak so quickly words blend together, and suddenly you're feeling completely lost.",
                "blend together",
                "expression",
                "collocation",
            ),
            (
                "This sounds like something you would hear in a real conversation.",
                "something you would hear",
                "grammar_pattern",
                "grammar_pattern",
            ),
            (
                "Welcome back to the channel and today we will learn English.",
                "welcome back to the channel",
                "expression",
                "spoken_phrase",
            ),
            (
                "I don't know what you're doing, but let's figure this out together.",
                "key expression",
                "expression",
                "spoken_phrase",
            ),
        ]

        for text, span, candidate_kind, phrase_type in samples:
            with self.subTest(span=span, candidate_kind=candidate_kind, phrase_type=phrase_type):
                self.assertEqual(
                    card_planning.usable_learning_point_span(text, span, candidate_kind, phrase_type),
                    legacy.usable_learning_point_span(text, span, candidate_kind, phrase_type),
                )

    def test_plan_card_types_matches_legacy_wrapper(self):
        from acg import card_planning

        legacy = worker._legacy_worker
        samples = [
            (
                {
                    "text": "They speak so quickly words blend together, and suddenly you're feeling completely lost.",
                    "phrase": "blend together",
                    "candidate_kind": "expression",
                    "phrase_type": "collocation",
                },
                ["phrase", "listening", "cloze"],
                "B2",
            ),
            (
                {
                    "text": "You're gonna hear the words connect and disappear in natural speech.",
                    "phrase": "gonna hear",
                    "candidate_kind": "listening_feature",
                    "phrase_type": "listening_sentence",
                },
                ["phrase", "listening"],
                "B1",
            ),
            (
                {
                    "text": "The word absolutely changes the feeling of the sentence.",
                    "phrase": "absolutely",
                    "candidate_kind": "contextual_vocab",
                    "phrase_type": "vocabulary_usage",
                },
                ["phrase", "listening", "cloze"],
                "C1",
            ),
        ]

        for segment, card_types, level in samples:
            with self.subTest(segment=segment, card_types=card_types, level=level):
                self.assertEqual(
                    card_planning.plan_card_types(segment, card_types, level),
                    legacy.plan_card_types(segment, card_types, level),
                )

    def test_card_type_for_learning_point_matches_legacy_wrapper(self):
        from acg import card_planning

        legacy = worker._legacy_worker
        samples = [
            ({"kind": "listening_feature", "answer_core": "key expression"}, ["listening", "phrase"]),
            ({"kind": "expression", "suggested_card_type": "cloze", "answer_core": "figure out"}, ["phrase", "cloze"]),
            ({"kind": "contextual_vocab", "answer_core": "absolutely"}, ["phrase", "listening"]),
            ({}, ["cloze", "listening"]),
        ]

        for point, requested in samples:
            with self.subTest(point=point, requested=requested):
                self.assertEqual(
                    card_planning.card_type_for_learning_point(point, requested),
                    legacy.card_type_for_learning_point(point, requested),
                )


if __name__ == "__main__":
    unittest.main()
