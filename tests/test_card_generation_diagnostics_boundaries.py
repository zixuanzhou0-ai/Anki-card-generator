import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = ROOT / "workers" / "anki_worker.py"


def load_worker():
    spec = importlib.util.spec_from_file_location("anki_worker_for_card_generation_diagnostics_tests", WORKER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


worker = load_worker()


class CardGenerationDiagnosticsBoundaryTests(unittest.TestCase):
    def _card(self, learning_point_id="lp-1", **overrides):
        card = {
            "enabled": True,
            "learning_point_id": learning_point_id,
            "quality": {"status": "recommended", "issues": []},
            "chinese": "自然中文意思",
            "definition": "A useful meaning for export.",
            "teacher_note": "Review this expression in context.",
            "why": "It appears in the source sentence.",
            "context": "Can you run the register for a minute?",
        }
        card.update(overrides)
        return card

    def test_generated_card_helpers_ignore_disabled_rejected_and_export_blocked_cards(self):
        from acg import card_generation_diagnostics as diagnostics

        segments = [
            {"learning_point_id": "lp-from-segment", "cards": [self._card("")]},
            {"learning_point_id": "lp-segment", "cards": [self._card("lp-from-card")]},
            {"learning_point_id": "lp-disabled", "cards": [self._card("lp-disabled", enabled=False)]},
            {
                "learning_point_id": "lp-rejected",
                "cards": [self._card("lp-rejected", quality={"status": "reject", "issues": []})],
            },
            {
                "learning_point_id": "lp-blocked",
                "cards": [self._card("lp-blocked", quality={"status": "recommended", "issues": ["缺少中文意思"]})],
            },
            {"learning_point_id": "lp-no-card", "cards": ["not-a-card"]},
        ]

        self.assertEqual(diagnostics.generated_card_count_from_segments(segments), 2)
        self.assertEqual(
            diagnostics.generated_learning_point_ids_from_project({"segments": segments}),
            {"lp-from-segment", "lp-from-card"},
        )
        self.assertTrue(diagnostics.segment_has_generated_learning_point_card(segments[0]))
        self.assertFalse(diagnostics.segment_has_generated_learning_point_card(segments[2]))
        self.assertFalse(diagnostics.card_counts_as_generated(segments[4]["cards"][0]))

    def test_diagnostic_items_report_skipped_model_missing_and_filtered_points(self):
        from acg import card_generation_diagnostics as diagnostics

        selected_points = [
            {"id": "lp-ok", "answer_core": "run the register"},
            {"id": "lp-skipped", "answer_core": "ring up"},
            {"id": "lp-missing", "answer_core": "cash out"},
            {"id": "lp-filtered", "exact_span": "close up shop"},
        ]
        eligible_segments = [
            {"id": "seg-ok", "learning_point_id": "lp-ok"},
            {"id": "seg-missing", "learning_point_id": "lp-missing"},
            {"id": "seg-filtered", "learning_point_id": "lp-filtered"},
        ]
        pre_filter_segments = [
            {
                "id": "seg-filtered",
                "learning_point_id": "lp-filtered",
                "cards": [
                    self._card(
                        "lp-filtered",
                        quality={
                            "status": "recommended",
                            "issues": ["缺少中文意思", "缺少释义", "缺少中文意思"],
                        },
                    )
                ],
            }
        ]
        output_segments = [
            {"id": "seg-ok", "learning_point_id": "lp-ok", "cards": [self._card("lp-ok")]}
        ]

        items = diagnostics.card_generation_diagnostic_items(
            selected_points,
            eligible_segments,
            pre_filter_segments,
            output_segments,
            {"seg-missing"},
        )

        self.assertEqual(
            {item["learning_point_id"]: item["status"] for item in items},
            {
                "lp-skipped": "skipped",
                "lp-missing": "hard_failed",
                "lp-filtered": "filtered",
            },
        )
        self.assertEqual(
            {item["learning_point_id"]: item["answer_core"] for item in items},
            {
                "lp-skipped": "ring up",
                "lp-missing": "cash out",
                "lp-filtered": "close up shop",
            },
        )
        self.assertIn("缺少中文意思；缺少释义", [item["reason"] for item in items])
        self.assertEqual(
            diagnostics.card_generation_diagnostic_counts(items),
            {"skipped": 1, "model_missing": 0, "hard_failed": 1, "filtered": 1},
        )


if __name__ == "__main__":
    unittest.main()
