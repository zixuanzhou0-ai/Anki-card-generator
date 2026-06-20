import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = ROOT / "workers" / "anki_worker.py"


def load_worker():
    spec = importlib.util.spec_from_file_location("anki_worker_for_card_generation_cache_tests", WORKER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


worker = load_worker()


class CardGenerationCacheBoundaryTests(unittest.TestCase):
    def _payload(self):
        return {
            "language": "en",
            "level": "B1",
            "level_mode": "auto",
            "review_density": "fast",
            "template_id": "immersive_v11",
            "api_config": {
                "provider": "gemini-vertex",
                "model": "gemini-3.1-pro-preview",
                "base_url": "https://example.test/",
            },
        }

    def _segment(self, segment_id="seg-1", learning_point_id="lp-1"):
        return {
            "id": segment_id,
            "learning_point_id": learning_point_id,
            "source_segment_id": "src-1",
            "text": "Can you run the register for a minute?",
            "exact_span": "run the register",
            "answer_core": "run the register",
            "candidate_kind": "expression",
            "phrase_type": "spoken_phrase",
            "learning_action_key": "expression:run-the-register",
            "learning_action": "训练口语中的自然表达。",
        }

    def test_card_generation_cache_namespace_changes_key(self):
        from acg.card_generation_cache import card_generation_cache_path

        with tempfile.TemporaryDirectory() as tmpdir:
            common = {
                "cache_root": Path(tmpdir),
                "provider_name": "gemini-vertex",
                "normalized_language": "en",
                "normalized_level_mode": "auto",
                "normalized_review_density": "fast",
            }
            path_a, key_a = card_generation_cache_path(
                {**self._payload(), "card_generation_cache_namespace": "ns-a"},
                [self._segment()],
                ["phrase"],
                **common,
            )
            path_b, key_b = card_generation_cache_path(
                {**self._payload(), "card_generation_cache_namespace": "ns-b"},
                [self._segment()],
                ["phrase"],
                **common,
            )
            path_a_again, key_a_again = card_generation_cache_path(
                {**self._payload(), "card_generation_cache_namespace": "ns-a"},
                [self._segment()],
                ["phrase"],
                **common,
            )

        self.assertNotEqual(key_a, key_b)
        self.assertNotEqual(path_a, path_b)
        self.assertEqual(key_a, key_a_again)
        self.assertEqual(path_a, path_a_again)

    def test_card_generation_cache_loads_only_usable_payloads(self):
        from acg.card_generation_cache import load_card_generation_cache, store_card_generation_cache

        usable_payload = {
            "segments": [
                {
                    "id": "seg-1",
                    "cards": [{"phrase": "run the register"}],
                }
            ]
        }
        empty_payload = {"segments": [{"id": "seg-empty", "cards": [{}]}]}
        error_payload = {"error": "bad response", "segments": [{"id": "seg-err", "cards": [{"phrase": "x"}]}]}

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            usable_path = root / "usable.json"
            empty_path = root / "empty.json"
            error_path = root / "error.json"
            broken_path = root / "broken.json"

            store_card_generation_cache(usable_path, "usable", usable_payload)
            store_card_generation_cache(empty_path, "empty", empty_payload)
            store_card_generation_cache(error_path, "error", error_payload)
            broken_path.write_text("{not-json", encoding="utf-8")

            self.assertEqual(load_card_generation_cache(usable_path), usable_payload)
            self.assertIsNone(load_card_generation_cache(empty_path))
            self.assertIsNone(load_card_generation_cache(error_path))
            self.assertIsNone(load_card_generation_cache(broken_path))

    def test_card_generation_cache_policy_preserves_legacy_and_split_flags(self):
        from acg.card_generation_cache import card_generation_cache_policy

        self.assertEqual(card_generation_cache_policy({}), (True, True))
        self.assertEqual(card_generation_cache_policy({"disable_card_generation_cache": True}), (False, False))
        self.assertEqual(card_generation_cache_policy({"disable_card_generation_cache_read": True}), (False, True))
        self.assertEqual(card_generation_cache_policy({"disable_card_generation_cache_write": True}), (True, False))
        self.assertEqual(
            card_generation_cache_policy({"api_config": {"disable_card_generation_cache_read": True}}),
            (False, True),
        )

    def test_source_fingerprint_uses_effective_source_identity(self):
        from acg.card_generation_cache import source_fingerprint

        base = {
            "source_mode": "url",
            "source_url": "https://www.youtube.com/watch?v=one",
            "url_import_mode": "video",
            "title": "Video One",
        }
        same_with_source_info = source_fingerprint(base, {"video_path": "E:/cache/source.mp4"})
        same_again = source_fingerprint({**base, "video_path": "E:/cache/source.mp4"})
        different_url = source_fingerprint({**base, "source_url": "https://www.youtube.com/watch?v=two"})

        self.assertEqual(same_with_source_info, same_again)
        self.assertNotEqual(same_again, different_url)


if __name__ == "__main__":
    unittest.main()
