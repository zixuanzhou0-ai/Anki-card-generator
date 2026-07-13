import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = ROOT / "workers" / "anki_worker.py"


def load_worker():
    spec = importlib.util.spec_from_file_location("anki_worker_for_subtitle_sentence_tests", WORKER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


worker = load_worker()


class SubtitleSentenceBoundaryTests(unittest.TestCase):
    def test_source_sentence_records_provenance_and_flags_bad_join(self):
        from acg.pipeline.learning_point_pipeline import source_sentences_from_cues
        from acg.subtitles.core import Cue

        cues = [
            Cue(1, 45.791, 49.0, "It's sort of like a mini English that works in your everyday"),
            Cue(2, 49.05, 53.911, "You're confident with the English that you use inside your bubble."),
        ]

        sentences = source_sentences_from_cues(cues, {"language": "en"})

        self.assertEqual(len(sentences), 1)
        sentence = sentences[0]
        self.assertEqual(sentence["source_cue_ids"], [1, 2])
        self.assertEqual(sentence["source_cue_count"], 2)
        self.assertIn("possible_bad_join", sentence["source_sentence_quality_flags"])
        self.assertEqual(sentence["source_sentence_quality_status"], "needs_review")

    def test_source_sentence_flags_dangling_tail_as_needing_review(self):
        from acg.subtitles.sentences import sentence_quality_flags, sentence_quality_status

        truncated = (
            "And the proverb, “Don’t judge a book by its cover” advises people "
            "not to form opinions about people based"
        )
        flags = sentence_quality_flags(truncated, [truncated])

        self.assertIn("truncated_tail", flags)
        self.assertEqual(sentence_quality_status(flags), "needs_review")

    def test_source_sentence_builder_extends_soft_window_to_close_dangling_tail(self):
        from acg.pipeline.learning_point_pipeline import source_sentences_from_cues
        from acg.subtitles.core import Cue

        cues = [
            Cue(12, 28.890, 30.390, "And the proverb, “Don’t"),
            Cue(13, 30.390, 32.649, "judge a book by its cover”"),
            Cue(14, 32.649, 34.680, "advises people not to form"),
            Cue(15, 34.680, 36.790, "opinions about people based"),
            Cue(16, 36.790, 38.780, "on how they look."),
        ]

        sentences = source_sentences_from_cues(cues, {"language": "en"})

        self.assertEqual(len(sentences), 1)
        self.assertEqual(
            sentences[0]["source_sentence"],
            (
                "And the proverb, “Don’t judge a book by its cover” advises people "
                "not to form opinions about people based on how they look."
            ),
        )
        self.assertEqual(sentences[0]["source_cue_ids"], [12, 13, 14, 15, 16])
        self.assertEqual(sentences[0]["source_sentence_quality_flags"], ["clean"])
        self.assertEqual(sentences[0]["source_sentence_quality_status"], "clean")

    def test_source_sentence_builder_matches_pipeline_boundary(self):
        from acg import media_alignment
        from acg.pipeline.learning_point_pipeline import source_sentences_from_cues as pipeline_source_sentences_from_cues
        from acg.subtitles.core import Cue
        from acg.subtitles.sentences import source_sentences_from_cues as subtitle_source_sentences_from_cues

        legacy = worker._legacy_worker
        cues = [
            Cue(1, 0.0, 1.0, "When you heat apples,"),
            Cue(2, 1.1, 3.0, "the cells release more useful compounds."),
            Cue(3, 4.2, 6.1, "That is why cooked apples taste different."),
        ]

        direct = subtitle_source_sentences_from_cues(
            cues,
            language="English",
            merge_subtitle_parts=media_alignment.merge_subtitle_parts,
            clean_candidate_text=media_alignment.clean_candidate_text,
            looks_complete_sentence=media_alignment.looks_complete_sentence,
            normalize_language=legacy.normalize_learning_language,
        )
        wrapper = pipeline_source_sentences_from_cues(cues, {"language": "English"})

        self.assertEqual(direct, wrapper)
        self.assertEqual(len(wrapper), 2)
        self.assertEqual(wrapper[0]["source_cue_ids"], [1, 2])
        self.assertEqual(wrapper[0]["source_merge_reason"], "merged_until_sentence_boundary")
        self.assertEqual(wrapper[0]["next_sentence"], wrapper[1]["source_sentence"])
        self.assertEqual(wrapper[1]["previous_sentence"], wrapper[0]["source_sentence"])
        self.assertEqual(wrapper[1]["source_merge_reason"], "single_cue")

    def test_source_segment_key_legacy_boundary_matches_subtitle_module(self):
        from acg.subtitles import sentences

        legacy = worker._legacy_worker
        samples = [
            (0.0, 4.11, "Does anyone want to tell me how we went from how to learn a language in 90 days?"),
            (16.455, 23.134, "They speak so quickly words blend together, and suddenly you're feeling completely lost."),
            (349.287, 358.061, "The more you live in English, the faster your brain rewires itself."),
        ]

        for start, end, text in samples:
            with self.subTest(text=text):
                self.assertEqual(sentences.source_segment_key(start, end, text), legacy.source_segment_key(start, end, text))

    def test_looks_complete_sentence_legacy_boundary_matches_media_alignment(self):
        from acg import media_alignment

        legacy = worker._legacy_worker
        samples = [
            ("This is a complete sentence.", True),
            ("This is not complete", False),
            ("Wait, what?", False),
            ("You're feeling completely lost.", True),
            ("", False),
        ]

        for text, expected in samples:
            with self.subTest(text=text):
                self.assertEqual(media_alignment.looks_complete_sentence(text), expected)
                self.assertEqual(legacy.looks_complete_sentence(text), expected)

    def test_is_filler_text_legacy_boundary_matches_media_alignment(self):
        from acg import media_alignment

        legacy = worker._legacy_worker
        samples = [
            ("yeah", True),
            ("Well.", True),
            ("oh wow", False),
            ("not because", False),
            ("", False),
        ]

        for text, expected in samples:
            with self.subTest(text=text):
                self.assertEqual(media_alignment.is_filler_text(text), expected)
                self.assertEqual(legacy.is_filler_text(text), expected)

    def test_sentence_fragment_helpers_legacy_boundary_matches_subtitle_module(self):
        from acg.subtitles import sentences

        legacy = worker._legacy_worker
        quote_samples = [
            ('He said "hello', True),
            ('He said "hello"', False),
            ("“Hello", True),
            ("“Hello”", False),
        ]
        fragment_samples = [
            ("because they focus on the wrong things.", True),
            (", and then they continued.", True),
            ("lifestyle, and they only amplify my dream.", True),
            ("I want to learn faster.", False),
            ("This is a complete sentence.", False),
            ("", True),
        ]

        for text, expected in quote_samples:
            with self.subTest(kind="quotes", text=text):
                self.assertEqual(sentences.has_unbalanced_quotes(text), expected)
                self.assertEqual(legacy.has_unbalanced_quotes(text), expected)

        for text, expected in fragment_samples:
            with self.subTest(kind="fragment", text=text):
                self.assertEqual(sentences.starts_like_fragment(text), expected)
                self.assertEqual(legacy.starts_like_fragment(text), expected)

    def test_rolling_caption_helpers_legacy_boundary_matches_subtitle_module(self):
        from acg.subtitles import sentences

        legacy = worker._legacy_worker
        self.assertEqual(
            sentences.incremental_caption_text(
                "an ancient Chinese myth tells that long",
                "an ancient Chinese myth tells that long ago before humans inhabited the Earth",
            ),
            legacy.incremental_caption_text(
                "an ancient Chinese myth tells that long",
                "an ancient Chinese myth tells that long ago before humans inhabited the Earth",
            ),
        )
        self.assertEqual(
            sentences.split_caption_fragment("First sentence. Second idea without ending", 1.0, 5.0),
            legacy.split_caption_fragment("First sentence. Second idea without ending", 1.0, 5.0),
        )
        self.assertEqual(sentences.append_caption_text("fast-", "track"), legacy.append_caption_text("fast-", "track"))

        cues = [
            worker.Cue(1, 0.0, 2.0, "an ancient Chinese myth tells that long"),
            worker.Cue(2, 2.0, 4.0, "an ancient Chinese myth tells that long ago before humans inhabited the Earth"),
            worker.Cue(3, 4.0, 6.0, "ago before humans inhabited the Earth the world was populated only by plants"),
            worker.Cue(4, 6.0, 8.0, "the world was populated only by plants and animals and the gods were proud"),
        ]
        direct = sentences.normalize_rolling_cues(cues)
        wrapper = legacy.normalize_rolling_cues(cues)

        self.assertEqual([(cue.index, cue.start, cue.end, cue.text) for cue in direct], [(cue.index, cue.start, cue.end, cue.text) for cue in wrapper])
        self.assertGreater(len(direct), 1)
        self.assertLess(max(len(worker.overlap_words(cue.text)) for cue in direct), 20)

    def test_bad_join_source_sentence_demotes_default_recommendation(self):
        from acg.pipeline.learning_point_pipeline import _apply_source_sentence_quality_gate

        point = {
            "id": "lp_bad_join",
            "status": "recommended",
            "status_reason": "AI 认为值得默认学习。",
            "source_sentence_quality_flags": ["possible_bad_join"],
        }

        gated = _apply_source_sentence_quality_gate(point)

        self.assertEqual(gated["status"], "candidate_only")
        self.assertEqual(gated["source_sentence_quality_gate"], "demoted_from_recommended")
        self.assertIn("字幕句子边界不够可靠", gated["status_reason"])

    def test_question_restart_after_fragment_flags_bad_join(self):
        from acg.subtitles.sentences import sentence_quality_flags, sentence_quality_status

        flags = sentence_quality_flags(
            "Yes, I did. I read various materials about eloquence as well as rehearsed a "
            "How did you know about the competition?",
            [
                "Yes, I did. I read various materials about eloquence as well as rehearsed a",
                "How did you know about the competition?",
            ],
        )

        self.assertIn("possible_bad_join", flags)
        self.assertEqual(sentence_quality_status(flags), "needs_review")

    def test_subtitle_sentence_quality_gate_is_available_from_sentence_module(self):
        from acg.subtitles.sentences import apply_source_sentence_quality_gate

        gated = apply_source_sentence_quality_gate(
            {
                "id": "lp_bad_join",
                "status": "recommended",
                "status_reason": "AI 认为值得默认学习。",
                "source_sentence_quality_flags": ["possible_bad_join"],
            }
        )

        self.assertEqual(gated["status"], "candidate_only")
        self.assertEqual(gated["source_sentence_quality_gate"], "demoted_from_recommended")

    def test_lowercase_comma_fragment_demotes_default_recommendation(self):
        from acg.pipeline.learning_point_pipeline import _apply_source_sentence_quality_gate
        from acg.subtitles.sentences import sentence_quality_flags, sentence_quality_status

        flags = sentence_quality_flags("lifestyle, and they only amplify my dream of doing the same.")
        self.assertIn("fragment", flags)
        self.assertEqual(sentence_quality_status(flags), "needs_review")

        point = {
            "id": "lp_fragment",
            "status": "recommended",
            "status_reason": "AI 认为值得默认学习。",
            "source_sentence_quality_flags": flags,
        }

        gated = _apply_source_sentence_quality_gate(point)

        self.assertEqual(gated["status"], "candidate_only")
        self.assertEqual(gated["source_sentence_quality_gate"], "demoted_from_recommended")

    def test_too_long_source_sentence_demotes_default_recommendation(self):
        from acg.pipeline.learning_point_pipeline import _apply_source_sentence_quality_gate
        from acg.subtitles.sentences import sentence_quality_flags, sentence_quality_status

        long_sentence = (
            "The first thing I noticed was how quickly the speaker moved from one idea to another "
            "without giving learners enough time to separate the example, the explanation, the warning, "
            "and the final takeaway into clean studyable pieces."
        )
        flags = sentence_quality_flags(long_sentence)

        self.assertIn("too_long", flags)
        self.assertEqual(sentence_quality_status(flags), "needs_review")

        point = {
            "id": "lp_too_long",
            "status": "recommended",
            "status_reason": "AI 认为值得默认学习。",
            "source_sentence_quality_flags": flags,
        }

        gated = _apply_source_sentence_quality_gate(point)

        self.assertEqual(gated["status"], "candidate_only")
        self.assertEqual(gated["source_sentence_quality_gate"], "demoted_from_recommended")

    def test_clean_single_cue_sentence_stays_clean(self):
        from acg.pipeline.learning_point_pipeline import source_sentences_from_cues
        from acg.subtitles.core import Cue

        cues = [
            Cue(1, 0.0, 3.2, "Most people think that it takes years to reach fluency."),
        ]

        sentences = source_sentences_from_cues(cues, {"language": "en"})

        self.assertEqual(sentences[0]["source_sentence_quality_flags"], ["clean"])
        self.assertEqual(sentences[0]["source_sentence_quality_status"], "clean")

    def test_lowercase_complete_sentence_stays_clean(self):
        from acg.subtitles.sentences import sentence_quality_flags, sentence_quality_status

        flags = sentence_quality_flags("this is a complete subtitle sentence.")

        self.assertEqual(flags, ["clean"])
        self.assertEqual(sentence_quality_status(flags), "clean")

    def test_adjacent_disfluency_repetition_demotes_default_recommendation(self):
        from acg.pipeline.learning_point_pipeline import _apply_source_sentence_quality_gate
        from acg.subtitles.sentences import sentence_quality_flags, sentence_quality_status

        flags = sentence_quality_flags(
            "and stuff that you know have spent their whole life in the state "
            "and they they are from a a different time before the internet."
        )

        self.assertIn("repeated_adjacent_words", flags)
        self.assertEqual(sentence_quality_status(flags), "needs_review")

        point = {
            "id": "lp_repeated_words",
            "status": "recommended",
            "status_reason": "AI 认为值得默认学习。",
            "source_sentence_quality_flags": flags,
        }

        gated = _apply_source_sentence_quality_gate(point)

        self.assertEqual(gated["status"], "candidate_only")
        self.assertEqual(gated["source_sentence_quality_gate"], "demoted_from_recommended")

    def test_valid_emphasis_repetition_stays_clean(self):
        from acg.subtitles.sentences import sentence_quality_flags, sentence_quality_status

        flags = sentence_quality_flags("This is very very useful for daily conversation.")

        self.assertEqual(flags, ["clean"])
        self.assertEqual(sentence_quality_status(flags), "clean")

    def test_learning_point_provenance_reattaches_source_sentence_by_id(self):
        from acg.subtitles.provenance import point_with_source_sentence_provenance, source_sentence_indexes

        source_sentences = [
            {
                "id": "src-provenance",
                "source_segment_id": "src-provenance",
                "source_sentence": "everyday You're confident with the English that you use.",
                "start": 12.0,
                "end": 16.2,
                "source_time": "00:00:12.000 - 00:00:16.200",
                "source_cue_ids": [7, 8],
                "source_cue_count": 2,
                "source_cue_start": 12.0,
                "source_cue_end": 16.2,
                "source_cue_texts": [
                    "It's sort of like a mini English that works in your everyday",
                    "You're confident with the English that you use.",
                ],
                "source_sentence_quality_flags": ["possible_bad_join"],
                "source_sentence_quality_status": "needs_review",
            }
        ]
        by_id, by_text = source_sentence_indexes(source_sentences)

        point = point_with_source_sentence_provenance(
            {
                "id": "lp-provenance",
                "source_segment_id": "src-provenance",
                "answer_core": "confident",
            },
            by_id,
            by_text,
        )

        self.assertEqual(point["source_sentence"], source_sentences[0]["source_sentence"])
        self.assertEqual(point["source_time"], "00:00:12.000 - 00:00:16.200")
        self.assertEqual(point["start"], 12.0)
        self.assertEqual(point["end"], 16.2)
        self.assertEqual(point["source_cue_ids"], [7, 8])
        self.assertEqual(point["source_sentence_quality_flags"], ["possible_bad_join"])
        self.assertEqual(point["source_sentence_quality_status"], "needs_review")

    def test_learning_point_provenance_falls_back_to_source_sentence_text(self):
        from acg.subtitles.provenance import point_with_source_sentence_provenance, source_sentence_indexes

        source_sentences = [
            {
                "id": "src-register",
                "source_segment_id": "src-register",
                "source_sentence": "Can you run the register for a minute?",
                "start": 10.0,
                "end": 12.0,
                "source_time": "00:00:10.000 - 00:00:12.000",
            }
        ]
        by_id, by_text = source_sentence_indexes(source_sentences)

        point = point_with_source_sentence_provenance(
            {
                "id": "lp-register",
                "source_sentence": "  Can you run the register for a minute?  ",
                "answer_core": "run the register",
            },
            by_id,
            by_text,
        )

        self.assertEqual(point["start"], 10.0)
        self.assertEqual(point["end"], 12.0)
        self.assertEqual(point["source_time"], "00:00:10.000 - 00:00:12.000")
        self.assertEqual(point["source_sentence_quality_flags"], ["clean"])
        self.assertEqual(point["source_sentence_quality_status"], "clean")


if __name__ == "__main__":
    unittest.main()
