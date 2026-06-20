import copy
import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = ROOT / "workers" / "anki_worker.py"


def load_worker():
    spec = importlib.util.spec_from_file_location("anki_worker_for_review_mode_tests", WORKER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


worker = load_worker()


class ReviewModeBoundaryTests(unittest.TestCase):
    def test_template_style_and_density_helpers_match_legacy_wrappers(self):
        from acg import review_modes

        legacy = worker._legacy_worker
        template_values = ["immersive_v11", "ciba_tianxia_v1", "dictionary", "", None, "unknown"]
        style_values = ["warm_paper", "minimal_white", "dark_immersive", "", None, "unknown"]
        density_values = ["full", "fast", "", None, "deep"]

        for value in template_values:
            with self.subTest(template=value):
                self.assertEqual(review_modes.normalize_template_id(value), legacy.normalize_template_id(value))
        for value in style_values:
            with self.subTest(style=value):
                self.assertEqual(review_modes.normalize_card_style(value), legacy.normalize_card_style(value))
        for value in density_values:
            with self.subTest(density=value):
                self.assertEqual(review_modes.normalize_review_density(value), legacy.normalize_review_density(value))

        payloads = [{"template_id": "ciba_tianxia_v1"}, {"template_id": "immersive_v11"}, {}, None]
        for payload in payloads:
            with self.subTest(payload=payload):
                self.assertEqual(review_modes.ciba_tianxia_mode(payload), legacy.ciba_tianxia_mode(payload))

    def test_fast_review_prompt_and_quality_helpers_match_legacy_wrappers(self):
        from acg import review_modes

        legacy = worker._legacy_worker
        projects = [{"review_density": "fast"}, {"review_density": "full"}, {}, {"review_density": "unknown"}]
        cards = [
            {
                "answer_core": "blend together",
                "english": "The words blend together when people speak quickly.",
                "chinese": "这些词在快语速里连在一起。",
                "definition": "自然连读。",
                "retrieval_prompt": "What happens to the words?",
            },
            {
                "phrase": "outside your bubble",
                "english": "Step outside your bubble and speak more.",
                "teacher_note": "提醒自己走出舒适区。",
                "retrieval_prompt": "What should you step outside of?",
            },
            {"phrase": "", "english": "", "chinese": "", "definition": "", "retrieval_prompt": ""},
        ]

        for project in projects:
            with self.subTest(project=project):
                self.assertEqual(review_modes.fast_review_density(project), legacy.fast_review_density(project))
                self.assertEqual(
                    review_modes.fast_review_prompt_instruction(project),
                    legacy.fast_review_prompt_instruction(project),
                )
        for card in cards:
            with self.subTest(card=card):
                self.assertEqual(
                    review_modes.fast_review_card_quality(card, {"text": card.get("english", "")}),
                    legacy.fast_review_card_quality(card, {"text": card.get("english", "")}),
                )

    def test_fast_review_slimming_helpers_match_legacy_wrappers(self):
        from acg import review_modes

        legacy = worker._legacy_worker
        segment = {
            "text": "The words blend together when people speak quickly.",
            "cards": [
                {
                    "answer_core": "blend together",
                    "english": "The words blend together when people speak quickly.",
                    "chinese": "这些词在快语速里连在一起。",
                    "definition": "自然连读。后面这句应该被截断。",
                    "teacher_note": "听的时候不要逐词拆。后面这句应该被截断。",
                    "how_to_use_it": "Use it when describing connected speech.",
                    "why_it_matters": "It helps listening.",
                    "usage_boundary": "Not a formal grammar term.",
                    "retrieval_prompt": "What happens to the words?",
                }
            ],
        }

        direct_card = review_modes.slim_fast_review_card(copy.deepcopy(segment["cards"][0]), copy.deepcopy(segment))
        legacy_card = legacy.slim_fast_review_card(copy.deepcopy(segment["cards"][0]), copy.deepcopy(segment))
        self.assertEqual(direct_card, legacy_card)

        segments = [copy.deepcopy(segment)]
        direct_segments = review_modes.slim_fast_review_segments(copy.deepcopy(segments), {"review_density": "fast"})
        legacy_segments = legacy.slim_fast_review_segments(copy.deepcopy(segments), {"review_density": "fast"})
        self.assertEqual(direct_segments, legacy_segments)

        unchanged = review_modes.slim_fast_review_segments(copy.deepcopy(segments), {"review_density": "full"})
        self.assertEqual(unchanged, segments)


if __name__ == "__main__":
    unittest.main()
