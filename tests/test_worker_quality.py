import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = ROOT / "workers" / "anki_worker.py"


def load_worker():
    spec = importlib.util.spec_from_file_location("anki_worker_for_tests", WORKER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


worker = load_worker()


class WorkerQualityTests(unittest.TestCase):
    def test_video_html_keeps_mp4_and_webm_fallbacks(self):
        html = worker.anki_video_html("clip.webm", "clip.mp4", "clip.jpg")

        self.assertIn('poster="clip.jpg"', html)
        self.assertIn('<img src="clip.jpg"', html)
        self.assertIn('src="clip.mp4"', html)
        self.assertIn('type="video/mp4"', html)
        self.assertIn('src="clip.webm"', html)
        self.assertIn('type="video/webm"', html)

    def test_extract_media_references_reads_sources_and_poster(self):
        html = worker.anki_video_html("clip.webm", "clip.mp4", "clip.jpg") + worker.anki_audio_html("clip_tts.mp3")

        self.assertEqual(worker.extract_media_references(html), ["clip.jpg", "clip.mp4", "clip.webm", "clip_tts.mp3"])

    def test_compare_media_manifest_detects_media_collision(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            export_dir = root / "export"
            anki_dir = root / "anki"
            export_dir.mkdir()
            anki_dir.mkdir()
            (export_dir / "deck_seg_0001.mp3").write_bytes(b"new audio")
            (anki_dir / "deck_seg_0001.mp3").write_bytes(b"old audio")

            manifest = worker.media_manifest([str(export_dir / "deck_seg_0001.mp3")])
            result = worker.compare_media_manifest(manifest, anki_dir)

        self.assertEqual(result["missing"], [])
        self.assertEqual(result["mismatched"][0]["file"], "deck_seg_0001.mp3")

    def test_phrase_match_requires_all_phrase_words_in_compact_order(self):
        self.assertTrue(worker.phrase_in_text("I need to make sure we are ready.", "make sure"))
        self.assertFalse(worker.phrase_in_text("I need to make sure we are ready.", "make ready"))

    def test_phrase_match_supports_placeholder_patterns(self):
        self.assertTrue(worker.phrase_in_text("You really let me down.", "let someone down"))
        self.assertTrue(worker.phrase_in_text("We can work it out.", "work something out"))

    def test_subtitle_cleaning_removes_youtube_speaker_markers(self):
        self.assertEqual(
            worker.strip_subtitle_text("? >> Before we start, don't forget to subscribe."),
            "Before we start, don't forget to subscribe.",
        )

    def test_parse_srt_handles_blank_line_between_timestamp_and_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            srt = Path(temp_dir) / "blank-after-time.srt"
            srt.write_text(
                "1\n"
                "00:00:00,120 --> 00:00:02,389\n"
                "\n"
                "an ancient Chinese myth tells that long\n"
                "\n"
                "2\n"
                "00:00:02,399 --> 00:00:04,950\n"
                "ago before humans inhabited the Earth\n",
                encoding="utf-8",
            )

            cues = worker.parse_srt(str(srt))

        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0].text, "an ancient Chinese myth tells that long")
        self.assertEqual(cues[1].text, "ago before humans inhabited the Earth")

    def test_rolling_subtitles_without_punctuation_do_not_collapse_to_one_cue(self):
        cues = [
            worker.Cue(1, 0.0, 2.0, "an ancient Chinese myth tells that long"),
            worker.Cue(2, 2.0, 4.0, "an ancient Chinese myth tells that long ago before humans inhabited the Earth"),
            worker.Cue(3, 4.0, 6.0, "ago before humans inhabited the Earth the world was populated only by plants"),
            worker.Cue(4, 6.0, 8.0, "the world was populated only by plants and animals and the gods were proud"),
        ]

        normalized = worker.normalize_rolling_cues(cues)

        self.assertGreater(len(normalized), 1)
        self.assertLess(max(len(worker.overlap_words(cue.text)) for cue in normalized), 20)

    def test_find_phrase_prefers_transferable_tell_about_pattern(self):
        self.assertEqual(worker.find_phrase("Can you tell me about your plan?", "B1"), "tell me about")

    def test_find_phrase_detects_discourse_markers(self):
        self.assertEqual(worker.find_phrase("Oh, by the way, did I tell you about this?", "B1"), "by the way")
        self.assertEqual(worker.find_phrase("I see what you mean, but I disagree.", "B1"), "i see what you mean")
        self.assertEqual(worker.find_phrase("And sometimes they are funny when we look back.", "B1"), "look back")

    def test_phrase_pool_respects_collection_levels(self):
        pool = worker.phrase_pool("B1", ["A1", "A2"])

        self.assertIn("want to", pool)
        self.assertIn("find out", pool)
        self.assertNotIn("figure out", pool)

    def test_find_phrase_uses_collection_levels_for_basic_range(self):
        self.assertEqual(worker.find_phrase("I want to go home right now.", "B1", ["A1"]), "right now")
        self.assertEqual(worker.find_phrase("I want to go home right now.", "B1", ["B1"]), "key expression")

    def test_complete_expression_can_end_with_preposition(self):
        card = {
            "type": "phrase",
            "english": "I'm suddenly in the mood for Greek food.",
            "phrase": "in the mood for",
            "chinese": "我突然想吃希腊菜了。",
            "definition": "想要做某事或想要某种东西。",
            "collocations": "in the mood for food / in the mood for a walk",
            "context": "表达当下突然有某种兴致。",
            "example": "I'm not in the mood for a movie tonight.",
            "chinese_feel": "中文里就是“突然想...”。",
            "why": "很常见的口语表达。",
            "teacher_note": "for 后面接名词或动名词。",
            "difficulty": "B1 日常交流",
            "cloze": "I'm suddenly ____ Greek food.",
        }
        quality = worker.assess_card_quality(card, {"text": card["english"]}, "ai", "B1")

        self.assertEqual(quality["status"], "recommended")

    def test_low_value_standalone_phrase_is_not_usable(self):
        self.assertEqual(worker.find_phrase("They are literally working with nerfed Nvidia GPUs.", "B1"), "working with")
        self.assertFalse(worker.usable_phrase("They are literally working with nerfed Nvidia GPUs.", "working with"))

    def test_basic_phrase_is_not_recommended_for_b1(self):
        card = {
            "type": "phrase",
            "english": "Tittle-tattle is talk about other people's lives",
            "phrase": "talk about",
            "chinese": "八卦就是谈论别人的生活。",
            "definition": "谈论，讨论某人或某事。",
            "collocations": "talk about sth / talk about sb",
            "context": "说明讨论的主题。",
            "example": "We were just talking about the new movie.",
            "chinese_feel": "就是日常说的“聊一下”。",
            "why": "这是基础动词短语。",
            "teacher_note": "说明 discuss 的口语说法。",
            "difficulty": "A1 入门",
            "cloze": "Tittle-tattle is ____ other people's lives",
        }
        quality = worker.assess_card_quality(card, {"text": card["english"]}, "ai", "B1")

        self.assertNotEqual(quality["status"], "recommended")
        self.assertIn("目标表达低于用户水平", quality["issues"])

    def test_fallback_phrase_fields_are_specific_for_known_expression(self):
        fields = worker.fallback_phrase_fields(
            "Not because China caught up, but because of what happens next.",
            "what happens next",
            "B1",
        )

        self.assertEqual(fields["chinese"], "接下来会发生什么；后续走势。")
        self.assertNotIn("not really what happens next", fields["collocations"])
        self.assertNotIn("值得优先熟悉的表达块", fields["definition"])
        self.assertNotEqual(fields["example"], "Not because China caught up, but because of what happens next.")

    def test_fallback_phrase_fields_use_inflection_aliases(self):
        fields = worker.fallback_phrase_fields(
            "I was very tired and I fell asleep.",
            "fell asleep",
            "B1",
        )

        self.assertIn("睡着", fields["chinese"])
        self.assertNotIn("待精修", fields["definition"])

    def test_segment_builder_keeps_short_complete_sentence(self):
        cues = [
            worker.Cue(1, 0.0, 1.9, "I was very tired and I fell asleep."),
            worker.Cue(2, 2.0, 4.0, 'Suddenly, I woke up and shouted, "Stop the car."'),
        ]
        segments = worker.build_segments(
            cues,
            {
                "level": "B1",
                "max_segments": 4,
                "content_toggles": {
                    "daily": True,
                    "slang": True,
                    "sarcasm": True,
                    "business": True,
                    "culture": True,
                    "profanity": False,
                    "romance": False,
                    "rare": False,
                },
            },
        )

        self.assertGreaterEqual(len(segments), 1)
        self.assertEqual(segments[0]["text"], "I was very tired and I fell asleep.")
        self.assertEqual(segments[0]["phrase"], "fell asleep")

    def test_segment_builder_keeps_strong_short_sentence_for_model_discovery(self):
        cues = [worker.Cue(1, 0.0, 2.1, "Honestly, it's such a nice Monday morning.")]

        segments = worker.build_segments(
            cues,
            {
                "level": "B1",
                "max_segments": 4,
                "content_toggles": {
                    "daily": True,
                    "slang": True,
                    "sarcasm": True,
                    "business": True,
                    "culture": True,
                    "profanity": False,
                    "romance": False,
                    "rare": False,
                },
            },
        )

        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0]["phrase"], "key expression")
        self.assertGreaterEqual(segments[0]["score"], 3.2)

    def test_segment_builder_still_rejects_known_low_value_phrase(self):
        cues = [worker.Cue(1, 0.0, 2.8, "They are literally working with nerfed Nvidia GPUs.")]

        segments = worker.build_segments(
            cues,
            {
                "level": "B1",
                "max_segments": 4,
                "content_toggles": {
                    "daily": True,
                    "slang": True,
                    "sarcasm": True,
                    "business": True,
                    "culture": True,
                    "profanity": False,
                    "romance": False,
                    "rare": False,
                },
            },
        )

        self.assertEqual(segments, [])

    def test_segment_builder_keeps_rolling_vlog_candidates_for_review(self):
        cues = [
            worker.Cue(1, 0.68, 5.67, "I started vlogging recently and it has completely changed my life I went from"),
            worker.Cue(2, 5.68, 11.39, "having just 1,000 subscribers to now 11,000 in just 3 months opening doors to"),
            worker.Cue(3, 15.799, 19.429, "you but I get it starting vlogging can"),
            worker.Cue(4, 60.199, 64.59, "going through all the trouble because if you've ever considered doing this you"),
            worker.Cue(5, 76.799, 81.35, "you Vlog more consistently in the long run few questions here to help you"),
            worker.Cue(6, 115.799, 120.469, "YouTube is amazing whatever that you are interested in there's probably someone"),
            worker.Cue(7, 197.56, 202.509, "just totally change your perspective on everything whatever's normal and mundane"),
            worker.Cue(8, 236.68, 240.309, "convenience whatever camera you choose to go with you want want to make sure"),
        ]

        segments = worker.build_segments(
            cues,
            {
                "level": "B1",
                "max_segments": 35,
                "_candidate_limit": 70,
                "content_toggles": {
                    "daily": True,
                    "slang": True,
                    "sarcasm": True,
                    "business": True,
                    "culture": True,
                    "profanity": False,
                    "romance": False,
                    "rare": False,
                },
            },
        )

        self.assertGreaterEqual(len(segments), 6)
        self.assertIn("changed my life", [segment["phrase"] for segment in segments])
        self.assertIn("opening doors to", [segment["phrase"] for segment in segments])

    def test_auto_segment_budget_uses_video_length_and_subtitle_density(self):
        cues = [
            worker.Cue(index, index * 4.0, index * 4.0 + 2.0, "I need to figure out what happens next.")
            for index in range(1, 119)
        ]

        budget = worker.resolved_max_segments({"max_segments": 0, "source_info": {"duration": 557}}, cues)

        self.assertGreaterEqual(budget, 35)
        self.assertLessEqual(budget, 55)

    def test_segment_builder_auto_budget_keeps_more_candidates_than_manual_limit(self):
        phrases = [
            "I need to figure out what happens next.",
            "Please don't take it personally.",
            "It turns out I was wrong.",
            "I want to make sure this works.",
            "We ended up going home.",
        ]
        cues = [
            worker.Cue(index + 1, index * 3.2, index * 3.2 + 2.3, phrases[index % len(phrases)])
            for index in range(45)
        ]
        payload = {
            "level": "B1",
            "max_segments": 0,
            "source_info": {"duration": 540},
            "content_toggles": {
                "daily": True,
                "slang": True,
                "sarcasm": True,
                "business": True,
                "culture": True,
                "profanity": False,
                "romance": False,
                "rare": False,
            },
        }

        automatic = worker.build_segments(cues, payload)
        manual = worker.build_segments(cues, {**payload, "max_segments": 4})

        self.assertGreater(len(automatic), len(manual))
        self.assertEqual(len(manual), 4)
        self.assertLessEqual(len(automatic), worker.resolved_max_segments(payload, cues))

    def test_segment_builder_adds_media_window_fields(self):
        cues = [worker.Cue(1, 10.0, 15.2, "I need to figure out what happens next before we decide.")]

        segments = worker.build_segments(
            cues,
            {
                "level": "B1",
                "max_segments": 0,
                "source_info": {"duration": 120},
                "content_toggles": {
                    "daily": True,
                    "slang": True,
                    "sarcasm": True,
                    "business": True,
                    "culture": True,
                    "profanity": False,
                    "romance": False,
                    "rare": False,
                },
            },
        )

        self.assertEqual(len(segments), 1)
        self.assertIn("media_start", segments[0])
        self.assertIn("media_end", segments[0])
        self.assertIn("media_source_time", segments[0])
        self.assertGreaterEqual(segments[0]["media_start"], 0)
        self.assertGreater(segments[0]["media_end"], segments[0]["media_start"])

    def test_segment_media_bounds_crops_long_window_around_phrase(self):
        media_start, media_end = worker.segment_media_bounds(
            100.0,
            112.0,
            "Today I want to talk about the plan because honestly we need to figure out what happens next before we move on.",
            "what happens next",
            False,
        )

        self.assertGreater(media_start, 100.0)
        self.assertLess(media_end, 112.35)
        self.assertLessEqual(media_end - media_start, 6.25)

    def test_function_frame_phrase_can_start_with_it(self):
        self.assertTrue(worker.usable_phrase("It turns out that I was wrong.", "it turns out"))

    def test_phrase_review_keeps_score_four_and_marks_score_three_review(self):
        segments = [
            {
                "id": "seg_0001",
                "start": 0.0,
                "end": 2.0,
                "source_time": "00:00:00.000 - 00:00:02.000",
                "text": "Honestly, it's such a nice Monday morning.",
                "phrase": "key expression",
                "score": 3.4,
                "recommendation": 3,
            },
            {
                "id": "seg_0002",
                "start": 3.0,
                "end": 5.0,
                "source_time": "00:00:03.000 - 00:00:05.000",
                "text": "It turns out that I was wrong.",
                "phrase": "key expression",
                "score": 3.4,
                "recommendation": 3,
            },
        ]
        reviews = {
            "seg_0001": {
                "decision": "keep",
                "phrase": "such a nice",
                "value_score": 4,
                "reason": "自然赞叹框架。",
                "card_focus": "训练 such a nice + 名词。",
            },
            "seg_0002": {
                "decision": "keep",
                "phrase": "it turns out",
                "value_score": 3,
                "reason": "可学但偏基础。",
                "card_focus": "训练转折发现。",
            },
        }

        kept, skipped = worker.apply_phrase_review_decisions(segments, reviews, {"level": "B1"})

        self.assertEqual(skipped, [])
        self.assertEqual([item["phrase"] for item in kept], ["such a nice", "it turns out"])
        self.assertEqual(kept[0]["phrase_review_status"], "recommended")
        self.assertEqual(kept[1]["phrase_review_status"], "needs_review")

    def test_phrase_review_skip_does_not_generate_candidate(self):
        segment = {
            "id": "seg_0001",
            "start": 0.0,
            "end": 2.0,
            "source_time": "00:00:00.000 - 00:00:02.000",
            "text": "They are literally working with nerfed Nvidia GPUs.",
            "phrase": "working with",
            "score": 3.5,
            "recommendation": 4,
        }
        reviews = {
            "seg_0001": {
                "decision": "skip",
                "phrase": "working with",
                "value_score": 2,
                "reason": "",
                "reject_reason": "半截泛短语。",
            }
        }

        kept, skipped = worker.apply_phrase_review_decisions([segment], reviews, {"level": "B1"})

        self.assertEqual(kept, [])
        self.assertEqual(skipped[0]["cards"], [])
        self.assertEqual(skipped[0]["phrase_review_status"], "reject")
        self.assertIn("半截泛短语", skipped[0]["phrase_reject_reason"])

    def test_phrase_review_rejects_phrase_not_in_sentence_without_repair(self):
        segment = {
            "id": "seg_0001",
            "start": 0.0,
            "end": 2.0,
            "source_time": "00:00:00.000 - 00:00:02.000",
            "text": "Honestly, it's such a nice Monday morning.",
            "phrase": "key expression",
            "score": 3.4,
            "recommendation": 3,
        }
        reviews = {
            "seg_0001": {
                "decision": "keep",
                "phrase": "in the mood for",
                "value_score": 5,
                "reason": "错误词伙。",
            }
        }

        kept, skipped = worker.apply_phrase_review_decisions([segment], reviews, {"level": "B1"})

        self.assertEqual(kept, [])
        self.assertEqual(skipped[0]["phrase_review_status"], "reject")
        self.assertIn("不在原句", skipped[0]["phrase_reject_reason"])

    def test_duplicate_phrase_segments_keep_two_best_contexts(self):
        segments = [
            {"id": "seg_0001", "start": 0.0, "text": "I figured it out.", "phrase": "figured it out", "score": 4.0, "phrase_value_score": 4},
            {"id": "seg_0002", "start": 5.0, "text": "We figured it out.", "phrase": "figured it out", "score": 4.5, "phrase_value_score": 5},
            {"id": "seg_0003", "start": 9.0, "text": "They figured it out.", "phrase": "figured it out", "score": 3.8, "phrase_value_score": 4},
        ]

        kept, duplicates = worker.split_duplicate_phrase_segments(segments)

        self.assertEqual({item["id"] for item in kept}, {"seg_0001", "seg_0002"})
        self.assertEqual([item["id"] for item in duplicates], ["seg_0003"])
        self.assertEqual(duplicates[0]["phrase_review_status"], "duplicate")

    def test_review_failure_falls_back_to_original_segments(self):
        segment = {
            "id": "seg_0001",
            "start": 0.0,
            "end": 2.0,
            "source_time": "00:00:00.000 - 00:00:02.000",
            "text": "Honestly, it's such a nice Monday morning.",
            "phrase": "key expression",
            "score": 3.4,
            "recommendation": 3,
        }
        original = worker.compatible_chat_completion

        def failing_chat(*_args, **_kwargs):
            raise RuntimeError("network down")

        worker.compatible_chat_completion = failing_chat
        try:
            kept, skipped, warning = worker.review_phrase_candidates_with_mimo(
                {
                    "level": "B1",
                    "max_segments": 10,
                    "api_config": {
                        "provider": "mimo",
                        "api_key": "test-key",
                        "model": "mimo-test",
                        "base_url": "https://api.xiaomimimo.com/v1",
                    },
                },
                [segment],
            )
        finally:
            worker.compatible_chat_completion = original

        self.assertEqual(kept, [segment])
        self.assertEqual(skipped, [])
        self.assertIn("回退", warning)

    def test_mock_mimo_review_filters_twenty_candidates(self):
        keep_items = [
            ("in the mood for", "I'm suddenly in the mood for coffee."),
            ("figure out", "We need to figure out the answer."),
            ("it turns out", "It turns out that I was wrong."),
            ("let you down", "I don't want to let you down."),
            ("ended up", "We ended up at home."),
            ("find out", "Let's find out what happened."),
            ("come up with", "Can you come up with a plan?"),
            ("get away with", "He can't get away with that."),
            ("run into", "I might run into her later."),
            ("take it personally", "Please don't take it personally."),
        ]
        segments = []
        decisions = []
        for index, (phrase, text) in enumerate(keep_items, start=1):
            segment_id = f"seg_{index:04d}"
            segments.append(
                {
                    "id": segment_id,
                    "start": float(index),
                    "end": float(index) + 2,
                    "source_time": "00:00:00.000 - 00:00:02.000",
                    "text": text,
                    "phrase": "key expression",
                    "score": 3.4,
                    "recommendation": 3,
                }
            )
            decisions.append(
                {
                    "id": segment_id,
                    "decision": "keep",
                    "phrase": phrase,
                    "value_score": 4,
                    "reason": "可迁移表达。",
                    "card_focus": "训练真实口语表达。",
                    "reject_reason": "",
                }
            )
        for index in range(11, 21):
            segment_id = f"seg_{index:04d}"
            segments.append(
                {
                    "id": segment_id,
                    "start": float(index),
                    "end": float(index) + 2,
                    "source_time": "00:00:00.000 - 00:00:02.000",
                    "text": "They are literally working with nerfed Nvidia GPUs.",
                    "phrase": "working with",
                    "score": 3.4,
                    "recommendation": 3,
                }
            )
            decisions.append(
                {
                    "id": segment_id,
                    "decision": "skip",
                    "phrase": "working with",
                    "value_score": 2,
                    "reason": "",
                    "card_focus": "",
                    "reject_reason": "半截泛短语。",
                }
            )

        original = worker.compatible_chat_completion

        def fake_chat(*_args, **_kwargs):
            return {"choices": [{"message": {"content": worker.json.dumps({"candidates": decisions})}}]}

        worker.compatible_chat_completion = fake_chat
        try:
            kept, skipped, warning = worker.review_phrase_candidates_with_mimo(
                {
                    "level": "B1",
                    "max_segments": 35,
                    "api_config": {
                        "provider": "mimo",
                        "api_key": "test-key",
                        "model": "mimo-test",
                        "base_url": "https://api.xiaomimimo.com/v1",
                    },
                },
                segments,
                batch_size=20,
            )
        finally:
            worker.compatible_chat_completion = original

        self.assertIsNone(warning)
        self.assertEqual(len(kept), 10)
        self.assertEqual(len(skipped), 10)
        self.assertTrue(all(item["phrase_review_status"] == "recommended" for item in kept))
        self.assertTrue(all(item["phrase_review_status"] == "reject" for item in skipped))

    def test_mimo_review_over_strict_result_promotes_local_candidates_to_review(self):
        segments = [
            {
                "id": f"seg_{index:04d}",
                "start": float(index),
                "end": float(index) + 2.0,
                "source_time": f"00:00:{index:02d}.000 - 00:00:{index + 2:02d}.000",
                "text": text,
                "phrase": "key expression",
                "score": 3.4,
                "recommendation": 3,
            }
            for index, text in enumerate(
                [
                    "I'm suddenly in the mood for coffee.",
                    "Honestly, it's such a nice Monday morning.",
                    "It turns out that I was wrong.",
                    "You never know who might need this.",
                    "This changed my life in a small way.",
                    "We need to figure out the answer.",
                    "Feel free to send me the file.",
                    "I get it, starting can feel awkward.",
                    "This routine helps in the long run.",
                    "Just pick up your camera today.",
                    "The plan can work from the start.",
                    "You can make a living doing this.",
                ],
                1,
            )
        ]
        decisions = [
            {
                "id": "seg_0001",
                "decision": "keep",
                "phrase": "in the mood for",
                "value_score": 5,
                "reason": "高价值表达。",
                "card_focus": "训练偏好表达。",
                "reject_reason": "",
            },
            *[
                {
                    "id": segment["id"],
                    "decision": "skip",
                    "phrase": "working with",
                    "value_score": 2,
                    "reason": "",
                    "card_focus": "",
                    "reject_reason": "过窄。",
                }
                for segment in segments[1:]
            ],
        ]

        def fake_chat(*_args, **_kwargs):
            return {"choices": [{"message": {"content": worker.json.dumps({"candidates": decisions})}}]}

        original_chat = worker.compatible_chat_completion
        worker.compatible_chat_completion = fake_chat
        try:
            kept, skipped, warning = worker.review_phrase_candidates_with_mimo(
                {
                    "level": "B1",
                    "max_segments": 12,
                    "api_config": {
                        "provider": "mimo",
                        "api_key": "test-key",
                        "model": "mimo-test",
                        "base_url": "https://api.xiaomimimo.com/v1",
                    },
                },
                segments,
                batch_size=20,
            )
        finally:
            worker.compatible_chat_completion = original_chat

        self.assertIsNone(warning)
        self.assertGreaterEqual(len(kept), 8)
        self.assertEqual(kept[0]["phrase_review_status"], "recommended")
        self.assertTrue(any(item["phrase_review_status"] == "needs_review" for item in kept))
        self.assertLess(len(skipped), len(segments) - 1)

    def test_score_three_review_card_is_not_enabled_by_default(self):
        segments = [
            {
                "id": "seg_0001",
                "text": "It turns out that I was wrong.",
                "phrase": "it turns out",
                "source_time": "00:00:01.000 - 00:00:04.000",
                "phrase_value_score": 3,
                "phrase_review_status": "needs_review",
                "phrase_decision_reason": "可学但需要确认。",
            }
        ]
        ai_payload = {
            "segments": [
                {
                    "id": "seg_0001",
                    "cards": [
                        {
                            "type": "phrase",
                            "phrase": "it turns out",
                            "chinese": "结果证明我错了。",
                            "definition": "用来引出后来发现的真实情况。",
                            "collocations": "it turns out that + clause / as it turns out",
                            "context": "解释事后发现和原先想法不同。",
                            "example": "It turns out that she was right.",
                            "chinese_feel": "中文里的“结果发现”。",
                            "why": "常见的转折说明框架。",
                            "difficulty": "B1 日常交流",
                            "teacher_note": "turns out 后面常接 that 从句。",
                            "cloze": "____ that I was wrong.",
                        }
                    ],
                }
            ]
        }

        merged, _ = worker.merge_ai_cards(segments, ai_payload, ["phrase"], "B1")

        self.assertEqual(merged[0]["cards"][0]["quality"]["status"], "needs_review")
        self.assertFalse(merged[0]["cards"][0]["enabled"])

    def test_segment_builder_rejects_unbalanced_quote_fragments(self):
        cues = [worker.Cue(1, 0.0, 2.4, 'Suddenly, I woke up and shouted, "Stop the car.')]
        segments = worker.build_segments(
            cues,
            {
                "level": "B1",
                "max_segments": 4,
                "content_toggles": {
                    "daily": True,
                    "slang": True,
                    "sarcasm": True,
                    "business": True,
                    "culture": True,
                    "profanity": False,
                    "romance": False,
                    "rare": False,
                },
            },
        )

        self.assertEqual(segments, [])

    def test_quality_rejects_template_noise_and_bad_collocation(self):
        card = {
            "type": "phrase",
            "english": "Not because China caught up, but because of what happens next.",
            "phrase": "what happens next",
            "chinese": "本地草稿：请在预览页用模型精修或手动改成自然中文。",
            "definition": "what happens next 是这句里值得优先熟悉的表达块。",
            "collocations": "what happens next; not really what happens next; use it in short spoken replies",
            "context": "真实口语中，这类表达通常用来快速说明态度、心情或行动意图。",
            "example": "Not because China caught up, but because of what happens next.",
            "chinese_feel": "中文里更接近自然顺口的一句话，而不是逐词硬翻。",
            "why": "这句短、口语感强，适合做听力和词伙记忆。",
            "teacher_note": "这句短、口语感强，适合做听力和词伙记忆。",
            "cloze": "Not because China caught up, but because of ____.",
        }
        quality = worker.assess_card_quality(card, {"text": card["english"]}, "ai")

        self.assertEqual(quality["status"], "reject")
        self.assertIn("字段像模板废话", quality["issues"])
        self.assertIn("搭配不自然", quality["issues"])

    def test_quality_rejects_generic_learning_noise(self):
        card = {
            "type": "phrase",
            "english": "I'm suddenly in the mood for Greek food.",
            "phrase": "in the mood for",
            "chinese": "I suddenly want Greek food.",
            "definition": "This phrase is useful in daily English.",
            "collocations": "in the mood for + natural object",
            "context": "这句短、口语感强，适合做听力和词伙记忆。",
            "example": "I'm suddenly in the mood for Italian food.",
            "chinese_feel": "这句短、口语感强，适合做听力和词伙记忆。",
            "why": "这句短、口语感强，适合做听力和词伙记忆。",
            "teacher_note": "这句短、口语感强，适合做听力和词伙记忆。",
            "difficulty": "B1 日常交流",
            "cloze": "I'm suddenly ____ Greek food.",
        }
        quality = worker.assess_card_quality(card, {"text": card["english"]}, "ai", "B1")

        self.assertEqual(quality["status"], "reject")
        self.assertIn("字段像模板废话", quality["issues"])
        self.assertIn("中文意思不是中文", quality["issues"])
        self.assertIn("老师提示和学习理由重复", quality["issues"])

    def test_prompt_asks_model_to_skip_low_value_segments(self):
        prompt = worker.build_prompt(
            {"card_types": ["listening", "phrase", "cloze"], "language": "English", "level": "B1"},
            [
                {
                    "id": "seg_0001",
                    "source_time": "00:00:01.000 - 00:00:04.000",
                    "text": "They are literally working with nerfed Nvidia GPUs.",
                    "phrase": "working with",
                    "recommendation": 3,
                }
            ],
        )

        self.assertIn("cards: []", prompt)
        self.assertIn("working with 这种孤立泛表达", prompt)
        self.assertIn("example 必须是新的短例句", prompt)
        self.assertIn("默认每个片段只生成 1 张主卡", prompt)
        self.assertNotIn("cards 必须包含全部需要卡型", prompt)

    def test_card_planner_defaults_to_one_main_card(self):
        segment = {
            "id": "seg_0001",
            "text": "By the way, how long will it take?",
            "phrase": "by the way",
        }
        cards = worker.fallback_cards(segment, ["listening", "phrase", "cloze"], "B1")

        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["type"], "phrase")
        self.assertEqual(cards[0]["type_label"], "沉浸主卡")
        self.assertEqual(cards[0]["card_role"], "primary")

    def test_card_planner_does_not_make_cloze_just_because_guide_exists(self):
        segment = {
            "id": "seg_0001",
            "text": "Okay, Mike, you go first.",
            "phrase": "go first",
        }
        cards = worker.fallback_cards(segment, ["listening", "phrase", "cloze"], "B1")

        self.assertEqual([card["type"] for card in cards], ["phrase"])

    def test_merge_ai_cards_does_not_inflate_to_all_requested_types(self):
        segments = [
            {
                "id": "seg_0001",
                "text": "By the way, how long will it take?",
                "phrase": "by the way",
                "source_time": "00:00:01.000 - 00:00:04.000",
            }
        ]
        ai_payload = {
            "segments": [
                {
                    "id": "seg_0001",
                    "cards": [
                        {
                            "type": "phrase",
                            "phrase": "by the way",
                            "chinese": "顺便问一下，这需要多长时间？",
                            "definition": "用来顺便插入一个问题或新话题。",
                            "collocations": "by the way, + question / by the way, + new topic",
                            "context": "对话中临时补充问题。",
                            "example": "By the way, did you call her?",
                            "chinese_feel": "中文里的“对了，顺便问一下”。",
                            "why": "让转话题更自然。",
                            "difficulty": "A2 基础",
                            "teacher_note": "放在句首时常带短暂停顿。",
                            "cloze": "____, how long will it take?",
                        },
                        {
                            "type": "listening",
                            "phrase": "by the way",
                            "chinese": "顺便问一下，这需要多长时间？",
                        },
                        {
                            "type": "cloze",
                            "phrase": "by the way",
                            "chinese": "顺便问一下，这需要多长时间？",
                        },
                    ],
                }
            ]
        }
        merged, _ = worker.merge_ai_cards(segments, ai_payload, ["listening", "phrase", "cloze"], "B1")

        self.assertEqual(len(merged[0]["cards"]), 1)
        self.assertEqual(merged[0]["cards"][0]["type"], "phrase")

    def test_specialist_card_requires_explicit_ai_payload(self):
        segments = [
            {
                "id": "seg_0001",
                "text": "I'm suddenly in the mood for Greek food.",
                "phrase": "in the mood for",
                "source_time": "00:00:01.000 - 00:00:04.000",
            }
        ]
        ai_payload = {
            "segments": [
                {
                    "id": "seg_0001",
                    "cards": [
                        {
                            "type": "phrase",
                            "phrase": "in the mood for",
                            "chinese": "我突然想吃希腊菜。",
                            "definition": "表示此刻想要某种东西或想做某事。",
                            "collocations": "in the mood for dinner / in the mood for a walk",
                            "context": "说自己当下的兴趣、胃口或状态。",
                            "example": "I'm not in the mood for a long meeting.",
                            "chinese_feel": "中文里接近“突然想... / 有点想...”。",
                            "why": "这个表达能自然说明当下想不想做某事。",
                            "difficulty": "B1 日常交流",
                            "teacher_note": "for 后面接名词或动名词，不接完整句。",
                            "cloze": "I'm suddenly ____ Greek food.",
                        }
                    ],
                }
            ]
        }
        merged, _ = worker.merge_ai_cards(segments, ai_payload, ["phrase", "cloze"], "B1")

        self.assertEqual([card["type"] for card in merged[0]["cards"]], ["phrase"])

    def test_explicit_specialist_card_can_be_kept(self):
        segments = [
            {
                "id": "seg_0001",
                "text": "I'm suddenly in the mood for Greek food.",
                "phrase": "in the mood for",
                "source_time": "00:00:01.000 - 00:00:04.000",
            }
        ]
        ai_payload = {
            "segments": [
                {
                    "id": "seg_0001",
                    "cards": [
                        {
                            "type": "phrase",
                            "phrase": "in the mood for",
                            "chinese": "我突然想吃希腊菜。",
                            "definition": "表示此刻想要某种东西或想做某事。",
                            "collocations": "in the mood for dinner / in the mood for a walk",
                            "context": "说自己当下的兴趣、胃口或状态。",
                            "example": "I'm not in the mood for a long meeting.",
                            "chinese_feel": "中文里接近“突然想... / 有点想...”。",
                            "why": "这个表达能自然说明当下想不想做某事。",
                            "difficulty": "B1 日常交流",
                            "teacher_note": "for 后面接名词或动名词，不接完整句。",
                            "cloze": "I'm suddenly ____ Greek food.",
                        },
                        {
                            "type": "cloze",
                            "phrase": "in the mood for",
                            "chinese": "我突然想吃希腊菜。",
                            "definition": "表示此刻有想做某事或想要某物的兴致。",
                            "collocations": "in the mood for coffee / in the mood for talking",
                            "context": "主动表达自己的意愿或状态。",
                            "example": "Are you in the mood for coffee?",
                            "chinese_feel": "中文里像“有点想...”。",
                            "why": "适合训练 for 后面接名词或动名词的输出。",
                            "difficulty": "B1 日常交流",
                            "teacher_note": "挖空的是整块表达，复习时要一次说出 in the mood for。",
                            "cloze": "I'm suddenly ____ Greek food.",
                        },
                    ],
                }
            ]
        }
        merged, _ = worker.merge_ai_cards(segments, ai_payload, ["phrase", "cloze"], "B1")

        self.assertEqual([card["type"] for card in merged[0]["cards"]], ["phrase", "cloze"])
        self.assertTrue(all(card["enabled"] for card in merged[0]["cards"]))

    def test_english_subtitle_selection_prefers_original_tracks(self):
        self.assertEqual(worker.subtitle_language_args("English"), "en,en-orig,en-GB,en-US")

    def test_project_media_prefix_is_unique_per_source(self):
        first = worker.project_media_prefix({"title": "Deck", "source_url": "https://youtu.be/one", "created_at": 1})
        second = worker.project_media_prefix({"title": "Deck", "source_url": "https://youtu.be/two", "created_at": 2})
        third = worker.project_media_prefix({"title": "Deck", "source_url": "https://youtu.be/one", "created_at": 1}, 177)

        self.assertNotEqual(first, second)
        self.assertNotEqual(first, third)
        self.assertTrue(first.startswith("Deck_"))

    def test_card_template_uses_responsive_canvas_and_fit_text(self):
        self.assertIn("height: min(1500px, 90vh)", worker.CARD_CSS)
        self.assertIn("--font-scale", worker.CARD_CSS)
        self.assertIn("data-fit", worker.BACK_TEMPLATE)
        self.assertIn("fitResponsiveText", worker.BACK_TEMPLATE)
        self.assertIn("fitAdaptiveCard", worker.BACK_TEMPLATE)
        self.assertIn("hasHiddenOverflow", worker.BACK_TEMPLATE)
        self.assertIn('class="teacher" data-fit', worker.BACK_TEMPLATE)
        self.assertNotIn("@media (max-height: 980px)", worker.CARD_CSS)


if __name__ == "__main__":
    unittest.main()
