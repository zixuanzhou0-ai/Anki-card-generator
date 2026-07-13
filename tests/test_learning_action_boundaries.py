import copy
import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = ROOT / "workers" / "anki_worker.py"


def load_worker():
    spec = importlib.util.spec_from_file_location("anki_worker_for_learning_action_tests", WORKER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


worker = load_worker()


class LearningActionBoundaryTests(unittest.TestCase):
    def test_normalized_contains_text_matches_legacy_wrapper(self):
        from acg import learning_actions

        legacy = worker._legacy_worker
        samples = [
            ("Use this when the object is already clear.", "object is already clear"),
            ("使用边界：不要对陌生人说得太直接。", "不要 对 陌生人 说得 太 直接"),
            ("", "anything"),
            ("The words blend together.", ""),
        ]

        for haystack, needle in samples:
            with self.subTest(haystack=haystack, needle=needle):
                self.assertEqual(
                    learning_actions.normalized_contains_text(haystack, needle),
                    legacy.normalized_contains_text(haystack, needle),
                )

    def test_learning_action_for_card_matches_legacy_wrapper(self):
        from acg import learning_actions

        legacy = worker._legacy_worker
        samples = [
            {"learning_action": "grammar_pattern", "candidate_kind": "expression"},
            {"candidate_kind": "contextual_vocab", "phrase_type": "spoken_phrase"},
            {"candidate_kind": "listening_feature"},
            {"content_kind": "grammar"},
            {"candidate_kind": "pragmatic_risk"},
            {"phrase_type": "collocation"},
            {},
        ]

        for card in samples:
            with self.subTest(card=card):
                self.assertEqual(
                    learning_actions.learning_action_for_card(card),
                    legacy.learning_action_for_card(card),
                )

    def test_normalize_learning_action_fields_matches_legacy_wrapper(self):
        from acg import learning_actions

        legacy = worker._legacy_worker
        samples = [
            {
                "candidate_kind": "contextual_vocab",
                "chinese": "这个词在这里表示真实语境义。",
                "definition": "This phrase is useful in daily English.",
                "learning_target": "抓住词在原句里的具体含义。",
                "why_it_matters": "避免只背字典义。",
                "how_to_use_it": "看到同一词在新语境里先判断说话人意图。",
                "teacher_note": "很常见",
            },
            {
                "candidate_kind": "expression",
                "phrase_type": "collocation",
                "definition": "自然搭配，表达两个词在口语里连在一起。",
                "usage_boundary": "只适合非正式口语。",
                "confusable_note": "不要逐词硬翻。",
                "teacher_note": "自然搭配，表达两个词在口语里连在一起。",
            },
            {
                "candidate_kind": "pragmatic_risk",
                "learning_target": ["注意语气边界", "避免冒犯"],
                "chinese_learner_trap": "中文里不冒犯，英语里可能太直接。",
                "collocations": "use it with close friends",
                "why": "本地 fallback：为什么值得学",
            },
        ]

        for source in samples:
            with self.subTest(source=source):
                direct = copy.deepcopy(source)
                via_legacy = copy.deepcopy(source)
                learning_actions.normalize_learning_action_fields(direct)
                legacy.normalize_learning_action_fields(via_legacy)
                self.assertEqual(direct, via_legacy)


    def test_normalize_learning_action_fields_repairs_valid_give_opinion_contrast(self):
        from acg import learning_actions

        card = {
            "answer_core": "form opinions about",
            "phrase": "form opinions about",
            "teacher_note": (
                "记住 form + opinion(s) + about；"
                "易混表达：容易说 make opinions 或 give opinions，正确是 form opinions about"
            ),
            "chinese_learner_trap": "容易说 make opinions 或 give opinions，正确是 form opinions about",
            "confusable_note": "不要说 give opinions；应改为 form opinions about",
        }

        learning_actions.normalize_learning_action_fields(card)

        self.assertIn("make opinions 不自然", card["chinese_learner_trap"])
        self.assertIn("give an opinion / give opinions", card["chinese_learner_trap"])
        self.assertIn("后两者都可用，但含义不同", card["chinese_learner_trap"])
        self.assertNotIn("give opinions，正确是", card["teacher_note"])
        self.assertIn("已修复把 give an opinion / give opinions 错判", card["content_repair_history"][0])


if __name__ == "__main__":
    unittest.main()
