import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = ROOT / "workers" / "anki_worker.py"


def load_worker():
    spec = importlib.util.spec_from_file_location("anki_worker_for_model_json_tests", WORKER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


worker = load_worker()


class ModelJsonBoundaryTests(unittest.TestCase):
    def test_strip_reasoning_text_matches_legacy_wrapper(self):
        from acg import model_json

        legacy = worker._legacy_worker
        samples = [
            "<think>internal</think>{\"ok\": true}",
            "<thinking>step 1\nstep 2</thinking>\n{\"segments\": []}",
            "plain text",
        ]
        for text in samples:
            with self.subTest(text=text):
                self.assertEqual(model_json.strip_reasoning_text(text), legacy.strip_reasoning_text(text))

    def test_extract_json_object_matches_legacy_wrapper(self):
        from acg import model_json

        legacy = worker._legacy_worker
        samples = [
            "```json\n{\"segments\": [{\"id\": \"s1\"}]}\n```",
            "noise {\"unused\": true} more {\"candidates\": [{\"id\": \"c1\"}]}",
            "<think>ignore</think> prefix {\"foo\": 1} suffix {\"segments\": []}",
            "prefix {\"candidates\": []} middle {\"segments\": [{\"id\": \"preferred\"}]}",
            "prefix {\"foo\": 1} suffix {\"bar\": 2}",
        ]
        for text in samples:
            with self.subTest(text=text):
                self.assertEqual(model_json.extract_json_object(text), legacy.extract_json_object(text))

    def test_extract_json_object_raises_on_missing_json(self):
        from acg import model_json

        legacy = worker._legacy_worker
        with self.assertRaises(ValueError):
            model_json.extract_json_object("no JSON here")
        with self.assertRaises(ValueError):
            legacy.extract_json_object("no JSON here")


if __name__ == "__main__":
    unittest.main()
