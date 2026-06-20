import copy
import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = ROOT / "workers" / "anki_worker.py"


def load_worker():
    spec = importlib.util.spec_from_file_location("anki_worker_for_inventory_tests", WORKER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


worker = load_worker()


class InventoryBoundaryTests(unittest.TestCase):
    def test_inventory_status_helpers_match_legacy_wrappers(self):
        from acg import inventory

        legacy = worker._legacy_worker
        filtered_samples = [
            ({"phrase_review_status": "duplicate"}, ""),
            ({"phrase_review_status": "reject", "validation_issues": "exact_span 不在原句"}, ""),
            ({"phrase_review_status": "reject", "phrase_reject_reason": "只是候选，不够强"}, ""),
            ({"phrase_reject_reason": "重复候选"}, ""),
            ({}, "bad json from model"),
        ]
        for item, reason in filtered_samples:
            with self.subTest(item=item, reason=reason):
                self.assertEqual(
                    inventory.inventory_status_for_filtered_item(item, reason),
                    legacy.inventory_status_for_filtered_item(item, reason),
                )

        rejected_samples = [
            ({"quality": {"issues": ["缺少中文意思"]}}, {"phrase_review_status": "reject"}),
            ({"quality": {"issues": ["answer_core 不在原句"]}}, {"phrase_review_status": "reject"}),
            ({"quality": {"issues": []}}, {}),
        ]
        for card, segment in rejected_samples:
            with self.subTest(card=card, segment=segment):
                self.assertEqual(
                    inventory.inventory_status_for_rejected_card(card, segment),
                    legacy.inventory_status_for_rejected_card(card, segment),
                )

    def test_inventory_learning_action_and_stats_match_legacy_wrappers(self):
        from acg import inventory

        legacy = worker._legacy_worker
        action_samples = [
            ({"learning_action": "contextual_meaning"}, None),
            ({"phrase_card_focus": "训练语气边界"}, {"learning_target": "避免直译导致冒犯"}),
            ({}, {"teacher_note": "确认搭配是否自然"}),
            ({}, None),
        ]
        for item, card in action_samples:
            with self.subTest(item=item, card=card):
                self.assertEqual(
                    inventory.inventory_learning_action(item, card),
                    legacy.inventory_learning_action(item, card),
                )

        inventory_items = [
            {"status": "candidate_only"},
            {"status": "hidden_duplicate"},
            {"status": "hard_blocked"},
            {"status": "card_generated"},
            {"status": "candidate_only"},
            {},
        ]
        self.assertEqual(
            inventory.learning_point_inventory_stats(inventory_items),
            legacy.learning_point_inventory_stats(inventory_items),
        )

    def test_default_selection_and_quality_status_match_legacy_wrappers(self):
        from acg import inventory

        legacy = worker._legacy_worker
        cards = [
            {"id": "a", "quality": {"status": "recommended"}, "enabled": False},
            {"id": "b", "quality": {"status": "needs_review"}, "enabled": False},
            {"id": "c", "quality": {"status": "reject"}, "enabled": True},
            {"id": "d", "quality": {}, "enabled": True},
            {"id": "e"},
        ]
        for card in cards:
            with self.subTest(card=card):
                self.assertEqual(inventory.card_quality_status(card), legacy.card_quality_status(card))

        segments_for_module = [{"id": "s1", "cards": copy.deepcopy(cards)}]
        segments_for_legacy = [{"id": "s1", "cards": copy.deepcopy(cards)}]
        self.assertEqual(
            inventory.apply_default_generated_card_selection(segments_for_module, {}),
            legacy.apply_default_generated_card_selection(segments_for_legacy, {}),
        )


if __name__ == "__main__":
    unittest.main()
