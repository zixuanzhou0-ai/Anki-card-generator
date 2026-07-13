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
                "lp-filtered": "needs_review",
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
            {"skipped": 1, "model_missing": 0, "hard_failed": 1, "filtered": 0, "needs_review": 1},
        )

    def test_reliability_manifest_accounts_for_every_selected_point(self):
        from acg import card_reliability

        selected = [{"id": "lp-good"}, {"id": "lp-fallback"}, {"id": "lp-unknown"}]
        review_segments = [
            {
                "id": "seg-good",
                "learning_point_id": "lp-good",
                "cards": [self._card("lp-good", id="card-good")],
            },
            {
                "id": "seg-fallback",
                "learning_point_id": "lp-fallback",
                "cards": [
                    self._card(
                        "lp-fallback",
                        id="card-fallback",
                        enabled=False,
                        generation_source="fallback_from_selected_learning_point",
                        quality={"status": "needs_review", "issues": ["系统保底生成，需人工复核。"]},
                    )
                ],
            },
        ]
        manifest = card_reliability.build_reliability_manifest(
            selected,
            review_segments,
            [review_segments[0]],
            model_missing_segment_ids={"seg-fallback"},
            source_fingerprint="source-1",
            model_provider="test",
            model_name="model",
        )

        self.assertTrue(manifest["accounting_complete"])
        self.assertEqual(manifest["decision"], "block")
        self.assertEqual(manifest["selected_point_count"], 3)
        self.assertEqual(manifest["verified_count"], 1)
        self.assertEqual(manifest["needs_review_count"], 1)
        self.assertEqual(manifest["hard_failed_count"], 1)
        self.assertEqual(
            {item["learning_point_id"]: item["status"] for item in manifest["selected_point_outcomes"]},
            {"lp-good": "verified", "lp-fallback": "needs_review", "lp-unknown": "hard_failed"},
        )
        fallback = next(
            item for item in manifest["selected_point_outcomes"] if item["learning_point_id"] == "lp-fallback"
        )
        self.assertIn("FALLBACK_CARD_REQUIRES_REVIEW", fallback["blocker_codes"])
        self.assertIn("MODEL_RESULT_MISSING", fallback["blocker_codes"])

    def test_diagnostics_keep_review_draft_distinct_from_hard_failure(self):
        from acg import card_generation_diagnostics as diagnostics

        items = diagnostics.card_generation_diagnostic_items(
            [{"id": "lp-review", "answer_core": "get it over with"}],
            [{"id": "seg-review", "learning_point_id": "lp-review"}],
            [
                {
                    "id": "seg-review",
                    "learning_point_id": "lp-review",
                    "cards": [self._card("lp-review", enabled=False, quality={"status": "needs_review", "issues": []})],
                }
            ],
            [],
            {"seg-review"},
        )
        self.assertEqual(items[0]["status"], "needs_review")

    def test_reliability_manifest_fails_closed_on_truncated_source_evidence(self):
        from acg import card_reliability

        truncated = (
            "And the proverb, “Don’t judge a book by its cover” advises people "
            "not to form opinions about people based"
        )
        review_segment = {
            "id": "seg-truncated",
            "learning_point_id": "lp-truncated",
            "cards": [
                self._card(
                    "lp-truncated",
                    id="card-truncated",
                    english=truncated,
                    phrase="form opinions about",
                    answer_core="form opinions about",
                )
            ],
        }
        manifest = card_reliability.build_reliability_manifest(
            [{"id": "lp-truncated"}],
            [review_segment],
            [review_segment],
        )
        project = {"reliability_manifest": manifest, "segments": [review_segment]}

        self.assertEqual(manifest["decision"], "block")
        self.assertEqual(manifest["verified_count"], 0)
        self.assertEqual(manifest["needs_review_count"], 1)
        self.assertIn(
            "SOURCE_EVIDENCE_UNRELIABLE",
            manifest["selected_point_outcomes"][0]["blocker_codes"],
        )
        self.assertIn(
            "SOURCE_EVIDENCE_UNRELIABLE",
            card_reliability.export_reliability_blockers(project),
        )

    def test_export_command_fails_closed_on_blocked_reliability_manifest(self):
        from acg import card_reliability

        review_segment = {
            "id": "seg-fallback",
            "learning_point_id": "lp-fallback",
            "cards": [
                self._card(
                    "lp-fallback",
                    id="card-fallback",
                    enabled=False,
                    generation_source="fallback_from_selected_learning_point",
                    quality={"status": "needs_review", "issues": ["系统保底生成，需人工复核。"]},
                )
            ],
        }
        manifest = card_reliability.build_reliability_manifest(
            [{"id": "lp-fallback"}],
            [review_segment],
            [],
        )
        project = {"reliability_manifest": manifest, "segments": [review_segment]}

        self.assertIn("RELIABILITY_GATE_NOT_PASSED", card_reliability.export_reliability_blockers(project))
        with self.assertRaises(SystemExit):
            worker.COMMANDS["export"]({"project": project})

if __name__ == "__main__":
    unittest.main()
