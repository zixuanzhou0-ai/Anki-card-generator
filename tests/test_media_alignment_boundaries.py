import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = ROOT / "workers" / "anki_worker.py"


def load_worker():
    spec = importlib.util.spec_from_file_location("anki_worker_for_media_alignment_tests", WORKER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


worker = load_worker()


class MediaAlignmentBoundaryTests(unittest.TestCase):
    def assert_window_covers_phrase(self, *, text, phrase, start, end, media_start, media_end):
        from acg.media_alignment import overlap_words, phrase_word_indices

        indices = phrase_word_indices(text, phrase)
        self.assertIsNotNone(indices)
        assert indices is not None
        first, last = indices
        words = overlap_words(text)
        duration = end - start
        phrase_start = start + duration * (first / len(words))
        phrase_end = start + duration * ((last + 1) / len(words))

        self.assertLessEqual(media_start, phrase_start)
        self.assertGreaterEqual(media_end, phrase_end)

    def test_media_subtitle_alignment_uses_counted_overlap_for_repeated_caption_words(self):
        from acg.media_alignment import (
            _counted_word_overlap_ratio,
            media_subtitle_alignment_blocks_export,
            media_subtitle_alignment_diagnostic,
        )
        from acg.subtitles.core import Cue

        expected_text = "go go go go now"
        actual_window_text = "go now"
        cues = [Cue(index=1, start=10.0, end=11.0, text=actual_window_text)]

        self.assertEqual(_counted_word_overlap_ratio(expected_text, actual_window_text), 0.4)

        diagnostic = media_subtitle_alignment_diagnostic(
            cues,
            10.0,
            11.0,
            expected_text,
        )

        self.assertEqual(diagnostic["media_subtitle_alignment_status"], "partial")
        self.assertEqual(diagnostic["media_subtitle_overlap_score"], 0.4)
        self.assertTrue(media_subtitle_alignment_blocks_export(diagnostic, {}))

    def test_phrase_media_bounds_cover_phrase_at_start_middle_and_end(self):
        from acg.media_alignment import segment_media_bounds

        text = (
            "right at the start we explain the setup then quietly make the decision "
            "together and save the surprise right before we leave"
        )
        start = 100.0
        end = 118.0

        for phrase in [
            "right at the start",
            "quietly make the decision",
            "right before we leave",
        ]:
            with self.subTest(phrase=phrase):
                media_start, media_end = segment_media_bounds(start, end, text, phrase, review_mode=False)

                self.assert_window_covers_phrase(
                    text=text,
                    phrase=phrase,
                    start=start,
                    end=end,
                    media_start=media_start,
                    media_end=media_end,
                )
                self.assertLessEqual(media_end - media_start, 6.25)

    def test_learning_point_media_alignment_fields_keep_full_sentence_window_for_phrase_positions(self):
        from acg.media_alignment import learning_point_media_alignment_fields

        full_sentence = (
            "right at the start we explain the setup then quietly make the decision "
            "together and save the surprise right before we leave"
        )

        for phrase in [
            "right at the start",
            "quietly make the decision",
            "right before we leave",
        ]:
            with self.subTest(phrase=phrase):
                fields = learning_point_media_alignment_fields(
                    {
                        "source_sentence": full_sentence,
                        "answer_core": phrase,
                        "exact_span": phrase,
                    },
                    start=100.0,
                    end=118.0,
                    display_sentence=full_sentence,
                )

                self.assertEqual(fields["media_alignment_status"], "source_sentence_window")
                self.assertEqual(fields["media_alignment_text"], full_sentence)
                self.assertEqual(fields["media_alignment_source_text"], full_sentence)
                self.assertEqual(fields["media_alignment_phrase"], phrase)
                self.assertTrue(fields["media_alignment_phrase_located"])
                self.assertLessEqual(fields["media_start"], 100.0)
                self.assertGreaterEqual(fields["media_end"], 118.0)

    def test_learning_point_media_alignment_fields_mark_unlocated_phrase_needs_review(self):
        from acg.media_alignment import learning_point_media_alignment_fields

        full_sentence = "We explain the setup before moving on."
        fields = learning_point_media_alignment_fields(
            {
                "source_sentence": full_sentence,
                "answer_core": "take the scenic route",
                "exact_span": "take the scenic route",
            },
            start=10.0,
            end=14.0,
            display_sentence=full_sentence,
        )

        self.assertEqual(fields["media_alignment_status"], "source_sentence_window")
        self.assertEqual(fields["media_alignment_text"], full_sentence)
        self.assertEqual(fields["media_alignment_source_text"], full_sentence)
        self.assertEqual(fields["media_alignment_phrase"], "take the scenic route")
        self.assertFalse(fields["media_alignment_phrase_located"])
        self.assertEqual(fields["media_alignment_review_status"], "needs_review")
        self.assertEqual(
            fields["media_alignment_review_reason"],
            "phrase_not_found_in_media_alignment_text",
        )
        self.assertLessEqual(fields["media_start"], 10.0)
        self.assertGreaterEqual(fields["media_end"], 14.0)

    def test_abstract_learning_span_requires_literal_media_review(self):
        from acg.learning_spans import phrase_in_text
        from acg.media_alignment import learning_point_media_alignment_fields

        full_sentence = "I need you to rewire it before the next conversation."
        abstract_phrase = "rewire something"

        self.assertTrue(phrase_in_text(full_sentence, abstract_phrase))

        fields = learning_point_media_alignment_fields(
            {
                "source_sentence": full_sentence,
                "answer_core": abstract_phrase,
                "exact_span": abstract_phrase,
            },
            start=22.0,
            end=27.0,
            display_sentence=full_sentence,
        )

        self.assertEqual(fields["media_alignment_status"], "source_sentence_window")
        self.assertEqual(fields["media_alignment_text"], full_sentence)
        self.assertEqual(fields["media_alignment_source_text"], full_sentence)
        self.assertEqual(fields["media_alignment_phrase"], abstract_phrase)
        self.assertFalse(fields["media_alignment_phrase_located"])
        self.assertEqual(fields["media_alignment_review_status"], "needs_review")
        self.assertEqual(
            fields["media_alignment_review_reason"],
            "phrase_not_found_in_media_alignment_text",
        )
        self.assertLessEqual(fields["media_start"], 22.0)
        self.assertGreaterEqual(fields["media_end"], 27.0)

    def test_export_subtitle_alignment_diagnostics_use_media_alignment_text_and_path(self):
        from acg.media_alignment import export_subtitle_alignment_diagnostics
        from acg.subtitles.core import Cue

        diagnostics = export_subtitle_alignment_diagnostics(
            [
                {
                    "id": "seg-1",
                    "media_start": 10.0,
                    "media_end": 14.0,
                    "text": "stale phrase only",
                    "media_alignment_text": "build your perspective",
                }
            ],
            [
                Cue(index=1, start=10.0, end=12.0, text="Today we need to build"),
                Cue(index=2, start=12.0, end=14.0, text="your perspective before moving on."),
            ],
            "loaded",
            "E:/media/source.srt",
        )

        diagnostic = diagnostics["seg-1"]
        self.assertEqual(diagnostic["media_subtitle_alignment_status"], "matched")
        self.assertEqual(diagnostic["media_subtitle_overlap_score"], 1.0)
        self.assertEqual(diagnostic["subtitle_path"], "E:/media/source.srt")
        self.assertIn("build your perspective", diagnostic["media_window_subtitle_text"])

    def test_export_subtitle_alignment_diagnostics_preserve_unloaded_reason(self):
        from acg.media_alignment import export_subtitle_alignment_diagnostics

        diagnostics = export_subtitle_alignment_diagnostics(
            [{"id": "seg-missing", "media_start": "bad", "text": "build your perspective"}],
            [],
            "subtitle_path_missing",
            "",
        )

        diagnostic = diagnostics["seg-missing"]
        self.assertEqual(diagnostic["media_subtitle_alignment_status"], "unknown")
        self.assertEqual(diagnostic["media_subtitle_alignment_reason"], "subtitle_path_missing")
        self.assertNotIn("subtitle_path", diagnostic)


if __name__ == "__main__":
    unittest.main()
