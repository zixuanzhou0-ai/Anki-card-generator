import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = ROOT / "workers" / "anki_worker.py"


def load_worker():
    spec = importlib.util.spec_from_file_location("anki_worker_for_generation_timing_tests", WORKER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


worker = load_worker()


class GenerationTimingBoundaryTests(unittest.TestCase):
    def test_add_generation_timing_aliases_populates_release_report_keys(self):
        from acg.generation_timing import add_generation_timing_aliases

        timing = {
            "source_prepare": 11,
            "card_model": 22,
            "field_merge": 33,
            "total": 44,
        }

        self.assertIs(add_generation_timing_aliases(timing), timing)
        self.assertEqual(
            timing,
            {
                "source_prepare": 11,
                "card_model": 22,
                "field_merge": 33,
                "total": 44,
                "source_prepare_ms": 11,
                "card_body_ms": 22,
                "field_merge_ms": 33,
                "total_ms": 44,
            },
        )

    def test_add_generation_timing_aliases_preserves_existing_aliases(self):
        from acg.generation_timing import add_generation_timing_aliases

        timing = {
            "source_prepare": 11,
            "card_model": 22,
            "source_prepare_ms": 999,
            "card_body_ms": 888,
        }

        add_generation_timing_aliases(timing)

        self.assertEqual(timing["source_prepare_ms"], 999)
        self.assertEqual(timing["card_body_ms"], 888)
        self.assertNotIn("field_merge_ms", timing)
        self.assertNotIn("total_ms", timing)

    def test_add_generation_timing_aliases_coerces_falsy_sources_to_zero(self):
        from acg.generation_timing import add_generation_timing_aliases

        timing = {
            "source_prepare": None,
            "card_model": 0,
            "field_merge": False,
            "total": "",
        }

        add_generation_timing_aliases(timing)

        self.assertEqual(timing["source_prepare_ms"], 0)
        self.assertEqual(timing["card_body_ms"], 0)
        self.assertEqual(timing["field_merge_ms"], 0)
        self.assertEqual(timing["total_ms"], 0)

    def test_add_learning_point_extraction_timing_aliases_populates_release_keys(self):
        from acg.generation_timing import add_learning_point_extraction_timing_aliases

        timing = {
            "source_prepare": 10,
            "learning_point_extract": 20,
            "ai_review": 30,
            "postprocess": 40,
            "total": 100,
        }

        self.assertIs(add_learning_point_extraction_timing_aliases(timing), timing)
        self.assertEqual(timing["source_prepare_ms"], 10)
        self.assertEqual(timing["learning_point_extract_ms"], 20)
        self.assertEqual(timing["ai_review_ms"], 30)
        self.assertEqual(timing["total_ms"], 100)
        self.assertEqual(timing["postprocess"], 40)

    def test_add_export_timing_aliases_populates_release_keys(self):
        from acg.generation_timing import add_export_timing_aliases

        timing = {
            "source_prepare": 11,
            "tts": 22,
            "media": 33,
            "apkg_packaging": 44,
            "total": 55,
        }

        self.assertIs(add_export_timing_aliases(timing), timing)
        self.assertEqual(timing["source_prepare_ms"], 11)
        self.assertEqual(timing["tts_ms"], 22)
        self.assertEqual(timing["media_slice_ms"], 33)
        self.assertEqual(timing["apkg_pack_ms"], 44)
        self.assertEqual(timing["total_ms"], 55)

    def test_add_verify_anki_import_timing_aliases_populates_release_keys(self):
        from acg.generation_timing import add_verify_anki_import_timing_aliases

        timing = {
            "anki_import": 12,
            "anki_query": 34,
            "anki_verify": 56,
            "total": 56,
        }

        self.assertIs(add_verify_anki_import_timing_aliases(timing), timing)
        self.assertEqual(timing["anki_verify_ms"], 56)
        self.assertEqual(timing["total_ms"], 56)
        self.assertEqual(timing["anki_import"], 12)
        self.assertEqual(timing["anki_query"], 34)

    def test_verify_anki_import_missing_apkg_reports_timing_aliases(self):
        result = worker.handle_verify_anki_import(
            {
                "import_apkg": True,
                "apkg_path": str(ROOT / "missing-release-timing.apkg"),
                "export_result": {"media_summary": {"media_files": 0}},
            }
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["failed_checks"], ["apkg_missing_for_import"])
        self.assertIn("timing_ms", result)
        self.assertIn("anki_verify_ms", result["timing_ms"])
        self.assertIn("total_ms", result["timing_ms"])
        self.assertEqual(result["timing_ms"]["anki_verify_ms"], result["timing_ms"]["total_ms"])


if __name__ == "__main__":
    unittest.main()
