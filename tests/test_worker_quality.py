import base64
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
from contextlib import redirect_stderr
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = ROOT / "workers" / "anki_worker.py"
VERIFY_APKG_PATH = ROOT / "workers" / "verify_apkg.py"


def load_worker():
    spec = importlib.util.spec_from_file_location("anki_worker_for_tests", WORKER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


worker = load_worker()
from acg import ytdlp_support


def load_verify_apkg():
    spec = importlib.util.spec_from_file_location("verify_apkg_for_tests", VERIFY_APKG_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


verify_apkg = load_verify_apkg()


class WorkerQualityTests(unittest.TestCase):
    def setUp(self):
        # Older behavioral tests use tiny byte strings as APKG stand-ins and
        # exercise post-import/media logic rather than the production APKG
        # contract gate. Keep those tests narrow; dedicated preflight tests use
        # the real helper and cover fail-closed behavior.
        self._production_import_preflight = worker._legacy_worker.preflight_anki_import_apkg

        def _allow_legacy_fake_apkg_preflight(payload, export_result):
            path_text = str(export_result.get("apkg_path") or payload.get("apkg_path") or "")
            path = Path(path_text) if path_text else Path()
            if not path.exists() or not path.is_file():
                return {
                    "ok": False,
                    "message": f"找不到要导入的 APKG：{path}",
                    "failed_checks": ["apkg_missing_for_import"],
                }
            if path.suffix.lower() != ".apkg":
                return {
                    "ok": False,
                    "message": f"导入路径不是 APKG 文件：{path}",
                    "failed_checks": ["apkg_invalid_for_import"],
                }
            stat = path.stat()
            manifest = (
                export_result.get("media_manifest")
                if isinstance(export_result.get("media_manifest"), dict)
                else {}
            )
            media_summary = (
                export_result.get("media_summary")
                if isinstance(export_result.get("media_summary"), dict)
                else {}
            )
            media_files = media_summary.get("media_files")
            if not isinstance(media_files, int) or isinstance(media_files, bool):
                media_files = len(manifest)
            media_bytes = media_summary.get("media_bytes")
            if not isinstance(media_bytes, int) or isinstance(media_bytes, bool):
                media_bytes = sum(
                    int(entry.get("bytes") or 0)
                    for entry in manifest.values()
                    if isinstance(entry, dict)
                )
            return {
                "ok": True,
                "message": "test-only APKG fixture accepted",
                "failed_checks": [],
                "apkg_path": str(path),
                "apkg_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "apkg_size_bytes": stat.st_size,
                "apkg_mtime_ms": int(stat.st_mtime * 1000),
                "deck_name": str(export_result.get("deck_name") or payload.get("deck_name") or ""),
                "deck_kind": str(export_result.get("deck_kind") or payload.get("deck_kind") or ""),
                "media_dir": str(export_result.get("media_dir") or payload.get("media_dir") or ""),
                "cards": int(export_result.get("cards") or payload.get("expected_cards") or 0),
                "media_manifest": manifest,
                "media_files": media_files,
                "media_bytes": media_bytes,
                "note_model_contract": {},
            }

        worker._legacy_worker.preflight_anki_import_apkg = _allow_legacy_fake_apkg_preflight
        self.addCleanup(
            setattr,
            worker._legacy_worker,
            "preflight_anki_import_apkg",
            self._production_import_preflight,
        )
    def _ai_config(self):
        return {
            "provider": "gemini-vertex",
            "model": "gemini-3.1-pro-preview",
            "project": "test-project",
            "location": "global",
            "disable_ai_review_cache": True,
            "disable_card_generation_cache": True,
        }

    def test_url_video_mode_overrides_stale_skip_video_flag(self):
        legacy = worker._legacy_worker
        payload = {
            "source_url": "https://example.com/watch",
            "url_import_mode": "video",
            "skip_video_slicing": True,
            "language": "English",
        }

        self.assertFalse(legacy.wants_subtitle_only(payload))
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_root = Path(temp_dir)
            source_dir = cache_root / "url_deadbeef"
            source_dir.mkdir()
            (source_dir / "source.mp4").write_bytes(b"fake video")
            (source_dir / "source.en.srt").write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nHello there.\n",
                encoding="utf-8",
            )

            cached = legacy.find_cached_url_source(cache_root, "deadbeef", payload)
            self.assertIsNotNone(cached)
            assert cached is not None
            self.assertEqual(cached["download_mode"], "video")
            self.assertFalse(cached["skip_video_slicing"])
            project = {
                "source_mode": "url",
                "url_import_mode": "video",
                "skip_video_slicing": True,
                "video_path": cached["video_path"],
                "source_info": cached,
            }
            self.assertFalse(legacy.video_free_export_allowed(project))
            self.assertTrue(legacy.video_media_required_for_export(project))

            stale_transcript_project = {
                "source_mode": "url",
                "skip_video_slicing": True,
                "video_path": cached["video_path"],
                "source_info": {"transcript_only": True},
            }
            self.assertFalse(legacy.video_free_export_allowed(stale_transcript_project))
            self.assertTrue(legacy.video_media_required_for_export(stale_transcript_project))

    def test_url_subtitle_mode_still_allows_video_free_export(self):
        legacy = worker._legacy_worker
        self.assertTrue(legacy.wants_subtitle_only({"url_import_mode": "subtitles", "skip_video_slicing": False}))
        self.assertTrue(
            legacy.video_free_export_allowed(
                {
                    "source_mode": "url",
                    "url_import_mode": "subtitles",
                    "skip_video_slicing": False,
                    "video_path": "source.mp4",
                    "source_info": {"download_mode": "video", "transcript_only": False},
                }
            )
        )

    def test_source_mode_helpers_match_worker_boundary(self):
        from acg import source_modes

        url_video_project = {
            "source_mode": "url",
            "url_import_mode": "video",
            "skip_video_slicing": True,
            "video_path": "source.mp4",
            "source_info": {"download_mode": "video", "transcript_only": True},
        }
        subtitle_project = {
            "source_mode": "url",
            "url_import_mode": "subtitles",
            "skip_video_slicing": False,
            "video_path": "source.mp4",
            "source_info": {"download_mode": "video", "transcript_only": False},
        }
        document_project = {"source_mode": "document"}

        self.assertFalse(worker._legacy_worker.wants_subtitle_only(url_video_project))
        self.assertEqual(
            worker._legacy_worker.video_free_export_allowed(url_video_project),
            source_modes.video_free_export_allowed(url_video_project),
        )
        self.assertEqual(
            worker._legacy_worker.video_media_required_for_export(url_video_project),
            source_modes.video_media_required_for_export(url_video_project),
        )
        self.assertTrue(source_modes.video_free_export_allowed(subtitle_project))
        self.assertTrue(source_modes.video_free_export_allowed(document_project))

    def test_language_text_helpers_match_worker_boundary(self):
        from acg import language_text

        languages = ["", "English", "français", "es-MX", "日本語", "русский", "unknown"]
        for language in languages:
            self.assertEqual(
                worker._legacy_worker.normalize_learning_language(language),
                language_text.normalize_learning_language(language),
            )
            self.assertEqual(
                worker._legacy_worker.pronunciation_profile(language),
                language_text.pronunciation_profile(language),
            )

        samples = [
            "You're feeling completely lost.",
            "we'll test overlap",
            "中文语境义",
            "日本語の例",
            "Русский текст",
            "",
        ]
        for sample in samples:
            self.assertEqual(worker._legacy_worker.overlap_words(sample), language_text.overlap_words(sample))
            self.assertEqual(
                worker._legacy_worker.expanded_overlap_words(sample),
                language_text.expanded_overlap_words(sample),
            )
            self.assertEqual(worker._legacy_worker.has_cjk(sample), language_text.has_cjk(sample))
            self.assertEqual(worker._legacy_worker.has_japanese_kana(sample), language_text.has_japanese_kana(sample))
            self.assertEqual(worker._legacy_worker.has_cyrillic(sample), language_text.has_cyrillic(sample))
            self.assertEqual(worker._legacy_worker.has_latin_letter(sample), language_text.has_latin_letter(sample))

        self.assertTrue(worker._legacy_worker.looks_like_target_language_text("bonjour", "fr"))
        self.assertTrue(language_text.looks_like_target_language_text("bonjour", "fr"))
        self.assertFalse(worker._legacy_worker.looks_like_target_language_text("需要人工确认", "en"))
        self.assertFalse(language_text.looks_like_target_language_text("需要人工确认", "en"))
        self.assertEqual(
            worker._legacy_worker.word_overlap_ratio("You're completely lost", "you are lost"),
            language_text.word_overlap_ratio("You're completely lost", "you are lost"),
        )
        self.assertEqual(worker._legacy_worker.TTS_LANGUAGE_FALLBACKS, language_text.TTS_LANGUAGE_FALLBACKS)

    def test_service_error_helpers_match_worker_boundary(self):
        from acg import service_errors

        messages = [
            "API HTTP 429: quota exceeded",
            "TTS download HTTP 500: connection reset",
            "HTTP Error 403: Forbidden",
            "not an http status",
        ]
        for message in messages:
            self.assertEqual(
                worker._legacy_worker.http_status_from_error_message(message),
                service_errors.http_status_from_error_message(message),
            )

        for kind in ("model", "tts", "unknown"):
            self.assertEqual(worker._legacy_worker.service_error_codes(kind), service_errors.service_error_codes(kind))
            self.assertEqual(worker._legacy_worker.service_stage(kind), service_errors.service_stage(kind))
            self.assertEqual(worker._legacy_worker.service_label(kind), service_errors.service_label(kind))
            for category in ("timeout", "auth", "quota", "not_found", "connection", "unknown"):
                self.assertEqual(
                    worker._legacy_worker.service_error_message(kind, category, "detail"),
                    service_errors.service_error_message(kind, category, "detail"),
                )

        errors = [
            RuntimeError("Gemini Vertex 没有返回正文：输出预算被 thinking 消耗完，请提高 maxOutputTokens。"),
            TimeoutError("request timed out"),
            urllib.error.HTTPError("https://example.test", 403, "Forbidden", None, None),
            RuntimeError("API HTTP 429: resource exhausted quota"),
            RuntimeError("model not found"),
            urllib.error.URLError("getaddrinfo failed"),
            RuntimeError("unexpected provider failure"),
        ]
        for kind in ("model", "tts"):
            for err in errors:
                self.assertEqual(
                    worker._legacy_worker.classify_service_error(err, kind=kind),
                    service_errors.classify_service_error(err, kind=kind),
                )

        worker_cases = [
            (RuntimeError("Gemini API HTTP 500"), "generate"),
            (RuntimeError("TTS HTTP 400 invalid argument"), "test_tts"),
            (RuntimeError("plain failure"), "unknown_command"),
        ]
        for err, command in worker_cases:
            self.assertEqual(
                worker._legacy_worker.classify_worker_exception(err, command=command),
                service_errors.classify_worker_exception(err, command=command),
            )

    def test_parse_srt_strips_non_speech_stage_directions(self):
        legacy = worker._legacy_worker
        with tempfile.TemporaryDirectory() as temp_dir:
            subtitle = Path(temp_dir) / "stage-markers.srt"
            subtitle.write_text(
                "\n".join(
                    [
                        "1",
                        "00:00:01,000 --> 00:00:04,000",
                        "[Applause] [Applause] when I was 27 years old",
                        "",
                        "2",
                        "00:00:04,100 --> 00:00:06,000",
                        "[Music] I left a very demanding job.",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            cues = legacy.parse_srt(str(subtitle))

        joined = " ".join(cue.text for cue in cues)
        self.assertNotIn("Applause", joined)
        self.assertNotIn("Music", joined)
        self.assertIn("when I was 27 years old", joined)
        self.assertIn("I left a very demanding job", joined)

    def test_learning_point_card_source_sentence_preserves_complete_evidence(self):
        from acg.commands import generate_cards_from_learning_points as command

        point = {
            "source_sentence": (
                "when the work came back I calculated grades what struck me was that IQ was not the only "
                "difference between my best and my worst students some of my"
            ),
            "exact_span": "what struck me was that",
            "answer_core": "what struck me was that",
            "exact_span_start": 44,
            "exact_span_end": 67,
        }

        sentence = command._source_sentence_for_card(point)

        self.assertIn("what struck me was that", sentence)
        self.assertEqual(sentence, point["source_sentence"])

    def _patch_learning_point_ai_review(self):
        original = worker._legacy_worker.gemini_vertex_generate_content

        def fake_gemini_vertex_generate_content(api, prompt, **kwargs):
            marker = "字幕和候选_JSON_START"
            compact = json.loads(prompt.split(marker, 1)[1].strip())
            sources = []
            for source in compact:
                reviews = []
                for candidate in source.get("local_candidates", []):
                    answer = candidate.get("answer_core") or candidate.get("exact_span")
                    value = float(candidate.get("local_value_score") or 3)
                    decision = "candidate" if answer == "right now" or value < 4 else "recommend"
                    reviews.append(
                        {
                            "id": candidate["id"],
                            "decision": decision,
                            "value_score": 3 if decision == "candidate" else max(4, value),
                            "estimated_level": "A1" if answer == "right now" else "B2" if answer == "messing with us" else candidate.get("local_level") or "B1",
                            "exact_span": candidate.get("exact_span"),
                            "answer_core": answer,
                            "normalized_answer": candidate.get("normalized_answer") or answer,
                            "candidate_kind": candidate.get("candidate_kind"),
                            "phrase_type": candidate.get("phrase_type"),
                            "learning_action": candidate.get("learning_action") or f"训练 {answer}。",
                            "reason": "AI mock 精筛通过。",
                            "status_reason": "AI mock 推荐。" if decision == "recommend" else "AI mock 候选。",
                        }
                    )
                sources.append({"source_segment_id": source["source_segment_id"], "reviews": reviews, "new_learning_points": []})
            return json.dumps({"sources": sources}, ensure_ascii=False)

        worker._legacy_worker.gemini_vertex_generate_content = fake_gemini_vertex_generate_content
        return original

    def test_extract_learning_points_finds_core_subtitle_points(self):
        original = self._patch_learning_point_ai_review()
        cues = [
            worker.Cue(1, 1.0, 3.0, "I'm not really in the mood for this right now."),
            worker.Cue(2, 4.0, 6.0, "It turns out he was just messing with us."),
            worker.Cue(3, 7.0, 9.0, "It's not that I don't like it, it's just that I'm tired."),
            worker.Cue(4, 10.0, 12.0, "Can you run the register for a minute?"),
        ]

        try:
            result = worker.extract_learning_points_from_subtitles(
                {
                    "language": "en",
                    "level": "B1",
                    "language_focus": ["phrases", "vocabulary", "grammar", "listening"],
                    "api_config": self._ai_config(),
                },
                cues,
            )
        finally:
            worker._legacy_worker.gemini_vertex_generate_content = original
        points = result["learning_points"]
        answers = {point["answer_core"]: point for point in points}

        self.assertEqual(result["review_basis"], "ai_reviewed")
        self.assertIn("in the mood for", answers)
        self.assertEqual(answers["in the mood for"]["type"], "phrase")
        self.assertEqual(answers["in the mood for"]["review_source"], "ai")
        self.assertIn("messing with us", answers)
        self.assertEqual(answers["messing with us"]["level"], "B2")
        self.assertIn("run the register", answers)
        self.assertIn("register", answers)
        self.assertEqual(answers["register"]["type"], "vocab_usage")
        self.assertTrue(any(point["type"] == "grammar" for point in points))
        self.assertGreaterEqual(result["learning_point_summary"]["recommended"], 5)

    def test_extract_learning_points_keeps_basic_points_as_candidates(self):
        original = self._patch_learning_point_ai_review()
        cues = [worker.Cue(1, 1.0, 3.0, "I'm not really in the mood for this right now.")]

        try:
            result = worker.extract_learning_points_from_subtitles(
                {
                    "language": "en",
                    "level": "B1",
                    "language_focus": ["phrases", "vocabulary", "grammar", "listening"],
                    "api_config": self._ai_config(),
                },
                cues,
            )
        finally:
            worker._legacy_worker.gemini_vertex_generate_content = original
        answers = {point["answer_core"]: point for point in result["learning_points"]}

        self.assertEqual(answers["right now"]["status"], "candidate_only")
        self.assertEqual(answers["right now"]["level"], "A1")
        self.assertEqual(answers["in the mood for"]["status"], "recommended")

    def test_extract_learning_points_demotes_ai_recommended_weak_new_points(self):
        original = worker._legacy_worker.gemini_vertex_generate_content

        def fake_gemini_vertex_generate_content(api, prompt, **kwargs):
            compact = json.loads(prompt.rsplit("_JSON_START", 1)[1].strip())
            sources = []
            for source in compact:
                sources.append(
                    {
                        "source_segment_id": source["source_segment_id"],
                        "reviews": [],
                        "new_learning_points": [
                            {
                                "id": f"{source['source_segment_id']}_age_groups",
                                "decision": "recommend",
                                "value_score": 4.8,
                                "estimated_level": "A2",
                                "exact_span": "age groups",
                                "answer_core": "age groups",
                                "normalized_answer": "age groups",
                                "candidate_kind": "expression",
                                "phrase_type": "collocation",
                                "learning_action": "Practice age groups as a topic label.",
                                "reason": "Model says this is useful.",
                                "status_reason": "Model recommended this noun chunk.",
                            }
                        ],
                    }
                )
            return json.dumps({"sources": sources}, ensure_ascii=False)

        worker._legacy_worker.gemini_vertex_generate_content = fake_gemini_vertex_generate_content
        try:
            result = worker.extract_learning_points_from_subtitles(
                {
                    "language": "en",
                    "level": "B1",
                    "language_focus": ["phrases", "vocabulary", "grammar", "listening"],
                    "api_config": self._ai_config(),
                },
                [worker.Cue(1, 1.0, 3.0, "There are different age groups in my school.")],
            )
        finally:
            worker._legacy_worker.gemini_vertex_generate_content = original

        point = {item["answer_core"]: item for item in result["learning_points"]}["age groups"]
        self.assertIn("weak_noun_chunk", point["recommendation_flags"])
        self.assertEqual(point["status"], "candidate_only")

    def test_extract_learning_points_soft_ai_rejects_remain_candidates(self):
        original = worker._legacy_worker.gemini_vertex_generate_content

        def fake_gemini_vertex_generate_content(api, prompt, **kwargs):
            marker = "字幕和候选_JSON_START"
            compact = json.loads(prompt.split(marker, 1)[1].strip())
            sources = []
            for source in compact:
                reviews = []
                for candidate in source.get("local_candidates", []):
                    answer = candidate.get("answer_core") or candidate.get("exact_span")
                    decision = "reject" if answer == "gonna" else "recommend"
                    reviews.append(
                        {
                            "id": candidate["id"],
                            "decision": decision,
                            "value_score": 2 if decision == "reject" else 4,
                            "estimated_level": "A1" if answer == "gonna" else "B1",
                            "exact_span": candidate.get("exact_span"),
                            "answer_core": answer,
                            "normalized_answer": candidate.get("normalized_answer") or answer,
                            "candidate_kind": candidate.get("candidate_kind"),
                            "phrase_type": candidate.get("phrase_type"),
                            "learning_action": candidate.get("learning_action") or f"训练 {answer}。",
                            "reason": "过于基础，无需单独制卡。" if decision == "reject" else "值得推荐。",
                            "status_reason": "太基础，保留为候选。" if decision == "reject" else "推荐。",
                        }
                    )
                sources.append({"source_segment_id": source["source_segment_id"], "reviews": reviews, "new_learning_points": []})
            return json.dumps({"sources": sources}, ensure_ascii=False)

        worker._legacy_worker.gemini_vertex_generate_content = fake_gemini_vertex_generate_content
        try:
            result = worker.extract_learning_points_from_subtitles(
                {
                    "language": "en",
                    "level": "B1",
                    "language_focus": ["phrases", "vocabulary", "grammar", "listening"],
                    "api_config": self._ai_config(),
                },
                [worker.Cue(1, 1.0, 3.0, "I'm gonna run the register.")],
            )
        finally:
            worker._legacy_worker.gemini_vertex_generate_content = original

        answers = {point["answer_core"]: point for point in result["learning_points"]}
        self.assertEqual(answers["gonna"]["status"], "candidate_only")
        self.assertEqual(answers["gonna"]["ai_decision"], "candidate")
        self.assertNotEqual(answers["gonna"].get("validation_status"), "hard_blocked")

    def test_extract_learning_points_reviews_nontrivial_sentences_without_local_candidates(self):
        original = worker._legacy_worker.gemini_vertex_generate_content
        reviewed_batch_sizes: list[int] = []

        def fake_gemini_vertex_generate_content(api, prompt, **kwargs):
            marker = "字幕和候选_JSON_START"
            compact = json.loads(prompt.split(marker, 1)[1].strip())
            reviewed_batch_sizes.append(len(compact))
            sources = []
            for source in compact:
                reviews = []
                for candidate in source.get("local_candidates", []):
                    answer = candidate.get("answer_core") or candidate.get("exact_span")
                    reviews.append(
                        {
                            "id": candidate["id"],
                            "decision": "recommend",
                            "value_score": 4,
                            "estimated_level": "B1",
                            "exact_span": candidate.get("exact_span"),
                            "answer_core": answer,
                            "normalized_answer": candidate.get("normalized_answer") or answer,
                            "candidate_kind": candidate.get("candidate_kind"),
                            "phrase_type": candidate.get("phrase_type"),
                            "learning_action": candidate.get("learning_action") or f"训练 {answer}。",
                            "reason": "AI mock 精筛通过。",
                            "status_reason": "推荐。",
                        }
                    )
                sources.append({"source_segment_id": source["source_segment_id"], "reviews": reviews, "new_learning_points": []})
            return json.dumps({"sources": sources}, ensure_ascii=False)

        worker._legacy_worker.gemini_vertex_generate_content = fake_gemini_vertex_generate_content
        try:
            result = worker.extract_learning_points_from_subtitles(
                {
                    "language": "en",
                    "level": "B1",
                    "language_focus": ["phrases", "vocabulary", "grammar", "listening"],
                    "api_config": self._ai_config(),
                },
                [
                    worker.Cue(1, 1.0, 2.0, "Hello."),
                    worker.Cue(2, 3.0, 4.0, "Can you run the register for a minute?"),
                    worker.Cue(3, 5.0, 6.0, "This is a perfectly ordinary sentence."),
                    worker.Cue(4, 7.0, 8.0, "Good night."),
                ],
            )
        finally:
            worker._legacy_worker.gemini_vertex_generate_content = original

        self.assertEqual(reviewed_batch_sizes, [2])
        self.assertEqual(result["quality_funnel"]["source_sentence_count"], 4)
        self.assertEqual(result["ai_reviewed_source_count"], 2)
        self.assertGreaterEqual(result["learning_point_summary"]["recommended"], 1)

    def test_ai_review_source_budget_keeps_short_subtitles_exhaustive(self):
        from acg.pipeline import learning_point_pipeline

        source_sentences = [
            {
                "id": f"src-{index}",
                "source_segment_id": f"src-{index}",
                "source_sentence": f"This useful sentence {index} explains everyday spending choices.",
                "text": f"This useful sentence {index} explains everyday spending choices.",
                "start": float(index),
                "end": float(index) + 1,
                "source_time": "00:00:00.000 - 00:00:01.000",
                "source_sentence_quality_flags": ["clean"],
            }
            for index in range(20)
        ]
        payload = {"language": "en", "level": "B1", "api_config": self._ai_config()}

        selected = learning_point_pipeline._ai_review_source_sentences(payload, source_sentences, [])

        self.assertEqual(len(selected), 20)
        self.assertEqual(payload["_ai_review_discovery_source_count"], 20)
        self.assertEqual(payload["_ai_review_discovery_source_deferred_count"], 0)

    def test_ai_review_source_budget_caps_long_discovery_but_keeps_local_candidates(self):
        from acg.pipeline import learning_point_pipeline

        source_sentences = [
            {
                "id": f"src-{index}",
                "source_segment_id": f"src-{index}",
                "source_sentence": f"This useful sentence {index} explains everyday spending choices in context.",
                "text": f"This useful sentence {index} explains everyday spending choices in context.",
                "start": float(index),
                "end": float(index) + 1,
                "source_time": "00:00:00.000 - 00:00:01.000",
                "source_sentence_quality_flags": ["clean"],
            }
            for index in range(220)
        ]
        local_points = [
            {
                "id": f"lp-{index}",
                "source_segment_id": f"src-{index}",
                "exact_span": "spending choices",
                "answer_core": "spending choices",
                "normalized_answer": "spending choices",
                "candidate_kind": "expression",
                "phrase_type": "collocation",
                "learning_action": "训练 spending choices。",
                "value_score": 4,
                "validation_status": "valid",
            }
            for index in (5, 120, 219)
        ]
        payload = {"language": "en", "level": "B1", "api_config": self._ai_config()}

        selected = learning_point_pipeline._ai_review_source_sentences(payload, source_sentences, local_points)
        selected_ids = {item["source_segment_id"] for item in selected}

        self.assertTrue({"src-5", "src-120", "src-219"} <= selected_ids)
        self.assertEqual(payload["_ai_review_local_candidate_source_count"], 3)
        self.assertEqual(payload["_ai_review_discovery_source_count"], 64)
        self.assertEqual(payload["_ai_review_discovery_source_deferred_count"], 153)
        self.assertEqual(len(selected), 67)

    def test_extract_learning_points_reuses_ai_review_batch_cache_when_explicitly_enabled(self):
        original = worker._legacy_worker.gemini_vertex_generate_content
        calls = {"count": 0}
        cwd = os.getcwd()

        def fake_gemini_vertex_generate_content(api, prompt, **kwargs):
            calls["count"] += 1
            marker = "字幕和候选_JSON_START"
            compact = json.loads(prompt.split(marker, 1)[1].strip())
            sources = []
            for source in compact:
                reviews = []
                for candidate in source.get("local_candidates", []):
                    answer = candidate.get("answer_core") or candidate.get("exact_span")
                    reviews.append(
                        {
                            "id": candidate["id"],
                            "decision": "recommend",
                            "value_score": 4,
                            "estimated_level": "B1",
                            "exact_span": candidate.get("exact_span"),
                            "answer_core": answer,
                            "normalized_answer": candidate.get("normalized_answer") or answer,
                            "candidate_kind": candidate.get("candidate_kind"),
                            "phrase_type": candidate.get("phrase_type"),
                            "learning_action": candidate.get("learning_action") or f"训练 {answer}。",
                            "reason": "首次 AI 精筛结果。",
                            "status_reason": "推荐。",
                        }
                    )
                sources.append({"source_segment_id": source["source_segment_id"], "reviews": reviews, "new_learning_points": []})
            return json.dumps({"sources": sources}, ensure_ascii=False)

        worker._legacy_worker.gemini_vertex_generate_content = fake_gemini_vertex_generate_content
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                os.chdir(temp_dir)
                payload = {
                    "language": "en",
                    "level": "B1",
                    "reuse_ai_review_cache": True,
                    "language_focus": ["phrases", "vocabulary", "grammar", "listening"],
                    "api_config": {
                        "provider": "gemini-vertex",
                        "model": "gemini-3.1-pro-preview",
                        "project": "test-project",
                        "location": "global",
                    },
                }
                cues = [worker.Cue(1, 1.0, 3.0, "Can you run the register for a minute?")]
                first = worker.extract_learning_points_from_subtitles(payload, cues)
                second = worker.extract_learning_points_from_subtitles(payload, cues)
                os.chdir(cwd)
        finally:
            os.chdir(cwd)
            worker._legacy_worker.gemini_vertex_generate_content = original

        self.assertEqual(calls["count"], 1)
        self.assertEqual(first["ai_reviewed_source_count"], 1)
        self.assertEqual(second["ai_reviewed_source_count"], 1)
        self.assertEqual(first["quality_funnel"]["ai_review_cache_hits"], 0)
        self.assertEqual(second["quality_funnel"]["ai_review_cache_hits"], 1)
        self.assertGreaterEqual(second["learning_point_summary"]["recommended"], 1)

    def test_extract_learning_points_can_skip_ai_review_cache_read_while_writing_for_hot_followup(self):
        original = worker._legacy_worker.gemini_vertex_generate_content
        calls = {"count": 0}
        cwd = os.getcwd()

        def fake_gemini_vertex_generate_content(api, prompt, **kwargs):
            calls["count"] += 1
            marker = "字幕和候选_JSON_START"
            compact = json.loads(prompt.split(marker, 1)[1].strip())
            sources = []
            for source in compact:
                reviews = []
                for candidate in source.get("local_candidates", []):
                    answer = candidate.get("answer_core") or candidate.get("exact_span")
                    reviews.append(
                        {
                            "id": candidate["id"],
                            "decision": "recommend",
                            "value_score": 4,
                            "estimated_level": "B1",
                            "exact_span": candidate.get("exact_span"),
                            "answer_core": answer,
                            "normalized_answer": candidate.get("normalized_answer") or answer,
                            "candidate_kind": candidate.get("candidate_kind"),
                            "phrase_type": candidate.get("phrase_type"),
                            "learning_action": candidate.get("learning_action") or f"训练 {answer}。",
                            "reason": "AI 精筛写入缓存。",
                            "status_reason": "推荐。",
                        }
                    )
                sources.append({"source_segment_id": source["source_segment_id"], "reviews": reviews, "new_learning_points": []})
            return json.dumps({"sources": sources}, ensure_ascii=False)

        worker._legacy_worker.gemini_vertex_generate_content = fake_gemini_vertex_generate_content
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                os.chdir(temp_dir)
                base_payload = {
                    "language": "en",
                    "level": "B1",
                    "reuse_ai_review_cache": True,
                    "language_focus": ["phrases", "vocabulary", "grammar", "listening"],
                    "api_config": {
                        "provider": "gemini-vertex",
                        "model": "gemini-3.1-pro-preview",
                        "project": "test-project",
                        "location": "global",
                    },
                }
                cues = [worker.Cue(1, 1.0, 3.0, "Can you run the register for a minute?")]
                cold_payload = {**base_payload, "disable_ai_review_cache_read": True}
                hot_payload = dict(base_payload)
                first = worker.extract_learning_points_from_subtitles(cold_payload, cues)
                second = worker.extract_learning_points_from_subtitles(hot_payload, cues)
                os.chdir(cwd)
        finally:
            os.chdir(cwd)
            worker._legacy_worker.gemini_vertex_generate_content = original

        self.assertEqual(calls["count"], 1)
        self.assertEqual(first["quality_funnel"]["ai_review_cache_hits"], 0)
        self.assertEqual(first["quality_funnel"]["ai_review_cache_misses"], 1)
        self.assertFalse(first["quality_funnel"]["ai_review_cache_read_enabled"])
        self.assertTrue(first["quality_funnel"]["ai_review_cache_write_enabled"])
        self.assertEqual(second["quality_funnel"]["ai_review_cache_hits"], 1)
        self.assertEqual(second["quality_funnel"]["ai_review_cache_misses"], 0)
        self.assertTrue(second["quality_funnel"]["ai_review_cache_read_enabled"])
        self.assertTrue(second["quality_funnel"]["ai_review_cache_write_enabled"])
        self.assertGreaterEqual(second["learning_point_summary"]["recommended"], 1)

    def test_extract_learning_points_ai_review_cache_namespace_isolated_when_explicit(self):
        original = worker._legacy_worker.gemini_vertex_generate_content
        calls = {"count": 0}
        cwd = os.getcwd()

        def fake_gemini_vertex_generate_content(api, prompt, **kwargs):
            calls["count"] += 1
            marker = "字幕和候选_JSON_START"
            compact = json.loads(prompt.split(marker, 1)[1].strip())
            sources = []
            for source in compact:
                reviews = []
                for candidate in source.get("local_candidates", []):
                    answer = candidate.get("answer_core") or candidate.get("exact_span")
                    reviews.append(
                        {
                            "id": candidate["id"],
                            "decision": "recommend",
                            "value_score": 4,
                            "estimated_level": "B1",
                            "exact_span": candidate.get("exact_span"),
                            "answer_core": answer,
                            "normalized_answer": candidate.get("normalized_answer") or answer,
                            "candidate_kind": candidate.get("candidate_kind"),
                            "phrase_type": candidate.get("phrase_type"),
                            "learning_action": candidate.get("learning_action") or f"训练 {answer}。",
                            "reason": "命名空间缓存测试。",
                            "status_reason": "推荐。",
                        }
                    )
                sources.append({"source_segment_id": source["source_segment_id"], "reviews": reviews, "new_learning_points": []})
            return json.dumps({"sources": sources}, ensure_ascii=False)

        worker._legacy_worker.gemini_vertex_generate_content = fake_gemini_vertex_generate_content
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                os.chdir(temp_dir)
                base_payload = {
                    "language": "en",
                    "level": "B1",
                    "reuse_ai_review_cache": True,
                    "language_focus": ["phrases", "vocabulary", "grammar", "listening"],
                    "api_config": {
                        "provider": "gemini-vertex",
                        "model": "gemini-3.1-pro-preview",
                        "project": "test-project",
                        "location": "global",
                    },
                }
                cues = [worker.Cue(1, 1.0, 3.0, "Can you run the register for a minute?")]
                first = worker.extract_learning_points_from_subtitles({**base_payload, "ai_review_cache_namespace": "ns-a"}, cues)
                second = worker.extract_learning_points_from_subtitles({**base_payload, "ai_review_cache_namespace": "ns-b"}, cues)
                third = worker.extract_learning_points_from_subtitles({**base_payload, "ai_review_cache_namespace": "ns-a"}, cues)
                os.chdir(cwd)
        finally:
            os.chdir(cwd)
            worker._legacy_worker.gemini_vertex_generate_content = original

        self.assertEqual(calls["count"], 2)
        self.assertEqual(first["quality_funnel"]["ai_review_cache_hits"], 0)
        self.assertEqual(second["quality_funnel"]["ai_review_cache_hits"], 0)
        self.assertEqual(third["quality_funnel"]["ai_review_cache_hits"], 1)

    def test_extract_learning_points_does_not_read_ai_review_cache_by_default(self):
        original = worker._legacy_worker.gemini_vertex_generate_content
        calls = {"count": 0}
        cwd = os.getcwd()

        def fake_gemini_vertex_generate_content(api, prompt, **kwargs):
            calls["count"] += 1
            marker = "字幕和候选_JSON_START"
            compact = json.loads(prompt.split(marker, 1)[1].strip())
            sources = []
            for source in compact:
                reviews = []
                for candidate in source.get("local_candidates", []):
                    answer = candidate.get("answer_core") or candidate.get("exact_span")
                    reviews.append(
                        {
                            "id": candidate["id"],
                            "decision": "recommend",
                            "value_score": 4,
                            "estimated_level": "B1",
                            "exact_span": candidate.get("exact_span"),
                            "answer_core": answer,
                            "normalized_answer": candidate.get("normalized_answer") or answer,
                            "candidate_kind": candidate.get("candidate_kind"),
                            "phrase_type": candidate.get("phrase_type"),
                            "learning_action": candidate.get("learning_action") or f"训练 {answer}。",
                            "reason": "AI 重新精筛结果。",
                            "status_reason": "推荐。",
                        }
                    )
                sources.append({"source_segment_id": source["source_segment_id"], "reviews": reviews, "new_learning_points": []})
            return json.dumps({"sources": sources}, ensure_ascii=False)

        worker._legacy_worker.gemini_vertex_generate_content = fake_gemini_vertex_generate_content
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                os.chdir(temp_dir)
                payload = {
                    "language": "en",
                    "level": "B1",
                    "language_focus": ["phrases", "vocabulary", "grammar", "listening"],
                    "api_config": {
                        "provider": "gemini-vertex",
                        "model": "gemini-3.1-pro-preview",
                        "project": "test-project",
                        "location": "global",
                    },
                }
                cues = [worker.Cue(1, 1.0, 3.0, "Can you run the register for a minute?")]
                first = worker.extract_learning_points_from_subtitles(payload, cues)
                second = worker.extract_learning_points_from_subtitles(payload, cues)
                os.chdir(cwd)
        finally:
            os.chdir(cwd)
            worker._legacy_worker.gemini_vertex_generate_content = original

        self.assertEqual(calls["count"], 2)
        self.assertEqual(first["quality_funnel"]["ai_review_cache_hits"], 0)
        self.assertEqual(second["quality_funnel"]["ai_review_cache_hits"], 0)
        self.assertGreaterEqual(second["learning_point_summary"]["recommended"], 1)

    def test_ai_learning_point_review_uses_limited_concurrency_and_preserves_order(self):
        from acg.pipeline import learning_point_pipeline

        original = worker._legacy_worker.gemini_vertex_generate_content
        lock = threading.Lock()
        active_calls = {"count": 0, "max": 0, "total": 0}

        def fake_gemini_vertex_generate_content(api, prompt, **kwargs):
            marker = "字幕和候选_JSON_START"
            compact = json.loads(prompt.split(marker, 1)[1].strip())
            with lock:
                active_calls["count"] += 1
                active_calls["total"] += 1
                active_calls["max"] = max(active_calls["max"], active_calls["count"])
            try:
                time.sleep(0.05)
                sources = []
                for source in compact:
                    reviews = []
                    for candidate in source.get("local_candidates", []):
                        answer = candidate.get("answer_core") or candidate.get("exact_span")
                        reviews.append(
                            {
                                "id": candidate["id"],
                                "decision": "recommend",
                                "value_score": 4,
                                "estimated_level": "B1",
                                "exact_span": candidate.get("exact_span"),
                                "answer_core": answer,
                                "normalized_answer": candidate.get("normalized_answer") or answer,
                                "candidate_kind": candidate.get("candidate_kind"),
                                "phrase_type": candidate.get("phrase_type"),
                                "learning_action": candidate.get("learning_action") or f"训练 {answer}。",
                                "reason": "并发 mock 精筛通过。",
                                "status_reason": "推荐。",
                            }
                        )
                    sources.append({"source_segment_id": source["source_segment_id"], "reviews": reviews, "new_learning_points": []})
                return json.dumps({"sources": sources}, ensure_ascii=False)
            finally:
                with lock:
                    active_calls["count"] -= 1

        source_sentences = [
            {
                "id": f"src-{index}",
                "source_segment_id": f"src-{index}",
                "source_sentence": f"Sentence {index} uses point {index}.",
                "text": f"Sentence {index} uses point {index}.",
                "start": float(index),
                "end": float(index) + 1,
                "source_time": "00:00:00.000 - 00:00:01.000",
            }
            for index in range(33)
        ]
        local_points = [
            {
                "id": f"lp-{index}",
                "source_segment_id": f"src-{index}",
                "exact_span": f"point {index}",
                "answer_core": f"point {index}",
                "normalized_answer": f"point {index}",
                "candidate_kind": "expression",
                "phrase_type": "collocation",
                "learning_action": f"训练 point {index}。",
                "value_score": 4,
                "validation_status": "valid",
            }
            for index in range(33)
        ]

        worker._legacy_worker.gemini_vertex_generate_content = fake_gemini_vertex_generate_content
        try:
            payload = {
                "language": "en",
                "level": "B1",
                "language_focus": ["phrases"],
                "api_config": self._ai_config(),
            }
            reviews_by_id, new_by_source, model_errors = learning_point_pipeline._call_ai_learning_point_review(
                payload,
                source_sentences,
                local_points,
            )
        finally:
            worker._legacy_worker.gemini_vertex_generate_content = original

        self.assertEqual(model_errors, [])
        self.assertTrue(all(not items for items in new_by_source.values()))
        self.assertEqual(active_calls["total"], 3)
        self.assertEqual(payload["_ai_review_concurrency"], 2)
        self.assertEqual(active_calls["max"], 2)
        self.assertEqual(reviews_by_id["lp-0"]["ai_batch_id"], "ai_review_1")
        self.assertEqual(reviews_by_id["lp-16"]["ai_batch_id"], "ai_review_2")
        self.assertEqual(reviews_by_id["lp-32"]["ai_batch_id"], "ai_review_3")
        self.assertEqual(set(payload["_ai_review_timing_ms"].keys()), {"1", "2", "3"})

    def test_extract_learning_points_recovers_non_string_status_from_scoring(self):
        from acg.pipeline import learning_point_pipeline

        original_ai = self._patch_learning_point_ai_review()
        original_score = learning_point_pipeline.score_learning_point

        def fake_score_learning_point(point, user_level, payload=None):
            score = original_score(point, user_level, payload)
            return {**score, "status": {"bad": "shape"}}

        learning_point_pipeline.score_learning_point = fake_score_learning_point
        try:
            result = worker.extract_learning_points_from_subtitles(
                {
                    "language": "en",
                    "level": "B1",
                    "language_focus": ["phrases", "vocabulary", "grammar", "listening"],
                    "api_config": self._ai_config(),
                },
                [worker.Cue(1, 1.0, 3.0, "Can you run the register for a minute?")],
            )
        finally:
            learning_point_pipeline.score_learning_point = original_score
            worker._legacy_worker.gemini_vertex_generate_content = original_ai

        statuses = {point["status"] for point in result["learning_points"]}
        self.assertTrue(statuses <= {"recommended", "candidate_only", "hidden_duplicate", "hard_blocked"})
        self.assertGreaterEqual(result["learning_point_summary"]["recommended"], 1)

    def test_extract_learning_points_sanitizes_nested_ai_review_fields(self):
        original = worker._legacy_worker.gemini_vertex_generate_content

        def fake_gemini_vertex_generate_content(api, prompt, **kwargs):
            marker = "字幕和候选_JSON_START"
            compact = json.loads(prompt.split(marker, 1)[1].strip())
            sources = []
            for source in compact:
                reviews = []
                for candidate in source.get("local_candidates", []):
                    reviews.append(
                        {
                            "id": candidate["id"],
                            "decision": "reject",
                            "value_score": 1,
                            "estimated_level": {"value": "B1"},
                            "exact_span": candidate.get("exact_span"),
                            "answer_core": candidate.get("answer_core") or candidate.get("exact_span"),
                            "candidate_kind": {"value": candidate.get("candidate_kind") or "expression"},
                            "phrase_type": {"value": candidate.get("phrase_type") or "spoken_phrase"},
                            "learning_action": {"text": "本地候选仅用于回归测试。"},
                            "reason": [{"text": "mock reject"}],
                            "status_reason": {"text": "mock blocked"},
                            "repair_history": [{"bad": "shape"}],
                        }
                    )
                sources.append(
                    {
                        "source_segment_id": source["source_segment_id"],
                        "reviews": reviews,
                        "new_learning_points": [
                            {
                                "decision": {"value": "recommend"},
                                "value_score": {"bad": "shape"},
                                "estimated_level": {"value": "B1"},
                                "exact_span": "repeat after me",
                                "answer_core": "repeat after me",
                                "normalized_answer": {"text": "repeat after me"},
                                "candidate_kind": {"value": "expression"},
                                "phrase_type": {"value": "spoken_phrase"},
                                "learning_action": {"text": "训练 repeat after me 作为课堂指令。"},
                                "reason": [{"text": "高频课堂指令。"}],
                                "status_reason": {"text": "推荐。"},
                                "repair_history": [{"bad": "shape"}],
                            }
                        ],
                    }
                )
            return json.dumps({"sources": sources}, ensure_ascii=False)

        worker._legacy_worker.gemini_vertex_generate_content = fake_gemini_vertex_generate_content
        try:
            result = worker.extract_learning_points_from_subtitles(
                {
                    "language": "en",
                    "level": "B1",
                    "language_focus": ["phrases", "vocabulary", "grammar", "listening"],
                    "api_config": self._ai_config(),
                },
                [worker.Cue(1, 1.0, 3.0, "Please repeat after me one more time.")],
            )
        finally:
            worker._legacy_worker.gemini_vertex_generate_content = original

        answers = {point["answer_core"]: point for point in result["learning_points"]}
        self.assertIn("repeat after me", answers)
        self.assertEqual(answers["repeat after me"]["candidate_kind"], "expression")
        self.assertEqual(answers["repeat after me"]["phrase_type"], "spoken_phrase")
        self.assertIn(answers["repeat after me"]["status"], {"recommended", "candidate_only"})

    def test_extract_learning_points_hides_global_duplicate_learning_actions(self):
        original = worker._legacy_worker.gemini_vertex_generate_content

        def fake_gemini_vertex_generate_content(api, prompt, **kwargs):
            marker = "字幕和候选_JSON_START"
            compact = json.loads(prompt.split(marker, 1)[1].strip())
            sources = []
            for source in compact:
                sources.append(
                    {
                        "source_segment_id": source["source_segment_id"],
                        "reviews": [],
                        "new_learning_points": [
                            {
                                "decision": "recommend",
                                "value_score": 5,
                                "estimated_level": "B1",
                                "exact_span": "What the hell",
                                "answer_core": "What the hell",
                                "normalized_answer": "what the hell",
                                "candidate_kind": "expression",
                                "phrase_type": "spoken_phrase",
                                "learning_action": "训练情绪化口语表达",
                                "reason": "高频口语表达。",
                                "status_reason": "推荐。",
                            }
                        ],
                    }
                )
            return json.dumps({"sources": sources}, ensure_ascii=False)

        worker._legacy_worker.gemini_vertex_generate_content = fake_gemini_vertex_generate_content
        try:
            result = worker.extract_learning_points_from_subtitles(
                {
                    "language": "en",
                    "level": "B1",
                    "language_focus": ["phrases", "vocabulary", "grammar", "listening"],
                    "api_config": self._ai_config(),
                },
                [
                    worker.Cue(1, 1.0, 3.0, "What the hell is this?"),
                    worker.Cue(2, 4.0, 6.0, "- What the hell is this? - Lab safety equipment."),
                ],
            )
        finally:
            worker._legacy_worker.gemini_vertex_generate_content = original

        matches = [point for point in result["learning_points"] if str(point.get("answer_core") or "").lower() == "what the hell"]
        self.assertEqual(sum(1 for point in matches if point["status"] == "recommended"), 1)
        self.assertGreaterEqual(sum(1 for point in matches if point["status"] == "hidden_duplicate"), 1)
        self.assertEqual(sum(1 for point in matches if point["status"] in {"recommended", "candidate_only"}), 1)

    def test_extract_learning_points_requires_model_api(self):
        cues = [worker.Cue(1, 1.0, 3.0, "Can you run the register for a minute?")]

        with self.assertRaises(SystemExit):
            worker.extract_learning_points_from_subtitles(
                {
                    "language": "en",
                    "level": "B1",
                    "language_focus": ["phrases", "vocabulary", "grammar", "listening"],
                    "api_config": {"provider": "local", "model": ""},
                },
                cues,
            )

    def test_extract_learning_points_retries_bad_ai_review_json(self):
        original = worker._legacy_worker.gemini_vertex_generate_content
        calls = {"count": 0}

        def fake_gemini_vertex_generate_content(api, prompt, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                return "not json"
            marker = "字幕和候选_JSON_START"
            compact = json.loads(prompt.split(marker, 1)[1].strip())
            sources = []
            for source in compact:
                reviews = []
                for candidate in source.get("local_candidates", []):
                    answer = candidate.get("answer_core") or candidate.get("exact_span")
                    reviews.append(
                        {
                            "id": candidate["id"],
                            "decision": "recommend",
                            "value_score": 4,
                            "estimated_level": "B1",
                            "exact_span": candidate.get("exact_span"),
                            "answer_core": answer,
                            "normalized_answer": candidate.get("normalized_answer") or answer,
                            "candidate_kind": candidate.get("candidate_kind"),
                            "phrase_type": candidate.get("phrase_type"),
                            "learning_action": candidate.get("learning_action") or f"训练 {answer}。",
                            "reason": "重试后 JSON 正常。",
                            "status_reason": "重试后推荐。",
                        }
                    )
                sources.append({"source_segment_id": source["source_segment_id"], "reviews": reviews, "new_learning_points": []})
            return json.dumps({"sources": sources}, ensure_ascii=False)

        worker._legacy_worker.gemini_vertex_generate_content = fake_gemini_vertex_generate_content
        try:
            result = worker.extract_learning_points_from_subtitles(
                {
                    "language": "en",
                    "level": "B1",
                    "language_focus": ["phrases", "vocabulary", "grammar", "listening"],
                    "api_config": self._ai_config(),
                },
                [worker.Cue(1, 1.0, 3.0, "Can you run the register for a minute?")],
            )
        finally:
            worker._legacy_worker.gemini_vertex_generate_content = original

        self.assertGreaterEqual(calls["count"], 2)
        self.assertEqual(result["ai_model_errors"], [])
        self.assertGreaterEqual(result["learning_point_summary"]["recommended"], 1)

    def test_extract_learning_points_degrades_failed_ai_review_batch_to_diagnostics(self):
        original = worker._legacy_worker.gemini_vertex_generate_content

        def fake_gemini_vertex_generate_content(api, prompt, **kwargs):
            return "not json"

        worker._legacy_worker.gemini_vertex_generate_content = fake_gemini_vertex_generate_content
        try:
            result = worker.extract_learning_points_from_subtitles(
                {
                    "language": "en",
                    "level": "B1",
                    "language_focus": ["phrases", "vocabulary", "grammar", "listening"],
                    "api_config": self._ai_config(),
                },
                [
                    worker.Cue(1, 1.0, 3.0, "Can you run the register for a minute?"),
                    worker.Cue(2, 4.0, 6.0, "I'm not really in the mood for this right now."),
                ],
            )
        finally:
            worker._legacy_worker.gemini_vertex_generate_content = original

        self.assertGreaterEqual(len(result["ai_model_errors"]), 1)
        self.assertGreaterEqual(result["learning_point_summary"]["hard_blocked"], 1)
        self.assertTrue(
            any(point.get("ai_decision") == "model_batch_failed" for point in result["learning_points"])
        )

    def test_generate_cards_from_selected_learning_points_only_uses_selected_ids(self):
        original_call_model_batches = worker._legacy_worker.call_model_batches

        def fake_call_model_batches(project, segments):
            self.assertEqual(project.get("_progress_command"), "generate_cards_from_learning_points")
            return {
                "segments": [
                    {
                        "id": segment["id"],
                        "cards": [
                            {
                                "type": "phrase",
                                "learning_point_id": segment["learning_point_id"],
                                "phrase": segment["answer_core"],
                                "chinese": "收银机",
                                "definition": "cash register in a store context",
                                "collocations": "run the register",
                                "context": segment["text"],
                                "example": "Can you run the register?",
                                "chinese_feel": "负责收银",
                                "why": "服务业高频场景表达。",
                                "difficulty": "B1",
                                "teacher_note": "AI mock 完整制卡。",
                                "cloze": "Can you ____ for a minute?",
                            }
                        ],
                    }
                    for segment in segments
                ]
            }

        worker._legacy_worker.call_model_batches = fake_call_model_batches
        learning_points = [
            {
                "id": "lp-1",
                "source_segment_id": "src-1",
                "source_sentence": "Can you run the register for a minute?",
                "source_time": "00:00:10.000 - 00:00:12.000",
                "start": 10.0,
                "end": 12.0,
                "exact_span": "run the register",
                "answer_core": "run the register",
                "normalized_answer": "run the register",
                "type": "phrase",
                "candidate_kind": "expression",
                "phrase_type": "collocation",
                "level": "B1",
                "learning_action": "训练服务业场景搭配。",
                "learning_action_key": "expression:run the register",
                "value_score": 4.6,
                "reason": "可迁移词伙。",
                "confidence": "high",
                "status": "recommended",
            },
            {
                "id": "lp-2",
                "source_segment_id": "src-1",
                "source_sentence": "Can you run the register for a minute?",
                "source_time": "00:00:10.000 - 00:00:12.000",
                "start": 10.0,
                "end": 12.0,
                "exact_span": "register",
                "answer_core": "register",
                "normalized_answer": "register",
                "type": "vocab_usage",
                "candidate_kind": "contextual_vocab",
                "phrase_type": "vocabulary_usage",
                "level": "B1",
                "learning_action": "理解 register 的收银机语境义。",
                "learning_action_key": "contextual_vocab:register",
                "value_score": 4.2,
                "reason": "熟词语境义。",
                "confidence": "high",
                "status": "recommended",
            },
        ]

        try:
            project = worker.handle_generate_cards_from_learning_points(
                {
                    "project_id": "project-test",
                    "title": "test",
                    "language": "en",
                    "level": "B1",
                    "disable_card_generation_cache": True,
                    "api_config": self._ai_config(),
                    "selected_learning_point_ids": ["lp-2"],
                    "learning_points": learning_points,
                    "card_types": ["phrase"],
                }
            )
        finally:
            worker._legacy_worker.call_model_batches = original_call_model_batches

        self.assertEqual(len(project["segments"]), 1)
        self.assertEqual(project["segments"][0]["learning_point_id"], "lp-2")
        self.assertEqual(project["segments"][0]["cards"][0]["phrase"], "register")
        self.assertEqual(project["segments"][0]["cards"][0]["chinese"], "收银机")

    def test_generate_cards_from_learning_points_blocks_unconfirmed_local_paths(self):
        original_call_model_batches = worker._legacy_worker.call_model_batches
        calls = {"count": 0}

        def fake_call_model_batches(project, segments):
            calls["count"] += 1
            return {"segments": []}

        worker._legacy_worker.call_model_batches = fake_call_model_batches
        stderr = io.StringIO()
        try:
            with redirect_stderr(stderr), self.assertRaises(SystemExit):
                worker.handle_generate_cards_from_learning_points(
                    {
                        "project_id": "project-test",
                        "title": "test",
                        "source_mode": "local",
                        "video_path": "E:/media/source.mp4",
                        "subtitle_path": "E:/media/source.srt",
                        "local_path_access_confirmed": False,
                        "language": "en",
                        "level": "B1",
                        "disable_card_generation_cache": True,
                        "api_config": self._ai_config(),
                        "selected_learning_point_ids": ["lp-1"],
                        "learning_points": [
                            {
                                "id": "lp-1",
                                "source_segment_id": "src-1",
                                "source_sentence": "Can you run the register for a minute?",
                                "source_time": "00:00:10.000 - 00:00:12.000",
                                "start": 10.0,
                                "end": 12.0,
                                "exact_span": "run the register",
                                "answer_core": "run the register",
                                "type": "phrase",
                                "candidate_kind": "expression",
                                "status": "recommended",
                                "value_score": 4.6,
                            }
                        ],
                        "card_types": ["phrase"],
                    }
                )
        finally:
            worker._legacy_worker.call_model_batches = original_call_model_batches

        self.assertEqual(calls["count"], 0)
        self.assertIn("LOCAL_PATH_ACCESS_CONFIRMATION_REQUIRED", stderr.getvalue())

    def test_generate_cards_from_learning_points_preserves_url_source_identity(self):
        original_call_model_batches = worker._legacy_worker.call_model_batches

        def fake_call_model_batches(project, segments):
            return {
                "segments": [
                    {
                        "id": segments[0]["id"],
                        "cards": [
                            {
                                "type": "phrase",
                                "learning_point_id": segments[0]["learning_point_id"],
                                "phrase": "run the register",
                                "answer_core": "run the register",
                                "english": segments[0]["text"],
                                "chinese": "负责收银",
                                "definition": "operate the cash register",
                                "collocations": "run the register",
                                "context": segments[0]["text"],
                                "example": "Can you run the register?",
                                "chinese_feel": "负责收银",
                                "why": "服务业高频场景表达。",
                                "difficulty": "B1",
                                "teacher_note": "AI mock 完整制卡。",
                                "cloze": "Can you ____ for a minute?",
                            }
                        ],
                    }
                ]
            }

        worker._legacy_worker.call_model_batches = fake_call_model_batches
        try:
            project = worker.handle_generate_cards_from_learning_points(
                {
                    "project_id": "url-project",
                    "title": "URL Video",
                    "source_mode": "url",
                    "source_url": "https://www.youtube.com/watch?v=test",
                    "source_info": {
                        "webpage_url": "https://www.youtube.com/watch?v=test",
                        "title": "URL Video",
                    },
                    "video_path": r"C:\Users\Example\AppData\Local\com.ankicard.generator\projects\url_cache\url_test\source.mp4",
                    "subtitle_path": r"C:\Users\Example\AppData\Local\com.ankicard.generator\projects\url_cache\url_test\source.en.srt",
                    "language": "en",
                    "level": "B1",
                    "api_config": self._ai_config(),
                    "tts_config": {
                        "enabled": True,
                        "provider": "gemini-vertex",
                        "base_url": "https://aiplatform.googleapis.com",
                        "project": "test-project",
                        "model": "gemini-3.1-flash-tts-preview",
                        "location": "global",
                        "voice": "Kore",
                        "language": "en-US",
                    },
                    "tts_semantic_verification": {
                        "asr_provider": "whisper-cli",
                        "whisper_model": "tiny.en",
                        "whisper_language": "en",
                        "require_pass_for_export": True,
                    },
                    "selected_learning_point_ids": ["lp-1"],
                    "learning_points": [
                        {
                            "id": "lp-1",
                            "source_segment_id": "src-1",
                            "source_sentence": "Can you run the register for a minute?",
                            "source_time": "00:00:10.000 - 00:00:12.000",
                            "start": 10.0,
                            "end": 12.0,
                            "exact_span": "run the register",
                            "answer_core": "run the register",
                            "normalized_answer": "run the register",
                            "candidate_kind": "expression",
                            "phrase_type": "collocation",
                            "learning_action": "训练服务业场景搭配。",
                            "learning_action_key": "expression:run the register",
                            "value_score": 4.6,
                            "reason": "可迁移词伙。",
                            "confidence": "high",
                            "status": "recommended",
                        }
                    ],
                    "card_types": ["phrase"],
                }
            )
        finally:
            worker._legacy_worker.call_model_batches = original_call_model_batches

        self.assertEqual(project["source_mode"], "url")
        self.assertEqual(project["source_url"], "https://www.youtube.com/watch?v=test")
        self.assertEqual(project["source_info"]["webpage_url"], "https://www.youtube.com/watch?v=test")
        self.assertTrue(project["video_path"].endswith("source.mp4"))
        self.assertTrue(project["subtitle_path"].endswith("source.en.srt"))
        self.assertTrue(project["tts_config"]["enabled"])
        self.assertEqual(project["tts_config"]["provider"], "gemini-vertex")
        self.assertEqual(worker._legacy_worker.normalized_tts_config(project)["provider"], "gemini-vertex")
        self.assertEqual(project["tts_semantic_verification"]["asr_provider"], "whisper-cli")
        self.assertTrue(project["tts_semantic_verification"]["require_pass_for_export"])
        self.assertEqual(len(project["segments"]), 1)

    def test_generate_cards_from_learning_points_reattaches_source_sentence_provenance(self):
        original_call_model_batches = worker._legacy_worker.call_model_batches
        from acg.media_alignment import fmt_time

        def fake_call_model_batches(project, segments):
            self.assertEqual(segments[0]["source_sentence_quality_flags"], ["possible_bad_join"])
            self.assertEqual(segments[0]["source_sentence_quality_status"], "needs_review")
            self.assertEqual(segments[0]["source_cue_ids"], [7, 8])
            self.assertEqual(segments[0]["start"], segments[0]["source_cue_start"])
            self.assertEqual(segments[0]["end"], segments[0]["source_cue_end"])
            self.assertEqual(segments[0]["source_time"], segments[0]["source_cue_time"])
            self.assertLessEqual(segments[0]["media_start"], segments[0]["source_cue_start"])
            self.assertGreaterEqual(segments[0]["media_end"], segments[0]["source_cue_end"])
            self.assertEqual(segments[0]["media_alignment_status"], "source_sentence_window")
            self.assertEqual(segments[0]["media_alignment_text"], segments[0]["full_source_sentence"])
            self.assertEqual(
                segments[0]["media_source_time"],
                f"{fmt_time(segments[0]['media_start'])} - {fmt_time(segments[0]['media_end'])}",
            )
            return {
                "segments": [
                    {
                        "id": segments[0]["id"],
                        "cards": [
                            {
                                "type": "phrase",
                                "learning_point_id": "lp-provenance",
                                "phrase": "confident",
                                "answer_core": "confident",
                                "exact_span": "confident",
                                "english": segments[0]["text"],
                                "chinese": "自信的",
                                "definition": "在当前语境里表示对自己使用英语有把握。",
                                "collocations": "feel confident / sound confident / be confident with English",
                                "context": segments[0]["text"],
                                "chinese_feel": "强调使用英语时有底气、不怯场。",
                                "teacher_note": "be confident with something 表示对某件事有把握。",
                                "how_to_use_it": "用 be confident with 说明对某件事有把握。",
                                "why_it_matters": "帮助区分自信情绪和对具体能力有把握的语境。",
                                "retrieval_prompt": "这句里表示有信心的词是什么？",
                            }
                        ],
                    }
                ]
            }

        worker._legacy_worker.call_model_batches = fake_call_model_batches
        try:
            project = worker.handle_generate_cards_from_learning_points(
                {
                    "project_id": "project-provenance",
                    "title": "test",
                    "language": "en",
                    "level": "B2",
                    "api_config": self._ai_config(),
                    "disable_card_generation_cache": True,
                    "selected_learning_point_ids": ["lp-provenance"],
                    "source_sentences": [
                        {
                            "id": "src-provenance",
                            "source_segment_id": "src-provenance",
                            "source_sentence": "everyday You're confident with the English that you use.",
                            "source_cue_ids": [7, 8],
                            "source_cue_count": 2,
                            "source_cue_start": 12.0,
                            "source_cue_end": 16.2,
                            "source_cue_time": "00:00:12.000 - 00:00:16.200",
                            "source_cue_texts": [
                                "just totally change your perspective on everything whatever's normal and mundane",
                                "everyday You're confident with the English that you use.",
                            ],
                            "source_merge_reason": "cue_sentence_merge",
                            "source_sentence_quality_flags": ["possible_bad_join"],
                            "source_sentence_quality_status": "needs_review",
                        }
                    ],
                    "learning_points": [
                        {
                            "id": "lp-provenance",
                            "source_segment_id": "src-provenance",
                            "source_sentence": "everyday You're confident with the English that you use.",
                            "exact_span": "confident",
                            "answer_core": "confident",
                            "normalized_answer": "confident",
                            "type": "phrase",
                            "candidate_kind": "contextual_vocab",
                            "phrase_type": "vocabulary_usage",
                            "status": "recommended",
                            "value_score": 4.2,
                            "reason": "可迁移词汇。",
                            "learning_action": "训练 confident 的语境用法。",
                        }
                    ],
                    "card_types": ["phrase"],
                }
            )
        finally:
            worker._legacy_worker.call_model_batches = original_call_model_batches

        segment = project["segments"][0]
        self.assertEqual(segment["source_cue_ids"], [7, 8])
        self.assertEqual(segment["source_cue_start"], 12.0)
        self.assertEqual(segment["source_cue_end"], 16.2)
        self.assertEqual(segment["source_sentence_quality_flags"], ["possible_bad_join"])
        self.assertEqual(segment["source_sentence_quality_status"], "needs_review")
        self.assertEqual(segment["start"], segment["source_cue_start"])
        self.assertEqual(segment["end"], segment["source_cue_end"])
        self.assertEqual(segment["source_time"], segment["source_cue_time"])
        self.assertLessEqual(segment["media_start"], segment["source_cue_start"])
        self.assertGreaterEqual(segment["media_end"], segment["source_cue_end"])
        self.assertEqual(segment["media_alignment_status"], "source_sentence_window")
        self.assertEqual(segment["media_alignment_text"], segment["full_source_sentence"])
        self.assertEqual(
            segment["media_source_time"],
            f"{fmt_time(segment['media_start'])} - {fmt_time(segment['media_end'])}",
        )

    def test_generate_cards_from_learning_points_marks_unlocated_media_phrase_needs_review(self):
        original_call_model_batches = worker._legacy_worker.call_model_batches

        def fake_call_model_batches(project, segments):
            segment = segments[0]
            self.assertFalse(segment["media_alignment_phrase_located"])
            self.assertEqual(segment["media_alignment_review_status"], "needs_review")
            self.assertIn("phrase_not_found_in_media_alignment_text", segment["phrase_decision_reason"])
            return {
                "segments": [
                    {
                        "id": segment["id"],
                        "cards": [
                            {
                                "type": "phrase",
                                "learning_point_id": segment["learning_point_id"],
                                "phrase": "take the scenic route",
                                "answer_core": "take the scenic route",
                                "exact_span": "take the scenic route",
                                "phrase_review_status": "recommended",
                                "phrase_value_score": 5,
                                "english": segment["text"],
                                "chinese": "绕风景路走",
                                "definition": "choose a longer but more scenic way",
                                "collocations": "take the scenic route / choose the scenic route",
                                "context": segment["text"],
                                "example": "We decided to take the scenic route.",
                                "chinese_feel": "强调不走最快路线，而走更有风景的路线。",
                                "why": "常见路线选择表达。",
                                "difficulty": "B1",
                                "teacher_note": "训练路线选择语境里的自然表达。",
                                "cloze": "We decided to ____.",
                            }
                        ],
                    }
                ]
            }

        worker._legacy_worker.call_model_batches = fake_call_model_batches
        try:
            project = worker.handle_generate_cards_from_learning_points(
                {
                    "project_id": "lp-media-unlocated",
                    "title": "Learning point media review",
                    "language": "en",
                    "level": "B1",
                    "api_config": self._ai_config(),
                    "disable_card_generation_cache": True,
                    "selected_learning_point_ids": ["lp-unlocated"],
                    "learning_points": [
                        {
                            "id": "lp-unlocated",
                            "source_segment_id": "src-1",
                            "source_sentence": "We explain the setup before moving on.",
                            "source_time": "00:00:10.000 - 00:00:14.000",
                            "start": 10.0,
                            "end": 14.0,
                            "exact_span": "take the scenic route",
                            "answer_core": "take the scenic route",
                            "normalized_answer": "take the scenic route",
                            "candidate_kind": "expression",
                            "phrase_type": "collocation",
                            "learning_action": "训练路线选择表达。",
                            "learning_action_key": "expression:take the scenic route",
                            "value_score": 4.7,
                            "reason": "可迁移词伙。",
                            "confidence": "high",
                            "status": "recommended",
                        }
                    ],
                    "card_types": ["phrase"],
                }
            )
        finally:
            worker._legacy_worker.call_model_batches = original_call_model_batches

        segment = project["segments"][0]
        card = segment["cards"][0]
        self.assertFalse(segment["media_alignment_phrase_located"])
        self.assertEqual(segment["media_alignment_review_status"], "needs_review")
        self.assertEqual(segment["media_alignment_review_reason"], "phrase_not_found_in_media_alignment_text")
        self.assertIn("phrase_not_found_in_media_alignment_text", segment["phrase_decision_reason"])
        self.assertEqual(segment["phrase_review_status"], "needs_review")
        self.assertEqual(card["phrase_review_status"], "needs_review")
        self.assertEqual(card["quality"]["status"], "needs_review")
        self.assertIn("媒体对齐未在原句中定位到目标表达，需复查。", card["quality"]["issues"])

    def test_generate_cards_from_learning_points_drops_off_target_cards_from_same_sentence(self):
        original_call_model_batches = worker._legacy_worker.call_model_batches

        def fake_call_model_batches(project, segments):
            segment = segments[0]
            return {
                "segments": [
                    {
                        "id": segment["id"],
                        "cards": [
                            {
                                "type": "phrase",
                                "learning_point_id": segment["learning_point_id"],
                                "phrase": "run the register",
                                "answer_core": "run the register",
                                "english": segment["text"],
                                "chinese": "负责收银",
                                "definition": "operate the cash register",
                                "collocations": "run the register",
                                "context": segment["text"],
                                "example": "Can you run the register?",
                                "chinese_feel": "负责收银",
                                "why": "服务业高频场景表达。",
                                "difficulty": "B1",
                                "teacher_note": "AI mock 完整制卡。",
                                "cloze": "Can you ____ for a minute?",
                            },
                            {
                                "type": "phrase",
                                "learning_point_id": segment["learning_point_id"],
                                "phrase": "take a break",
                                "answer_core": "take a break",
                                "english": segment["text"],
                                "chinese": "休息一下",
                                "definition": "暂时停止工作或学习，稍作休息。",
                                "collocations": "take a break / need a break / short break",
                                "context": segment["text"],
                                "example": "Let's take a break.",
                                "teacher_note": "这张卡只是用来模拟模型跑偏，同句旁支表达不应被带出。",
                            },
                        ],
                    }
                ]
            }

        worker._legacy_worker.call_model_batches = fake_call_model_batches
        try:
            project = worker.handle_generate_cards_from_learning_points(
                {
                    "project_id": "lp-off-target",
                    "title": "Learning point only",
                    "language": "en",
                    "level": "B1",
                    "api_config": self._ai_config(),
                    "selected_learning_point_ids": ["lp-run-register"],
                    "learning_points": [
                        {
                            "id": "lp-run-register",
                            "source_segment_id": "src-1",
                            "source_sentence": "Can you run the register while I take a break?",
                            "source_time": "00:00:00.120 - 00:00:11.160",
                            "start": 0.12,
                            "end": 11.16,
                            "exact_span": "run the register",
                            "answer_core": "run the register",
                            "normalized_answer": "run the register",
                            "candidate_kind": "expression",
                            "phrase_type": "collocation",
                            "learning_action": "训练服务业场景里的 run the register。",
                            "learning_action_key": "expression:run the register",
                            "value_score": 4.6,
                            "reason": "服务业高频搭配。",
                            "confidence": "high",
                            "status": "recommended",
                        }
                    ],
                    "card_types": ["phrase"],
                }
            )
        finally:
            worker._legacy_worker.call_model_batches = original_call_model_batches

        cards = [card for segment in project["segments"] for card in segment.get("cards", [])]
        self.assertEqual([card["answer_core"] for card in cards], ["run the register"])
        self.assertEqual(project["quality_funnel"]["off_target_learning_point_cards_dropped"], 1)
        self.assertEqual(project["quality_funnel"]["selected_learning_point_count"], 1)

    def test_generate_cards_from_learning_points_prepares_url_video_source(self):
        original_call_model_batches = worker._legacy_worker.call_model_batches
        original_download_url_source = worker._legacy_worker.download_url_source
        calls = {"download": 0}

        def fake_download_url_source(payload):
            calls["download"] += 1
            self.assertEqual(payload.get("url_import_mode"), "video")
            return {
                "video_path": r"C:\cache\source.mp4",
                "subtitle_path": r"C:\cache\source.en.srt",
                "url": payload.get("source_url"),
                "title": "URL Video",
                "transcript_only": False,
                "skip_video_slicing": False,
                "download_mode": "video",
            }

        def fake_call_model_batches(project, segments):
            self.assertEqual(project.get("video_path"), r"C:\cache\source.mp4")
            return {
                "segments": [
                    {
                        "id": segments[0]["id"],
                        "cards": [
                            {
                                "type": "phrase",
                                "learning_point_id": segments[0]["learning_point_id"],
                                "phrase": "special guest",
                                "answer_core": "special guest",
                                "english": segments[0]["text"],
                                "chinese": "特别嘉宾",
                                "definition": "a guest invited for a special role",
                                "collocations": "have a special guest",
                                "context": segments[0]["text"],
                                "example": "Today I have a special guest.",
                                "chinese_feel": "特别请来的嘉宾。",
                                "why": "高频主持开场表达。",
                                "difficulty": "B1",
                                "teacher_note": "AI mock 完整制卡。",
                                "cloze": "Today I have a ____.",
                            }
                        ],
                    }
                ]
            }

        worker._legacy_worker.download_url_source = fake_download_url_source
        worker._legacy_worker.call_model_batches = fake_call_model_batches
        try:
            project = worker.handle_generate_cards_from_learning_points(
                {
                    "project_id": "url-project",
                    "source_mode": "url",
                    "source_url": "https://www.youtube.com/watch?v=test",
                    "url_import_mode": "video",
                    "skip_video_slicing": True,
                    "language": "en",
                    "level": "B1",
                    "api_config": self._ai_config(),
                    "selected_learning_point_ids": ["lp-1"],
                    "learning_points": [
                        {
                            "id": "lp-1",
                            "source_segment_id": "src-1",
                            "source_sentence": "Today I have a special guest.",
                            "source_time": "00:00:01.222 - 00:00:03.170",
                            "start": 1.222,
                            "end": 3.17,
                            "exact_span": "special guest",
                            "answer_core": "special guest",
                            "normalized_answer": "special guest",
                            "candidate_kind": "expression",
                            "phrase_type": "collocation",
                            "learning_action": "训练主持开场表达。",
                            "learning_action_key": "expression:special guest",
                            "value_score": 4.6,
                            "reason": "高频实用词伙。",
                            "confidence": "high",
                            "status": "recommended",
                        }
                    ],
                    "card_types": ["phrase"],
                }
            )
        finally:
            worker._legacy_worker.download_url_source = original_download_url_source
            worker._legacy_worker.call_model_batches = original_call_model_batches

        self.assertEqual(calls["download"], 1)
        self.assertEqual(project["source_mode"], "url")
        self.assertEqual(project["url_import_mode"], "video")
        self.assertEqual(project["video_path"], r"C:\cache\source.mp4")
        self.assertEqual(project["subtitle_path"], r"C:\cache\source.en.srt")
        self.assertFalse(project["skip_video_slicing"])
        self.assertEqual(project["source_info"]["download_mode"], "video")

    def test_generate_cards_from_learning_points_preserves_fast_review_density_and_slims_cards(self):
        original_call_model_batches = worker._legacy_worker.call_model_batches

        def fake_call_model_batches(project, segments):
            return {
                "segments": [
                    {
                        "id": segment["id"],
                        "cards": [
                            {
                                "type": "phrase",
                                "learning_point_id": segment["learning_point_id"],
                                "phrase": segment["answer_core"],
                                "answer_core": segment["answer_core"],
                                "english": segment["text"],
                                "chinese": "负责收银",
                                "definition": "在零售或餐饮业中，指操作收银机、负责结账的工作。这是一个很长的解释，快速复读不应该保留。",
                                "collocations": "run the register / cover the register / operate the cash register",
                                "context": "在商店、餐厅等服务业场景中，安排或请求某人负责收银时使用。",
                                "example": "I'll run the register while you take a break.",
                                "chinese_feel": "安排某人暂时看收银台。",
                                "why": "服务业高频场景表达，值得学习。",
                                "teacher_note": "下次想说负责收银时，用 run the register，比 operate the cash register 更自然；使用边界：主要用于零售、餐饮等需要结账的服务业场景；易错提醒：register 是收银机，不是注册；易混表达：不要翻成跑登记。",
                                "retrieval_prompt": "这句里表示负责收银的表达是什么？",
                                "why_it_matters": "是海外生活、打工或购物时极高频的真实场景表达。",
                                "how_to_use_it": "I used to run the register at a coffee shop.",
                                "usage_boundary": "主要用于零售、餐饮等需要结账的服务业场景。",
                                "confusable_note": "这里的 register 是 cash register 的简称，不是注册。",
                            }
                        ],
                    }
                    for segment in segments
                ]
            }

        worker._legacy_worker.call_model_batches = fake_call_model_batches
        try:
            project = worker.handle_generate_cards_from_learning_points(
                {
                    "project_id": "project-test",
                    "title": "test",
                    "language": "en",
                    "level": "B1",
                    "api_config": self._ai_config(),
                    "review_density": "fast",
                    "learning_points": [
                        {
                            "id": "lp-1",
                            "source_segment_id": "src-1",
                            "source_sentence": "Can you run the register for a minute?",
                            "source_time": "00:00:10.000 - 00:00:12.000",
                            "start": 10.0,
                            "end": 12.0,
                            "exact_span": "run the register",
                            "answer_core": "run the register",
                            "candidate_kind": "expression",
                            "phrase_type": "collocation",
                            "learning_action": "训练服务业场景搭配。",
                            "value_score": 4.6,
                            "status": "recommended",
                        }
                    ],
                    "card_types": ["phrase"],
                }
            )
        finally:
            worker._legacy_worker.call_model_batches = original_call_model_batches

        card = project["segments"][0]["cards"][0]
        self.assertEqual(project["review_density"], "fast")
        self.assertEqual(worker.anki_template_family(project["template_id"], "video_language", project["card_style"], project["review_density"]), "language-immersive-v11-fast")
        self.assertLessEqual(len(card.get("teacher_note") or ""), 48)
        self.assertLessEqual(len(card.get("definition") or ""), 48)
        self.assertEqual(card.get("usage_boundary") or "", "")
        self.assertEqual(card.get("confusable_note") or "", "")
        self.assertEqual(card.get("why_it_matters") or "", "")
        self.assertEqual(card.get("how_to_use_it") or "", "")

    def test_fast_review_minimal_model_cards_are_exportable(self):
        original_call_model_batches = worker._legacy_worker.call_model_batches

        def fake_call_model_batches(project, segments):
            return {
                "segments": [
                    {
                        "id": segment["id"],
                        "cards": [
                            {
                                "type": "phrase",
                                "learning_point_id": segment["learning_point_id"],
                                "candidate_kind": segment.get("candidate_kind") or "expression",
                                "exact_span": segment.get("exact_span") or segment["answer_core"],
                                "phrase": segment["answer_core"],
                                "answer_core": segment["answer_core"],
                                "english": segment["text"],
                                "chinese": "负责收银",
                                "definition": "在店里操作收银机，负责顾客结账。",
                                "chinese_feel": "临时顶替或负责收银的动作感。",
                                "teacher_note": "run 在这里是操作机器，不是跑步。",
                                "retrieval_prompt": "这句里表示负责收银的表达是什么？",
                            }
                        ],
                    }
                    for segment in segments
                ]
            }

        worker._legacy_worker.call_model_batches = fake_call_model_batches
        try:
            project = worker.handle_generate_cards_from_learning_points(
                {
                    "project_id": "project-test",
                    "title": "test",
                    "language": "en",
                    "level": "B1",
                    "api_config": self._ai_config(),
                    "review_density": "fast",
                    "learning_points": [
                        {
                            "id": "lp-1",
                            "source_segment_id": "src-1",
                            "source_sentence": "Can you run the register for a minute?",
                            "source_time": "00:00:10.000 - 00:00:12.000",
                            "start": 10.0,
                            "end": 12.0,
                            "exact_span": "run the register",
                            "answer_core": "run the register",
                            "candidate_kind": "expression",
                            "phrase_type": "collocation",
                            "learning_action": "训练服务业场景搭配。",
                            "value_score": 4.9,
                            "final_score": 4.9,
                            "status": "recommended",
                        }
                    ],
                    "card_types": ["phrase"],
                }
            )
        finally:
            worker._legacy_worker.call_model_batches = original_call_model_batches

        self.assertEqual(len(project["segments"]), 1)
        card = project["segments"][0]["cards"][0]
        self.assertEqual(card["quality"]["status"], "recommended")
        self.assertGreaterEqual(card["quality"]["score"], 80)
        self.assertNotIn("字段像模板废话", card["quality"].get("issues", []))
        self.assertNotIn("例句只是照抄原句", card["quality"].get("issues", []))
        self.assertEqual(card.get("why") or "", "")
        self.assertEqual(card.get("example") or "", "")

    def test_generate_cards_from_learning_points_empty_explicit_selection_fails(self):
        original_call_model_batches = worker._legacy_worker.call_model_batches
        calls = {"count": 0}

        def fake_call_model_batches(project, segments):
            calls["count"] += 1
            return {"segments": []}

        worker._legacy_worker.call_model_batches = fake_call_model_batches
        try:
            with self.assertRaises(SystemExit):
                worker.handle_generate_cards_from_learning_points(
                    {
                        "project_id": "project-test",
                        "title": "test",
                        "language": "en",
                        "level": "B1",
                        "api_config": self._ai_config(),
                        "selected_learning_point_ids": [],
                        "learning_points": [
                            {
                                "id": "lp-1",
                                "source_segment_id": "src-1",
                                "source_sentence": "Can you run the register for a minute?",
                                "source_time": "00:00:10.000 - 00:00:12.000",
                                "start": 10.0,
                                "end": 12.0,
                                "exact_span": "run the register",
                                "answer_core": "run the register",
                                "candidate_kind": "expression",
                                "phrase_type": "collocation",
                                "learning_action": "训练服务业场景搭配。",
                                "value_score": 4.6,
                                "status": "recommended",
                            }
                        ],
                        "card_types": ["phrase"],
                    }
                )
        finally:
            worker._legacy_worker.call_model_batches = original_call_model_batches

        self.assertEqual(calls["count"], 0)

    def test_generate_cards_from_learning_points_accounts_for_unknown_selected_id(self):
        project = worker.handle_generate_cards_from_learning_points(
            {
                "project_id": "project-unknown-selection",
                "title": "unknown selection",
                "language": "en",
                "level": "B1",
                "api_config": self._ai_config(),
                "selected_learning_point_ids": ["lp-does-not-exist"],
                "learning_points": [],
                "card_types": ["phrase"],
            }
        )

        self.assertEqual(project["segments"], [])
        self.assertEqual(project["quality_funnel"]["selected_learning_point_count"], 1)
        self.assertEqual(project["quality_funnel"]["generation_missing_count"], 1)
        manifest = project["reliability_manifest"]
        self.assertTrue(manifest["accounting_complete"])
        self.assertEqual(manifest["decision"], "block")
        self.assertEqual(manifest["selected_point_count"], 1)
        self.assertEqual(manifest["verified_count"], 0)
        self.assertEqual(manifest["needs_review_count"], 0)
        self.assertEqual(manifest["hard_failed_count"], 1)
        self.assertEqual(
            manifest["selected_point_outcomes"][0],
            {
                "learning_point_id": "lp-does-not-exist",
                "status": "hard_failed",
                "blocker_codes": ["SELECTED_POINT_NOT_AVAILABLE"],
                "reason": "选中的学习点没有生成可复核卡片。",
            },
        )

    def test_generate_cards_from_learning_points_legacy_payload_defaults_to_recommended_only(self):
        original_call_model_batches = worker._legacy_worker.call_model_batches
        seen_learning_point_ids: list[str] = []

        def fake_call_model_batches(project, segments):
            seen_learning_point_ids.extend(str(segment["learning_point_id"]) for segment in segments)
            return {
                "segments": [
                    {
                        "id": segment["id"],
                        "cards": [
                            {
                                "type": "phrase",
                                "learning_point_id": segment["learning_point_id"],
                                "phrase": segment["answer_core"],
                                "answer_core": segment["answer_core"],
                                "english": segment["text"],
                                "chinese": "负责收银",
                                "definition": "表示操作收银机或负责收银。",
                                "collocations": "run the register / cover the register",
                                "context": segment["text"],
                                "example": "Could you run the register while I take inventory?",
                                "chinese_feel": "口语里是在安排店铺工作，不是字面“跑”。",
                                "teacher_note": "常见于店铺、餐厅等工作分工场景。",
                                "why": "服务业场景高频表达。",
                                "how_to_use_it": "用在需要某人暂时负责收银台的场景。",
                                "usage_boundary": "不要把 register 理解成登记动作，这里是收银机。",
                            }
                        ],
                    }
                    for segment in segments
                ]
            }

        worker._legacy_worker.call_model_batches = fake_call_model_batches
        try:
            project = worker.handle_generate_cards_from_learning_points(
                {
                    "project_id": "project-test",
                    "title": "test",
                    "language": "en",
                    "level": "B1",
                    "api_config": self._ai_config(),
                    "learning_points": [
                        {
                            "id": "lp-recommended",
                            "source_segment_id": "src-1",
                            "source_sentence": "Can you run the register for a minute?",
                            "source_time": "00:00:10.000 - 00:00:12.000",
                            "start": 10.0,
                            "end": 12.0,
                            "exact_span": "run the register",
                            "answer_core": "run the register",
                            "candidate_kind": "expression",
                            "phrase_type": "collocation",
                            "learning_action": "训练服务业场景搭配。",
                            "value_score": 4.6,
                            "status": "recommended",
                        },
                        {
                            "id": "lp-candidate",
                            "source_segment_id": "src-1",
                            "source_sentence": "Can you run the register for a minute?",
                            "source_time": "00:00:10.000 - 00:00:12.000",
                            "start": 10.0,
                            "end": 12.0,
                            "exact_span": "register",
                            "answer_core": "register",
                            "candidate_kind": "contextual_vocab",
                            "phrase_type": "vocabulary_usage",
                            "learning_action": "理解 register 的收银机语境义。",
                            "value_score": 3.2,
                            "status": "candidate_only",
                        },
                    ],
                    "card_types": ["phrase"],
                }
            )
        finally:
            worker._legacy_worker.call_model_batches = original_call_model_batches

        self.assertEqual(seen_learning_point_ids, ["lp-recommended"])
        self.assertEqual(len(project["segments"]), 1)

    def test_fast_review_density_defaults_to_one_best_recommended_point_per_source(self):
        original_call_model_batches = worker._legacy_worker.call_model_batches
        seen_learning_point_ids: list[str] = []

        def fake_call_model_batches(project, segments):
            seen_learning_point_ids.extend(str(segment["learning_point_id"]) for segment in segments)
            return {
                "segments": [
                    {
                        "id": segment["id"],
                        "cards": [
                            {
                                "type": "phrase",
                                "learning_point_id": segment["learning_point_id"],
                                "candidate_kind": segment.get("candidate_kind") or "expression",
                                "phrase_type": segment.get("phrase_type") or "spoken_phrase",
                                "exact_span": segment.get("exact_span") or segment["answer_core"],
                                "normalized_answer": segment["answer_core"],
                                "phrase": segment["answer_core"],
                                "answer_core": segment["answer_core"],
                                "english": segment["text"],
                                "chinese": "语境义：负责收银。",
                                "definition": "表示在店里负责收银或操作收银机。",
                                "context": segment["text"],
                                "example": "I can run the register for ten minutes.",
                                "chinese_feel": "店铺工作分工里的自然说法。",
                                "why": "服务业场景高频。",
                                "difficulty": "B1 日常交流",
                                "estimated_level": "B1",
                                "difficulty_reason": "服务业场景搭配。",
                                "teacher_note": "把 run the register 当整体记，表示负责收银。",
                                "learning_target": "训练一个服务业场景高频搭配。",
                                "learning_action": "expression_recall",
                                "retrieval_prompt": "这句里表示负责收银的表达是什么？",
                                "quality": {"score": 90, "status": "recommended", "issues": []},
                            }
                        ],
                    }
                    for segment in segments
                ]
            }

        worker._legacy_worker.call_model_batches = fake_call_model_batches
        try:
            try:
                worker.handle_generate_cards_from_learning_points(
                    {
                        "project_id": "project-test",
                        "title": "test",
                        "language": "en",
                        "level": "B1",
                        "api_config": self._ai_config(),
                        "review_density": "fast",
                        "learning_points": [
                            {
                                "id": "lp-register",
                                "source_segment_id": "src-1",
                                "source_sentence": "Can you run the register for a minute?",
                                "source_time": "00:00:10.000 - 00:00:12.000",
                                "start": 10.0,
                                "end": 12.0,
                                "exact_span": "register",
                                "answer_core": "register",
                                "candidate_kind": "contextual_vocab",
                                "phrase_type": "vocabulary_usage",
                                "learning_action": "理解 register 的收银机语境义。",
                                "value_score": 4.2,
                                "final_score": 4.2,
                                "status": "recommended",
                            },
                            {
                                "id": "lp-run-register",
                                "source_segment_id": "src-1",
                                "source_sentence": "Can you run the register for a minute?",
                                "source_time": "00:00:10.000 - 00:00:12.000",
                                "start": 10.0,
                                "end": 12.0,
                                "exact_span": "run the register",
                                "answer_core": "run the register",
                                "candidate_kind": "expression",
                                "phrase_type": "collocation",
                                "learning_action": "训练服务业场景搭配。",
                                "value_score": 4.9,
                                "final_score": 4.9,
                                "status": "recommended",
                            },
                            {
                                "id": "lp-turns-out",
                                "source_segment_id": "src-2",
                                "source_sentence": "It turns out I was looking at it the wrong way.",
                                "source_time": "00:00:13.000 - 00:00:15.000",
                                "start": 13.0,
                                "end": 15.0,
                                "exact_span": "turns out",
                                "answer_core": "turns out",
                                "candidate_kind": "expression",
                                "phrase_type": "spoken_phrase",
                                "learning_action": "训练引出结果的口语表达。",
                                "value_score": 4.6,
                                "final_score": 4.6,
                                "status": "recommended",
                            },
                        ],
                        "card_types": ["phrase"],
                    }
                )
            except SystemExit:
                # This test is about fast-mode default selection before model generation.
                # Later quality gates are covered by separate card-output tests.
                pass
        finally:
            worker._legacy_worker.call_model_batches = original_call_model_batches

        self.assertEqual(seen_learning_point_ids, ["lp-run-register", "lp-turns-out"])

    def test_generate_cards_from_learning_points_outputs_every_selected_point(self):
        original_call_model_batches = worker._legacy_worker.call_model_batches

        def fake_call_model_batches(project, segments):
            output_segments = []
            for segment in segments:
                lp_id = segment["learning_point_id"]
                if lp_id == "lp-missing":
                    continue
                if lp_id == "lp-filtered":
                    output_segments.append(
                        {
                            "id": segment["id"],
                            "cards": [
                                {
                                    "type": "phrase",
                                    "learning_point_id": lp_id,
                                    "phrase": segment["answer_core"],
                                    "answer_core": segment["answer_core"],
                                    "english": segment["text"],
                                    "chinese": "待精修：先把 bad point 当作目标表达。",
                                    "definition": "本地草稿",
                                    "teacher_note": "本地 fallback 只保证结构完整。",
                                }
                            ],
                        }
                    )
                    continue
                output_segments.append(
                    {
                        "id": segment["id"],
                        "cards": [
                            {
                                "type": "phrase",
                                "learning_point_id": lp_id,
                                "phrase": segment["answer_core"],
                                "answer_core": segment["answer_core"],
                                "english": segment["text"],
                                "chinese": "负责收银。",
                                "definition": "表示操作收银机或暂时负责收银。",
                                "collocations": "run the register / cover the register",
                                "context": segment["text"],
                                "example": "Could you run the register while I help the customer?",
                                "chinese_feel": "店铺工作分工里的自然口语说法。",
                                "why": "服务业和日常帮忙场景都可迁移。",
                                "teacher_note": "这里的 register 是收银机，不是登记这个动作。",
                                "how_to_use_it": "用在请别人暂时看收银台或操作收银机的场景。",
                                "usage_boundary": "不要把它理解成跑步，也不要泛化到所有登记场景。",
                            }
                        ],
                    }
                )
            return {"segments": output_segments}

        worker._legacy_worker.call_model_batches = fake_call_model_batches
        points = [
            {
                "id": "lp-good",
                "source_segment_id": "src-1",
                "source_sentence": "Can you run the register for a minute?",
                "source_time": "00:00:10.000 - 00:00:12.000",
                "start": 10.0,
                "end": 12.0,
                "exact_span": "run the register",
                "answer_core": "run the register",
                "candidate_kind": "expression",
                "phrase_type": "collocation",
                "learning_action": "训练服务业场景搭配。",
                "value_score": 4.8,
                "status": "recommended",
            },
            {
                "id": "lp-missing",
                "source_segment_id": "src-2",
                "source_sentence": "Let's get this over with.",
                "source_time": "00:00:13.000 - 00:00:15.000",
                "start": 13.0,
                "end": 15.0,
                "exact_span": "get this over with",
                "answer_core": "get this over with",
                "candidate_kind": "expression",
                "phrase_type": "spoken_phrase",
                "learning_action": "训练不情愿地把事情做完的表达。",
                "value_score": 4.5,
                "status": "recommended",
            },
            {
                "id": "lp-filtered",
                "source_segment_id": "src-3",
                "source_sentence": "This is a bad point.",
                "source_time": "00:00:16.000 - 00:00:18.000",
                "start": 16.0,
                "end": 18.0,
                "exact_span": "bad point",
                "answer_core": "bad point",
                "candidate_kind": "expression",
                "phrase_type": "spoken_phrase",
                "learning_action": "训练一个会被过滤的坏样例。",
                "value_score": 4.0,
                "status": "recommended",
            },
        ]

        try:
            project = worker.handle_generate_cards_from_learning_points(
                {
                    "project_id": "project-test",
                    "title": "test",
                    "language": "en",
                    "level": "B1",
                    "api_config": self._ai_config(),
                    "selected_learning_point_ids": [point["id"] for point in points],
                    "learning_points": points,
                    "card_types": ["phrase"],
                }
            )
        finally:
            worker._legacy_worker.call_model_batches = original_call_model_batches

        self.assertEqual(len(project["segments"]), 3)
        funnel = project["quality_funnel"]
        self.assertEqual(funnel["selected_learning_point_count"], 3)
        self.assertEqual(funnel["eligible_learning_point_count"], 3)
        self.assertEqual(funnel["successful_learning_point_count"], 1)
        self.assertEqual(funnel["generation_missing_count"], 2)
        self.assertEqual(funnel["generation_reconciliation_status"], "partial")
        self.assertEqual(funnel["card_generation_missing_learning_point_count"], 0)
        self.assertEqual(funnel["card_generation_filtered_card_count"], 0)
        self.assertEqual(funnel["card_generation_skipped_learning_point_count"], 0)
        self.assertEqual(funnel["user_selected_fallback_card_count"], 2)
        self.assertEqual(funnel["review_only_card_count"], 2)
        diagnostics = project["card_generation_diagnostics"]
        self.assertEqual(diagnostics["selected_learning_point_count"], 3)
        self.assertEqual(diagnostics["successful_learning_point_count"], 1)
        self.assertEqual(diagnostics["generated_card_count"], 1)
        self.assertEqual(diagnostics["exportable_card_count"], 1)
        self.assertEqual(diagnostics["missing_learning_point_count"], 2)
        self.assertEqual(diagnostics["model_missing_learning_point_count"], 0)
        self.assertEqual(diagnostics["filtered_learning_point_count"], 0)
        self.assertEqual(diagnostics["skipped_learning_point_count"], 0)
        self.assertEqual(
            {item["learning_point_id"]: item["status"] for item in diagnostics["items"]},
            {"lp-missing": "needs_review", "lp-filtered": "needs_review"},
        )
        cards_by_lp = {
            segment["learning_point_id"]: segment["cards"][0]
            for segment in project["segments"]
        }
        self.assertEqual(cards_by_lp["lp-good"]["answer_core"], "run the register")
        self.assertEqual(cards_by_lp["lp-missing"]["answer_core"], "get this over with")
        self.assertEqual(cards_by_lp["lp-filtered"]["answer_core"], "bad point")
        self.assertEqual(cards_by_lp["lp-missing"]["generation_source"], "fallback_from_selected_learning_point")
        self.assertEqual(cards_by_lp["lp-filtered"]["generation_source"], "fallback_from_selected_learning_point")
        self.assertIn("card", cards_by_lp["lp-missing"]["missing_ai_fields"])
        self.assertIn("teacher_note", cards_by_lp["lp-filtered"].get("fallback_fields_filled", []))
        self.assertTrue(cards_by_lp["lp-good"].get("enabled"))
        self.assertFalse(cards_by_lp["lp-missing"].get("enabled"))
        self.assertFalse(cards_by_lp["lp-filtered"].get("enabled"))
        self.assertFalse(worker._legacy_worker.card_has_export_blocking_content(cards_by_lp["lp-good"]))
        self.assertTrue(worker._legacy_worker.card_has_export_blocking_content(cards_by_lp["lp-missing"]))
        self.assertTrue(worker._legacy_worker.card_has_export_blocking_content(cards_by_lp["lp-filtered"]))
        manifest = project["reliability_manifest"]
        self.assertTrue(manifest["accounting_complete"])
        self.assertEqual(manifest["decision"], "block")
        self.assertEqual(manifest["selected_point_count"], 3)
        self.assertEqual(manifest["verified_count"], 1)
        self.assertEqual(manifest["needs_review_count"], 2)
        self.assertEqual(manifest["hard_failed_count"], 0)
        self.assertEqual(
            {item["learning_point_id"]: item["status"] for item in manifest["selected_point_outcomes"]},
            {"lp-good": "verified", "lp-missing": "needs_review", "lp-filtered": "needs_review"},
        )

    def test_generate_cards_from_learning_points_treats_metadata_only_repairs_as_exportable(self):
        original_call_model_batches = worker._legacy_worker.call_model_batches

        def fake_call_model_batches(project, segments):
            segment = segments[0]
            return {
                "segments": [
                    {
                        "id": segment["id"],
                        "cards": [
                            {
                                "type": "phrase",
                                "phrase": "sort of",
                                "english": segment["text"],
                                "chinese": "Kind of; used to soften a statement.",
                                "definition": "Use it to make a statement less direct or less absolute in casual speech.",
                                "collocations": "sort of tired / sort of like / sort of works",
                                "context": segment["text"],
                                "example": "I'm sort of tired, but I can keep going.",
                                "chinese_feel": "Softens the statement in casual speech.",
                                "why": "High-frequency discourse marker for natural speech.",
                                "difficulty": "A2",
                                "teacher_note": "Teach sort of as a softener, not as the noun meaning of kind/type.",
                                "cloze": "I'm ____ tired, but I can keep going.",
                            }
                        ],
                    }
                ]
            }

        worker._legacy_worker.call_model_batches = fake_call_model_batches
        try:
            project = worker.handle_generate_cards_from_learning_points(
                {
                    "project_id": "project-metadata-repair",
                    "title": "metadata repair",
                    "language": "en",
                    "level": "A2",
                    "api_config": self._ai_config(),
                    "disable_card_generation_cache": True,
                    "selected_learning_point_ids": ["lp-sort-of"],
                    "learning_points": [
                        {
                            "id": "lp-sort-of",
                            "source_segment_id": "src-1",
                            "source_sentence": "I sort of talk to different age groups.",
                            "source_time": "00:00:10.000 - 00:00:12.000",
                            "start": 10.0,
                            "end": 12.0,
                            "exact_span": "sort of",
                            "answer_core": "sort of",
                            "normalized_answer": "sort of",
                            "candidate_kind": "pragmatic_marker",
                            "phrase_type": "discourse_marker",
                            "learning_action": "Practice sort of as a spoken softener.",
                            "learning_action_key": "pragmatic_marker:sort of",
                            "value_score": 4.7,
                            "reason": "High-transfer spoken discourse marker.",
                            "confidence": "high",
                            "status": "recommended",
                        }
                    ],
                    "card_types": ["phrase"],
                }
            )
        finally:
            worker._legacy_worker.call_model_batches = original_call_model_batches

        card = project["segments"][0]["cards"][0]
        funnel = project["quality_funnel"]
        self.assertTrue(card.get("enabled"))
        self.assertEqual(card["generation_source"], "ai_repaired")
        self.assertEqual(card["quality"]["status"], "recommended")
        self.assertEqual(funnel["generation_success_count"], 1)
        self.assertEqual(funnel["card_generation_filtered_card_count"], 0)
        self.assertEqual(funnel["review_only_card_count"], 0)
        self.assertFalse(worker._legacy_worker.card_has_export_blocking_content(card))
        self.assertEqual(card["learning_point_id"], "lp-sort-of")
        self.assertEqual(card["answer_core"], "sort of")
        self.assertIn("answer_core", card.get("missing_ai_fields", []))

    def test_generate_cards_from_learning_points_retries_missing_selected_points_individually(self):
        original_call_model_batches = worker._legacy_worker.call_model_batches
        called_batches: list[list[str]] = []

        def make_card(segment):
            return {
                "type": "phrase",
                "learning_point_id": segment["learning_point_id"],
                "phrase": segment["answer_core"],
                "answer_core": segment["answer_core"],
                "english": segment["text"],
                "chinese": f"Meaning of {segment['answer_core']}.",
                "definition": f"Use {segment['answer_core']} naturally in this context.",
                "collocations": segment["answer_core"],
                "context": segment["text"],
                "example": segment["text"],
                "chinese_feel": "Natural spoken expression.",
                "why": "Useful and transferable.",
                "difficulty": "A2",
                "teacher_note": "AI mock complete card.",
                "cloze": segment["text"],
            }

        def fake_call_model_batches(project, segments, batch_size=10):
            ids = [str(segment["learning_point_id"]) for segment in segments]
            called_batches.append(ids)
            if len(called_batches) == 1:
                returned = [segment for segment in segments if str(segment["learning_point_id"]) == "lp-wake-up"]
            else:
                returned = segments
            return {
                "segments": [
                    {"id": segment["id"], "cards": [make_card(segment)]}
                    for segment in returned
                ]
            }

        points = [
            {
                "id": "lp-get-out",
                "source_segment_id": "src-1",
                "source_sentence": "I wake up at half past 7 and get out of bed.",
                "source_time": "00:00:10.000 - 00:00:12.000",
                "start": 10.0,
                "end": 12.0,
                "exact_span": "get out of bed",
                "answer_core": "get out of bed",
                "normalized_answer": "get out of bed",
                "candidate_kind": "expression",
                "phrase_type": "collocation",
                "learning_action": "Practice get out of bed.",
                "learning_action_key": "expression:get out of bed",
                "value_score": 4.7,
                "status": "recommended",
            },
            {
                "id": "lp-wake-up",
                "source_segment_id": "src-1",
                "source_sentence": "I wake up at half past 7 and get out of bed.",
                "source_time": "00:00:10.000 - 00:00:12.000",
                "start": 10.0,
                "end": 12.0,
                "exact_span": "wake up",
                "answer_core": "wake up",
                "normalized_answer": "wake up",
                "candidate_kind": "expression",
                "phrase_type": "phrasal_verb",
                "learning_action": "Practice wake up.",
                "learning_action_key": "expression:wake up",
                "value_score": 4.1,
                "status": "recommended",
            },
            {
                "id": "lp-relax",
                "source_segment_id": "src-2",
                "source_sentence": "I relax for a bit after lunch.",
                "source_time": "00:00:13.000 - 00:00:15.000",
                "start": 13.0,
                "end": 15.0,
                "exact_span": "relax for a bit",
                "answer_core": "relax for a bit",
                "normalized_answer": "relax for a bit",
                "candidate_kind": "expression",
                "phrase_type": "collocation",
                "learning_action": "Practice relax for a bit.",
                "learning_action_key": "expression:relax for a bit",
                "value_score": 4.7,
                "status": "recommended",
            },
        ]

        worker._legacy_worker.call_model_batches = fake_call_model_batches
        try:
            project = worker.handle_generate_cards_from_learning_points(
                {
                    "project_id": "project-partial-retry",
                    "title": "partial retry",
                    "language": "en",
                    "level": "A2",
                    "api_config": self._ai_config(),
                    "disable_card_generation_cache": True,
                    "selected_learning_point_ids": [point["id"] for point in points],
                    "learning_points": points,
                    "card_types": ["phrase"],
                }
            )
        finally:
            worker._legacy_worker.call_model_batches = original_call_model_batches

        self.assertEqual(called_batches, [["lp-get-out", "lp-wake-up", "lp-relax"], ["lp-get-out", "lp-relax"]])
        self.assertEqual(project["quality_funnel"]["generation_success_count"], 3)
        self.assertEqual(project["quality_funnel"]["generation_missing_count"], 0)
        self.assertEqual(project["quality_funnel"]["card_generation_retry_count"], 1)
        enabled_cards = [card for segment in project["segments"] for card in segment.get("cards", []) if card.get("enabled")]
        self.assertEqual([card["answer_core"] for card in enabled_cards], ["get out of bed", "wake up", "relax for a bit"])

    def test_generate_cards_from_learning_points_aligns_media_to_phrase_in_full_sentence(self):
        original_call_model_batches = worker._legacy_worker.call_model_batches

        def fake_call_model_batches(project, segments):
            return {
                "segments": [
                    {
                        "id": segments[0]["id"],
                        "cards": [
                            {
                                "type": "phrase",
                                "learning_point_id": segments[0]["learning_point_id"],
                                "phrase": "what happens next",
                                "answer_core": "what happens next",
                                "english": segments[0]["text"],
                                "chinese": "接下来会发生什么",
                                "definition": "ask about the next event",
                                "collocations": "what happens next",
                                "context": segments[0]["text"],
                                "example": "Let's see what happens next.",
                                "chinese_feel": "想知道后续",
                                "why": "常用于衔接叙事。",
                                "difficulty": "B1",
                                "teacher_note": "目标表达靠近长字幕后半段。",
                                "cloze": "Let's see ____.",
                            }
                        ],
                    }
                ]
            }

        worker._legacy_worker.call_model_batches = fake_call_model_batches
        try:
            project = worker.handle_generate_cards_from_learning_points(
                {
                    "project_id": "media-align-test",
                    "title": "test",
                    "language": "en",
                    "level": "B1",
                    "api_config": self._ai_config(),
                    "disable_card_generation_cache": True,
                    "selected_learning_point_ids": ["lp-late"],
                    "learning_points": [
                        {
                            "id": "lp-late",
                            "source_segment_id": "src-late",
                            "source_sentence": (
                                "At the start we introduce the idea and give a little background "
                                "before we finally ask what happens next in this story."
                            ),
                            "source_time": "00:01:40.000 - 00:01:52.000",
                            "start": 100.0,
                            "end": 112.0,
                            "exact_span": "what happens next",
                            "answer_core": "what happens next",
                            "candidate_kind": "expression",
                            "phrase_type": "spoken_phrase",
                            "learning_action": "训练衔接叙事时的自然提问。",
                            "value_score": 4.5,
                            "status": "recommended",
                        }
                    ],
                    "card_types": ["phrase"],
                }
            )
        finally:
            worker._legacy_worker.call_model_batches = original_call_model_batches

        segment = project["segments"][0]
        self.assertEqual(segment["media_alignment_status"], "source_sentence_window")
        self.assertIn("what happens next", segment["text"])
        self.assertIn("At the start we introduce", segment["media_alignment_text"])
        self.assertLessEqual(segment["media_start"], 100.0)
        self.assertGreaterEqual(segment["media_end"], 112.0)
        self.assertGreater(segment["media_end"] - segment["media_start"], 12.0)
        self.assertEqual(segment["source_time"], "00:01:40.000 - 00:01:52.000")
        self.assertNotEqual(segment["media_source_time"], segment["source_time"])

    def test_generate_cards_from_learning_points_expands_phrase_only_media_to_full_source_sentence(self):
        original_call_model_batches = worker._legacy_worker.call_model_batches
        full_sentence = "The more you live in English, the faster your brain rewires itself."

        def fake_call_model_batches(project, segments):
            return {
                "segments": [
                    {
                        "id": segments[0]["id"],
                        "cards": [
                            {
                                "type": "phrase",
                                "learning_point_id": segments[0]["learning_point_id"],
                                "phrase": "rewires itself",
                                "answer_core": "rewires itself",
                                "english": segments[0]["text"],
                                "chinese": "大脑会重塑自己。",
                                "definition": "change and adapt its own habits or wiring",
                                "collocations": "rewires itself",
                                "context": segments[0]["text"],
                                "example": "Practice rewires itself through repetition.",
                                "chinese_feel": "强调自我重塑",
                                "why": "描述大脑适应语言输入。",
                                "difficulty": "B2",
                                "teacher_note": "目标表达靠近原句末尾。",
                            }
                        ],
                    }
                ]
            }

        worker._legacy_worker.call_model_batches = fake_call_model_batches
        try:
            project = worker.handle_generate_cards_from_learning_points(
                {
                    "project_id": "media-align-phrase-only-test",
                    "title": "test",
                    "language": "en",
                    "level": "B2",
                    "api_config": self._ai_config(),
                    "disable_card_generation_cache": True,
                    "selected_learning_point_ids": ["lp-rewire"],
                    "source_sentences": [
                        {
                            "id": "src-rewire",
                            "source_segment_id": "src-rewire",
                            "source_sentence": full_sentence,
                            "text": full_sentence,
                            "start": 349.287,
                            "end": 358.061,
                            "source_time": "00:05:49.287 - 00:05:58.061",
                        }
                    ],
                    "learning_points": [
                        {
                            "id": "lp-rewire",
                            "source_segment_id": "src-rewire",
                            "source_sentence": full_sentence,
                            "source_time": "00:05:49.287 - 00:05:58.061",
                            "start": 349.287,
                            "end": 358.061,
                            "exact_span": "rewires itself",
                            "answer_core": "rewires itself",
                            "candidate_kind": "expression",
                            "phrase_type": "spoken_phrase",
                            "learning_action": "训练表达大脑/系统自我重塑。",
                            "value_score": 4.5,
                            "status": "recommended",
                        }
                    ],
                    "card_types": ["phrase"],
                }
            )
        finally:
            worker._legacy_worker.call_model_batches = original_call_model_batches

        segment = project["segments"][0]
        self.assertEqual(segment["text"], full_sentence)
        self.assertEqual(segment["full_source_sentence"], full_sentence)
        self.assertEqual(segment["media_alignment_status"], "source_sentence_window")
        self.assertEqual(segment["media_alignment_text"], full_sentence)
        self.assertLessEqual(segment["media_start"], 349.3)
        self.assertGreaterEqual(segment["media_end"], 358.0)
        self.assertGreater(segment["media_end"] - segment["media_start"], 8.5)

    def test_generate_cards_from_learning_points_does_not_count_blocked_output_as_success(self):
        original_call_model_batches = worker._legacy_worker.call_model_batches
        original_filter_usable_segments = worker._legacy_worker.filter_usable_segments_for_output

        def fake_call_model_batches(project, segments):
            return {
                "segments": [
                    {
                        "id": segments[0]["id"],
                        "cards": [
                            {
                                "type": "phrase",
                                "enabled": True,
                                "learning_point_id": segments[0]["learning_point_id"],
                                "phrase": "stay on track",
                                "answer_core": "stay on track",
                                "english": segments[0]["text"],
                                "chinese": "保持正轨",
                                "definition": "continue making progress toward a goal",
                                "collocations": "stay on track",
                                "context": segments[0]["text"],
                                "example": segments[0]["text"],
                                "chinese_feel": "自然表达继续按计划推进。",
                                "why": "高频口语表达。",
                                "teacher_note": "可以用于提醒自己别偏离目标。",
                                "cloze": segments[0]["text"],
                            }
                        ],
                    }
                ]
            }

        def leaky_filter(segments, skipped_segments=None, **kwargs):
            leaked_segments = json.loads(json.dumps(segments, ensure_ascii=False))
            leaked_segments[0]["cards"][0]["teacher_note"] = "本地草稿，需要人工确认"
            return leaked_segments, {
                "filtered_learning_point_count": 0,
                "duplicate_learning_point_count": 0,
                "low_value_filtered_count": 0,
                "blocked_quality_issue_count": 0,
            }

        worker._legacy_worker.call_model_batches = fake_call_model_batches
        worker._legacy_worker.filter_usable_segments_for_output = leaky_filter
        try:
            project = worker.handle_generate_cards_from_learning_points(
                {
                    "project_id": "blocked-output-test",
                    "title": "test",
                    "language": "en",
                    "level": "B1",
                    "api_config": self._ai_config(),
                    "disable_card_generation_cache": True,
                    "selected_learning_point_ids": ["lp-blocked-output"],
                    "learning_points": [
                        {
                            "id": "lp-blocked-output",
                            "source_segment_id": "src-blocked-output",
                            "source_sentence": "I need to stay on track this week.",
                            "source_time": "00:00:03.000 - 00:00:06.000",
                            "start": 3.0,
                            "end": 6.0,
                            "exact_span": "stay on track",
                            "answer_core": "stay on track",
                            "candidate_kind": "expression",
                            "phrase_type": "spoken_phrase",
                            "learning_action": "训练 stay on track 的自然用法。",
                            "value_score": 4.3,
                            "status": "recommended",
                        }
                    ],
                    "card_types": ["phrase"],
                }
            )
        finally:
            worker._legacy_worker.call_model_batches = original_call_model_batches
            worker._legacy_worker.filter_usable_segments_for_output = original_filter_usable_segments

        self.assertEqual(project["card_generation_diagnostics"]["exportable_card_count"], 0)
        manifest = project["reliability_manifest"]
        self.assertEqual(manifest["decision"], "block")
        self.assertEqual(manifest["verified_count"], 0)
        self.assertEqual(manifest["needs_review_count"], 1)
        self.assertEqual(manifest["selected_point_outcomes"][0]["learning_point_id"], "lp-blocked-output")
        self.assertEqual(manifest["selected_point_outcomes"][0]["status"], "needs_review")

    def test_generate_cards_from_learning_points_repairs_partial_ai_card(self):
        original_call_model_batches = worker._legacy_worker.call_model_batches

        def fake_call_model_batches(project, segments):
            return {
                "segments": [
                    {
                        "id": segments[0]["id"],
                        "cards": [
                            {
                                "type": "phrase",
                                "learning_point_id": segments[0]["learning_point_id"],
                                "phrase": "wake up",
                                "answer_core": "wake up",
                                "english": segments[0]["text"],
                                "chinese": "醒来；意识到",
                            }
                        ],
                    }
                ]
            }

        worker._legacy_worker.call_model_batches = fake_call_model_batches
        try:
            project = worker.handle_generate_cards_from_learning_points(
                {
                    "project_id": "repair-test",
                    "title": "test",
                    "language": "en",
                    "level": "B1",
                    "api_config": self._ai_config(),
                    "disable_card_generation_cache": True,
                    "selected_learning_point_ids": ["lp-partial"],
                    "learning_points": [
                        {
                            "id": "lp-partial",
                            "source_segment_id": "src-partial",
                            "source_sentence": "I need to wake up earlier tomorrow.",
                            "source_time": "00:00:03.000 - 00:00:06.000",
                            "start": 3.0,
                            "end": 6.0,
                            "exact_span": "wake up",
                            "answer_core": "wake up",
                            "candidate_kind": "expression",
                            "phrase_type": "phrasal_verb",
                            "learning_action": "训练 wake up 的自然用法。",
                            "reason": "高频短语动词。",
                            "value_score": 4.2,
                            "status": "recommended",
                        }
                    ],
                    "card_types": ["phrase"],
                }
            )
        finally:
            worker._legacy_worker.call_model_batches = original_call_model_batches

        card = project["segments"][0]["cards"][0]
        self.assertEqual(project["card_generation_diagnostics"]["generated_card_count"], 1)
        self.assertEqual(project["card_generation_diagnostics"]["missing_learning_point_count"], 0)
        self.assertEqual(card["generation_source"], "ai_repaired")
        self.assertTrue(card.get("enabled"))
        self.assertEqual(card["quality"]["status"], "recommended")
        self.assertIn("definition", card["missing_ai_fields"])
        self.assertNotIn("fallback_fields_filled", card)
        self.assertTrue(card["definition"])
        self.assertTrue(card["teacher_note"])

    def test_generate_cards_from_learning_points_preserves_ai_scan_stats(self):
        original_call_model_batches = worker._legacy_worker.call_model_batches

        def fake_call_model_batches(project, segments):
            return {
                "segments": [
                    {
                        "id": segments[0]["id"],
                        "cards": [
                            {
                                "type": "phrase",
                                "learning_point_id": segments[0]["learning_point_id"],
                                "phrase": "run the register",
                                "answer_core": "run the register",
                                "english": segments[0]["text"],
                                "chinese": "负责收银",
                                "definition": "operate the cash register",
                                "collocations": "run the register",
                                "context": segments[0]["text"],
                                "example": "Can you run the register?",
                                "chinese_feel": "负责收银",
                                "why": "服务业高频场景表达。",
                                "difficulty": "B1",
                                "teacher_note": "AI mock 完整制卡。",
                                "cloze": "Can you ____ for a minute?",
                            }
                        ],
                    }
                ]
            }

        worker._legacy_worker.call_model_batches = fake_call_model_batches
        try:
            project = worker.handle_generate_cards_from_learning_points(
                {
                    "project_id": "project-test",
                    "title": "test",
                    "language": "en",
                    "level": "B1",
                    "api_config": self._ai_config(),
                    "review_basis": "ai_reviewed",
                    "ai_model_provider": "gemini-vertex",
                    "ai_model_name": "gemini-3.1-pro-preview",
                    "ai_reviewed_source_count": 538,
                    "ai_reviewed_candidate_count": 168,
                    "local_candidate_count": 195,
                    "quality_funnel": {
                        "source_sentence_count": 544,
                        "ai_reviewed_source_count": 538,
                        "ai_reviewed_candidate_count": 168,
                        "local_candidate_count": 195,
                        "learning_point_count": 391,
                        "recommended_learning_point_count": 239,
                        "candidate_only_learning_point_count": 152,
                        "hidden_duplicate_learning_point_count": 11,
                        "hard_blocked_learning_point_count": 7,
                        "ai_recommended_count": 239,
                        "ai_candidate_count": 152,
                        "ai_rejected_count": 62,
                    },
                    "selected_learning_point_ids": ["lp-1"],
                    "learning_points": [
                        {
                            "id": "lp-1",
                            "source_segment_id": "src-1",
                            "source_sentence": "Can you run the register for a minute?",
                            "source_time": "00:00:10.000 - 00:00:12.000",
                            "start": 10.0,
                            "end": 12.0,
                            "exact_span": "run the register",
                            "answer_core": "run the register",
                            "normalized_answer": "run the register",
                            "candidate_kind": "expression",
                            "phrase_type": "collocation",
                            "learning_action": "训练服务业场景搭配。",
                            "learning_action_key": "expression:run the register",
                            "value_score": 4.6,
                            "reason": "可迁移词伙。",
                            "confidence": "high",
                            "status": "recommended",
                        }
                    ],
                    "card_types": ["phrase"],
                }
            )
        finally:
            worker._legacy_worker.call_model_batches = original_call_model_batches

        self.assertEqual(project["quality_funnel"]["source_sentence_count"], 544)
        self.assertEqual(project["quality_funnel"]["ai_reviewed_source_count"], 538)
        self.assertEqual(project["quality_funnel"]["learning_point_count"], 391)
        self.assertEqual(project["quality_funnel"]["candidate_only_learning_point_count"], 152)
        self.assertEqual(project["quality_funnel"]["hidden_duplicate_learning_point_count"], 11)
        self.assertEqual(project["quality_funnel"]["hard_blocked_learning_point_count"], 7)
        self.assertEqual(project["ai_reviewed_source_count"], 538)
        self.assertEqual(project["ai_model_name"], "gemini-3.1-pro-preview")

    def test_generate_cards_from_learning_points_reuses_card_generation_cache(self):
        original_call_model_batches = worker._legacy_worker.call_model_batches
        calls = {"count": 0}
        cwd = os.getcwd()

        def fake_call_model_batches(project, segments):
            calls["count"] += 1
            return {
                "segments": [
                    {
                        "id": segment["id"],
                        "cards": [
                            {
                                "type": "phrase",
                                "learning_point_id": segment["learning_point_id"],
                                "phrase": segment["answer_core"],
                                "answer_core": segment["answer_core"],
                                "english": segment["text"],
                                "chinese": "操作收银机",
                                "definition": "operate the cash register",
                                "collocations": "run the register",
                                "context": segment["text"],
                                "example": "Can you run the register?",
                                "chinese_feel": "负责收银",
                                "why": "服务业高频场景表达。",
                                "difficulty": "B1",
                                "teacher_note": "AI mock 完整制卡。",
                                "cloze": "Can you ____ for a minute?",
                            }
                        ],
                    }
                    for segment in segments
                ]
            }

        worker._legacy_worker.call_model_batches = fake_call_model_batches
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                os.chdir(temp_dir)
                payload = {
                    "project_id": "project-test",
                    "title": "test",
                    "language": "en",
                    "level": "B1",
                    "api_config": {
                        "provider": "gemini-vertex",
                        "model": "gemini-3.1-pro-preview",
                        "project": "test-project",
                        "location": "global",
                    },
                    "selected_learning_point_ids": ["lp-1"],
                    "learning_points": [
                        {
                            "id": "lp-1",
                            "source_segment_id": "src-1",
                            "source_sentence": "Can you run the register for a minute?",
                            "source_time": "00:00:10.000 - 00:00:12.000",
                            "start": 10.0,
                            "end": 12.0,
                            "exact_span": "run the register",
                            "answer_core": "run the register",
                            "normalized_answer": "run the register",
                            "type": "phrase",
                            "candidate_kind": "expression",
                            "phrase_type": "collocation",
                            "level": "B1",
                            "learning_action": "训练服务业场景搭配。",
                            "learning_action_key": "expression:run the register",
                            "value_score": 4.6,
                            "reason": "可迁移词伙。",
                            "confidence": "high",
                            "status": "recommended",
                        }
                    ],
                    "card_types": ["phrase"],
                }
                first = worker.handle_generate_cards_from_learning_points(payload)
                second = worker.handle_generate_cards_from_learning_points(payload)
                os.chdir(cwd)
        finally:
            os.chdir(cwd)
            worker._legacy_worker.call_model_batches = original_call_model_batches

        self.assertEqual(calls["count"], 1)
        self.assertEqual(first["segments"][0]["cards"][0]["phrase"], "run the register")
        self.assertEqual(second["segments"][0]["cards"][0]["phrase"], "run the register")
        self.assertFalse(first["quality_funnel"]["card_generation_cache_hit"])
        self.assertTrue(second["quality_funnel"]["card_generation_cache_hit"])
        self.assertEqual(second["quality_funnel"]["card_generation_cache_hits"], 1)

    def test_generate_cards_from_learning_points_card_cache_read_disabled_still_writes_for_hot(self):
        original_call_model_batches = worker._legacy_worker.call_model_batches
        calls = {"count": 0}
        cwd = os.getcwd()

        def fake_call_model_batches(project, segments):
            calls["count"] += 1
            return {
                "segments": [
                    {
                        "id": segment["id"],
                        "cards": [
                            {
                                "type": "phrase",
                                "learning_point_id": segment["learning_point_id"],
                                "phrase": segment["answer_core"],
                                "answer_core": segment["answer_core"],
                                "english": segment["text"],
                                "chinese": "负责收银",
                                "definition": "operate the cash register",
                                "collocations": segment["answer_core"],
                                "context": segment["text"],
                                "example": segment["text"],
                                "chinese_feel": "服务业语境",
                                "why": "高频口语表达。",
                                "difficulty": "B1",
                                "teacher_note": "AI mock 完整制卡。",
                                "cloze": "Can you ____?",
                            }
                        ],
                    }
                    for segment in segments
                ]
            }

        worker._legacy_worker.call_model_batches = fake_call_model_batches
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                os.chdir(temp_dir)
                base_payload = {
                    "project_id": "project-test",
                    "title": "test",
                    "language": "en",
                    "level": "B1",
                    "card_generation_cache_namespace": "read-write-split",
                    "api_config": {
                        "provider": "gemini-vertex",
                        "model": "gemini-3.1-pro-preview",
                        "project": "test-project",
                        "location": "global",
                    },
                    "selected_learning_point_ids": ["lp-1"],
                    "learning_points": [
                        {
                            "id": "lp-1",
                            "source_segment_id": "src-1",
                            "source_sentence": "Can you run the register for a minute?",
                            "source_time": "00:00:10.000 - 00:00:12.000",
                            "start": 10.0,
                            "end": 12.0,
                            "exact_span": "run the register",
                            "answer_core": "run the register",
                            "normalized_answer": "run the register",
                            "candidate_kind": "expression",
                            "phrase_type": "collocation",
                            "learning_action": "训练服务业场景搭配。",
                            "learning_action_key": "expression:run the register",
                            "value_score": 4.6,
                            "reason": "可迁移词伙。",
                            "confidence": "high",
                            "status": "recommended",
                        }
                    ],
                    "card_types": ["phrase"],
                }
                cold = worker.handle_generate_cards_from_learning_points(
                    {**base_payload, "disable_card_generation_cache_read": True}
                )
                hot = worker.handle_generate_cards_from_learning_points(base_payload)
                os.chdir(cwd)
        finally:
            os.chdir(cwd)
            worker._legacy_worker.call_model_batches = original_call_model_batches

        self.assertEqual(calls["count"], 1)
        self.assertEqual(cold["quality_funnel"]["card_generation_cache_hits"], 0)
        self.assertEqual(cold["quality_funnel"]["card_generation_cache_misses"], 1)
        self.assertFalse(cold["quality_funnel"]["card_generation_cache_read_enabled"])
        self.assertTrue(cold["quality_funnel"]["card_generation_cache_write_enabled"])
        self.assertEqual(hot["quality_funnel"]["card_generation_cache_hits"], 1)
        self.assertEqual(hot["quality_funnel"]["card_generation_cache_misses"], 0)
        self.assertTrue(hot["quality_funnel"]["card_generation_cache_read_enabled"])
        self.assertTrue(hot["quality_funnel"]["card_generation_cache_write_enabled"])

    def test_generate_cards_from_learning_points_card_cache_namespace_isolated_when_explicit(self):
        original_call_model_batches = worker._legacy_worker.call_model_batches
        calls = {"count": 0}
        cwd = os.getcwd()

        def fake_call_model_batches(project, segments):
            calls["count"] += 1
            return {
                "segments": [
                    {
                        "id": segment["id"],
                        "cards": [
                            {
                                "type": "phrase",
                                "learning_point_id": segment["learning_point_id"],
                                "phrase": segment["answer_core"],
                                "answer_core": segment["answer_core"],
                                "english": segment["text"],
                                "chinese": f"解释 {calls['count']}",
                                "definition": "definition",
                                "collocations": segment["answer_core"],
                                "context": segment["text"],
                                "example": segment["text"],
                                "chinese_feel": "语境理解",
                                "why": "高频表达。",
                                "difficulty": "B1",
                                "teacher_note": "AI mock 完整制卡。",
                                "cloze": "Can you ____?",
                            }
                        ],
                    }
                    for segment in segments
                ]
            }

        worker._legacy_worker.call_model_batches = fake_call_model_batches
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                os.chdir(temp_dir)
                base_payload = {
                    "project_id": "project-test",
                    "title": "test",
                    "language": "en",
                    "level": "B1",
                    "api_config": {
                        "provider": "gemini-vertex",
                        "model": "gemini-3.1-pro-preview",
                        "project": "test-project",
                        "location": "global",
                    },
                    "selected_learning_point_ids": ["lp-1"],
                    "learning_points": [
                        {
                            "id": "lp-1",
                            "source_segment_id": "src-1",
                            "source_sentence": "Can you run the register for a minute?",
                            "source_time": "00:00:10.000 - 00:00:12.000",
                            "start": 10.0,
                            "end": 12.0,
                            "exact_span": "run the register",
                            "answer_core": "run the register",
                            "normalized_answer": "run the register",
                            "candidate_kind": "expression",
                            "phrase_type": "collocation",
                            "learning_action": "训练服务业场景搭配。",
                            "learning_action_key": "expression:run the register",
                            "value_score": 4.6,
                            "reason": "可迁移词伙。",
                            "confidence": "high",
                            "status": "recommended",
                        }
                    ],
                    "card_types": ["phrase"],
                }
                first = worker.handle_generate_cards_from_learning_points(
                    {**base_payload, "card_generation_cache_namespace": "ns-a"}
                )
                second = worker.handle_generate_cards_from_learning_points(
                    {**base_payload, "card_generation_cache_namespace": "ns-b"}
                )
                third = worker.handle_generate_cards_from_learning_points(
                    {**base_payload, "card_generation_cache_namespace": "ns-a"}
                )
                os.chdir(cwd)
        finally:
            os.chdir(cwd)
            worker._legacy_worker.call_model_batches = original_call_model_batches

        self.assertEqual(calls["count"], 2)
        self.assertEqual(first["quality_funnel"]["card_generation_cache_hits"], 0)
        self.assertEqual(second["quality_funnel"]["card_generation_cache_hits"], 0)
        self.assertEqual(third["quality_funnel"]["card_generation_cache_hits"], 1)
        self.assertEqual(third["quality_funnel"]["card_generation_cache_namespace"], "ns-a")

    def test_generate_cards_from_learning_points_retries_unusable_payload_without_poisoning_cache(self):
        original_call_model_batches = worker._legacy_worker.call_model_batches
        calls = {"count": 0}
        cwd = os.getcwd()

        def fake_call_model_batches(project, segments):
            calls["count"] += 1
            if calls["count"] == 1:
                return {"segments": [{"id": segments[0]["id"], "cards": [{"type": "phrase"}]}]}
            return {
                "segments": [
                    {
                        "id": segments[0]["id"],
                        "cards": [
                            {
                                "type": "phrase",
                                "learning_point_id": segments[0]["learning_point_id"],
                                "phrase": "run the register",
                                "answer_core": "run the register",
                                "english": segments[0]["text"],
                                "chinese": "负责收银",
                                "definition": "operate the cash register",
                                "collocations": "run the register",
                                "context": segments[0]["text"],
                                "example": "Can you run the register?",
                                "chinese_feel": "负责收银",
                                "why": "服务业高频场景表达。",
                                "difficulty": "B1",
                                "teacher_note": "AI mock 完整制卡。",
                                "cloze": "Can you ____ for a minute?",
                            }
                        ],
                    }
                ]
            }

        worker._legacy_worker.call_model_batches = fake_call_model_batches
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                os.chdir(temp_dir)
                payload = {
                    "project_id": "project-test",
                    "title": "test",
                    "language": "en",
                    "level": "B1",
                    "api_config": {
                        "provider": "gemini-vertex",
                        "model": "gemini-3.1-pro-preview",
                        "project": "test-project",
                        "location": "global",
                    },
                    "selected_learning_point_ids": ["lp-1"],
                    "learning_points": [
                        {
                            "id": "lp-1",
                            "source_segment_id": "src-1",
                            "source_sentence": "Can you run the register for a minute?",
                            "source_time": "00:00:10.000 - 00:00:12.000",
                            "start": 10.0,
                            "end": 12.0,
                            "exact_span": "run the register",
                            "answer_core": "run the register",
                            "normalized_answer": "run the register",
                            "candidate_kind": "expression",
                            "phrase_type": "collocation",
                            "learning_action": "训练服务业场景搭配。",
                            "learning_action_key": "expression:run the register",
                            "value_score": 4.6,
                            "reason": "可迁移词伙。",
                            "confidence": "high",
                            "status": "recommended",
                        }
                    ],
                    "card_types": ["phrase"],
                }
                first = worker.handle_generate_cards_from_learning_points(payload)
                second = worker.handle_generate_cards_from_learning_points(payload)
                os.chdir(cwd)
        finally:
            os.chdir(cwd)
            worker._legacy_worker.call_model_batches = original_call_model_batches

        self.assertEqual(calls["count"], 2)
        self.assertEqual(first["segments"][0]["cards"][0]["phrase"], "run the register")
        self.assertEqual(first["quality_funnel"]["card_generation_retry_count"], 1)
        self.assertTrue(second["quality_funnel"]["card_generation_cache_hit"])
        self.assertEqual(second["segments"][0]["cards"][0]["phrase"], "run the register")

    def test_generate_cards_from_learning_points_only_calls_model_for_cache_misses(self):
        original_call_model_batches = worker._legacy_worker.call_model_batches
        called_batches: list[list[str]] = []
        cwd = os.getcwd()

        def learning_point(lp_id: str, text: str, answer: str) -> dict:
            return {
                "id": lp_id,
                "source_segment_id": lp_id.replace("lp", "src"),
                "source_sentence": text,
                "source_time": "00:00:10.000 - 00:00:12.000",
                "start": 10.0,
                "end": 12.0,
                "exact_span": answer,
                "answer_core": answer,
                "normalized_answer": answer,
                "type": "phrase",
                "candidate_kind": "expression",
                "phrase_type": "collocation",
                "level": "B1",
                "learning_action": f"训练 {answer}。",
                "learning_action_key": f"expression:{answer}",
                "value_score": 4.6,
                "reason": "可迁移词伙。",
                "confidence": "high",
                "status": "recommended",
            }

        def fake_call_model_batches(project, segments):
            called_batches.append([str(segment["learning_point_id"]) for segment in segments])
            return {
                "segments": [
                    {
                        "id": segment["id"],
                        "cards": [
                            {
                                "type": "phrase",
                                "learning_point_id": segment["learning_point_id"],
                                "phrase": segment["answer_core"],
                                "answer_core": segment["answer_core"],
                                "english": segment["text"],
                                "chinese": "中文解释",
                                "definition": "definition",
                                "collocations": segment["answer_core"],
                                "context": segment["text"],
                                "example": segment["text"],
                                "chinese_feel": "语境理解",
                                "why": "高频表达。",
                                "difficulty": "B1",
                                "teacher_note": "AI mock 完整制卡。",
                                "cloze": "Can you ____?",
                            }
                        ],
                    }
                    for segment in segments
                ]
            }

        worker._legacy_worker.call_model_batches = fake_call_model_batches
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                os.chdir(temp_dir)
                points = [
                    learning_point("lp-1", "Can you run the register?", "run the register"),
                    learning_point("lp-2", "I'm not in the mood.", "in the mood"),
                    learning_point("lp-3", "It turns out fine.", "turns out"),
                ]
                base_payload = {
                    "project_id": "project-test",
                    "title": "test",
                    "language": "en",
                    "level": "B1",
                    "api_config": {
                        "provider": "gemini-vertex",
                        "model": "gemini-3.1-pro-preview",
                        "project": "test-project",
                        "location": "global",
                    },
                    "learning_points": points,
                    "card_types": ["phrase"],
                }
                worker.handle_generate_cards_from_learning_points(
                    {**base_payload, "selected_learning_point_ids": ["lp-1", "lp-2"]}
                )
                second = worker.handle_generate_cards_from_learning_points(
                    {**base_payload, "selected_learning_point_ids": ["lp-1", "lp-2", "lp-3"]}
                )
                os.chdir(cwd)
        finally:
            os.chdir(cwd)
            worker._legacy_worker.call_model_batches = original_call_model_batches

        self.assertEqual(called_batches, [["lp-1", "lp-2"], ["lp-3"]])
        self.assertEqual(second["quality_funnel"]["card_generation_cache_hits"], 2)
        self.assertEqual(second["quality_funnel"]["card_generation_cache_misses"], 1)
        self.assertEqual([segment["learning_point_id"] for segment in second["segments"]], ["lp-1", "lp-2", "lp-3"])

    def test_generate_cards_from_learning_points_incremental_skips_existing_learning_points(self):
        original_call_model_batches = worker._legacy_worker.call_model_batches
        seen_learning_point_ids: list[str] = []

        def fake_call_model_batches(project, segments):
            seen_learning_point_ids.extend(str(segment["learning_point_id"]) for segment in segments)
            return {
                "segments": [
                    {
                        "id": segment["id"],
                        "cards": [
                            {
                                "type": "phrase",
                                "learning_point_id": segment["learning_point_id"],
                                "phrase": segment["answer_core"],
                                "answer_core": segment["answer_core"],
                                "english": segment["text"],
                                "chinese": "新增解释",
                                "definition": "new definition",
                                "collocations": segment["answer_core"],
                                "context": segment["text"],
                                "example": segment["text"],
                                "chinese_feel": "新增语境",
                                "why": "补卡。",
                                "difficulty": "B1",
                                "teacher_note": "AI mock 增量制卡。",
                                "cloze": "Can you ____?",
                            }
                        ],
                    }
                    for segment in segments
                ]
            }

        worker._legacy_worker.call_model_batches = fake_call_model_batches
        try:
            project = worker.handle_generate_cards_from_learning_points(
                {
                    "project_id": "project-test",
                    "title": "test",
                    "language": "en",
                    "level": "B1",
                    "disable_card_generation_cache": True,
                    "api_config": self._ai_config(),
                    "selected_learning_point_ids": ["lp-1", "lp-2"],
                    "existing_project": {
                        "id": "project-test",
                        "title": "test",
                        "segments": [
                            {
                                "id": "seg_lp_0001",
                                "learning_point_id": "lp-1",
                                "text": "Can you run the register?",
                                "cards": [
                                    {
                                        "id": "card_0001",
                                        "type": "phrase",
                                        "enabled": True,
                                        "learning_point_id": "lp-1",
                                        "phrase": "run the register",
                                        "english": "Can you run the register?",
                                        "chinese": "已有解释",
                                        "definition": "existing definition",
                                    },
                                    {
                                        "id": "card_blocked_0001",
                                        "type": "phrase",
                                        "enabled": True,
                                        "learning_point_id": "lp-1",
                                        "phrase": "run the register",
                                        "english": "Can you run the register?",
                                        "chinese": "",
                                        "definition": "needs repair",
                                        "quality": {"issues": ["缺少中文意思"]},
                                    },
                                ],
                            }
                        ],
                    },
                    "learning_points": [
                        {
                            "id": "lp-1",
                            "source_segment_id": "src-1",
                            "source_sentence": "Can you run the register?",
                            "source_time": "00:00:10.000 - 00:00:12.000",
                            "start": 10.0,
                            "end": 12.0,
                            "exact_span": "run the register",
                            "answer_core": "run the register",
                            "normalized_answer": "run the register",
                            "type": "phrase",
                            "candidate_kind": "expression",
                            "phrase_type": "collocation",
                            "learning_action": "训练服务业表达。",
                            "learning_action_key": "expression:run the register",
                            "value_score": 4.6,
                            "reason": "可迁移词伙。",
                            "confidence": "high",
                            "status": "recommended",
                        },
                        {
                            "id": "lp-2",
                            "source_segment_id": "src-2",
                            "source_sentence": "I'm not in the mood.",
                            "source_time": "00:00:13.000 - 00:00:15.000",
                            "start": 13.0,
                            "end": 15.0,
                            "exact_span": "in the mood",
                            "answer_core": "in the mood",
                            "normalized_answer": "in the mood",
                            "type": "phrase",
                            "candidate_kind": "expression",
                            "phrase_type": "collocation",
                            "learning_action": "训练情绪表达。",
                            "learning_action_key": "expression:in the mood",
                            "value_score": 4.4,
                            "reason": "口语高频。",
                            "confidence": "high",
                            "status": "recommended",
                        },
                    ],
                    "card_types": ["phrase"],
                }
            )
        finally:
            worker._legacy_worker.call_model_batches = original_call_model_batches

        self.assertEqual(seen_learning_point_ids, ["lp-2"])
        self.assertEqual([segment["learning_point_id"] for segment in project["segments"]], ["lp-1", "lp-2"])
        self.assertEqual(project["generated_learning_point_ids"], ["lp-1", "lp-2"])
        self.assertEqual(project["quality_funnel"]["generation_queue_count"], 2)
        self.assertEqual(project["quality_funnel"]["generation_success_count"], 2)
        self.assertEqual(project["quality_funnel"]["new_successful_learning_point_count"], 1)
        self.assertEqual(project["quality_funnel"]["existing_generated_selected_count"], 1)
        self.assertEqual(project["quality_funnel"]["generation_missing_count"], 0)
        self.assertEqual(project["quality_funnel"]["generation_reconciliation_status"], "ok")
        diagnostics = project["card_generation_diagnostics"]
        self.assertEqual(diagnostics["processed_learning_point_count"], 2)
        self.assertEqual(diagnostics["successful_learning_point_count"], 2)
        self.assertEqual(diagnostics["new_successful_learning_point_count"], 1)
        self.assertEqual(diagnostics["existing_generated_selected_count"], 1)
        self.assertEqual(diagnostics["missing_learning_point_count"], 0)

    def test_generate_cards_from_learning_points_ignores_existing_shells_without_exportable_cards(self):
        original_call_model_batches = worker._legacy_worker.call_model_batches
        seen_learning_point_ids: list[str] = []

        def fake_call_model_batches(project, segments):
            seen_learning_point_ids.extend(str(segment["learning_point_id"]) for segment in segments)
            return {
                "segments": [
                    {
                        "id": segment["id"],
                        "cards": [
                            {
                                "type": "phrase",
                                "enabled": True,
                                "learning_point_id": segment["learning_point_id"],
                                "phrase": segment["answer_core"],
                                "answer_core": segment["answer_core"],
                                "english": segment["text"],
                                "chinese": "重新生成的解释",
                                "definition": "重新生成的定义",
                                "collocations": segment["answer_core"],
                                "context": segment["text"],
                                "example": segment["text"],
                                "chinese_feel": "重新生成后可导出。",
                                "why": "补齐旧项目里没有可用卡的学习点。",
                                "teacher_note": "旧项目壳不能算作已生成。",
                                "cloze": segment["text"],
                            }
                        ],
                    }
                    for segment in segments
                ]
            }

        points = [
            {
                "id": "lp-empty-shell",
                "source_segment_id": "src-1",
                "source_sentence": "Can you run the register?",
                "source_time": "00:00:10.000 - 00:00:12.000",
                "start": 10.0,
                "end": 12.0,
                "exact_span": "run the register",
                "answer_core": "run the register",
                "normalized_answer": "run the register",
                "type": "phrase",
                "candidate_kind": "expression",
                "phrase_type": "collocation",
                "learning_action": "训练服务业表达。",
                "learning_action_key": "expression:run the register",
                "value_score": 4.6,
                "reason": "可迁移词伙。",
                "confidence": "high",
                "status": "recommended",
            },
            {
                "id": "lp-disabled-card",
                "source_segment_id": "src-2",
                "source_sentence": "I'm not in the mood.",
                "source_time": "00:00:13.000 - 00:00:15.000",
                "start": 13.0,
                "end": 15.0,
                "exact_span": "in the mood",
                "answer_core": "in the mood",
                "normalized_answer": "in the mood",
                "type": "phrase",
                "candidate_kind": "expression",
                "phrase_type": "collocation",
                "learning_action": "训练情绪表达。",
                "learning_action_key": "expression:in the mood",
                "value_score": 4.4,
                "reason": "口语高频。",
                "confidence": "high",
                "status": "recommended",
            },
        ]

        worker._legacy_worker.call_model_batches = fake_call_model_batches
        try:
            project = worker.handle_generate_cards_from_learning_points(
                {
                    "project_id": "project-existing-shells",
                    "title": "test",
                    "language": "en",
                    "level": "B1",
                    "api_config": self._ai_config(),
                    "disable_card_generation_cache": True,
                    "selected_learning_point_ids": [point["id"] for point in points],
                    "existing_generated_ids": [point["id"] for point in points],
                    "existing_project": {
                        "id": "project-existing-shells",
                        "title": "test",
                        "segments": [
                            {
                                "id": "seg_lp_0001",
                                "learning_point_id": "lp-empty-shell",
                                "text": "Can you run the register?",
                                "cards": [],
                            },
                            {
                                "id": "seg_lp_0002",
                                "learning_point_id": "lp-disabled-card",
                                "text": "I'm not in the mood.",
                                "cards": [
                                    {
                                        "id": "card-disabled",
                                        "type": "phrase",
                                        "enabled": False,
                                        "learning_point_id": "lp-disabled-card",
                                        "phrase": "in the mood",
                                        "english": "I'm not in the mood.",
                                        "chinese": "旧的禁用卡",
                                        "definition": "不能算作已生成。",
                                    }
                                ],
                            },
                        ],
                    },
                    "learning_points": points,
                    "card_types": ["phrase"],
                }
            )
        finally:
            worker._legacy_worker.call_model_batches = original_call_model_batches

        self.assertEqual(seen_learning_point_ids, ["lp-empty-shell", "lp-disabled-card"])
        self.assertEqual([segment["learning_point_id"] for segment in project["segments"]], ["lp-empty-shell", "lp-disabled-card"])
        generated_cards = [
            card
            for segment in project["segments"]
            for card in segment.get("cards", [])
            if card.get("enabled")
        ]
        self.assertEqual(len(generated_cards), 2)
        self.assertEqual(project["generated_learning_point_ids"], ["lp-disabled-card", "lp-empty-shell"])
        self.assertEqual(project["quality_funnel"]["existing_generated_selected_count"], 0)
        self.assertEqual(project["quality_funnel"]["new_successful_learning_point_count"], 2)
        self.assertEqual(project["quality_funnel"]["generation_success_count"], 2)
        self.assertEqual(project["quality_funnel"]["generation_missing_count"], 0)

    def test_generate_cards_from_learning_points_all_existing_reports_reconciled(self):
        original_call_model_batches = worker._legacy_worker.call_model_batches

        def fail_if_called(project, segments):
            raise AssertionError("existing learning points should not call the model")

        worker._legacy_worker.call_model_batches = fail_if_called
        try:
            project = worker.handle_generate_cards_from_learning_points(
                {
                    "project_id": "project-existing",
                    "title": "test",
                    "language": "en",
                    "level": "B1",
                    "api_config": self._ai_config(),
                    "selected_learning_point_ids": ["lp-1"],
                    "existing_project": {
                        "id": "project-existing",
                        "title": "test",
                        "tts_semantic_verification": {
                            "enabled": True,
                            "require_pass_for_export": True,
                            "asr_provider": "whisper-cli",
                        },
                        "asr_provider": "whisper-cli",
                        "require_pass_for_export": True,
                        "enable_asr_quality_gate": True,
                        "segments": [
                            {
                                "id": "seg_lp_0001",
                                "learning_point_id": "lp-1",
                                "text": "Can you run the register?",
                                "cards": [
                                    {
                                        "id": "card_0001",
                                        "type": "phrase",
                                        "enabled": True,
                                        "learning_point_id": "lp-1",
                                        "phrase": "run the register",
                                        "english": "Can you run the register?",
                                        "chinese": "已有解释",
                                        "definition": "existing definition",
                                    }
                                ],
                            }
                        ],
                    },
                    "learning_points": [
                        {
                            "id": "lp-1",
                            "source_segment_id": "src-1",
                            "source_sentence": "Can you run the register?",
                            "source_time": "00:00:10.000 - 00:00:12.000",
                            "start": 10.0,
                            "end": 12.0,
                            "exact_span": "run the register",
                            "answer_core": "run the register",
                            "candidate_kind": "expression",
                            "phrase_type": "collocation",
                            "learning_action": "训练服务业表达。",
                            "value_score": 4.6,
                            "status": "recommended",
                        },
                    ],
                    "card_types": ["phrase"],
                }
            )
        finally:
            worker._legacy_worker.call_model_batches = original_call_model_batches

        self.assertEqual([segment["learning_point_id"] for segment in project["segments"]], ["lp-1"])
        self.assertEqual(project["quality_funnel"]["generation_queue_count"], 1)
        self.assertEqual(project["quality_funnel"]["generation_success_count"], 1)
        self.assertEqual(project["quality_funnel"]["new_successful_learning_point_count"], 0)
        self.assertEqual(project["quality_funnel"]["existing_generated_selected_count"], 1)
        self.assertEqual(project["quality_funnel"]["generation_missing_count"], 0)
        self.assertEqual(project["quality_funnel"]["generation_reconciliation_status"], "ok")
        diagnostics = project["card_generation_diagnostics"]
        self.assertEqual(diagnostics["processed_learning_point_count"], 1)
        self.assertEqual(diagnostics["successful_learning_point_count"], 1)
        self.assertEqual(diagnostics["generated_card_count"], 0)
        self.assertEqual(diagnostics["exportable_card_count"], 1)
        self.assertEqual(diagnostics["missing_learning_point_count"], 0)
        self.assertEqual(project.get("tts_semantic_verification"), {})
        self.assertNotIn("asr_provider", project)
        self.assertNotIn("require_pass_for_export", project)
        self.assertNotIn("enable_asr_quality_gate", project)
        self.assertNotIn("whisper-cli", json.dumps(project, ensure_ascii=False))

    def test_call_model_batches_uses_dynamic_weighted_batches(self):
        original_call_model_batch_with_retry = worker._legacy_worker.call_model_batch_with_retry
        batch_sizes: list[int] = []

        def fake_call_model_batch_with_retry(project, segments, **kwargs):
            batch_sizes.append(len(segments))
            return ([{"id": segment["id"], "cards": [{"phrase": segment["phrase"], "chinese": "解释"}]} for segment in segments], [], [])

        worker._legacy_worker.call_model_batch_with_retry = fake_call_model_batch_with_retry
        try:
            api_config = self._ai_config()
            api_config["card_generation_batch_weight"] = 4
            result = worker._legacy_worker.call_model_batches(
                {"api_config": api_config},
                [
                    {
                        "id": f"seg-{index}",
                        "text": "long text " * 180,
                        "phrase": f"phrase-{index}",
                        "answer_core": f"phrase-{index}",
                        "learning_action": "训练长文本学习点。",
                    }
                    for index in range(3)
                ],
                batch_size=10,
            )
        finally:
            worker._legacy_worker.call_model_batch_with_retry = original_call_model_batch_with_retry

        self.assertEqual(len(result["segments"]), 3)
        self.assertGreater(len(batch_sizes), 1)
        self.assertTrue(all(size <= 1 for size in batch_sizes))

    def test_document_point_generation_cache_only_calls_model_for_misses(self):
        original_call_document_model = worker._legacy_worker.call_document_model
        called_batches: list[list[str]] = []
        cwd = os.getcwd()

        def fake_call_document_model(project, segments):
            called_batches.append([str(segment["id"]) for segment in segments])
            return {
                "segments": [
                    {
                        "id": segment["id"],
                        "cards": [
                            {
                                "type": "knowledge",
                                "knowledge_type": "concepts",
                                "english": segment["text"],
                                "chinese": "核心答案",
                                "phrase": segment.get("phrase") or "概念",
                                "definition": "概念解释",
                                "source_evidence": segment.get("document_excerpt", ""),
                                "memory_hook": "记忆钩子",
                                "transfer_check": "迁移检查",
                                "boundary": "边界",
                                "collocations": "相关概念",
                                "context": "适用语境",
                                "example": "例子",
                                "why": "值得记。",
                                "teacher_note": "老师提醒。",
                                "cloze": "概念核心是 ____。",
                            }
                        ],
                    }
                    for segment in segments
                ]
            }

        worker._legacy_worker.call_document_model = fake_call_document_model
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                os.chdir(temp_dir)
                project = {
                    "api_config": self._ai_config(),
                    "language": "en",
                    "level": "B1",
                    "document_path": str(Path(temp_dir) / "doc.md"),
                    "document_study_mode": "knowledge",
                    "material_context": {"topic": "test"},
                }
                segments = [
                    {"id": "doc_0001", "text": "第一点是什么？", "phrase": "第一点", "document_excerpt": "第一点的原文依据。"},
                    {"id": "doc_0002", "text": "第二点是什么？", "phrase": "第二点", "document_excerpt": "第二点的原文依据。"},
                    {"id": "doc_0003", "text": "第三点是什么？", "phrase": "第三点", "document_excerpt": "第三点的原文依据。"},
                ]
                worker._legacy_worker.cached_or_generated_document_payload(
                    project,
                    segments[:2],
                    cache_disabled=False,
                )
                payload, stats = worker._legacy_worker.cached_or_generated_document_payload(
                    project,
                    segments,
                    cache_disabled=False,
                )
                os.chdir(cwd)
        finally:
            os.chdir(cwd)
            worker._legacy_worker.call_document_model = original_call_document_model

        self.assertEqual(called_batches, [["doc_0001", "doc_0002"], ["doc_0003"]])
        self.assertEqual(stats["cache_hits"], 2)
        self.assertEqual(stats["cache_misses"], 1)
        self.assertEqual([segment["id"] for segment in payload["segments"]], ["doc_0001", "doc_0002", "doc_0003"])

    def test_output_filter_removes_exact_duplicate_enabled_cards(self):
        segments = [
            {
                "id": "seg-a",
                "text": "I'm shorthanded, Walter. What am I to do?",
                "cards": [
                    {
                        "id": "card-a",
                        "type": "phrase",
                        "english": "I'm shorthanded, Walter. What am I to do?",
                        "phrase": "shorthanded",
                        "answer_core": "shorthanded",
                        "quality": {"status": "recommended", "score": 5, "issues": []},
                    }
                ],
            },
            {
                "id": "seg-b",
                "text": "I'm shorthanded, Walter. What am I to do?",
                "cards": [
                    {
                        "id": "card-b",
                        "type": "phrase",
                        "english": "I'm shorthanded, Walter. What am I to do?",
                        "phrase": "shorthanded",
                        "answer_core": "shorthanded",
                        "quality": {"status": "recommended", "score": 5, "issues": []},
                    }
                ],
            },
        ]

        filtered, stats = worker._legacy_worker.filter_usable_segments_for_output(segments, [])

        cards = [card for segment in filtered for card in segment["cards"]]
        self.assertEqual([card["id"] for card in cards], ["card-a"])
        self.assertEqual(stats["duplicate_learning_point_count"], 1)

    def test_output_filter_blocks_local_fallback_drafts_from_export(self):
        segments = [
            {
                "id": "seg-a",
                "text": "Tell you what, I'll let you off for a 10.",
                "cards": [
                    {
                        "id": "draft-card",
                        "type": "phrase",
                        "english": "Tell you what, I'll let you off for a 10.",
                        "phrase": "Tell you what",
                        "answer_core": "Tell you what",
                        "chinese": "待精修：先把 Tell you what 当作本句目标表达。",
                        "definition": "本地待审：正式导出前需要用 AI 精修释义。",
                        "teacher_note": "本地 fallback 只保证结构完整；正式导出前应使用模型精修内容。",
                        "quality": {
                            "status": "needs_review",
                            "score": 42,
                            "issues": ["本地草稿，需要人工确认", "字段像模板废话"],
                        },
                    },
                    {
                        "id": "good-card",
                        "type": "phrase",
                        "english": "Tell you what, I'll let you off for a 10.",
                        "phrase": "let you off",
                        "answer_core": "let you off",
                        "chinese": "放过某人；从轻处理。",
                        "definition": "表示不惩罚某人，或只给较轻的惩罚/要求。",
                        "teacher_note": "常接 with a warning，说明从轻处理的方式。",
                        "quality": {"status": "recommended", "score": 82, "issues": []},
                    },
                ],
            }
        ]

        filtered, stats = worker._legacy_worker.filter_usable_segments_for_output(segments, [])

        cards = [card for segment in filtered for card in segment["cards"]]
        self.assertEqual([card["id"] for card in cards], ["good-card"])
        self.assertEqual(stats["blocked_quality_issue_count"], 1)

    def test_mimo_token_plan_key_uses_token_plan_base_url(self):
        base_url = worker.compatible_base_url(
            {
                "provider": "mimo",
                "api_key": "tp-test-token",
                "base_url": "https://api.xiaomimimo.com/v1",
            }
        )

        self.assertEqual(base_url, worker.MIMO_TOKEN_PLAN_SGP_BASE_URL)

    def test_provider_config_helpers_match_worker_boundary(self):
        from acg import provider_config

        configs = [
            {"provider": "mimo", "api_key": "tp-token", "base_url": "https://api.xiaomimimo.com/v1", "model": "mimo-v2.5-pro"},
            {"provider": "mimo", "api_key": "sk-token", "model": "mimo-v2.5-pro"},
            {"provider": "openai-compatible", "api_key": "sk-token", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen3.1-max", "thinking_budget": 512},
            {"provider": "openai-compatible", "api_key": "sk-token", "base_url": "https://api.deepseek.com", "model": "deepseek-v4-pro", "reasoning_budget": 9000},
            {"provider": "gemini-vertex", "model": "gemini-3.1-pro-preview"},
            {"provider": "local", "model": "anything"},
            {"provider": "openai-compatible", "model": ""},
        ]

        for config in configs:
            self.assertEqual(worker._legacy_worker.provider_name(config), provider_config.provider_name(config))
            self.assertEqual(worker._legacy_worker.compatible_base_url(config, "https://default.example/v1"), provider_config.compatible_base_url(config, "https://default.example/v1"))
            self.assertEqual(worker._legacy_worker.is_mimo_config(config), provider_config.is_mimo_config(config))
            self.assertEqual(worker._legacy_worker.is_qwen_config(config), provider_config.is_qwen_config(config))
            self.assertEqual(worker._legacy_worker.is_deepseek_config(config), provider_config.is_deepseek_config(config))
            self.assertEqual(
                worker._legacy_worker.is_deepseek_thinking_config(config),
                provider_config.is_deepseek_thinking_config(config),
            )
            self.assertEqual(
                worker._legacy_worker.is_gemini_vertex_config(config),
                provider_config.is_gemini_vertex_config(config),
            )
            self.assertEqual(
                worker._legacy_worker.is_gemini_vertex_tts_config(config),
                provider_config.is_gemini_vertex_tts_config(config),
            )
            self.assertEqual(
                worker._legacy_worker.is_gemini_vertex_thinking_config(config),
                provider_config.is_gemini_vertex_thinking_config(config),
            )
            self.assertEqual(
                worker._legacy_worker.is_thinking_model_config(config),
                provider_config.is_thinking_model_config(config),
            )
            self.assertEqual(worker._legacy_worker.thinking_budget(config), provider_config.thinking_budget(config))
            self.assertEqual(
                worker._legacy_worker.should_stream_reasoning(config),
                provider_config.should_stream_reasoning(config),
            )
            self.assertEqual(worker._legacy_worker.api_key_header(config), provider_config.api_key_header(config))
            self.assertEqual(worker._legacy_worker.model_api_available(config), provider_config.model_api_available(config))

        self.assertEqual(worker._legacy_worker.MIMO_TOKEN_PLAN_SGP_BASE_URL, provider_config.MIMO_TOKEN_PLAN_SGP_BASE_URL)
        self.assertEqual(worker._legacy_worker.GEMINI_VERTEX_DEFAULT_MODEL, provider_config.GEMINI_VERTEX_DEFAULT_MODEL)

    def test_qwen_compatible_chat_completion_streams_with_thinking_budget(self):
        calls = {}
        original_http_sse_json_events = worker._legacy_worker.http_sse_json_events

        def fake_http_sse_json_events(url, headers, body, timeout=120):
            calls["url"] = url
            calls["headers"] = headers
            calls["body"] = body
            calls["timeout"] = timeout
            return [
                {"choices": [{"delta": {"reasoning_content": "thinking"}, "finish_reason": None}]},
                {"choices": [{"delta": {"content": '{"segments":[]}'}, "finish_reason": "stop"}]},
            ]

        try:
            worker._legacy_worker.http_sse_json_events = fake_http_sse_json_events
            response = worker.compatible_chat_completion(
                {
                    "provider": "openai-compatible",
                    "api_key": "sk-test",
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "model": "qwen3.1-max",
                    "thinking_budget": 512,
                },
                [{"role": "user", "content": "Return JSON."}],
                temperature=0,
                timeout=90,
                max_tokens=800,
            )
        finally:
            worker._legacy_worker.http_sse_json_events = original_http_sse_json_events

        self.assertEqual(calls["url"], "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
        self.assertEqual(calls["headers"]["Authorization"], "Bearer sk-test")
        self.assertEqual(calls["body"]["response_format"], {"type": "json_object"})
        self.assertTrue(calls["body"]["enable_thinking"])
        self.assertEqual(calls["body"]["thinking_budget"], 512)
        self.assertTrue(calls["body"]["stream"])
        self.assertEqual(calls["body"]["stream_options"], {"include_usage": True})
        self.assertEqual(calls["body"]["max_tokens"], 800)
        self.assertEqual(calls["timeout"], 90)
        self.assertEqual(response["choices"][0]["message"]["content"], '{"segments":[]}')
        self.assertEqual(response["choices"][0]["message"]["reasoning_content"], "thinking")

    def test_mimo_compatible_chat_completion_enables_thinking_stream(self):
        calls = {}
        original_http_sse_json_events = worker._legacy_worker.http_sse_json_events

        def fake_http_sse_json_events(url, headers, body, timeout=120):
            calls["url"] = url
            calls["headers"] = headers
            calls["body"] = body
            return [
                {"choices": [{"delta": {"reasoning_content": "reason"}, "finish_reason": None}]},
                {"choices": [{"delta": {"content": '{"segments":[]}'}, "finish_reason": "stop"}]},
            ]

        try:
            worker._legacy_worker.http_sse_json_events = fake_http_sse_json_events
            response = worker.compatible_chat_completion(
                {
                    "provider": "mimo",
                    "api_key": "test-key",
                    "base_url": "https://api.xiaomimimo.com/v1",
                    "model": "mimo-v2.5-pro",
                },
                [{"role": "user", "content": "Return JSON."}],
                temperature=0,
                timeout=120,
                max_tokens=2000,
            )
        finally:
            worker._legacy_worker.http_sse_json_events = original_http_sse_json_events

        self.assertEqual(calls["url"], "https://api.xiaomimimo.com/v1/chat/completions")
        self.assertEqual(calls["headers"]["api-key"], "test-key")
        self.assertEqual(calls["body"]["reasoning_effort"], "low")
        self.assertEqual(calls["body"]["thinking"], {"type": "enabled"})
        self.assertTrue(calls["body"]["stream"])
        self.assertEqual(calls["body"]["max_completion_tokens"], 2000)
        self.assertNotIn("response_format", calls["body"])
        self.assertEqual(response["choices"][0]["message"]["content"], '{"segments":[]}')
        self.assertEqual(response["choices"][0]["message"]["reasoning_content"], "reason")

    def test_deepseek_v4_compatible_chat_completion_streams_reasoning(self):
        calls = {}
        original_http_sse_json_events = worker._legacy_worker.http_sse_json_events

        def fake_http_sse_json_events(url, headers, body, timeout=120):
            calls["url"] = url
            calls["headers"] = headers
            calls["body"] = body
            calls["timeout"] = timeout
            return [
                {"choices": [{"delta": {"reasoning_content": "think"}, "finish_reason": None}]},
                {"choices": [{"delta": {"content": '{"segments":[]}'}, "finish_reason": "stop"}]},
            ]

        try:
            worker._legacy_worker.http_sse_json_events = fake_http_sse_json_events
            response = worker.compatible_chat_completion(
                {
                    "provider": "openai-compatible",
                    "api_key": "sk-deepseek",
                    "base_url": "https://api.deepseek.com",
                    "model": "deepseek-v4-pro",
                },
                [{"role": "user", "content": "Return JSON."}],
                temperature=0,
                timeout=180,
                max_tokens=8000,
            )
        finally:
            worker._legacy_worker.http_sse_json_events = original_http_sse_json_events

        self.assertEqual(calls["url"], "https://api.deepseek.com/chat/completions")
        self.assertEqual(calls["headers"]["Authorization"], "Bearer sk-deepseek")
        self.assertEqual(calls["body"]["response_format"], {"type": "json_object"})
        self.assertEqual(calls["body"]["thinking"], {"type": "enabled"})
        self.assertEqual(calls["body"]["reasoning_effort"], "high")
        self.assertTrue(calls["body"]["stream"])
        self.assertEqual(calls["body"]["stream_options"], {"include_usage": True})
        self.assertEqual(calls["body"]["max_tokens"], 8000)
        self.assertNotIn("enable_thinking", calls["body"])
        self.assertEqual(calls["timeout"], 180)
        self.assertEqual(response["choices"][0]["message"]["content"], '{"segments":[]}')
        self.assertEqual(response["choices"][0]["message"]["reasoning_content"], "think")

    def test_gemini_vertex_generate_content_uses_gcloud_auth_and_global_endpoint(self):
        calls = {}
        original_http_json = worker._legacy_worker.http_json
        original_gcloud_value = worker._legacy_worker.gcloud_value

        def fake_gcloud_value(args, timeout=30):
            calls.setdefault("gcloud", []).append(args)
            if args == ["config", "get-value", "core/project"]:
                return "project-test"
            if args == ["auth", "print-access-token"]:
                return "ya29.test-token"
            return ""

        def fake_http_json(url, headers, body, timeout=60):
            calls["url"] = url
            calls["headers"] = headers
            calls["body"] = body
            calls["timeout"] = timeout
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": '{"segments":[]}'},
                            ]
                        },
                        "finishReason": "STOP",
                    }
                ]
            }

        try:
            worker._legacy_worker.gcloud_value = fake_gcloud_value
            worker._legacy_worker.http_json = fake_http_json
            content = worker.gemini_vertex_generate_content(
                {
                    "provider": "gemini-vertex",
                    "base_url": "https://aiplatform.googleapis.com",
                    "model": "gemini-3.1-pro-preview",
                },
                "Return JSON.",
                temperature=0,
                timeout=180,
                max_output_tokens=16000,
            )
        finally:
            worker._legacy_worker.http_json = original_http_json
            worker._legacy_worker.gcloud_value = original_gcloud_value

        self.assertEqual(
            calls["url"],
            "https://aiplatform.googleapis.com/v1/projects/project-test/locations/global/"
            "publishers/google/models/gemini-3.1-pro-preview:generateContent",
        )
        self.assertEqual(calls["headers"]["Authorization"], "Bearer ya29.test-token")
        self.assertEqual(calls["body"]["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(calls["body"]["generationConfig"]["maxOutputTokens"], 16000)
        self.assertEqual(calls["body"]["generationConfig"]["temperature"], 0)
        self.assertEqual(calls["timeout"], 180)
        self.assertEqual(content, '{"segments":[]}')

    def test_gemini_vertex_model_alias_falls_back_to_preview(self):
        calls = {}
        original_http_json = worker._legacy_worker.http_json
        original_gcloud_value = worker._legacy_worker.gcloud_value

        def fake_gcloud_value(args, timeout=30):
            if args == ["config", "get-value", "core/project"]:
                return "project-test"
            if args == ["auth", "print-access-token"]:
                return "ya29.test-token"
            return ""

        def fake_http_json(url, headers, body, timeout=60):
            calls["url"] = url
            return {"candidates": [{"content": {"parts": [{"text": '{"segments":[]}'}]}}]}

        try:
            worker._legacy_worker.gcloud_value = fake_gcloud_value
            worker._legacy_worker.http_json = fake_http_json
            worker.gemini_vertex_generate_content(
                {
                    "provider": "gemini-vertex",
                    "base_url": "https://aiplatform.googleapis.com",
                    "model": "gemini-3.1-pro",
                },
                "Return JSON.",
            )
        finally:
            worker._legacy_worker.http_json = original_http_json
            worker._legacy_worker.gcloud_value = original_gcloud_value

        self.assertIn("/models/gemini-3.1-pro-preview:generateContent", calls["url"])

    def test_gemini_vertex_35_alias_maps_to_flash(self):
        calls = {}
        original_http_json = worker._legacy_worker.http_json
        original_gcloud_value = worker._legacy_worker.gcloud_value

        def fake_gcloud_value(args, timeout=30):
            if args == ["config", "get-value", "core/project"]:
                return "project-test"
            if args == ["auth", "print-access-token"]:
                return "ya29.test-token"
            return ""

        def fake_http_json(url, headers, body, timeout=60):
            calls["url"] = url
            return {"candidates": [{"content": {"parts": [{"text": '{"segments":[]}'}]}}]}

        try:
            worker._legacy_worker.gcloud_value = fake_gcloud_value
            worker._legacy_worker.http_json = fake_http_json
            worker.gemini_vertex_generate_content(
                {
                    "provider": "gemini-vertex",
                    "base_url": "https://aiplatform.googleapis.com",
                    "model": "gemini-3.5",
                },
                "Return JSON.",
            )
        finally:
            worker._legacy_worker.http_json = original_http_json
            worker._legacy_worker.gcloud_value = original_gcloud_value

        self.assertIn("/models/gemini-3.5-flash:generateContent", calls["url"])

    def test_test_api_classifies_gemini_vertex_timeout(self):
        original_generate = worker._legacy_worker.gemini_vertex_generate_content

        def fake_generate(*args, **kwargs):
            raise TimeoutError("timed out")

        try:
            worker._legacy_worker.gemini_vertex_generate_content = fake_generate
            result = worker.handle_test_api(
                {
                    "api_config": {
                        "provider": "gemini-vertex",
                        "base_url": "https://aiplatform.googleapis.com",
                        "model": "gemini-3.1-pro-preview",
                    }
                }
            )
        finally:
            worker._legacy_worker.gemini_vertex_generate_content = original_generate

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "MODEL_TIMEOUT")
        self.assertEqual(result["stage"], "model_api")
        self.assertTrue(result["retryable"])
        self.assertIn("模型请求超时", result["message"])

    def test_test_api_classifies_gemini_vertex_quota_error(self):
        original_generate = worker._legacy_worker.gemini_vertex_generate_content

        def fake_generate(*args, **kwargs):
            raise RuntimeError('API HTTP 429: {"error":{"message":"RESOURCE_EXHAUSTED quota exceeded"}}')

        try:
            worker._legacy_worker.gemini_vertex_generate_content = fake_generate
            result = worker.handle_test_api(
                {
                    "api_config": {
                        "provider": "gemini-vertex",
                        "base_url": "https://aiplatform.googleapis.com",
                        "model": "gemini-3.1-pro-preview",
                    }
                }
            )
        finally:
            worker._legacy_worker.gemini_vertex_generate_content = original_generate

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "MODEL_QUOTA_EXCEEDED")
        self.assertEqual(result["stage"], "model_api")
        self.assertTrue(result["retryable"])
        self.assertIn("模型配额或限流", result["message"])

    def test_test_tts_classifies_vertex_timeout(self):
        original_call_tts_audio = worker._legacy_worker.call_tts_audio

        def fake_call_tts_audio(*args, **kwargs):
            raise RuntimeError("Gemini Vertex TTS 请求失败：timed out")

        try:
            worker._legacy_worker.call_tts_audio = fake_call_tts_audio
            result = worker.handle_test_tts(
                {
                    "tts_config": {
                        "enabled": True,
                        "provider": "gemini-vertex",
                        "base_url": "https://aiplatform.googleapis.com",
                        "model": "gemini-3.1-flash-tts-preview",
                        "voice": "Kore",
                        "language": "auto",
                    },
                    "language": "en",
                }
            )
        finally:
            worker._legacy_worker.call_tts_audio = original_call_tts_audio

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "TTS_TIMEOUT")
        self.assertEqual(result["stage"], "tts")
        self.assertTrue(result["retryable"])
        self.assertIn("TTS请求超时", result["message"])

    def test_tts_output_volume_defaults_and_clamps(self):
        self.assertEqual(worker._legacy_worker.normalized_tts_config({"tts_config": {}})["output_volume"], 0.65)
        self.assertEqual(
            worker._legacy_worker.normalized_tts_config({"tts_config": {"output_volume": 0.2}})["output_volume"],
            0.4,
        )
        self.assertEqual(
            worker._legacy_worker.normalized_tts_config({"tts_config": {"output_volume": 2}})["output_volume"],
            1.0,
        )

    def test_normalized_tts_config_prefers_api_config_over_stale_top_level_tts(self):
        tts = worker._legacy_worker.normalized_tts_config(
            {
                "tts_config": {"enabled": False, "provider": "disabled"},
                "api_config": {
                    "provider": "gemini-vertex",
                    "tts_config": {
                        "enabled": True,
                        "provider": "gemini-vertex",
                        "base_url": "https://aiplatform.googleapis.com",
                        "model": "gemini-3.1-flash-tts-preview",
                        "voice": "Kore",
                        "language": "en-US",
                    },
                },
            }
        )

        self.assertTrue(tts["enabled"])
        self.assertEqual(tts["provider"], "gemini-vertex")
        self.assertEqual(tts["voice"], "Kore")

    def test_tts_transcode_applies_output_volume_filter(self):
        original_which = worker._legacy_worker.shutil.which
        original_run = worker._legacy_worker.subprocess.run
        calls = {}

        class Completed:
            returncode = 0
            stderr = ""

        def fake_run(args, **kwargs):
            calls["args"] = args
            calls["kwargs"] = kwargs
            return Completed()

        with tempfile.TemporaryDirectory() as temp_dir:
            wav_path = Path(temp_dir) / "tts.wav"
            mp3_path = Path(temp_dir) / "tts.mp3"
            wav_path.write_bytes(b"RIFF")

            try:
                worker._legacy_worker.shutil.which = lambda name: "ffmpeg" if name == "ffmpeg" else None
                worker._legacy_worker.subprocess.run = fake_run
                worker._legacy_worker.transcode_wav_file_to_mp3(wav_path, mp3_path, "Unit TTS", 0.65)
            finally:
                worker._legacy_worker.shutil.which = original_which
                worker._legacy_worker.subprocess.run = original_run

            self.assertFalse(wav_path.exists())
            self.assertIn("-af", calls["args"])
            self.assertIn("volume=0.650", calls["args"])
            self.assertEqual(worker._legacy_worker.tts_volume_filter_args(1.0), [])

    def test_synthesize_tts_reuses_persistent_cache_for_same_voice_and_text(self):
        original_call_tts_audio = worker._legacy_worker.call_tts_audio
        original_transcribe_tts_audio = worker._legacy_worker.transcribe_tts_audio
        calls = {"count": 0}

        def fake_call_tts_audio(tts, text, language):
            calls["count"] += 1
            return f"ID3:{text}:{language}".encode("utf-8") + (b"\x00" * 8192)

        def fake_transcribe_tts_audio(audio_path, *, project, expected_text, role):
            return {"ok": True, "provider": "fake-asr", "transcript": expected_text}

        project = {
            "language": "en",
            "api_config": {
                "tts_config": {
                    "enabled": True,
                    "provider": "grok",
                    "base_url": "https://api.x.ai/v1",
                    "api_key": "sk-test",
                    "model": "",
                    "voice": "eve",
                    "language": "en-US",
                    "sample_rate": 24000,
                    "bit_rate": 128000,
                    "output_volume": 1.0,
                }
            },
        }
        segment = {"id": "seg_cache", "text": "Read this once."}

        with tempfile.TemporaryDirectory() as temp_dir:
            original_cwd = os.getcwd()
            os.chdir(temp_dir)
            first_path = Path(temp_dir) / "first.mp3"
            second_path = Path(temp_dir) / "second.mp3"
            try:
                worker._legacy_worker.call_tts_audio = fake_call_tts_audio
                worker._legacy_worker.transcribe_tts_audio = fake_transcribe_tts_audio
                first = worker._legacy_worker.synthesize_tts(project, segment, first_path)
                second = worker._legacy_worker.synthesize_tts(project, segment, second_path)
                first_bytes = first_path.read_bytes()
                second_bytes = second_path.read_bytes()
            finally:
                worker._legacy_worker.call_tts_audio = original_call_tts_audio
                worker._legacy_worker.transcribe_tts_audio = original_transcribe_tts_audio
                os.chdir(original_cwd)

        self.assertEqual(calls["count"], 1)
        self.assertTrue(first)
        self.assertIsInstance(second, dict)
        self.assertTrue(second["cache_hit"])
        self.assertEqual(first_bytes, second_bytes)

    def test_transcribe_tts_audio_uses_whisper_cli_when_configured(self):
        original_which = worker._legacy_worker.shutil.which
        original_run = worker._legacy_worker.subprocess.run
        calls = {"args": []}

        class FakeCompleted:
            returncode = 0
            stdout = ""
            stderr = ""

        def fake_run(args, **kwargs):
            calls["args"] = list(args)
            output_dir = Path(args[args.index("--output_dir") + 1])
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "sample.txt").write_text("semantic firewall", encoding="utf-8")
            return FakeCompleted()

        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "sample.mp3"
            audio_path.write_bytes(b"ID3" + b"\x00" * 8192)
            try:
                worker._legacy_worker.shutil.which = lambda name: "C:/Tools/whisper.exe" if name == "whisper" else None
                worker._legacy_worker.subprocess.run = fake_run
                result = worker._legacy_worker.transcribe_tts_audio(
                    audio_path,
                    project={
                        "tts_semantic_verification": {
                            "asr_provider": "whisper-cli",
                            "whisper_model": "tiny.en",
                            "whisper_language": "en",
                        }
                    },
                    expected_text="semantic firewall",
                    role="phrase_tts",
                )
            finally:
                worker._legacy_worker.shutil.which = original_which
                worker._legacy_worker.subprocess.run = original_run

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["provider"], "whisper-cli:tiny.en")
        self.assertEqual(result["transcript"], "semantic firewall")
        self.assertIn("--output_format", calls["args"])
        self.assertIn("txt", calls["args"])

    def test_tts_semantic_matches_common_asr_homophones_for_sentence_tts(self):
        from acg.tts_semantic import normalize_tts_semantic_text, tts_semantic_matches

        matched, expected_norm, actual_norm = worker._legacy_worker.tts_semantic_matches(
            "As your morning alarm blares, you mutter to yourself, why did I set it so early?",
            "As you're mourning alarm blares, you mutter to yourself. Why did I set it so early?",
            role="sentence_tts",
        )

        self.assertTrue(matched, (expected_norm, actual_norm))
        self.assertEqual(
            worker._legacy_worker.tts_semantic_matches(
                "As your morning alarm blares, you mutter to yourself, why did I set it so early?",
                "As you're mourning alarm blares, you mutter to yourself. Why did I set it so early?",
                role="sentence_tts",
            ),
            tts_semantic_matches(
                "As your morning alarm blares, you mutter to yourself, why did I set it so early?",
                "As you're mourning alarm blares, you mutter to yourself. Why did I set it so early?",
                role="sentence_tts",
            ),
        )
        self.assertEqual(normalize_tts_semantic_text("[Music] The answer's two."), "the answer's two")

    def test_tts_semantic_matches_common_asr_homophones_for_long_phrase_tts(self):
        matched, expected_norm, actual_norm = worker._legacy_worker.tts_semantic_matches(
            "just in time to",
            "Just in time too.",
            role="phrase_tts",
        )

        self.assertTrue(matched, (expected_norm, actual_norm))

    def test_tts_semantic_manifest_review_helpers_live_in_dedicated_module(self):
        from acg.tts_semantic import (
            phrase_tts_max_duration_seconds,
            tts_manual_review_items,
            tts_semantic_failure_items,
            tts_semantic_verification_summary,
        )

        manifest = {
            "sentence_passed.mp3": {
                "role": "sentence_tts",
                "field": "TtsAudio",
                "tts_text": "This sentence passed.",
                "semantic_verification": "passed",
                "asr_transcript": "This sentence passed.",
            },
            "phrase_manual.mp3": {
                "role": "phrase_tts",
                "field": "PhraseTtsAudio",
                "card_id": "card-1",
                "learning_point_id": "lp-1",
                "segment_id": "seg-1",
                "source_time": "00:00:01.000 - 00:00:03.000",
                "tts_text": "model",
                "semantic_verification": "manual_review_required",
            },
            "phrase_mismatch.mp3": {
                "role": "phrase_tts",
                "field": "PhraseTtsAudio",
                "card_id": "card-2",
                "learning_point_id": "lp-2",
                "tts_text": "scratch",
                "semantic_verification": "mismatch",
                "asr_transcript": "stretch",
                "expected_text_normalized": "scratch",
                "actual_text_normalized": "stretch",
            },
            "phrase_na.mp3": {
                "role": "phrase_tts",
                "field": "PhraseTtsAudio",
                "tts_text": "fine",
                "semantic_verification": "not_applicable",
            },
        }

        manual_items = tts_manual_review_items(manifest)
        failure_items = tts_semantic_failure_items(manifest)
        summary = tts_semantic_verification_summary(manual_items, manifest)

        self.assertEqual(manual_items, worker._legacy_worker.tts_manual_review_items(manifest))
        self.assertEqual(failure_items, worker._legacy_worker.tts_semantic_failure_items(manifest))
        self.assertEqual(summary, worker._legacy_worker.tts_semantic_verification_summary(manual_items, manifest))
        self.assertEqual(len(manual_items), 1)
        self.assertEqual(manual_items[0]["file"], "phrase_manual.mp3")
        self.assertEqual(manual_items[0]["max_duration_seconds"], round(phrase_tts_max_duration_seconds("model"), 3))
        self.assertEqual(
            manual_items[0]["semantic_review_reasons"],
            ["asr_semantic_check_unavailable", "high_risk_short_expression", "short_expression"],
        )
        self.assertEqual(len(failure_items), 1)
        self.assertEqual(failure_items[0]["file"], "phrase_mismatch.mp3")
        self.assertEqual(summary["status"], "mismatch")
        self.assertEqual(summary["passed"], 1)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["manual_review_required"], 1)

    def test_tts_semantic_config_and_asr_command_helpers_match_worker_boundary(self):
        from acg import tts_semantic

        project = {
            "tts_semantic_verification": {
                "enabled": True,
                "require_pass_for_export": True,
            }
        }
        self.assertEqual(
            worker._legacy_worker.tts_semantic_config(project),
            tts_semantic.tts_semantic_config(project),
        )
        self.assertEqual(
            worker._legacy_worker.tts_semantic_verification_enabled(project),
            tts_semantic.tts_semantic_verification_enabled(project),
        )
        self.assertEqual(
            worker._legacy_worker.tts_semantic_requires_export_pass(project),
            tts_semantic.tts_semantic_requires_export_pass(project),
        )
        self.assertEqual(
            worker._legacy_worker.unsafe_asr_command_reason("cmd.exe /c echo {audio}"),
            tts_semantic.unsafe_asr_command_reason("cmd.exe /c echo {audio}"),
        )
        self.assertEqual(
            worker._legacy_worker.unsafe_asr_command_reason("safe-asr"),
            "",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "sample.mp3"
            module_argv, module_reason = tts_semantic.build_asr_command_argv(
                "safe-asr",
                ["--input", "{audio}", "--plain"],
                audio_path,
            )
            self.assertEqual(module_reason, "")
            self.assertEqual(
                worker._legacy_worker.build_asr_command_argv(
                    "safe-asr",
                    ["--input", "{audio}", "--plain"],
                    audio_path,
                ),
                module_argv,
            )

    def test_transcribe_tts_audio_rejects_shell_template_command(self):
        original_run = worker._legacy_worker.subprocess.run

        def fake_run(*args, **kwargs):
            raise AssertionError("unsafe ASR command must not be executed")

        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "sample.mp3"
            audio_path.write_bytes(b"ID3" + b"\x00" * 8192)
            try:
                worker._legacy_worker.subprocess.run = fake_run
                with self.assertRaises(SystemExit):
                    worker._legacy_worker.transcribe_tts_audio(
                        audio_path,
                        project={
                            "tts_semantic_verification": {
                                "asr_command": "cmd.exe /c echo {audio}",
                                "asr_timeout_seconds": 1,
                            }
                        },
                        expected_text="semantic firewall",
                        role="phrase_tts",
                    )
            finally:
                worker._legacy_worker.subprocess.run = original_run

    def test_transcribe_tts_audio_uses_safe_asr_command_args(self):
        original_run = worker._legacy_worker.subprocess.run
        calls = {}

        class FakeCompleted:
            returncode = 0
            stdout = "semantic firewall"
            stderr = ""

        def fake_run(args, **kwargs):
            calls["args"] = list(args)
            calls["kwargs"] = dict(kwargs)
            return FakeCompleted()

        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "sample.mp3"
            audio_path.write_bytes(b"ID3" + b"\x00" * 8192)
            try:
                worker._legacy_worker.subprocess.run = fake_run
                result = worker._legacy_worker.transcribe_tts_audio(
                    audio_path,
                    project={
                        "tts_semantic_verification": {
                            "asr_command": "safe-asr",
                            "asr_command_args": ["--input", "{audio}", "--plain"],
                        }
                    },
                    expected_text="semantic firewall",
                    role="phrase_tts",
                )
            finally:
                worker._legacy_worker.subprocess.run = original_run

        self.assertTrue(result["ok"], result)
        self.assertEqual(calls["args"], ["safe-asr", "--input", str(audio_path), "--plain"])
        self.assertNotIn("shell", calls["kwargs"])

    def test_url_and_anki_security_guards_block_untrusted_hosts(self):
        legacy = worker._legacy_worker
        with self.assertRaises(SystemExit):
            legacy.validate_source_url_for_import({"source_url": "http://127.0.0.1:8080/video.mp4"})
        self.assertEqual(
            legacy.validate_source_url_for_import(
                {
                    "source_url": "http://127.0.0.1:8080/video.mp4",
                    "allow_private_network_url": True,
                }
            ),
            "http://127.0.0.1:8080/video.mp4",
        )
        self.assertEqual(
            legacy.validate_source_url_for_import({"source_url": "https://www.youtube.com/watch?v=test"}),
            "https://www.youtube.com/watch?v=test",
        )
        legacy.validate_anki_connect_url("http://127.0.0.1:8765")
        legacy.validate_anki_connect_url("http://localhost:8765")
        with self.assertRaises(SystemExit):
            legacy.validate_anki_connect_url("http://192.168.1.10:8765")

    def test_yt_dlp_remote_components_are_explicit_opt_in(self):
        legacy = worker._legacy_worker
        original_which = legacy.shutil.which
        try:
            legacy.shutil.which = lambda name: f"C:/Tools/{name}.exe" if name == "deno" else None
            self.assertEqual(legacy.yt_dlp_js_runtime_args(False), [])
            self.assertEqual(
                legacy.yt_dlp_js_runtime_args(True),
                ["--js-runtimes", "deno", "--remote-components", "ejs:github"],
            )
        finally:
            legacy.shutil.which = original_which

    def test_synthesize_tts_rejects_overlong_phrase_audio_and_does_not_cache(self):
        original_call_tts_audio = worker._legacy_worker.call_tts_audio
        original_audio_duration_seconds = worker._legacy_worker.audio_duration_seconds

        def fake_call_tts_audio(tts, text, language):
            return b"ID3" + b"\x00" * 8192

        project = {
            "language": "en",
            "api_config": {
                "tts_config": {
                    "enabled": True,
                    "provider": "grok",
                    "base_url": "https://api.x.ai/v1",
                    "api_key": "sk-test",
                    "model": "",
                    "voice": "eve",
                    "language": "en-US",
                    "sample_rate": 24000,
                    "bit_rate": 128000,
                    "output_volume": 1.0,
                }
            },
        }
        segment = {"id": "seg_prompt", "text": "prompt"}

        with tempfile.TemporaryDirectory() as temp_dir:
            original_cwd = os.getcwd()
            os.chdir(temp_dir)
            output_path = Path(temp_dir) / "prompt.mp3"
            tts = worker._legacy_worker.normalized_tts_config(project)
            cache_path, _cache_key = worker._legacy_worker.tts_cache_path(tts, "prompt", "en")
            try:
                worker._legacy_worker.call_tts_audio = fake_call_tts_audio
                worker._legacy_worker.audio_duration_seconds = lambda path: 87.64
                with self.assertRaisesRegex(RuntimeError, "表达 TTS 时长异常"):
                    worker._legacy_worker.synthesize_tts(
                        project,
                        segment,
                        output_path,
                        text_override="prompt",
                        tts_kind="phrase",
                    )
            finally:
                worker._legacy_worker.call_tts_audio = original_call_tts_audio
                worker._legacy_worker.audio_duration_seconds = original_audio_duration_seconds
                os.chdir(original_cwd)

            self.assertFalse(output_path.exists())
            self.assertFalse(cache_path.exists())

    def test_synthesize_tts_discards_overlong_phrase_cache_before_regenerating(self):
        original_call_tts_audio = worker._legacy_worker.call_tts_audio
        original_audio_duration_seconds = worker._legacy_worker.audio_duration_seconds
        original_transcribe_tts_audio = worker._legacy_worker.transcribe_tts_audio
        calls = {"count": 0}
        durations = iter([88.0, 1.4])

        def fake_call_tts_audio(tts, text, language):
            calls["count"] += 1
            return b"ID3regenerated" + b"\x00" * 8192

        def fake_transcribe_tts_audio(audio_path, *, project, expected_text, role):
            return {"ok": True, "provider": "fake-asr", "transcript": expected_text}

        project = {
            "language": "en",
            "api_config": {
                "tts_config": {
                    "enabled": True,
                    "provider": "grok",
                    "base_url": "https://api.x.ai/v1",
                    "api_key": "sk-test",
                    "model": "",
                    "voice": "eve",
                    "language": "en-US",
                    "sample_rate": 24000,
                    "bit_rate": 128000,
                    "output_volume": 1.0,
                }
            },
        }
        segment = {"id": "seg_prompt", "text": "prompt"}

        with tempfile.TemporaryDirectory() as temp_dir:
            original_cwd = os.getcwd()
            os.chdir(temp_dir)
            output_path = Path(temp_dir) / "prompt.mp3"
            tts = worker._legacy_worker.normalized_tts_config(project)
            cache_path, _cache_key = worker._legacy_worker.tts_cache_path(tts, "prompt", "en")
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(b"ID3cached" + b"\x00" * 8192)
            try:
                worker._legacy_worker.call_tts_audio = fake_call_tts_audio
                worker._legacy_worker.audio_duration_seconds = lambda path: next(durations)
                worker._legacy_worker.transcribe_tts_audio = fake_transcribe_tts_audio
                result = worker._legacy_worker.synthesize_tts(
                    project,
                    segment,
                    output_path,
                    text_override="prompt",
                    tts_kind="phrase",
                )
                output_bytes = output_path.read_bytes()
                cache_bytes = cache_path.read_bytes()
            finally:
                worker._legacy_worker.call_tts_audio = original_call_tts_audio
                worker._legacy_worker.audio_duration_seconds = original_audio_duration_seconds
                worker._legacy_worker.transcribe_tts_audio = original_transcribe_tts_audio
                os.chdir(original_cwd)

        self.assertEqual(calls["count"], 1)
        self.assertIsInstance(result, dict)
        self.assertFalse(result["cache_hit"])
        self.assertTrue(output_bytes.startswith(b"ID3regenerated"))
        self.assertTrue(cache_bytes.startswith(b"ID3regenerated"))

    def test_media_cache_rejects_tiny_invalid_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_path = root / "bad.mp4"
            output_path = root / "out" / "clip.mp4"
            cache_path.write_bytes(b"media")

            copied = worker._legacy_worker.copy_cached_file(cache_path, output_path)

            self.assertFalse(copied)
            self.assertFalse(output_path.exists())
            self.assertFalse(cache_path.exists())

    def test_media_cache_does_not_store_invalid_outputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_path = root / "clip.jpg"
            cache_path = root / "cache" / "clip.jpg"
            output_path.write_bytes(b"media")

            worker._legacy_worker.store_cached_file(output_path, cache_path)

            self.assertFalse(cache_path.exists())

    def test_media_cache_copies_valid_mp4_signature(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_path = root / "valid.mp4"
            output_path = root / "out" / "clip.mp4"
            cache_path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 8192)

            copied = worker._legacy_worker.copy_cached_file(cache_path, output_path)

            self.assertTrue(copied)
            self.assertEqual(output_path.read_bytes(), cache_path.read_bytes())

    def test_cache_identity_helpers_match_worker_boundary(self):
        from acg.cache_identity import (
            cached_media_file_valid,
            copy_cached_file,
            file_fingerprint,
            stable_cache_key,
            store_cached_file,
        )

        payload = {"b": 2, "a": ["x", "y"], "nested": {"语言": "English"}}
        self.assertEqual(worker._legacy_worker.stable_cache_key(payload, 24), stable_cache_key(payload, 24))

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_path = root / "source.txt"
            source_path.write_text("stable source fingerprint", encoding="utf-8")
            self.assertEqual(worker._legacy_worker.file_fingerprint(source_path), file_fingerprint(source_path))

            valid_mp3 = root / "valid.mp3"
            cache_path = root / "cache" / "valid.mp3"
            output_path = root / "out" / "valid.mp3"
            valid_mp3.write_bytes(b"ID3" + b"\x00" * 2048)

            self.assertEqual(worker._legacy_worker.cached_media_file_valid(valid_mp3), cached_media_file_valid(valid_mp3))
            store_cached_file(valid_mp3, cache_path)
            copied_by_worker = worker._legacy_worker.copy_cached_file(cache_path, output_path)
            self.assertTrue(copied_by_worker)
            self.assertTrue(output_path.exists())
            output_path.unlink()
            copied_by_module = copy_cached_file(cache_path, output_path)
            self.assertTrue(copied_by_module)

    def test_tts_cache_key_includes_vertex_scope(self):
        base = {
            "enabled": True,
            "provider": "gemini-vertex-tts",
            "model": "gemini-3.1-flash-tts-preview",
            "voice": "Kore",
            "language": "en-US",
            "sample_rate": 24000,
            "bit_rate": 128000,
            "output_volume": 0.65,
            "project": "project-a",
            "location": "global",
        }

        _path_a, key_a = worker._legacy_worker.tts_cache_path(base, "Read this once.", "en")
        _path_b, key_b = worker._legacy_worker.tts_cache_path(
            {**base, "project": "project-b"},
            "Read this once.",
            "en",
        )
        _path_c, key_c = worker._legacy_worker.tts_cache_path(
            {**base, "location": "us-central1"},
            "Read this once.",
            "en",
        )

        self.assertNotEqual(key_a, key_b)
        self.assertNotEqual(key_a, key_c)

    def test_cache_identity_helpers_match_worker_boundary(self):
        from acg import cache_identity

        tts = {
            "enabled": True,
            "provider": "gemini-vertex-tts",
            "base_url": "https://aiplatform.googleapis.com/",
            "model": "gemini-3.1-flash-tts-preview",
            "voice": "Kore",
            "sample_rate": 24000,
            "bit_rate": 128000,
            "output_volume": 0.65,
            "project": "project-a",
            "location": "",
        }

        cache_root = worker._legacy_worker.persistent_cache_root()
        self.assertEqual(cache_root, cache_identity.persistent_cache_root(Path.cwd()))
        self.assertEqual(
            worker._legacy_worker.tts_provider_scope(tts),
            cache_identity.tts_provider_scope(
                tts,
                provider=worker._legacy_worker.provider_name(tts),
                default_region=worker._legacy_worker.gemini_vertex_location(tts),
            ),
        )

        worker_tts_path, worker_tts_key = worker._legacy_worker.tts_cache_path(tts, "Read this once.", "en")
        module_tts_path, module_tts_key = cache_identity.tts_cache_path(
            cache_root,
            tts,
            "Read this once.",
            "en",
            provider_name_func=worker._legacy_worker.provider_name,
            resolve_language_func=worker._legacy_worker.resolve_tts_language_code,
            normalize_volume_func=worker._legacy_worker.normalized_tts_output_volume,
            clean_text_func=worker._legacy_worker.clean_tts_input_text,
            text_hash_func=worker._legacy_worker.media_text_hash,
            provider_scope_func=worker._legacy_worker.tts_provider_scope,
        )
        self.assertEqual(worker_tts_path, module_tts_path)
        self.assertEqual(worker_tts_key, module_tts_key)

        worker_media_path, worker_media_key = worker._legacy_worker.media_clip_cache_path(
            "video-fingerprint",
            "00:00:01.000",
            "3.500",
            "video",
            ".mp4",
            "faststart",
        )
        module_media_path, module_media_key = cache_identity.media_clip_cache_path(
            cache_root,
            "video-fingerprint",
            "00:00:01.000",
            "3.500",
            "video",
            ".mp4",
            "faststart",
            ffmpeg_signature=worker._legacy_worker.ffmpeg_cache_signature(),
        )
        self.assertEqual(worker_media_path, module_media_path)
        self.assertEqual(worker_media_key, module_media_key)

    def test_apkg_offline_field_report_detects_tts_hash_mismatch_and_bad_pronunciation_meta(self):
        report = verify_apkg.offline_field_report(
            [
                {
                    "CardId": "card-1",
                    "English": "You won't even taste the difference.",
                    "Answer": "taste the difference",
                    "Chinese": "",
                    "Definition": "待精修：先把 taste the difference 当作本句目标表达。",
                    "TeacherNote": "本地 fallback 只保证结构完整。",
                    "TtsAudio": '<audio><source src="deck_tts_deadbeef0000.mp3"></audio>',
                    "PhraseTtsAudio": '<audio><source src="deck_phrase_deadbeef0000.mp3"></audio>',
                    "PronunciationMeta": "{not-json}",
                }
            ],
            {"deck_tts_deadbeef0000.mp3", "deck_phrase_deadbeef0000.mp3"},
        )

        self.assertEqual(report["missing_referenced_media"], [])
        self.assertEqual(len(report["pronunciation_meta_parse_errors"]), 1)
        self.assertEqual(len(report["tts_text_hash_mismatches"]), 1)
        self.assertEqual(len(report["phrase_tts_text_hash_mismatches"]), 1)
        self.assertEqual(len(report["empty_required_text_fields"]), 1)
        self.assertEqual(len(report["blocked_study_text_values"]), 2)
        self.assertEqual(report["corrupted_study_text_values"], [])

    def test_apkg_offline_field_report_detects_question_mark_corrupted_study_text(self):
        report = verify_apkg.offline_field_report(
            [
                {
                    "CardId": "card-corrupt",
                    "English": "This is a demanding job.",
                    "Answer": "demanding job",
                    "Chinese": "???????",
                    "Definition": "A job requiring much effort.",
                    "TeacherNote": "demanding ??????????????????",
                    "TtsAudio": '<audio><source src="deck_tts_4a639f4d4a41.mp3"></audio>',
                    "PhraseTtsAudio": '<audio><source src="deck_phrase_0423349bb0c2.mp3"></audio>',
                    "PronunciationMeta": '{"validation_issues":[{"message":"??????????"}]}',
                }
            ],
            {"deck_tts_4a639f4d4a41.mp3", "deck_phrase_0423349bb0c2.mp3"},
        )

        self.assertEqual(
            {item["field"] for item in report["corrupted_study_text_values"]},
            {"Chinese", "TeacherNote"},
        )

    def test_apkg_media_header_validator_rejects_invalid_video_bytes(self):
        self.assertFalse(verify_apkg.media_header_valid("clip.mp4", 5, b"media"))
        self.assertTrue(
            verify_apkg.media_header_valid(
                "clip.mp4",
                8204,
                b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 8192,
            )
        )

    def test_apkg_offline_field_report_flags_video_without_webm_fallback(self):
        report = verify_apkg.offline_field_report(
            [
                {
                    "CardId": "card-video",
                    "English": "You won't even taste the difference.",
                    "Answer": "taste the difference",
                    "Chinese": "你根本尝不出区别。",
                    "Definition": "notice a difference by taste",
                    "TeacherNote": "注意 taste 的语境搭配。",
                    "Video": '<video><source src="clip.mp4" type="video/mp4"></video>',
                    "Audio": "",
                    "TtsAudio": "",
                    "PhraseTtsAudio": "",
                    "PronunciationMeta": "{}",
                }
            ],
            {"clip.mp4"},
        )

        self.assertEqual(len(report["video_reference_compatibility_issues"]), 1)
        self.assertEqual(report["video_reference_compatibility_issues"][0]["code"], "NO_WEBM_FALLBACK")

    def test_video_compatibility_issues_flag_high_profile_1080p_mp4(self):
        issues = verify_apkg.video_compatibility_issues(
            "clip.mp4",
            {
                "ok": True,
                "codec": "h264",
                "profile": "High",
                "width": 1920,
                "height": 1080,
            },
        )

        self.assertEqual(
            {issue["code"] for issue in issues},
            {"VIDEO_RESOLUTION_TOO_HIGH", "MP4_PROFILE_NOT_ANKI_FRIENDLY"},
        )

    def test_verify_apkg_prepare_output_dir_refuses_non_workspace_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir) / "important"
            out_dir.mkdir()
            keep_file = out_dir / "keep.txt"
            keep_file.write_text("do not delete", encoding="utf-8")

            with self.assertRaises(SystemExit):
                verify_apkg.prepare_verify_output_dir(out_dir)

            self.assertTrue(keep_file.exists())
            self.assertEqual(keep_file.read_text(encoding="utf-8"), "do not delete")

    def test_verify_apkg_prepare_output_dir_allows_marked_workspace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir) / "workspace"
            out_dir.mkdir()
            (out_dir / verify_apkg.VERIFY_WORKSPACE_MARKER).write_text("safe", encoding="utf-8")
            (out_dir / "collection.anki2").write_text("old", encoding="utf-8")

            prepared = verify_apkg.prepare_verify_output_dir(out_dir)

            self.assertEqual(prepared, out_dir.resolve())
            self.assertTrue((prepared / verify_apkg.VERIFY_WORKSPACE_MARKER).exists())
            self.assertFalse((prepared / "collection.anki2").exists())

    def test_verify_apkg_archive_limits_reject_too_many_media_entries(self):
        class FakeInfo:
            def __init__(self, filename, file_size=1):
                self.filename = filename
                self.file_size = file_size

        class FakeArchive:
            def infolist(self):
                return [FakeInfo("collection.anki2"), FakeInfo("media")] + [
                    FakeInfo(str(index)) for index in range(verify_apkg.MAX_ARCHIVE_MEDIA_ENTRIES + 1)
                ]

        with self.assertRaisesRegex(RuntimeError, "UNSAFE_APKG_ARCHIVE"):
            verify_apkg.validate_apkg_archive_limits(FakeArchive())

    def test_verify_apkg_archive_limits_reject_oversized_entry(self):
        class FakeInfo:
            filename = "0"
            file_size = verify_apkg.MAX_ARCHIVE_ENTRY_BYTES + 1

        class FakeArchive:
            def infolist(self):
                return [FakeInfo()]

        with self.assertRaisesRegex(RuntimeError, "UNSAFE_APKG_ARCHIVE"):
            verify_apkg.validate_apkg_archive_limits(FakeArchive())

    def test_apkg_offline_field_report_accepts_pronunciation_meta_with_arrays_and_ipa(self):
        meta = {
            "language_code": "en",
            "accent_profile": "en-US-general",
            "notation_system": "ipa_en_connected",
            "generation_basis": "dictionary_only",
            "field_confidence": {"phonetic_ipa": "medium"},
            "validation_issues": [
                {
                    "field": "source_spoken_ipa",
                    "severity": "block",
                    "code": "DICTIONARY_ONLY_NO_SPOKEN",
                    "message": "只保留标准读法。",
                }
            ],
            "field_changes": [
                {
                    "field": "source_spoken_ipa",
                    "action": "hidden",
                    "code": "DICTIONARY_ONLY_NO_SPOKEN",
                    "message": "原句听感已隐藏。",
                    "original_value": "/ju woʊnt ˈivən teɪst ðə ˈdɪfərəns/",
                }
            ],
        }
        report = verify_apkg.offline_field_report(
            [
                {
                    "CardId": "card-1",
                    "English": "You won't even taste the difference.",
                    "Answer": "taste the difference",
                    "Chinese": "你根本尝不出区别。",
                    "Definition": "taste the difference 表示尝出两者之间的差别。",
                    "TeacherNote": "常用于食品、饮料或质量对比场景。",
                    "TtsAudio": "",
                    "PhraseTtsAudio": "",
                    "PronunciationMeta": json.dumps(meta, ensure_ascii=False),
                }
            ],
            set(),
        )

        self.assertEqual(report["pronunciation_meta_parse_errors"], [])
        self.assertEqual(report["empty_required_text_fields"], [])
        self.assertEqual(report["blocked_study_text_values"], [])

    def test_material_context_accepts_direct_gemini_vertex_context_payload(self):
        original_generate = worker._legacy_worker.gemini_vertex_generate_content

        def fake_generate(*args, **kwargs):
            return '{"summary":"AI scene read","scene":"car wash counter","key_points":["register"]}'

        try:
            worker._legacy_worker.gemini_vertex_generate_content = fake_generate
            context = worker.call_material_context(
                {
                    "study_depth": "deep",
                    "title": "clip",
                    "language": "English",
                    "api_config": {
                        "provider": "gemini-vertex",
                        "base_url": "https://aiplatform.googleapis.com",
                        "model": "gemini-3.1-pro-preview",
                    },
                },
                [
                    {
                        "id": "seg_001",
                        "start": 1.0,
                        "end": 3.0,
                        "text": "I'm gonna run the register.",
                    }
                ],
            )
        finally:
            worker._legacy_worker.gemini_vertex_generate_content = original_generate

        self.assertEqual(context["source"], "ai")
        self.assertEqual(context["summary"], "AI scene read")
        self.assertEqual(context["scene"], "car wash counter")

    def test_extract_json_object_ignores_reasoning_blocks(self):
        payload = worker.extract_json_object(
            '<think>{"noise": true}</think>\n模型最终答案：\n```json\n{"segments":[]}\n```'
        )

        self.assertEqual(payload, {"segments": []})

    def test_ytdlp_node_runtime_enables_remote_ejs_components_only_after_confirmation(self):
        original_which = worker.shutil.which
        try:
            worker.shutil.which = lambda name: "C:/node/node.exe" if name == "node" else None

            default_args = worker.yt_dlp_js_runtime_args()
            confirmed_args = worker.yt_dlp_js_runtime_args(allow_remote_components=True)
        finally:
            worker.shutil.which = original_which

        self.assertEqual(default_args, [])
        self.assertEqual(confirmed_args, ["--js-runtimes", "node", "--remote-components", "ejs:github"])

    def test_ytdlp_429_message_points_to_subtitle_rate_limit(self):
        message = worker.format_yt_dlp_failure(
            "ERROR: Unable to download video subtitles for 'en': HTTP Error 429: Too Many Requests"
        )

        self.assertIn("YouTube 返回 HTTP 429", message)
        self.assertIn("本地 SRT", message)

    def test_ytdlp_429_meta_is_structured_and_actionable(self):
        meta = worker.yt_dlp_failure_meta(
            "ERROR: Unable to download video subtitles for 'en': HTTP Error 429: Too Many Requests"
        )

        self.assertEqual(meta["error_code"], "YOUTUBE_RATE_LIMIT")
        self.assertEqual(meta["stage"], "download_subtitles")
        self.assertTrue(meta["retryable"])
        self.assertIn("local_srt", meta["fallbacks"])

    def test_ytdlp_support_helpers_match_worker_boundary(self):
        completed = subprocess.CompletedProcess(["yt-dlp"], 1, stdout="stdout detail", stderr="stderr detail")
        self.assertEqual(worker.yt_dlp_failure_detail(completed), ytdlp_support.yt_dlp_failure_detail(completed))

        details = [
            "ERROR: Unable to download video subtitles for 'en': HTTP Error 429: Too Many Requests",
            "ERROR: unable to download video: HTTP Error 429: Too Many Requests",
            "ERROR: n challenge solving failed: remote component challenge solver required",
            "ERROR: Unable to download video subtitles for 'en': requested subtitles are unavailable",
            "ERROR: unable to download video data",
        ]
        for detail in details:
            with self.subTest(detail=detail):
                self.assertEqual(
                    worker.yt_dlp_needs_remote_components(detail),
                    ytdlp_support.yt_dlp_needs_remote_components(detail),
                )
                self.assertEqual(
                    worker.is_subtitle_rate_limited(detail),
                    ytdlp_support.is_subtitle_rate_limited(detail),
                )
                self.assertEqual(worker.format_yt_dlp_failure(detail), ytdlp_support.format_yt_dlp_failure(detail))
                self.assertEqual(worker.yt_dlp_failure_meta(detail), ytdlp_support.yt_dlp_failure_meta(detail))

    def test_ytdlp_argument_helpers_match_worker_boundary(self):
        legacy = worker._legacy_worker
        original_which = legacy.shutil.which
        original_find_spec = legacy.importlib.util.find_spec
        try:
            legacy.shutil.which = lambda name: f"C:/Tools/{name}.exe" if name == "bun" else None
            self.assertEqual(legacy.yt_dlp_js_runtime_args(False), [])
            self.assertEqual(
                legacy.yt_dlp_js_runtime_args(True),
                ytdlp_support.yt_dlp_js_runtime_args(
                    True,
                    which_func=lambda name: f"C:/Tools/{name}.exe" if name == "bun" else None,
                ),
            )

            legacy.importlib.util.find_spec = lambda name: object() if name == "curl_cffi" else None
            self.assertEqual(
                legacy.yt_dlp_network_args(),
                ytdlp_support.yt_dlp_network_args(curl_cffi_available=True),
            )
            legacy.importlib.util.find_spec = lambda _name: None
            self.assertEqual(
                legacy.yt_dlp_network_args(),
                ytdlp_support.yt_dlp_network_args(curl_cffi_available=False),
            )
        finally:
            legacy.shutil.which = original_which
            legacy.importlib.util.find_spec = original_find_spec

    def test_clean_input_path_removes_outer_quotes_and_spaces(self):
        self.assertEqual(worker.clean_input_path(' "F:\\Video\\clip.mkv" '), "F:\\Video\\clip.mkv")
        self.assertEqual(worker.clean_input_path("'F:\\Video\\clip.srt'"), "F:\\Video\\clip.srt")

    def test_discover_local_subtitle_matches_same_video_stem(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "JMDS S01E01.mkv"
            english_subtitle = root / "JMDS S01E01-EN.srt"
            other_subtitle = root / "JMDS S01E02-EN.srt"
            video.write_bytes(b"video")
            english_subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello.\n", encoding="utf-8")
            other_subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\nWrong.\n", encoding="utf-8")

            selected = worker.discover_local_subtitle(f' "{video}" ', "English")

        self.assertEqual(selected, english_subtitle)

    def test_subtitle_discovery_helpers_match_worker_boundary(self):
        from acg.subtitles import discovery

        for language in ("English", "中文", "français", "es-MX", "日本語", "русский"):
            self.assertEqual(worker.subtitle_language_args(language), discovery.subtitle_language_args(language))
            self.assertEqual(worker.subtitle_language_markers(language), discovery.subtitle_language_markers(language))
            self.assertEqual(worker.subtitle_language_aliases(language), discovery.subtitle_language_aliases(language))

        self.assertEqual(worker.compact_match_text("JMDS S01E01 - EN"), discovery.compact_match_text("JMDS S01E01 - EN"))
        self.assertEqual(worker.TEXT_SUBTITLE_CODECS, discovery.TEXT_SUBTITLE_CODECS)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "JMDS S01E01.mkv"
            small_video = root / "small.mp4"
            large_video = root / "large.mp4"
            subtitle = root / "JMDS S01E01.en.srt"
            unrelated = root / "JMDS S01E02.en.srt"
            ignored = root / "largest.info.json"
            video.write_bytes(b"video")
            small_video.write_bytes(b"v")
            large_video.write_bytes(b"video-video")
            subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello.\n", encoding="utf-8")
            unrelated.write_text("1\n00:00:00,000 --> 00:00:01,000\nWrong.\n", encoding="utf-8")
            ignored.write_text("{}", encoding="utf-8")

            self.assertEqual(
                worker.first_file_by_suffix(root, (".mp4",)),
                discovery.first_file_by_suffix(root, (".mp4",)),
            )
            self.assertEqual(
                worker.pick_subtitle_file(root, "English"),
                discovery.pick_subtitle_file(root, "English"),
            )
            self.assertEqual(
                worker.discover_local_subtitle(f' "{video}" ', "English"),
                discovery.discover_local_subtitle(f' "{video}" ', "English"),
            )

    def test_select_embedded_subtitle_stream_prefers_requested_language(self):
        probe = {
            "streams": [
                {
                    "index": 2,
                    "codec_type": "subtitle",
                    "codec_name": "subrip",
                    "tags": {"language": "chi"},
                    "disposition": {"default": 1},
                },
                {
                    "index": 3,
                    "codec_type": "subtitle",
                    "codec_name": "subrip",
                    "tags": {"language": "eng"},
                    "disposition": {"default": 0},
                },
            ]
        }

        selected = worker.select_embedded_subtitle_stream(probe, "English")

        self.assertEqual(selected["index"], 3)

        from acg.subtitles import discovery

        self.assertEqual(selected, discovery.select_embedded_subtitle_stream(probe, "English"))

    def test_local_generate_auto_discovers_subtitle_when_path_is_empty(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "clip.mkv"
            subtitle = root / "clip.en.srt"
            video.write_bytes(b"video")
            subtitle.write_text(
                "1\n"
                "00:00:00,000 --> 00:00:02,000\n"
                "Dad, come check this out.\n\n"
                "2\n"
                "00:00:03,000 --> 00:00:05,000\n"
                "It looks like a normal morning.\n",
                encoding="utf-8",
            )

            project = worker.handle_generate(
                {
                    "source_mode": "local",
                    "title": "auto subtitle",
                    "video_path": str(video),
                    "subtitle_path": "",
                    "language": "English",
                    "level": "B1",
                    "collection_levels": ["A2", "B1", "B2"],
                    "card_types": ["phrase"],
                    "content_toggles": {"daily": True},
                    "api_config": {"provider": "local"},
                }
            )

        self.assertEqual(project["subtitle_path"], str(subtitle))
        self.assertEqual(project["source_info"]["subtitle_source"], "auto_matched")
        self.assertIn("自动匹配同目录字幕", project["warning"])
        self.assertGreaterEqual(project["quality_funnel"]["subtitle_cues"], 2)

    def test_local_generate_ignores_stale_source_url(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "local-episode.mkv"
            subtitle = root / "local-episode.srt"
            video.write_bytes(b"video")
            subtitle.write_text(
                "1\n"
                "00:00:00,000 --> 00:00:02,000\n"
                "Local only line, do not use the stale URL.\n\n"
                "2\n"
                "00:00:03,000 --> 00:00:05,000\n"
                "This local subtitle should drive the cards.\n",
                encoding="utf-8",
            )
            original_download_url_source = worker._legacy_worker.download_url_source

            def fail_if_url_source_is_used(payload):
                raise AssertionError("Local generation must not use stale source_url")

            try:
                worker._legacy_worker.download_url_source = fail_if_url_source_is_used
                project = worker.handle_generate(
                    {
                        "source_mode": "local",
                        "source_url": "https://www.youtube.com/watch?v=stale",
                        "title": "local stale url guard",
                        "video_path": str(video),
                        "subtitle_path": str(subtitle),
                        "language": "English",
                        "level": "B1",
                        "collection_levels": ["A2", "B1", "B2"],
                        "card_types": ["phrase"],
                        "content_toggles": {"daily": True},
                        "api_config": {"provider": "local"},
                    }
                )
            finally:
                worker._legacy_worker.download_url_source = original_download_url_source

        self.assertEqual(project["source_mode"], "local")
        self.assertEqual(project["source_url"], "")
        self.assertEqual(project["video_path"], str(video))
        self.assertEqual(project["subtitle_path"], str(subtitle))
        self.assertRegex(project["source_info"]["video_fingerprint"], r"^[0-9a-f]{24}$")
        self.assertRegex(project["source_info"]["subtitle_fingerprint"], r"^[0-9a-f]{24}$")
        self.assertGreaterEqual(project["quality_funnel"]["subtitle_cues"], 2)
        self.assertGreaterEqual(project["quality_funnel"]["filtered_learning_point_count"], 1)

    def test_catch_all_groups_multiple_learning_points_from_one_sentence(self):
        cues = [worker.Cue(1, 0.0, 4.0, "Ever want me to run the register, I could critique it for you.")]
        segments = worker.build_segments(
            cues,
            {
                "level": "C2",
                "selection_strategy": "catch_all",
                "collection_levels": ["A1", "A2", "B1", "B2", "C1", "C2"],
                "language_focus": ["phrases", "vocabulary", "grammar", "listening"],
                "card_types": ["phrase", "listening"],
                "content_toggles": {"daily": True},
                "max_segments": 1,
                "_candidate_limit": 12,
            },
        )
        grouped = worker.group_segments_by_learning_points(segments)

        self.assertEqual(len(grouped), 1)
        point_labels = {point["answer_core"].lower() for point in grouped[0]["learning_points"]}
        self.assertIn("run the register", point_labels)
        self.assertIn("register", point_labels)
        self.assertIn("ever want me to", point_labels)
        self.assertGreaterEqual(len(grouped[0]["learning_points"]), 3)

    def test_merge_ai_cards_preserves_multiple_same_type_learning_points(self):
        cues = [worker.Cue(1, 0.0, 2.5, "I'm gonna run the register.")]
        grouped = worker.group_segments_by_learning_points(
            worker.build_segments(
                cues,
                {
                    "level": "C2",
                    "selection_strategy": "catch_all",
                    "collection_levels": ["A1", "A2", "B1", "B2", "C1", "C2"],
                    "language_focus": ["phrases", "vocabulary", "grammar", "listening"],
                    "card_types": ["phrase"],
                    "content_toggles": {"daily": True},
                    "max_segments": 1,
                    "_candidate_limit": 12,
                },
            )
        )
        segment = grouped[0]
        expression_point = next(point for point in segment["learning_points"] if point["answer_core"] == "run the register")
        vocab_point = next(point for point in segment["learning_points"] if point["answer_core"] == "register")
        ai_payload = {
            "segments": [
                {
                    "id": segment["id"],
                    "cards": [
                        {
                            "type": "phrase",
                            "learning_point_id": expression_point["id"],
                            "candidate_kind": "expression",
                            "phrase_type": "collocation",
                            "content_kind": "phrase",
                            "exact_span": "run the register",
                            "normalized_answer": "run the register",
                            "answer_core": "run the register",
                            "phrase": "run the register",
                            "chinese": "负责收银",
                            "definition": "在店里负责操作收银机。",
                            "collocations": "run the register today",
                            "context": "服务业工作场景。",
                            "example": "Can you run the register for a minute?",
                            "chinese_feel": "我来收银。",
                            "why": "地道职场口语。",
                            "difficulty": "B2 独立表达",
                            "teacher_note": "不要直译成运行登记表。",
                            "cloze": "I'm gonna ____.",
                            "learning_target": "训练服务业场景表达。",
                            "why_it_matters": "避免用 work as a cashier 的书面说法。",
                            "how_to_use_it": "用在接手收银任务时。",
                            "natural_chinese": "我来负责收银。",
                            "replacement_examples": "I'll run the register for a while.",
                            "retrieval_prompt": "这句里表示“负责收银”的自然表达是什么？",
                            "usage_boundary": "适合商店、餐厅收银场景。",
                            "confusable_note": "register 这里是收银机，不是注册。",
                            "learning_action": "expression_recall",
                            "conceptual_action": "把 run 当成临时负责一台设备或岗位的动作。",
                            "chinese_learner_trap": "不要按中文把 run 理解成跑步或运行程序。",
                        },
                        {
                            "type": "phrase",
                            "learning_point_id": vocab_point["id"],
                            "candidate_kind": "contextual_vocab",
                            "phrase_type": "vocabulary_usage",
                            "content_kind": "vocabulary",
                            "exact_span": "register",
                            "normalized_answer": "register",
                            "answer_core": "register",
                            "phrase": "register",
                            "chinese": "收银机 / 收银台",
                            "definition": "register 在这里指店里的收银设备或收银台。",
                            "collocations": "at the register / behind the register",
                            "context": "零售或餐饮结账场景。",
                            "example": "Meet me at the register.",
                            "chinese_feel": "收银台。",
                            "why": "同一个词在服务业语境里不是注册。",
                            "difficulty": "B1 日常交流",
                            "teacher_note": "看上下文判断 register 的场景义。",
                            "cloze": "I'm gonna run the ____.",
                            "learning_target": "训练 register 的语境词义。",
                            "why_it_matters": "避免把 register 误解成登记。",
                            "how_to_use_it": "用在商店、柜台、结账场景。",
                            "natural_chinese": "我来负责收银。",
                            "replacement_examples": "The receipt is at the register.",
                            "retrieval_prompt": "register 在这句里是什么意思？",
                            "usage_boundary": "在结账场景才这样理解。",
                            "confusable_note": "不要默认理解成动词“注册”。",
                        },
                    ],
                }
            ]
        }

        merged, _ = worker.merge_ai_cards(grouped, ai_payload, ["phrase"], "C2")
        phrases = {card["phrase"] for card in merged[0]["cards"]}

        self.assertIn("run the register", phrases)
        self.assertIn("register", phrases)
        expression_card = next(card for card in merged[0]["cards"] if card["phrase"] == "run the register")
        self.assertEqual(expression_card["learning_action"], "expression_recall")
        self.assertIn("临时负责", expression_card["conceptual_action"])
        self.assertIn("跑步", expression_card["chinese_learner_trap"])
        self.assertEqual(len([card for card in merged[0]["cards"] if card["type"] == "phrase"]), 2)

    def test_merge_ai_cards_extra_card_does_not_inherit_fallback_phrase(self):
        segments = [
            {
                "id": "seg_0001",
                "text": "Star snitch says some dude goes by cap'n Cook lives up to his name in there.",
                "phrase": "goes by",
                "exact_span": "goes by",
                "normalized_answer": "goes by",
                "answer_core": "goes by",
                "candidate_kind": "expression",
                "phrase_type": "spoken_phrase",
                "content_kind": "phrase",
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
                            "phrase": "goes by",
                            "exact_span": "goes by",
                            "normalized_answer": "goes by",
                            "answer_core": "goes by",
                            "candidate_kind": "expression",
                            "phrase_type": "spoken_phrase",
                            "content_kind": "phrase",
                            "chinese": "自称 / 叫作",
                            "definition": "Use this to say what name someone uses.",
                            "context": "Someone is describing an alias.",
                            "teacher_note": "常见于介绍绰号或化名。",
                        },
                        {
                            "type": "phrase",
                            "exact_span": "lives up to his name",
                            "normalized_answer": "live up to one's name",
                            "answer_core": "lives up to his name",
                            "candidate_kind": "expression",
                            "phrase_type": "idiom",
                            "content_kind": "phrase",
                            "chinese": "名副其实",
                            "definition": "Use this when someone's behavior matches their name or reputation.",
                            "context": "The nickname Cook matches what the person does.",
                            "teacher_note": "这里是评价绰号和行为相符。",
                        },
                    ],
                }
            ]
        }

        merged, _ = worker.merge_ai_cards(segments, ai_payload, ["phrase"], "B2")
        extra = next(card for card in merged[0]["cards"] if card["answer_core"] == "lives up to his name")

        self.assertEqual(extra["phrase"], "lives up to his name")
        self.assertNotEqual(extra["phrase"], "goes by")

    def test_sparse_ai_phrase_card_is_not_recommended(self):
        segments = [
            {
                "id": "seg_0001",
                "text": "This thing performs as advertised.",
                "phrase": "performs as advertised",
                "source_time": "00:00:01.000 - 00:00:03.000",
                "candidate_kind": "expression",
                "phrase_type": "collocation",
                "content_kind": "phrase",
                "learning_points": [
                    {
                        "id": "lp_phrase",
                        "kind": "expression",
                        "exact_span": "performs as advertised",
                        "normalized_answer": "performs as advertised",
                        "answer_core": "performs as advertised",
                        "phrase_type": "collocation",
                        "content_kind": "phrase",
                        "suggested_card_type": "phrase",
                    }
                ],
            }
        ]
        ai_payload = {
            "segments": [
                {
                    "id": "seg_0001",
                    "cards": [
                        {
                            "type": "phrase",
                            "learning_point_id": "lp_phrase",
                            "exact_span": "performs as advertised",
                            "normalized_answer": "performs as advertised",
                            "answer_core": "performs as advertised",
                            "phrase": "performs as advertised",
                        }
                    ],
                }
            ]
        }

        merged, _ = worker.merge_ai_cards(segments, ai_payload, ["phrase"], "C1")
        card = merged[0]["cards"][0]

        self.assertFalse(card["enabled"])
        self.assertNotEqual(card["quality"]["status"], "recommended")
        self.assertIn("AI 解释字段不足", card["quality"]["issues"])
        self.assertIn("字段像模板废话", card["quality"]["issues"])

    def test_try_run_ffmpeg_returns_error_instead_of_exiting(self):
        original_which = worker.shutil.which
        try:
            worker.shutil.which = lambda name: None if name == "ffmpeg" else original_which(name)

            message = worker.try_run_ffmpeg(["-version"])
        finally:
            worker.shutil.which = original_which

        self.assertIn("找不到 ffmpeg", message)

    def test_export_blocks_video_cards_when_local_media_slicing_fails(self):
        try:
            import genanki  # noqa: F401
        except ImportError:
            self.skipTest("genanki is required for export smoke")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video_path = root / "not-a-real-video.mkv"
            subtitle_path = root / "not-a-real-video.srt"
            output_dir = root / "out"
            video_path.write_bytes(b"not a real video")
            subtitle_path.write_text(
                "1\n"
                "00:00:00,000 --> 00:00:02,000\n"
                "Dad, come check this out.\n\n"
                "2\n"
                "00:00:03,000 --> 00:00:05,000\n"
                "It looks like a normal morning.\n",
                encoding="utf-8",
            )
            output_dir.mkdir()

            project = worker.handle_generate(
                {
                    "source_mode": "local",
                    "title": "bad media fallback",
                    "video_path": str(video_path),
                    "subtitle_path": str(subtitle_path),
                    "language": "English",
                    "level": "B1",
                    "collection_levels": ["A2", "B1", "B2"],
                    "card_types": ["phrase"],
                    "content_toggles": {"daily": True},
                    "api_config": {"provider": "local"},
                }
            )
            for segment in project["segments"]:
                for card in segment["cards"]:
                    card["difficulty_reason"] = "根据当前水平和表达可迁移性估计。"
                    card["enabled"] = True

            original_synthesize_tts = worker._legacy_worker.synthesize_tts
            stderr = io.StringIO()
            try:
                worker._legacy_worker.synthesize_tts = lambda *args, **kwargs: self.fail(
                    "TTS synthesis should not run when TTS is disabled"
                )
                with redirect_stderr(stderr), self.assertRaises(SystemExit):
                    worker.handle_export({"project": project, "output_dir": str(output_dir)})
            finally:
                worker._legacy_worker.synthesize_tts = original_synthesize_tts

            message = stderr.getvalue()
            self.assertIn("视频/原声切片失败", message)
            self.assertIn("避免生成缺视频的视频卡", message)
            self.assertNotIn("skip-video-slicing", message)
            self.assertNotIn("use-subtitle-only", message)
            self.assertFalse(any(output_dir.glob("*.apkg")))

    def test_export_requires_video_path_for_video_projects_by_default(self):
        try:
            import genanki  # noqa: F401
        except ImportError:
            self.skipTest("genanki is required for export smoke")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "out"
            output_dir.mkdir()
            project = {
                "title": "video without media",
                "source_mode": "local",
                "video_path": "",
                "subtitle_path": "",
                "language": "English",
                "level": "B1",
                "template_id": "immersive_v11",
                "review_density": "fast",
                "segments": [
                    {
                        "id": "seg_1",
                        "start": 0,
                        "end": 2,
                        "text": "Can you run the register?",
                        "cards": [
                            {
                                "id": "card_1",
                                "type": "phrase",
                                "enabled": True,
                                "phrase": "run the register",
                                "answer_core": "run the register",
                                "english": "Can you run the register?",
                                "chinese": "负责收银",
                                "definition": "负责操作收银机。",
                                "context": "Can you run the register?",
                            }
                        ],
                    }
                ],
            }

            stderr = io.StringIO()
            with redirect_stderr(stderr), self.assertRaises(SystemExit):
                worker.handle_export({"project": project, "output_dir": str(output_dir)})

            message = stderr.getvalue()
            self.assertIn("没有可切片的视频文件", message)
            self.assertNotIn("use-subtitle-only", message)
            self.assertFalse(any(output_dir.glob("*.apkg")))

    def test_export_allows_url_subtitle_only_without_video_path(self):
        try:
            import genanki  # noqa: F401
        except ImportError:
            self.skipTest("genanki is required for export smoke")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "out"
            output_dir.mkdir()
            project = {
                "title": "url subtitle only",
                "source_mode": "url",
                "source_url": "https://www.youtube.com/watch?v=test",
                "url_import_mode": "subtitles",
                "source_info": {"download_mode": "subtitles", "transcript_only": True},
                "skip_video_slicing": True,
                "video_path": "",
                "subtitle_path": "",
                "language": "English",
                "level": "B1",
                "template_id": "immersive_v11",
                "review_density": "fast",
                "segments": [
                    {
                        "id": "seg_1",
                        "start": 0,
                        "end": 2,
                        "source_time": "00:00:00.000 - 00:00:02.000",
                        "text": "Can you run the register?",
                        "cards": [
                            {
                                "id": "card_1",
                                "type": "phrase",
                                "enabled": True,
                                "phrase": "run the register",
                                "answer_core": "run the register",
                                "english": "Can you run the register?",
                                "chinese": "负责收银",
                                "definition": "负责操作收银机。",
                                "context": "Can you run the register?",
                            }
                        ],
                    }
                ],
            }

            result = worker.handle_export({"project": project, "output_dir": str(output_dir)})

            self.assertTrue(Path(result["apkg_path"]).exists())
            self.assertEqual(len(result["apkg_sha256"]), 64)
            self.assertEqual(result["apkg_sha256"], hashlib.sha256(Path(result["apkg_path"]).read_bytes()).hexdigest())
            self.assertEqual(result["apkg_size_bytes"], Path(result["apkg_path"]).stat().st_size)
            self.assertGreater(result["apkg_mtime_ms"], 0)
            self.assertEqual(result["cards"], 1)
            self.assertEqual(result["media_summary"]["video_segments"], 0)
            self.assertIn("total", result["timing_ms"])
            self.assertIn("source_prepare", result["timing_ms"])
            self.assertEqual(result["media_summary"]["media_concurrency"], 0)
            self.assertEqual(result["deck_kind"], "subtitle_language")

    def test_export_can_write_direct_canonical_release_apkg(self):
        try:
            import genanki  # noqa: F401
        except ImportError:
            self.skipTest("genanki is required for export smoke")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            apkg_dir = (
                root
                / "test_runs"
                / "video_release_hardening_20260620_010000"
                / "cases"
                / "local_srt_full1_cold"
                / "apkg"
            )
            apkg_dir.mkdir(parents=True)
            canonical_apkg_path = apkg_dir / "local_srt_full1_cold.apkg"
            project = {
                "title": "local_srt_full1_cold",
                "source_mode": "url",
                "source_url": "https://www.youtube.com/watch?v=test",
                "url_import_mode": "subtitles",
                "source_info": {"download_mode": "subtitles", "transcript_only": True},
                "skip_video_slicing": True,
                "video_path": "",
                "subtitle_path": "",
                "language": "English",
                "level": "B1",
                "template_id": "immersive_v11",
                "review_density": "fast",
                "segments": [
                    {
                        "id": "seg_1",
                        "start": 0,
                        "end": 2,
                        "source_time": "00:00:00.000 - 00:00:02.000",
                        "text": "Can you run the register?",
                        "cards": [
                            {
                                "id": "card_1",
                                "type": "phrase",
                                "enabled": True,
                                "phrase": "run the register",
                                "answer_core": "run the register",
                                "english": "Can you run the register?",
                                "chinese": "负责收银",
                                "definition": "负责操作收银机。",
                                "context": "Can you run the register?",
                            }
                        ],
                    }
                ],
            }

            result = worker.handle_export(
                {
                    "project": project,
                    "output_dir": str(apkg_dir),
                    "canonical_apkg_path": str(canonical_apkg_path),
                }
            )

            self.assertEqual(Path(result["apkg_path"]), canonical_apkg_path)
            self.assertTrue(canonical_apkg_path.exists())
            self.assertEqual(list(apkg_dir.glob("*.apkg")), [canonical_apkg_path])
            self.assertEqual(result["apkg_sha256"], hashlib.sha256(canonical_apkg_path.read_bytes()).hexdigest())
            self.assertEqual(result["apkg_size_bytes"], canonical_apkg_path.stat().st_size)

    def test_export_refuses_existing_canonical_release_apkg(self):
        try:
            import genanki  # noqa: F401
        except ImportError:
            self.skipTest("genanki is required for export smoke")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            apkg_dir = root / "test_runs" / "video_release_hardening_20260620_010000" / "cases" / "case_a" / "apkg"
            apkg_dir.mkdir(parents=True)
            canonical_apkg_path = apkg_dir / "case_a.apkg"
            canonical_apkg_path.write_bytes(b"existing release evidence")
            stderr = io.StringIO()

            with redirect_stderr(stderr), self.assertRaises(SystemExit):
                worker.handle_export(
                    {
                        "project": {"title": "case_a", "source_mode": "document", "segments": []},
                        "output_dir": str(apkg_dir),
                        "canonical_apkg_path": str(canonical_apkg_path),
                    }
                )

            self.assertIn("为避免覆盖证据已停止", stderr.getvalue())
            self.assertEqual(canonical_apkg_path.read_bytes(), b"existing release evidence")

    def test_export_batch_project_writes_nested_subdecks(self):
        try:
            import genanki  # noqa: F401
        except ImportError:
            self.skipTest("genanki is required for export smoke")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "out"
            output_dir.mkdir()
            project = {
                "id": "batch-shameless-s1",
                "title": "无耻之徒 第一季",
                "source_mode": "local",
                "video_path": "",
                "subtitle_path": "",
                "language": "en",
                "level": "B1",
                "template_id": "immersive_v11",
                "skip_video_slicing": True,
                "batch_enabled": True,
                "batch_items": [
                    {
                        "id": "ep1",
                        "enabled": True,
                        "source_mode": "local",
                        "subdeck_title": "S01E01 - Pilot",
                        "deck_name": "无耻之徒 第一季::S01E01 - Pilot",
                    },
                    {
                        "id": "ep2",
                        "enabled": True,
                        "source_mode": "local",
                        "subdeck_title": "S01E02 - Frank the Plank",
                        "deck_name": "无耻之徒 第一季::S01E02 - Frank the Plank",
                    },
                ],
                "segments": [
                    {
                        "id": "seg-ep1",
                        "batch_item_id": "ep1",
                        "text": "I am in the mood to help today.",
                        "start": 1.0,
                        "end": 2.0,
                        "source_time": "00:00:01.000 - 00:00:02.000",
                        "cards": [
                            {
                                "id": "card-ep1",
                                "type": "phrase",
                                "enabled": True,
                                "english": "I am in the mood to help today.",
                                "answer_core": "in the mood",
                                "phrase": "in the mood",
                                "chinese": "有心情",
                                "definition": "ready or willing to do something",
                                "context": "Someone is willing to help.",
                                "teacher_note": "不是 mood 本身的普通名词用法。",
                                "pronunciation_meta": {},
                            }
                        ],
                    },
                    {
                        "id": "seg-ep2",
                        "batch_item_id": "ep2",
                        "text": "Can you run the register for a minute?",
                        "start": 3.0,
                        "end": 4.0,
                        "source_time": "00:00:03.000 - 00:00:04.000",
                        "cards": [
                            {
                                "id": "card-ep2",
                                "type": "phrase",
                                "enabled": True,
                                "english": "Can you run the register for a minute?",
                                "answer_core": "run the register",
                                "phrase": "run the register",
                                "chinese": "负责收银",
                                "definition": "operate the cash register",
                                "context": "A store work task.",
                                "teacher_note": "服务业场景搭配。",
                                "pronunciation_meta": {},
                            }
                        ],
                    },
                ],
            }

            result = worker.handle_export({"project": project, "output_dir": str(output_dir)})

            self.assertTrue(Path(result["apkg_path"]).exists())
            self.assertEqual(result["cards"], 2)
            self.assertEqual(result["deck_name"], "无耻之徒 第一季")
            self.assertEqual(
                result["deck_names"],
                ["无耻之徒 第一季::S01E01 - Pilot", "无耻之徒 第一季::S01E02 - Frank the Plank"],
            )
            self.assertEqual(result["batch_summary"]["items"], 2)
            self.assertEqual(result["batch_summary"]["exported_items"], 2)

            import sqlite3
            import zipfile

            with zipfile.ZipFile(result["apkg_path"]) as apkg:
                apkg.extract("collection.anki2", root)
            connection = sqlite3.connect(root / "collection.anki2")
            try:
                decks_json = connection.execute("select decks from col").fetchone()[0]
                card_deck_ids = [row[0] for row in connection.execute("select did from cards order by id").fetchall()]
            finally:
                connection.close()
            decks_by_id = json.loads(decks_json)
            exported_deck_names = {deck["name"] for deck in decks_by_id.values()}
            self.assertIn("无耻之徒 第一季::S01E01 - Pilot", exported_deck_names)
            self.assertIn("无耻之徒 第一季::S01E02 - Frank the Plank", exported_deck_names)
            self.assertEqual(len(set(card_deck_ids)), 2)

    def test_batch_export_smoke_for_url_and_document_projects(self):
        try:
            import genanki  # noqa: F401
        except ImportError:
            self.skipTest("genanki is required for export smoke")

        import sqlite3
        import zipfile

        def assert_batch_export(project, expected_kind: str, expected_decks: list[str]) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                output_dir = root / "out"
                unpacked = root / "unpacked"
                output_dir.mkdir()
                unpacked.mkdir()

                result = worker.handle_export({"project": project, "output_dir": str(output_dir)})

                self.assertTrue(Path(result["apkg_path"]).exists())
                self.assertEqual(result["deck_kind"], expected_kind)
                self.assertEqual(result["deck_names"], expected_decks)
                self.assertEqual(result["batch_summary"]["items"], len(expected_decks))
                self.assertEqual(result["batch_summary"]["exported_items"], len(expected_decks))
                self.assertEqual(result["media_summary"]["video_segments"], 0)
                self.assertEqual(result["quality_audit"]["empty_required_fields"], 0)

                with zipfile.ZipFile(result["apkg_path"]) as apkg:
                    apkg.extract("collection.anki2", unpacked)
                connection = sqlite3.connect(unpacked / "collection.anki2")
                try:
                    decks_json = connection.execute("select decks from col").fetchone()[0]
                    card_deck_ids = [row[0] for row in connection.execute("select did from cards order by id").fetchall()]
                finally:
                    connection.close()
                exported_names = {deck["name"] for deck in json.loads(decks_json).values()}
                for deck_name in expected_decks:
                    self.assertIn(deck_name, exported_names)
                self.assertEqual(len(set(card_deck_ids)), len(expected_decks))

        url_project = {
            "id": "batch-url-smoke",
            "title": "TED Links",
            "source_mode": "url",
            "source_url": "",
            "video_path": "",
            "subtitle_path": "",
            "language": "en",
            "level": "B1",
            "template_id": "immersive_v11",
            "skip_video_slicing": True,
            "batch_enabled": True,
            "batch_items": [
                {"id": "url1", "enabled": True, "source_mode": "url", "subdeck_title": "001 - First talk", "deck_name": "TED Links::001 - First talk"},
                {"id": "url2", "enabled": True, "source_mode": "url", "subdeck_title": "002 - Second talk", "deck_name": "TED Links::002 - Second talk"},
            ],
            "segments": [
                {
                    "id": "url-seg-1",
                    "batch_item_id": "url1",
                    "text": "Let me look it up before the meeting.",
                    "start": 1,
                    "end": 2,
                    "source_time": "00:00:01.000 - 00:00:02.000",
                    "cards": [
                        {
                            "id": "url-card-1",
                            "type": "phrase",
                            "enabled": True,
                            "english": "Let me look it up before the meeting.",
                            "answer_core": "look it up",
                            "phrase": "look it up",
                            "chinese": "查一下",
                            "definition": "search for information",
                            "context": "Someone checks information before a meeting.",
                            "teacher_note": "up 是短语动词的一部分，不是方向。",
                            "pronunciation_meta": {},
                        }
                    ],
                },
                {
                    "id": "url-seg-2",
                    "batch_item_id": "url2",
                    "text": "We need to figure it out together.",
                    "start": 3,
                    "end": 4,
                    "source_time": "00:00:03.000 - 00:00:04.000",
                    "cards": [
                        {
                            "id": "url-card-2",
                            "type": "phrase",
                            "enabled": True,
                            "english": "We need to figure it out together.",
                            "answer_core": "figure it out",
                            "phrase": "figure it out",
                            "chinese": "弄明白",
                            "definition": "understand or solve something",
                            "context": "A team solves a problem.",
                            "teacher_note": "不是 figure 的数字/身材含义。",
                            "pronunciation_meta": {},
                        }
                    ],
                },
            ],
        }
        assert_batch_export(url_project, "subtitle_language", ["TED Links::001 - First talk", "TED Links::002 - Second talk"])

        document_project = {
            "id": "batch-doc-smoke",
            "title": "Learning Science Notes",
            "source_mode": "document",
            "document_path": "",
            "language": "en",
            "level": "B1",
            "template_id": "immersive",
            "document_study_mode": "knowledge",
            "batch_enabled": True,
            "batch_items": [
                {"id": "doc1", "enabled": True, "source_mode": "document", "subdeck_title": "001 - Retrieval", "deck_name": "Learning Science Notes::001 - Retrieval"},
                {"id": "doc2", "enabled": True, "source_mode": "document", "subdeck_title": "002 - Spacing", "deck_name": "Learning Science Notes::002 - Spacing"},
            ],
            "segments": [
                {
                    "id": "doc-seg-1",
                    "batch_item_id": "doc1",
                    "text": "Retrieval practice strengthens later access better than rereading.",
                    "source_time": "文档知识点 1",
                    "cards": [
                        {
                            "id": "doc-card-1",
                            "type": "knowledge",
                            "enabled": True,
                            "english": "为什么 retrieval practice 比重读更有效？",
                            "answer_core": "retrieval practice",
                            "phrase": "retrieval practice",
                            "chinese": "主动回忆会练习从记忆中取回信息，而不只是再次看到信息。",
                            "definition": "通过尝试回答来强化长期记忆的学习方式。",
                            "context": "The note contrasts retrieval practice with rereading.",
                            "teacher_note": "它不是简单重读；没有取回动作就不算主动回忆。",
                            "why": "能避免熟悉感误导学习者。",
                            "pronunciation_meta": {},
                        }
                    ],
                },
                {
                    "id": "doc-seg-2",
                    "batch_item_id": "doc2",
                    "text": "The spacing effect improves long-term retention when reviews are spread across time.",
                    "source_time": "文档知识点 2",
                    "cards": [
                        {
                            "id": "doc-card-2",
                            "type": "knowledge",
                            "enabled": True,
                            "english": "spacing effect 的关键是什么？",
                            "answer_core": "spacing effect",
                            "phrase": "spacing effect",
                            "chinese": "把复习分散到不同时间点，利用遗忘与重新取回来巩固记忆。",
                            "definition": "间隔安排复习比集中重复更利于长期保持。",
                            "context": "The note links review spacing to long-term retention.",
                            "teacher_note": "它不是拖延复习，而是有意拉开复习间隔。",
                            "why": "能让卡片复习更符合记忆规律。",
                            "pronunciation_meta": {},
                        }
                    ],
                },
            ],
        }
        assert_batch_export(
            document_project,
            "document_knowledge",
            ["Learning Science Notes::001 - Retrieval", "Learning Science Notes::002 - Spacing"],
        )

    def test_export_reuses_media_for_identical_clip_windows(self):
        try:
            import genanki  # noqa: F401
        except ImportError:
            self.skipTest("genanki is required for export smoke")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video_path = root / "source.mkv"
            output_dir = root / "out"
            video_path.write_bytes(b"fake video bytes for fingerprint")
            output_dir.mkdir()
            project = {
                "title": "media reuse",
                "source_mode": "local",
                "video_path": str(video_path),
                "language": "en",
                "level": "B1",
                "template_id": "immersive_v11",
                "api_config": {
                    "provider": "local",
                    "tts_config": {
                        "enabled": True,
                        "provider": "openai-compatible",
                        "base_url": "https://api.example.com/v1",
                        "api_key": "sk-test",
                        "model": "tts-test",
                        "voice": "alloy",
                    },
                },
                "segments": [
                    {
                        "id": "seg-a",
                        "text": "Can you calibrate the nozzle before we start?",
                        "start": 10.0,
                        "end": 12.0,
                        "media_start": 10.0,
                        "media_end": 12.0,
                        "source_time": "00:00:10.000 - 00:00:12.000",
                        "cards": [
                            {
                                "id": "card-a",
                                "type": "phrase",
                                "enabled": True,
                                "english": "Can you run the register for a minute?",
                                "answer_core": "run the register",
                                "phrase": "run the register",
                                "chinese": "负责收银",
                                "definition": "operate the cash register",
                                "context": "A store work task.",
                                "teacher_note": "服务业场景搭配。",
                                "pronunciation_meta": {},
                            }
                        ],
                    },
                    {
                        "id": "seg-b",
                        "text": "Can you run the register for a minute?",
                        "start": 10.0,
                        "end": 12.0,
                        "media_start": 10.0,
                        "media_end": 12.0,
                        "source_time": "00:00:10.000 - 00:00:12.000",
                        "cards": [
                            {
                                "id": "card-b",
                                "type": "phrase",
                                "enabled": True,
                                "english": "Can you run the register for a minute?",
                                "answer_core": "register",
                                "phrase": "register",
                                "chinese": "收银机",
                                "definition": "cash register in this context",
                                "context": "A store work task.",
                                "teacher_note": "熟词语境义。",
                                "pronunciation_meta": {},
                            }
                        ],
                    },
                ],
            }
            original_try_run_ffmpeg = worker._legacy_worker.try_run_ffmpeg
            original_synthesize_tts = worker._legacy_worker.synthesize_tts
            original_cwd = os.getcwd()

            def fake_try_run_ffmpeg(command):
                output_path = Path(command[-1])
                if output_path.suffix == ".mp4":
                    output_path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 8192)
                elif output_path.suffix == ".webm":
                    output_path.write_bytes(b"\x1a\x45\xdf\xa3" + b"\x00" * 8192)
                elif output_path.suffix == ".jpg":
                    output_path.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 8192)
                elif output_path.suffix == ".mp3":
                    output_path.write_bytes(b"ID3" + b"\x00" * 8192)
                else:
                    output_path.write_bytes(b"media")
                return ""

            def fake_synthesize_tts(project_arg, segment_arg, output_path, text_override=None, tts_kind="sentence"):
                Path(output_path).write_bytes(b"ID3" + b"\x00" * 8192)
                text = str(text_override or segment_arg.get("text") or "")
                return {
                    "ok": True,
                    "cache_hit": False,
                    "semantic": worker._legacy_worker.tts_semantic_not_applicable(
                        text,
                        "phrase_tts" if tts_kind == "phrase" else "sentence_tts",
                    ),
                }

            try:
                os.chdir(root)
                worker._legacy_worker.try_run_ffmpeg = fake_try_run_ffmpeg
                worker._legacy_worker.synthesize_tts = fake_synthesize_tts
                result = worker.handle_export({"project": project, "output_dir": str(output_dir)})
            finally:
                os.chdir(original_cwd)
                worker._legacy_worker.try_run_ffmpeg = original_try_run_ffmpeg
                worker._legacy_worker.synthesize_tts = original_synthesize_tts

            self.assertEqual(result["cards"], 2)
            self.assertEqual(result["segments"], 2)
            self.assertEqual(result["media_summary"]["video_segments"], 1)
            self.assertEqual(result["media_summary"]["video_files"], 2)
            self.assertEqual(result["media_summary"]["original_audio_files"], 1)
            self.assertEqual(result["media_summary"]["sentence_tts_files"], 2)
            self.assertEqual(result["media_summary"]["phrase_tts_files"], 2)
            self.assertEqual(result["media_summary"]["media_reused_segments"], 1)
            self.assertEqual(result["media_summary"]["media_files"], 8)
            self.assertEqual(result["media_summary"]["tts_cache_hits"], 0)
            self.assertEqual(result["media_summary"]["tts_cache_misses"], 4)
            self.assertEqual(result["media_summary"]["tts_cache_total"], 4)
            self.assertEqual(result["media_summary"]["media_cache_hits"], 0)
            self.assertEqual(result["media_summary"]["media_cache_misses"], 4)
            self.assertEqual(result["media_summary"]["media_cache_total"], 4)

    def test_export_cuts_video_and_original_audio_from_final_media_bounds_for_phrase_positions(self):
        try:
            import genanki  # noqa: F401
        except ImportError:
            self.skipTest("genanki is required for export smoke")

        from acg.media_alignment import align_segment_media_to_display_sentence, fmt_time, segment_media_bounds

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video_path = root / "source.mp4"
            output_dir = root / "out"
            video_path.write_bytes(b"unique media bounds fixture " + os.urandom(16))
            output_dir.mkdir()
            full_sentence = (
                "right at the start we explain the setup then quietly make the decision "
                "together and save the surprise right before we leave"
            )
            phrases = [
                ("seg_start", "right at the start", 100.0, 118.0),
                ("seg_middle", "quietly make the decision", 140.0, 158.0),
                ("seg_end", "right before we leave", 180.0, 198.0),
            ]
            segments = []
            for index, (segment_id, phrase, start_at, end_at) in enumerate(phrases, start=1):
                media_start, media_end = segment_media_bounds(start_at, end_at, full_sentence, phrase, review_mode=False)
                segments.append(
                    {
                        "id": segment_id,
                        "start": start_at,
                        "end": end_at,
                        "media_start": media_start,
                        "media_end": media_end,
                        "full_source_sentence": full_sentence,
                        "source_time": f"{fmt_time(start_at)} - {fmt_time(end_at)}",
                        "media_source_time": f"{fmt_time(media_start)} - {fmt_time(media_end)}",
                        "text": full_sentence,
                        "cards": [
                            {
                                "id": f"card_{index}",
                                "type": "phrase",
                                "enabled": True,
                                "english": full_sentence,
                                "answer_core": phrase,
                                "phrase": phrase,
                                "chinese": "结合原句理解这个表达。",
                                "definition": "A useful expression from the sentence.",
                                "context": full_sentence,
                                "teacher_note": "检查视频与原声都使用 media_start/media_end。",
                                "pronunciation_meta": {},
                            }
                        ],
                    }
                )
            expected_aligned_by_segment = {
                str(segment["id"]): align_segment_media_to_display_sentence(segment)
                for segment in segments
            }
            project = {
                "title": "media bounds original audio",
                "source_mode": "local",
                "video_path": str(video_path),
                "language": "en",
                "level": "B1",
                "template_id": "immersive_v11",
                "api_config": {
                    "provider": "local",
                    "tts_config": {
                        "enabled": True,
                        "provider": "openai-compatible",
                        "base_url": "https://api.example.com/v1",
                        "api_key": "sk-test",
                        "model": "tts-test",
                        "voice": "alloy",
                    },
                },
                "segments": segments,
            }
            captured_commands: list[list[str]] = []
            original_try_run_ffmpeg = worker._legacy_worker.try_run_ffmpeg
            original_synthesize_tts = worker._legacy_worker.synthesize_tts

            def fake_try_run_ffmpeg(command):
                captured_commands.append([str(part) for part in command])
                output_path = Path(command[-1])
                if output_path.suffix == ".mp4":
                    output_path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 8192)
                elif output_path.suffix == ".webm":
                    output_path.write_bytes(b"\x1a\x45\xdf\xa3" + b"\x00" * 8192)
                elif output_path.suffix == ".jpg":
                    output_path.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 8192)
                elif output_path.suffix == ".mp3":
                    output_path.write_bytes(b"ID3" + b"\x00" * 8192)
                else:
                    output_path.write_bytes(b"media")
                return ""

            def fake_synthesize_tts(project_arg, segment_arg, output_path, text_override=None, tts_kind="sentence"):
                Path(output_path).write_bytes(b"ID3" + b"\x00" * 8192)
                text = str(text_override or segment_arg.get("text") or "")
                return {
                    "ok": True,
                    "cache_hit": False,
                    "semantic": worker._legacy_worker.tts_semantic_not_applicable(
                        text,
                        "phrase_tts" if tts_kind == "phrase" else "sentence_tts",
                    ),
                }

            try:
                worker._legacy_worker.try_run_ffmpeg = fake_try_run_ffmpeg
                worker._legacy_worker.synthesize_tts = fake_synthesize_tts
                result = worker.handle_export({"project": project, "output_dir": str(output_dir)})
            finally:
                worker._legacy_worker.try_run_ffmpeg = original_try_run_ffmpeg
                worker._legacy_worker.synthesize_tts = original_synthesize_tts

            self.assertEqual(result["cards"], 3)
            self.assertEqual(result["media_summary"]["video_segments"], 3)
            self.assertEqual(result["media_summary"]["original_audio_files"], 3)
            media_by_segment = {item["segment_id"]: item for item in result["card_media_ledger"]}
            audit_by_segment = {item["segment_id"]: item for item in result["audio_audit_items"]}
            used_adjusted_media_window = False
            for segment in segments:
                segment_id = segment["id"]
                card_media = media_by_segment[segment_id]
                expected_aligned = expected_aligned_by_segment[segment_id]
                expected_start = str(max(0.0, float(expected_aligned["media_start"])))
                expected_duration = str(
                    max(0.5, float(expected_aligned["media_end"]) - float(expected_aligned["media_start"]))
                )
                mp4_command = next(
                    command
                    for command in captured_commands
                    if Path(command[-1]).suffix == ".mp4" and segment_id in Path(command[-1]).name
                )
                original_audio_command = next(
                    command
                    for command in captured_commands
                    if Path(command[-1]).suffix == ".mp3" and segment_id in Path(command[-1]).name
                )
                for command in [mp4_command, original_audio_command]:
                    self.assertEqual(command[command.index("-ss") + 1], expected_start)
                    self.assertEqual(command[command.index("-t") + 1], expected_duration)
                used_adjusted_media_window = used_adjusted_media_window or expected_start != str(segment["start"])
                used_adjusted_media_window = used_adjusted_media_window or expected_duration != str(
                    segment["end"] - segment["start"]
                )

            self.assertTrue(used_adjusted_media_window)
            for segment in segments:
                expected_aligned = expected_aligned_by_segment[segment["id"]]
                card_media = media_by_segment[segment["id"]]
                audit_item = audit_by_segment[segment["id"]]
                self.assertEqual(card_media["media_start"], expected_aligned["media_start"])
                self.assertEqual(card_media["media_end"], expected_aligned["media_end"])
                self.assertEqual(card_media["media_source_time"], expected_aligned["media_source_time"])
                self.assertEqual(audit_item["media_start"], expected_aligned["media_start"])
                self.assertEqual(audit_item["media_end"], expected_aligned["media_end"])
                self.assertEqual(audit_item["media_source_time"], expected_aligned["media_source_time"])

    def test_export_phrase_tts_matches_visible_answer_for_repetition_cards(self):
        try:
            import genanki  # noqa: F401
        except ImportError:
            self.skipTest("genanki is required for export smoke")

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            output_dir.mkdir()
            project = {
                "id": "tts-visible-answer",
                "title": "tts visible answer",
                "source_mode": "local",
                "video_path": "",
                "subtitle_path": "",
                "language": "English",
                "level": "B1",
                "template_id": "immersive_v11",
                "skip_video_slicing": True,
                "api_config": {
                    "provider": "local",
                    "tts_config": {
                        "enabled": True,
                        "provider": "openai-compatible",
                        "base_url": "https://api.example.com/v1",
                        "api_key": "sk-test",
                        "model": "tts-test",
                        "voice": "alloy",
                        "language": "en-US",
                        "sample_rate": 24000,
                        "bit_rate": 128000,
                    },
                },
                "segments": [
                    {
                        "id": "seg_ever",
                        "start": 1851.82,
                        "end": 1854.45,
                        "source_time": "00:30:51.820 - 00:30:54.450",
                        "text": "Ever want me to read anything, I could critique it for you.",
                        "cards": [
                            {
                                "id": "seg_ever_listening",
                                "type": "listening",
                                "type_label": "听力卡",
                                "enabled": True,
                                "english": "Ever want me to read anything, I could critique it for you.",
                                "chinese": "如果你什么时候想让我读点什么，我可以帮你点评。",
                                "phrase": "critique it",
                                "answer_core": "Ever want me to",
                                "definition": "句首省略 If you。",
                                "teacher_note": "不要误以为是疑问句。",
                            }
                        ],
                    }
                ],
            }
            captured: list[str | None] = []
            original_synthesize_tts = worker._legacy_worker.synthesize_tts

            def fake_synthesize_tts(project_arg, segment_arg, output_path, text_override=None, tts_kind="sentence"):
                captured.append(text_override)
                Path(output_path).write_bytes(b"ID3" + b"\x00" * 8192)
                return True

            try:
                worker._legacy_worker.synthesize_tts = fake_synthesize_tts
                result = worker.handle_export({"project": project, "output_dir": str(output_dir)})
            finally:
                worker._legacy_worker.synthesize_tts = original_synthesize_tts

            self.assertTrue(Path(result["apkg_path"]).exists())
            self.assertEqual(captured[0], "Ever want me to read anything, I could critique it for you.")
            self.assertEqual(captured[1], "Ever want me to")
            self.assertNotIn("critique it", captured)
            self.assertEqual(result["media_summary"]["phrase_tts_files"], 1)
            ledger = result["media_ledger"]
            phrase_entries = [item for item in ledger if item["role"] == "phrase_tts"]
            sentence_entries = [item for item in ledger if item["role"] == "sentence_tts"]
            self.assertEqual(phrase_entries[0]["tts_text"], "Ever want me to")
            self.assertIn(phrase_entries[0]["text_hash"], phrase_entries[0]["file"])
            self.assertEqual(sentence_entries[0]["tts_text"], "Ever want me to read anything, I could critique it for you.")
            self.assertIn(sentence_entries[0]["text_hash"], sentence_entries[0]["file"])
            manifest_entry = result["media_manifest"][phrase_entries[0]["file"]]
            self.assertEqual(manifest_entry["role"], "phrase_tts")
            self.assertEqual(phrase_entries[0]["semantic_verification"], "not_applicable")
            self.assertEqual(phrase_entries[0]["semantic_review_reasons"], [])
            self.assertEqual(result["media_summary"]["tts_manual_review_items"], 0)
            self.assertEqual(result["media_summary"]["tts_high_risk_manual_review_items"], 0)
            manual_phrase_items = [
                item for item in result["tts_manual_review_items"] if item["role"] == "phrase_tts"
            ]
            self.assertEqual(manual_phrase_items, [])
            self.assertEqual(result["tts_semantic_verification"]["status"], "not_applicable")
            self.assertEqual(result["media_summary"]["card_media_ledger_items"], 1)
            card_media = result["card_media_ledger"][0]
            self.assertEqual(card_media["answer"], "Ever want me to")
            self.assertEqual(card_media["sentence_tts_text"], "Ever want me to read anything, I could critique it for you.")
            self.assertEqual(card_media["phrase_tts_text"], "Ever want me to")
            self.assertEqual(card_media["sentence_tts_audio"], sentence_entries[0]["file"])
            self.assertEqual(card_media["phrase_tts_audio"], phrase_entries[0]["file"])
            self.assertTrue(Path(result["audio_audit_path"]).exists())
            self.assertTrue(Path(result["audio_audit_markdown_path"]).exists())
            self.assertEqual(result["audio_audit_summary"]["items"], 1)
            self.assertEqual(result["audio_audit_summary"]["expected_items"], 1)
            audio_audit_item = result["audio_audit_items"][0]
            self.assertEqual(audio_audit_item["card_id"], card_media["card_id"])
            self.assertEqual(audio_audit_item["visible_answer"], "Ever want me to")
            self.assertEqual(audio_audit_item["sentence_tts_expected_text"], "Ever want me to read anything, I could critique it for you.")
            self.assertEqual(audio_audit_item["phrase_tts_expected_text"], "Ever want me to")
            self.assertEqual(audio_audit_item["sentence_tts_file"], sentence_entries[0]["file"])
            self.assertEqual(audio_audit_item["phrase_tts_file"], phrase_entries[0]["file"])

    def test_export_sentence_tts_prefers_full_source_sentence_over_phrase_segment_text(self):
        try:
            import genanki  # noqa: F401
        except ImportError:
            self.skipTest("genanki is required for export smoke")

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            output_dir.mkdir()
            full_sentence = "The more you live in English, the faster your brain rewires itself."
            project = {
                "id": "tts-full-source-over-phrase",
                "title": "tts full source over phrase",
                "source_mode": "local",
                "video_path": "",
                "subtitle_path": "",
                "language": "English",
                "level": "B2",
                "template_id": "immersive_v11",
                "skip_video_slicing": True,
                "api_config": {
                    "provider": "local",
                    "tts_config": {
                        "enabled": True,
                        "provider": "openai-compatible",
                        "base_url": "https://api.example.com/v1",
                        "api_key": "sk-test",
                        "model": "tts-test",
                        "voice": "alloy",
                        "language": "en-US",
                    },
                },
                "segments": [
                    {
                        "id": "seg_rewire",
                        "start": 349.287,
                        "end": 358.061,
                        "source_time": "00:05:49.287 - 00:05:58.061",
                        "text": "rewires itself",
                        "full_source_sentence": full_sentence,
                        "source_sentence": full_sentence,
                        "cards": [
                            {
                                "id": "seg_rewire_phrase",
                                "type": "phrase",
                                "type_label": "表达",
                                "enabled": True,
                                "english": "rewires itself",
                                "chinese": "你越多用英语生活，大脑就越快重塑自己。",
                                "phrase": "rewires itself",
                                "answer_core": "rewires itself",
                                "definition": "Changes and adapts its own wiring or habits.",
                                "teacher_note": "Here it describes how the brain adapts through use.",
                            }
                        ],
                    }
                ],
            }
            captured: list[tuple[str, str | None]] = []
            original_synthesize_tts = worker._legacy_worker.synthesize_tts

            def fake_synthesize_tts(project_arg, segment_arg, output_path, text_override=None, tts_kind="sentence"):
                captured.append((tts_kind, text_override))
                Path(output_path).write_bytes(b"ID3" + b"\x00" * 8192)
                return True

            try:
                worker._legacy_worker.synthesize_tts = fake_synthesize_tts
                result = worker.handle_export({"project": project, "output_dir": str(output_dir)})
            finally:
                worker._legacy_worker.synthesize_tts = original_synthesize_tts

            self.assertTrue(Path(result["apkg_path"]).exists())
            self.assertIn(("sentence", full_sentence), captured)
            self.assertIn(("phrase", "rewires itself"), captured)
            ledger = result["media_ledger"]
            sentence_entries = [item for item in ledger if item["role"] == "sentence_tts"]
            phrase_entries = [item for item in ledger if item["role"] == "phrase_tts"]
            self.assertEqual(sentence_entries[0]["tts_text"], full_sentence)
            self.assertEqual(phrase_entries[0]["tts_text"], "rewires itself")
            card_media = result["card_media_ledger"][0]
            self.assertEqual(card_media["sentence_tts_text"], full_sentence)
            self.assertEqual(card_media["phrase_tts_text"], "rewires itself")
            audio_audit_item = result["audio_audit_items"][0]
            self.assertEqual(audio_audit_item["sentence_tts_expected_text"], full_sentence)
            self.assertEqual(audio_audit_item["phrase_tts_expected_text"], "rewires itself")
            report = verify_apkg.sqlite_fallback_report(Path(result["apkg_path"]))
            self.assertEqual(report["tts_text_hash_mismatches"], [])
            self.assertEqual(report["phrase_tts_text_hash_mismatches"], [])

            import sqlite3
            import zipfile

            with zipfile.ZipFile(result["apkg_path"]) as archive:
                collection_name = "collection.anki21" if "collection.anki21" in archive.namelist() else "collection.anki2"
                collection_path = output_dir / "collection-for-source-check.anki2"
                collection_path.write_bytes(archive.read(collection_name))
            con = sqlite3.connect(collection_path)
            try:
                models = json.loads(con.execute("select models from col").fetchone()[0])
                notes = verify_apkg.note_field_dicts(con, models)
            finally:
                con.close()
            self.assertEqual(len(notes), 1)
            self.assertEqual(verify_apkg.plain_field_text(notes[0]["English"]), full_sentence)

    def test_export_records_media_subtitle_alignment_in_card_ledger_and_audit(self):
        try:
            import genanki  # noqa: F401
        except ImportError:
            self.skipTest("genanki is required for export smoke")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "out"
            output_dir.mkdir()
            subtitle_path = root / "source.srt"
            subtitle_path.write_text(
                "\n".join(
                    [
                        "1",
                        "00:00:10,000 --> 00:00:13,000",
                        "Today we need to build your perspective on",
                        "",
                        "2",
                        "00:00:13,000 --> 00:00:16,000",
                        "build your perspective on the world before moving on.",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            project = {
                "id": "media-subtitle-alignment",
                "title": "media subtitle alignment",
                "source_mode": "local",
                "video_path": "",
                "subtitle_path": str(subtitle_path),
                "language": "English",
                "level": "B1",
                "template_id": "immersive_v11",
                "skip_video_slicing": True,
                "api_config": {"provider": "local", "tts_config": {"enabled": False, "provider": "disabled"}},
                "segments": [
                    {
                        "id": "seg_perspective",
                        "start": 10.0,
                        "end": 16.0,
                        "source_time": "00:00:10.000 - 00:00:16.000",
                        "full_source_sentence": "Today we need to build your perspective on the world before moving on.",
                        "text": "build your perspective on the world before moving on.",
                        "cards": [
                            {
                                "id": "seg_perspective_card",
                                "type": "phrase",
                                "type_label": "表达",
                                "enabled": True,
                                "english": "build your perspective on the world before moving on.",
                                "phrase": "build your perspective on",
                                "answer_core": "build your perspective on",
                                "definition": "Develop the way you understand something.",
                                "teacher_note": "Use it for viewpoints or worldview.",
                            }
                        ],
                    }
                ],
            }

            result = worker.handle_export({"project": project, "output_dir": str(output_dir)})

            self.assertEqual(result["media_summary"]["subtitle_diagnostic_status"], "loaded")
            self.assertEqual(result["media_summary"]["media_subtitle_alignment"]["matched"], 1)
            card_media = result["card_media_ledger"][0]
            self.assertLessEqual(card_media["media_start"], 10.0)
            self.assertGreaterEqual(card_media["media_end"], 16.0)
            self.assertEqual(
                card_media["card_display_sentence"],
                "Today we need to build your perspective on the world before moving on.",
            )
            self.assertEqual(card_media["media_alignment_status"], "source_sentence_window")
            self.assertEqual(
                card_media["media_alignment_text"],
                "Today we need to build your perspective on the world before moving on.",
            )
            self.assertEqual(card_media["media_subtitle_alignment_status"], "matched")
            self.assertIn("build your perspective", card_media["media_window_subtitle_text"])
            audit_item = result["audio_audit_items"][0]
            self.assertEqual(audit_item["media_start"], card_media["media_start"])
            self.assertEqual(audit_item["media_end"], card_media["media_end"])
            self.assertEqual(
                audit_item["card_display_sentence"],
                "Today we need to build your perspective on the world before moving on.",
            )
            self.assertEqual(audit_item["media_subtitle_alignment_status"], "matched")
            self.assertIn("build your perspective", audit_item["media_window_subtitle_text"])
            self.assertIn("build your perspective", audit_item["media_subtitle_text"])
            self.assertEqual(audit_item["media_alignment_score"], audit_item["media_subtitle_overlap_score"])

    def test_export_repeated_caption_alignment_matches_for_url_and_local_video_sources(self):
        try:
            import genanki  # noqa: F401
        except ImportError:
            self.skipTest("genanki is required for export smoke")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repeated_caption_srt = "\n".join(
                [
                    "1",
                    "00:00:10,000 --> 00:00:11,000",
                    "go go go go",
                    "",
                    "2",
                    "00:00:11,000 --> 00:00:12,200",
                    "go go now",
                    "",
                ]
            )
            original_try_run_ffmpeg = worker._legacy_worker.try_run_ffmpeg
            original_synthesize_tts = worker._legacy_worker.synthesize_tts
            original_ffprobe_video = verify_apkg.ffprobe_video
            original_cwd = os.getcwd()

            def fake_try_run_ffmpeg(command):
                output_path = Path(command[-1])
                if output_path.suffix == ".mp4":
                    output_path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 8192)
                elif output_path.suffix == ".webm":
                    output_path.write_bytes(b"\x1a\x45\xdf\xa3" + b"\x00" * 8192)
                elif output_path.suffix == ".jpg":
                    output_path.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 8192)
                elif output_path.suffix == ".mp3":
                    output_path.write_bytes(b"ID3" + b"\x00" * 8192)
                else:
                    output_path.write_bytes(b"media")
                return ""

            def fake_synthesize_tts(project_arg, segment_arg, output_path, text_override=None, tts_kind="sentence"):
                Path(output_path).write_bytes(b"ID3" + b"\x00" * 8192)
                text = str(text_override or segment_arg.get("text") or "")
                return {
                    "ok": True,
                    "cache_hit": False,
                    "semantic": worker._legacy_worker.tts_semantic_not_applicable(
                        text,
                        "phrase_tts" if tts_kind == "phrase" else "sentence_tts",
                    ),
                }

            def fake_ffprobe_video(path):
                suffix = Path(path).suffix.lower()
                return {
                    "ok": True,
                    "codec": "h264" if suffix == ".mp4" else "vp8",
                    "profile": "Baseline" if suffix == ".mp4" else "",
                    "width": 960,
                    "height": 540,
                }

            def repeated_caption_project(source_mode: str) -> dict:
                case_video_path = root / f"source_{source_mode}.mp4"
                case_subtitle_path = root / f"source_{source_mode}.srt"
                case_video_path.write_bytes(f"repeated caption video fixture {source_mode} ".encode("utf-8") + os.urandom(16))
                case_subtitle_path.write_text(repeated_caption_srt, encoding="utf-8")
                source_info = {
                    "title": f"Repeated captions {source_mode}",
                    "video_path": str(case_video_path),
                    "subtitle_path": str(case_subtitle_path),
                    "download_mode": "video",
                    "transcript_only": False,
                    "skip_video_slicing": False,
                }
                project = {
                    "id": f"repeated-caption-{source_mode}",
                    "title": f"repeated caption {source_mode}",
                    "source_mode": source_mode,
                    "video_path": str(case_video_path),
                    "subtitle_path": str(case_subtitle_path),
                    "language": "English",
                    "level": "B1",
                    "template_id": "immersive_v11",
                    "skip_video_slicing": source_mode == "url",
                    "api_config": {
                        "provider": "local",
                        "tts_config": {
                            "enabled": True,
                            "provider": "openai-compatible",
                            "base_url": "https://api.example.com/v1",
                            "api_key": "sk-test",
                            "model": "tts-test",
                            "voice": "alloy",
                        },
                    },
                    "segments": [
                        {
                            "id": f"seg_repeated_{source_mode}",
                            "start": 10.0,
                            "end": 12.2,
                            "source_time": "00:00:10.000 - 00:00:12.200",
                            "full_source_sentence": "go go go go now",
                            "text": "go go go go now",
                            "source_sentence_quality_flags": ["clean"],
                            "source_sentence_quality_status": "clean",
                            "cards": [
                                {
                                    "id": f"card_repeated_{source_mode}",
                                    "type": "phrase",
                                    "type_label": "表达",
                                    "enabled": True,
                                    "english": "go go go go now",
                                    "phrase": "go go now",
                                    "answer_core": "go go now",
                                    "chinese": "现在就行动。",
                                    "definition": "A repeated call to start moving or acting immediately.",
                                    "context": "go go go go now",
                                    "teacher_note": "Listen for repeated words without losing the final cue.",
                                }
                            ],
                        }
                    ],
                }
                if source_mode == "url":
                    project.update(
                        {
                            "source_url": "https://example.com/repeated-caption-video",
                            "url_import_mode": "video",
                            "source_info": {
                                **source_info,
                                "url": "https://example.com/repeated-caption-video",
                            },
                        }
                    )
                else:
                    project["source_info"] = {**source_info, "subtitle_source": "manual"}
                return project

            try:
                worker._legacy_worker.try_run_ffmpeg = fake_try_run_ffmpeg
                worker._legacy_worker.synthesize_tts = fake_synthesize_tts
                verify_apkg.ffprobe_video = fake_ffprobe_video
                os.chdir(root)
                for source_mode in ["local", "url"]:
                    with self.subTest(source_mode=source_mode):
                        output_dir = root / f"out_{source_mode}"
                        output_dir.mkdir()
                        project = repeated_caption_project(source_mode)
                        expected_subtitle_path = Path(project["subtitle_path"])
                        expected_video_path = Path(project["video_path"])
                        expected_video_fingerprint = worker.file_fingerprint(expected_video_path)
                        expected_subtitle_fingerprint = worker.file_fingerprint(expected_subtitle_path)
                        result = worker.handle_export(
                            {"project": project, "output_dir": str(output_dir)}
                        )

                        self.assertEqual(result["deck_kind"], "video_language")
                        self.assertTrue(Path(result["apkg_path"]).exists())
                        self.assertEqual(result["media_summary"]["video_segments"], 1)
                        self.assertGreaterEqual(result["media_summary"]["video_files"], 1)
                        self.assertEqual(result["media_summary"]["original_audio_files"], 1)
                        self.assertEqual(result["media_summary"]["sentence_tts_files"], 1)
                        self.assertEqual(result["media_summary"]["phrase_tts_files"], 1)
                        self.assertEqual(result["media_summary"]["card_media_ledger_items"], 1)
                        self.assertEqual(result["media_summary"]["subtitle_diagnostic_status"], "loaded")
                        self.assertEqual(str(Path(result["media_summary"]["subtitle_path"])), str(expected_subtitle_path))
                        self.assertEqual(result["source_identity"]["source_mode"], source_mode)
                        self.assertEqual(
                            result["source_identity"]["source_video_fingerprint"],
                            expected_video_fingerprint,
                        )
                        self.assertEqual(
                            result["source_identity"]["source_subtitle_fingerprint"],
                            expected_subtitle_fingerprint,
                        )
                        alignment_summary = result["media_summary"]["media_subtitle_alignment"]
                        self.assertEqual(alignment_summary["matched"], 1)
                        self.assertEqual(alignment_summary["partial"], 0)
                        self.assertEqual(alignment_summary["mismatch"], 0)
                        self.assertEqual(alignment_summary["unknown"], 0)
                        self.assertEqual(len(result["card_media_ledger"]), 1)
                        self.assertEqual(len(result["audio_audit_items"]), 1)
                        self.assertEqual(result["audio_audit_summary"]["items"], 1)
                        self.assertEqual(result["audio_audit_summary"]["expected_items"], 1)
                        self.assertEqual(result["audio_audit_summary"]["media_subtitle_alignment"], alignment_summary)

                        card_media = result["card_media_ledger"][0]
                        audit_by_card_id = {item["card_id"]: item for item in result["audio_audit_items"]}
                        audit_item = audit_by_card_id[card_media["card_id"]]
                        self.assertEqual(audit_item["segment_id"], card_media["segment_id"])
                        for item in [card_media, audit_item]:
                            self.assertEqual(item["source_mode"], source_mode)
                            self.assertEqual(str(Path(item["source_video_path"])), str(expected_video_path))
                            self.assertEqual(item["source_video_fingerprint"], expected_video_fingerprint)
                            self.assertEqual(str(Path(item["source_subtitle_path"])), str(expected_subtitle_path))
                            self.assertEqual(item["source_subtitle_fingerprint"], expected_subtitle_fingerprint)
                            self.assertEqual(item["source_subtitle_status"], "loaded")
                            self.assertEqual(item["media_subtitle_alignment_status"], "matched")
                            self.assertGreaterEqual(item["media_subtitle_overlap_score"], 0.68)
                            self.assertEqual(str(Path(item["subtitle_path"])), str(expected_subtitle_path))
                            self.assertIn("go go go go", item["media_window_subtitle_text"])
                            self.assertIn("go go now", item["media_window_subtitle_text"])
                            self.assertLessEqual(item["media_start"], 10.0)
                            self.assertGreaterEqual(item["media_end"], 12.2)
                            self.assertEqual(item["media_alignment_status"], "source_sentence_window")
                            self.assertEqual(item["media_alignment_text"], "go go go go now")
                            self.assertEqual(item["card_display_sentence"], "go go go go now")
                        self.assertEqual(audit_item["media_start"], card_media["media_start"])
                        self.assertEqual(audit_item["media_end"], card_media["media_end"])
                        self.assertEqual(audit_item["media_alignment_score"], card_media["media_subtitle_overlap_score"])
                        self.assertTrue(card_media["video_mp4"])
                        self.assertTrue(card_media["video_webm"])
                        self.assertTrue(card_media["original_audio"])
                        self.assertTrue(card_media["sentence_tts_audio"])
                        self.assertTrue(card_media["phrase_tts_audio"])
                        for file_name in [
                            card_media["video_mp4"],
                            card_media["original_audio"],
                            card_media["sentence_tts_audio"],
                            card_media["phrase_tts_audio"],
                        ]:
                            manifest_entry = result["media_manifest"][file_name]
                            self.assertEqual(manifest_entry["source_video_fingerprint"], expected_video_fingerprint)
                            self.assertEqual(manifest_entry["source_subtitle_fingerprint"], expected_subtitle_fingerprint)

                        report = verify_apkg.sqlite_fallback_report(Path(result["apkg_path"]))
                        self.assertTrue(report["ok"], report["failed_checks"])
                        self.assertEqual(report["failed_checks"], [])
                        self.assertEqual(report["note_count"], result["cards"])
                        self.assertEqual(report["card_count"], result["cards"])
                        self.assertEqual(set(report["media_files"]), set(result["media_manifest"]))

                        self.assertEqual(report["missing_archive_media"], [])
                        self.assertEqual(report["invalid_archive_media"], [])
                        self.assertEqual(report["missing_referenced_media"], [])
                        self.assertEqual(report["unreferenced_media"], [])

                        self.assertTrue(report["has_video_html_field"])
                        self.assertTrue(report["has_mp4_video_source"])
                        self.assertTrue(report["has_webm_video_source"])
                        self.assertTrue(report["has_poster_html_field"])
                        self.assertTrue(report["has_audio_html_field"])
                        self.assertEqual(report["empty_required_text_fields"], [])
                        self.assertEqual(report["tts_text_hash_mismatches"], [])
                        self.assertEqual(report["phrase_tts_text_hash_mismatches"], [])
            finally:
                os.chdir(original_cwd)
                worker._legacy_worker.try_run_ffmpeg = original_try_run_ffmpeg
                worker._legacy_worker.synthesize_tts = original_synthesize_tts
                verify_apkg.ffprobe_video = original_ffprobe_video

    def test_export_blocks_video_package_when_media_subtitle_alignment_mismatches(self):
        try:
            import genanki  # noqa: F401
        except ImportError:
            self.skipTest("genanki is required for export smoke")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "out"
            output_dir.mkdir()
            video_path = root / "source.mp4"
            subtitle_path = root / "source.srt"
            video_path.write_bytes(b"fake video bytes")
            subtitle_path.write_text(
                "\n".join(
                    [
                        "1",
                        "00:00:10,000 --> 00:00:13,000",
                        "This is unrelated visual text.",
                        "",
                        "2",
                        "00:00:13,000 --> 00:00:16,000",
                        "Still unrelated captions on screen.",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            project = {
                "id": "media-subtitle-mismatch",
                "title": "media subtitle mismatch",
                "source_mode": "local",
                "video_path": str(video_path),
                "subtitle_path": str(subtitle_path),
                "language": "English",
                "level": "B1",
                "template_id": "immersive_v11",
                "skip_video_slicing": False,
                "api_config": {"provider": "local", "tts_config": {"enabled": False, "provider": "disabled"}},
                "segments": [
                    {
                        "id": "seg_perspective",
                        "start": 10.0,
                        "end": 16.0,
                        "source_time": "00:00:10.000 - 00:00:16.000",
                        "full_source_sentence": "Today we need to build your perspective on the world before moving on.",
                        "text": "Today we need to build your perspective on the world before moving on.",
                        "cards": [
                            {
                                "id": "seg_perspective_card",
                                "learning_point_id": "lp-perspective",
                                "type": "phrase",
                                "type_label": "表达",
                                "enabled": True,
                                "english": "Today we need to build your perspective on the world before moving on.",
                                "phrase": "build your perspective",
                                "answer_core": "build your perspective",
                                "definition": "Develop the way you understand something.",
                                "teacher_note": "Use it for viewpoints or worldview.",
                            }
                        ],
                    }
                ],
            }

            original_try_run_ffmpeg = worker._legacy_worker.try_run_ffmpeg
            original_synthesize_tts = worker._legacy_worker.synthesize_tts
            stderr = io.StringIO()
            try:
                worker._legacy_worker.try_run_ffmpeg = lambda *args, **kwargs: self.fail(
                    "ffmpeg should not run when media/subtitle alignment is already mismatched"
                )
                worker._legacy_worker.synthesize_tts = lambda *args, **kwargs: self.fail(
                    "TTS should not run when media/subtitle alignment is already mismatched"
                )
                with redirect_stderr(stderr), self.assertRaises(SystemExit):
                    worker.handle_export({"project": project, "output_dir": str(output_dir)})
            finally:
                worker._legacy_worker.try_run_ffmpeg = original_try_run_ffmpeg
                worker._legacy_worker.synthesize_tts = original_synthesize_tts

            error_line = next(
                line for line in stderr.getvalue().splitlines() if line.startswith("__ANKI_CARD_ERROR__")
            )
            payload = json.loads(error_line.removeprefix("__ANKI_CARD_ERROR__"))
            self.assertEqual(payload["error_code"], "MEDIA_SUBTITLE_ALIGNMENT_MISMATCH")
            self.assertEqual(payload["stage"], "media_alignment")
            self.assertFalse(payload["retryable"])
            self.assertEqual(payload["details"]["mismatch_count"], 1)
            item = payload["details"]["items"][0]
            self.assertEqual(item["segment_id"], "seg_perspective")
            self.assertEqual(item["learning_point_ids"], ["lp-perspective"])
            self.assertIn("build your perspective", item["expected_text"])
            self.assertIn("unrelated", item["media_window_subtitle_text"])
            self.assertFalse(any(output_dir.glob("*.apkg")))

    def test_export_blocks_video_package_when_media_subtitle_alignment_is_low_partial(self):
        try:
            import genanki  # noqa: F401
        except ImportError:
            self.skipTest("genanki is required for export smoke")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "out"
            output_dir.mkdir()
            video_path = root / "source.mp4"
            subtitle_path = root / "source.srt"
            video_path.write_bytes(b"fake video bytes")
            subtitle_path.write_text(
                "\n".join(
                    [
                        "1",
                        "00:00:10,000 --> 00:00:16,000",
                        "Today we need to build unrelated filler words now.",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            project = {
                "id": "media-subtitle-low-partial",
                "title": "media subtitle low partial",
                "source_mode": "local",
                "video_path": str(video_path),
                "subtitle_path": str(subtitle_path),
                "language": "English",
                "level": "B1",
                "template_id": "immersive_v11",
                "skip_video_slicing": False,
                "api_config": {"provider": "local", "tts_config": {"enabled": False, "provider": "disabled"}},
                "segments": [
                    {
                        "id": "seg_perspective",
                        "start": 10.0,
                        "end": 16.0,
                        "source_time": "00:00:10.000 - 00:00:16.000",
                        "full_source_sentence": "Today we need to build your perspective on the world before moving on.",
                        "text": "Today we need to build your perspective on the world before moving on.",
                        "cards": [
                            {
                                "id": "seg_perspective_card",
                                "learning_point_id": "lp-perspective",
                                "type": "phrase",
                                "type_label": "表达",
                                "enabled": True,
                                "english": "Today we need to build your perspective on the world before moving on.",
                                "phrase": "build your perspective",
                                "answer_core": "build your perspective",
                                "definition": "Develop the way you understand something.",
                                "teacher_note": "Use it for viewpoints or worldview.",
                            }
                        ],
                    }
                ],
            }

            original_try_run_ffmpeg = worker._legacy_worker.try_run_ffmpeg
            original_synthesize_tts = worker._legacy_worker.synthesize_tts
            stderr = io.StringIO()
            try:
                worker._legacy_worker.try_run_ffmpeg = lambda *args, **kwargs: self.fail(
                    "ffmpeg should not run when media/subtitle alignment is low-confidence partial"
                )
                worker._legacy_worker.synthesize_tts = lambda *args, **kwargs: self.fail(
                    "TTS should not run when media/subtitle alignment is low-confidence partial"
                )
                with redirect_stderr(stderr), self.assertRaises(SystemExit):
                    worker.handle_export({"project": project, "output_dir": str(output_dir)})
            finally:
                worker._legacy_worker.try_run_ffmpeg = original_try_run_ffmpeg
                worker._legacy_worker.synthesize_tts = original_synthesize_tts

            error_line = next(
                line for line in stderr.getvalue().splitlines() if line.startswith("__ANKI_CARD_ERROR__")
            )
            payload = json.loads(error_line.removeprefix("__ANKI_CARD_ERROR__"))
            self.assertEqual(payload["error_code"], "MEDIA_SUBTITLE_ALIGNMENT_MISMATCH")
            item = payload["details"]["items"][0]
            self.assertEqual(item["media_subtitle_alignment_status"], "partial")
            self.assertLess(item["media_subtitle_overlap_score"], worker.MEDIA_SUBTITLE_PARTIAL_EXPORT_BLOCK_THRESHOLD)
            self.assertEqual(item["media_subtitle_alignment_reason"], "partial_overlap_below_export_threshold")
            self.assertFalse(any(output_dir.glob("*.apkg")))

    def test_export_retries_failed_tts_once_serially_before_blocking_apkg(self):
        try:
            import genanki  # noqa: F401
        except ImportError:
            self.skipTest("genanki is required for export smoke")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "out"
            output_dir.mkdir()
            project = {
                "id": "tts-retry-export",
                "title": "tts retry export",
                "source_mode": "local",
                "video_path": "",
                "subtitle_path": "",
                "language": "English",
                "level": "B1",
                "template_id": "immersive_v11",
                "skip_video_slicing": True,
                "api_config": {
                    "provider": "local",
                    "tts_config": {
                        "enabled": True,
                        "provider": "openai-compatible",
                        "base_url": "https://api.example.com/v1",
                        "api_key": "sk-test",
                        "model": "tts-test",
                        "voice": "alloy",
                        "language": "en-US",
                    },
                },
                "segments": [
                    {
                        "id": "seg_retry",
                        "start": 1,
                        "end": 4,
                        "source_time": "00:00:01.000 - 00:00:04.000",
                        "text": "These are the things that these guys are missing out on.",
                        "cards": [
                            {
                                "id": "card_retry",
                                "type": "phrase",
                                "enabled": True,
                                "english": "These are the things that these guys are missing out on.",
                                "chinese": "这些就是他们错过的东西。",
                                "phrase": "missing out on",
                                "answer_core": "missing out on",
                                "definition": "fail to experience or get something useful",
                                "context": "A speaker explains what someone lacks.",
                                "teacher_note": "常见口语表达，后面可接机会、经历或信息。",
                                "pronunciation_meta": {},
                            }
                        ],
                    }
                ],
            }
            original_synthesize_tts = worker._legacy_worker.synthesize_tts
            original_cwd = os.getcwd()
            calls: list[tuple[str, str | None]] = []

            def fake_synthesize_tts(project_arg, segment_arg, output_path, text_override=None, tts_kind="sentence"):
                calls.append((tts_kind, text_override))
                if tts_kind == "sentence" and len([call for call in calls if call[0] == "sentence"]) == 1:
                    raise RuntimeError("Gemini Vertex TTS 请求失败：API HTTP 400 INVALID_ARGUMENT")
                Path(output_path).write_bytes(b"ID3" + b"\x00" * 8192)
                return True

            try:
                os.chdir(root)
                worker._legacy_worker.synthesize_tts = fake_synthesize_tts
                result = worker.handle_export({"project": project, "output_dir": str(output_dir)})
            finally:
                worker._legacy_worker.synthesize_tts = original_synthesize_tts
                os.chdir(original_cwd)

            self.assertTrue(Path(result["apkg_path"]).exists())
            self.assertEqual(result["media_summary"]["sentence_tts_files"], 1)
            self.assertEqual(result["media_summary"]["phrase_tts_files"], 1)
            self.assertGreaterEqual(len([call for call in calls if call[0] == "sentence"]), 2)

    def test_export_returns_structured_missing_tts_media_error(self):
        try:
            import genanki  # noqa: F401
        except ImportError:
            self.skipTest("genanki is required for export smoke")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "out"
            output_dir.mkdir()
            project = {
                "id": "tts-missing-export",
                "title": "tts missing export",
                "source_mode": "local",
                "video_path": "",
                "subtitle_path": "",
                "language": "English",
                "level": "B1",
                "template_id": "immersive_v11",
                "skip_video_slicing": True,
                "api_config": {
                    "provider": "local",
                    "tts_config": {
                        "enabled": True,
                        "provider": "openai-compatible",
                        "base_url": "https://api.example.com/v1",
                        "api_key": "sk-test",
                        "model": "tts-test",
                        "voice": "alloy",
                        "language": "en-US",
                    },
                },
                "segments": [
                    {
                        "id": "seg_missing",
                        "start": 1,
                        "end": 4,
                        "source_time": "00:00:01.000 - 00:00:04.000",
                        "text": "You get to go, that idea is old to me.",
                        "cards": [
                            {
                                "id": "card_missing",
                                "type": "phrase",
                                "enabled": True,
                                "english": "You get to go, that idea is old to me.",
                                "chinese": "你会发现这个想法对我来说已经旧了。",
                                "phrase": "old to me",
                                "answer_core": "old to me",
                                "definition": "no longer new to the speaker",
                                "context": "A speaker compares a past idea with a current view.",
                                "teacher_note": "用来表达某个想法已经不新鲜。",
                                "pronunciation_meta": {},
                            }
                        ],
                    }
                ],
            }
            original_synthesize_tts = worker._legacy_worker.synthesize_tts
            original_cwd = os.getcwd()

            def fake_synthesize_tts(project_arg, segment_arg, output_path, text_override=None, tts_kind="sentence"):
                if tts_kind == "sentence":
                    raise RuntimeError("Gemini Vertex TTS 请求失败：API HTTP 400 INVALID_ARGUMENT")
                Path(output_path).write_bytes(b"ID3" + b"\x00" * 8192)
                return True

            stderr = io.StringIO()
            try:
                os.chdir(root)
                worker._legacy_worker.synthesize_tts = fake_synthesize_tts
                with self.assertRaises(SystemExit):
                    with redirect_stderr(stderr):
                        worker.handle_export({"project": project, "output_dir": str(output_dir)})
            finally:
                worker._legacy_worker.synthesize_tts = original_synthesize_tts
                os.chdir(original_cwd)

            error_line = next(
                line for line in stderr.getvalue().splitlines() if line.startswith("__ANKI_CARD_ERROR__")
            )
            payload = json.loads(error_line.removeprefix("__ANKI_CARD_ERROR__"))
            self.assertEqual(payload["error_code"], "MISSING_TTS_MEDIA")
            self.assertEqual(payload["stage"], "tts")
            self.assertTrue(payload["retryable"])
            self.assertEqual(payload["details"]["tts_failure_count"], 1)
            self.assertEqual(payload["details"]["sentence_tts_generated"], 0)
            self.assertEqual(payload["details"]["sentence_tts_requested"], 1)
            self.assertEqual(payload["details"]["tts_failure_items"][0]["segment_id"], "seg_missing")
            self.assertEqual(payload["details"]["tts_failure_items"][0]["role"], "sentence_tts")
            self.assertIn("INVALID_ARGUMENT", payload["details"]["tts_failure_items"][0]["error"])

    def test_export_blocks_manual_tts_semantic_review_when_strict_export_required(self):
        try:
            import genanki  # noqa: F401
        except ImportError:
            self.skipTest("genanki is required for export smoke")

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            output_dir.mkdir()
            project = {
                "id": "tts-strict-manual-review",
                "title": "tts strict manual review",
                "source_mode": "local",
                "video_path": "",
                "subtitle_path": "",
                "language": "English",
                "level": "B1",
                "template_id": "immersive_v11",
                "skip_video_slicing": True,
                "tts_semantic_verification": {
                    "enabled": True,
                    "require_pass_for_export": True,
                },
                "api_config": {
                    "provider": "local",
                    "tts_config": {
                        "enabled": True,
                        "provider": "openai-compatible",
                        "base_url": "https://api.example.com/v1",
                        "api_key": "sk-test",
                        "model": "tts-strict-test",
                        "voice": "alloy",
                        "language": "en-US",
                    },
                },
                "segments": [
                    {
                        "id": "seg_strict",
                        "start": 0,
                        "end": 2,
                        "source_time": "00:00:00.000 - 00:00:02.000",
                        "text": "Strict export should not accept unverified audio.",
                        "cards": [
                            {
                                "id": "card_strict",
                                "type": "phrase",
                                "type_label": "表达卡",
                                "enabled": True,
                                "english": "Strict export should not accept unverified audio.",
                                "chinese": "严格导出不接受未核验音频。",
                                "phrase": "unverified audio",
                                "answer_core": "unverified audio",
                                "definition": "Audio whose content has not been proven by ASR.",
                                "teacher_note": "This test keeps the semantic status in manual review.",
                            }
                        ],
                    }
                ],
            }
            original_synthesize_tts = worker._legacy_worker.synthesize_tts
            stderr = io.StringIO()

            def fake_synthesize_tts(project_arg, segment_arg, output_path, text_override=None, tts_kind="sentence"):
                Path(output_path).write_bytes(b"ID3" + b"\x00" * 8192)
                return True

            try:
                worker._legacy_worker.synthesize_tts = fake_synthesize_tts
                with redirect_stderr(stderr), self.assertRaises(SystemExit):
                    worker.handle_export({"project": project, "output_dir": str(output_dir)})
            finally:
                worker._legacy_worker.synthesize_tts = original_synthesize_tts

            self.assertIn("TTS 语义未能自动证明", stderr.getvalue())
            self.assertIn("TTS_SEMANTIC_UNVERIFIED", stderr.getvalue())
            self.assertFalse(any(output_dir.rglob("*.apkg")))

    def test_video_language_export_does_not_require_tts_semantic_pass_by_default(self):
        self.assertFalse(
            worker._legacy_worker.tts_semantic_requires_export_pass(
                {"source_mode": "local", "template_id": "immersive_v11"},
                "video_language",
            )
        )
        self.assertTrue(
            worker._legacy_worker.tts_semantic_requires_export_pass(
                {
                    "source_mode": "local",
                    "template_id": "immersive_v11",
                    "tts_semantic_verification": {"enabled": True, "require_pass_for_export": True},
                },
                "video_language",
            )
        )
        self.assertFalse(
            worker._legacy_worker.tts_semantic_requires_export_pass(
                {"source_mode": "local", "template_id": "immersive_v11"},
                "subtitle_language",
            )
        )

    def test_tts_semantic_match_ignores_subtitle_sound_effect_tags(self):
        matched, expected_norm, actual_norm = worker._legacy_worker.tts_semantic_matches(
            "[laughter] [laughter] Nobody say Sam in the comments.",
            "Nobody say Sam in the comments.",
            role="sentence_tts",
        )

        self.assertTrue(matched)
        self.assertEqual(expected_norm, "nobody say sam in the comments")
        self.assertEqual(actual_norm, "nobody say sam in the comments")

    def test_tts_semantic_sentence_match_allows_minor_asr_inflection(self):
        matched, expected_norm, actual_norm = worker._legacy_worker.tts_semantic_matches(
            "[laughter] Nobody say Sam in the comments.",
            "Nobody says Sam in the comments.",
            role="sentence_tts",
        )

        self.assertTrue(matched)
        self.assertEqual(expected_norm, "nobody say sam in the comments")
        self.assertEqual(actual_norm, "nobody says sam in the comments")

    def test_export_flags_high_risk_short_phrase_tts_for_manual_review(self):
        try:
            import genanki  # noqa: F401
        except ImportError:
            self.skipTest("genanki is required for export smoke")

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            output_dir.mkdir()
            project = {
                "id": "tts-high-risk-prompt",
                "title": "tts high risk prompt",
                "source_mode": "local",
                "video_path": "",
                "subtitle_path": "",
                "language": "English",
                "level": "B1",
                "template_id": "immersive_v11",
                "skip_video_slicing": True,
                "tts_semantic_verification": {"enabled": True},
                "api_config": {
                    "provider": "local",
                    "tts_config": {
                        "enabled": True,
                        "provider": "openai-compatible",
                        "base_url": "https://api.example.com/v1",
                        "api_key": "sk-test",
                        "model": "tts-test",
                        "voice": "alloy",
                        "language": "en-US",
                    },
                },
                "segments": [
                    {
                        "id": "seg_prompt",
                        "start": 0,
                        "end": 2,
                        "source_time": "00:00:00.000 - 00:00:02.000",
                        "text": "Here is the prompt.",
                        "cards": [
                            {
                                "id": "seg_prompt_listening",
                                "type": "listening",
                                "type_label": "听力卡",
                                "enabled": True,
                                "english": "Here is the prompt.",
                                "chinese": "这是提示词。",
                                "phrase": "prompt",
                                "answer_core": "prompt",
                                "definition": "a short instruction",
                                "teacher_note": "短词必须人工抽听。",
                            }
                        ],
                    }
                ],
            }
            original_synthesize_tts = worker._legacy_worker.synthesize_tts

            def fake_synthesize_tts(project_arg, segment_arg, output_path, text_override=None, tts_kind="sentence"):
                Path(output_path).write_bytes(b"ID3" + b"\x00" * 8192)
                return True

            try:
                worker._legacy_worker.synthesize_tts = fake_synthesize_tts
                result = worker.handle_export({"project": project, "output_dir": str(output_dir)})
            finally:
                worker._legacy_worker.synthesize_tts = original_synthesize_tts

            manual_phrase_items = [
                item for item in result["tts_manual_review_items"] if item["role"] == "phrase_tts"
            ]
            self.assertEqual(len(manual_phrase_items), 1)
            self.assertEqual(manual_phrase_items[0]["tts_text"], "prompt")
            self.assertIn("high_risk_short_expression", manual_phrase_items[0]["semantic_review_reasons"])
            self.assertIn("short_expression", manual_phrase_items[0]["semantic_review_reasons"])
            self.assertEqual(result["media_summary"]["tts_high_risk_manual_review_items"], 1)
            self.assertEqual(result["tts_semantic_verification"]["high_risk_items"], 1)

    def test_export_records_passed_tts_semantic_verification_when_asr_matches(self):
        try:
            import genanki  # noqa: F401
        except ImportError:
            self.skipTest("genanki is required for export smoke")

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            output_dir.mkdir()
            sentence = "The semantic firewall reads this sentence."
            phrase = "semantic firewall"
            project = {
                "id": "tts-semantic-pass",
                "title": "tts semantic pass",
                "source_mode": "local",
                "video_path": "",
                "subtitle_path": "",
                "language": "English",
                "level": "B1",
                "template_id": "immersive_v11",
                "skip_video_slicing": True,
                "tts_semantic_verification": {"enabled": True, "require_pass_for_export": True},
                "api_config": {
                    "provider": "local",
                    "tts_config": {
                        "enabled": True,
                        "provider": "openai-compatible",
                        "base_url": "https://api.example.com/v1",
                        "api_key": "sk-test",
                        "model": "tts-semantic-pass-test",
                        "voice": "semantic-pass-voice",
                        "language": "en-US",
                    },
                },
                "segments": [
                    {
                        "id": "seg_semantic_pass",
                        "start": 0,
                        "end": 2,
                        "source_time": "00:00:00.000 - 00:00:02.000",
                        "text": sentence,
                        "cards": [
                            {
                                "id": "card_semantic_pass",
                                "type": "phrase",
                                "enabled": True,
                                "english": sentence,
                                "chinese": "语义防火墙",
                                "phrase": phrase,
                                "answer_core": phrase,
                                "definition": "A phrase used in this regression test.",
                                "teacher_note": "ASR transcript matches the intended phrase.",
                            }
                        ],
                    }
                ],
            }
            original_call_tts_audio = worker._legacy_worker.call_tts_audio
            original_apply_tts_output_volume = worker._legacy_worker.apply_tts_output_volume
            original_transcribe_tts_audio = worker._legacy_worker.transcribe_tts_audio

            def fake_call_tts_audio(*_args, **_kwargs):
                return b"ID3" + b"\x00" * 8192

            def fake_transcribe_tts_audio(audio_path, *, project, expected_text, role):
                return {
                    "ok": True,
                    "provider": "fake-asr",
                    "transcript": expected_text,
                }

            try:
                worker._legacy_worker.call_tts_audio = fake_call_tts_audio
                worker._legacy_worker.apply_tts_output_volume = lambda *_args, **_kwargs: None
                worker._legacy_worker.transcribe_tts_audio = fake_transcribe_tts_audio
                result = worker.handle_export({"project": project, "output_dir": str(output_dir)})
            finally:
                worker._legacy_worker.call_tts_audio = original_call_tts_audio
                worker._legacy_worker.apply_tts_output_volume = original_apply_tts_output_volume
                worker._legacy_worker.transcribe_tts_audio = original_transcribe_tts_audio

            self.assertTrue(Path(result["apkg_path"]).exists())
            self.assertEqual(result["tts_manual_review_items"], [])
            self.assertEqual(result["tts_semantic_failures"], [])
            self.assertEqual(result["tts_semantic_verification"]["status"], "passed")
            self.assertEqual(result["tts_semantic_verification"]["passed"], 2)
            self.assertEqual(result["media_summary"]["tts_semantic_passed_items"], 2)
            tts_entries = [
                item for item in result["media_ledger"] if item["role"] in {"sentence_tts", "phrase_tts"}
            ]
            self.assertEqual({item["semantic_verification"] for item in tts_entries}, {"passed"})
            self.assertEqual(result["card_media_ledger"][0]["phrase_tts_semantic_verification"], "passed")

    def test_export_fails_on_phrase_tts_semantic_mismatch(self):
        try:
            import genanki  # noqa: F401
        except ImportError:
            self.skipTest("genanki is required for export smoke")

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            output_dir.mkdir()
            sentence = "Here is the checksum sentinel."
            phrase = "checksum sentinel"
            project = {
                "id": "tts-semantic-mismatch",
                "title": "tts semantic mismatch",
                "source_mode": "local",
                "video_path": "",
                "subtitle_path": "",
                "language": "English",
                "level": "B1",
                "template_id": "immersive_v11",
                "skip_video_slicing": True,
                "tts_semantic_verification": {
                    "enabled": True,
                    "require_pass_for_export": True,
                },
                "api_config": {
                    "provider": "local",
                    "tts_config": {
                        "enabled": True,
                        "provider": "openai-compatible",
                        "base_url": "https://api.example.com/v1",
                        "api_key": "sk-test",
                        "model": "tts-semantic-mismatch-test",
                        "voice": "semantic-mismatch-voice",
                        "language": "en-US",
                    },
                },
                "segments": [
                    {
                        "id": "seg_semantic_mismatch",
                        "start": 0,
                        "end": 2,
                        "source_time": "00:00:00.000 - 00:00:02.000",
                        "text": sentence,
                        "cards": [
                            {
                                "id": "card_semantic_mismatch",
                                "type": "phrase",
                                "enabled": True,
                                "english": sentence,
                                "chinese": "校验哨兵",
                                "phrase": phrase,
                                "answer_core": phrase,
                                "definition": "A phrase used in this regression test.",
                                "teacher_note": "ASR transcript intentionally mismatches the phrase.",
                            }
                        ],
                    }
                ],
            }
            original_call_tts_audio = worker._legacy_worker.call_tts_audio
            original_apply_tts_output_volume = worker._legacy_worker.apply_tts_output_volume
            original_transcribe_tts_audio = worker._legacy_worker.transcribe_tts_audio
            stderr = io.StringIO()

            def fake_call_tts_audio(*_args, **_kwargs):
                return b"ID3" + b"\x00" * 8192

            def fake_transcribe_tts_audio(audio_path, *, project, expected_text, role):
                transcript = expected_text if role == "sentence_tts" else "the model explained a different word"
                return {
                    "ok": True,
                    "provider": "fake-asr",
                    "transcript": transcript,
                }

            try:
                worker._legacy_worker.call_tts_audio = fake_call_tts_audio
                worker._legacy_worker.apply_tts_output_volume = lambda *_args, **_kwargs: None
                worker._legacy_worker.transcribe_tts_audio = fake_transcribe_tts_audio
                with redirect_stderr(stderr), self.assertRaises(SystemExit):
                    worker.handle_export({"project": project, "output_dir": str(output_dir)})
            finally:
                worker._legacy_worker.call_tts_audio = original_call_tts_audio
                worker._legacy_worker.apply_tts_output_volume = original_apply_tts_output_volume
                worker._legacy_worker.transcribe_tts_audio = original_transcribe_tts_audio

            self.assertIn("TTS 语义核验失败", stderr.getvalue())
            self.assertFalse(any(output_dir.rglob("*.apkg")))

    def test_export_tts_uses_bounded_concurrency(self):
        try:
            import genanki  # noqa: F401
        except ImportError:
            self.skipTest("genanki is required for export smoke")

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            output_dir.mkdir()
            segments = []
            for index in range(3):
                phrase = f"phrase {index}"
                segments.append(
                    {
                        "id": f"seg_{index}",
                        "start": index * 2,
                        "end": index * 2 + 1,
                        "source_time": f"00:00:0{index}.000 - 00:00:0{index + 1}.000",
                        "text": f"They say {phrase} in this line.",
                        "cards": [
                            {
                                "id": f"card_{index}",
                                "type": "expression",
                                "type_label": "表达卡",
                                "enabled": True,
                                "english": f"They say {phrase} in this line.",
                                "chinese": "这句话在训练一个表达。",
                                "phrase": phrase,
                                "answer_core": phrase,
                                "definition": "一个可练习的表达。",
                                "teacher_note": "关注表达在原句中的用法。",
                                "context": "来自测试字幕。",
                            }
                        ],
                    }
                )
            project = {
                "id": "tts-concurrency",
                "title": "tts concurrency",
                "source_mode": "local",
                "video_path": "",
                "subtitle_path": "",
                "language": "English",
                "level": "B1",
                "template_id": "immersive_v11",
                "skip_video_slicing": True,
                "tts_concurrency": 2,
                "api_config": {
                    "provider": "local",
                    "tts_config": {
                        "enabled": True,
                        "provider": "openai-compatible",
                        "base_url": "https://api.example.com/v1",
                        "api_key": "sk-test",
                        "model": "tts-test",
                        "voice": "alloy",
                        "language": "en-US",
                        "sample_rate": 24000,
                        "bit_rate": 128000,
                    },
                },
                "segments": segments,
            }
            active = 0
            max_active = 0
            lock = threading.Lock()
            original_synthesize_tts = worker._legacy_worker.synthesize_tts

            def fake_synthesize_tts(project_arg, segment_arg, output_path, text_override=None, tts_kind="sentence"):
                nonlocal active, max_active
                with lock:
                    active += 1
                    max_active = max(max_active, active)
                try:
                    time.sleep(0.05)
                    Path(output_path).write_bytes(b"ID3" + b"\x00" * 8192)
                    return {"ok": True, "cache_hit": False}
                finally:
                    with lock:
                        active -= 1

            try:
                worker._legacy_worker.synthesize_tts = fake_synthesize_tts
                result = worker.handle_export({"project": project, "output_dir": str(output_dir)})
            finally:
                worker._legacy_worker.synthesize_tts = original_synthesize_tts

            self.assertTrue(Path(result["apkg_path"]).exists())
            self.assertEqual(result["media_summary"]["tts_concurrency"], 2)
            self.assertEqual(result["media_summary"]["sentence_tts_requested"], 3)
            self.assertEqual(result["media_summary"]["phrase_tts_requested"], 3)
            self.assertEqual(result["media_summary"]["sentence_tts_files"], 3)
            self.assertEqual(result["media_summary"]["phrase_tts_files"], 3)
            self.assertEqual(result["media_summary"]["tts_cache_hits"], 0)
            self.assertEqual(result["media_summary"]["tts_cache_misses"], 6)
            self.assertEqual(result["media_summary"]["tts_cache_total"], 6)
            self.assertEqual(result["media_summary"]["media_cache_hits"], 0)
            self.assertEqual(result["media_summary"]["media_cache_misses"], 0)
            self.assertEqual(result["media_summary"]["media_cache_total"], 0)
            self.assertGreaterEqual(max_active, 2)
            self.assertLessEqual(max_active, 2)
            report = verify_apkg.sqlite_fallback_report(Path(result["apkg_path"]))
            self.assertTrue(report["ok"], report)
            self.assertEqual(report["failed_checks"], [])
            self.assertEqual(report["note_model_contract_issues"], [])
            self.assertEqual(report["note_model_contracts"][0]["noteModelId"], 3157735470)
            self.assertEqual(report["empty_required_text_fields"], [])
            self.assertEqual(report["tts_text_hash_mismatches"], [])
            self.assertEqual(report["phrase_tts_text_hash_mismatches"], [])

    def test_export_fails_when_enabled_tts_media_is_missing(self):
        try:
            import genanki  # noqa: F401
        except ImportError:
            self.skipTest("genanki is required for export smoke")

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            output_dir.mkdir()
            project = {
                "id": "missing-tts-media",
                "title": "missing tts media",
                "source_mode": "local",
                "video_path": "",
                "subtitle_path": "",
                "language": "English",
                "level": "B1",
                "template_id": "immersive_v11",
                "skip_video_slicing": True,
                "api_config": {
                    "provider": "local",
                    "tts_config": {
                        "enabled": True,
                        "provider": "openai-compatible",
                        "base_url": "https://api.example.com/v1",
                        "api_key": "sk-test",
                        "model": "tts-test",
                        "voice": "alloy",
                    },
                },
                "segments": [
                    {
                        "id": "seg_1",
                        "start": 0,
                        "end": 2,
                        "source_time": "00:00:00.000 - 00:00:02.000",
                        "text": "Today I have a special guest.",
                        "cards": [
                            {
                                "id": "card_1",
                                "type": "phrase",
                                "enabled": True,
                                "english": "Today I have a special guest.",
                                "chinese": "特别嘉宾",
                                "phrase": "special guest",
                                "answer_core": "special guest",
                                "definition": "一个自然的介绍嘉宾表达。",
                                "teacher_note": "用于介绍受邀来宾。",
                            }
                        ],
                    }
                ],
            }
            original_synthesize_tts = worker._legacy_worker.synthesize_tts
            stderr = io.StringIO()

            try:
                worker._legacy_worker.synthesize_tts = lambda *args, **kwargs: False
                with redirect_stderr(stderr), self.assertRaises(SystemExit):
                    worker.handle_export({"project": project, "output_dir": str(output_dir)})
            finally:
                worker._legacy_worker.synthesize_tts = original_synthesize_tts

            message = stderr.getvalue()
            self.assertIn("TTS 生成失败", message)
            self.assertIn("MISSING_TTS_MEDIA", message)
            self.assertIn("避免生成缺 TTS 的视频卡", message)
            error_line = next(line for line in message.splitlines() if line.startswith("__ANKI_CARD_ERROR__"))
            payload = json.loads(error_line.removeprefix("__ANKI_CARD_ERROR__"))
            self.assertEqual(payload["details"]["tts_failure_count"], 2)
            self.assertEqual(payload["details"]["sentence_tts_generated"], 0)
            self.assertEqual(payload["details"]["phrase_tts_generated"], 0)
            self.assertFalse(any(output_dir.glob("*.apkg")))

    def test_export_blocks_video_language_cards_when_tts_disabled(self):
        try:
            import genanki  # noqa: F401
        except ImportError:
            self.skipTest("genanki is required for export smoke")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "out"
            video_path = root / "source.mp4"
            output_dir.mkdir()
            video_path.write_bytes(b"fake video bytes for fingerprint")
            project = {
                "id": "tts-disabled-video-language",
                "title": "tts disabled video language",
                "source_mode": "local",
                "video_path": str(video_path),
                "subtitle_path": "",
                "language": "English",
                "level": "B1",
                "template_id": "immersive_v11",
                "skip_video_slicing": False,
                "api_config": {"provider": "local", "tts_config": {"enabled": False, "provider": "disabled"}},
                "segments": [
                    {
                        "id": "seg_1",
                        "start": 0,
                        "end": 2,
                        "source_time": "00:00:00.000 - 00:00:02.000",
                        "text": "Today I have a special guest.",
                        "cards": [
                            {
                                "id": "card_1",
                                "type": "phrase",
                                "enabled": True,
                                "english": "Today I have a special guest.",
                                "chinese": "特别嘉宾",
                                "phrase": "special guest",
                                "answer_core": "special guest",
                                "definition": "一个自然的介绍嘉宾表达。",
                                "teacher_note": "用于介绍受邀来宾。",
                            }
                        ],
                    }
                ],
            }
            original_synthesize_tts = worker._legacy_worker.synthesize_tts
            original_try_run_ffmpeg = worker._legacy_worker.try_run_ffmpeg
            stderr = io.StringIO()

            def fake_try_run_ffmpeg(command):
                output_path = Path(command[-1])
                if output_path.suffix == ".mp4":
                    output_path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 8192)
                elif output_path.suffix == ".webm":
                    output_path.write_bytes(b"\x1a\x45\xdf\xa3" + b"\x00" * 8192)
                elif output_path.suffix == ".jpg":
                    output_path.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 8192)
                elif output_path.suffix == ".mp3":
                    output_path.write_bytes(b"ID3" + b"\x00" * 8192)
                else:
                    output_path.write_bytes(b"media")
                return ""

            try:
                worker._legacy_worker.try_run_ffmpeg = fake_try_run_ffmpeg
                worker._legacy_worker.synthesize_tts = lambda *args, **kwargs: self.fail(
                    "TTS synthesis should not run when TTS is disabled"
                )
                with redirect_stderr(stderr), self.assertRaises(SystemExit):
                    worker.handle_export({"project": project, "output_dir": str(output_dir)})
            finally:
                worker._legacy_worker.synthesize_tts = original_synthesize_tts
                worker._legacy_worker.try_run_ffmpeg = original_try_run_ffmpeg

            message = stderr.getvalue()
            self.assertIn("TTS 当前未启用", message)
            self.assertIn("MISSING_TTS_MEDIA", message)
            self.assertIn("必须包含整句 TTS 和表达 TTS", message)
            error_line = next(line for line in message.splitlines() if line.startswith("__ANKI_CARD_ERROR__"))
            payload = json.loads(error_line.removeprefix("__ANKI_CARD_ERROR__"))
            self.assertEqual(payload["error_code"], "MISSING_TTS_MEDIA")
            self.assertEqual(payload["details"]["sentence_tts_requested"], 1)
            self.assertEqual(payload["details"]["sentence_tts_generated"], 0)
            self.assertEqual(payload["details"]["phrase_tts_requested"], 1)
            self.assertEqual(payload["details"]["phrase_tts_generated"], 0)
            self.assertFalse(any(output_dir.glob("*.apkg")))

    def test_export_v14_required_fields_use_safe_fallbacks_after_generic_filter(self):
        try:
            import genanki  # noqa: F401
        except ImportError:
            self.skipTest("genanki is required for export smoke")

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            output_dir.mkdir()
            project = {
                "id": "v11-required-fallbacks",
                "title": "v11 required fallbacks",
                "source_mode": "local",
                "video_path": "",
                "subtitle_path": "",
                "language": "English",
                "level": "B1",
                "template_id": "immersive_v11",
                "skip_video_slicing": True,
                "segments": [
                    {
                        "id": "seg_1",
                        "start": 0,
                        "end": 1,
                        "source_time": "00:00:00.000 - 00:00:01.000",
                        "text": "Can you calibrate the nozzle before we start?",
                        "cards": [
                            {
                                "id": "card_1",
                                "type": "expression",
                                "type_label": "表达卡",
                                "enabled": True,
                                "english": "Can you calibrate the nozzle before we start?",
                                "chinese": "开始前你能校准一下喷嘴吗？",
                                "phrase": "calibrate the nozzle",
                                "answer_core": "calibrate the nozzle",
                                "exact_span": "calibrate the nozzle",
                                "exact_span_start": 8,
                                "exact_span_end": 28,
                                "example": "Please calibrate the nozzle now. / We calibrate the nozzle before each run.",
                                "definition": "很常见，先抓住表达再回看上下文。",
                                "how_to_use_it": "不要只背中文翻译。",
                                "teacher_note": "复习时先听语气。",
                                "usage_boundary": "注意语境。",
                                "context": "请求别人开始前校准设备。",
                            }
                        ],
                    }
                ],
            }

            result = worker.handle_export({"project": project, "output_dir": str(output_dir)})
            self.assertEqual(result["quality_audit"]["empty_required_fields"], 0)
            self.assertEqual(result["template_family"], "language-immersive-v11")
            self.assertEqual(result["template_schema"], "V14")
            self.assertEqual(result["template_version"], "V14")
            self.assertEqual(result["note_model_id"], 3157735470)
            self.assertEqual(result["model_name"], "Anki Card Generator V14 - 沉浸复读 V11")
            self.assertEqual(result["compatibility_contract_version"], 1)
            self.assertEqual(len(result["note_model_contract_digest"]), 64)
            self.assertEqual(result["presentation_warnings"], [])
            report = verify_apkg.sqlite_fallback_report(Path(result["apkg_path"]))
            self.assertTrue(report["ok"], report)
            self.assertEqual(report["failed_checks"], [])
            self.assertEqual(report["note_model_contract_issues"], [])
            self.assertEqual(report["note_model_contracts"][0]["noteModelId"], 3157735470)
            self.assertEqual(report["empty_required_text_fields"], [])

            import sqlite3
            import zipfile

            with tempfile.TemporaryDirectory() as unpacked:
                with zipfile.ZipFile(result["apkg_path"]) as package:
                    package.extract("collection.anki2", unpacked)
                con = sqlite3.connect(Path(unpacked) / "collection.anki2")
                try:
                    models = json.loads(con.execute("select models from col").fetchone()[0])
                    notes = verify_apkg.note_field_dicts(con, models)
                finally:
                    con.close()
            self.assertEqual(len(notes), 1)
            self.assertIn("calibrate the nozzle", verify_apkg.plain_field_text(notes[0]["Definition"]))
            self.assertIn("calibrate the nozzle", verify_apkg.plain_field_text(notes[0]["TeacherNote"]))
            self.assertNotIn("很常见", verify_apkg.plain_field_text(notes[0]["Definition"]))
            self.assertNotIn("注意语境", verify_apkg.plain_field_text(notes[0]["TeacherNote"]))
            self.assertEqual(notes[0]["English"], "Can you calibrate the nozzle before we start?")
            self.assertIn(
                '<mark class="target-expression">calibrate the nozzle</mark>',
                notes[0]["EnglishDisplay"],
            )
            self.assertIn(
                '<mark class="target-expression">calibrate the nozzle</mark>',
                notes[0]["DefinitionDisplay"],
            )
            self.assertIn(
                '<mark class="target-expression">calibrate the nozzle</mark>',
                notes[0]["TeacherNoteDisplay"],
            )
            self.assertIn('<ul class="v11-example-list">', notes[0]["TransferExamplesDisplay"])
            self.assertEqual(verify_apkg.plain_field_text(notes[0]["Example"]), "Please calibrate the nozzle now. / We calibrate the nozzle before each run.")

    def test_worker_fail_emits_machine_readable_error(self):
        from acg.protocol import ERROR_PREFIX, fail

        stderr = io.StringIO()
        with self.assertRaises(SystemExit):
            with redirect_stderr(stderr):
                fail(
                    "YouTube 限流。",
                    error_code="YOUTUBE_RATE_LIMIT",
                    stage="download_subtitles",
                    retryable=True,
                    fallbacks=["local_srt"],
                )

        first_line = stderr.getvalue().splitlines()[0]
        self.assertTrue(first_line.startswith(ERROR_PREFIX))
        payload = json.loads(first_line.removeprefix(ERROR_PREFIX))
        self.assertEqual(payload["schema_version"], 2)
        self.assertEqual(payload["message"], "YouTube 限流。")
        self.assertEqual(payload["error_code"], "YOUTUBE_RATE_LIMIT")
        self.assertEqual(payload["fallbacks"], ["local_srt"])

    def test_worker_protocol_adds_schema_version_to_success_payloads(self):
        from acg.protocol import with_schema_version

        payload = with_schema_version({"ok": True})

        self.assertEqual(payload["schema_version"], 2)
        self.assertTrue(payload["ok"])

    def test_document_reader_is_exposed_through_worker_router(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            document_path = Path(temp_dir) / "note.txt"
            document_path.write_text("Hello from a UTF-16 document.", encoding="utf-16")

            text = worker.read_document_source(str(document_path))

        self.assertIn("Hello from a UTF-16 document.", text)

    def test_document_chunking_prefers_markdown_sections(self):
        from acg.documents.chunking import split_document_chunks

        text = "\n\n".join(
            [
                "# First idea\nThis section explains a transferable idea with enough detail for a review card.",
                "# Second idea\nThis section explains another idea with examples, limits, and useful context.",
            ]
        )

        segments = split_document_chunks(text, 5)

        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0]["id"], "doc_0001")
        self.assertIn("First idea", segments[0]["phrase"])

    def test_document_prompt_uses_selected_absorption_focus(self):
        prompt = worker.build_document_prompt(
            {
                "level": "B1",
                "document_focus": ["terms", "examples"],
                "document_answer_language": "bilingual",
                "document_depth": "deep",
                "document_answer_length": "long",
            },
            [
                {
                    "id": "doc_0001",
                    "source_time": "文档知识点 1",
                    "text": "What is spaced repetition?",
                    "document_excerpt": "Spaced repetition schedules reviews before forgetting.",
                }
            ],
        )

        self.assertIn("术语定义 / 例子案例", prompt)
        self.assertIn("原文语言", prompt)
        self.assertIn("深入掌握", prompt)
        self.assertIn("详细答案", prompt)
        self.assertIn("读书笔记老师", prompt)
        self.assertIn("不要照抄整段原文", prompt)
        self.assertIn("最小信息原则", prompt)
        self.assertIn("先理解再记忆", prompt)
        self.assertIn("原文依据", prompt)
        self.assertIn("边界/反例", prompt)
        self.assertIn("不要把标题、目录、铺垫做成卡", prompt)
        self.assertIn("cloze 只能有一个 ____", prompt)

    def test_document_prompt_supports_non_english_answer_languages(self):
        prompt = worker.build_document_prompt(
            {
                "level": "B1",
                "document_answer_language": "ja",
                "document_depth": "standard",
                "document_answer_length": "medium",
            },
            [
                {
                    "id": "doc_0001",
                    "source_time": "文档知识点 1",
                    "text": "Spaced repetition schedules reviews before forgetting.",
                    "document_excerpt": "Spaced repetition schedules reviews before forgetting.",
                }
            ],
        )

        self.assertIn("自然日语", prompt)
        self.assertIn("字段内容必须遵守本次讲解语言", prompt)
        self.assertIn("不要因为字段名包含 chinese 就强制写中文", prompt)
        self.assertIn('"knowledge_type":"concepts|arguments|terms|examples"', prompt)

    def test_document_prompt_requires_atomic_retrieval_and_transfer_fields(self):
        prompt = worker.build_document_prompt(
            {
                "level": "B1",
                "document_focus": ["concepts", "arguments"],
                "document_depth": "standard",
                "document_answer_length": "medium",
            },
            [
                {
                    "id": "doc_0001",
                    "source_time": "文档知识点 1",
                    "text": "Why does retrieval practice improve retention?",
                    "document_excerpt": "Retrieval practice strengthens later access better than rereading.",
                }
            ],
        )

        self.assertIn("主动回忆", prompt)
        self.assertIn("最小信息原则", prompt)
        self.assertIn("原文依据", prompt)
        self.assertIn("迁移检查", prompt)
        self.assertIn("边界/反例", prompt)
        self.assertIn("同一个 segment.cards 里输出多张", prompt)
        self.assertIn("综合/对比卡", prompt)
        self.assertIn('"retrieval_task":"正面主动回忆问题"', prompt)
        self.assertIn('"atomic_answer":"背面第一屏短答案"', prompt)
        self.assertIn('"memory_hook":"记忆钩子"', prompt)
        self.assertIn('"transfer_check":"迁移检查"', prompt)
        self.assertIn('"boundary":"边界/反例"', prompt)

    def test_document_merge_preserves_learning_card_fields(self):
        segments = [
            {
                "id": "doc_0001",
                "source_time": "文档知识点 1",
                "text": "Why does retrieval practice improve retention?",
                "phrase": "retrieval practice",
                "document_excerpt": "Retrieval practice strengthens later access better than rereading.",
            }
        ]
        ai_payload = {
            "segments": [
                {
                    "id": "doc_0001",
                    "cards": [
                        {
                            "type": "knowledge",
                            "knowledge_type": "concepts",
                            "retrieval_task": "为什么主动回忆比重读更能帮助长期记忆？",
                            "atomic_answer": "主动回忆会练习从记忆中取回信息，而不只是再次看到信息。",
                            "phrase": "retrieval practice",
                            "definition": "一种通过尝试取回答案来巩固记忆的学习方式。",
                            "source_evidence": "Retrieval practice strengthens later access better than rereading.",
                            "memory_hook": "把大脑当成搜索系统：越练搜索，越容易搜到。",
                            "transfer_check": "复习时先合上资料说答案，再打开核对，而不是边看边点头。",
                            "boundary": "它不是简单重读；如果只看答案没有取回动作，就不算主动回忆。",
                            "why_it_matters": "能区分真正复习和熟悉感，避免假会。",
                            "cloze": "主动回忆训练的是从记忆中 ____ 信息。",
                        }
                    ],
                }
            ]
        }

        merged, _ = worker.merge_document_cards(segments, ai_payload, "B1")
        card = merged[0]["cards"][0]

        self.assertEqual(card["english"], "为什么主动回忆比重读更能帮助长期记忆？")
        self.assertEqual(card["chinese"], "主动回忆会练习从记忆中取回信息，而不只是再次看到信息。")
        self.assertIn("搜索系统", card["chinese_feel"])
        self.assertIn("合上资料", card["how_to_use_it"])
        self.assertIn("不是简单重读", card["teacher_note"])
        self.assertNotIn("本地文档草稿", card["difficulty_reason"])
        self.assertIn("当前水平", card["difficulty_reason"])
        self.assertEqual(card["quality"]["status"], "recommended")

    def test_document_merge_preserves_multiple_distinct_cards_and_caps_total(self):
        segments = [
            {
                "id": "doc_0001",
                "source_time": "文档知识点 1",
                "text": "What should the learner remember?",
                "phrase": "learning practice",
                "document_excerpt": (
                    "Spaced repetition helps memory over time. "
                    "Active recall makes learning stick. "
                    "Feedback prevents confident wrong answers."
                ),
            }
        ]
        base_card = {
            "type": "knowledge",
            "knowledge_type": "concepts",
            "definition": "把一个学习动作压缩成可主动回忆的问题。",
            "source_evidence": "Spaced repetition helps memory over time. Active recall makes learning stick.",
            "memory_hook": "先回忆，再核对。",
            "transfer_check": "复习时先说出答案，再打开资料检查。",
            "boundary": "不是单纯重读，也不是边看边点头。",
            "why_it_matters": "能避免熟悉感伪装成掌握。",
            "teacher_note": "复习时关注自己能否独立说出答案。",
            "cloze": "有效复习需要先 ____ 再核对。",
        }
        ai_payload = {
            "segments": [
                {
                    "id": "doc_0001",
                    "cards": [
                        {
                            **base_card,
                            "retrieval_task": "间隔复习为什么能帮助长期记忆？",
                            "atomic_answer": "它让学习者在遗忘开始后重新取回信息。",
                            "phrase": "spaced repetition",
                        },
                        {
                            **base_card,
                            "retrieval_task": "主动回忆和重读的关键差别是什么？",
                            "atomic_answer": "主动回忆要求先从记忆中产出答案。",
                            "phrase": "active recall",
                        },
                        {
                            **base_card,
                            "retrieval_task": "反馈为什么能防止错答案被强化？",
                            "atomic_answer": "反馈让学习者把答案和证据对照并修正。",
                            "phrase": "feedback loop",
                        },
                    ],
                }
            ]
        }

        merged, _ = worker.merge_document_cards(segments, ai_payload, "B1", max_cards=2)

        self.assertEqual(len(merged[0]["cards"]), 2)
        self.assertEqual([card["phrase"] for card in merged[0]["cards"]], ["spaced repetition", "active recall"])
        self.assertEqual(merged[0]["cards"][0]["id"], "doc_0001_knowledge")
        self.assertEqual(merged[0]["cards"][1]["id"], "doc_0001_knowledge_02")
        self.assertTrue(all(card["enabled"] for card in merged[0]["cards"]))

        relation_segments = [{**segments[0]}]
        relation_ai_payload = {
            "segments": [
                {
                    "id": "doc_0001",
                    "cards": ai_payload["segments"][0]["cards"][:2],
                }
            ]
        }
        expanded, _ = worker.merge_document_cards(relation_segments, relation_ai_payload, "B1", max_cards=3)
        self.assertEqual(len(expanded[0]["cards"]), 3)
        relation_card = expanded[0]["cards"][2]
        self.assertEqual(relation_card["knowledge_type"], "arguments")
        self.assertEqual(relation_card["phrase"], "spaced repetition + active recall")
        self.assertIn("是什么关系", relation_card["english"])
        self.assertIn("两个需要同时理解的侧面", relation_card["chinese"])
        self.assertNotIn("本地文档草稿", relation_card["difficulty_reason"])
        self.assertEqual(relation_card["quality"]["status"], "recommended")
        self.assertTrue(relation_card["enabled"])

    def test_document_quality_flags_missing_transfer_or_boundary(self):
        quality = worker.document_card_quality(
            {
                "type": "knowledge",
                "knowledge_type": "concepts",
                "english": "为什么主动回忆有助于长期记忆？",
                "chinese": "它训练从记忆中取回信息。",
                "phrase": "主动回忆",
                "definition": "通过尝试回答来强化记忆的学习方式。",
                "source_evidence": "Retrieval practice strengthens later access better than rereading.",
                "why_it_matters": "能避免把熟悉感误当成掌握。",
                "teacher_note": "复习时不要直接看答案。",
                "cloze": "主动回忆训练从记忆中 ____ 信息。",
            }
        )

        joined = " / ".join(quality["issues"])
        self.assertIn("缺少迁移检查", joined)
        self.assertIn("缺少边界/反例", joined)
        self.assertNotEqual(quality["status"], "recommended")

    def test_document_language_reading_prompt_excludes_listening_focus(self):
        prompt = worker.build_document_prompt(
            {
                "level": "B1",
                "document_study_mode": "language_reading",
                "language_focus": ["phrases", "listening", "grammar"],
            },
            [
                {
                    "id": "doc_0001",
                    "source_time": "文档知识点 1",
                    "text": "What does the phrase mean?",
                    "document_excerpt": "It turns out the method works in practice.",
                }
            ],
        )

        self.assertIn("英文文档精读老师", prompt)
        self.assertIn("词伙表达", prompt)
        self.assertIn("语法框架", prompt)
        self.assertIn("禁止生成听力卡", prompt)
        self.assertNotIn("听力难点", prompt)

    def test_document_language_reading_cards_default_to_review(self):
        segments = [
            {
                "id": "doc_0001",
                "source_time": "文档知识点 1",
                "text": "What does it turns out mean?",
                "phrase": "it turns out",
                "document_excerpt": "It turns out the method works in practice.",
            }
        ]
        ai_payload = {
            "segments": [
                {
                    "id": "doc_0001",
                    "cards": [
                        {
                            "type": "knowledge",
                            "knowledge_type": "terms",
                            "english": "How does the document use it turns out?",
                            "chinese": "它表示后来发现或结果证明。",
                            "phrase": "it turns out",
                            "definition": "用来引出后来发现的结果。",
                            "collocations": "it turns out that; as it turns out",
                            "context": "文档里用它引出方法实际有效的结果。",
                            "example": "It turns out the simple method works.",
                            "why": "这是阅读文章时常见的转折发现表达。",
                            "teacher_note": "复习时注意它不是 turn out the lights 的动作含义。",
                            "cloze": "____ the method works.",
                        }
                    ],
                }
            ]
        }

        merged, _ = worker.merge_document_cards(segments, ai_payload, "B1", study_mode="language_reading")
        card = merged[0]["cards"][0]

        self.assertFalse(card["enabled"])
        self.assertEqual(card["type_label"], "文档精读卡")
        self.assertEqual(card["document_card_kind"], "language_reading")
        self.assertEqual(card["quality"]["status"], "needs_review")
        self.assertIn("文档精读卡默认待审", " / ".join(card["quality"]["issues"]))
        self.assertEqual(merged[0]["phrase_review_status"], "needs_review")

    def test_document_language_reading_project_filters_listening_focus(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            document = Path(temp_dir) / "reading.md"
            document.write_text(
                "# Reading point\nIt turns out the simple method works in practice and the phrase marks a discovered result.",
                encoding="utf-8",
            )
            project = worker.handle_generate_document(
                {
                    "document_path": str(document),
                    "document_study_mode": "language_reading",
                    "language_focus": ["phrases", "listening", "grammar"],
                    "api_config": {"provider": "local"},
                    "level": "B1",
                }
            )

        self.assertEqual(project["document_study_mode"], "language_reading")
        self.assertEqual(project["language_focus"], ["phrases", "grammar"])
        self.assertTrue(project["segments"][0]["source_time"].startswith("文档精读点"))
        self.assertEqual(project["segments"][0]["cards"][0]["type_label"], "文档精读卡")

    def test_document_generation_cache_ignores_title_and_material_context_drift(self):
        original_call_document_model = worker._legacy_worker.call_document_model
        calls: list[dict] = []
        cwd = os.getcwd()

        def fake_call_document_model(project, segments):
            calls.append(
                {
                    "title": project.get("title"),
                    "material_context": project.get("material_context"),
                    "segments": [segment.get("id") for segment in segments],
                }
            )
            first_id = segments[0]["id"]
            return {
                "segments": [
                    {
                        "id": first_id,
                        "cards": [
                            {
                                "type": "knowledge",
                                "knowledge_type": "concepts",
                                "retrieval_task": "为什么间隔复习有助于长期记忆？",
                                "atomic_answer": "间隔复习让大脑多次主动取回信息。",
                                "phrase": "spaced repetition",
                                "definition": "把复习分散到不同时间点的学习方式。",
                                "source_evidence": "Spaced repetition helps you remember ideas over time.",
                                "memory_hook": "隔一段时间再找回，记忆路径会更稳。",
                                "transfer_check": "安排今天、明天和下周各复习一次。",
                                "boundary": "它不是一次性长时间重读。",
                                "why_it_matters": "能减少熟悉感误判。",
                                "cloze": "间隔复习让大脑多次 ____ 信息。",
                            }
                        ],
                    }
                ]
            }

        try:
            worker._legacy_worker.call_document_model = fake_call_document_model
            with tempfile.TemporaryDirectory() as temp_dir:
                os.chdir(temp_dir)
                try:
                    document = Path(temp_dir) / "spacing.md"
                    document.write_text(
                        "Spaced repetition helps you remember ideas over time. Active recall makes learning stick.",
                        encoding="utf-8",
                    )
                    base_payload = {
                        "source_mode": "document",
                        "document_path": str(document),
                        "document_study_mode": "knowledge",
                        "document_focus": ["concepts"],
                        "document_depth": "standard",
                        "document_answer_length": "medium",
                        "api_config": {
                            "provider": "openai-compatible",
                            "base_url": "http://example.invalid/v1",
                            "api_key": "test",
                            "model": "fake-doc-model",
                        },
                        "level": "B1",
                        "max_segments": 1,
                    }
                    first = worker.handle_generate_document({**base_payload, "title": "Document cache cold"})
                    second = worker.handle_generate_document({**base_payload, "title": "Document cache hot"})
                finally:
                    os.chdir(cwd)
        finally:
            os.chdir(cwd)
            worker._legacy_worker.call_document_model = original_call_document_model

        self.assertEqual(len(calls), 1)
        self.assertIn("Document cache cold", calls[0]["material_context"]["summary"])
        self.assertIn("Document cache hot", second["material_context"]["summary"])
        self.assertEqual(first["quality_funnel"]["card_generation_cache_hits"], 0)
        self.assertEqual(first["quality_funnel"]["card_generation_cache_misses"], 1)
        self.assertEqual(second["quality_funnel"]["card_generation_cache_hits"], 1)
        self.assertEqual(second["quality_funnel"]["card_generation_cache_misses"], 0)
        self.assertEqual(second["segments"][0]["cards"][0]["phrase"], "spaced repetition")

    def test_document_generation_cache_key_changes_for_quality_inputs(self):
        cwd = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                os.chdir(temp_dir)
                try:
                    project = {
                        "document_path": str(Path(temp_dir) / "spacing.md"),
                        "language": "en",
                        "level": "B1",
                        "document_study_mode": "knowledge",
                        "document_focus": ["concepts"],
                        "document_depth": "standard",
                        "document_answer_length": "medium",
                        "api_config": {"provider": "openai-compatible", "model": "fake-a"},
                    }
                    segment = {
                        "id": "doc_0001",
                        "text": "What is spaced repetition?",
                        "phrase": "spaced repetition",
                        "document_excerpt": "Spaced repetition helps memory.",
                    }

                    _, base_key = worker.document_generation_cache_path(project, segment)
                    _, changed_text_key = worker.document_generation_cache_path(
                        project,
                        {**segment, "document_excerpt": "Active recall makes learning stick."},
                    )
                    _, changed_focus_key = worker.document_generation_cache_path(
                        {**project, "document_focus": ["arguments"]},
                        segment,
                    )
                    _, changed_depth_key = worker.document_generation_cache_path(
                        {**project, "document_depth": "deep"},
                        segment,
                    )
                    _, changed_model_key = worker.document_generation_cache_path(
                        {**project, "api_config": {"provider": "openai-compatible", "model": "fake-b"}},
                        segment,
                    )
                finally:
                    os.chdir(cwd)
        finally:
            os.chdir(cwd)

        self.assertNotEqual(base_key, changed_text_key)
        self.assertNotEqual(base_key, changed_focus_key)
        self.assertNotEqual(base_key, changed_depth_key)
        self.assertNotEqual(base_key, changed_model_key)

    def test_document_generation_cache_rejects_unusable_payloads(self):
        original_call_document_model = worker._legacy_worker.call_document_model
        cwd = os.getcwd()
        calls = {"count": 0}

        def fake_call_document_model(project, segments):
            calls["count"] += 1
            return {
                "segments": [
                    {
                        "id": segments[0]["id"],
                        "cards": [
                            {
                                "type": "knowledge",
                                "retrieval_task": "什么是主动回忆？",
                                "atomic_answer": "先尝试从记忆中取回答案，再核对资料。",
                                "phrase": "active recall",
                                "definition": "主动提取信息的学习方式。",
                                "source_evidence": "Active recall makes learning stick.",
                            }
                        ],
                    }
                ]
            }

        try:
            worker._legacy_worker.call_document_model = fake_call_document_model
            with tempfile.TemporaryDirectory() as temp_dir:
                os.chdir(temp_dir)
                try:
                    project = {
                        "document_path": str(Path(temp_dir) / "recall.md"),
                        "language": "en",
                        "level": "B1",
                        "document_study_mode": "knowledge",
                        "document_focus": ["concepts"],
                        "document_depth": "standard",
                        "document_answer_length": "medium",
                        "api_config": {"provider": "openai-compatible", "model": "fake-doc-model"},
                    }
                    segment = {
                        "id": "doc_0001",
                        "text": "What is active recall?",
                        "phrase": "active recall",
                        "document_excerpt": "Active recall makes learning stick.",
                    }
                    cache_path, cache_key = worker.document_generation_cache_path(project, segment)
                    bad_payload = {"segments": [{"id": "doc_0001", "cards": [{"type": "knowledge"}]}]}

                    worker.store_document_generation_cache(cache_path, cache_key, bad_payload)
                    self.assertFalse(cache_path.exists())

                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    cache_path.write_text(
                        json.dumps({"schema_version": 1, "cache_key": cache_key, "payload": bad_payload}),
                        encoding="utf-8",
                    )
                    self.assertIsNone(worker.load_document_generation_cache(cache_path))

                    payload, stats = worker.cached_or_generated_document_payload(
                        project,
                        [segment],
                        cache_disabled=False,
                    )
                finally:
                    os.chdir(cwd)
        finally:
            os.chdir(cwd)
            worker._legacy_worker.call_document_model = original_call_document_model

        self.assertEqual(calls["count"], 1)
        self.assertEqual(stats["cache_hits"], 0)
        self.assertEqual(stats["cache_misses"], 1)
        self.assertEqual(payload["segments"][0]["cards"][0]["phrase"], "active recall")

    def test_document_knowledge_generation_exports_apkg_without_media_steps(self):
        try:
            import genanki  # noqa: F401
        except ImportError:
            self.skipTest("genanki is required for document export smoke")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            document = root / "retrieval.md"
            document.write_text(
                "# Retrieval practice\n\n"
                "Retrieval practice strengthens later access better than rereading. "
                "Learners should first try to answer from memory, then check the source.",
                encoding="utf-8",
            )
            output_dir = root / "out"
            output_dir.mkdir()

            original_call_document_model = worker._legacy_worker.call_document_model

            def fake_call_document_model(project, segments):
                first_id = segments[0]["id"]
                return {
                    "segments": [
                        {
                            "id": first_id,
                            "cards": [
                                {
                                    "type": "knowledge",
                                    "knowledge_type": "concepts",
                                    "retrieval_task": "为什么主动回忆比重读更能帮助长期记忆？",
                                    "atomic_answer": "主动回忆训练从记忆中取回信息，而不只是再次看到信息。",
                                    "phrase": "retrieval practice",
                                    "definition": "通过尝试回答来强化长期记忆的学习方式。",
                                    "source_evidence": "Retrieval practice strengthens later access better than rereading.",
                                    "memory_hook": "把大脑当成搜索系统：越练搜索越容易搜到。",
                                    "transfer_check": "复习时先合上资料说答案，再打开核对原文。",
                                    "boundary": "它不是简单重读；只看答案没有取回动作，就不算主动回忆。",
                                    "why_it_matters": "能避免把熟悉感误当成掌握。",
                                    "cloze": "主动回忆训练从记忆中 ____ 信息。",
                                }
                            ],
                        }
                    ]
                }

            try:
                worker._legacy_worker.call_document_model = fake_call_document_model
                project = worker.handle_generate_document(
                    {
                        "title": "retrieval doc smoke",
                        "source_mode": "document",
                        "document_path": str(document),
                        "document_study_mode": "knowledge",
                        "document_focus": ["concepts"],
                        "document_depth": "standard",
                        "document_answer_length": "medium",
                        "api_config": {"provider": "openai-compatible", "base_url": "http://example.invalid/v1", "api_key": "test", "model": "fake"},
                        "level": "B1",
                        "template_id": "immersive",
                        "max_segments": 1,
                    }
                )
            finally:
                worker._legacy_worker.call_document_model = original_call_document_model

            self.assertEqual(project["source_mode"], "document")
            self.assertEqual(project["document_study_mode"], "knowledge")
            self.assertEqual(project["segments"][0]["cards"][0]["quality"]["status"], "recommended")
            self.assertTrue(project["segments"][0]["cards"][0]["enabled"])

            result = worker.handle_export({"project": project, "output_dir": str(output_dir)})

            self.assertTrue(Path(result["apkg_path"]).exists())
            self.assertEqual(result["deck_kind"], "document_knowledge")
            self.assertEqual(result["cards"], 1)
            self.assertEqual(result["media_summary"]["video_segments"], 0)
            self.assertEqual(result["media_summary"]["media_files"], 0)

            import sqlite3
            import zipfile

            with zipfile.ZipFile(result["apkg_path"]) as apkg:
                apkg.extract("collection.anki2", root)
            connection = sqlite3.connect(root / "collection.anki2")
            try:
                models_json = connection.execute("select models from col").fetchone()[0]
                note_fields = connection.execute("select flds from notes limit 1").fetchone()[0]
            finally:
                connection.close()

            model = next(iter(json.loads(models_json).values()))
            template = model["tmpls"][0]
            field_names = [field["name"] for field in model["flds"]]
            exported_fields = note_fields.split("\x1f")

            self.assertIn("文档知识 V10", model["name"])
            self.assertIn("迁移检查", template["afmt"])
            self.assertEqual(exported_fields[field_names.index("FrontPrompt")], "为什么主动回忆比重读更能帮助长期记忆？")
            self.assertIn("训练从记忆中取回信息", exported_fields[field_names.index("Chinese")])
            self.assertIn("合上资料", exported_fields[field_names.index("Why")])
            self.assertIn("不是简单重读", exported_fields[field_names.index("TeacherNote")])

    def test_generate_document_batch_merges_items_with_batch_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "01 retrieval.md"
            second = root / "02 spacing.md"
            first.write_text(
                "# Retrieval practice\nRetrieval practice strengthens later access better than rereading.",
                encoding="utf-8",
            )
            second.write_text(
                "# Spacing effect\nSpacing reviews across time improves long-term retention.",
                encoding="utf-8",
            )

            original_call_document_model = worker._legacy_worker.call_document_model

            def fake_call_document_model(project, segments):
                first_id = segments[0]["id"]
                phrase = "spacing effect" if "spacing" in str(project.get("title", "")).lower() else "retrieval practice"
                question = "为什么间隔复习能提升长期保持？" if phrase == "spacing effect" else "为什么主动回忆比重读更有效？"
                answer = "间隔能让大脑在遗忘前后重新取回信息。" if phrase == "spacing effect" else "主动回忆训练从记忆中取回信息。"
                definition = "间隔效应指把复习分散到不同时间以提升保持。" if phrase == "spacing effect" else "主动回忆指先从记忆中提取答案，再核对资料。"
                evidence = "Spacing reviews across time improves long-term retention." if phrase == "spacing effect" else "Retrieval practice strengthens later access better than rereading."
                return {
                    "segments": [
                        {
                            "id": first_id,
                            "cards": [
                                {
                                    "type": "knowledge",
                                    "knowledge_type": "concepts",
                                    "retrieval_task": question,
                                    "atomic_answer": answer,
                                    "phrase": phrase,
                                    "definition": definition,
                                    "source_evidence": evidence,
                                    "memory_hook": "把复习当成主动搜索，而不是重看。",
                                    "transfer_check": "合上资料先回答，再打开核对原文。",
                                    "boundary": "只看答案或机械重读不算。",
                                    "why_it_matters": "避免熟悉感伪装成掌握。",
                                    "cloze": "有效复习需要从记忆中 ____ 信息。",
                                }
                            ],
                        }
                    ]
                }

            try:
                worker._legacy_worker.call_document_model = fake_call_document_model
                project = worker.handle_generate(
                    {
                        "title": "学习方法资料包",
                        "source_mode": "document",
                        "batch_enabled": True,
                        "batch_items": [
                            {
                                "id": "doc1",
                                "enabled": True,
                                "source_mode": "document",
                                "subdeck_title": "01 - Retrieval",
                                "deck_name": "学习方法资料包::01 - Retrieval",
                                "document_path": str(first),
                            },
                            {
                                "id": "doc2",
                                "enabled": True,
                                "source_mode": "document",
                                "subdeck_title": "02 - Spacing",
                                "deck_name": "学习方法资料包::02 - Spacing",
                                "document_path": str(second),
                            },
                        ],
                        "document_study_mode": "knowledge",
                        "document_focus": ["concepts"],
                        "api_config": {"provider": "openai-compatible", "base_url": "http://example.invalid/v1", "api_key": "test", "model": "fake"},
                        "level": "B1",
                        "template_id": "immersive",
                        "max_segments": 1,
                    }
                )
            finally:
                worker._legacy_worker.call_document_model = original_call_document_model

            self.assertEqual(project["title"], "学习方法资料包")
            self.assertTrue(project["batch_enabled"])
            self.assertEqual(len(project["batch_items"]), 2)
            self.assertEqual(project["source_mode"], "document")
            self.assertEqual(project["document_path"], "")
            self.assertEqual(len(project["segments"]), 2)
            self.assertEqual({segment["batch_item_id"] for segment in project["segments"]}, {"doc1", "doc2"})
            self.assertTrue(all(segment["id"].startswith(("doc1_", "doc2_")) for segment in project["segments"]))
            self.assertEqual({card["batch_item_id"] for segment in project["segments"] for card in segment["cards"]}, {"doc1", "doc2"})
            self.assertEqual(project["quality_funnel"]["card_count"], 2)
            self.assertEqual(project["quality_funnel"]["selected_card_count"], 2)

    def test_fallback_document_card_is_review_only(self):
        card = worker.fallback_document_card(
            {
                "id": "doc_0001",
                "text": "What is the idea?",
                "document_excerpt": "This passage introduces a concept but needs model refinement.",
            },
            "B1",
        )

        self.assertFalse(card["enabled"])
        self.assertEqual(card["quality"]["status"], "needs_review")
        self.assertIn("本地文档草稿", card["quality"]["issues"][0])

    def test_placeholder_document_concept_is_downgraded(self):
        segments = [
            {
                "id": "doc_0001",
                "source_time": "文档知识点 1",
                "text": "这段主要讲什么？",
                "phrase": "核心知识点",
                "document_excerpt": "The text explains why spaced repetition works.",
            }
        ]
        ai_payload = {
            "segments": [
                {
                    "id": "doc_0001",
                    "cards": [
                        {
                            "type": "knowledge",
                            "knowledge_type": "concepts",
                            "english": "这段主要讲什么？",
                            "chinese": "It is about spaced repetition.",
                            "phrase": "核心知识点",
                            "definition": "It is about spaced repetition.",
                            "why": "",
                            "teacher_note": "很重要",
                            "cloze": "核心知识点 的核心是 ____。",
                        }
                    ],
                }
            ]
        }

        merged, _ = worker.merge_document_cards(segments, ai_payload, "B1")
        card = merged[0]["cards"][0]

        self.assertFalse(card["enabled"])
        self.assertEqual(card["quality"]["status"], "reject")
        self.assertIn("概念名是占位词", " / ".join(card["quality"]["issues"]))

    def test_document_quality_flags_summary_like_or_source_less_cards(self):
        quality = worker.document_card_quality(
            {
                "type": "knowledge",
                "knowledge_type": "concepts",
                "english": "这段主要讲什么？",
                "chinese": "这段文字主要介绍间隔重复，并且继续补充很多不适合直接复习的摘要性背景。" * 6,
                "phrase": "章节标题",
                "definition": "间隔重复是一种复习安排方法。",
                "context": "",
                "source_evidence": "",
                "why_it_matters": "能解释为什么复习时间需要被安排。",
                "teacher_note": "要能区分复习计划和普通重复阅读。",
                "cloze": "间隔重复在 ____ 前安排复习，并通过 ____ 降低遗忘。",
            }
        )

        joined = " / ".join(quality["issues"])
        self.assertIn("正面问题太泛", joined)
        self.assertIn("缺少原文依据", joined)
        self.assertIn("答案过长", joined)
        self.assertIn("cloze 只能有一个空", joined)
        self.assertIn("概念名像标题", joined)
        self.assertNotEqual(quality["status"], "recommended")

    def test_cached_url_source_can_be_subtitle_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_root = Path(temp_dir)
            source_dir = cache_root / "url_deadbeef"
            source_dir.mkdir()
            (source_dir / "source.en.srt").write_text(
                "1\n00:00:00,000 --> 00:00:02,000\nIt turns out I was wrong.\n",
                encoding="utf-8",
            )

            cached = worker.find_cached_url_source(
                cache_root,
                "deadbeef",
                {
                    "source_url": "https://www.youtube.com/watch?v=test",
                    "language": "English",
                    "url_import_mode": "subtitles",
                },
            )

        self.assertIsNotNone(cached)
        self.assertEqual(cached["video_path"], "")
        self.assertTrue(cached["skip_video_slicing"])
        self.assertEqual(cached["download_mode"], "subtitles")

    def test_cached_url_source_requires_video_by_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_root = Path(temp_dir)
            source_dir = cache_root / "url_deadbeef"
            source_dir.mkdir()
            (source_dir / "source.en.srt").write_text(
                "1\n00:00:00,000 --> 00:00:02,000\nIt turns out I was wrong.\n",
                encoding="utf-8",
            )

            cached = worker.find_cached_url_source(
                cache_root,
                "deadbeef",
                {"source_url": "https://www.youtube.com/watch?v=test", "language": "English"},
            )

        self.assertIsNone(cached)

    def test_check_env_returns_actionable_status_items_without_secrets(self):
        status = worker.handle_check_env({})

        self.assertIn("status_items", status)
        self.assertTrue(any(item["id"] == "python" for item in status["status_items"]))
        self.assertTrue(any(item["id"] == "anki" for item in status["status_items"]))
        self.assertIn("anki_installed", status)
        self.assertIn("anki_running", status)
        self.assertNotIn("api_key", worker.json.dumps(status).lower())
        self.assertNotIn("sk-", worker.json.dumps(status).lower())

    def test_find_anki_executable_treats_permission_denied_ankiw_as_installed(self):
        legacy = worker._legacy_worker
        original_candidates = legacy.anki_executable_candidates
        original_exists = legacy.Path.exists
        candidate = legacy.Path(r"C:\Users\Example\AppData\Local\AnkiProgramFiles\.venv\Scripts\ankiw.exe")

        def fake_exists(path):
            if str(path) == str(candidate):
                raise PermissionError("access denied")
            return original_exists(path)

        try:
            legacy.anki_executable_candidates = lambda: [candidate]
            legacy.Path.exists = fake_exists

            self.assertEqual(legacy.find_anki_executable(), str(candidate))
        finally:
            legacy.anki_executable_candidates = original_candidates
            legacy.Path.exists = original_exists

    def test_windows_process_check_falls_back_to_powershell_when_tasklist_denied(self):
        legacy = worker._legacy_worker
        original_os_name = legacy.os.name
        original_run = legacy.subprocess.run
        calls = []

        class Completed:
            def __init__(self, returncode, stdout="", stderr=""):
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        def fake_run(command, **_kwargs):
            calls.append(command)
            if command[0] == "tasklist":
                return Completed(1, "", "ERROR: Access denied")
            return Completed(0, "59800\n", "")

        try:
            legacy.os.name = "nt"
            legacy.subprocess.run = fake_run

            self.assertTrue(legacy.is_process_running("ankiw.exe"))
        finally:
            legacy.os.name = original_os_name
            legacy.subprocess.run = original_run

        self.assertEqual(calls[0][0], "tasklist")
        self.assertEqual(calls[1][0], "powershell.exe")

    def test_repair_env_returns_manual_ankiconnect_steps_without_secrets(self):
        original_check_anki_connect = worker._legacy_worker.check_anki_connect
        original_find_anki_executable = worker._legacy_worker.find_anki_executable
        original_is_process_running = worker._legacy_worker.is_process_running
        original_launch_anki_desktop = worker._legacy_worker.launch_anki_desktop

        try:
            worker._legacy_worker.check_anki_connect = lambda: (False, "not connected")
            worker._legacy_worker.find_anki_executable = lambda: r"C:\Program Files\Anki\anki.exe"
            worker._legacy_worker.is_process_running = lambda _name: False
            worker._legacy_worker.launch_anki_desktop = lambda _path: (True, "已尝试打开 Anki")

            result = worker.handle_repair_env({"target": "anki_connect"})
        finally:
            worker._legacy_worker.check_anki_connect = original_check_anki_connect
            worker._legacy_worker.find_anki_executable = original_find_anki_executable
            worker._legacy_worker.is_process_running = original_is_process_running
            worker._legacy_worker.launch_anki_desktop = original_launch_anki_desktop

        self.assertTrue(result["ok"])
        self.assertEqual(result["target"], "anki_connect")
        self.assertTrue(any(action["id"] == "anki_launch" and action["status"] == "success" for action in result["actions"]))
        plugin_action = next(action for action in result["actions"] if action["id"] == "anki_connect")
        self.assertEqual(plugin_action["status"], "manual")
        self.assertIn("2055492159", plugin_action["next_step"])
        self.assertNotIn("api_key", worker.json.dumps(result).lower())
        self.assertNotIn("sk-", worker.json.dumps(result).lower())

    def test_video_html_keeps_mp4_and_webm_fallbacks(self):
        from acg.anki_media import anki_audio_html, anki_video_html

        html = worker.anki_video_html("clip.webm", "clip.mp4", "clip.jpg")

        self.assertIn('poster="clip.jpg"', html)
        self.assertIn('<img src="clip.jpg"', html)
        self.assertIn('src="clip.mp4"', html)
        self.assertIn('type="video/mp4"', html)
        self.assertIn('src="clip.webm"', html)
        self.assertIn('type="video/webm"', html)
        self.assertLess(html.index('src="clip.webm"'), html.index('src="clip.mp4"'))
        self.assertIn('class="anki-video-fallback"', html)
        self.assertIn('aria-hidden="true"', html)
        self.assertNotIn("视频无法播放", html)
        self.assertEqual(html, anki_video_html("clip.webm", "clip.mp4", "clip.jpg"))
        escaped_video = anki_video_html('clip"&.webm', 'clip<.mp4', 'post>.jpg', controls=False, muted=True)
        self.assertIn('clip&quot;&amp;.webm', escaped_video)
        self.assertIn('clip&lt;.mp4', escaped_video)
        self.assertIn('post&gt;.jpg', escaped_video)
        self.assertNotIn(" controls", escaped_video)
        self.assertIn("muted", escaped_video)
        escaped_audio = anki_audio_html('tts"&.mp3', role='slow"role')
        self.assertEqual(escaped_audio, worker.anki_audio_html('tts"&.mp3', role='slow"role'))
        self.assertIn('tts&quot;&amp;.mp3', escaped_audio)
        self.assertIn('data-audio-role="slow&quot;role"', escaped_audio)

    def test_extract_media_references_reads_sources_and_poster(self):
        from acg.media_refs import extract_media_references, media_refs_with_suffix, missing_video_required_media_roles

        html = worker.anki_video_html("clip.webm", "clip.mp4", "clip.jpg") + worker.anki_audio_html("clip_tts.mp3")

        refs = extract_media_references(html)
        self.assertEqual(refs, ["clip.jpg", "clip.webm", "clip.mp4", "clip_tts.mp3"])
        self.assertEqual(media_refs_with_suffix(refs, {".mp4", ".webm"}), ["clip.webm", "clip.mp4"])
        self.assertEqual(worker.extract_media_references(html), refs)
        complete_refs_by_field = {
            "Video": ["clip.jpg", "clip.webm", "clip.mp4"],
            "Audio": ["original.mp3"],
            "TtsAudio": ["sentence.mp3"],
            "PhraseTtsAudio": ["phrase.mp3"],
        }
        self.assertEqual(missing_video_required_media_roles(complete_refs_by_field), [])
        incomplete_refs_by_field = {
            "Video": ["clip.mp4"],
            "Audio": ["original.mp3"],
            "TtsAudio": ["sentence.mp3"],
            "PhraseTtsAudio": [],
        }
        self.assertEqual(
            missing_video_required_media_roles(incomplete_refs_by_field),
            ["Video.webm", "Video.poster", "PhraseTtsAudio.mp3"],
        )

    def test_anki_field_helpers_extract_plain_text_and_card_identity(self):
        from acg.anki_fields import (
            anki_card_deck_name,
            anki_card_model_name,
            anki_field_has_any_text,
            anki_field_plain_text,
            anki_field_value,
            anki_import_pronunciation_meta_error,
            imported_model_template_mismatches,
            imported_corrupted_study_text_values,
            imported_tts_text_hash_mismatches,
            missing_document_required_text_fields,
            missing_video_required_text_fields,
        )
        from acg.audio_audit import media_text_hash

        fields = {
            "English": {"value": "The <b>quick</b> &amp; reliable card."},
            "Answer": "quick card",
            "Chinese": {"value": "??????"},
            "TeacherNote": {"value": "Clean note"},
            "PronunciationMeta": {"value": '{"status":"ok"}'},
        }
        info = {
            "deckName": "视频语言卡 - Smoke",
            "note": {"modelName": "Anki Card Generator V12 - 沉浸复读 V11 · 快速复读"},
        }

        self.assertEqual(anki_field_value(fields, "English"), "The <b>quick</b> &amp; reliable card.")
        self.assertEqual(anki_field_plain_text(fields, "English"), "The quick & reliable card.")
        self.assertTrue(anki_field_has_any_text(fields, ["Answer", "English"]))
        self.assertEqual(anki_card_model_name(info), "Anki Card Generator V12 - 沉浸复读 V11 · 快速复读")
        self.assertEqual(anki_card_deck_name(info), "视频语言卡 - Smoke")
        self.assertEqual(
            imported_corrupted_study_text_values(fields, "card-1"),
            [{"card_id": "card-1", "field": "Chinese", "pattern": "??????", "excerpt": "??????"}],
        )
        self.assertEqual(anki_import_pronunciation_meta_error(fields), "")
        self.assertEqual(anki_import_pronunciation_meta_error({"PronunciationMeta": ""}), "missing")
        self.assertEqual(
            anki_import_pronunciation_meta_error({"PronunciationMeta": "{not-json}"}),
            "invalid_json:Expecting property name enclosed in double quotes",
        )
        self.assertEqual(anki_import_pronunciation_meta_error({"PronunciationMeta": "[]"}), "not_object")
        self.assertEqual(worker.anki_field_plain_text(fields, "English"), "The quick & reliable card.")
        self.assertEqual(worker.imported_corrupted_study_text_values(fields, "card-1")[0]["field"], "Chinese")
        self.assertEqual(missing_video_required_text_fields(fields), ["CardId"])
        self.assertEqual(
            missing_video_required_text_fields(
                {
                    "CardId": {"value": "card-1"},
                    "English": {"value": "Source sentence."},
                    "Phrase": {"value": "source"},
                }
            ),
            [],
        )
        self.assertEqual(
            missing_document_required_text_fields(
                {
                    "CardId": {"value": "doc-1"},
                    "English": {"value": "Document question"},
                    "Definition": {"value": "Document answer"},
                }
            ),
            [],
        )
        self.assertEqual(
            missing_document_required_text_fields({"CardId": {"value": "doc-1"}}),
            ["QuestionOrSource", "AnswerOrDefinition"],
        )
        video_template_check = imported_model_template_mismatches(
            [
                "Anki Card Generator V12 - 沉浸复读 V11 · 快速复读",
                "Anki Card Generator V10 - 文档知识 V10",
                "Anki Card Generator V12 - 词霸天下实验 V1",
            ],
            strict_video_import=True,
        )
        self.assertEqual(video_template_check["ciba_model_names"], ["Anki Card Generator V12 - 词霸天下实验 V1"])
        self.assertEqual(
            video_template_check["video_template_mismatches"],
            ["Anki Card Generator V10 - 文档知识 V10", "Anki Card Generator V12 - 词霸天下实验 V1"],
        )
        exact_name_check = imported_model_template_mismatches(
            [
                "Anki Card Generator V14 - 沉浸复读 V11",
                "Anki Card Generator V12 - 沉浸复读 V11 · 快速复读",
                "Anki Card Generator V14 - 沉浸复读 V11 copy",
                "Anki Card Generator V12 - 词霸天下实验 V1 copy",
            ],
            strict_video_import=True,
        )
        self.assertEqual(exact_name_check["ciba_model_names"], [])
        self.assertEqual(
            exact_name_check["video_template_mismatches"],
            [
                "Anki Card Generator V12 - 词霸天下实验 V1 copy",
                "Anki Card Generator V14 - 沉浸复读 V11 copy",
            ],
        )
        document_template_check = imported_model_template_mismatches(
            [
                "Anki Card Generator V12 - 沉浸复读 V11",
                "Anki Card Generator V10 - 文档知识 V10",
                "ciba scratch",
            ],
            strict_document_import=True,
        )
        self.assertEqual(
            document_template_check["document_template_mismatches"],
            ["Anki Card Generator V12 - 沉浸复读 V11", "ciba scratch"],
        )
        matching_refs = {
            "TtsAudio": [f"sentence_{media_text_hash('The quick & reliable card.')}.mp3"],
            "PhraseTtsAudio": [f"phrase_{media_text_hash('quick card')}.mp3"],
        }
        self.assertEqual(
            imported_tts_text_hash_mismatches(fields, "card-1", matching_refs, media_text_hash),
            [],
        )
        mismatched_refs = {**matching_refs, "PhraseTtsAudio": ["phrase_wrong.mp3"]}
        tts_mismatches = imported_tts_text_hash_mismatches(fields, "card-1", mismatched_refs, media_text_hash)
        self.assertEqual(tts_mismatches[0]["field"], "PhraseTtsAudio")
        self.assertEqual(tts_mismatches[0]["expected_text_hash"], media_text_hash("quick card"))

    def test_anki_verify_helpers_preserve_failed_check_order_and_messages(self):
        from acg.anki_verify import verify_anki_import_failed_checks, verify_anki_import_message

        failed_checks = verify_anki_import_failed_checks(
            card_infos_present=True,
            strict_video_import=True,
            strict_document_import=False,
            sorted_model_names=[],
            video_template_mismatches=["Document V10"],
            ciba_model_names=["词霸天下实验 V1"],
            document_template_mismatches=[],
            expected_cards=2,
            verified_card_count=1,
            card_media_ledger_provided=True,
            card_media_ledger_count=1,
            audio_audit_count=1,
            audio_audit_mismatches=[{"field": "English"}],
            audio_audit_write_errors=[],
            card_media_ledger_mismatches=[{"field": "PhraseTtsAudio"}],
            missing_video_field_media=[{"missing": ["Video.webm"]}],
            empty_required_fields=[{"missing": ["English"]}],
            corrupted_study_text_values=[{"field": "Chinese"}],
            pronunciation_meta_errors=[{"error": "missing"}],
            imported_tts_text_hash_mismatch=[{"field": "TtsAudio"}],
            unreferenced_expected=["unused.mp3"],
            unexpected_references=["extra.mp3"],
            manifest_missing=["missing.mp3"],
            manifest_mismatched=[{"file": "bad.mp3"}],
            manifest_inaccessible=[{"file": "locked.mp3"}],
            tts_audio_duration_issues=[{"file": "short.mp3"}],
            tts_semantic_failures=[{"file": "semantic.mp3"}],
            tts_semantic_export_required=False,
            ledger_missing_manifest=["ledger-extra.mp3"],
            manifest_tts_without_ledger=["tts-no-ledger.mp3"],
            ledger_text_hash_mismatch=[{"file": "hash.mp3"}],
            media_ledger_card_text_mismatches=[{"file": "card-text.mp3"}],
        )

        self.assertEqual(
            failed_checks,
            [
                "imported_model_missing",
                "video_template_mismatch",
                "ordinary_flow_ciba_template",
                "card_count_mismatch",
                "card_media_ledger_count_mismatch",
                "audio_audit_count_mismatch",
                "audio_audit_mismatch",
                "card_media_ledger_mismatch",
                "missing_imported_video_field_media",
                "empty_imported_required_fields",
                "corrupted_imported_study_text",
                "pronunciation_meta_parse_errors",
                "imported_tts_text_hash_mismatch",
                "unreferenced_expected_media",
                "unexpected_media_references",
                "missing_imported_media",
                "media_hash_mismatch",
                "inaccessible_imported_media",
                "imported_tts_audio_duration",
                "ledger_missing_manifest",
                "manifest_tts_without_ledger",
                "ledger_text_hash_mismatch",
                "media_ledger_card_text_mismatch",
            ],
        )
        self.assertNotIn("tts_semantic_mismatch", failed_checks)
        self.assertEqual(verify_anki_import_message(failed_checks, duplicate_imported_cards=[], tts_manual_items=[]), "Anki 导入媒体核验发现问题。")
        self.assertEqual(
            verify_anki_import_message([], duplicate_imported_cards=[{"card_id": "card-1"}], tts_manual_items=[]),
            "Anki 导入媒体核验通过；检测到同名 deck 里已有旧导入，已按本次 audio_audit 匹配到的卡片核验。",
        )
        self.assertEqual(
            verify_anki_import_message([], duplicate_imported_cards=[], tts_manual_items=[{"file": "tts.mp3"}]),
            "Anki 导入媒体核验通过；TTS 语义仍需按清单人工抽查。",
        )

    def test_audio_audit_media_ref_helpers_match_anki_fields(self):
        from acg.audio_audit import (
            audio_audit_imported_text_mismatches,
            audio_audit_expected_refs_by_field,
            card_media_expected_refs_by_field,
            compare_expected_media_refs_by_field,
            items_by_card_id,
            missing_expected_entry_mismatch,
        )

        card_media = {
            "card_id": "card-1",
            "video_webm": "clip.webm",
            "video_mp4": "clip.mp4",
            "poster": "clip.jpg",
            "original_audio": "original.mp3",
            "sentence_tts_audio": "sentence.mp3",
            "phrase_tts_audio": "phrase.mp3",
        }
        audit_item = {
            "card_id": "card-1",
            "video_webm": "clip.webm",
            "video_mp4": "clip.mp4",
            "poster": "clip.jpg",
            "original_audio": "original.mp3",
            "sentence_tts_file": "sentence.mp3",
            "phrase_tts_file": "phrase.mp3",
        }
        refs_by_field = {
            "Video": ["clip.webm", "clip.mp4", "clip.jpg"],
            "Audio": ["original.mp3"],
            "TtsAudio": ["sentence.mp3"],
            "PhraseTtsAudio": ["wrong_phrase.mp3"],
        }

        self.assertEqual(items_by_card_id([card_media])["card-1"], card_media)
        self.assertEqual(card_media_expected_refs_by_field(card_media)["PhraseTtsAudio"], ["phrase.mp3"])
        self.assertEqual(audio_audit_expected_refs_by_field(audit_item)["PhraseTtsAudio"], ["phrase.mp3"])
        mismatches = compare_expected_media_refs_by_field(
            "card-1",
            refs_by_field,
            audio_audit_expected_refs_by_field(audit_item),
        )
        self.assertEqual(mismatches[0]["field"], "PhraseTtsAudio")
        self.assertIn("phrase.mp3", mismatches[0]["missing_expected"])
        self.assertIn("wrong_phrase.mp3", mismatches[0]["unexpected_actual"])
        self.assertEqual(
            missing_expected_entry_mismatch("card-1", "audio_audit entry")["missing_expected"],
            ["audio_audit entry"],
        )
        audit_item.update(
            {
                "card_display_sentence": "Expected display sentence.",
                "sentence_tts_expected_text": "Expected display sentence.",
                "phrase_tts_expected_text": "expected phrase",
                "media_subtitle_alignment_status": "mismatch",
                "media_subtitle_overlap_score": 0.1,
                "media_subtitle_time": "00:00:01.000 - 00:00:02.000",
                "media_window_subtitle_text": "unrelated media subtitle",
            }
        )
        sentence_actual, text_mismatches = audio_audit_imported_text_mismatches(
            "card-1",
            audit_item,
            {
                "English": {"value": "Imported display sentence."},
                "Answer": {"value": "imported phrase"},
                "Phrase": {"value": ""},
            },
        )
        self.assertEqual(sentence_actual, "Imported display sentence.")
        self.assertEqual(
            [item["field"] for item in text_mismatches],
            ["CardDisplaySentence", "MediaSubtitleAlignment", "English", "AnswerOrPhrase"],
        )
        self.assertEqual(text_mismatches[1]["media_window_subtitle_text"], "unrelated media subtitle")

    def test_audio_audit_allows_optional_empty_tts_text(self):
        from acg.audio_audit import (
            audio_audit_imported_text_mismatches,
            build_audio_audit_items,
            media_text_hash,
        )

        sentence = "A reliable source sentence."
        self.assertEqual(media_text_hash(""), "")
        items = build_audio_audit_items(
            [
                {
                    "card_id": "card-optional",
                    "segment_id": "segment-optional",
                    "sentence_tts_text": sentence,
                    "sentence_tts_audio": "sentence.mp3",
                    "phrase_tts_text": "",
                    "phrase_tts_audio": "",
                }
            ],
            {
                "sentence.mp3": {
                    "sha256": "sentence-sha",
                    "text_hash": media_text_hash(sentence),
                    "semantic_verification": "passed",
                }
            },
            deck_name="Deck",
            model_name="Model",
            deck_kind="subtitle_language",
        )

        self.assertEqual(items[0]["sentence_tts_expected_text"], sentence)
        self.assertNotIn("phrase_tts_expected_text", items[0])
        self.assertNotIn("phrase_tts_file", items[0])
        sentence_actual, mismatches = audio_audit_imported_text_mismatches(
            "card-optional",
            {},
            {
                "English": {"value": ""},
                "Answer": {"value": ""},
                "Phrase": {"value": ""},
            },
        )
        self.assertEqual(sentence_actual, "")
        self.assertEqual(mismatches, [])

    def test_compare_media_manifest_detects_media_collision(self):
        from acg.media_manifest import compare_media_manifest, media_manifest

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            export_dir = root / "export"
            anki_dir = root / "anki"
            export_dir.mkdir()
            anki_dir.mkdir()
            (export_dir / "deck_seg_0001.mp3").write_bytes(b"new audio")
            (anki_dir / "deck_seg_0001.mp3").write_bytes(b"old audio")

            manifest = media_manifest(
                [str(export_dir / "deck_seg_0001.mp3")],
                [{"file": "deck_seg_0001.mp3", "role": "sentence_tts", "tts_text": "new audio"}],
            )
            legacy_manifest = worker.media_manifest([str(export_dir / "deck_seg_0001.mp3")])
            result = compare_media_manifest(manifest, anki_dir)
            legacy_result = worker.compare_media_manifest(legacy_manifest, anki_dir)

        self.assertEqual(manifest["deck_seg_0001.mp3"]["role"], "sentence_tts")
        self.assertEqual(result["missing"], [])
        self.assertEqual(result["mismatched"][0]["file"], "deck_seg_0001.mp3")
        self.assertEqual(legacy_result["mismatched"][0]["file"], "deck_seg_0001.mp3")

    def test_media_ledger_manifest_consistency_reports_ledger_drift(self):
        from acg.audio_audit import media_text_hash
        from acg.media_manifest import media_ledger_card_text_mismatches, media_ledger_manifest_consistency

        expected_manifest = {
            "sentence.mp3": {"role": "sentence_tts"},
            "phrase.mp3": {"role": "phrase_tts"},
            "clip.mp4": {"role": "video"},
        }
        media_ledger = [
            {
                "file": "C:/export/sentence.mp3",
                "role": "sentence_tts",
                "tts_text": "Correct sentence text.",
                "text_hash": media_text_hash("Correct sentence text."),
            },
            {
                "file": "C:/export/extra.mp3",
                "role": "phrase_tts",
                "tts_text": "Wrong hash text.",
                "text_hash": "wrong-hash",
            },
        ]

        result = media_ledger_manifest_consistency(media_ledger, expected_manifest)

        self.assertEqual(result["ledger_missing_manifest"], ["extra.mp3"])
        self.assertEqual(result["manifest_tts_without_ledger"], ["phrase.mp3"])
        self.assertEqual(result["ledger_text_hash_mismatch"][0]["file"], "extra.mp3")
        self.assertEqual(
            result["ledger_text_hash_mismatch"][0]["expected_text_hash"],
            media_text_hash("Wrong hash text."),
        )

        card_text_mismatches = media_ledger_card_text_mismatches(
            [
                {
                    "card_id": "card-1",
                    "sentence_tts_audio": "sentence.mp3",
                    "sentence_tts_text": "Correct sentence text.",
                    "phrase_tts_audio": "phrase.mp3",
                    "phrase_tts_text": "Correct phrase text.",
                }
            ],
            [
                media_ledger[0],
                {
                    "file": "phrase.mp3",
                    "role": "phrase_tts",
                    "tts_text": "Wrong but self-consistent phrase text.",
                    "text_hash": media_text_hash("Wrong but self-consistent phrase text."),
                },
            ],
        )

        self.assertEqual(len(card_text_mismatches), 1)
        self.assertEqual(card_text_mismatches[0]["field"], "PhraseTtsAudio")
        self.assertEqual(card_text_mismatches[0]["file"], "phrase.mp3")
        self.assertEqual(card_text_mismatches[0]["expected_text_hash"], media_text_hash("Correct phrase text."))
        self.assertEqual(
            card_text_mismatches[0]["ledger_text_hash"],
            media_text_hash("Wrong but self-consistent phrase text."),
        )

    def test_compare_media_manifest_retries_transient_permission_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            export_dir = root / "export"
            anki_dir = root / "anki"
            export_dir.mkdir()
            anki_dir.mkdir()
            (export_dir / "deck_seg_0001.mp3").write_bytes(b"audio")
            (anki_dir / "deck_seg_0001.mp3").write_bytes(b"audio")

            manifest = worker.media_manifest([str(export_dir / "deck_seg_0001.mp3")])
            original_file_sha256 = worker._legacy_worker.file_sha256
            calls = {"count": 0}

            def flaky_file_sha256(path):
                calls["count"] += 1
                if calls["count"] == 1:
                    raise PermissionError("media file is temporarily locked")
                return original_file_sha256(path)

            try:
                worker._legacy_worker.file_sha256 = flaky_file_sha256
                result = worker.compare_media_manifest(
                    manifest,
                    anki_dir,
                    max_attempts=2,
                    retry_delay_seconds=0,
                )
            finally:
                worker._legacy_worker.file_sha256 = original_file_sha256

        self.assertEqual(result["checked"], 1)
        self.assertEqual(result["missing"], [])
        self.assertEqual(result["mismatched"], [])
        self.assertEqual(result["inaccessible"], [])

    def test_compare_media_manifest_reports_persistent_permission_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            export_dir = root / "export"
            anki_dir = root / "anki"
            export_dir.mkdir()
            anki_dir.mkdir()
            (export_dir / "deck_seg_0001.mp3").write_bytes(b"audio")
            (anki_dir / "deck_seg_0001.mp3").write_bytes(b"audio")

            manifest = worker.media_manifest([str(export_dir / "deck_seg_0001.mp3")])
            original_file_sha256 = worker._legacy_worker.file_sha256

            try:
                worker._legacy_worker.file_sha256 = lambda _path: (_ for _ in ()).throw(PermissionError("locked"))
                result = worker.compare_media_manifest(
                    manifest,
                    anki_dir,
                    max_attempts=2,
                    retry_delay_seconds=0,
                )
            finally:
                worker._legacy_worker.file_sha256 = original_file_sha256

        self.assertEqual(result["checked"], 0)
        self.assertEqual(result["missing"], [])
        self.assertEqual(result["mismatched"], [])
        self.assertEqual(result["inaccessible"][0]["file"], "deck_seg_0001.mp3")

    def test_compare_media_manifest_falls_back_to_anki_connect_when_filesystem_denied(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            export_dir = root / "export"
            anki_dir = root / "anki"
            export_dir.mkdir()
            anki_dir.mkdir()
            media_bytes = b"audio from anki connect"
            (export_dir / "deck_seg_0001.mp3").write_bytes(media_bytes)
            (anki_dir / "deck_seg_0001.mp3").write_bytes(media_bytes)

            manifest = worker.media_manifest([str(export_dir / "deck_seg_0001.mp3")])
            original_file_sha256 = worker._legacy_worker.file_sha256
            original_retrieve = worker._legacy_worker.retrieve_anki_media_bytes

            try:
                worker._legacy_worker.file_sha256 = lambda _path: (_ for _ in ()).throw(PermissionError("locked"))
                worker._legacy_worker.retrieve_anki_media_bytes = lambda filename, _url: (
                    media_bytes if filename == "deck_seg_0001.mp3" else None
                )
                result = worker.compare_media_manifest(
                    manifest,
                    anki_dir,
                    anki_url="http://127.0.0.1:8765",
                    max_attempts=1,
                    retry_delay_seconds=0,
                )
            finally:
                worker._legacy_worker.file_sha256 = original_file_sha256
                worker._legacy_worker.retrieve_anki_media_bytes = original_retrieve

        self.assertEqual(result["checked"], 1)
        self.assertEqual(result["missing"], [])
        self.assertEqual(result["mismatched"], [])
        self.assertEqual(result["inaccessible"], [])

    def test_imported_tts_duration_reports_permission_error_instead_of_crashing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            anki_dir = Path(temp_dir) / "anki"
            anki_dir.mkdir()
            manifest = {
                "locked_phrase.mp3": {
                    "role": "phrase_tts",
                    "tts_text": "prompt",
                    "duration_seconds": 1.2,
                }
            }
            original_exists = worker._legacy_worker.Path.exists

            def locked_exists(path):
                if Path(path).name == "locked_phrase.mp3":
                    raise PermissionError("locked by Anki")
                return original_exists(path)

            try:
                worker._legacy_worker.Path.exists = locked_exists
                result = worker._legacy_worker.imported_tts_audio_duration_issues(
                    manifest,
                    anki_dir,
                    {"locked_phrase.mp3"},
                    strict_video_import=True,
                    max_attempts=2,
                    retry_delay_seconds=0,
                )
            finally:
                worker._legacy_worker.Path.exists = original_exists

        self.assertEqual(result[0]["file"], "locked_phrase.mp3")
        self.assertEqual(result[0]["reason"], "duration_inaccessible")

    def test_imported_tts_duration_falls_back_to_anki_connect_when_filesystem_denied(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            anki_dir = Path(temp_dir) / "anki"
            anki_dir.mkdir()
            manifest = {
                "locked_phrase.mp3": {
                    "role": "phrase_tts",
                    "tts_text": "prompt",
                    "duration_seconds": 1.2,
                }
            }
            original_exists = worker._legacy_worker.Path.exists
            original_retrieve = worker._legacy_worker.retrieve_anki_media_bytes
            original_duration = worker._legacy_worker.audio_duration_seconds_from_bytes

            def locked_exists(path):
                if Path(path).name == "locked_phrase.mp3":
                    raise PermissionError("locked by Anki")
                return original_exists(path)

            try:
                worker._legacy_worker.Path.exists = locked_exists
                worker._legacy_worker.retrieve_anki_media_bytes = lambda filename, _url: (
                    b"audio from anki connect" if filename == "locked_phrase.mp3" else None
                )
                worker._legacy_worker.audio_duration_seconds_from_bytes = lambda _filename, _data: 1.2
                result = worker._legacy_worker.imported_tts_audio_duration_issues(
                    manifest,
                    anki_dir,
                    {"locked_phrase.mp3"},
                    strict_video_import=True,
                    anki_url="http://127.0.0.1:8765",
                    max_attempts=1,
                    retry_delay_seconds=0,
                )
            finally:
                worker._legacy_worker.Path.exists = original_exists
                worker._legacy_worker.retrieve_anki_media_bytes = original_retrieve
                worker._legacy_worker.audio_duration_seconds_from_bytes = original_duration

        self.assertEqual(result, [])

    def test_imported_media_duration_helpers_match_worker_boundary(self):
        from acg import imported_media

        with tempfile.TemporaryDirectory() as temp_dir:
            anki_dir = Path(temp_dir) / "anki"
            anki_dir.mkdir()
            phrase_file = anki_dir / "phrase.mp3"
            phrase_file.write_bytes(b"fake audio")
            manifest = {
                "phrase.mp3": {
                    "role": "phrase_tts",
                    "tts_text": "prompt",
                    "duration_seconds": 1.2,
                }
            }

            def fake_audio_duration_seconds(path):
                return 87.64 if Path(path).name == "phrase.mp3" else None

            original_audio_duration_seconds = worker._legacy_worker.audio_duration_seconds
            try:
                worker._legacy_worker.audio_duration_seconds = fake_audio_duration_seconds
                wrapper_result = worker._legacy_worker.imported_tts_audio_duration_issues(
                    manifest,
                    anki_dir,
                    {"phrase.mp3"},
                    strict_video_import=True,
                    max_attempts=1,
                    retry_delay_seconds=0,
                )
            finally:
                worker._legacy_worker.audio_duration_seconds = original_audio_duration_seconds

            core_result = imported_media.imported_tts_audio_duration_issues(
                manifest,
                anki_dir,
                {"phrase.mp3"},
                strict_video_import=True,
                max_attempts=1,
                retry_delay_seconds=0,
                retrieve_media_bytes_func=lambda _filename, _url: None,
                duration_seconds_func=fake_audio_duration_seconds,
                duration_seconds_from_bytes_func=lambda _filename, _data: None,
                clean_tts_text_func=worker._legacy_worker.clean_tts_input_text,
                phrase_max_duration_func=worker._legacy_worker.phrase_tts_max_duration_seconds,
            )

        self.assertEqual(wrapper_result, core_result)
        self.assertEqual(core_result[0]["reason"], "overlong_phrase_tts")
        self.assertEqual(worker._legacy_worker.numeric_manifest_value("1.25"), 1.25)
        self.assertEqual(imported_media.numeric_manifest_value("1.25"), 1.25)

    def test_export_text_helpers_match_worker_boundary(self):
        from acg import export_text

        raw_html = '<span class="x">A & B</span>'
        self.assertEqual(worker._legacy_worker.anki_text(raw_html), export_text.anki_text(raw_html))
        self.assertEqual(export_text.anki_text(raw_html), '&lt;span class="x"&gt;A &amp; B&lt;/span&gt;')
        long_text = "one two three four five"
        self.assertEqual(worker._legacy_worker.audit_text_excerpt(long_text, 12), "one two thr\u2026")
        self.assertEqual(worker._legacy_worker.audit_text_excerpt(long_text, 12), export_text.audit_text_excerpt(long_text, 12))
        self.assertEqual(worker._legacy_worker.anki_study_text("本地 fallback 只保证结构完整"), "")
        self.assertEqual(worker._legacy_worker.anki_study_text("A & B"), "A &amp; B")

    def test_verify_anki_import_accepts_zero_media_exports(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            anki_dir = Path(temp_dir) / "anki_media"
            anki_dir.mkdir()
            original_anki_connect = worker._legacy_worker.anki_connect

            def fake_anki_connect(action, params=None, url=""):
                if action == "findCards":
                    return [123]
                if action == "cardsInfo":
                    return [
                        {
                            "cardId": 123,
                            "fields": {
                                "Video": {"value": ""},
                                "Audio": {"value": ""},
                                "TtsAudio": {"value": ""},
                                "PhraseTtsAudio": {"value": ""},
                            },
                        }
                    ]
                if action == "getMediaDirPath":
                    return str(anki_dir)
                raise AssertionError(action)

            try:
                worker._legacy_worker.anki_connect = fake_anki_connect
                result = worker.handle_verify_anki_import(
                    {
                        "export_result": {
                            "deck_name": "Zero Media Deck",
                            "cards": 1,
                            "source_identity": {
                                "source_fingerprint": "file:freshsource1234",
                                "source_mode": "local_video",
                            },
                            "source_fingerprint": "file:freshsource1234",
                            "media_manifest": {},
                            "media_summary": {"media_files": 0},
                            "media_dir": str(Path(temp_dir) / "export_media"),
                        }
                    }
                )
            finally:
                worker._legacy_worker.anki_connect = original_anki_connect

        self.assertTrue(result["ok"])
        self.assertEqual(result["media_count_expected"], 0)
        self.assertEqual(result["media_count_checked"], 0)
        self.assertEqual(result["card_count"], 1)
        self.assertEqual(result["source_identity"]["source_fingerprint"], "file:freshsource1234")
        self.assertEqual(result["source_fingerprint"], "file:freshsource1234")

    def test_verify_anki_import_prechecks_before_importing_new_apkg(self):
        calls = []
        imported = False
        with tempfile.TemporaryDirectory() as temp_dir:
            apkg_path = Path(temp_dir) / "deck.apkg"
            apkg_path.write_bytes(b"fake apkg for importPackage mock")
            expected_apkg_sha256 = hashlib.sha256(apkg_path.read_bytes()).hexdigest()
            expected_apkg_size_bytes = apkg_path.stat().st_size
            anki_dir = Path(temp_dir) / "anki_media"
            anki_dir.mkdir()
            original_anki_connect = worker._legacy_worker.anki_connect

            def fake_anki_connect(action, params=None, url=""):
                nonlocal imported
                calls.append((action, params or {}))
                if action == "importPackage":
                    self.assertEqual(params["path"], str(apkg_path))
                    imported = True
                    return True
                if action == "findCards":
                    return [123] if imported else []
                if action == "cardsInfo":
                    return [
                        {
                            "cardId": 123,
                            "deckName": "Import Then Verify",
                            "fields": {
                                "Video": {"value": ""},
                                "Audio": {"value": ""},
                                "TtsAudio": {"value": ""},
                                "PhraseTtsAudio": {"value": ""},
                            },
                        }
                    ]
                if action == "getMediaDirPath":
                    return str(anki_dir)
                raise AssertionError(action)

            try:
                worker._legacy_worker.anki_connect = fake_anki_connect
                result = worker.handle_verify_anki_import(
                    {
                        "import_apkg": True,
                        "export_result": {
                            "apkg_path": str(apkg_path),
                            "deck_name": "Import Then Verify",
                            "cards": 1,
                            "media_manifest": {},
                            "media_summary": {"media_files": 0},
                            "media_dir": str(Path(temp_dir) / "export_media"),
                        },
                    }
                )
            finally:
                worker._legacy_worker.anki_connect = original_anki_connect

        self.assertTrue(result["ok"])
        self.assertTrue(result["import_attempted"])
        self.assertTrue(result["import_result"])
        self.assertFalse(result["import_skipped_existing"])
        self.assertEqual(result["apkg_path"], str(apkg_path))
        self.assertEqual(result["apkg_sha256"], expected_apkg_sha256)
        self.assertEqual(result["apkg_size_bytes"], expected_apkg_size_bytes)
        self.assertGreater(result["apkg_mtime_ms"], 0)
        actions = [action for action, _ in calls]
        self.assertLess(actions.index("findCards"), actions.index("importPackage"))
        self.assertLess(actions.index("importPackage"), len(actions) - 1 - actions[::-1].index("findCards"))

    def test_verify_anki_import_skips_import_when_all_export_card_ids_exist(self):
        calls = []
        with tempfile.TemporaryDirectory() as temp_dir:
            apkg_path = Path(temp_dir) / "deck.apkg"
            apkg_path.write_bytes(b"already imported package")
            anki_dir = Path(temp_dir) / "anki_media"
            anki_dir.mkdir()
            original_anki_connect = worker._legacy_worker.anki_connect
            field_names = ["CardId", "Answer"]
            field_values = {
                "export-card-1": ["export-card-1", "first answer"],
                "export-card-2": ["export-card-2", "second answer"],
            }

            def fake_anki_connect(action, params=None, url=""):
                calls.append((action, params or {}))
                if action == "getMediaDirPath":
                    return str(anki_dir)
                if action == "findCards":
                    return [101, 102]
                if action == "cardsInfo":
                    return [
                        {
                            "cardId": card_id,
                            "deckName": "Already Imported",
                            "fields": {
                                "CardId": {"value": export_card_id},
                                "Answer": {"value": field_values[export_card_id][1]},
                            },
                        }
                        for card_id, export_card_id in [(101, "export-card-1"), (102, "export-card-2")]
                    ]
                if action == "importPackage":
                    raise AssertionError("a fully existing package must not be imported again")
                raise AssertionError(action)

            try:
                worker._legacy_worker.anki_connect = fake_anki_connect
                result = worker.handle_verify_anki_import(
                    {
                        "import_apkg": True,
                        "export_result": {
                            "apkg_path": str(apkg_path),
                            "deck_name": "Already Imported",
                            "anki_tag": "anki_card_generator_v12",
                            "cards": 2,
                            "card_media_ledger": [
                                {
                                    "card_id": card_id,
                                    "sentence_tts_text": "sentence",
                                    "phrase_tts_text": "phrase",
                                    "note_tags": [
                                        "anki_card_generator_v12",
                                        "lang_english",
                                        "level_b1",
                                        "template_immersive_v11",
                                        "type_expression",
                                        "layout_phrase",
                                    ],
                                    "note_content_sha256": worker._legacy_worker.note_content_sha256(
                                        field_names, values
                                    ),
                                }
                                for card_id, values in field_values.items()
                            ],
                            "note_content_fingerprint": {
                                "schema_version": 1,
                                "algorithm": "sha256",
                                "serialization": "json-field-pairs-v1",
                                "field_names": field_names,
                                "card_count": 2,
                            },
                            "media_manifest": {},
                            "media_summary": {"media_files": 0},
                            "media_dir": str(Path(temp_dir) / "export_media"),
                        },
                    }
                )
            finally:
                worker._legacy_worker.anki_connect = original_anki_connect

        self.assertTrue(result["ok"], result)
        self.assertTrue(result["import_attempted"])
        self.assertIsNone(result["import_result"])
        self.assertTrue(result["import_skipped_existing"])
        self.assertEqual(result["import_existing_check"]["evidence"], "card_id+content_sha256")
        self.assertNotIn("importPackage", [action for action, _ in calls])
        preflight_query = next(params["query"] for action, params in calls if action == "findCards")
        self.assertEqual(preflight_query, 'deck:"Already Imported" tag:"anki_card_generator_v12"')

    def test_verify_anki_import_reimports_same_card_id_when_note_content_changed(self):
        calls = []
        imported = False
        with tempfile.TemporaryDirectory() as temp_dir:
            apkg_path = Path(temp_dir) / "deck.apkg"
            apkg_path.write_bytes(b"updated package")
            anki_dir = Path(temp_dir) / "anki_media"
            anki_dir.mkdir()
            original_anki_connect = worker._legacy_worker.anki_connect
            field_names = ["CardId", "Answer"]
            expected_values = ["export-card-1", "new answer"]

            def fake_anki_connect(action, params=None, url=""):
                nonlocal imported
                calls.append((action, params or {}))
                if action == "getMediaDirPath":
                    return str(anki_dir)
                if action == "findCards":
                    return [101]
                if action == "cardsInfo":
                    return [
                        {
                            "cardId": 101,
                            "deckName": "Updated Content",
                            "fields": {
                                "CardId": {"value": "export-card-1"},
                                "Answer": {"value": "new answer" if imported else "old answer"},
                            },
                        }
                    ]
                if action == "importPackage":
                    imported = True
                    return True
                raise AssertionError(action)

            try:
                worker._legacy_worker.anki_connect = fake_anki_connect
                result = worker.handle_verify_anki_import(
                    {
                        "import_apkg": True,
                        "export_result": {
                            "apkg_path": str(apkg_path),
                            "deck_name": "Updated Content",
                            "anki_tag": "anki_card_generator_v12",
                            "cards": 1,
                            "card_media_ledger": [
                                {
                                    "card_id": "export-card-1",
                                    "sentence_tts_text": "updated sentence",
                                    "phrase_tts_text": "updated phrase",
                                    "note_tags": [
                                        "anki_card_generator_v12",
                                        "lang_english",
                                        "level_b1",
                                        "template_immersive_v11",
                                        "type_expression",
                                        "layout_phrase",
                                    ],
                                    "note_content_sha256": worker._legacy_worker.note_content_sha256(
                                        field_names, expected_values
                                    ),
                                }
                            ],
                            "note_content_fingerprint": {
                                "schema_version": 1,
                                "algorithm": "sha256",
                                "serialization": "json-field-pairs-v1",
                                "field_names": field_names,
                                "card_count": 1,
                            },
                            "media_manifest": {},
                            "media_summary": {"media_files": 0},
                            "media_dir": str(Path(temp_dir) / "export_media"),
                        },
                    }
                )
            finally:
                worker._legacy_worker.anki_connect = original_anki_connect

        self.assertTrue(result["ok"], result)
        self.assertTrue(result["import_result"])
        self.assertFalse(result["import_skipped_existing"])
        self.assertEqual(result["import_existing_check"]["reason"], "note_content_fingerprint_mismatch")
        self.assertEqual([action for action, _ in calls].count("importPackage"), 1)

    def test_verify_anki_import_imports_when_only_some_export_card_ids_exist(self):
        calls = []
        imported = False
        with tempfile.TemporaryDirectory() as temp_dir:
            apkg_path = Path(temp_dir) / "deck.apkg"
            apkg_path.write_bytes(b"partially imported package")
            anki_dir = Path(temp_dir) / "anki_media"
            anki_dir.mkdir()
            original_anki_connect = worker._legacy_worker.anki_connect

            def fake_anki_connect(action, params=None, url=""):
                nonlocal imported
                calls.append((action, params or {}))
                if action == "getMediaDirPath":
                    return str(anki_dir)
                if action == "findCards":
                    return [101, 102] if imported else [101]
                if action == "cardsInfo":
                    ids = params["cards"]
                    return [
                        {
                            "cardId": card_id,
                            "deckName": "Partial Import",
                            "fields": {"CardId": {"value": f"export-card-{card_id - 100}"}},
                        }
                        for card_id in ids
                    ]
                if action == "importPackage":
                    imported = True
                    return True
                raise AssertionError(action)

            try:
                worker._legacy_worker.anki_connect = fake_anki_connect
                result = worker.handle_verify_anki_import(
                    {
                        "import_apkg": True,
                        "export_result": {
                            "apkg_path": str(apkg_path),
                            "deck_name": "Partial Import",
                            "cards": 2,
                            "card_media_ledger": [
                                {"card_id": "export-card-1", "sentence_tts_text": "sentence", "phrase_tts_text": "phrase"},
                                {"card_id": "export-card-2", "sentence_tts_text": "sentence", "phrase_tts_text": "phrase"},
                            ],
                            "media_manifest": {},
                            "media_summary": {"media_files": 0},
                            "media_dir": str(Path(temp_dir) / "export_media"),
                        },
                    }
                )
            finally:
                worker._legacy_worker.anki_connect = original_anki_connect

        self.assertTrue(result["ok"], result)
        self.assertFalse(result["import_skipped_existing"])
        self.assertTrue(result["import_result"])
        self.assertEqual(result["import_existing_check"]["reason"], "missing_export_card_ids")
        self.assertEqual([action for action, _ in calls].count("importPackage"), 1)

    def test_verify_anki_import_does_not_skip_same_count_with_different_card_ids(self):
        calls = []
        imported = False
        with tempfile.TemporaryDirectory() as temp_dir:
            apkg_path = Path(temp_dir) / "deck.apkg"
            apkg_path.write_bytes(b"new package with same count")
            anki_dir = Path(temp_dir) / "anki_media"
            anki_dir.mkdir()
            original_anki_connect = worker._legacy_worker.anki_connect

            def fake_anki_connect(action, params=None, url=""):
                nonlocal imported
                calls.append((action, params or {}))
                if action == "getMediaDirPath":
                    return str(anki_dir)
                if action == "findCards":
                    return [301, 302]
                if action == "cardsInfo":
                    prefix = "current" if imported else "old"
                    return [
                        {
                            "cardId": card_id,
                            "deckName": "Reused Deck",
                            "fields": {"CardId": {"value": f"{prefix}-card-{index}"}},
                        }
                        for index, card_id in enumerate(params["cards"], 1)
                    ]
                if action == "importPackage":
                    imported = True
                    return True
                raise AssertionError(action)

            try:
                worker._legacy_worker.anki_connect = fake_anki_connect
                result = worker.handle_verify_anki_import(
                    {
                        "import_apkg": True,
                        "export_result": {
                            "apkg_path": str(apkg_path),
                            "deck_name": "Reused Deck",
                            "cards": 2,
                            "card_media_ledger": [
                                {"card_id": "current-card-1", "sentence_tts_text": "sentence", "phrase_tts_text": "phrase"},
                                {"card_id": "current-card-2", "sentence_tts_text": "sentence", "phrase_tts_text": "phrase"},
                            ],
                            "media_manifest": {},
                            "media_summary": {"media_files": 0},
                            "media_dir": str(Path(temp_dir) / "export_media"),
                        },
                    }
                )
            finally:
                worker._legacy_worker.anki_connect = original_anki_connect

        self.assertTrue(result["ok"], result)
        self.assertFalse(result["import_skipped_existing"])
        self.assertTrue(result["import_result"])
        self.assertEqual([action for action, _ in calls].count("importPackage"), 1)

    def test_verify_anki_import_query_failure_never_suppresses_import(self):
        calls = []
        find_calls = 0
        with tempfile.TemporaryDirectory() as temp_dir:
            apkg_path = Path(temp_dir) / "deck.apkg"
            apkg_path.write_bytes(b"query failure package")
            anki_dir = Path(temp_dir) / "anki_media"
            anki_dir.mkdir()
            original_anki_connect = worker._legacy_worker.anki_connect

            def fake_anki_connect(action, params=None, url=""):
                nonlocal find_calls
                calls.append((action, params or {}))
                if action == "getMediaDirPath":
                    return str(anki_dir)
                if action == "findCards":
                    find_calls += 1
                    if find_calls == 1:
                        raise RuntimeError("temporary Anki query failure")
                    return [501]
                if action == "cardsInfo":
                    return [
                        {
                            "cardId": 501,
                            "deckName": "Query Failure",
                            "fields": {"CardId": {"value": "query-card-1"}},
                        }
                    ]
                if action == "importPackage":
                    return True
                raise AssertionError(action)

            try:
                worker._legacy_worker.anki_connect = fake_anki_connect
                result = worker.handle_verify_anki_import(
                    {
                        "import_apkg": True,
                        "export_result": {
                            "apkg_path": str(apkg_path),
                            "deck_name": "Query Failure",
                            "cards": 1,
                            "card_media_ledger": [{"card_id": "query-card-1", "sentence_tts_text": "sentence", "phrase_tts_text": "phrase"}],
                            "media_manifest": {},
                            "media_summary": {"media_files": 0},
                            "media_dir": str(Path(temp_dir) / "export_media"),
                        },
                    }
                )
            finally:
                worker._legacy_worker.anki_connect = original_anki_connect

        self.assertTrue(result["ok"], result)
        self.assertFalse(result["import_skipped_existing"])
        self.assertTrue(result["import_result"])
        self.assertEqual(result["import_existing_check"]["reason"], "query_failed")
        self.assertEqual([action for action, _ in calls].count("importPackage"), 1)

    def test_verify_anki_import_legacy_fallback_requires_strict_deck_tag_and_count(self):
        calls = []
        with tempfile.TemporaryDirectory() as temp_dir:
            apkg_path = Path(temp_dir) / "deck.apkg"
            apkg_path.write_bytes(b"legacy package")
            anki_dir = Path(temp_dir) / "anki_media"
            anki_dir.mkdir()
            original_anki_connect = worker._legacy_worker.anki_connect

            def fake_anki_connect(action, params=None, url=""):
                calls.append((action, params or {}))
                if action == "getMediaDirPath":
                    return str(anki_dir)
                if action == "findCards":
                    return [601, 602]
                if action == "cardsInfo":
                    return [
                        {"cardId": card_id, "deckName": "Legacy Deck", "fields": {}}
                        for card_id in params["cards"]
                    ]
                if action == "importPackage":
                    calls.append(("legacyImportConfirmed", {}))
                    return True
                raise AssertionError(action)

            try:
                worker._legacy_worker.anki_connect = fake_anki_connect
                result = worker.handle_verify_anki_import(
                    {
                        "import_apkg": True,
                        "export_result": {
                            "apkg_path": str(apkg_path),
                            "deck_name": "Legacy Deck",
                            "anki_tag": "anki_card_generator_v10",
                            "cards": 2,
                            "media_manifest": {},
                            "media_summary": {"media_files": 0},
                            "media_dir": str(Path(temp_dir) / "export_media"),
                        },
                    }
                )
            finally:
                worker._legacy_worker.anki_connect = original_anki_connect

        self.assertTrue(result["ok"], result)
        self.assertFalse(result["import_skipped_existing"])
        self.assertTrue(result["import_result"])
        self.assertEqual(result["import_existing_check"]["evidence"], "legacy_unbound")
        self.assertEqual(result["import_existing_check"]["reason"], "legacy_content_fingerprint_unavailable")
        self.assertEqual(
            next(params["query"] for action, params in calls if action == "findCards"),
            'deck:"Legacy Deck" tag:"anki_card_generator_v10"',
        )
        self.assertEqual([action for action, _ in calls].count("importPackage"), 1)

    def test_verify_anki_import_can_prepare_media_before_native_anki_dialog(self):
        calls = []
        with tempfile.TemporaryDirectory() as temp_dir:
            apkg_path = Path(temp_dir) / "deck.apkg"
            apkg_path.write_bytes(b"fake apkg for native dialog")
            export_dir = Path(temp_dir) / "export_media"
            export_dir.mkdir()
            media_name = "sample_original.mp3"
            media_bytes = b"trusted media bytes"
            (export_dir / media_name).write_bytes(media_bytes)
            manifest = worker.media_manifest([str(export_dir / media_name)])
            anki_dir = Path(temp_dir) / "anki_media"
            anki_dir.mkdir()
            original_anki_connect = worker._legacy_worker.anki_connect

            def fake_anki_connect(action, params=None, url=""):
                calls.append((action, params or {}))
                if action == "getMediaDirPath":
                    return str(anki_dir)
                if action == "retrieveMediaFile":
                    stored_path = anki_dir / params["filename"]
                    return (
                        base64.b64encode(stored_path.read_bytes()).decode("ascii")
                        if stored_path.is_file()
                        else None
                    )
                if action == "storeMediaFile":
                    stored_bytes = base64.b64decode(params["data"])
                    (anki_dir / params["filename"]).write_bytes(stored_bytes)
                    return params["filename"]
                if action == "importPackage":
                    raise AssertionError("prepare_media_only must not import the package")
                raise AssertionError(action)

            try:
                worker._legacy_worker.anki_connect = fake_anki_connect
                result = worker.handle_verify_anki_import(
                    {
                        "prepare_media_only": True,
                        "import_apkg": False,
                        "export_result": {
                            "apkg_path": str(apkg_path),
                            "deck_name": "Native Dialog Preparation",
                            "cards": 1,
                            "media_manifest": manifest,
                            "media_summary": {"media_files": 1},
                            "media_dir": str(export_dir),
                        },
                    }
                )
                stored_media_bytes = (anki_dir / media_name).read_bytes()
            finally:
                worker._legacy_worker.anki_connect = original_anki_connect

        self.assertTrue(result["ok"], result)
        self.assertFalse(result["import_attempted"])
        self.assertIsNone(result["import_result"])
        self.assertEqual(result["media_prepared_count"], 1)
        self.assertEqual(result["media_already_present_count"], 0)
        self.assertEqual(stored_media_bytes, media_bytes)
        self.assertNotIn("importPackage", [action for action, _ in calls])

    def test_anki_media_preload_blocks_same_name_with_different_content(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            anki_dir = Path(temp_dir) / "collection.media"
            anki_dir.mkdir()
            media_name = "sample_original.mp3"
            (anki_dir / media_name).write_bytes(b"old unrelated bytes")
            expected_hash = hashlib.sha256(b"new trusted bytes").hexdigest()

            result = worker._legacy_worker.inspect_anki_media_for_preload(
                {media_name: {"sha256": expected_hash, "bytes": len(b"new trusted bytes")}},
                anki_dir,
            )

        self.assertEqual(result["missing"], [])
        self.assertEqual(result["already_present"], [])
        self.assertEqual(len(result["conflicts"]), 1)
        self.assertEqual(result["conflicts"][0]["file"], media_name)
        self.assertEqual(result["failures"], [])

    def test_verify_anki_import_restores_missing_package_media_through_anki_connect(self):
        calls = []
        with tempfile.TemporaryDirectory() as temp_dir:
            apkg_path = Path(temp_dir) / "deck.apkg"
            apkg_path.write_bytes(b"fake apkg")
            export_dir = Path(temp_dir) / "export_media"
            export_dir.mkdir()
            media_name = "sample_original.mp3"
            media_bytes = b"trusted media bytes"
            (export_dir / media_name).write_bytes(media_bytes)
            manifest = worker.media_manifest([str(export_dir / media_name)])
            anki_dir = Path(temp_dir) / "anki_media"
            anki_dir.mkdir()
            original_anki_connect = worker._legacy_worker.anki_connect

            def fake_anki_connect(action, params=None, url=""):
                calls.append((action, params or {}))
                if action == "importPackage":
                    return True
                if action == "findCards":
                    return [123]
                if action == "cardsInfo":
                    return [
                        {
                            "cardId": 123,
                            "fields": {
                                "Audio": {"value": worker.anki_audio_html(media_name)},
                            },
                        }
                    ]
                if action == "getMediaDirPath":
                    return str(anki_dir)
                if action == "retrieveMediaFile":
                    stored_path = anki_dir / params["filename"]
                    return (
                        base64.b64encode(stored_path.read_bytes()).decode("ascii")
                        if stored_path.is_file()
                        else None
                    )
                if action == "storeMediaFile":
                    stored_bytes = base64.b64decode(params["data"])
                    (anki_dir / params["filename"]).write_bytes(stored_bytes)
                    return params["filename"]
                raise AssertionError(action)

            try:
                worker._legacy_worker.anki_connect = fake_anki_connect
                result = worker.handle_verify_anki_import(
                    {
                        "import_apkg": True,
                        "export_result": {
                            "apkg_path": str(apkg_path),
                            "deck_name": "Media Recovery",
                            "cards": 1,
                            "media_manifest": manifest,
                            "media_summary": {"media_files": 1},
                            "media_dir": str(export_dir),
                        },
                    }
                )
            finally:
                worker._legacy_worker.anki_connect = original_anki_connect

        self.assertTrue(result["ok"], result)
        self.assertTrue(result["media_recovery_attempted"])
        self.assertEqual(result["media_recovered_count"], 1)
        self.assertEqual(result["media_recovered"], [media_name])
        self.assertEqual(result["media_recovery_methods"], {media_name: "anki_connect"})
        self.assertEqual(result["media_recovery_failures"], [])
        self.assertEqual(result["missing_media"], [])
        store_call = next(params for action, params in calls if action == "storeMediaFile")
        self.assertEqual(store_call["filename"], media_name)
        self.assertEqual(base64.b64decode(store_call["data"]), media_bytes)

    def test_verify_anki_import_uses_trusted_atomic_copy_for_cross_drive_anki_error(self):
        calls = []
        with tempfile.TemporaryDirectory() as temp_dir:
            app_data = Path(temp_dir) / "appdata"
            anki_dir = app_data / "Anki2" / "Profile" / "collection.media"
            anki_dir.mkdir(parents=True)
            apkg_path = Path(temp_dir) / "deck.apkg"
            apkg_path.write_bytes(b"fake apkg")
            export_dir = Path(temp_dir) / "export_media"
            export_dir.mkdir()
            media_name = "sample_original.mp3"
            media_bytes = b"trusted media bytes"
            (export_dir / media_name).write_bytes(media_bytes)
            manifest = worker.media_manifest([str(export_dir / media_name)])
            original_anki_connect = worker._legacy_worker.anki_connect
            original_app_data = os.environ.get("APPDATA")

            def fake_anki_connect(action, params=None, url=""):
                calls.append(action)
                if action == "importPackage":
                    return True
                if action == "findCards":
                    return [123]
                if action == "cardsInfo":
                    return [
                        {
                            "cardId": 123,
                            "fields": {
                                "Audio": {"value": worker.anki_audio_html(media_name)},
                            },
                        }
                    ]
                if action == "getMediaDirPath":
                    return str(anki_dir)
                if action == "retrieveMediaFile":
                    return None
                if action == "storeMediaFile":
                    raise RuntimeError("The system cannot move the file to a different disk drive. (os error 17)")
                raise AssertionError(action)

            try:
                os.environ["APPDATA"] = str(app_data)
                worker._legacy_worker.anki_connect = fake_anki_connect
                result = worker.handle_verify_anki_import(
                    {
                        "import_apkg": True,
                        "export_result": {
                            "apkg_path": str(apkg_path),
                            "deck_name": "Media Recovery",
                            "cards": 1,
                            "media_manifest": manifest,
                            "media_summary": {"media_files": 1},
                            "media_dir": str(export_dir),
                        },
                    }
                )
                restored_bytes = (anki_dir / media_name).read_bytes()
            finally:
                worker._legacy_worker.anki_connect = original_anki_connect
                if original_app_data is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = original_app_data

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["media_recovered_count"], 1)
        self.assertEqual(result["media_recovery_methods"], {media_name: "trusted_atomic_copy"})
        self.assertEqual(result["media_recovery_failures"], [])
        self.assertEqual(restored_bytes, media_bytes)
        self.assertNotIn("retrieveMediaFile", calls)
        self.assertNotIn("storeMediaFile", calls)

    def test_media_recovery_refuses_cross_drive_fallback_outside_anki_profile(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app_data = Path(temp_dir) / "appdata"
            (app_data / "Anki2").mkdir(parents=True)
            unsafe_dir = Path(temp_dir) / "outside" / "collection.media"
            unsafe_dir.mkdir(parents=True)
            export_dir = Path(temp_dir) / "export_media"
            export_dir.mkdir()
            media_name = "sample_original.mp3"
            media_path = export_dir / media_name
            media_path.write_bytes(b"trusted media bytes")
            manifest = worker.media_manifest([str(media_path)])
            original_anki_connect = worker._legacy_worker.anki_connect
            original_app_data = os.environ.get("APPDATA")

            def fake_anki_connect(action, params=None, url=""):
                if action == "retrieveMediaFile":
                    return None
                if action == "storeMediaFile":
                    raise RuntimeError("cross-device link (os error 17)")
                raise AssertionError(action)

            try:
                os.environ["APPDATA"] = str(app_data)
                worker._legacy_worker.anki_connect = fake_anki_connect
                result = worker.restore_missing_anki_media(
                    [media_name],
                    manifest,
                    export_dir,
                    unsafe_dir,
                    "http://127.0.0.1:8765",
                )
            finally:
                worker._legacy_worker.anki_connect = original_anki_connect
                if original_app_data is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = original_app_data

        self.assertEqual(result["restored"], [])
        self.assertEqual(len(result["failures"]), 1)
        self.assertEqual(result["failures"][0]["code"], "anki_connect_store_failed")
        self.assertIn("标准 Anki profile", result["failures"][0]["error"])

    def test_direct_media_restore_accepts_identical_file_created_during_publish(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app_data = Path(temp_dir) / "appdata"
            anki_media_dir = app_data / "Anki2" / "Profile" / "collection.media"
            anki_media_dir.mkdir(parents=True)
            filename = "race-identical.mp3"
            destination = anki_media_dir / filename
            source_bytes = b"trusted media bytes"
            source_path = Path(temp_dir) / "source-identical.mp3"
            source_path.write_bytes(source_bytes)
            expected_hash = hashlib.sha256(source_bytes).hexdigest()
            original_app_data = os.environ.get("APPDATA")
            original_publish = worker._legacy_worker.publish_file_no_replace

            def publish_after_identical_race(source, target):
                self.assertFalse(target.exists())
                target.write_bytes(source_bytes)
                raise FileExistsError("simulated concurrent identical publish")

            try:
                os.environ["APPDATA"] = str(app_data)
                worker._legacy_worker.publish_file_no_replace = publish_after_identical_race
                error = worker.restore_anki_media_file_direct(
                    source_path,
                    anki_media_dir,
                    filename,
                    expected_hash,
                    len(source_bytes),
                )
            finally:
                worker._legacy_worker.publish_file_no_replace = original_publish
                if original_app_data is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = original_app_data

            self.assertEqual(error, "")
            self.assertEqual(destination.read_bytes(), source_bytes)
            self.assertEqual(list(anki_media_dir.glob(".anki-card-generator-media-*.tmp")), [])

    def test_direct_media_restore_refuses_conflicting_file_created_during_publish(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app_data = Path(temp_dir) / "appdata"
            anki_media_dir = app_data / "Anki2" / "Profile" / "collection.media"
            anki_media_dir.mkdir(parents=True)
            filename = "race-conflict.mp3"
            destination = anki_media_dir / filename
            source_bytes = b"trusted media bytes"
            source_path = Path(temp_dir) / "source-conflict.mp3"
            source_path.write_bytes(source_bytes)
            conflicting_bytes = b"concurrent conflicting bytes"
            expected_hash = hashlib.sha256(source_bytes).hexdigest()
            original_app_data = os.environ.get("APPDATA")
            original_publish = worker._legacy_worker.publish_file_no_replace

            def publish_after_conflicting_race(source, target):
                self.assertFalse(target.exists())
                target.write_bytes(conflicting_bytes)
                raise FileExistsError("simulated concurrent conflicting publish")

            try:
                os.environ["APPDATA"] = str(app_data)
                worker._legacy_worker.publish_file_no_replace = publish_after_conflicting_race
                error = worker.restore_anki_media_file_direct(
                    source_path,
                    anki_media_dir,
                    filename,
                    expected_hash,
                    len(source_bytes),
                )
            finally:
                worker._legacy_worker.publish_file_no_replace = original_publish
                if original_app_data is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = original_app_data

            self.assertIn("同名媒体冲突", error)
            self.assertEqual(destination.read_bytes(), conflicting_bytes)
            self.assertEqual(list(anki_media_dir.glob(".anki-card-generator-media-*.tmp")), [])

    def test_trusted_media_restore_streams_64_mib_without_base64_or_anki_media_api(self):
        import tracemalloc

        chunk = b"x" * (1024 * 1024)
        chunk_count = 64
        expected_bytes = len(chunk) * chunk_count
        digest = hashlib.sha256()
        with tempfile.TemporaryDirectory() as temp_dir:
            app_data = Path(temp_dir) / "appdata"
            anki_dir = app_data / "Anki2" / "Profile" / "collection.media"
            anki_dir.mkdir(parents=True)
            export_dir = Path(temp_dir) / "export_media"
            export_dir.mkdir()
            media_name = "large-original.mp3"
            source_path = export_dir / media_name
            with source_path.open("wb") as handle:
                for _ in range(chunk_count):
                    handle.write(chunk)
                    digest.update(chunk)
            manifest = {
                media_name: {
                    "sha256": digest.hexdigest(),
                    "bytes": expected_bytes,
                }
            }
            original_app_data = os.environ.get("APPDATA")
            original_anki_connect = worker._legacy_worker.anki_connect
            original_read_bytes = Path.read_bytes
            original_b64encode = worker._legacy_worker.base64.b64encode
            original_b64decode = worker._legacy_worker.base64.b64decode

            def forbidden(*_args, **_kwargs):
                raise AssertionError("trusted streaming path must not whole-read or use Base64/Anki media APIs")

            try:
                os.environ["APPDATA"] = str(app_data)
                worker._legacy_worker.anki_connect = forbidden
                Path.read_bytes = forbidden
                worker._legacy_worker.base64.b64encode = forbidden
                worker._legacy_worker.base64.b64decode = forbidden
                tracemalloc.start()
                result = worker.restore_missing_anki_media(
                    [media_name],
                    manifest,
                    export_dir,
                    anki_dir,
                    "http://127.0.0.1:8765",
                )
                _, peak_bytes = tracemalloc.get_traced_memory()
                tracemalloc.stop()
            finally:
                if tracemalloc.is_tracing():
                    tracemalloc.stop()
                worker._legacy_worker.anki_connect = original_anki_connect
                Path.read_bytes = original_read_bytes
                worker._legacy_worker.base64.b64encode = original_b64encode
                worker._legacy_worker.base64.b64decode = original_b64decode
                if original_app_data is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = original_app_data

            destination = anki_dir / media_name
            self.assertEqual(result["restored"], [media_name])
            self.assertEqual(result["restored_by"][media_name], "trusted_atomic_copy")
            self.assertEqual(result["created"], [media_name])
            self.assertEqual(destination.stat().st_size, expected_bytes)
            self.assertEqual(worker._legacy_worker.file_sha256(destination), digest.hexdigest())
            self.assertLess(peak_bytes, 32 * 1024 * 1024)

    def test_nonstandard_media_dir_rejects_anki_connect_file_over_8_mib_without_api_call(self):
        source_bytes = b"x" * (worker._legacy_worker.ANKI_CONNECT_MEDIA_MAX_RAW_BYTES + 1)
        calls = []
        with tempfile.TemporaryDirectory() as temp_dir:
            export_dir = Path(temp_dir) / "export_media"
            export_dir.mkdir()
            media_name = "too-large.mp3"
            source_path = export_dir / media_name
            source_path.write_bytes(source_bytes)
            manifest = {
                media_name: {
                    "sha256": hashlib.sha256(source_bytes).hexdigest(),
                    "bytes": len(source_bytes),
                }
            }
            anki_dir = Path(temp_dir) / "portable" / "collection.media"
            anki_dir.mkdir(parents=True)
            original_anki_connect = worker._legacy_worker.anki_connect

            def forbidden_anki_connect(action, params=None, url=""):
                calls.append(action)
                raise AssertionError("over-limit fallback must fail before AnkiConnect")

            try:
                worker._legacy_worker.anki_connect = forbidden_anki_connect
                result = worker.restore_missing_anki_media(
                    [media_name],
                    manifest,
                    export_dir,
                    anki_dir,
                    "http://127.0.0.1:8765",
                )
            finally:
                worker._legacy_worker.anki_connect = original_anki_connect

        self.assertEqual(calls, [])
        self.assertEqual(result["restored"], [])
        self.assertEqual(result["failures"][0]["code"], "anki_connect_media_limit_exceeded")

    def test_nonstandard_media_dir_accepts_exact_8_mib_bounded_anki_connect_fallback(self):
        source_bytes = b"z" * worker._legacy_worker.ANKI_CONNECT_MEDIA_MAX_RAW_BYTES
        stored = {}
        with tempfile.TemporaryDirectory() as temp_dir:
            export_dir = Path(temp_dir) / "export_media"
            export_dir.mkdir()
            media_name = "inline-limit.mp3"
            source_path = export_dir / media_name
            source_path.write_bytes(source_bytes)
            manifest = {
                media_name: {
                    "sha256": hashlib.sha256(source_bytes).hexdigest(),
                    "bytes": len(source_bytes),
                }
            }
            anki_dir = Path(temp_dir) / "portable" / "collection.media"
            anki_dir.mkdir(parents=True)
            original_anki_connect = worker._legacy_worker.anki_connect

            def fake_anki_connect(action, params=None, url=""):
                params = params or {}
                if action == "retrieveMediaFile":
                    data = stored.get(params["filename"])
                    return base64.b64encode(data).decode("ascii") if data is not None else None
                if action == "storeMediaFile":
                    stored[params["filename"]] = base64.b64decode(params["data"], validate=True)
                    return params["filename"]
                raise AssertionError(action)

            try:
                worker._legacy_worker.anki_connect = fake_anki_connect
                result = worker.restore_missing_anki_media(
                    [media_name],
                    manifest,
                    export_dir,
                    anki_dir,
                    "http://127.0.0.1:8765",
                )
            finally:
                worker._legacy_worker.anki_connect = original_anki_connect

        self.assertEqual(result["restored"], [media_name])
        self.assertEqual(result["restored_by"][media_name], "anki_connect")
        self.assertEqual(stored[media_name], source_bytes)

    def test_anki_connect_media_decode_and_http_reader_enforce_hard_limits(self):
        class FakeResponse:
            def __init__(self, data, content_length=None):
                self.data = data
                self.headers = {}
                if content_length is not None:
                    self.headers["Content-Length"] = str(content_length)

            def read(self, amount=None):
                return self.data if amount is None else self.data[:amount]

        self.assertEqual(
            worker._legacy_worker._read_http_response_bytes(FakeResponse(b"1234"), 4),
            b"1234",
        )
        with self.assertRaisesRegex(RuntimeError, "ANKI_CONNECT_RESPONSE_TOO_LARGE"):
            worker._legacy_worker._read_http_response_bytes(FakeResponse(b"12345"), 4)
        with self.assertRaisesRegex(RuntimeError, "ANKI_CONNECT_RESPONSE_TOO_LARGE"):
            worker._legacy_worker._read_http_response_bytes(
                FakeResponse(b"", content_length=5),
                4,
            )
        with self.assertRaises(ValueError):
            worker._legacy_worker.decode_anki_media_base64("not base64!")
        with self.assertRaisesRegex(RuntimeError, "ANKI_CONNECT_RESPONSE_TOO_LARGE"):
            worker._legacy_worker.decode_anki_media_base64("A" * 9, max_raw_bytes=3)

    def test_anki_connect_health_check_uses_bounded_response(self):
        captured = {}
        original_http_json = worker._legacy_worker.http_json

        def fake_http_json(url, headers, body, timeout=60, max_response_bytes=None):
            captured["url"] = url
            captured["body"] = body
            captured["timeout"] = timeout
            captured["max_response_bytes"] = max_response_bytes
            return {"result": 6, "error": None}

        try:
            worker._legacy_worker.http_json = fake_http_json
            ok, detail = worker._legacy_worker.check_anki_connect()
        finally:
            worker._legacy_worker.http_json = original_http_json

        self.assertTrue(ok)
        self.assertEqual(detail, "AnkiConnect 6")
        self.assertEqual(captured["body"]["action"], "version")
        self.assertEqual(
            captured["max_response_bytes"],
            worker._legacy_worker.ANKI_CONNECT_SMALL_RESPONSE_MAX_BYTES,
        )

    def test_anki_connect_routes_every_action_through_expected_response_cap(self):
        captured = []
        original_http_json = worker._legacy_worker.http_json

        def fake_http_json(url, headers, body, timeout=60, max_response_bytes=None):
            captured.append((body["action"], max_response_bytes))
            return {"result": None, "error": None}

        try:
            worker._legacy_worker.http_json = fake_http_json
            for action in ("retrieveMediaFile", "storeMediaFile", "cardsInfo"):
                worker._legacy_worker.anki_connect(action)
        finally:
            worker._legacy_worker.http_json = original_http_json

        self.assertEqual(
            captured,
            [
                (
                    "retrieveMediaFile",
                    worker._legacy_worker.ANKI_CONNECT_RETRIEVE_MAX_JSON_BYTES,
                ),
                (
                    "storeMediaFile",
                    worker._legacy_worker.ANKI_CONNECT_SMALL_RESPONSE_MAX_BYTES,
                ),
                (
                    "cardsInfo",
                    worker._legacy_worker.ANKI_CONNECT_DEFAULT_RESPONSE_MAX_BYTES,
                ),
            ],
        )

    def test_direct_media_restore_rejects_source_symlink_without_writing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app_data = Path(temp_dir) / "appdata"
            anki_dir = app_data / "Anki2" / "Profile" / "collection.media"
            anki_dir.mkdir(parents=True)
            source_target = Path(temp_dir) / "source-target.mp3"
            source_target.write_bytes(b"trusted media")
            source_link = Path(temp_dir) / "source-link.mp3"
            try:
                os.symlink(source_target, source_link)
            except OSError as err:
                self.skipTest(f"symlink creation is unavailable: {err}")
            original_app_data = os.environ.get("APPDATA")
            try:
                os.environ["APPDATA"] = str(app_data)
                result = worker._legacy_worker._restore_anki_media_file_direct_result(
                    source_link,
                    anki_dir,
                    "target.mp3",
                    hashlib.sha256(b"trusted media").hexdigest(),
                    len(b"trusted media"),
                )
            finally:
                if original_app_data is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = original_app_data

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "unsafe_source_or_name")
        self.assertFalse((anki_dir / "target.mp3").exists())

    def test_trusted_media_directory_rejects_reparse_component(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app_data = Path(temp_dir) / "appdata"
            anki_dir = app_data / "Anki2" / "Profile" / "collection.media"
            anki_dir.mkdir(parents=True)
            export_dir = Path(temp_dir) / "export_media"
            export_dir.mkdir()
            media_name = "reparse.mp3"
            source_bytes = b"trusted media"
            source_path = export_dir / media_name
            source_path.write_bytes(source_bytes)
            manifest = {
                media_name: {
                    "sha256": hashlib.sha256(source_bytes).hexdigest(),
                    "bytes": len(source_bytes),
                }
            }
            original_app_data = os.environ.get("APPDATA")
            original_reparse_check = worker._legacy_worker._path_is_reparse
            original_anki_connect = worker._legacy_worker.anki_connect

            def fake_reparse_check(path, info=None):
                if Path(path) == anki_dir:
                    return True
                return original_reparse_check(Path(path), info)

            def forbidden_anki_connect(*_args, **_kwargs):
                raise AssertionError("reparse media directory must fail before AnkiConnect")

            try:
                os.environ["APPDATA"] = str(app_data)
                worker._legacy_worker._path_is_reparse = fake_reparse_check
                worker._legacy_worker.anki_connect = forbidden_anki_connect
                trusted = worker._legacy_worker.trusted_anki_media_directory(anki_dir)
                result = worker.restore_missing_anki_media(
                    [media_name],
                    manifest,
                    export_dir,
                    anki_dir,
                    "http://127.0.0.1:8765",
                )
            finally:
                worker._legacy_worker._path_is_reparse = original_reparse_check
                worker._legacy_worker.anki_connect = original_anki_connect
                if original_app_data is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = original_app_data

        self.assertFalse(trusted)
        self.assertEqual(result["restored"], [])
        self.assertEqual(result["failures"][0]["code"], "unsafe_source_or_name")

    def test_already_present_media_in_reparse_directory_blocks_import(self):
        calls = []
        with tempfile.TemporaryDirectory() as temp_dir:
            app_data = Path(temp_dir) / "appdata"
            anki_dir = app_data / "Anki2" / "Profile" / "collection.media"
            anki_dir.mkdir(parents=True)
            export_dir = Path(temp_dir) / "export_media"
            export_dir.mkdir()
            media_name = "already-present.mp3"
            media_bytes = b"trusted media"
            (export_dir / media_name).write_bytes(media_bytes)
            (anki_dir / media_name).write_bytes(media_bytes)
            manifest = worker.media_manifest([str(export_dir / media_name)])
            apkg_path = Path(temp_dir) / "deck.apkg"
            apkg_path.write_bytes(b"fake apkg")
            original_app_data = os.environ.get("APPDATA")
            original_reparse_check = worker._legacy_worker._path_is_reparse
            original_anki_connect = worker._legacy_worker.anki_connect

            def fake_reparse_check(path, info=None):
                if Path(path) == anki_dir:
                    return True
                return original_reparse_check(Path(path), info)

            def fake_anki_connect(action, params=None, url=""):
                calls.append(action)
                if action == "getMediaDirPath":
                    return str(anki_dir)
                if action == "importPackage":
                    raise AssertionError("reparse media directory must block importPackage")
                raise AssertionError(action)

            try:
                os.environ["APPDATA"] = str(app_data)
                worker._legacy_worker._path_is_reparse = fake_reparse_check
                worker._legacy_worker.anki_connect = fake_anki_connect
                result = worker.handle_verify_anki_import(
                    {
                        "import_apkg": True,
                        "export_result": {
                            "apkg_path": str(apkg_path),
                            "deck_name": "Reparse Already Present",
                            "cards": 1,
                            "media_manifest": manifest,
                            "media_summary": {
                                "media_files": 1,
                                "media_bytes": len(media_bytes),
                            },
                            "media_dir": str(export_dir),
                        },
                    }
                )
            finally:
                worker._legacy_worker._path_is_reparse = original_reparse_check
                worker._legacy_worker.anki_connect = original_anki_connect
                if original_app_data is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = original_app_data

        self.assertFalse(result["ok"])
        self.assertIn("anki_media_preload_conflict", result["failed_checks"])
        self.assertEqual(calls, ["getMediaDirPath"])

    def test_partial_media_preload_reports_created_file_and_blocks_import(self):
        calls = []
        with tempfile.TemporaryDirectory() as temp_dir:
            app_data = Path(temp_dir) / "appdata"
            anki_dir = app_data / "Anki2" / "Profile" / "collection.media"
            anki_dir.mkdir(parents=True)
            export_dir = Path(temp_dir) / "export_media"
            export_dir.mkdir()
            first_name = "a-valid.mp3"
            second_name = "b-tampered.mp3"
            first_path = export_dir / first_name
            second_path = export_dir / second_name
            first_path.write_bytes(b"valid first media")
            second_path.write_bytes(b"original second")
            manifest = worker.media_manifest([str(first_path), str(second_path)])
            second_path.write_bytes(b"tampered second")
            apkg_path = Path(temp_dir) / "deck.apkg"
            apkg_path.write_bytes(b"fake apkg")
            original_app_data = os.environ.get("APPDATA")
            original_anki_connect = worker._legacy_worker.anki_connect

            def fake_anki_connect(action, params=None, url=""):
                calls.append(action)
                if action == "getMediaDirPath":
                    return str(anki_dir)
                if action == "importPackage":
                    raise AssertionError("partial media preload must block importPackage")
                raise AssertionError(action)

            try:
                os.environ["APPDATA"] = str(app_data)
                worker._legacy_worker.anki_connect = fake_anki_connect
                result = worker.handle_verify_anki_import(
                    {
                        "import_apkg": True,
                        "export_result": {
                            "apkg_path": str(apkg_path),
                            "deck_name": "Partial Recovery",
                            "cards": 1,
                            "media_manifest": manifest,
                            "media_summary": {"media_files": 2},
                            "media_dir": str(export_dir),
                        },
                    }
                )
            finally:
                worker._legacy_worker.anki_connect = original_anki_connect
                if original_app_data is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = original_app_data

        self.assertFalse(result["ok"])
        self.assertNotIn("importPackage", calls)
        self.assertEqual(result["media_recovered_count"], 1)
        self.assertEqual(result["media_recovered"], [first_name])
        self.assertEqual(result["media_recovery_methods"][first_name], "trusted_atomic_copy")
        ledger = result["media_recovery_ownership_ledger"]
        self.assertEqual([item["state"] for item in ledger], ["created", "failed"])
        self.assertEqual(result["media_recovery_failures"][0]["code"], "source_integrity_failed")

    def test_anki_connect_timeout_reconciles_exact_media_but_rejects_conflict(self):
        source_bytes = b"small bounded media"
        with tempfile.TemporaryDirectory() as temp_dir:
            export_dir = Path(temp_dir) / "export_media"
            export_dir.mkdir()
            media_name = "timeout.mp3"
            source_path = export_dir / media_name
            source_path.write_bytes(source_bytes)
            manifest = {
                media_name: {
                    "sha256": hashlib.sha256(source_bytes).hexdigest(),
                    "bytes": len(source_bytes),
                }
            }
            anki_dir = Path(temp_dir) / "portable" / "collection.media"
            anki_dir.mkdir(parents=True)
            original_anki_connect = worker._legacy_worker.anki_connect

            for stored_bytes, expected_ok in (
                (source_bytes, True),
                (b"conflicting media", False),
            ):
                calls = {"retrieve": 0}

                def fake_anki_connect(action, params=None, url=""):
                    if action == "retrieveMediaFile":
                        calls["retrieve"] += 1
                        if calls["retrieve"] == 1:
                            return None
                        return base64.b64encode(stored_bytes).decode("ascii")
                    if action == "storeMediaFile":
                        raise TimeoutError("simulated timeout after unknown write outcome")
                    raise AssertionError(action)

                try:
                    worker._legacy_worker.anki_connect = fake_anki_connect
                    result = worker.restore_missing_anki_media(
                        [media_name],
                        manifest,
                        export_dir,
                        anki_dir,
                        "http://127.0.0.1:8765",
                    )
                finally:
                    worker._legacy_worker.anki_connect = original_anki_connect

                with self.subTest(expected_ok=expected_ok):
                    if expected_ok:
                        self.assertEqual(result["restored_by"][media_name], "anki_connect_reconciled")
                        self.assertEqual(result["failures"], [])
                    else:
                        self.assertEqual(result["restored"], [])
                        self.assertEqual(result["failures"][0]["code"], "destination_conflict")

    def test_anki_connect_unexpected_stored_name_records_possible_orphan(self):
        source_bytes = b"small bounded media"
        with tempfile.TemporaryDirectory() as temp_dir:
            export_dir = Path(temp_dir) / "export_media"
            export_dir.mkdir()
            media_name = "orphan.mp3"
            source_path = export_dir / media_name
            source_path.write_bytes(source_bytes)
            manifest = {
                media_name: {
                    "sha256": hashlib.sha256(source_bytes).hexdigest(),
                    "bytes": len(source_bytes),
                }
            }
            anki_dir = Path(temp_dir) / "portable" / "collection.media"
            anki_dir.mkdir(parents=True)
            original_anki_connect = worker._legacy_worker.anki_connect

            def fake_anki_connect(action, params=None, url=""):
                if action == "retrieveMediaFile":
                    return None
                if action == "storeMediaFile":
                    return "orphan_1.mp3"
                raise AssertionError(action)

            try:
                worker._legacy_worker.anki_connect = fake_anki_connect
                result = worker.restore_missing_anki_media(
                    [media_name],
                    manifest,
                    export_dir,
                    anki_dir,
                    "http://127.0.0.1:8765",
                )
            finally:
                worker._legacy_worker.anki_connect = original_anki_connect

        self.assertEqual(result["restored"], [])
        self.assertEqual(result["failures"][0]["code"], "anki_connect_store_failed")
        self.assertEqual(result["failures"][0]["possible_orphan"], "orphan_1.mp3")
        self.assertEqual(
            result["ownership_ledger"][0]["possible_orphan"],
            "orphan_1.mp3",
        )

    def test_direct_post_write_cleanup_failure_is_truthful_in_ownership_ledger(self):
        source_bytes = b"trusted media bytes"
        with tempfile.TemporaryDirectory() as temp_dir:
            app_data = Path(temp_dir) / "appdata"
            anki_dir = app_data / "Anki2" / "Profile" / "collection.media"
            anki_dir.mkdir(parents=True)
            export_dir = Path(temp_dir) / "export_media"
            export_dir.mkdir()
            media_name = "locked.mp3"
            source_path = export_dir / media_name
            source_path.write_bytes(source_bytes)
            manifest = {
                media_name: {
                    "sha256": hashlib.sha256(source_bytes).hexdigest(),
                    "bytes": len(source_bytes),
                }
            }
            original_app_data = os.environ.get("APPDATA")
            original_verify = worker._legacy_worker._verify_media_file_path
            original_cleanup = worker._legacy_worker._safe_unlink_owned_file

            def fail_final_verify(path, expected_hash, expected_bytes):
                return "simulated final verification failure", None

            def fail_cleanup(path, identity):
                return False, "simulated Windows file lock"

            try:
                os.environ["APPDATA"] = str(app_data)
                worker._legacy_worker._verify_media_file_path = fail_final_verify
                worker._legacy_worker._safe_unlink_owned_file = fail_cleanup
                result = worker.restore_missing_anki_media(
                    [media_name],
                    manifest,
                    export_dir,
                    anki_dir,
                    "http://127.0.0.1:8765",
                )
            finally:
                worker._legacy_worker._verify_media_file_path = original_verify
                worker._legacy_worker._safe_unlink_owned_file = original_cleanup
                if original_app_data is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = original_app_data

            self.assertTrue((anki_dir / media_name).exists())

        self.assertEqual(result["restored"], [])
        self.assertTrue(result["failures"][0]["possible_partial_write"])
        self.assertEqual(result["failures"][0]["cleanup_error"], "simulated Windows file lock")
        self.assertTrue(result["ownership_ledger"][0]["possible_partial_write"])
        self.assertEqual(
            result["ownership_ledger"][0]["cleanup_error"],
            "simulated Windows file lock",
        )

    def test_direct_temporary_cleanup_failure_is_truthful_in_ownership_ledger(self):
        source_bytes = b"trusted media bytes"
        with tempfile.TemporaryDirectory() as temp_dir:
            app_data = Path(temp_dir) / "appdata"
            anki_dir = app_data / "Anki2" / "Profile" / "collection.media"
            anki_dir.mkdir(parents=True)
            export_dir = Path(temp_dir) / "export_media"
            export_dir.mkdir()
            media_name = "temporary-locked.mp3"
            source_path = export_dir / media_name
            source_path.write_bytes(source_bytes)
            manifest = {
                media_name: {
                    "sha256": hashlib.sha256(b"different media bytes").hexdigest(),
                    "bytes": len(source_bytes),
                }
            }
            original_app_data = os.environ.get("APPDATA")
            original_cleanup = worker._legacy_worker._safe_unlink_owned_file

            def fail_temporary_cleanup(path, identity):
                if path is not None and Path(path).suffix == ".tmp":
                    return False, "simulated temporary file lock"
                return original_cleanup(path, identity)

            try:
                os.environ["APPDATA"] = str(app_data)
                worker._legacy_worker._safe_unlink_owned_file = fail_temporary_cleanup
                result = worker.restore_missing_anki_media(
                    [media_name],
                    manifest,
                    export_dir,
                    anki_dir,
                    "http://127.0.0.1:8765",
                )
            finally:
                worker._legacy_worker._safe_unlink_owned_file = original_cleanup
                if original_app_data is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = original_app_data

        self.assertEqual(result["restored"], [])
        self.assertEqual(result["failures"][0]["code"], "source_integrity_failed")
        self.assertTrue(result["failures"][0]["possible_partial_write"])
        self.assertEqual(
            result["failures"][0]["cleanup_error"],
            "simulated temporary file lock",
        )
        self.assertTrue(result["ownership_ledger"][0]["possible_partial_write"])
        self.assertEqual(
            result["ownership_ledger"][0]["cleanup_error"],
            "simulated temporary file lock",
        )

    def test_direct_media_restore_rejects_short_long_and_wrong_hash_sources(self):
        source_bytes = b"trusted media bytes"
        with tempfile.TemporaryDirectory() as temp_dir:
            app_data = Path(temp_dir) / "appdata"
            anki_dir = app_data / "Anki2" / "Profile" / "collection.media"
            anki_dir.mkdir(parents=True)
            source_path = Path(temp_dir) / "source.mp3"
            source_path.write_bytes(source_bytes)
            original_app_data = os.environ.get("APPDATA")
            try:
                os.environ["APPDATA"] = str(app_data)
                cases = (
                    ("short.mp3", len(source_bytes) + 1, hashlib.sha256(source_bytes).hexdigest()),
                    ("long.mp3", len(source_bytes) - 1, hashlib.sha256(source_bytes[:-1]).hexdigest()),
                    ("hash.mp3", len(source_bytes), hashlib.sha256(b"different").hexdigest()),
                )
                for filename, expected_bytes, expected_hash in cases:
                    with self.subTest(filename=filename):
                        result = worker._legacy_worker._restore_anki_media_file_direct_result(
                            source_path,
                            anki_dir,
                            filename,
                            expected_hash,
                            expected_bytes,
                        )
                        self.assertFalse(result["ok"])
                        self.assertEqual(result["code"], "source_integrity_failed")
                        self.assertFalse((anki_dir / filename).exists())
            finally:
                if original_app_data is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = original_app_data

    def test_direct_media_restore_stops_when_trusted_directory_identity_changes(self):
        source_bytes = b"trusted media bytes"
        with tempfile.TemporaryDirectory() as temp_dir:
            anki_dir = Path(temp_dir) / "collection.media"
            anki_dir.mkdir()
            source_path = Path(temp_dir) / "source.mp3"
            source_path.write_bytes(source_bytes)
            original_identity = worker._legacy_worker._trusted_anki_media_directory_identity
            calls = {"count": 0}

            def changing_identity(_path):
                calls["count"] += 1
                return (1, 1) if calls["count"] == 1 else (1, 2)

            try:
                worker._legacy_worker._trusted_anki_media_directory_identity = changing_identity
                result = worker._legacy_worker._restore_anki_media_file_direct_result(
                    source_path,
                    anki_dir,
                    "identity.mp3",
                    hashlib.sha256(source_bytes).hexdigest(),
                    len(source_bytes),
                )
            finally:
                worker._legacy_worker._trusted_anki_media_directory_identity = original_identity

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "trusted_stream_copy_failed")
        self.assertIn("目录身份", result["error"])

    def test_direct_post_publish_directory_change_marks_cleanup_unproven(self):
        source_bytes = b"trusted media bytes"
        with tempfile.TemporaryDirectory() as temp_dir:
            anki_dir = Path(temp_dir) / "collection.media"
            anki_dir.mkdir()
            source_path = Path(temp_dir) / "source.mp3"
            source_path.write_bytes(source_bytes)
            original_identity = worker._legacy_worker._trusted_anki_media_directory_identity
            calls = {"count": 0}

            def changing_identity(_path):
                calls["count"] += 1
                return (1, 1) if calls["count"] <= 2 else (1, 2)

            try:
                worker._legacy_worker._trusted_anki_media_directory_identity = changing_identity
                result = worker._legacy_worker._restore_anki_media_file_direct_result(
                    source_path,
                    anki_dir,
                    "identity-after-publish.mp3",
                    hashlib.sha256(source_bytes).hexdigest(),
                    len(source_bytes),
                )
            finally:
                worker._legacy_worker._trusted_anki_media_directory_identity = original_identity

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "post_write_integrity_failed")
        self.assertTrue(result["possible_partial_write"])
        self.assertTrue(result["cleanup_unproven"])
        self.assertIn("无法证明", result["cleanup_error"])

    def test_final_media_barrier_blocks_import_if_media_disappears(self):
        calls = []
        with tempfile.TemporaryDirectory() as temp_dir:
            apkg_path = Path(temp_dir) / "deck.apkg"
            apkg_path.write_bytes(b"fake apkg")
            export_dir = Path(temp_dir) / "export_media"
            export_dir.mkdir()
            media_name = "barrier.mp3"
            media_bytes = b"barrier media"
            source_path = export_dir / media_name
            source_path.write_bytes(media_bytes)
            manifest = worker.media_manifest([str(source_path)])
            anki_dir = Path(temp_dir) / "portable" / "collection.media"
            anki_dir.mkdir(parents=True)
            (anki_dir / media_name).write_bytes(media_bytes)
            original_anki_connect = worker._legacy_worker.anki_connect
            original_inspect = worker._legacy_worker.inspect_anki_media_for_preload
            inspect_calls = {"count": 0}

            def fake_anki_connect(action, params=None, url=""):
                calls.append(action)
                if action == "getMediaDirPath":
                    return str(anki_dir)
                if action == "findCards":
                    return []
                if action == "importPackage":
                    raise AssertionError("final media barrier must block importPackage")
                raise AssertionError(action)

            def disappearing_inspect(expected, media_dir):
                inspect_calls["count"] += 1
                if inspect_calls["count"] >= 3:
                    return {
                        "missing": [media_name],
                        "already_present": [],
                        "conflicts": [],
                        "failures": [],
                    }
                return original_inspect(expected, media_dir)

            try:
                worker._legacy_worker.anki_connect = fake_anki_connect
                worker._legacy_worker.inspect_anki_media_for_preload = disappearing_inspect
                result = worker.handle_verify_anki_import(
                    {
                        "import_apkg": True,
                        "export_result": {
                            "apkg_path": str(apkg_path),
                            "deck_name": "Barrier",
                            "cards": 1,
                            "media_manifest": manifest,
                            "media_summary": {"media_files": 1},
                            "media_dir": str(export_dir),
                        },
                    }
                )
            finally:
                worker._legacy_worker.anki_connect = original_anki_connect
                worker._legacy_worker.inspect_anki_media_for_preload = original_inspect

        self.assertFalse(result["ok"])
        self.assertEqual(result["failed_checks"], ["anki_media_final_barrier_failed"])
        self.assertNotIn("importPackage", calls)

    def test_post_import_media_recovery_failure_can_never_report_ok(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            apkg_path = Path(temp_dir) / "deck.apkg"
            apkg_path.write_bytes(b"fake apkg")
            export_dir = Path(temp_dir) / "export_media"
            export_dir.mkdir()
            media_name = "post-import.mp3"
            media_bytes = b"post import media"
            source_path = export_dir / media_name
            source_path.write_bytes(media_bytes)
            manifest = worker.media_manifest([str(source_path)])
            anki_dir = Path(temp_dir) / "portable" / "collection.media"
            anki_dir.mkdir(parents=True)
            (anki_dir / media_name).write_bytes(media_bytes)
            original_anki_connect = worker._legacy_worker.anki_connect
            original_compare = worker._legacy_worker.compare_media_manifest
            original_restore = worker._legacy_worker.restore_missing_anki_media
            compare_calls = {"count": 0}

            def fake_anki_connect(action, params=None, url=""):
                if action == "getMediaDirPath":
                    return str(anki_dir)
                if action == "findCards":
                    return [123]
                if action == "cardsInfo":
                    return [
                        {
                            "cardId": 123,
                            "fields": {
                                "Audio": {"value": worker.anki_audio_html(media_name)},
                            },
                        }
                    ]
                if action == "importPackage":
                    return True
                raise AssertionError(action)

            def fake_compare(expected, media_dir, **kwargs):
                compare_calls["count"] += 1
                if compare_calls["count"] == 1:
                    return {
                        "checked": 0,
                        "missing": [media_name],
                        "mismatched": [],
                        "inaccessible": [],
                    }
                return {
                    "checked": 1,
                    "missing": [],
                    "mismatched": [],
                    "inaccessible": [],
                }

            def fake_restore(missing_names, *args, **kwargs):
                if not missing_names:
                    return {
                        "attempted": False,
                        "restored": [],
                        "restored_by": {},
                        "failures": [],
                        "ownership_ledger": [],
                        "created": [],
                        "already_present": [],
                        "failed": [],
                    }
                failure = {
                    "file": media_name,
                    "code": "post_write_integrity_failed",
                    "error": "simulated post-import recovery failure",
                }
                return {
                    "attempted": True,
                    "restored": [],
                    "restored_by": {},
                    "failures": [failure],
                    "ownership_ledger": [{"file": media_name, "state": "failed", **failure}],
                    "created": [],
                    "already_present": [],
                    "failed": [media_name],
                }

            try:
                worker._legacy_worker.anki_connect = fake_anki_connect
                worker._legacy_worker.compare_media_manifest = fake_compare
                worker._legacy_worker.restore_missing_anki_media = fake_restore
                result = worker.handle_verify_anki_import(
                    {
                        "import_apkg": True,
                        "export_result": {
                            "apkg_path": str(apkg_path),
                            "deck_name": "Post Import Failure",
                            "cards": 1,
                            "media_manifest": manifest,
                            "media_summary": {"media_files": 1},
                            "media_dir": str(export_dir),
                        },
                    }
                )
            finally:
                worker._legacy_worker.anki_connect = original_anki_connect
                worker._legacy_worker.compare_media_manifest = original_compare
                worker._legacy_worker.restore_missing_anki_media = original_restore

        self.assertFalse(result["ok"])
        self.assertIn("anki_media_recovery_failed", result["failed_checks"])
        self.assertEqual(len(result["media_recovery_failures"]), 1)

    def test_verify_anki_import_refuses_media_recovery_when_export_hash_changed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            apkg_path = Path(temp_dir) / "deck.apkg"
            apkg_path.write_bytes(b"fake apkg")
            export_dir = Path(temp_dir) / "export_media"
            export_dir.mkdir()
            media_name = "sample_original.mp3"
            media_path = export_dir / media_name
            media_path.write_bytes(b"trusted media bytes")
            manifest = worker.media_manifest([str(media_path)])
            media_path.write_bytes(b"tampered media bytes")
            anki_dir = Path(temp_dir) / "anki_media"
            anki_dir.mkdir()
            original_anki_connect = worker._legacy_worker.anki_connect

            def fake_anki_connect(action, params=None, url=""):
                if action == "importPackage":
                    return True
                if action == "findCards":
                    return [123]
                if action == "cardsInfo":
                    return [
                        {
                            "cardId": 123,
                            "fields": {
                                "Audio": {"value": worker.anki_audio_html(media_name)},
                            },
                        }
                    ]
                if action == "getMediaDirPath":
                    return str(anki_dir)
                if action == "storeMediaFile":
                    raise AssertionError("tampered media must not be uploaded")
                raise AssertionError(action)

            try:
                worker._legacy_worker.anki_connect = fake_anki_connect
                result = worker.handle_verify_anki_import(
                    {
                        "import_apkg": True,
                        "export_result": {
                            "apkg_path": str(apkg_path),
                            "deck_name": "Media Recovery",
                            "cards": 1,
                            "media_manifest": manifest,
                            "media_summary": {"media_files": 1},
                            "media_dir": str(export_dir),
                        },
                    }
                )
            finally:
                worker._legacy_worker.anki_connect = original_anki_connect

        self.assertFalse(result["ok"])
        self.assertIn("anki_media_source_integrity_failed", result["failed_checks"])
        self.assertIn("媒体内容与导出清单不一致", result["message"])
        self.assertEqual(result["media_recovered_count"], 0)
        self.assertEqual(len(result["media_recovery_failures"]), 1)
        self.assertIn("哈希", result["media_recovery_failures"][0]["error"])

    def test_verify_anki_import_fails_when_requested_apkg_is_missing(self):
        result = worker.handle_verify_anki_import(
            {
                "import_apkg": True,
                "export_result": {
                    "apkg_path": "E:\\missing\\deck.apkg",
                    "deck_name": "Missing APKG",
                    "cards": 1,
                    "media_manifest": {},
                    "media_summary": {"media_files": 0},
                    "media_dir": "",
                },
            }
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["failed_checks"], ["apkg_missing_for_import"])
        self.assertTrue(result["import_attempted"])
        self.assertFalse(result["import_result"])

    def test_verify_anki_import_uses_exported_template_tag(self):
        calls = []
        with tempfile.TemporaryDirectory() as temp_dir:
            anki_dir = Path(temp_dir) / "anki_media"
            anki_dir.mkdir()
            original_anki_connect = worker._legacy_worker.anki_connect

            def fake_anki_connect(action, params=None, url=""):
                calls.append((action, params or {}))
                if action == "findCards":
                    return [123]
                if action == "cardsInfo":
                    return [
                        {
                            "cardId": 123,
                            "fields": {
                                "Video": {"value": ""},
                                "Audio": {"value": ""},
                                "TtsAudio": {"value": ""},
                                "PhraseTtsAudio": {"value": ""},
                            },
                        }
                    ]
                if action == "getMediaDirPath":
                    return str(anki_dir)
                raise AssertionError(action)

            try:
                worker._legacy_worker.anki_connect = fake_anki_connect
                result = worker.handle_verify_anki_import(
                    {
                        "export_result": {
                            "deck_name": "V11 Deck",
                            "cards": 1,
                            "template_version": "V11",
                            "anki_tag": "anki_card_generator_v11",
                            "media_manifest": {},
                            "media_summary": {"media_files": 0},
                            "media_dir": str(Path(temp_dir) / "export_media"),
                        }
                    }
                )
            finally:
                worker._legacy_worker.anki_connect = original_anki_connect

        self.assertTrue(result["ok"])
        find_query = next(params["query"] for action, params in calls if action == "findCards")
        self.assertIn('tag:"anki_card_generator_v11"', find_query)
        self.assertNotIn("tag:anki_card_generator_v10", find_query)

    def test_verify_anki_import_accepts_explicit_anki_query(self):
        calls = []
        with tempfile.TemporaryDirectory() as temp_dir:
            anki_dir = Path(temp_dir) / "anki_media"
            anki_dir.mkdir()
            original_anki_connect = worker._legacy_worker.anki_connect

            def fake_anki_connect(action, params=None, url=""):
                calls.append((action, params or {}))
                if action == "findCards":
                    return [123, 456]
                if action == "cardsInfo":
                    return [
                        {
                            "cardId": 123,
                            "fields": {
                                "CardId": {"value": "doc_e2e_0001"},
                                "FrontContent": {"value": "Question one"},
                                "Answer": {"value": "Answer one"},
                                "Video": {"value": ""},
                                "Audio": {"value": ""},
                                "TtsAudio": {"value": ""},
                                "PhraseTtsAudio": {"value": ""},
                            },
                            "modelName": "Anki Card Generator V10 - 文档知识 V10",
                            "deckName": "文档知识卡::Document E2E",
                        },
                        {
                            "cardId": 456,
                            "fields": {
                                "CardId": {"value": "doc_e2e_0002"},
                                "FrontContent": {"value": "Question two"},
                                "Answer": {"value": "Answer two"},
                                "Video": {"value": ""},
                                "Audio": {"value": ""},
                                "TtsAudio": {"value": ""},
                                "PhraseTtsAudio": {"value": ""},
                            },
                            "modelName": "Anki Card Generator V10 - 文档知识 V10",
                            "deckName": "文档知识卡::Document E2E",
                        },
                    ]
                if action == "getMediaDirPath":
                    return str(anki_dir)
                raise AssertionError(action)

            try:
                worker._legacy_worker.anki_connect = fake_anki_connect
                result = worker.handle_verify_anki_import(
                    {
                        "anki_query": 'tag:anki_card_generator_v10 CardId:doc_e2e_*',
                        "export_result": {
                            "deck_name": "文档知识卡::Document E2E",
                            "deck_kind": "document_knowledge",
                            "cards": 2,
                            "media_manifest": {},
                            "media_summary": {"media_files": 0},
                            "media_dir": str(Path(temp_dir) / "export_media"),
                        },
                    }
                )
            finally:
                worker._legacy_worker.anki_connect = original_anki_connect

        self.assertTrue(result["ok"])
        self.assertEqual(result["card_count"], 2)
        find_query = next(params["query"] for action, params in calls if action == "findCards")
        self.assertEqual(find_query, "tag:anki_card_generator_v10 CardId:doc_e2e_*")
        self.assertNotIn('deck:"文档知识卡::Document E2E"', find_query)

    def test_verify_anki_import_checks_video_fields_pronunciation_and_tts_hashes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            anki_dir = Path(temp_dir) / "anki_media"
            anki_dir.mkdir()
            sentence = "We take public trust seriously."
            answer = "take public trust seriously"
            sentence_hash = worker.media_text_hash(sentence)
            phrase_hash = worker.media_text_hash(answer)
            media_names = [
                "sample_clip.webm",
                "sample_clip.mp4",
                "sample_clip.jpg",
                "sample_original.mp3",
                f"sample_tts_{sentence_hash}.mp3",
                f"sample_phrase_{phrase_hash}.mp3",
            ]
            for name in media_names:
                (anki_dir / name).write_bytes(f"media:{name}".encode("utf-8"))
            media_ledger = [
                {
                    "file": f"sample_tts_{sentence_hash}.mp3",
                    "role": "sentence_tts",
                    "tts_text": sentence,
                    "text_hash": sentence_hash,
                },
                {
                    "file": f"sample_phrase_{phrase_hash}.mp3",
                    "role": "phrase_tts",
                    "tts_text": answer,
                    "text_hash": phrase_hash,
                },
            ]
            original_anki_connect = worker._legacy_worker.anki_connect
            original_audio_duration_seconds = worker._legacy_worker.audio_duration_seconds

            def fake_audio_duration_seconds(path):
                name = Path(path).name
                if name.endswith((".mp4", ".webm")):
                    return 2.0
                if "phrase" in name:
                    return 1.7
                if name.endswith(".mp3"):
                    return 2.4
                return None

            def fake_anki_connect(action, params=None, url=""):
                if action == "findCards":
                    return [123]
                if action == "cardsInfo":
                    return [
                        {
                            "cardId": 123,
                            "deckName": "Video Gate Deck",
                            "modelName": "Anki Card Generator V12 - 沉浸复读 V11",
                            "fields": {
                                "CardId": {"value": "card-1"},
                                "Video": {
                                    "value": worker.anki_video_html(
                                        "sample_clip.webm",
                                        "sample_clip.mp4",
                                        "sample_clip.jpg",
                                    )
                                },
                                "Audio": {"value": worker.anki_audio_html("sample_original.mp3")},
                                "TtsAudio": {"value": worker.anki_audio_html(f"sample_tts_{sentence_hash}.mp3")},
                                "PhraseTtsAudio": {"value": worker.anki_audio_html(f"sample_phrase_{phrase_hash}.mp3")},
                                "PronunciationMeta": {"value": json.dumps({"status": "ok"})},
                                "English": {"value": sentence},
                                "Answer": {"value": answer},
                            },
                        }
                    ]
                if action == "getMediaDirPath":
                    return str(anki_dir)
                raise AssertionError(action)

            try:
                worker._legacy_worker.audio_duration_seconds = fake_audio_duration_seconds
                manifest = worker.media_manifest([str(anki_dir / name) for name in media_names], media_ledger)
                worker._legacy_worker.anki_connect = fake_anki_connect
                result = worker.handle_verify_anki_import(
                    {
                        "export_result": {
                            "deck_name": "Video Gate Deck",
                            "deck_kind": "video_language",
                            "cards": 1,
                            "template_version": "V12",
                            "anki_tag": "anki_card_generator_v12",
                            "media_manifest": manifest,
                            "media_ledger": media_ledger,
                            "card_media_ledger": [
                                {
                                    "card_id": "card-1",
                                    "learning_point_id": "lp-1",
                                    "segment_id": "seg-1",
                                    "answer": answer,
                                    "sentence_tts_text": sentence,
                                    "phrase_tts_text": answer,
                                    "video_webm": "sample_clip.webm",
                                    "video_mp4": "sample_clip.mp4",
                                    "poster": "sample_clip.jpg",
                                    "original_audio": "sample_original.mp3",
                                    "sentence_tts_audio": f"sample_tts_{sentence_hash}.mp3",
                                    "phrase_tts_audio": f"sample_phrase_{phrase_hash}.mp3",
                                }
                            ],
                            "media_summary": {"media_files": len(media_names)},
                            "media_dir": str(anki_dir),
                        }
                    }
                )
            finally:
                worker._legacy_worker.anki_connect = original_anki_connect
                worker._legacy_worker.audio_duration_seconds = original_audio_duration_seconds

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["failed_checks"], [])
        self.assertEqual(result["media_ledger_card_text_mismatches"], [])

    def test_verify_anki_import_rejects_question_mark_corrupted_study_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            anki_dir = Path(temp_dir) / "anki_media"
            anki_dir.mkdir()
            sentence = "This is a demanding job."
            answer = "demanding job"
            sentence_hash = worker.media_text_hash(sentence)
            phrase_hash = worker.media_text_hash(answer)
            media_names = [
                "sample_clip.webm",
                "sample_clip.mp4",
                "sample_clip.jpg",
                "sample_original.mp3",
                f"sample_tts_{sentence_hash}.mp3",
                f"sample_phrase_{phrase_hash}.mp3",
            ]
            for name in media_names:
                (anki_dir / name).write_bytes(f"media:{name}".encode("utf-8"))
            media_ledger = [
                {
                    "file": f"sample_tts_{sentence_hash}.mp3",
                    "role": "sentence_tts",
                    "tts_text": sentence,
                    "text_hash": sentence_hash,
                },
                {
                    "file": f"sample_phrase_{phrase_hash}.mp3",
                    "role": "phrase_tts",
                    "tts_text": answer,
                    "text_hash": phrase_hash,
                },
            ]
            original_anki_connect = worker._legacy_worker.anki_connect
            original_audio_duration_seconds = worker._legacy_worker.audio_duration_seconds

            def fake_audio_duration_seconds(path):
                return 2.0

            def fake_anki_connect(action, params=None, url=""):
                if action == "findCards":
                    return [123]
                if action == "cardsInfo":
                    return [
                        {
                            "cardId": 123,
                            "deckName": "Video Gate Deck",
                            "modelName": "Anki Card Generator V12 - 沉浸复读 V11",
                            "fields": {
                                "CardId": {"value": "card-1"},
                                "Video": {
                                    "value": worker.anki_video_html(
                                        "sample_clip.webm",
                                        "sample_clip.mp4",
                                        "sample_clip.jpg",
                                    )
                                },
                                "Audio": {"value": worker.anki_audio_html("sample_original.mp3")},
                                "TtsAudio": {"value": worker.anki_audio_html(f"sample_tts_{sentence_hash}.mp3")},
                                "PhraseTtsAudio": {"value": worker.anki_audio_html(f"sample_phrase_{phrase_hash}.mp3")},
                                "PronunciationMeta": {"value": '{"message":"??????????"}'},
                                "English": {"value": sentence},
                                "Answer": {"value": answer},
                                "Chinese": {"value": "???????"},
                                "TeacherNote": {"value": "demanding ??????????????????"},
                            },
                        }
                    ]
                if action == "getMediaDirPath":
                    return str(anki_dir)
                raise AssertionError(action)

            try:
                worker._legacy_worker.audio_duration_seconds = fake_audio_duration_seconds
                manifest = worker.media_manifest([str(anki_dir / name) for name in media_names], media_ledger)
                worker._legacy_worker.anki_connect = fake_anki_connect
                result = worker.handle_verify_anki_import(
                    {
                        "export_result": {
                            "deck_name": "Video Gate Deck",
                            "deck_kind": "video_language",
                            "cards": 1,
                            "template_version": "V12",
                            "anki_tag": "anki_card_generator_v12",
                            "media_manifest": manifest,
                            "media_ledger": media_ledger,
                            "card_media_ledger": [
                                {
                                    "card_id": "card-1",
                                    "learning_point_id": "lp-1",
                                    "segment_id": "seg-1",
                                    "answer": answer,
                                    "sentence_tts_text": sentence,
                                    "phrase_tts_text": answer,
                                    "video_webm": "sample_clip.webm",
                                    "video_mp4": "sample_clip.mp4",
                                    "poster": "sample_clip.jpg",
                                    "original_audio": "sample_original.mp3",
                                    "sentence_tts_audio": f"sample_tts_{sentence_hash}.mp3",
                                    "phrase_tts_audio": f"sample_phrase_{phrase_hash}.mp3",
                                }
                            ],
                            "media_summary": {"media_files": len(media_names)},
                            "media_dir": str(anki_dir),
                        }
                    }
                )
            finally:
                worker._legacy_worker.anki_connect = original_anki_connect
                worker._legacy_worker.audio_duration_seconds = original_audio_duration_seconds

        self.assertFalse(result["ok"])
        self.assertIn("corrupted_imported_study_text", result["failed_checks"])
        self.assertEqual(
            {item["field"] for item in result["corrupted_study_text_values"]},
            {"Chinese", "TeacherNote"},
        )
        self.assertEqual(result["model_names"], ["Anki Card Generator V12 - 沉浸复读 V11"])
        self.assertEqual(result["deck_names_seen"], ["Video Gate Deck"])
        self.assertEqual(result["media_count_checked"], len(media_names))
        self.assertEqual(result["card_media_ledger_count"], 1)
        self.assertEqual(result["missing_video_field_media"], [])
        self.assertEqual(result["pronunciation_meta_errors"], [])
        self.assertEqual(result["imported_tts_text_hash_mismatch"], [])
        self.assertEqual(result["imported_tts_audio_duration_issues"], [])
        self.assertEqual(result["tts_semantic_verification"]["status"], "manual_review_required")
        self.assertEqual(result["tts_semantic_verification"]["manual_review_required"], 2)
        self.assertEqual(result["tts_semantic_verification"]["high_risk_items"], 0)
        self.assertEqual(
            sorted(item["role"] for item in result["tts_manual_review_items"]),
            ["phrase_tts", "sentence_tts"],
        )
        self.assertTrue(result["audio_audit_verify_path"].endswith("audio_audit.verify.json"))
        self.assertTrue(result["audio_audit_verify_markdown_path"].endswith("audio_audit.verify.md"))
        self.assertEqual(result["audio_audit_mismatches"], [])
        self.assertEqual(result["audio_audit_summary"]["items"], 1)
        self.assertEqual(result["audio_audit_summary"]["expected_items"], 1)

    def test_verify_anki_import_does_not_fail_tts_semantic_mismatch_by_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            anki_dir = Path(temp_dir) / "anki_media"
            anki_dir.mkdir()
            sentence = "This card should read the source sentence."
            answer = "source sentence"
            sentence_hash = worker.media_text_hash(sentence)
            phrase_hash = worker.media_text_hash(answer)
            media_names = [
                "sample_clip.webm",
                "sample_clip.mp4",
                "sample_clip.jpg",
                "sample_original.mp3",
                f"sample_tts_{sentence_hash}.mp3",
                f"sample_phrase_{phrase_hash}.mp3",
            ]
            for name in media_names:
                (anki_dir / name).write_bytes(f"media:{name}".encode("utf-8"))
            media_ledger = [
                {
                    "file": f"sample_tts_{sentence_hash}.mp3",
                    "role": "sentence_tts",
                    "tts_text": sentence,
                    "text_hash": sentence_hash,
                    "semantic_verification": "passed",
                    "asr_transcript": sentence,
                },
                {
                    "file": f"sample_phrase_{phrase_hash}.mp3",
                    "role": "phrase_tts",
                    "tts_text": answer,
                    "text_hash": phrase_hash,
                    "semantic_verification": "mismatch",
                    "asr_transcript": "a different phrase",
                    "expected_text_normalized": "source sentence",
                    "actual_text_normalized": "a different phrase",
                    "semantic_review_reasons": ["asr_text_mismatch"],
                },
            ]
            original_anki_connect = worker._legacy_worker.anki_connect
            original_audio_duration_seconds = worker._legacy_worker.audio_duration_seconds

            def fake_audio_duration_seconds(path):
                name = Path(path).name
                if name.endswith((".mp4", ".webm")):
                    return 2.0
                if "phrase" in name:
                    return 1.2
                if name.endswith(".mp3"):
                    return 2.0
                return None

            def fake_anki_connect(action, params=None, url=""):
                if action == "findCards":
                    return [123]
                if action == "cardsInfo":
                    return [
                        {
                            "cardId": 123,
                            "deckName": "Video Gate Deck",
                            "modelName": "Anki Card Generator V12 - 沉浸复读 V11",
                            "fields": {
                                "CardId": {"value": "card-1"},
                                "Video": {
                                    "value": worker.anki_video_html(
                                        "sample_clip.webm",
                                        "sample_clip.mp4",
                                        "sample_clip.jpg",
                                    )
                                },
                                "Audio": {"value": worker.anki_audio_html("sample_original.mp3")},
                                "TtsAudio": {"value": worker.anki_audio_html(f"sample_tts_{sentence_hash}.mp3")},
                                "PhraseTtsAudio": {"value": worker.anki_audio_html(f"sample_phrase_{phrase_hash}.mp3")},
                                "PronunciationMeta": {"value": json.dumps({"status": "ok"})},
                                "English": {"value": sentence},
                                "Answer": {"value": answer},
                            },
                        }
                    ]
                if action == "getMediaDirPath":
                    return str(anki_dir)
                raise AssertionError(action)

            try:
                worker._legacy_worker.audio_duration_seconds = fake_audio_duration_seconds
                manifest = worker.media_manifest([str(anki_dir / name) for name in media_names], media_ledger)
                worker._legacy_worker.anki_connect = fake_anki_connect
                result = worker.handle_verify_anki_import(
                    {
                        "export_result": {
                            "deck_name": "Video Gate Deck",
                            "deck_kind": "video_language",
                            "cards": 1,
                            "template_version": "V12",
                            "anki_tag": "anki_card_generator_v12",
                            "media_manifest": manifest,
                            "media_ledger": media_ledger,
                            "card_media_ledger": [
                                {
                                    "card_id": "card-1",
                                    "learning_point_id": "lp-1",
                                    "segment_id": "seg-1",
                                    "answer": answer,
                                    "sentence_tts_text": sentence,
                                    "phrase_tts_text": answer,
                                    "video_webm": "sample_clip.webm",
                                    "video_mp4": "sample_clip.mp4",
                                    "poster": "sample_clip.jpg",
                                    "original_audio": "sample_original.mp3",
                                    "sentence_tts_audio": f"sample_tts_{sentence_hash}.mp3",
                                    "phrase_tts_audio": f"sample_phrase_{phrase_hash}.mp3",
                                }
                            ],
                            "media_summary": {"media_files": len(media_names)},
                            "media_dir": str(anki_dir),
                        }
                    }
                )
            finally:
                worker._legacy_worker.anki_connect = original_anki_connect
                worker._legacy_worker.audio_duration_seconds = original_audio_duration_seconds

        self.assertTrue(result["ok"], result)
        self.assertNotIn("tts_semantic_mismatch", result["failed_checks"])
        self.assertEqual(result["tts_semantic_verification"]["status"], "mismatch")
        self.assertEqual(result["tts_semantic_verification"]["failed"], 1)
        self.assertEqual(result["tts_semantic_failures"][0]["tts_text"], answer)

    def test_verify_anki_import_fails_media_ledger_card_text_mismatch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            anki_dir = Path(temp_dir) / "anki_media"
            anki_dir.mkdir()
            sentence = "Ledger text should match the imported card sentence."
            answer = "match the imported card"
            wrong_ledger_answer = "wrong but self consistent ledger phrase"
            sentence_hash = worker.media_text_hash(sentence)
            phrase_hash = worker.media_text_hash(answer)
            wrong_phrase_hash = worker.media_text_hash(wrong_ledger_answer)
            sentence_file = f"sample_tts_{sentence_hash}.mp3"
            phrase_file = f"sample_phrase_{phrase_hash}.mp3"
            media_names = [
                "sample_clip.webm",
                "sample_clip.mp4",
                "sample_clip.jpg",
                "sample_original.mp3",
                sentence_file,
                phrase_file,
            ]
            for name in media_names:
                (anki_dir / name).write_bytes(f"media:{name}".encode("utf-8"))
            media_ledger = [
                {
                    "file": sentence_file,
                    "role": "sentence_tts",
                    "tts_text": sentence,
                    "text_hash": sentence_hash,
                },
                {
                    "file": phrase_file,
                    "role": "phrase_tts",
                    "tts_text": wrong_ledger_answer,
                    "text_hash": wrong_phrase_hash,
                },
            ]
            card_media_ledger = [
                {
                    "card_id": "card-1",
                    "learning_point_id": "lp-1",
                    "segment_id": "seg-1",
                    "answer": answer,
                    "sentence_tts_text": sentence,
                    "phrase_tts_text": answer,
                    "video_webm": "sample_clip.webm",
                    "video_mp4": "sample_clip.mp4",
                    "poster": "sample_clip.jpg",
                    "original_audio": "sample_original.mp3",
                    "sentence_tts_audio": sentence_file,
                    "phrase_tts_audio": phrase_file,
                }
            ]
            original_anki_connect = worker._legacy_worker.anki_connect

            def fake_anki_connect(action, params=None, url=""):
                if action == "findCards":
                    return [123]
                if action == "cardsInfo":
                    return [
                        {
                            "cardId": 123,
                            "deckName": "Video Gate Deck",
                            "modelName": "Anki Card Generator V12 - 沉浸复读 V11",
                            "fields": {
                                "CardId": {"value": "card-1"},
                                "Video": {
                                    "value": worker.anki_video_html(
                                        "sample_clip.webm",
                                        "sample_clip.mp4",
                                        "sample_clip.jpg",
                                    )
                                },
                                "Audio": {"value": worker.anki_audio_html("sample_original.mp3")},
                                "TtsAudio": {"value": worker.anki_audio_html(sentence_file)},
                                "PhraseTtsAudio": {"value": worker.anki_audio_html(phrase_file)},
                                "PronunciationMeta": {"value": json.dumps({"status": "ok"})},
                                "English": {"value": sentence},
                                "Answer": {"value": answer},
                            },
                        }
                    ]
                if action == "getMediaDirPath":
                    return str(anki_dir)
                raise AssertionError(action)

            try:
                manifest = worker.media_manifest([str(anki_dir / name) for name in media_names], media_ledger)
                worker._legacy_worker.anki_connect = fake_anki_connect
                result = worker.handle_verify_anki_import(
                    {
                        "export_result": {
                            "deck_name": "Video Gate Deck",
                            "deck_kind": "video_language",
                            "cards": 1,
                            "template_version": "V12",
                            "anki_tag": "anki_card_generator_v12",
                            "media_manifest": manifest,
                            "media_ledger": media_ledger,
                            "card_media_ledger": card_media_ledger,
                            "media_summary": {"media_files": len(media_names)},
                            "media_dir": str(anki_dir),
                        }
                    }
                )
            finally:
                worker._legacy_worker.anki_connect = original_anki_connect

        self.assertFalse(result["ok"], result)
        self.assertIn("media_ledger_card_text_mismatch", result["failed_checks"])
        self.assertNotIn("card_media_ledger_mismatch", result["failed_checks"])
        self.assertNotIn("audio_audit_mismatch", result["failed_checks"])
        self.assertEqual(result["card_media_ledger_mismatches"], [])
        self.assertEqual(result["audio_audit_mismatches"], [])
        self.assertEqual(result["imported_tts_text_hash_mismatch"], [])
        self.assertEqual(result["ledger_text_hash_mismatch"], [])
        self.assertEqual(result["media_ledger_card_text_mismatches"][0]["field"], "PhraseTtsAudio")
        self.assertEqual(result["media_ledger_card_text_mismatches"][0]["expected_text_hash"], phrase_hash)
        self.assertEqual(result["media_ledger_card_text_mismatches"][0]["ledger_text_hash"], wrong_phrase_hash)
        self.assertEqual(result["media_ledger_card_text_mismatches"][0]["ledger_declared_text_hash"], wrong_phrase_hash)

    def test_verify_anki_import_fails_card_media_ledger_mismatch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            anki_dir = Path(temp_dir) / "anki_media"
            anki_dir.mkdir()
            sentence = "Ledger should bind media per card."
            answer = "bind media"
            sentence_hash = worker.media_text_hash(sentence)
            phrase_hash = worker.media_text_hash(answer)
            expected_phrase = f"sample_phrase_{phrase_hash}.mp3"
            wrong_phrase = f"wrong_phrase_{phrase_hash}.mp3"
            media_names = [
                "sample_clip.webm",
                "sample_clip.mp4",
                "sample_clip.jpg",
                "sample_original.mp3",
                f"sample_tts_{sentence_hash}.mp3",
                expected_phrase,
                wrong_phrase,
            ]
            for name in media_names:
                (anki_dir / name).write_bytes(f"media:{name}".encode("utf-8"))
            media_ledger = [
                {
                    "file": f"sample_tts_{sentence_hash}.mp3",
                    "role": "sentence_tts",
                    "tts_text": sentence,
                    "text_hash": sentence_hash,
                },
                {
                    "file": expected_phrase,
                    "role": "phrase_tts",
                    "tts_text": answer,
                    "text_hash": phrase_hash,
                },
                {
                    "file": wrong_phrase,
                    "role": "phrase_tts",
                    "tts_text": answer,
                    "text_hash": phrase_hash,
                },
            ]
            original_anki_connect = worker._legacy_worker.anki_connect

            def fake_anki_connect(action, params=None, url=""):
                if action == "findCards":
                    return [123]
                if action == "cardsInfo":
                    return [
                        {
                            "cardId": 123,
                            "deckName": "Video Gate Deck",
                            "modelName": "Anki Card Generator V12 - 沉浸复读 V11",
                            "fields": {
                                "CardId": {"value": "card-1"},
                                "Video": {
                                    "value": worker.anki_video_html(
                                        "sample_clip.webm",
                                        "sample_clip.mp4",
                                        "sample_clip.jpg",
                                    )
                                },
                                "Audio": {"value": worker.anki_audio_html("sample_original.mp3")},
                                "TtsAudio": {"value": worker.anki_audio_html(f"sample_tts_{sentence_hash}.mp3")},
                                "PhraseTtsAudio": {"value": worker.anki_audio_html(wrong_phrase)},
                                "PronunciationMeta": {"value": json.dumps({"status": "ok"})},
                                "English": {"value": sentence},
                                "Answer": {"value": answer},
                            },
                        }
                    ]
                if action == "getMediaDirPath":
                    return str(anki_dir)
                raise AssertionError(action)

            try:
                manifest = worker.media_manifest([str(anki_dir / name) for name in media_names], media_ledger)
                worker._legacy_worker.anki_connect = fake_anki_connect
                result = worker.handle_verify_anki_import(
                    {
                        "export_result": {
                            "deck_name": "Video Gate Deck",
                            "deck_kind": "video_language",
                            "cards": 1,
                            "template_version": "V12",
                            "anki_tag": "anki_card_generator_v12",
                            "media_manifest": manifest,
                            "media_ledger": media_ledger,
                            "card_media_ledger": [
                                {
                                    "card_id": "card-1",
                                    "learning_point_id": "lp-1",
                                    "segment_id": "seg-1",
                                    "answer": answer,
                                    "sentence_tts_text": sentence,
                                    "phrase_tts_text": answer,
                                    "video_webm": "sample_clip.webm",
                                    "video_mp4": "sample_clip.mp4",
                                    "poster": "sample_clip.jpg",
                                    "original_audio": "sample_original.mp3",
                                    "sentence_tts_audio": f"sample_tts_{sentence_hash}.mp3",
                                    "phrase_tts_audio": expected_phrase,
                                }
                            ],
                            "media_summary": {"media_files": len(media_names)},
                            "media_dir": str(anki_dir),
                        }
                    }
                )
            finally:
                worker._legacy_worker.anki_connect = original_anki_connect

        self.assertFalse(result["ok"], result)
        self.assertIn("card_media_ledger_mismatch", result["failed_checks"])
        self.assertIn("audio_audit_mismatch", result["failed_checks"])
        self.assertEqual(result["card_media_ledger_mismatches"][0]["field"], "PhraseTtsAudio")
        self.assertIn(expected_phrase, result["card_media_ledger_mismatches"][0]["missing_expected"])
        self.assertIn(wrong_phrase, result["card_media_ledger_mismatches"][0]["unexpected_actual"])
        self.assertEqual(result["audio_audit_mismatches"][0]["field"], "PhraseTtsAudio")

    def test_verify_anki_import_fails_card_display_sentence_mismatch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            anki_dir = Path(temp_dir) / "anki_media"
            anki_dir.mkdir()
            expected_display = "This is the sentence the card should display."
            imported_sentence = "This is the sentence Anki actually imported."
            answer = "sentence"
            sentence_hash = worker.media_text_hash(imported_sentence)
            phrase_hash = worker.media_text_hash(answer)
            media_names = [
                "sample_clip.webm",
                "sample_clip.mp4",
                "sample_clip.jpg",
                "sample_original.mp3",
                f"sample_tts_{sentence_hash}.mp3",
                f"sample_phrase_{phrase_hash}.mp3",
            ]
            for name in media_names:
                (anki_dir / name).write_bytes(f"media:{name}".encode("utf-8"))
            media_ledger = [
                {
                    "file": f"sample_tts_{sentence_hash}.mp3",
                    "role": "sentence_tts",
                    "tts_text": imported_sentence,
                    "text_hash": sentence_hash,
                },
                {
                    "file": f"sample_phrase_{phrase_hash}.mp3",
                    "role": "phrase_tts",
                    "tts_text": answer,
                    "text_hash": phrase_hash,
                },
            ]
            original_anki_connect = worker._legacy_worker.anki_connect

            def fake_anki_connect(action, params=None, url=""):
                if action == "findCards":
                    return [123]
                if action == "cardsInfo":
                    return [
                        {
                            "cardId": 123,
                            "deckName": "Video Gate Deck",
                            "modelName": "Anki Card Generator V12 - 沉浸复读 V11",
                            "fields": {
                                "CardId": {"value": "card-1"},
                                "Video": {
                                    "value": worker.anki_video_html(
                                        "sample_clip.webm",
                                        "sample_clip.mp4",
                                        "sample_clip.jpg",
                                    )
                                },
                                "Audio": {"value": worker.anki_audio_html("sample_original.mp3")},
                                "TtsAudio": {"value": worker.anki_audio_html(f"sample_tts_{sentence_hash}.mp3")},
                                "PhraseTtsAudio": {"value": worker.anki_audio_html(f"sample_phrase_{phrase_hash}.mp3")},
                                "PronunciationMeta": {"value": json.dumps({"status": "ok"})},
                                "English": {"value": imported_sentence},
                                "Answer": {"value": answer},
                            },
                        }
                    ]
                if action == "getMediaDirPath":
                    return str(anki_dir)
                raise AssertionError(action)

            try:
                manifest = worker.media_manifest([str(anki_dir / name) for name in media_names], media_ledger)
                worker._legacy_worker.anki_connect = fake_anki_connect
                result = worker.handle_verify_anki_import(
                    {
                        "export_result": {
                            "deck_name": "Video Gate Deck",
                            "deck_kind": "video_language",
                            "cards": 1,
                            "template_version": "V12",
                            "anki_tag": "anki_card_generator_v12",
                            "media_manifest": manifest,
                            "media_ledger": media_ledger,
                            "card_media_ledger": [
                                {
                                    "card_id": "card-1",
                                    "learning_point_id": "lp-1",
                                    "segment_id": "seg-1",
                                    "answer": answer,
                                    "card_display_sentence": expected_display,
                                    "sentence_tts_text": imported_sentence,
                                    "phrase_tts_text": answer,
                                    "video_webm": "sample_clip.webm",
                                    "video_mp4": "sample_clip.mp4",
                                    "poster": "sample_clip.jpg",
                                    "original_audio": "sample_original.mp3",
                                    "sentence_tts_audio": f"sample_tts_{sentence_hash}.mp3",
                                    "phrase_tts_audio": f"sample_phrase_{phrase_hash}.mp3",
                                }
                            ],
                            "media_summary": {"media_files": len(media_names)},
                            "media_dir": str(anki_dir),
                        }
                    }
                )
            finally:
                worker._legacy_worker.anki_connect = original_anki_connect

        self.assertFalse(result["ok"], result)
        self.assertIn("audio_audit_mismatch", result["failed_checks"])
        self.assertEqual(result["audio_audit_mismatches"][0]["field"], "CardDisplaySentence")
        self.assertEqual(result["imported_tts_text_hash_mismatch"], [])

    def test_verify_anki_import_fails_media_subtitle_alignment_mismatch_from_audit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            anki_dir = Path(temp_dir) / "anki_media"
            anki_dir.mkdir()
            sentence = "Today we need to build your perspective on the world before moving on."
            answer = "build your perspective"
            sentence_hash = worker.media_text_hash(sentence)
            phrase_hash = worker.media_text_hash(answer)
            media_names = [
                "sample_clip.webm",
                "sample_clip.mp4",
                "sample_clip.jpg",
                "sample_original.mp3",
                f"sample_tts_{sentence_hash}.mp3",
                f"sample_phrase_{phrase_hash}.mp3",
            ]
            for name in media_names:
                (anki_dir / name).write_bytes(f"media:{name}".encode("utf-8"))
            media_ledger = [
                {
                    "file": f"sample_tts_{sentence_hash}.mp3",
                    "role": "sentence_tts",
                    "tts_text": sentence,
                    "text_hash": sentence_hash,
                },
                {
                    "file": f"sample_phrase_{phrase_hash}.mp3",
                    "role": "phrase_tts",
                    "tts_text": answer,
                    "text_hash": phrase_hash,
                },
            ]
            card_media_item = {
                "card_id": "card-1",
                "learning_point_id": "lp-1",
                "segment_id": "seg-1",
                "answer": answer,
                "card_display_sentence": sentence,
                "sentence_tts_text": sentence,
                "phrase_tts_text": answer,
                "video_webm": "sample_clip.webm",
                "video_mp4": "sample_clip.mp4",
                "poster": "sample_clip.jpg",
                "original_audio": "sample_original.mp3",
                "sentence_tts_audio": f"sample_tts_{sentence_hash}.mp3",
                "phrase_tts_audio": f"sample_phrase_{phrase_hash}.mp3",
            }
            audio_audit_item = {
                **card_media_item,
                "sentence_tts_expected_text": sentence,
                "phrase_tts_expected_text": answer,
                "sentence_tts_file": f"sample_tts_{sentence_hash}.mp3",
                "phrase_tts_file": f"sample_phrase_{phrase_hash}.mp3",
                "video_webm": "sample_clip.webm",
                "video_mp4": "sample_clip.mp4",
                "poster": "sample_clip.jpg",
                "original_audio": "sample_original.mp3",
                "source_sentence_quality_flags": ["clean"],
                "source_sentence_quality_status": "clean",
                "media_subtitle_alignment_status": "mismatch",
                "media_subtitle_overlap_score": 0.0,
                "media_subtitle_alignment_reason": "no_subtitle_cues_overlap_media_window",
                "media_subtitle_time": "00:00:40.000 - 00:00:43.000",
                "media_window_subtitle_text": "This is unrelated visual text.",
            }
            original_anki_connect = worker._legacy_worker.anki_connect

            def fake_anki_connect(action, params=None, url=""):
                if action == "findCards":
                    return [123]
                if action == "cardsInfo":
                    return [
                        {
                            "cardId": 123,
                            "deckName": "Video Gate Deck",
                            "modelName": "Anki Card Generator V12 - 沉浸复读 V11",
                            "fields": {
                                "CardId": {"value": "card-1"},
                                "Video": {
                                    "value": worker.anki_video_html(
                                        "sample_clip.webm",
                                        "sample_clip.mp4",
                                        "sample_clip.jpg",
                                    )
                                },
                                "Audio": {"value": worker.anki_audio_html("sample_original.mp3")},
                                "TtsAudio": {"value": worker.anki_audio_html(f"sample_tts_{sentence_hash}.mp3")},
                                "PhraseTtsAudio": {"value": worker.anki_audio_html(f"sample_phrase_{phrase_hash}.mp3")},
                                "PronunciationMeta": {"value": json.dumps({"status": "ok"})},
                                "English": {"value": sentence},
                                "Answer": {"value": answer},
                            },
                        }
                    ]
                if action == "getMediaDirPath":
                    return str(anki_dir)
                raise AssertionError(action)

            try:
                manifest = worker.media_manifest([str(anki_dir / name) for name in media_names], media_ledger)
                worker._legacy_worker.anki_connect = fake_anki_connect
                result = worker.handle_verify_anki_import(
                    {
                        "export_result": {
                            "deck_name": "Video Gate Deck",
                            "deck_kind": "video_language",
                            "cards": 1,
                            "template_version": "V12",
                            "anki_tag": "anki_card_generator_v12",
                            "media_manifest": manifest,
                            "media_ledger": media_ledger,
                            "card_media_ledger": [card_media_item],
                            "audio_audit_items": [audio_audit_item],
                            "media_summary": {"media_files": len(media_names)},
                            "media_dir": str(anki_dir),
                        }
                    }
                )
            finally:
                worker._legacy_worker.anki_connect = original_anki_connect

        self.assertFalse(result["ok"], result)
        self.assertIn("audio_audit_mismatch", result["failed_checks"])
        media_alignment_mismatches = [
            item for item in result["audio_audit_mismatches"] if item.get("field") == "MediaSubtitleAlignment"
        ]
        self.assertEqual(len(media_alignment_mismatches), 1)
        self.assertEqual(media_alignment_mismatches[0]["status"], "mismatch")
        self.assertEqual(
            media_alignment_mismatches[0]["reason"],
            "no_subtitle_cues_overlap_media_window",
        )
        self.assertEqual(result["missing_video_field_media"], [])
        self.assertEqual(result["imported_tts_text_hash_mismatch"], [])

    def test_verify_anki_import_tolerates_duplicate_same_card_from_previous_import(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            anki_dir = Path(temp_dir) / "anki_media"
            anki_dir.mkdir()
            sentence = "I am going to practice."
            answer = "going to"
            sentence_hash = worker.media_text_hash(sentence)
            phrase_hash = worker.media_text_hash(answer)
            media_names = [
                "sample_clip.webm",
                "sample_clip.mp4",
                "sample_clip.jpg",
                "sample_original.mp3",
                f"sample_tts_{sentence_hash}.mp3",
                f"sample_phrase_{phrase_hash}.mp3",
            ]
            for name in media_names:
                (anki_dir / name).write_bytes(f"media:{name}".encode("utf-8"))
            media_ledger = [
                {
                    "file": f"sample_tts_{sentence_hash}.mp3",
                    "role": "sentence_tts",
                    "tts_text": sentence,
                    "text_hash": sentence_hash,
                    "semantic_verification": "passed",
                },
                {
                    "file": f"sample_phrase_{phrase_hash}.mp3",
                    "role": "phrase_tts",
                    "tts_text": answer,
                    "text_hash": phrase_hash,
                    "semantic_verification": "passed",
                },
            ]
            card_media_ledger = [
                {
                    "card_id": "card-1",
                    "learning_point_id": "lp-1",
                    "segment_id": "seg-1",
                    "answer": answer,
                    "sentence_tts_text": sentence,
                    "phrase_tts_text": answer,
                    "video_webm": "sample_clip.webm",
                    "video_mp4": "sample_clip.mp4",
                    "poster": "sample_clip.jpg",
                    "original_audio": "sample_original.mp3",
                    "sentence_tts_audio": f"sample_tts_{sentence_hash}.mp3",
                    "phrase_tts_audio": f"sample_phrase_{phrase_hash}.mp3",
                }
            ]
            original_anki_connect = worker._legacy_worker.anki_connect
            original_audio_duration_seconds = worker._legacy_worker.audio_duration_seconds

            def fake_audio_duration_seconds(path):
                return 1.0

            def duplicate_card_info(card_id):
                return {
                    "cardId": card_id,
                    "deckName": "Video Gate Deck",
                    "modelName": "Anki Card Generator V12 - 沉浸复读 V11 · 快速复读",
                    "fields": {
                        "CardId": {"value": "card-1"},
                        "Video": {
                            "value": worker.anki_video_html(
                                "sample_clip.webm",
                                "sample_clip.mp4",
                                "sample_clip.jpg",
                            )
                        },
                        "Audio": {"value": worker.anki_audio_html("sample_original.mp3")},
                        "TtsAudio": {"value": worker.anki_audio_html(f"sample_tts_{sentence_hash}.mp3")},
                        "PhraseTtsAudio": {"value": worker.anki_audio_html(f"sample_phrase_{phrase_hash}.mp3")},
                        "PronunciationMeta": {"value": json.dumps({"status": "ok"})},
                        "English": {"value": sentence},
                        "Answer": {"value": answer},
                    },
                }

            def fake_anki_connect(action, params=None, url=""):
                if action == "findCards":
                    return [123, 456]
                if action == "cardsInfo":
                    return [duplicate_card_info(123), duplicate_card_info(456)]
                if action == "getMediaDirPath":
                    return str(anki_dir)
                raise AssertionError(action)

            try:
                manifest = worker.media_manifest([str(anki_dir / name) for name in media_names], media_ledger)
                worker._legacy_worker.anki_connect = fake_anki_connect
                worker._legacy_worker.audio_duration_seconds = fake_audio_duration_seconds
                result = worker.handle_verify_anki_import(
                    {
                        "export_result": {
                            "deck_name": "Video Gate Deck",
                            "deck_kind": "video_language",
                            "cards": 1,
                            "template_version": "V12",
                            "anki_tag": "anki_card_generator_v12",
                            "media_manifest": manifest,
                            "media_ledger": media_ledger,
                            "card_media_ledger": card_media_ledger,
                            "media_summary": {"media_files": len(media_names)},
                            "media_dir": str(anki_dir),
                        }
                    }
                )
            finally:
                worker._legacy_worker.anki_connect = original_anki_connect
                worker._legacy_worker.audio_duration_seconds = original_audio_duration_seconds

        self.assertTrue(result["ok"], result)
        self.assertNotIn("card_count_mismatch", result["failed_checks"])
        self.assertEqual(result["card_count"], 1)
        self.assertEqual(result["expected_cards"], 1)
        self.assertEqual(result["imported_card_count"], 2)
        self.assertEqual(result["duplicate_imported_card_count"], 1)
        self.assertEqual(result["audio_audit_summary"]["items"], 1)
        self.assertEqual(result["audio_audit_summary"]["expected_items"], 1)

    def test_verify_anki_import_rejects_overlong_phrase_tts_duration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            anki_dir = Path(temp_dir) / "anki_media"
            anki_dir.mkdir()
            sentence = "Here is the prompt."
            answer = "prompt"
            sentence_hash = worker.media_text_hash(sentence)
            phrase_hash = worker.media_text_hash(answer)
            media_names = [
                "sample_clip.webm",
                "sample_clip.mp4",
                "sample_clip.jpg",
                "sample_original.mp3",
                f"sample_tts_{sentence_hash}.mp3",
                f"sample_phrase_{phrase_hash}.mp3",
            ]
            for name in media_names:
                (anki_dir / name).write_bytes(f"media:{name}".encode("utf-8"))
            media_ledger = [
                {
                    "file": f"sample_tts_{sentence_hash}.mp3",
                    "role": "sentence_tts",
                    "tts_text": sentence,
                    "text_hash": sentence_hash,
                },
                {
                    "file": f"sample_phrase_{phrase_hash}.mp3",
                    "role": "phrase_tts",
                    "tts_text": answer,
                    "text_hash": phrase_hash,
                },
            ]
            original_anki_connect = worker._legacy_worker.anki_connect
            original_audio_duration_seconds = worker._legacy_worker.audio_duration_seconds

            def fake_audio_duration_seconds(path):
                name = Path(path).name
                if name.endswith((".mp4", ".webm")):
                    return 2.0
                if "phrase" in name:
                    return 87.64
                if name.endswith(".mp3"):
                    return 2.0
                return None

            def fake_anki_connect(action, params=None, url=""):
                if action == "findCards":
                    return [123]
                if action == "cardsInfo":
                    return [
                        {
                            "cardId": 123,
                            "deckName": "Video Gate Deck",
                            "modelName": "Anki Card Generator V12 - 沉浸复读 V11 · 快速复读",
                            "fields": {
                                "CardId": {"value": "card-1"},
                                "Video": {
                                    "value": worker.anki_video_html(
                                        "sample_clip.webm",
                                        "sample_clip.mp4",
                                        "sample_clip.jpg",
                                    )
                                },
                                "Audio": {"value": worker.anki_audio_html("sample_original.mp3")},
                                "TtsAudio": {"value": worker.anki_audio_html(f"sample_tts_{sentence_hash}.mp3")},
                                "PhraseTtsAudio": {"value": worker.anki_audio_html(f"sample_phrase_{phrase_hash}.mp3")},
                                "PronunciationMeta": {"value": json.dumps({"status": "ok"})},
                                "English": {"value": sentence},
                                "Answer": {"value": answer},
                            },
                        }
                    ]
                if action == "getMediaDirPath":
                    return str(anki_dir)
                raise AssertionError(action)

            try:
                worker._legacy_worker.audio_duration_seconds = fake_audio_duration_seconds
                manifest = worker.media_manifest([str(anki_dir / name) for name in media_names], media_ledger)
                worker._legacy_worker.anki_connect = fake_anki_connect
                result = worker.handle_verify_anki_import(
                    {
                        "export_result": {
                            "deck_name": "Video Gate Deck",
                            "deck_kind": "video_language",
                            "cards": 1,
                            "template_version": "V12",
                            "anki_tag": "anki_card_generator_v12",
                            "media_manifest": manifest,
                            "media_ledger": media_ledger,
                            "media_summary": {"media_files": len(media_names)},
                            "media_dir": str(anki_dir),
                        }
                    }
                )
            finally:
                worker._legacy_worker.anki_connect = original_anki_connect
                worker._legacy_worker.audio_duration_seconds = original_audio_duration_seconds

        self.assertFalse(result["ok"], result)
        self.assertIn("imported_tts_audio_duration", result["failed_checks"])
        self.assertEqual(result["imported_tts_audio_duration_issues"][0]["reason"], "overlong_phrase_tts")
        self.assertEqual(result["imported_tts_audio_duration_issues"][0]["tts_text"], "prompt")
        self.assertEqual(result["tts_semantic_verification"]["high_risk_items"], 1)
        high_risk_items = [
            item
            for item in result["tts_manual_review_items"]
            if "high_risk_short_expression" in item.get("semantic_review_reasons", [])
        ]
        self.assertEqual(high_risk_items[0]["tts_text"], "prompt")

    def test_verify_anki_import_fails_video_without_tts_and_bad_meta(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            anki_dir = Path(temp_dir) / "anki_media"
            anki_dir.mkdir()
            original_anki_connect = worker._legacy_worker.anki_connect

            def fake_anki_connect(action, params=None, url=""):
                if action == "findCards":
                    return [123]
                if action == "cardsInfo":
                    return [
                        {
                            "cardId": 123,
                            "deckName": "Broken Video Gate Deck",
                            "modelName": "Anki Card Generator V12 - 词霸天下实验 V1",
                            "fields": {
                                "CardId": {"value": "card-1"},
                                "Video": {"value": ""},
                                "Audio": {"value": ""},
                                "TtsAudio": {"value": ""},
                                "PhraseTtsAudio": {"value": ""},
                                "PronunciationMeta": {"value": "{not json"},
                                "English": {"value": "Bad import."},
                                "Answer": {"value": "Bad import"},
                            },
                        }
                    ]
                if action == "getMediaDirPath":
                    return str(anki_dir)
                raise AssertionError(action)

            try:
                worker._legacy_worker.anki_connect = fake_anki_connect
                result = worker.handle_verify_anki_import(
                    {
                        "export_result": {
                            "deck_name": "Broken Video Gate Deck",
                            "deck_kind": "video_language",
                            "cards": 1,
                            "template_version": "V12",
                            "anki_tag": "anki_card_generator_v12",
                            "media_manifest": {},
                            "media_summary": {"media_files": 0},
                            "media_dir": str(Path(temp_dir) / "export_media"),
                        }
                    }
                )
            finally:
                worker._legacy_worker.anki_connect = original_anki_connect

        self.assertFalse(result["ok"])
        self.assertIn("video_template_mismatch", result["failed_checks"])
        self.assertIn("ordinary_flow_ciba_template", result["failed_checks"])
        self.assertIn("missing_imported_video_field_media", result["failed_checks"])
        self.assertIn("pronunciation_meta_parse_errors", result["failed_checks"])

    def test_verify_anki_import_rejects_document_on_video_template(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            anki_dir = Path(temp_dir) / "anki_media"
            anki_dir.mkdir()
            original_anki_connect = worker._legacy_worker.anki_connect

            def fake_anki_connect(action, params=None, url=""):
                if action == "findCards":
                    return [123]
                if action == "cardsInfo":
                    return [
                        {
                            "cardId": 123,
                            "deckName": "Document Gate Deck",
                            "modelName": "Anki Card Generator V12 - 沉浸复读 V11",
                            "fields": {
                                "CardId": {"value": "doc-card-1"},
                                "FrontContent": {"value": "What does the document say?"},
                                "Answer": {"value": "It says the import gate should reject video templates."},
                                "Video": {"value": ""},
                                "Audio": {"value": ""},
                                "TtsAudio": {"value": ""},
                                "PhraseTtsAudio": {"value": ""},
                            },
                        }
                    ]
                if action == "getMediaDirPath":
                    return str(anki_dir)
                raise AssertionError(action)

            try:
                worker._legacy_worker.anki_connect = fake_anki_connect
                result = worker.handle_verify_anki_import(
                    {
                        "export_result": {
                            "deck_name": "Document Gate Deck",
                            "deck_kind": "document_knowledge",
                            "cards": 1,
                            "template_version": "V10",
                            "anki_tag": "anki_card_generator_v10",
                            "media_manifest": {},
                            "media_summary": {"media_files": 0},
                            "media_dir": str(Path(temp_dir) / "export_media"),
                        }
                    }
                )
            finally:
                worker._legacy_worker.anki_connect = original_anki_connect

        self.assertFalse(result["ok"])
        self.assertIn("document_template_mismatch", result["failed_checks"])

    def test_qwen_tts_audio_uses_dashscope_generation_endpoint(self):
        calls = {}
        original_http_json = worker._legacy_worker.http_json
        original_http_get_binary = worker._legacy_worker.http_get_binary

        def fake_http_json(url, headers, body, timeout=60):
            calls["url"] = url
            calls["headers"] = headers
            calls["body"] = body
            return {"output": {"audio": {"url": "https://example.com/audio.wav"}}}

        def fake_http_get_binary(url, headers=None, timeout=90):
            calls["download_url"] = url
            return b"RIFF....WAVE"

        try:
            worker._legacy_worker.http_json = fake_http_json
            worker._legacy_worker.http_get_binary = fake_http_get_binary
            audio = worker.call_tts_audio(
                {
                    "provider": "qwen",
                    "base_url": "https://dashscope.aliyuncs.com/api/v1",
                    "api_key": "sk-test",
                    "model": "qwen3-tts-flash",
                    "voice": "Cherry",
                    "language": "en",
                    "sample_rate": 24000,
                    "bit_rate": 128000,
                },
                "Hello from a local video card.",
                "English",
            )
        finally:
            worker._legacy_worker.http_json = original_http_json
            worker._legacy_worker.http_get_binary = original_http_get_binary

        self.assertEqual(audio, b"RIFF....WAVE")
        self.assertEqual(
            calls["url"],
            "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
        )
        self.assertEqual(calls["headers"]["Authorization"], "Bearer sk-test")
        self.assertEqual(calls["body"]["model"], "qwen3-tts-flash")
        self.assertEqual(calls["body"]["input"]["voice"], "Cherry")
        self.assertEqual(calls["body"]["input"]["language_type"], "English")
        self.assertEqual(calls["download_url"], "https://example.com/audio.wav")

    def test_gemini_vertex_tts_audio_uses_gcloud_auth_and_vertex_endpoint(self):
        calls = {}
        original_http_json = worker._legacy_worker.http_json
        original_gcloud_value = worker._legacy_worker.gcloud_value

        def fake_gcloud_value(args, timeout=30):
            calls.setdefault("gcloud", []).append(args)
            if args == ["config", "get-value", "core/project"]:
                return "project-test"
            if args == ["auth", "print-access-token"]:
                return "ya29.test-token"
            return ""

        def fake_http_json(url, headers, body, timeout=60):
            calls["url"] = url
            calls["headers"] = headers
            calls["body"] = body
            calls["timeout"] = timeout
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "inlineData": {
                                        "data": base64.b64encode(b"\x00\x00\x01\x00").decode("ascii")
                                    }
                                }
                            ]
                        }
                    }
                ]
            }

        try:
            worker._legacy_worker.gcloud_value = fake_gcloud_value
            worker._legacy_worker.http_json = fake_http_json
            audio = worker.call_tts_audio(
                {
                    "provider": "gemini-vertex",
                    "base_url": "https://aiplatform.googleapis.com",
                    "api_key": "",
                    "model": "gemini-3.1-flash-tts-preview",
                    "voice": "Kore",
                    "language": "en-US",
                    "sample_rate": 24000,
                    "bit_rate": 128000,
                },
                "This is a local video card.",
                "English",
            )
        finally:
            worker._legacy_worker.http_json = original_http_json
            worker._legacy_worker.gcloud_value = original_gcloud_value

        self.assertTrue(audio.startswith(b"RIFF"))
        self.assertIn(b"WAVE", audio)
        self.assertEqual(
            calls["url"],
            "https://aiplatform.googleapis.com/v1beta1/projects/project-test/locations/global/publishers/google/models/gemini-3.1-flash-tts-preview:generateContent",
        )
        self.assertEqual(calls["headers"]["Authorization"], "Bearer ya29.test-token")
        self.assertEqual(calls["headers"]["x-goog-user-project"], "project-test")
        speech_config = calls["body"]["generationConfig"]["speechConfig"]
        self.assertEqual(calls["body"]["generationConfig"]["responseModalities"], ["AUDIO"])
        self.assertEqual(speech_config["languageCode"], "en-US")
        self.assertEqual(speech_config["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"], "Kore")
        self.assertNotIn("systemInstruction", calls["body"])
        prompt = calls["body"]["contents"][0]["parts"][0]["text"]
        self.assertIn("Read aloud exactly the target text below.", prompt)
        self.assertIn("Do not explain, translate, expand, add words", prompt)
        self.assertIn("Target text: This is a local video card.", prompt)

    def test_tts_text_module_matches_worker_exact_prompt_and_variants(self):
        from acg.tts_text import exact_tts_prompt, gemini_vertex_tts_text_variants

        self.assertEqual(exact_tts_prompt("in style"), worker.exact_tts_prompt("in style"))
        self.assertEqual(
            gemini_vertex_tts_text_variants("Tell you what, I'll let you off for a 10.")[:2],
            [
                "Tell you what, I'll let you off for a 10.",
                "Tell you what, I'll let you off for a ten.",
            ],
        )
        self.assertIn("in style.", gemini_vertex_tts_text_variants("in style"))

    def test_gemini_vertex_tts_retries_with_number_words_after_http_error(self):
        calls = {"texts": []}
        original_http_json = worker._legacy_worker.http_json
        original_gcloud_value = worker._legacy_worker.gcloud_value

        def fake_gcloud_value(args, timeout=30):
            if args == ["config", "get-value", "core/project"]:
                return "project-test"
            if args == ["auth", "print-access-token"]:
                return "ya29.test-token"
            return ""

        def fake_http_json(url, headers, body, timeout=60):
            text = body["contents"][0]["parts"][0]["text"]
            calls["texts"].append(text)
            if text == worker.exact_tts_prompt("Tell you what, I'll let you off for a 10."):
                raise RuntimeError("API HTTP 400: invalid argument")
            if text == worker.exact_tts_prompt("Tell you what, I'll let you off for a ten."):
                return {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "inlineData": {
                                            "data": base64.b64encode(b"\x00\x00\x01\x00").decode("ascii")
                                        }
                                    }
                                ]
                            }
                        }
                    ]
                }
            return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "no audio"}]}}]}

        try:
            worker._legacy_worker.gcloud_value = fake_gcloud_value
            worker._legacy_worker.http_json = fake_http_json
            audio = worker.call_tts_audio(
                {
                    "provider": "gemini-vertex",
                    "base_url": "https://aiplatform.googleapis.com",
                    "api_key": "",
                    "model": "gemini-3.1-flash-tts-preview",
                    "voice": "Kore",
                    "language": "en-US",
                    "sample_rate": 24000,
                    "bit_rate": 128000,
                },
                "Tell you what, I'll let you off for a 10.",
                "English",
            )
        finally:
            worker._legacy_worker.http_json = original_http_json
            worker._legacy_worker.gcloud_value = original_gcloud_value

        self.assertTrue(audio.startswith(b"RIFF"))
        self.assertEqual(
            calls["texts"],
            [
                worker.exact_tts_prompt("Tell you what, I'll let you off for a 10."),
                worker.exact_tts_prompt("Tell you what, I'll let you off for a ten."),
            ],
        )

    def test_gemini_vertex_tts_retries_short_phrase_with_sentence_punctuation_when_no_audio(self):
        calls = {"texts": []}
        original_http_json = worker._legacy_worker.http_json
        original_gcloud_value = worker._legacy_worker.gcloud_value

        def fake_gcloud_value(args, timeout=30):
            if args == ["config", "get-value", "core/project"]:
                return "project-test"
            if args == ["auth", "print-access-token"]:
                return "ya29.test-token"
            return ""

        def fake_http_json(url, headers, body, timeout=60):
            text = body["contents"][0]["parts"][0]["text"]
            calls["texts"].append(text)
            if text == worker.exact_tts_prompt("in style"):
                return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "in style"}]}}]}
            if text == worker.exact_tts_prompt("in style."):
                return {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "inlineData": {
                                            "data": base64.b64encode(b"\x00\x00\x01\x00").decode("ascii")
                                        }
                                    }
                                ]
                            }
                        }
                    ]
                }
            return {"candidates": []}

        try:
            worker._legacy_worker.gcloud_value = fake_gcloud_value
            worker._legacy_worker.http_json = fake_http_json
            audio = worker.call_tts_audio(
                {
                    "provider": "gemini-vertex",
                    "base_url": "https://aiplatform.googleapis.com",
                    "api_key": "",
                    "model": "gemini-3.1-flash-tts-preview",
                    "voice": "Kore",
                    "language": "en-US",
                    "sample_rate": 24000,
                    "bit_rate": 128000,
                },
                "in style",
                "English",
            )
        finally:
            worker._legacy_worker.http_json = original_http_json
            worker._legacy_worker.gcloud_value = original_gcloud_value

        self.assertTrue(audio.startswith(b"RIFF"))
        self.assertEqual(
            calls["texts"],
            [
                worker.exact_tts_prompt("in style"),
                worker.exact_tts_prompt("in style."),
            ],
        )

    def test_phrase_match_requires_all_phrase_words_in_compact_order(self):
        self.assertTrue(worker.phrase_in_text("I need to make sure we are ready.", "make sure"))
        self.assertFalse(worker.phrase_in_text("I need to make sure we are ready.", "make ready"))

    def test_phrase_match_supports_placeholder_patterns(self):
        self.assertTrue(worker.phrase_in_text("You really let me down.", "let someone down"))
        self.assertTrue(worker.phrase_in_text("We can work it out.", "work something out"))

    def test_phrase_match_supports_contractions_and_gap_patterns(self):
        self.assertTrue(worker.phrase_in_text("I've been uh thinking about that offer...", "have been thinking about"))
        self.assertTrue(worker.phrase_in_text("That's what a boiling flask is for.", "That's what ... is for"))

    def test_subtitle_cleaning_removes_youtube_speaker_markers(self):
        self.assertEqual(
            worker.strip_subtitle_text("? >> Before we start, don't forget to subscribe."),
            "Before we start, don't forget to subscribe.",
        )

    def test_subtitle_cleaning_removes_youtube_ass_spacing_controls(self):
        self.assertEqual(
            worker.strip_subtitle_text("repeat after me speaking\\h\\h practice\\Nout there"),
            "repeat after me speaking practice out there",
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

    def test_find_phrase_mines_common_spoken_frames(self):
        self.assertEqual(worker.find_phrase("Honestly, it's such a nice Monday morning.", "B1"), "such a nice")
        self.assertEqual(worker.find_phrase("It feels like we are finally ready.", "B1"), "feels like")
        self.assertEqual(worker.find_phrase("At some point, you just have to start.", "B1"), "at some point")
        self.assertEqual(worker.find_phrase("We are going through a lot right now.", "B1"), "going through")

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

    def test_fallback_phrase_fields_hide_key_expression_placeholder(self):
        fields = worker.fallback_phrase_fields(
            "This sentence needs a human review.",
            "key expression",
            "B1",
        )

        self.assertEqual(fields["phrase"], "")
        self.assertNotIn("key expression", " ".join(fields.values()))

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
        self.assertEqual(segments[0]["phrase"], "such a nice")
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

    def test_segment_builder_recalls_typed_learning_points(self):
        cues = [
            worker.Cue(1, 0.0, 2.5, "I'm gonna run the register."),
            worker.Cue(2, 3.0, 5.5, "I mean you're flat as a washboard."),
            worker.Cue(3, 6.0, 8.5, "I seen one of those bounce off a windshield one time."),
            worker.Cue(4, 9.0, 11.5, "Ever want me to read anything, I could critique it for you."),
        ]

        segments = worker.build_segments(
            cues,
            {
                "level": "C1",
                "max_segments": 30,
                "_candidate_limit": 60,
                "language_focus": ["phrases", "vocabulary", "grammar", "listening"],
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

        found = {(segment["candidate_kind"], segment["phrase"]) for segment in segments}
        self.assertIn(("expression", "run the register"), found)
        self.assertIn(("contextual_vocab", "register"), found)
        self.assertIn(("pragmatic_risk", "flat as a washboard"), found)
        self.assertIn(("grammar_pattern", "I seen"), found)
        self.assertIn(("expression", "bounce off a windshield"), found)
        self.assertIn(("grammar_pattern", "Ever want me to"), found)
        self.assertIn(("contextual_vocab", "critique"), found)
        run_source_ids = {
            segment["source_segment_id"]
            for segment in segments
            if segment["text"] == "I'm gonna run the register."
        }
        self.assertEqual(len(run_source_ids), 1)

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

    def test_sentence_window_media_bounds_tracks_display_sentence_not_phrase_only(self):
        full_text = (
            "Today I want to talk about the plan because honestly we need to figure out "
            "what happens next before we move on."
        )
        display_text = "the plan because honestly we need to figure out what happens next before we move on."

        media_start, media_end, status = worker.sentence_window_media_bounds(
            100.0,
            112.0,
            full_text,
            display_text,
        )

        self.assertEqual(status, "display_sentence_window")
        self.assertLess(media_start, 103.5)
        self.assertGreater(media_end, 111.5)
        self.assertGreater(media_end - media_start, 8.0)

    def test_learning_point_media_alignment_fields_prefers_full_source_sentence_window(self):
        from acg.media_alignment import learning_point_media_alignment_fields

        full_text = "The more you live in English, the faster your brain rewires itself."
        fields = learning_point_media_alignment_fields(
            {
                "source_sentence": full_text,
                "answer_core": "rewires itself",
                "exact_span": "rewires itself",
            },
            start=349.287,
            end=358.061,
            display_sentence="rewires itself",
        )

        self.assertEqual(fields["media_alignment_status"], "source_sentence_window")
        self.assertEqual(fields["media_alignment_text"], full_text)
        self.assertEqual(fields["media_alignment_source_text"], full_text)
        self.assertEqual(fields["media_alignment_phrase"], "rewires itself")
        self.assertTrue(fields["media_alignment_phrase_located"])
        self.assertLessEqual(fields["media_start"], 349.3)
        self.assertGreaterEqual(fields["media_end"], 358.0)
        self.assertGreater(fields["media_end"] - fields["media_start"], 8.5)

    def test_media_subtitle_alignment_diagnostic_detects_window_mismatch(self):
        cues = [
            worker.Cue(index=1, start=10.0, end=12.0, text="This is unrelated visual text."),
            worker.Cue(index=2, start=12.0, end=14.0, text="Still unrelated captions on screen."),
        ]

        diagnostic = worker.media_subtitle_alignment_diagnostic(
            cues,
            10.0,
            14.0,
            "build your perspective on the world",
        )

        self.assertEqual(diagnostic["media_subtitle_alignment_status"], "mismatch")
        self.assertLess(diagnostic["media_subtitle_overlap_score"], 0.38)

    def test_media_subtitle_alignment_partial_blocks_only_when_low_or_source_unreliable(self):
        cues = [
            worker.Cue(index=1, start=10.0, end=14.0, text="alpha beta gamma delta epsilon zeta filler words"),
        ]
        diagnostic = worker.media_subtitle_alignment_diagnostic(
            cues,
            10.0,
            14.0,
            "alpha beta gamma delta epsilon zeta eta theta iota kappa",
        )

        self.assertEqual(diagnostic["media_subtitle_alignment_status"], "partial")
        self.assertGreaterEqual(
            diagnostic["media_subtitle_overlap_score"],
            worker.MEDIA_SUBTITLE_PARTIAL_EXPORT_BLOCK_THRESHOLD,
        )
        self.assertFalse(worker.media_subtitle_alignment_blocks_export(diagnostic, {}))
        self.assertTrue(
            worker.media_subtitle_alignment_blocks_export(
                diagnostic,
                {"source_sentence_quality_flags": ["possible_bad_join"]},
            )
        )
        self.assertTrue(
            worker.media_subtitle_alignment_blocks_export(
                diagnostic,
                {"source_sentence_quality_flags": ["too_long"]},
            )
        )
        self.assertEqual(
            worker.media_subtitle_alignment_failure_reason(
                diagnostic,
                {"source_sentence_quality_flags": ["too_long"]},
            ),
            "partial_overlap_with_unreliable_source_sentence:too_long",
        )

        low_diagnostic = worker.media_subtitle_alignment_diagnostic(
            cues,
            10.0,
            14.0,
            "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron",
        )

        self.assertEqual(low_diagnostic["media_subtitle_alignment_status"], "partial")
        self.assertLess(
            low_diagnostic["media_subtitle_overlap_score"],
            worker.MEDIA_SUBTITLE_PARTIAL_EXPORT_BLOCK_THRESHOLD,
        )
        self.assertTrue(worker.media_subtitle_alignment_blocks_export(low_diagnostic, {}))

    def test_export_alignment_recomputes_old_phrase_aligned_segment_to_card_sentence(self):
        segment = {
            "id": "seg-old",
            "start": 100.0,
            "end": 112.0,
            "source_time": "00:01:40.000 - 00:01:52.000",
            "media_start": 108.0,
            "media_end": 112.2,
            "media_source_time": "00:01:48.000 - 00:01:52.200",
            "media_alignment_status": "phrase_aligned",
            "full_source_sentence": (
                "Today I want to talk about the plan because honestly we need to figure out "
                "what happens next before we move on."
            ),
            "text": "the plan because honestly we need to figure out what happens next before we move on.",
        }

        aligned = worker.align_segment_media_to_display_sentence(segment)

        self.assertEqual(aligned["media_alignment_status"], "source_sentence_window")
        self.assertEqual(aligned["media_alignment_text"], segment["full_source_sentence"])
        self.assertLessEqual(aligned["media_start"], 100.0)
        self.assertGreater(aligned["media_end"], 111.5)
        self.assertGreater(aligned["media_end"] - aligned["media_start"], 11.5)

    def test_export_alignment_expands_phrase_only_segment_to_full_source_sentence(self):
        full_sentence = "The more you live in English, the faster your brain rewires itself."
        segment = {
            "id": "seg-phrase-only",
            "start": 349.287,
            "end": 358.061,
            "source_time": "00:05:49.287 - 00:05:58.061",
            "media_start": 354.0,
            "media_end": 358.061,
            "media_source_time": "00:05:54.000 - 00:05:58.061",
            "media_alignment_status": "phrase_aligned",
            "full_source_sentence": full_sentence,
            "source_sentence": full_sentence,
            "text": "rewires itself",
        }

        aligned = worker.align_segment_media_to_display_sentence(segment)

        self.assertEqual(aligned["media_alignment_status"], "source_sentence_window")
        self.assertEqual(aligned["media_alignment_text"], full_sentence)
        self.assertLessEqual(aligned["media_start"], 349.3)
        self.assertGreaterEqual(aligned["media_end"], 358.0)
        self.assertGreater(aligned["media_end"] - aligned["media_start"], 8.5)

    def test_segment_display_source_time_prefers_media_source_time(self):
        from acg.media_alignment import segment_display_source_time

        segment = {
            "source_time": "00:01:40.000 - 00:01:52.000",
            "media_source_time": "00:01:42.100 - 00:01:45.400",
        }

        self.assertEqual(
            segment_display_source_time(segment),
            "00:01:42.100 - 00:01:45.400",
        )

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

    def test_phrase_review_recomputes_media_bounds_for_final_phrase(self):
        segment = {
            "id": "seg_0001",
            "start": 100.0,
            "end": 112.0,
            "source_time": "00:01:40.000 - 00:01:52.000",
            "media_start": 99.88,
            "media_end": 112.18,
            "media_source_time": "00:01:39.880 - 00:01:52.180",
            "text": "Before we start I need to coat some chicken in the cornflakes and then we move on.",
            "phrase": "key expression",
            "score": 3.4,
            "recommendation": 3,
        }
        reviews = {
            "seg_0001": {
                "decision": "keep",
                "phrase": "coat some chicken in the cornflakes",
                "value_score": 4,
                "reason": "可迁移的烹饪动作表达。",
            }
        }

        kept, skipped = worker.apply_phrase_review_decisions([segment], reviews, {"level": "B1"})

        self.assertEqual(skipped, [])
        self.assertEqual(kept[0]["phrase"], "coat some chicken in the cornflakes")
        self.assertGreater(kept[0]["media_start"], 100.0)
        self.assertLess(kept[0]["media_end"], 112.18)
        self.assertLessEqual(kept[0]["media_end"] - kept[0]["media_start"], 6.25)

    def test_phrase_review_repairs_explanatory_answer_core(self):
        segment = {
            "id": "seg_0001",
            "start": 0.0,
            "end": 2.0,
            "source_time": "00:00:00.000 - 00:00:02.000",
            "text": "I'm gonna run the register.",
            "phrase": "run the register",
            "candidate_kind": "expression",
            "phrase_type": "spoken_phrase",
            "score": 4.2,
            "recommendation": 5,
        }
        reviews = {
            "seg_0001": {
                "decision": "keep",
                "phrase": "run the register",
                "exact_span": "run the register",
                "normalized_answer": "run the register",
                "answer_core": "run the register = 负责收银",
                "candidate_kind": "expression",
                "phrase_type": "spoken_phrase",
                "value_score": 5,
                "reason": "很自然的工作场景表达。",
            }
        }

        kept, skipped = worker.apply_phrase_review_decisions([segment], reviews, {"level": "B1"})

        self.assertEqual(skipped, [])
        self.assertEqual(kept[0]["answer_core"], "run the register")
        self.assertEqual(kept[0]["validation_status"], "repaired")
        self.assertIn("answer_core", kept[0]["validation_issues"])

    def test_phrase_review_rejects_exact_span_outside_source_sentence(self):
        segment = {
            "id": "seg_0001",
            "start": 0.0,
            "end": 2.0,
            "source_time": "00:00:00.000 - 00:00:02.000",
            "text": "I'm gonna run the register.",
            "phrase": "run the register",
            "candidate_kind": "expression",
            "phrase_type": "spoken_phrase",
            "score": 4.2,
            "recommendation": 5,
        }
        reviews = {
            "seg_0001": {
                "decision": "keep",
                "phrase": "run the front desk",
                "exact_span": "run the front desk",
                "normalized_answer": "run the front desk",
                "answer_core": "run the front desk",
                "candidate_kind": "expression",
                "phrase_type": "spoken_phrase",
                "value_score": 5,
                "reason": "AI 幻觉了另一个表达。",
            }
        }

        kept, skipped = worker.apply_phrase_review_decisions([segment], reviews, {"level": "B1"})

        self.assertEqual(kept, [])
        self.assertEqual(skipped[0]["phrase_review_status"], "reject")
        self.assertIn("不在原句", skipped[0]["phrase_reject_reason"])

    def test_phrase_review_prompt_requests_teacher_level_judgement(self):
        prompt = worker.build_phrase_review_prompt(
            {"language": "English", "level": "B1", "language_focus": ["vocabulary", "grammar"]},
            [
                {
                    "id": "seg_0001",
                    "start": 0.0,
                    "end": 2.0,
                    "source_time": "00:00:00.000 - 00:00:02.000",
                    "text": "Honestly, it's such a nice Monday morning.",
                    "phrase": "key expression",
                    "score": 3.4,
                    "recommendation": 3,
                }
            ],
        )

        self.assertIn("学习动作", prompt)
        self.assertIn("phrase_type", prompt)
        self.assertIn("score_breakdown", prompt)
        self.assertIn("单词用法", prompt)
        self.assertIn("语法框架", prompt)
        self.assertIn("vocabulary_usage", prompt)
        self.assertIn("grammar_pattern", prompt)
        self.assertIn("such a nice Monday morning", prompt)
        self.assertIn("talk about", prompt)

    def test_default_language_focus_includes_contextual_vocabulary(self):
        self.assertEqual(worker.normalized_language_focus({}), ["phrases", "vocabulary", "listening"])

    def test_deep_material_context_is_injected_into_prompts(self):
        project = {
            "language": "English",
            "level": "B1",
            "language_focus": ["phrases", "vocabulary"],
            "material_context": {
                "summary": "Two friends are deciding whether to talk now or postpone a tense topic.",
                "tone": "hesitant and conversational",
                "learning_opportunities": ["语境生词", "词伙表达"],
            },
        }
        segment = {
            "id": "seg_0001",
            "start": 0.0,
            "end": 2.0,
            "source_time": "00:00:00.000 - 00:00:02.000",
            "text": "This is getting awkward.",
            "phrase": "awkward",
            "score": 3.4,
            "recommendation": 3,
        }

        review_prompt = worker.build_phrase_review_prompt(project, [segment])
        card_prompt = worker.build_prompt({**project, "card_types": ["phrase"]}, [segment])

        self.assertIn("全局素材理解", review_prompt)
        self.assertIn("hesitant and conversational", review_prompt)
        self.assertIn("全局素材理解", card_prompt)
        self.assertIn('"content_kind":"phrase|vocabulary|grammar|listening"', card_prompt)

    def test_ciba_tianxia_card_prompt_is_template_isolated(self):
        project = {
            "language": "en",
            "level": "B1",
            "card_types": ["phrase"],
        }
        segment = {
            "id": "seg_0001",
            "start": 0.0,
            "end": 2.0,
            "source_time": "00:00:00.000 - 00:00:02.000",
            "text": "Can you run the register for a minute?",
            "phrase": "run the register",
            "recommendation": 4,
            "learning_points": [
                {
                    "id": "lp-1",
                    "answer_core": "run the register",
                    "exact_span": "run the register",
                    "candidate_kind": "expression",
                    "phrase_type": "collocation",
                }
            ],
        }

        default_prompt = worker.build_prompt({**project, "template_id": "immersive_v11"}, [segment])
        ciba_prompt = worker.build_prompt({**project, "template_id": "ciba_tianxia_v1"}, [segment])

        self.assertNotIn("词霸天下实验 V1", default_prompt)
        self.assertNotIn("为说而思考", default_prompt)
        self.assertIn("词霸天下实验 V1", ciba_prompt)
        self.assertIn("为说而思考", ciba_prompt)
        self.assertIn("每张卡只训练一个真实语言动作", ciba_prompt)
        self.assertIn("搭配边界", ciba_prompt)
        self.assertIn('"learning_action":"contextual_meaning|expression_recall|listening_discrimination|collocation_boundary|chinese_learner_trap|conceptual_action|grammar_pattern"', ciba_prompt)
        self.assertIn('"conceptual_action":"概念动作感"', ciba_prompt)
        self.assertIn('"chinese_learner_trap":"中文学习者误区"', ciba_prompt)
        self.assertIn("不得把语法正确、自然的近义表达称为错误或中式英语", ciba_prompt)

    def test_ciba_tianxia_ai_review_prompt_is_template_isolated(self):
        from acg.pipeline import learning_point_pipeline

        source_batch = [
            {
                "source_segment_id": "src-1",
                "source_time": "00:00:01.000 - 00:00:02.000",
                "source_sentence": "Can you run the register for a minute?",
            }
        ]
        local_by_source = {
            "src-1": [
                {
                    "id": "lp-1",
                    "candidate_kind": "expression",
                    "phrase_type": "collocation",
                    "exact_span": "run the register",
                    "answer_core": "run the register",
                    "normalized_answer": "run the register",
                    "learning_action": "训练 run + the register 表示负责收银的搭配。",
                    "value_score": 4,
                }
            ]
        }

        default_prompt = learning_point_pipeline._build_ai_learning_point_review_prompt(
            {"language": "en", "level": "B1", "template_id": "immersive_v11"}, source_batch, local_by_source
        )
        ciba_prompt = learning_point_pipeline._build_ai_learning_point_review_prompt(
            {"language": "en", "level": "B1", "template_id": "ciba_tianxia_v1"}, source_batch, local_by_source
        )

        self.assertNotIn("词霸天下实验 V1", default_prompt)
        self.assertNotIn("为说而思考", default_prompt)
        self.assertIn("词霸天下实验 V1", ciba_prompt)
        self.assertIn("真实语言动作", ciba_prompt)
        self.assertIn("run the register", ciba_prompt)
        self.assertIn("迁移测试", default_prompt)
        self.assertIn("have break", default_prompt)
        self.assertIn("纯名词块", default_prompt)

    def test_ciba_tianxia_scoring_boosts_language_actions_without_changing_default(self):
        from acg.scoring.learning_value import score_learning_point

        point = {
            "candidate_kind": "expression",
            "phrase_type": "collocation",
            "answer_core": "run the register",
            "estimated_level": "B1",
            "value_score": 3.5,
            "learning_action": "训练 run + the register 表示负责收银的搭配边界。",
            "usage_boundary": "用于收银台工作或店员职责，不是普通登记。",
            "confusable_note": "register 在这里不是登记，而是收银机。",
        }
        default_score = score_learning_point(point, "B1", {"template_id": "immersive_v11"})
        ciba_score = score_learning_point(point, "B1", {"template_id": "ciba_tianxia_v1"})
        noise_score = score_learning_point(
            {
                **point,
                "answer_core": "talk about",
                "phrase_type": "spoken_phrase",
                "learning_action": "学习这个表达",
                "usage_boundary": "",
                "confusable_note": "",
            },
            "B1",
            {"template_id": "ciba_tianxia_v1"},
        )

        self.assertGreater(ciba_score["value_score"], default_score["value_score"])
        self.assertLess(noise_score["value_score"], ciba_score["value_score"])

    def test_learning_value_downgrades_low_transfer_or_unlocatable_answers(self):
        from acg.scoring.learning_value import assign_learning_point_status, score_learning_point

        low_transfer = {
            "candidate_kind": "expression",
            "phrase_type": "spoken_phrase",
            "answer_core": "talk about",
            "source_sentence": "Today we are going to talk about AI models.",
            "estimated_level": "B1",
            "value_score": 4.6,
            "learning_action": "学习这个表达",
        }
        scored_low_transfer = {**low_transfer, **score_learning_point(low_transfer, "B1", {})}
        low_transfer_status, low_transfer_reason = assign_learning_point_status(scored_low_transfer, "B1", {})

        unlocatable = {
            "candidate_kind": "expression",
            "phrase_type": "collocation",
            "answer_core": "take over",
            "source_sentence": "We are going to talk about AI models today.",
            "estimated_level": "B1",
            "value_score": 4.6,
            "learning_action": "训练 take over 表示接管的搭配边界。",
            "usage_boundary": "用于职责或控制权转移，不是普通讨论。",
        }
        scored_unlocatable = {**unlocatable, **score_learning_point(unlocatable, "B1", {})}
        unlocatable_status, unlocatable_reason = assign_learning_point_status(scored_unlocatable, "B1", {})

        self.assertIn("low_transfer_answer", scored_low_transfer["recommendation_flags"])
        self.assertEqual(low_transfer_status, "candidate_only")
        self.assertIn("默认推荐", low_transfer_reason)
        self.assertIn("answer_not_locatable", scored_unlocatable["recommendation_flags"])
        self.assertEqual(unlocatable_status, "candidate_only")
        self.assertIn("清楚定位", unlocatable_reason)
    def test_discourse_marker_learning_points_pass_contract_when_transferable(self):
        ok, reason, normalized = worker.sanitize_learning_point_contract(
            {
                "candidate_kind": "expression",
                "phrase_type": "discourse_marker",
                "exact_span": "sort of",
                "answer_core": "sort of",
                "learning_action": "训练 sort of 表达口语弱化和模糊语气。",
            },
            "It is sort of strange at first.",
            language="en",
        )

        self.assertTrue(ok, reason)
        self.assertEqual(normalized["phrase_type"], "discourse_marker")
        self.assertEqual(normalized["answer_core"], "sort of")

    def test_learning_value_demotes_weak_noun_chunks_and_asr_subtitle_errors(self):
        from acg.scoring.learning_value import assign_learning_point_status, score_learning_point

        weak_noun = {
            "candidate_kind": "expression",
            "phrase_type": "collocation",
            "answer_core": "age groups",
            "source_sentence": "There are different age groups and it is only boys there.",
            "estimated_level": "B1",
            "value_score": 4.8,
            "learning_action": "训练 age groups 这个名词块。",
        }
        scored_weak_noun = {**weak_noun, **score_learning_point(weak_noun, "B1", {})}
        weak_status, weak_reason = assign_learning_point_status(scored_weak_noun, "B1", {})

        bad_asr = {
            "candidate_kind": "expression",
            "phrase_type": "collocation",
            "answer_core": "have break for 15 minutes",
            "source_sentence": "At 10:45, we have break for 15 minutes.",
            "estimated_level": "B1",
            "value_score": 4.8,
            "learning_action": "训练 have break for 15 minutes 表示休息一段时间。",
        }
        scored_bad_asr = {**bad_asr, **score_learning_point(bad_asr, "B1", {})}
        bad_asr_status, _ = assign_learning_point_status(scored_bad_asr, "B1", {})

        spoken_marker = {
            "candidate_kind": "expression",
            "phrase_type": "discourse_marker",
            "answer_core": "sort of",
            "source_sentence": "It is sort of strange at first.",
            "estimated_level": "B1",
            "value_score": 3.8,
            "learning_action": "训练 sort of 表达口语弱化和模糊语气。",
        }
        scored_spoken_marker = {**spoken_marker, **score_learning_point(spoken_marker, "B1", {})}
        marker_status, _ = assign_learning_point_status(scored_spoken_marker, "B1", {})

        self.assertIn("weak_noun_chunk", scored_weak_noun["recommendation_flags"])
        self.assertEqual(weak_status, "candidate_only")
        self.assertIn("默认推荐", weak_reason)
        self.assertIn("asr_grammar_suspect", scored_bad_asr["recommendation_flags"])
        self.assertEqual(bad_asr_status, "candidate_only")
        self.assertEqual(marker_status, "recommended")

    def test_local_recall_finds_high_transfer_expression_patterns(self):
        from acg.recall.local_learning_points import recall_local_learning_points

        payload = {"level": "B1", "content_toggles": {}}
        segment = {
            "id": "seg_local_quality",
            "source_sentence": (
                "The stress is taking a toll on me, but I am under pressure "
                "and I was wondering if we could have a break for 15 minutes."
            ),
        }
        answers = {str(item.get("answer_core") or "").lower() for item in recall_local_learning_points(segment, payload)}

        self.assertIn("taking a toll on", answers)
        self.assertIn("under pressure", answers)
        self.assertIn("i was wondering if", answers)
        self.assertIn("have a break for 15 minutes", answers)

    def test_vocabulary_usage_cards_get_contextual_label(self):
        segments = [
            {
                "id": "seg_0001",
                "start": 0.0,
                "end": 2.0,
                "source_time": "00:00:00.000 - 00:00:02.000",
                "text": "This is getting awkward.",
                "phrase": "awkward",
                "phrase_type": "vocabulary_usage",
                "content_kind": "vocabulary",
                "score": 3.4,
                "recommendation": 4,
            }
        ]
        ai_payload = {
            "segments": [
                {
                    "id": "seg_0001",
                    "cards": [
                        {
                            "type": "phrase",
                            "phrase": "awkward",
                            "phrase_type": "vocabulary_usage",
                            "content_kind": "vocabulary",
                            "chinese": "尴尬的",
                            "definition": "在当前场景里表示气氛开始变得不自在。",
                            "collocations": "get awkward / feel awkward",
                            "context": "社交气氛变僵时使用。",
                            "example": "The room got awkward after that comment.",
                            "chinese_feel": "中文像“气氛有点尴尬”。",
                            "why": "中国学习者常知道中文义，但不一定会说 get awkward。",
                            "difficulty": "B1 日常交流",
                            "teacher_note": "重点记 get awkward 这个场景用法。",
                            "cloze": "This is getting ____.",
                        }
                    ],
                }
            ]
        }

        merged, _ = worker.merge_ai_cards(segments, ai_payload, ["phrase"], "B1")

        card = merged[0]["cards"][0]
        self.assertEqual(card["type_label"], "学习卡")
        self.assertEqual(card["content_kind"], "vocabulary")

    def test_card_front_fields_use_retrieval_prompts_by_card_kind(self):
        expression = worker.card_front_fields(
            {
                "type": "phrase",
                "phrase": "run the register",
                "chinese": "负责收银",
                "natural_chinese": "负责收银",
                "phrase_type": "collocation",
                "content_kind": "phrase",
            }
        )
        vocabulary = worker.card_front_fields(
            {
                "type": "phrase",
                "phrase": "register",
                "chinese": "收银机",
                "natural_chinese": "收银机",
                "phrase_type": "vocabulary_usage",
                "content_kind": "vocabulary",
            }
        )

        self.assertIn("负责收银", expression["front_prompt"])
        self.assertIn("自然表达是什么", expression["front_prompt"])
        self.assertNotIn("判断这句最值得学", expression["front_prompt"])
        self.assertEqual(expression["answer"], "run the register")
        self.assertEqual(vocabulary["front_prompt"], "“register”在这句里是什么意思？")
        self.assertEqual(vocabulary["answer"], "register")
        repetition = worker.card_front_fields(
            {
                "type": "phrase",
                "phrase": "run the register",
                "natural_chinese": "负责收银",
            },
            repetition_mode=True,
        )
        self.assertEqual(repetition["front_prompt"], "听原声，跟读这一句。")
        self.assertEqual(repetition["front_content"], "先听一遍，再模仿语气和节奏。")
        self.assertEqual(repetition["answer"], "run the register")
        self.assertEqual(worker.card_label_for_learning_card("", "vocabulary"), "学习卡")
        self.assertEqual(worker.card_label_for_learning_card("idiom", "phrase"), "学习卡")

    def test_repetition_front_fields_do_not_claim_original_audio_when_tts_only(self):
        from acg.export_fields import front_fields_for_export_media

        front_fields = {
            "front_prompt": "听原声，跟读这一句。",
            "front_content": "先听一遍，再模仿语气和节奏。",
            "answer": "special guest",
        }

        adjusted = front_fields_for_export_media(
            front_fields,
            repetition_mode=True,
            has_original_audio=False,
            has_tts_audio=True,
        )
        self.assertEqual(adjusted, worker.front_fields_for_export_media(
            front_fields,
            repetition_mode=True,
            has_original_audio=False,
            has_tts_audio=True,
        ))
        self.assertEqual(adjusted["front_prompt"], "听慢读，跟读这一句。")
        self.assertEqual(adjusted["front_content"], "先听慢读，再模仿语气和节奏。")
        self.assertEqual(front_fields["front_prompt"], "听原声，跟读这一句。")

        with_original = front_fields_for_export_media(
            front_fields,
            repetition_mode=True,
            has_original_audio=True,
            has_tts_audio=True,
        )
        self.assertEqual(with_original["front_prompt"], "听原声，跟读这一句。")

    def test_ciba_tianxia_does_not_use_v11_repetition_front_mode(self):
        self.assertTrue(worker.uses_v11_repetition_front("immersive_v11", "video_language"))
        self.assertTrue(worker.uses_v11_repetition_front("immersive_v11", "subtitle_language"))
        self.assertFalse(worker.uses_v11_repetition_front("ciba_tianxia_v1", "video_language"))
        self.assertFalse(worker.uses_v11_repetition_front("ciba_tianxia_v1", "subtitle_language"))
        self.assertFalse(worker.uses_v11_repetition_front("ciba_tianxia_v1", "document_reading"))

    def test_ciba_front_should_preserve_retrieval_prompt_when_not_repetition_mode(self):
        card = {
            "type": "phrase",
            "retrieval_prompt": "这句里表示“负责收银”的自然表达是什么？",
            "phrase": "run the register",
            "answer_core": "run the register",
            "chinese": "负责收银",
        }

        front = worker.card_front_fields(card, repetition_mode=False)

        self.assertEqual(front["front_prompt"], "这句里表示“负责收银”的自然表达是什么？")
        self.assertEqual(front["answer"], "run the register")

    def test_ciba_tianxia_export_fields_prefer_language_action_mapping(self):
        card = {
            "answer_core": "run the register",
            "phrase": "run the register",
            "chinese": "负责收银",
            "learning_target": "把 run the register 当作“负责收银”的整体搭配来识别。",
            "how_to_use_it": "用于店员临时负责收银台。",
            "replacement_examples": "Can you run the register for a minute?\nI’ll run the register while you restock.",
            "usage_boundary": "用于商店、收银台、店员职责。",
            "confusable_note": "register 这里不是“登记”，而是收银机。",
            "learning_action": "expression_recall",
            "conceptual_action": "把 run 理解成临时负责/运转一个岗位或设备。",
            "chinese_learner_trap": "中文容易把 run 直译成跑步或运行程序。",
        }

        self.assertIn("负责收银", worker.ciba_contextual_meaning_text(card))
        self.assertIn("整体搭配", worker.ciba_language_action_text(card))
        self.assertIn("临时负责", worker.ciba_conceptual_action_text(card))
        self.assertIn("直译成跑步", worker.ciba_chinese_learner_trap_text(card))
        self.assertIn("run the register", worker.ciba_transfer_text(card))
        self.assertIn("中文容易", worker.ciba_boundary_text(card))

    def test_ciba_contextual_meaning_prefers_core_meaning_over_sentence_translation(self):
        card = {
            "answer_core": "run the register",
            "phrase": "run the register",
            "chinese": "负责收银 / 操作收银机",
            "natural_chinese": "我来负责收银。",
            "chinese_feel": "中文像“我来负责收银”。",
        }

        self.assertEqual(worker.ciba_contextual_meaning_text(card), "负责收银 / 操作收银机")
        self.assertEqual(worker.ciba_source_context_text(card), "我来负责收银。")

    def test_internal_fallback_text_is_not_used_in_study_fields(self):
        card = {
            "type": "phrase",
            "phrase": "run the register",
            "chinese": "待精修：先把 run the register 当作本句目标表达。",
            "natural_chinese": "正式导出前需要 AI 精修。",
            "definition": "本地 fallback 只保证结构完整。",
            "collocations": "run the register + natural object / use run the register in a complete sentence",
            "teacher_note": "不建议直接作为正式学习内容。",
        }

        fields = worker.card_front_fields(card, repetition_mode=True)

        self.assertEqual(worker.card_answer_core(card), "run the register")
        self.assertEqual(worker.card_chinese_core(card), "")
        self.assertEqual(fields["answer"], "run the register")
        self.assertNotIn("待精修", fields["front_prompt"] + fields["front_content"] + fields["answer"])
        self.assertTrue(worker.contains_internal_placeholder(card["definition"]))
        self.assertEqual(worker.clean_study_text(card["collocations"]), "")
        self.assertEqual(worker.v11_meaning_text(card), "负责收银 / 操作收银机")
        self.assertIn("负责看收银台", worker.v11_usage_text(card))
        self.assertIn("Can you run the register today", worker.v11_self_sentence_text(card))
        self.assertIn("register 在这里是", worker.v11_misuse_text(card))

        sensitive = {"phrase": "flat as a washboard", "english": "I mean you're flat as a washboard."}
        self.assertIn("可能冒犯", worker.v11_misuse_text(sensitive))
        self.assertEqual(worker.v11_source_translation_text(sensitive), "我是说，你平得像个搓衣板。")

    def test_model_fallback_quality_issue_blocks_export(self):
        card = {
            "type": "phrase",
            "phrase": "it only takes",
            "chinese": "\u7ed3\u5408\u539f\u53e5\u7406\u89e3\u3002",
            "definition": "\u4fdd\u5e95\u89e3\u91ca\u3002",
            "teacher_note": "\u4fdd\u5e95\u751f\u6210\uff0c\u9700\u8981\u91cd\u65b0\u751f\u6210\u3002",
            "quality": {
                "score": 58,
                "status": "needs_review",
                "issues": ["\u7528\u6237\u5df2\u52fe\u9009\uff0c\u6a21\u578b\u672a\u5b8c\u6574\u8fd4\u56de\u65f6\u7531\u7cfb\u7edf\u4fdd\u5e95\u751f\u6210\u3002"],
            },
        }

        self.assertTrue(worker._legacy_worker.card_has_export_blocking_content(card))

    def test_text_cleaning_module_filters_internal_placeholders(self):
        from acg.text_cleaning import clean_study_text, contains_internal_placeholder

        value = "本地 fallback 只保证结构完整。"

        self.assertTrue(contains_internal_placeholder(value))
        self.assertEqual(clean_study_text(value), "")
        self.assertEqual(clean_study_text("  keep   this text  "), "keep this text")

    def test_v11_back_fields_are_labeled_and_deduped(self):
        card = {
            "type": "phrase",
            "phrase": "run the register",
            "english": "I'm gonna run the register.",
            "definition": "表示负责收银或操作收银机。",
            "chinese_feel": "表示负责收银或操作收银机。",
            "how_to_use_it": "在工作分工时说 I'll run the register.",
            "replacement_examples": "run the front desk / run the bar",
            "example": "Can you run the register for ten minutes?",
            "usage_boundary": "只用于工作职责，不是“买单”。",
            "confusable_note": "register 这里不是“登记”。",
            "why_it_matters": "能把 cashier 变成更自然的动作表达。",
        }

        self.assertEqual(worker.v11_meaning_text(card), "负责收银 / 操作收银机")
        self.assertEqual(worker.v11_source_translation_text(card), "我来负责收银。")
        self.assertIn("在工作分工时说", worker.v11_usage_text(card))
        self.assertIn("run the front desk", worker.v11_self_sentence_text(card))
        self.assertIn("Can you run the register", worker.v11_self_sentence_text(card))
        self.assertIn("只用于工作职责", worker.v11_misuse_text(card))
        self.assertIn("register 这里不是", worker.v11_misuse_text(card))

        no_matter = {
            "type": "phrase",
            "phrase": "no matter how",
            "teacher_note": "注意 no matter how 后面通常紧跟形容词或副词。",
            "usage_boundary": "适用于各种正式和非正式场合。",
            "confusable_note": "注意 no matter how 后面通常紧跟形容词或副词。",
        }
        misuse = worker.v11_misuse_text(no_matter)
        self.assertEqual(misuse.count("no matter how 后面通常紧跟"), 1)
        self.assertIn("适用于各种正式和非正式场合", misuse)

    def test_v11_back_template_labels_pronunciation_note_and_empty_spoken_status(self):
        self.assertIn("发音说明", worker.LANGUAGE_BACK_TEMPLATE_V11)
        self.assertIn("{{PronunciationStatus}}", worker.LANGUAGE_BACK_TEMPLATE_V11)
        self.assertIn("{{SourcePronunciationStatus}}", worker.LANGUAGE_BACK_TEMPLATE_V11)
        self.assertNotIn("未单独标注", worker.LANGUAGE_BACK_TEMPLATE_V11)
        self.assertIn("{{^SpokenIpa}}", worker.LANGUAGE_BACK_TEMPLATE_V11)

    def test_v11_long_answer_strips_listening_note_for_layout(self):
        card = {
            "type": "phrase",
            "phrase": "hold that against you",
            "english": "But we're not gonna hold that against you.",
            "chinese": "因此对你有看法；记你的仇",
            "natural_chinese": "我们不会因为这事儿对你有意见。",
            "answer_core": "hold that against you（听力中常连读为 hold tha-tagainst you）",
        }

        fields = worker.card_front_fields(card, repetition_mode=True)

        self.assertEqual(worker.card_answer_core(card), "hold that against you")
        self.assertEqual(fields["answer"], "hold that against you")
        self.assertEqual(worker.v11_answer_note_text(card), "听感：听力中常连读为 hold tha-tagainst you")
        self.assertEqual(worker.v11_meaning_text(card), "因此对你有看法；记你的仇")
        self.assertEqual(worker.v11_source_translation_text(card), "我们不会因为这事儿对你有意见。")

    def test_v11_answer_core_rejects_pronunciation_explanations(self):
        card = {
            "type": "phrase",
            "phrase": "bounce off a windshield",
            "english": "I seen one of those bounce off a windshield one time.",
            "chinese": "从挡风玻璃上弹开",
            "natural_chinese": "我见过那玩意儿从挡风玻璃上弹开。",
            "answer_core": "发音融合为 /baʊn sɔː fə/；'I seen' 是 'I saw' 的非标准口语变体，直接按过去式理解",
            "definition": "听到 /baʊn sɔː fə/ 时直接映射为 bounce off a，描述物体撞击表面后反弹开的动态过程。",
        }

        fields = worker.card_front_fields(card, repetition_mode=True)

        self.assertFalse(worker.is_answer_expression_candidate(card["answer_core"], card))
        self.assertEqual(worker.card_answer_core(card), "bounce off a windshield")
        self.assertEqual(fields["answer"], "bounce off a windshield")
        self.assertEqual(worker.v11_meaning_text(card), "从挡风玻璃上弹开")
        self.assertEqual(worker.v11_source_translation_text(card), "我见过那玩意儿从挡风玻璃上弹开。")

    def test_phrase_tts_uses_visible_answer_not_internal_phrase_field(self):
        card = {
            "type": "listening",
            "english": "Ever want me to read anything, I could critique it for you.",
            "phrase": "critique it",
            "answer_core": "Ever want me to",
            "chinese": "如果你什么时候想让我读点什么，我可以帮你点评。",
        }
        front_fields = worker.card_front_fields(card, repetition_mode=True)

        self.assertEqual(front_fields["answer"], "Ever want me to")
        self.assertEqual(worker.card_phrase_tts_text(card, front_fields), "Ever want me to")

    def test_sentence_tts_text_prefers_full_source_sentence_boundary(self):
        from acg.export_fields import card_sentence_tts_text

        segment = {
            "text": "rewires itself",
            "full_source_sentence": "The more you live in English, the faster your brain rewires itself.",
            "source_sentence": "The more you live in English, the faster your brain rewires itself.",
        }
        cards = [
            {
                "english": "rewires itself",
                "answer_core": "rewires itself",
                "phrase": "rewires itself",
                "normalized_answer": "rewires itself",
            }
        ]

        selected = card_sentence_tts_text(segment, cards)

        self.assertEqual(selected, "The more you live in English, the faster your brain rewires itself.")
        self.assertEqual(selected, worker.card_sentence_tts_text(segment, cards))
        self.assertNotEqual(selected, segment["text"])

    def test_merge_ai_cards_preserves_boundary_fields_for_back_template(self):
        segments = [
            {
                "id": "seg_0001",
                "start": 0.0,
                "end": 2.0,
                "source_time": "00:00:00.000 - 00:00:02.000",
                "text": "I mean you're flat as a washboard.",
                "phrase": "flat as a washboard",
                "score": 4.2,
                "recommendation": 5,
            }
        ]
        ai_payload = {
            "segments": [
                {
                    "id": "seg_0001",
                    "cards": [
                        {
                            "type": "phrase",
                            "phrase": "flat as a washboard",
                            "phrase_type": "idiom",
                            "content_kind": "phrase",
                            "english": "I mean you're flat as a washboard.",
                            "chinese": "你平得像个搓衣板。",
                            "definition": "夸张地说某人身体或表面很平。",
                            "collocations": "flat as a pancake / flat as a board",
                            "context": "非正式调侃里使用。",
                            "example": "After the diet joke, he said he was flat as a washboard.",
                            "chinese_feel": "画面感很强的调侃。",
                            "why": "能提醒学习者注意美剧里的夸张比喻。",
                            "difficulty": "C1 高阶表达",
                            "teacher_note": "语气偏调侃。",
                            "cloze": "You're ____.",
                            "retrieval_prompt": "这句里表示“平得像搓衣板”的夸张表达是什么？",
                            "answer_core": "flat as a washboard = 平得像搓衣板",
                            "usage_boundary": "调侃外貌或身材，可能冒犯；只适合很熟的人之间。",
                            "confusable_note": "不要当成中性夸奖，也不要用于正式场合。",
                        }
                    ],
                }
            ]
        }

        merged, _ = worker.merge_ai_cards(segments, ai_payload, ["phrase"], "C1")
        card = merged[0]["cards"][0]

        self.assertEqual(card["answer_core"], "flat as a washboard")
        self.assertIn("调侃外貌或身材，可能冒犯", card["teacher_note"])
        self.assertIn("不要当成中性夸奖", card["teacher_note"])
        self.assertIn("平得像搓衣板", worker.card_front_fields(card)["front_prompt"])

    def test_prompt_requests_retrieval_and_boundary_fields(self):
        prompt = worker.build_prompt(
            {
                "language": "English",
                "level": "B1",
                "collection_levels": ["B1", "B2"],
                "card_types": ["phrase"],
            },
            [
                {
                    "id": "seg_0001",
                    "text": "I'm gonna run the register.",
                    "phrase": "run the register",
                    "source_time": "00:00:01.000 - 00:00:03.000",
                    "recommendation": 5,
                }
            ],
        )

        self.assertIn("retrieval_prompt", prompt)
        self.assertIn("answer_core", prompt)
        self.assertIn("禁止在 answer_core 写中文释义、IPA、发音融合、连读说明", prompt)
        self.assertIn("usage_boundary", prompt)
        self.assertIn("confusable_note", prompt)
        self.assertIn("phonetic_ipa", prompt)
        self.assertIn("spoken_ipa", prompt)
        self.assertIn("source_spoken_ipa", prompt)
        self.assertIn("generation_basis 必须是 subtitle_inferred", prompt)
        self.assertIn("source_spoken_ipa 必须覆盖完整原句", prompt)
        self.assertIn("不能只覆盖 answer_core", prompt)
        self.assertIn("same_as_standard_reason", prompt)
        self.assertIn("不要只写短语片段", prompt)
        self.assertIn("学习卡 retrieval_prompt 要问一个明确的主动回忆问题", prompt)
        self.assertIn("typed learning point", prompt)
        self.assertIn("不要额外输出 listening 或 cloze 卡", prompt)

    def test_fast_review_prompt_requests_minimal_fields_to_reduce_tokens(self):
        prompt = worker.build_prompt(
            {
                "language": "English",
                "level": "B1",
                "collection_levels": ["B1", "B2"],
                "card_types": ["phrase"],
                "review_density": "fast",
            },
            [
                {
                    "id": "seg_0001",
                    "text": "I'm gonna run the register.",
                    "phrase": "run the register",
                    "source_time": "00:00:01.000 - 00:00:03.000",
                    "recommendation": 5,
                }
            ],
        )

        self.assertIn("快速复读模式", prompt)
        self.assertIn("减少 token", prompt)
        self.assertIn("不要输出长段落", prompt)
        self.assertIn("definition/context/example/collocations/why/why_it_matters/how_to_use_it/usage_boundary/confusable_note", prompt)
        self.assertIn("每张卡只生成最小复习字段", prompt)
        full_prompt = worker.build_prompt(
            {
                "language": "English",
                "level": "B1",
                "collection_levels": ["B1", "B2"],
                "card_types": ["phrase"],
                "review_density": "full",
            },
            [
                {
                    "id": "seg_0001",
                    "text": "I'm gonna run the register.",
                    "phrase": "run the register",
                    "source_time": "00:00:01.000 - 00:00:03.000",
                    "recommendation": 5,
                }
            ],
        )
        self.assertLess(len(prompt), len(full_prompt) * 0.7)
        self.assertNotIn("pronunciation_meta", prompt)
        self.assertNotIn("source_spoken_ipa", prompt)

    def test_partial_source_spoken_ipa_is_cleared(self):
        card = {
            "english": "We will produce a chemically pure And stable product that performs as advertised.",
            "answer_core": "performs as advertised",
            "phrase": "performs as advertised",
            "phonetic_ipa": "/pərˈfɔrmz æz ˈædvərˌtaɪzd/",
            "spoken_ipa": "/pɚˈfɔrmz əz ˈædvɚˌtaɪzd/",
            "source_spoken_ipa": "/pɚˈfɔrmz əz ˈædvɚˌtaɪzd/",
        }

        issues = worker.sanitize_pronunciation_fields(card, "English")

        self.assertNotIn("source_spoken_ipa", card)
        self.assertIn("source_spoken_ipa 不是完整原句听感，已清空。", issues)

    def test_full_source_spoken_ipa_is_kept_when_near_sentence_length(self):
        card = {
            "english": "What time do you think you'll be home?",
            "answer_core": "What time do you think you'll be",
            "phrase": "What time do you think you'll be",
            "phonetic_ipa": "/wʌt taɪm du ju θɪŋk jul bi/",
            "spoken_ipa": "/wət taɪm dʒə θɪŋk jəl bi/",
            "source_spoken_ipa": "/wət taɪm dʒə θɪŋk jəl bi hoʊm/",
        }

        issues = worker.sanitize_pronunciation_fields(card, "English")

        self.assertEqual([], issues)
        self.assertEqual("/wət taɪm dʒə θɪŋk jəl bi hoʊm/", card["source_spoken_ipa"])

    def test_duplicate_spoken_ipa_is_cleared_for_reduction_phrase(self):
        card = {
            "english": "What if we rented one of those self-storage places?",
            "answer_core": "What if we rented",
            "phonetic_ipa": "/wʌt ɪf wi ˈrɛntɪd/",
            "spoken_ipa": "/wʌt ɪf wi ˈrɛntɪd/",
        }

        issues = worker.sanitize_pronunciation_fields(card, "English")

        self.assertIn("phonetic_ipa", card)
        self.assertNotIn("spoken_ipa", card)
        self.assertIn("spoken_ipa 与标准读法完全相同，缺少口语听感，已清空。", issues)

    def test_duplicate_spoken_ipa_is_allowed_for_single_word_answer(self):
        card = {
            "english": "I mean you're flat as a washboard.",
            "answer_core": "washboard",
            "phonetic_ipa": "/ˈwɑʃˌbɔrd/",
            "spoken_ipa": "/ˈwɑʃˌbɔrd/",
        }

        issues = worker.sanitize_pronunciation_fields(card, "English")

        self.assertEqual([], issues)
        self.assertEqual("/ˈwɑʃˌbɔrd/", card["spoken_ipa"])

    def test_same_spoken_standard_gets_reason_when_kept(self):
        card = {
            "english": "You get paid till 5 You work till 5 no later.",
            "answer_core": "no later",
            "phonetic_ipa": "/noʊ ˈleɪtər/",
            "spoken_ipa": "/noʊ ˈleɪtər/",
            "source_spoken_ipa": "/ju ɡɛt peɪd tɪl faɪv | ju wɜrk tɪl faɪv | noʊ ˈleɪtər/",
            "pronunciation_meta": {
                "generation_basis": "subtitle_inferred",
                "field_confidence": {
                    "phonetic_ipa": "medium",
                    "spoken_ipa": "medium",
                    "source_spoken_ipa": "medium",
                },
                "validation_issues": [
                    {
                        "field": "spoken_ipa",
                        "severity": "warn",
                        "code": "SAME_AS_STANDARD_REASON_REQUIRED",
                        "message": "口语读法与标准读法相同，必须说明 same_as_standard_reason。",
                    }
                ],
            },
        }

        issues = worker.sanitize_pronunciation_fields(card, "English")

        self.assertNotIn("SAME_AS_STANDARD_REASON_REQUIRED", " ".join(issues))
        self.assertEqual("/noʊ ˈleɪtər/", card["spoken_ipa"])
        self.assertIn("未实听", card["pronunciation_meta"]["same_as_standard_reason"])
        self.assertIn("口语读法与标准读法暂按相同处理", card["pronunciation_note"])
        self.assertNotIn(
            "SAME_AS_STANDARD_REASON_REQUIRED",
            [issue["code"] for issue in card["pronunciation_meta"]["validation_issues"]],
        )

    def test_pronunciation_meta_defaults_to_subtitle_inferred_and_caps_spoken_confidence(self):
        card = {
            "english": "What time do you think you'll be home?",
            "answer_core": "What time do you think you'll be",
            "phonetic_ipa": "/wʌt taɪm du ju θɪŋk jul bi/",
            "spoken_ipa": "/wət taɪm dʒə θɪŋk jəl bi/",
            "source_spoken_ipa": "/wət taɪm dʒə θɪŋk jəl bi hoʊm/",
            "pronunciation_meta": {
                "generation_basis": "subtitle_inferred",
                "field_confidence": {
                    "phonetic_ipa": "high",
                    "spoken_ipa": "high",
                    "source_spoken_ipa": "high",
                },
                "validation_issues": [],
            },
        }

        worker.sanitize_pronunciation_fields(card, "en")

        meta = card["pronunciation_meta"]
        self.assertEqual(meta["language_code"], "en")
        self.assertEqual(meta["generation_basis"], "subtitle_inferred")
        self.assertEqual(meta["field_confidence"]["spoken_ipa"], "medium")
        self.assertEqual(meta["field_confidence"]["source_spoken_ipa"], "medium")
        self.assertEqual(card["pronunciation_confidence"], "medium")
        self.assertNotIn("未实听", card.get("pronunciation_note", ""))
        self.assertEqual(card.get("pronunciation_status", ""), "")

    def test_dictionary_only_global_confidence_uses_lowest_field_confidence(self):
        card = {
            "english": "I'm gonna run the register.",
            "answer_core": "run the register",
            "phrase": "run the register",
            "phonetic_ipa": "/rʌn ðə ˈrɛdʒɪstər/",
            "spoken_ipa": "/rʌn ðə ˈrɛdʒɪstər/",
            "source_spoken_ipa": "/aɪm ˈɡʌnə rʌn ðə ˈrɛdʒɪstər/",
            "pronunciation_meta": {
                "generation_basis": "dictionary_only",
                "field_confidence": {
                    "phonetic_ipa": "high",
                    "spoken_ipa": "low",
                    "source_spoken_ipa": "low",
                    "pronunciation_note": "medium",
                },
                "validation_issues": [],
            },
        }

        worker.sanitize_pronunciation_fields(card, "en")

        self.assertNotIn("spoken_ipa", card)
        self.assertNotIn("source_spoken_ipa", card)
        self.assertEqual(card["pronunciation_confidence"], "low")
        self.assertEqual(card["pronunciation_meta"]["field_confidence"]["phonetic_ipa"], "high")

    def test_dictionary_only_defaults_missing_spoken_confidence_to_low(self):
        card = {
            "english": "I'm gonna run the register.",
            "answer_core": "run the register",
            "phrase": "run the register",
            "phonetic_ipa": "/rʌn ðə ˈrɛdʒɪstər/",
            "pronunciation_meta": {
                "generation_basis": "dictionary_only",
                "field_confidence": {"phonetic_ipa": "high"},
                "validation_issues": [],
            },
        }

        worker.sanitize_pronunciation_fields(card, "en")

        self.assertEqual(card["pronunciation_meta"]["field_confidence"]["spoken_ipa"], "low")
        self.assertEqual(card["pronunciation_meta"]["field_confidence"]["source_spoken_ipa"], "low")
        self.assertEqual(card["pronunciation_confidence"], "low")

    def test_dictionary_only_without_any_pronunciation_leaves_visible_status_blank(self):
        card = {
            "english": "I'm shorthanded, Walter. What am I to do?",
            "answer_core": "shorthanded",
            "phrase": "shorthanded",
            "pronunciation_meta": {
                "generation_basis": "dictionary_only",
                "field_confidence": {
                    "phonetic_ipa": "low",
                    "spoken_ipa": "low",
                    "source_spoken_ipa": "low",
                    "pronunciation_note": "low",
                },
                "validation_issues": [],
            },
        }

        issues = worker.sanitize_pronunciation_fields(card, "en")

        self.assertIn("未生成可靠读法字段。", issues)
        self.assertNotIn("pronunciation_note", card)
        self.assertEqual(card.get("pronunciation_status", ""), "")
        self.assertEqual(card.get("source_pronunciation_status", ""), "")
        self.assertEqual(card["pronunciation_confidence"], "low")
        self.assertIn("PRONUNCIATION_NOT_GENERATED", [issue["code"] for issue in card["pronunciation_meta"]["validation_issues"]])
        self.assertIn("PRONUNCIATION_NOT_GENERATED", [change["code"] for change in card["pronunciation_meta"]["field_changes"]])

    def test_blocked_source_spoken_ipa_sets_low_confidence(self):
        card = {
            "english": "Red Phosphorus in the presence of moisture And accelerated by heat yields Phosphorus Hydride.",
            "answer_core": "in the presence of",
            "phrase": "in the presence of",
            "phonetic_ipa": "/ɪn ðə ˈprɛzəns ʌv/",
            "spoken_ipa": "/ɪn ðə ˈprɛzəns əv/",
            "source_spoken_ipa": "/ɪn ðə ˈprɛzəns əv/",
            "pronunciation_meta": {
                "generation_basis": "subtitle_inferred",
                "field_confidence": {
                    "phonetic_ipa": "medium",
                    "spoken_ipa": "medium",
                    "source_spoken_ipa": "medium",
                },
                "validation_issues": [],
            },
        }

        issues = worker.sanitize_pronunciation_fields(card, "en")

        self.assertNotIn("source_spoken_ipa", card)
        self.assertIn("source_spoken_ipa 不是完整原句听感，已清空。", issues)
        self.assertEqual(card["pronunciation_meta"]["field_confidence"]["source_spoken_ipa"], "low")
        changes = card["pronunciation_meta"]["field_changes"]
        self.assertEqual(changes[0]["field"], "source_spoken_ipa")
        self.assertEqual(changes[0]["action"], "hidden")
        self.assertEqual(changes[0]["code"], "SOURCE_PRONUNCIATION_TOO_SHORT")
        self.assertNotIn("原句听感未可靠生成", card.get("pronunciation_note", ""))
        self.assertEqual(card.get("source_pronunciation_status", ""), "")
        self.assertEqual(card["pronunciation_confidence"], "low")

    def test_export_quality_audit_detects_drafts_duplicates_and_bad_meta(self):
        card = {
            "id": "c1",
            "type": "phrase",
            "enabled": True,
            "english": "Can you run the register for a minute?",
            "answer_core": "run the register",
            "phrase": "run the register",
            "chinese": "操作收银机",
            "definition": "本地草稿",
            "teacher_note": "正式卡片不能包含内部草稿提示。",
            "context": "你能帮忙收一下银吗？",
            "pronunciation_meta": "{bad-json}",
        }
        duplicate = {**card, "id": "c2", "definition": "operate the cash register"}

        audit = worker.export_quality_audit({}, [{"id": "s1", "text": card["english"], "cards": [card, duplicate]}])

        self.assertEqual(audit["card_count"], 2)
        self.assertGreaterEqual(audit["blocked_text_values"], 1)
        self.assertEqual(audit["duplicate_visible_cards"], 1)
        self.assertEqual(audit["pronunciation_meta_errors"], 2)

    def test_existing_blocked_empty_source_keeps_low_confidence_on_resanitize(self):
        card = {
            "english": "Red Phosphorus in the presence of moisture And accelerated by heat yields Phosphorus Hydride.",
            "answer_core": "in the presence of",
            "phrase": "in the presence of",
            "phonetic_ipa": "/ɪn ðə ˈprɛzəns ʌv/",
            "spoken_ipa": "/ɪn ðə ˈprɛzəns əv/",
            "pronunciation_meta": {
                "generation_basis": "subtitle_inferred",
                "field_confidence": {
                    "phonetic_ipa": "medium",
                    "spoken_ipa": "medium",
                    "source_spoken_ipa": "medium",
                },
                "validation_issues": [
                    {
                        "field": "source_spoken_ipa",
                        "severity": "block",
                        "code": "SOURCE_PRONUNCIATION_TOO_SHORT",
                        "message": "source_spoken_ipa 不是完整原句听感，已清空。",
                    }
                ],
            },
        }

        worker.sanitize_pronunciation_fields(card, "en")

        self.assertEqual(card["pronunciation_meta"]["field_confidence"]["source_spoken_ipa"], "low")
        self.assertEqual(card["pronunciation_confidence"], "low")

    def test_spanish_latam_theta_is_blocked(self):
        card = {
            "english": "cereza",
            "answer_core": "cereza",
            "phonetic_ipa": "/θeˈɾeθa/",
        }

        issues = worker.sanitize_pronunciation_fields(card, "es")

        self.assertNotIn("phonetic_ipa", card)
        self.assertEqual(card["pronunciation_meta"]["language_code"], "es")
        self.assertIn("默认拉美西语 profile 不使用 /θ/", " / ".join(issues))

    def test_japanese_romaji_standard_reading_is_blocked(self):
        card = {
            "english": "何してるの？",
            "answer_core": "何してるの",
            "phonetic_ipa": "nani shiteru no",
        }

        issues = worker.sanitize_pronunciation_fields(card, "ja")

        self.assertNotIn("phonetic_ipa", card)
        self.assertEqual(card["pronunciation_meta"]["notation_system"], "kana_pitch")
        self.assertIn("日语标准读法不能只有 romaji", " / ".join(issues))

    def test_russian_multisyllable_standard_reading_requires_stress(self):
        card = {
            "english": "молоко",
            "answer_core": "молоко",
            "phonetic_ipa": "молоко",
        }

        issues = worker.sanitize_pronunciation_fields(card, "ru")

        self.assertNotIn("phonetic_ipa", card)
        self.assertEqual(card["pronunciation_meta"]["language_code"], "ru")
        self.assertIn("俄语多音节实词必须标重音", " / ".join(issues))

    def test_french_et_liaison_is_warned_not_cleared(self):
        card = {
            "english": "et ami",
            "answer_core": "et ami",
            "phonetic_ipa": "/e a.mi/",
            "source_spoken_ipa": "et‿ami",
        }

        issues = worker.sanitize_pronunciation_fields(card, "fr")

        self.assertEqual("et‿ami", card["source_spoken_ipa"])
        self.assertIn("法语 et 后通常禁连读", " / ".join(issues))

    def test_v10_template_is_review_first_and_mobile_flowing(self):
        self.assertIn("{{#IsListening}}", worker.FRONT_TEMPLATE)
        self.assertIn("{{^IsListening}}", worker.FRONT_TEMPLATE)
        self.assertIn("原声", worker.FRONT_TEMPLATE)
        self.assertNotIn("整句 AI 朗读", worker.FRONT_TEMPLATE)
        self.assertIn("核心答案", worker.BACK_TEMPLATE)
        self.assertIn("老师提醒", worker.BACK_TEMPLATE)
        self.assertIn("再造一句", worker.BACK_TEMPLATE)
        self.assertIn("layout-{{CardLayout}}", worker.FRONT_TEMPLATE)
        self.assertIn("{{FrontKicker}}", worker.FRONT_TEMPLATE)
        self.assertIn("{{SourceLabel}}", worker.BACK_TEMPLATE)
        self.assertIn("{{UnderstandLabel}}", worker.BACK_TEMPLATE)
        self.assertIn("{{UseLabel}}", worker.BACK_TEMPLATE)
        self.assertIn("overflow-y: auto !important", worker.CARD_CSS)
        self.assertIn("height: auto", worker.CARD_CSS)
        self.assertNotIn("fitResponsiveText", worker.FRONT_TEMPLATE + worker.BACK_TEMPLATE)

    def test_card_template_labels_are_source_aware(self):
        listening = worker.card_template_labels({"type": "listening"}, "video_language")
        phrase = worker.card_template_labels({"type": "phrase", "phrase_type": "collocation"}, "video_language")
        cloze = worker.card_template_labels({"type": "cloze"}, "video_language")
        vocab = worker.card_template_labels(
            {"type": "phrase", "phrase_type": "vocabulary_usage", "content_kind": "vocabulary"},
            "video_language",
        )
        knowledge = worker.card_template_labels({"type": "knowledge"}, "document_knowledge")
        reading = worker.card_template_labels({"type": "phrase"}, "document_reading")

        self.assertEqual(listening["card_layout"], "listening")
        self.assertEqual(listening["source_label"], "听力原句")
        self.assertEqual(phrase["card_layout"], "phrase")
        self.assertEqual(cloze["card_layout"], "cloze")
        self.assertEqual(vocab["card_layout"], "vocabulary")
        self.assertEqual(vocab["understand_label"], "此处词义")
        self.assertEqual(knowledge["understand_label"], "关键机制")
        self.assertEqual(reading["card_layout"], "document_reading")

    def test_template_assets_split_by_project_kind(self):
        v11 = worker.anki_template_assets("immersive_v11", "video_language")
        v11_fast = worker.anki_template_assets("immersive_v11", "video_language", None, "fast")
        ciba = worker.anki_template_assets("ciba_tianxia_v1", "video_language")
        language = worker.anki_template_assets("immersive", "video_language")
        knowledge = worker.anki_template_assets("immersive", "document_knowledge")
        reading = worker.anki_template_assets("immersive", "document_reading")

        self.assertEqual(v11[0], "沉浸复读 V11")
        self.assertEqual(ciba[0], "词霸天下实验 V1 · 暖色纸感")
        minimal_ciba = worker.anki_template_assets("ciba_tianxia_v1", "video_language", "minimal_white")
        dark_ciba = worker.anki_template_assets("ciba_tianxia_v1", "video_language", "dark_immersive")
        self.assertEqual(minimal_ciba[0], "词霸天下实验 V1 · 极简白卡")
        self.assertEqual(dark_ciba[0], "词霸天下实验 V1 · 深色沉浸")
        self.assertIn("ciba-style-warm-paper", ciba[1])
        self.assertIn("ciba-style-minimal-white", minimal_ciba[1])
        self.assertIn("ciba-style-dark-immersive", dark_ciba[1])
        self.assertNotEqual(ciba[1], minimal_ciba[1])
        self.assertNotEqual(ciba[1], dark_ciba[1])
        self.assertEqual(worker.normalize_card_style("unknown-style"), "warm_paper")
        self.assertEqual(worker.anki_template_version("ciba_tianxia_v1", "video_language"), "V12")
        self.assertNotEqual(ciba[2], v11[2])
        self.assertNotEqual(ciba[3], v11[3])
        self.assertIn("语言动作卡", ciba[2] + ciba[3])
        self.assertIn("核心答案", ciba[3])
        self.assertIn("语境义", ciba[3])
        self.assertIn("语言动作", ciba[3])
        self.assertIn("为什么选它", ciba[3])
        self.assertIn("迁移句", ciba[3])
        self.assertIn("搭配边界", ciba[3])
        self.assertIn("原句场景", ciba[3])
        self.assertIn("发音提示", ciba[3])
        self.assertIn("--ciba-paper", ciba[1])
        self.assertIn("ciba-focus-card", ciba[2] + ciba[3])
        self.assertIn("ciba-core-group", ciba[3])
        self.assertIn("理解核心", ciba[3])
        self.assertIn("ciba-priority-grid", ciba[3])
        self.assertIn("ciba-study-stack", ciba[3])
        self.assertIn("ciba-transfer-group", ciba[3])
        self.assertIn("迁移使用", ciba[3])
        self.assertIn("ciba-essential-block", ciba[3])
        self.assertIn("ciba-conceptual-block", ciba[3])
        self.assertIn("ConceptualAction", ciba[3])
        self.assertIn("ChineseLearnerTrap", ciba[3])
        self.assertIn("ciba-group-label", ciba[1])
        self.assertIn("ciba-core-group", ciba[1])
        self.assertIn("ciba-transfer-group", ciba[1])
        self.assertIn("ciba-inline-audio-row", ciba[3])
        self.assertIn("ciba-compact-audio-item", ciba[1])
        self.assertLess(ciba[3].index("ciba-source-block"), ciba[3].index("ciba-core-group"))
        self.assertLess(ciba[3].index("ciba-video-stage"), ciba[3].index("ciba-core-group"))
        self.assertLess(ciba[3].index("ciba-core-group"), ciba[3].index("ciba-priority-grid"))
        self.assertLess(ciba[3].index("ciba-priority-grid"), ciba[3].index("ciba-conceptual-stack"))
        self.assertLess(ciba[3].index("ciba-conceptual-stack"), ciba[3].index("ciba-transfer-group"))
        self.assertLess(ciba[3].index("ciba-transfer-group"), ciba[3].index("ciba-study-stack"))
        self.assertLess(ciba[3].index("ciba-video-stage"), ciba[3].index("ciba-source-context"))
        self.assertIn("ciba-audio-row ciba-inline-audio-row", ciba[3])
        self.assertNotIn("怎么用", ciba[3])
        self.assertNotIn("别误用", ciba[3])
        self.assertNotIn("自己造句", ciba[3])
        self.assertIn("v11-video-stage", v11[2])
        self.assertEqual(v11_fast[0], "沉浸复读 V11 · 快速复读")
        self.assertEqual(worker.anki_template_version("immersive_v11", "video_language"), "V14")
        self.assertIn("fast-review-card", v11_fast[1] + v11_fast[2] + v11_fast[3])
        self.assertNotEqual(v11_fast[2], v11[2])
        self.assertIn("语境义", v11_fast[3])
        for field in ["{{Video}}", "{{Audio}}", "{{TtsAudio}}", "{{PhraseTtsAudio}}"]:
            self.assertIn(field, v11[2] + v11[3])
            self.assertIn(field, v11_fast[2] + v11_fast[3])
        self.assertIn("{{PhraseTtsAudio}}", v11_fast[3])
        self.assertLess(v11_fast[3].index("fast-answer-focus"), v11_fast[3].index("v11-video-stage"))
        self.assertNotIn("怎么用", v11_fast[3])
        self.assertNotIn("别误用", v11_fast[3])
        self.assertNotIn("例句与迁移", v11_fast[3])
        self.assertNotIn("词霸天下", v11_fast[2] + v11_fast[3])
        self.assertNotIn("语言动作", v11_fast[2] + v11_fast[3])
        self.assertNotIn("v11-info-grid", v11_fast[3])
        self.assertLess(v11[3].index("v11-answer-main"), v11[3].index("v11-video-stage"))
        self.assertLess(v11[3].index('{{Answer}}</h1>'), v11[3].index('data-media-role="phrase"'))
        self.assertLess(v11[3].index('data-media-role="phrase"'), v11[3].index("{{#Chinese}}"))
        self.assertLess(v11_fast[3].index('{{Answer}}</h1>'), v11_fast[3].index('data-media-role="phrase"'))
        self.assertLess(v11_fast[3].index('data-media-role="phrase"'), v11_fast[3].index("{{#Chinese}}"))
        self.assertEqual(v11[3].count('data-media-role="phrase"'), 1)
        self.assertEqual(v11_fast[3].count('data-media-role="phrase"'), 1)
        self.assertIn(".v11-video-stage.is-error", v11[1])
        self.assertIn(".v11-video-stage.is-paused", v11[1])
        self.assertIn(".v11-answer-layout > .v11-video-stage", v11[1])
        self.assertIn(".v11-back .v11-answer-layout", v11[1])
        self.assertIn("flex-direction: column", v11[1])
        self.assertIn('aria-label="点击播放视频"', v11[2] + v11[3])
        self.assertIn('stage.addEventListener("keydown"', v11[2] + v11[3])
        self.assertIn("▮ 复读卡", v11[2] + v11[3])
        self.assertIn("playV11Audio", v11[2] + v11[3])
        self.assertIn("toggleV11Video", v11[2] + v11[3])
        self.assertIn("播放原声", v11[2] + v11[3])
        self.assertIn("播放慢读", v11[2] + v11[3])
        self.assertIn('data-media-state="idle"', v11[2] + v11[3])
        self.assertIn('aria-live="polite"', v11[2] + v11[3])
        self.assertIn("setV11AudioState", v11[2] + v11[3])
        self.assertIn('<div class="v11-label">{{CardType}}</div>', v11[3])
        self.assertIn("{{ContextDisplay}}", v11[3])
        self.assertIn("怎么用", v11[3])
        self.assertIn("别误用", v11[3])
        self.assertIn("例句与迁移", v11[3])
        self.assertIn("{{EnglishDisplay}}", v11[3])
        self.assertIn("{{TransferExamplesDisplay}}", v11[3])
        self.assertIn("{{ChineseDisplay}}", v11[3])
        self.assertIn("{{ChineseFeelDisplay}}", v11[3])
        self.assertIn("{{PronunciationNoteDisplay}}", v11[3])
        self.assertIn("{{ContextDisplay}}", v11[3])
        self.assertIn("{{DefinitionDisplay}}", v11[3])
        self.assertIn("{{TeacherNoteDisplay}}", v11[3])
        self.assertIn("understanding-block", v11[3])
        self.assertIn("boundary-block", v11[3])
        self.assertIn("transfer-block", v11[3])
        self.assertNotIn("怎么理解", v11[3])
        self.assertNotIn("怎么迁移", v11[3])
        self.assertNotIn("语言动作", v11[3])
        self.assertNotIn("词霸天下", v11[3])
        self.assertIn(".target-expression", v11[1])
        self.assertIn("font-size: 1.08em", v11[1])
        self.assertNotIn("box-shadow: inset 0 -2px", v11[1])
        self.assertIn("width: 44px", v11[1])
        self.assertNotIn("target-expression", v11[2])
        self.assertIn("v11-answer-title.is-long", v11[1])
        self.assertIn("setupV11TextSizing", v11[2] + v11[3])
        self.assertIn("{{ChineseFeelDisplay}}", v11[3])
        self.assertIn("{{#PhoneticIpa}}", v11[3])
        self.assertIn("标准读法", v11[3])
        self.assertIn("{{SpokenPronunciationLabel}}", v11[3])
        self.assertIn("v11-ipa-row is-spoken", v11[3])
        self.assertIn(".v11-source-block", v11[1])
        self.assertIn("grid-template-columns: max-content minmax(0, 1fr)", v11[1])
        self.assertLess(v11[3].index("{{#EnglishDisplay}}"), v11[3].index("v11-source-ipa"))
        self.assertLess(v11[3].index("v11-source-ipa"), v11[3].index("v11-source-translation"))
        self.assertNotIn("overflow-wrap: anywhere", v11[1])
        self.assertNotIn("<audio controls", v11[2] + v11[3])
        self.assertEqual(language[0], "视频语言 V10")
        self.assertEqual(knowledge[0], "文档知识 V10")
        self.assertEqual(reading[0], "文档精读 V10")
        self.assertIn("{{SourceLabel}}", language[3])
        self.assertIn("{{UnderstandLabel}}", knowledge[3])
        self.assertIn("knowledge-answer-shell", knowledge[3])
        self.assertIn("原文依据", knowledge[3])
        self.assertIn("理解结构", knowledge[3])
        self.assertIn("复习动作", knowledge[3])
        self.assertIn("knowledge-evidence-card", knowledge[1])
        self.assertIn("knowledge-action-card", knowledge[1])
        self.assertIn("knowledge-transfer-check", knowledge[1] + knowledge[3])
        self.assertIn("@media (max-width: 560px)", knowledge[1])
        self.assertIn(".knowledge-card .answer { font-size: clamp(24px, 6.8vw, 32px); }", knowledge[1])
        self.assertIn("迁移检查", knowledge[3])
        self.assertLess(knowledge[3].index("核心答案"), knowledge[3].index("原文依据"))
        self.assertLess(knowledge[3].index("原文依据"), knowledge[3].index("理解结构"))
        self.assertLess(knowledge[3].index("理解结构"), knowledge[3].index("迁移检查"))
        self.assertLess(knowledge[3].index("迁移检查"), knowledge[3].index("复习动作"))
        self.assertIn("边界 / 易错", reading[3])
        self.assertNotEqual(worker.anki_template_family("immersive_v11", "video_language"), worker.anki_template_family("immersive", "video_language"))
        self.assertNotEqual(worker.anki_template_family("ciba_tianxia_v1", "video_language"), worker.anki_template_family("immersive_v11", "video_language"))
        self.assertNotEqual(worker.anki_template_family("immersive", "video_language"), worker.anki_template_family("immersive", "document_knowledge"))

    def test_all_templates_follow_recall_first_visual_hierarchy(self):
        variants = [
            ("immersive", "video_language", None),
            ("dictionary", "video_language", None),
            ("minimal", "video_language", None),
            ("immersive", "document_knowledge", None),
            ("immersive", "document_reading", None),
            ("immersive_v11", "video_language", None),
            ("ciba_tianxia_v1", "video_language", "warm_paper"),
            ("ciba_tianxia_v1", "video_language", "minimal_white"),
            ("ciba_tianxia_v1", "video_language", "dark_immersive"),
        ]

        for template_id, project_kind, card_style in variants:
            with self.subTest(template_id=template_id, project_kind=project_kind, card_style=card_style):
                name, css, front, back = worker.anki_template_assets(template_id, project_kind, card_style)
                combined = css + front + back
                self.assertIn("learning-hierarchy-system", css, name)
                self.assertIn("recall-task", front, name)
                self.assertIn("answer-anchor", back, name)
                self.assertIn("evidence-anchor", back, name)
                if template_id == "immersive_v11":
                    self.assertIn("v11-info-block", back, name)
                    self.assertIn("怎么用", back, name)
                    self.assertIn("别误用", back, name)
                    self.assertIn("例句与迁移", back, name)
                elif template_id == "ciba_tianxia_v1":
                    self.assertIn("ciba-core-group", back, name)
                    self.assertIn("ciba-priority-grid", back, name)
                    self.assertIn("ciba-transfer-group", back, name)
                else:
                    self.assertIn("understanding-block", back, name)
                    self.assertIn("boundary-block", back, name)
                    self.assertIn("transfer-block", back, name)
                self.assertIn("font-weight: 950", css, name)
                self.assertLess(back.index("answer-anchor"), back.index("evidence-anchor"), name)
                self.assertNotIn("#0D1117", combined, name)
                self.assertNotIn("cyber", combined.lower(), name)

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

    def test_phrase_review_repairs_phrase_not_in_sentence_when_local_phrase_exists(self):
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

        self.assertEqual(skipped, [])
        self.assertEqual(kept[0]["phrase"], "such a nice")
        self.assertEqual(kept[0]["phrase_review_status"], "recommended")

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

    def test_placeholder_phrase_segments_are_not_deduped_as_one_expression(self):
        segments = [
            {
                "id": "seg_0001",
                "start": 0.0,
                "text": "You won't even taste the difference.",
                "phrase": "key expression",
                "normalized_answer": "key expression",
                "candidate_kind": "expression",
                "phrase_card_focus": "人工确认是否值得制卡。",
                "score": 3.6,
                "phrase_value_score": 3,
            },
            {
                "id": "seg_0002",
                "start": 4.0,
                "text": "What time do you think you'll be home?",
                "phrase": "key expression",
                "normalized_answer": "key expression",
                "candidate_kind": "expression",
                "phrase_card_focus": "人工确认是否值得制卡。",
                "score": 3.4,
                "phrase_value_score": 3,
            },
            {
                "id": "seg_0003",
                "start": 8.0,
                "text": "I hope you know that.",
                "phrase": "key expression",
                "normalized_answer": "key expression",
                "candidate_kind": "expression",
                "phrase_card_focus": "人工确认是否值得制卡。",
                "score": 3.2,
                "phrase_value_score": 3,
            },
        ]

        kept, duplicates = worker.split_duplicate_phrase_segments(segments)

        self.assertEqual({item["id"] for item in kept}, {"seg_0001", "seg_0002", "seg_0003"})
        self.assertEqual(duplicates, [])

    def test_same_source_sentence_keeps_at_most_two_learning_points(self):
        source_id = "src_same_sentence"
        segments = [
            {
                "id": "seg_0001",
                "source_segment_id": source_id,
                "start": 0.0,
                "end": 2.5,
                "text": "I'm gonna run the register.",
                "phrase": "run the register",
                "normalized_answer": "run the register",
                "candidate_kind": "expression",
                "score": 4.8,
                "phrase_value_score": 5,
            },
            {
                "id": "seg_0002",
                "source_segment_id": source_id,
                "start": 0.0,
                "end": 2.5,
                "text": "I'm gonna run the register.",
                "phrase": "register",
                "normalized_answer": "register",
                "candidate_kind": "contextual_vocab",
                "score": 4.2,
                "phrase_value_score": 4,
            },
            {
                "id": "seg_0003",
                "source_segment_id": source_id,
                "start": 0.0,
                "end": 2.5,
                "text": "I'm gonna run the register.",
                "phrase": "gonna",
                "normalized_answer": "gonna",
                "candidate_kind": "listening_feature",
                "score": 3.9,
                "phrase_value_score": 4,
            },
        ]

        kept, rejected = worker.enforce_max_learning_points_per_source(segments, 2)

        self.assertEqual(len(kept), 2)
        self.assertEqual({item["id"] for item in kept}, {"seg_0001", "seg_0002"})
        self.assertEqual([item["id"] for item in rejected], ["seg_0003"])
        self.assertEqual(rejected[0]["phrase_review_status"], "reject")
        self.assertIn("预算已满", rejected[0]["phrase_reject_reason"])

    def test_selection_strategy_learning_point_budgets_are_v2_values(self):
        self.assertEqual(worker.max_learning_points_per_source({"selection_strategy": "catch_all"}), 4)
        self.assertEqual(worker.max_learning_points_per_source({"selection_strategy": "exhaustive"}), 4)
        self.assertEqual(worker.max_learning_points_per_source({"selection_strategy": "curated"}), 4)

    def test_hermes_grok_card_generation_is_small_and_serial(self):
        api = {
            "provider": "openai-compatible",
            "base_url": "http://127.0.0.1:8645/v1",
            "model": "grok-4.5",
        }

        self.assertTrue(worker.is_hermes_local_config(api))
        self.assertEqual(worker.final_card_batch_size(api, 10), 6)
        self.assertEqual(worker.final_card_generation_concurrency(api, 4), 1)
        self.assertFalse(
            worker.is_hermes_local_config(
                {**api, "base_url": "https://example.com/v1"}
            )
        )

    def test_model_segment_ids_are_reconciled_by_learning_point_id(self):
        requested = [
            {
                "id": "seg_lp_0019",
                "learning_point_id": "lp-actions",
                "text": "Actions speak louder than words.",
                "answer_core": "Actions speak louder than words",
                "learning_points": [{"id": "lp-actions", "answer_core": "Actions speak louder than words"}],
            },
            {
                "id": "seg_lp_0020",
                "learning_point_id": "lp-opinions",
                "text": "People form opinions about it.",
                "answer_core": "form opinions about",
                "learning_points": [{"id": "lp-opinions", "answer_core": "form opinions about"}],
            },
        ]
        model_segments = [
            {
                "id": "seg_lp_0001",
                "cards": [{"learning_point_id": "lp-actions", "phrase": "Actions speak louder than words"}],
            },
            {
                "id": "seg_lp_0001",
                "cards": [{"learning_point_id": "lp-opinions", "phrase": "form opinions about"}],
            },
        ]

        reconciled = worker.reconcile_model_segment_ids(requested, model_segments)

        self.assertEqual([item["id"] for item in reconciled], ["seg_lp_0019", "seg_lp_0020"])
        self.assertEqual([item["id"] for item in model_segments], ["seg_lp_0001", "seg_lp_0001"])

    def test_positional_id_repair_requires_semantic_alignment(self):
        requested = [
            {"id": "seg_a", "text": "Use common sense here.", "answer_core": "common sense"},
            {"id": "seg_b", "text": "This evidence was passed down.", "answer_core": "passed down"},
        ]
        model_segments = [
            {"id": "renumbered_1", "cards": [{"phrase": "common sense"}]},
            {"id": "renumbered_1", "cards": [{"phrase": "invented mismatch"}]},
        ]

        reconciled = worker.reconcile_model_segment_ids(requested, model_segments)

        self.assertEqual(reconciled[0]["id"], "seg_a")
        self.assertEqual(reconciled[1]["id"], "renumbered_1")

    def test_card_prompt_requires_exact_input_ids(self):
        segment = {
            "id": "seg_lp_0042",
            "source_time": "00:00:01 - 00:00:02",
            "text": "Use common sense here.",
            "phrase": "common sense",
            "answer_core": "common sense",
            "candidate_kind": "expression",
            "recommendation": "keep",
            "learning_points": [{"id": "lp-common-sense", "answer_core": "common sense"}],
        }

        prompt = worker.build_immersive_v11_prompt(
            {"language": "en", "level": "B1", "card_types": ["phrase"]},
            [segment],
        )

        self.assertIn("逐字复制对应输入 segment.id", prompt)
        self.assertIn("COPY_EXACT_INPUT_SEGMENT_ID", prompt)
        self.assertIn("seg_lp_0042", prompt)
    def test_vertex_thinking_final_card_batch_size_is_not_clamped_to_three(self):
        api = {"provider": "gemini-vertex", "model": "gemini-3.1-pro-preview"}
        self.assertEqual(worker.final_card_batch_size(api, 10), 8)
        self.assertEqual(worker.final_card_generation_concurrency(api, 4), 3)

    def test_vertex_thinking_budget_exhaustion_is_retryable(self):
        details = worker._legacy_worker.classify_service_error(
            RuntimeError("Gemini Vertex 没有返回正文：输出预算被 thinking 消耗完，请提高 maxOutputTokens。"),
            kind="model",
        )

        self.assertEqual(details["error_code"], worker._legacy_worker.worker_errors.MODEL_TIMEOUT)
        self.assertTrue(details["retryable"])

    def test_learning_point_inventory_exposes_generated_candidates_duplicates_and_blocks(self):
        segment = {
            "id": "seg_0001",
            "source_segment_id": "src_1",
            "source_time": "00:00:01 - 00:00:03",
            "start": 1.0,
            "end": 3.0,
            "text": "I'm gonna run the register.",
            "phrase": "run the register",
            "exact_span": "run the register",
            "answer_core": "run the register",
            "candidate_kind": "expression",
            "phrase_type": "collocation",
            "phrase_value_score": 4,
            "phrase_decision_reason": "服务业场景搭配值得学。",
            "cards": [
                {
                    "id": "card_1",
                    "type": "phrase",
                    "phrase": "run the register",
                    "answer_core": "run the register",
                    "exact_span": "run the register",
                    "candidate_kind": "expression",
                    "phrase_type": "collocation",
                    "learning_target": "训练 run the register 这个搭配。",
                    "quality": {"status": "recommended", "score": 88, "issues": []},
                }
            ],
        }
        skipped = [
            {
                **segment,
                "id": "seg_dup",
                "phrase": "run the register",
                "answer_core": "run the register",
                "phrase_review_status": "duplicate",
                "phrase_reject_reason": "同一句已有训练动作相近的学习点，已合并为重复候选。",
                "cards": [],
            },
            {
                **segment,
                "id": "seg_candidate",
                "phrase": "register",
                "answer_core": "register",
                "candidate_kind": "contextual_vocab",
                "phrase_review_status": "reject",
                "phrase_reject_reason": "片段预算已满，暂未生成完整卡。",
                "cards": [],
            },
            {
                **segment,
                "id": "seg_block",
                "phrase": "中文解释",
                "answer_core": "中文解释",
                "phrase_review_status": "reject",
                "phrase_reject_reason": "answer_core 包含中文解释。",
                "cards": [],
            },
        ]

        inventory = worker.build_learning_point_inventory([segment], skipped)
        statuses = {item["status"] for item in inventory}

        self.assertIn("card_generated", statuses)
        self.assertIn("hidden_duplicate", statuses)
        self.assertIn("candidate_only", statuses)
        self.assertIn("hard_blocked", statuses)
        self.assertEqual(worker.learning_point_inventory_stats(inventory)["candidate_only_learning_point_count"], 1)

    def test_catch_all_keeps_four_distinct_learning_actions_per_source(self):
        source_id = "src_same_sentence"
        base = {
            "source_segment_id": source_id,
            "start": 0.0,
            "end": 3.0,
            "text": "I'm gonna run the register, but I don't want to hold that against you.",
            "score": 4.0,
            "phrase_value_score": 4,
        }
        segments = [
            {
                **base,
                "id": "seg_expr",
                "phrase": "run the register",
                "normalized_answer": "run the register",
                "candidate_kind": "expression",
                "phrase_card_focus": "训练服务业搭配。",
            },
            {
                **base,
                "id": "seg_vocab",
                "phrase": "register",
                "normalized_answer": "register",
                "candidate_kind": "contextual_vocab",
                "phrase_card_focus": "训练 register 的语境义。",
            },
            {
                **base,
                "id": "seg_listen",
                "phrase": "I'm gonna",
                "normalized_answer": "I'm gonna",
                "candidate_kind": "listening_feature",
                "phrase_card_focus": "训练 gonna 弱读听辨。",
            },
            {
                **base,
                "id": "seg_prag",
                "phrase": "hold that against you",
                "normalized_answer": "hold that against you",
                "candidate_kind": "pragmatic_risk",
                "phrase_card_focus": "训练责怪语气边界。",
            },
            {
                **base,
                "id": "seg_extra",
                "phrase": "don't want to",
                "normalized_answer": "don't want to",
                "candidate_kind": "grammar_pattern",
                "phrase_card_focus": "训练 want to 结构。",
                "phrase_value_score": 3,
            },
        ]

        kept, rejected = worker.enforce_max_learning_points_per_source(
            segments,
            worker.max_learning_points_per_source({"selection_strategy": "catch_all"}),
        )

        self.assertEqual(len(kept), 4)
        self.assertEqual({item["candidate_kind"] for item in kept}, {"expression", "contextual_vocab", "listening_feature", "pragmatic_risk"})
        self.assertEqual([item["id"] for item in rejected], ["seg_extra"])

    def test_source_expansion_adds_valid_points_and_rejects_invalid_spans(self):
        source_id = "src_expansion"
        segment = {
            "id": "seg_0001",
            "source_segment_id": source_id,
            "start": 0.0,
            "end": 2.5,
            "source_time": "00:00:00.000 - 00:00:02.500",
            "text": "I'm gonna run the register.",
            "duration": 2.5,
            "phrase": "run the register",
            "exact_span": "run the register",
            "normalized_answer": "run the register",
            "answer_core": "run the register",
            "candidate_kind": "expression",
            "phrase_type": "collocation",
            "content_kind": "phrase",
            "phrase_card_focus": "训练搭配。",
            "score": 4.2,
            "recommendation": 4,
        }
        original_call = worker._legacy_worker.call_source_learning_point_expansion

        def fake_expansion(_project, _groups):
            return {
                source_id: [
                    {
                        "candidate_kind": "contextual_vocab",
                        "phrase_type": "vocabulary_usage",
                        "exact_span": "register",
                        "answer_core": "register = 收银机 /ˈredʒɪstər/",
                        "normalized_answer": "register",
                        "card_focus": "训练 register 在服务业语境里的意思。",
                        "value_score": 4,
                    },
                    {
                        "candidate_kind": "expression",
                        "phrase_type": "spoken_phrase",
                        "exact_span": "not in sentence",
                        "answer_core": "not in sentence",
                        "value_score": 4,
                    },
                ]
            }, None

        worker._legacy_worker.call_source_learning_point_expansion = fake_expansion
        try:
            expanded, rejected, warning = worker.expand_learning_points_by_source(
                {
                    "selection_strategy": "catch_all",
                    "language": "en",
                    "language_focus": ["phrases", "vocabulary", "listening"],
                },
                [segment],
            )
        finally:
            worker._legacy_worker.call_source_learning_point_expansion = original_call

        self.assertIsNone(warning)
        self.assertEqual(len(expanded), 2)
        self.assertTrue(any(item.get("candidate_source") == "source_expansion" for item in expanded))
        repaired = next(item for item in expanded if item.get("candidate_source") == "source_expansion")
        self.assertEqual(repaired["answer_core"], "register")
        self.assertEqual(len(rejected), 1)
        self.assertIn("exact_span 不在原句", rejected[0]["phrase_reject_reason"])

    def test_learning_point_contract_adds_offsets_action_key_source_and_repair_history(self):
        ok, reason, point = worker.sanitize_learning_point_contract(
            {
                "candidate_kind": "contextual_vocab",
                "phrase_type": "vocabulary_usage",
                "exact_span": "register",
                "answer_core": "register = 收银机 /ˈredʒɪstər/",
                "normalized_answer": "register",
                "card_focus": "训练 register 在服务业语境里的意思。",
                "value_score": 4,
                "candidate_source": "source_expansion",
            },
            "I'm gonna run the register.",
            language="en",
        )

        self.assertTrue(ok, reason)
        self.assertEqual(point["answer_core"], "register")
        self.assertEqual(point["exact_span_start"], 18)
        self.assertEqual(point["exact_span_end"], 26)
        self.assertEqual(point["learning_action"], "训练 register 在服务业语境里的意思。")
        self.assertIn("contextual_vocab::register", point["learning_action_key"])
        self.assertEqual(point["source"], "repaired")
        self.assertEqual(point["confidence"], "high")
        self.assertEqual(point["validation_status"], "repaired")
        self.assertTrue(point["repair_history"])

    def test_learning_point_contract_accepts_structured_repair_history(self):
        ok, reason, point = worker.sanitize_learning_point_contract(
            {
                "candidate_kind": "contextual_vocab",
                "phrase_type": "vocabulary_usage",
                "exact_span": "register",
                "answer_core": "register = 收银机 /ˈredʒɪstər/",
                "normalized_answer": "register",
                "card_focus": "训练 register 在服务业语境里的意思。",
                "repair_history": [
                    {
                        "field": "answer_core",
                        "action": "trim_explanation",
                        "reason": "answer_core 含解释，已回退为目标词。",
                    }
                ],
            },
            "I'm gonna run the register.",
            language="en",
        )

        self.assertTrue(ok, reason)
        self.assertEqual(point["validation_status"], "repaired")
        self.assertTrue(point["repair_history"])
        self.assertTrue(all(isinstance(entry, str) for entry in point["repair_history"]))
        self.assertIn("answer_core 含解释，已回退为目标词。", point["repair_history"])

    def test_source_expansion_auto_caps_requested_source_groups(self):
        segments = []
        for index in range(1, 9):
            source_id = f"src_{index:04d}"
            segments.append(
                {
                    "id": f"seg_{index:04d}",
                    "source_segment_id": source_id,
                    "start": float(index),
                    "end": float(index) + 2.0,
                    "source_time": "00:00:00.000 - 00:00:02.000",
                    "text": f"I'm gonna run the register number {index}.",
                    "phrase": "run the register",
                    "exact_span": "run the register",
                    "normalized_answer": "run the register",
                    "answer_core": "run the register",
                    "candidate_kind": "expression",
                    "phrase_type": "collocation",
                    "content_kind": "phrase",
                    "score": 4.0 + index / 100,
                    "recommendation": 4,
                }
            )
        calls = {}
        original_call = worker._legacy_worker.call_source_learning_point_expansion

        def fake_expansion(_project, groups):
            calls["groups"] = groups
            return {}, None

        worker._legacy_worker.call_source_learning_point_expansion = fake_expansion
        project = {
            "selection_strategy": "catch_all",
            "source_expansion_mode": "auto",
            "max_source_expansion_groups": 3,
            "language": "en",
        }
        try:
            expanded, rejected, warning = worker.expand_learning_points_by_source(project, segments)
        finally:
            worker._legacy_worker.call_source_learning_point_expansion = original_call

        self.assertEqual(expanded, segments)
        self.assertEqual(rejected, [])
        self.assertIsNone(warning)
        self.assertEqual(len(calls["groups"]), 3)
        self.assertEqual(project["_source_expansion_stats"]["eligible_source_groups"], 8)
        self.assertEqual(project["_source_expansion_stats"]["requested_source_groups"], 3)

    def test_default_catch_all_selection_defaults_to_recommended_only(self):
        segments = [
            {
                "id": "seg_0001",
                "start": 0,
                "end": 2,
                "text": "It turns out this works.",
                "source_time": "00:00:00.000 - 00:00:02.000",
                "cards": [
                    {"id": "c1", "quality": {"status": "recommended", "score": 90}, "enabled": False},
                    {"id": "c2", "quality": {"status": "needs_review", "score": 62}, "enabled": False},
                    {"id": "c3", "quality": {"status": "reject", "score": 20}, "enabled": True},
                ],
            }
        ]

        selected = worker.apply_default_generated_card_selection(segments, {"selection_strategy": "catch_all"})

        self.assertEqual([card["enabled"] for card in selected[0]["cards"]], [True, False, False])

    def test_pronunciation_fields_do_not_affect_quality_score(self):
        segment = {
            "id": "seg_0001",
            "text": "You won't even taste the difference.",
            "phrase": "taste the difference",
            "candidate_kind": "expression",
            "phrase_type": "spoken_phrase",
            "source_time": "00:00:00.000 - 00:00:03.000",
        }
        card = {
            "id": "card_1",
            "type": "phrase",
            "english": segment["text"],
            "phrase": "taste the difference",
            "answer_core": "taste the difference",
            "definition": "notice a difference in flavor or quality.",
            "chinese": "尝出区别",
            "chinese_feel": "你根本尝不出区别。",
            "teacher_note": "自然口语表达。",
            "cloze": "You won't even ____.",
            "content_kind": "phrase",
            "candidate_kind": "expression",
        }
        with_pronunciation = {
            **card,
            "phonetic_ipa": "/teɪst ðə ˈdɪfrəns/",
            "spoken_ipa": "/teɪs ðə ˈdɪfrəns/",
            "source_spoken_ipa": "you WON't even tas(t) the difference",
            "pronunciation_note": "字幕推测口语读法。",
        }

        plain_quality = worker.assess_card_quality(card, segment, "ai", "B1")
        pronounced_quality = worker.assess_card_quality(with_pronunciation, segment, "ai", "B1")

        self.assertEqual(plain_quality["score"], pronounced_quality["score"])
        self.assertEqual(plain_quality["status"], pronounced_quality["status"])

    def test_min_review_promotion_does_not_revive_ai_rejected_candidates(self):
        rejected_id = "seg_0001"
        original_segments = [
            {
                "id": rejected_id,
                "start": 0.0,
                "end": 2.0,
                "text": "I'm gonna run the register.",
                "phrase": "run the register",
                "candidate_kind": "expression",
                "score": 5,
            }
        ]
        skipped = [
            worker.skipped_review_segment(
                original_segments[0],
                "reject",
                "AI 评审认为 answer_core 不合格。",
                5,
            )
        ]

        kept, updated_skipped = worker.ensure_min_review_candidates(
            original_segments,
            [],
            skipped,
            {"level": "B1", "max_segments": 20},
            {rejected_id},
        )

        self.assertEqual(kept, [])
        self.assertEqual(updated_skipped, skipped)

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

    def test_mimo_review_over_strict_result_does_not_revive_rejected_candidates(self):
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
        self.assertEqual(len(kept), 1)
        self.assertEqual(len(skipped), len(segments) - 1)
        self.assertEqual(kept[0]["phrase_review_status"], "recommended")
        self.assertTrue(all(item["phrase_review_status"] == "reject" for item in skipped))
        self.assertNotIn("key expression", [item["phrase"] for item in kept])

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

    def test_merge_ai_cards_maps_learning_action_fields_to_legacy_fields(self):
        segments = [
            {
                "id": "seg_0001",
                "text": "Honestly, it's such a nice Monday morning.",
                "phrase": "such a nice",
                "source_time": "00:00:01.000 - 00:00:04.000",
                "phrase_value_score": 5,
                "phrase_review_status": "recommended",
            }
        ]
        ai_payload = {
            "segments": [
                {
                    "id": "seg_0001",
                    "cards": [
                        {
                            "type": "phrase",
                            "phrase": "such a nice",
                            "chinese": "Honestly, it's such a nice Monday morning.",
                            "definition": "This phrase is useful in daily English.",
                            "collocations": "such a nice + natural object",
                            "context": "本地待审字段。",
                            "example": "It was such a nice evening.",
                            "chinese_feel": "",
                            "why": "",
                            "difficulty": "B1 日常交流",
                            "teacher_note": "很常见。",
                            "cloze": "Honestly, it's ____ Monday morning.",
                            "learning_target": "训练 such a nice + 名词表达自然赞叹。",
                            "why_it_matters": "比 very nice 更像真实口语。",
                            "how_to_use_it": "下次夸天气、地方或体验时，用 such a nice + 名词。",
                            "natural_chinese": "说真的，这是一个特别舒服的周一早晨。",
                            "replacement_examples": "such a nice day / such a nice place",
                        }
                    ],
                }
            ]
        }

        merged, _ = worker.merge_ai_cards(segments, ai_payload, ["phrase"], "B1")
        card = merged[0]["cards"][0]

        self.assertEqual(card["chinese"], "说真的，这是一个特别舒服的周一早晨。")
        self.assertEqual(card["learning_goal"], "训练 such a nice + 名词表达自然赞叹。")
        self.assertEqual(card["why"], "比 very nice 更像真实口语。")
        self.assertEqual(card["context"], "下次夸天气、地方或体验时，用 such a nice + 名词。")
        self.assertEqual(card["collocations"], "such a nice day / such a nice place")
        self.assertEqual(card["teacher_note"], "训练 such a nice + 名词表达自然赞叹。")
        self.assertEqual(card["definition"], "训练 such a nice + 名词表达自然赞叹。")

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

    def test_quality_rejects_truncated_source_evidence_and_blocks_export(self):
        truncated = (
            "And the proverb, “Don’t judge a book by its cover” advises people "
            "not to form opinions about people based"
        )
        card = {
            "type": "phrase",
            "english": truncated,
            "phrase": "form opinions about",
            "answer_core": "form opinions about",
            "candidate_kind": "expression",
            "content_kind": "phrase",
            "chinese": "对……形成看法。",
            "definition": "form opinions about 表示对某人或某事形成看法。",
            "collocations": "form opinions about a topic / form an opinion about the issue",
            "context": "用于讨论观点如何形成。",
            "example": "Try not to form opinions about people too quickly.",
            "teacher_note": "form 强调看法逐渐形成的过程。",
            "learning_goal": "训练 form opinions about 的自然搭配。",
            "difficulty": "B1 日常交流",
            "cloze": truncated.replace("form opinions about", "____", 1),
        }

        quality = worker.assess_card_quality(card, {"text": truncated}, "ai", "B1")
        card["quality"] = quality

        self.assertEqual(quality["status"], "reject")
        self.assertIn("原句疑似截断", quality["issues"])
        self.assertTrue(worker.ends_like_fragment(truncated))
        self.assertTrue(worker.card_has_export_blocking_content(card))

    def test_source_tail_gate_keeps_valid_spoken_ellipsis_and_stranded_prepositions(self):
        complete_sources = [
            "That’s what I was talking about.",
            "Who are you with?",
            "I don’t want to.",
            "The report is based on evidence.",
            "The decision is evidence based.",
        ]

        for source in complete_sources:
            self.assertFalse(worker.ends_like_fragment(source), source)

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
        self.assertIn("释义太泛", quality["issues"])

    def test_contextual_vocab_allows_one_word_answer_but_rejects_explanatory_answer_core(self):
        good_card = {
            "type": "phrase",
            "english": "I'm gonna run the register.",
            "phrase": "register",
            "answer_core": "register",
            "phrase_type": "vocabulary_usage",
            "content_kind": "vocabulary",
            "candidate_kind": "contextual_vocab",
            "chinese": "收银机 / 收银台",
            "definition": "register 在这句里指店里的收银机，不是注册。",
            "collocations": "run the register / work the register",
            "context": "服务业工作分工时使用。",
            "example": "Can you watch the register for a minute?",
            "teacher_note": "看到 run the register 时，先理解成负责看收银台。",
            "learning_goal": "训练 register 的服务业语境义。",
        }
        bad_card = {**good_card, "answer_core": "register = 收银机"}

        good_quality = worker.assess_card_quality(good_card, {"text": good_card["english"]}, "ai", "C1")
        bad_quality = worker.assess_card_quality(bad_card, {"text": bad_card["english"]}, "ai", "C1")

        self.assertNotIn("目标表达过短", good_quality["issues"])
        self.assertIn("核心答案包含解释而不是英文答案", bad_quality["issues"])

    def test_quality_rejects_incomplete_answer_core_fragments(self):
        cases = [
            {
                "type": "cloze",
                "english": "I do not like it when you don't talk to me.",
                "phrase": "it when",
                "answer_core": "it when",
                "candidate_kind": "grammar_pattern",
                "content_kind": "grammar",
                "cloze": "I do not like ____ you don't talk to me.",
            },
            {
                "type": "phrase",
                "english": "You will not believe who's cleaning Chad's car.",
                "phrase": "You will not believe who's",
                "answer_core": "You will not believe who's",
                "candidate_kind": "grammar_pattern",
                "content_kind": "grammar",
                "cloze": "____ cleaning Chad's car.",
            },
            {
                "type": "phrase",
                "english": "Is there something wrong with your table?",
                "phrase": "Is there something wrong with",
                "answer_core": "Is there something wrong with",
                "candidate_kind": "grammar_pattern",
                "content_kind": "grammar",
                "cloze": "____ your table?",
            },
        ]

        for card in cases:
            card.update(
                {
                    "chinese": "这是一条测试中文释义。",
                    "definition": "测试用：确保半截答案不会被推荐。",
                    "collocations": "use the full pattern with a complete slot",
                    "context": "用于检测卡片答案是否截断在功能词上。",
                    "example": "Please finish the sentence with a complete object.",
                    "teacher_note": "如果答案停在功能词上，学习者无法直接复用。",
                    "learning_goal": "拦截半截学习点。",
                    "difficulty": "B1 日常交流",
                }
            )
            quality = worker.assess_card_quality(card, {"text": card["english"]}, "ai", "B1")

            self.assertEqual(quality["status"], "reject")
            self.assertIn("核心答案像半截词串", quality["issues"])

    def test_quality_keeps_transferable_sentence_frames_ending_in_function_words(self):
        cases = [
            ("But I prefer to see it as the study of change.", "prefer to see it as", "grammar_pattern"),
            ("I was thinking of driving up to Los Alamos.", "was thinking of", "grammar_pattern"),
            ("So what tells you it's a meth lab?", "what tells you", "grammar_pattern"),
            ("Yeah well we'll see about that.", "we'll see about that", "expression"),
            (
                "Red Phosphorus in the presence of moisture yields Phosphorus Hydride.",
                "in the presence of",
                "expression",
            ),
            ("I seen one of those bounce off a windshield one time.", "I seen", "grammar_pattern"),
        ]

        for english, answer, candidate_kind in cases:
            card = {
                "type": "phrase",
                "english": english,
                "phrase": answer,
                "answer_core": answer,
                "candidate_kind": candidate_kind,
                "content_kind": "grammar" if candidate_kind == "grammar_pattern" else "phrase",
                "chinese": "这是一条测试中文释义。",
                "definition": f"测试用：{answer} 是可迁移句型或表达。",
                "collocations": f"{answer} + natural continuation",
                "context": "用于检测句型框架不会被误判为半截答案。",
                "example": "I would use this pattern in a different sentence.",
                "teacher_note": "这是可复用框架，答案本身可以停在功能词上。",
                "learning_goal": "保留可迁移句型框架。",
                "difficulty": "B1 日常交流",
                "cloze": english.replace(answer, "____", 1),
            }

            quality = worker.assess_card_quality(card, {"text": english}, "ai", "B1")

            self.assertNotIn("核心答案像半截词串", quality["issues"])

    def test_quality_downgrades_truncated_listening_answers(self):
        card = {
            "type": "listening",
            "english": "What'd you do to them?",
            "phrase": "What'd you",
            "answer_core": "What'd you",
            "candidate_kind": "listening_feature",
            "content_kind": "listening",
            "chinese": "你对他们做了什么？",
            "context": "听辨整句里的 what'd you do。",
            "teacher_note": "只截到 What'd you 会丢掉真正的动作信息。",
            "learning_goal": "听辨完整问句。",
            "difficulty": "B1 日常交流",
        }

        quality = worker.assess_card_quality(card, {"text": card["english"]}, "ai", "B1")

        self.assertNotEqual(quality["status"], "recommended")
        self.assertIn("听力答案像截断片段", quality["issues"])

    def test_quality_keeps_complete_short_phrases(self):
        card = {
            "type": "phrase",
            "english": "They're going out in style.",
            "phrase": "in style",
            "answer_core": "in style",
            "candidate_kind": "expression",
            "content_kind": "phrase",
            "chinese": "很体面、很有派头地结束或出场。",
            "definition": "in style 表示做某事很体面、有派头。",
            "collocations": "go out in style / celebrate in style",
            "context": "用于描述收尾、庆祝或出场很漂亮。",
            "example": "We finished the season in style.",
            "teacher_note": "in style 是完整短语，不是半截介词短语。",
            "learning_goal": "训练 in style 的整体口语含义。",
            "difficulty": "B1 日常交流",
            "cloze": "They're going out ____.",
        }

        quality = worker.assess_card_quality(card, {"text": card["english"]}, "ai", "B1")

        self.assertEqual(quality["status"], "recommended")
        self.assertNotIn("核心答案像半截词串", quality["issues"])

    def test_quality_treats_context_shape_issues_as_warnings_for_good_phrases(self):
        cases = [
            (
                "But we're not gonna hold that against you.",
                "hold that against you",
                "The teacher didn't hold my late work against me.",
            ),
            (
                "When we can put this big a dent in the local drug trade.",
                "put a dent in",
                "This expense will put a dent in our budget.",
            ),
        ]

        for english, phrase, example in cases:
            card = {
                "type": "phrase",
                "english": english,
                "phrase": phrase,
                "answer_core": phrase,
                "candidate_kind": "expression",
                "content_kind": "phrase",
                "chinese": "不要因为这件事一直怪你。",
                "definition": f"{phrase} 表示把某件事记在某人账上、因此责怪对方。",
                "collocations": f"{phrase} / don't hold one mistake against me",
                "context": "用于表达虽然发生了问题，但不会因此长期责怪某人。",
                "example": example,
                "teacher_note": "重点记 hold + something + against + someone 的责怪结构。",
                "learning_goal": f"训练 {phrase} 的自然用法。",
                "difficulty": "B1 日常交流",
                "cloze": english.replace(phrase, "____", 1),
            }

            quality = worker.assess_card_quality(card, {"text": english}, "ai", "B1")

            self.assertEqual(quality["status"], "recommended")

    def test_quality_downgrades_generic_teacher_note_and_definition(self):
        card = {
            "type": "phrase",
            "english": "Honestly, it's such a nice Monday morning.",
            "phrase": "such a nice",
            "chinese": "说真的，这是一个特别舒服的周一早晨。",
            "definition": "This phrase is useful in daily English.",
            "collocations": "such a nice day / such a nice place",
            "context": "用来真诚地夸一个日子、地方或体验。",
            "example": "It was such a nice evening.",
            "chinese_feel": "中文里像“真是个很舒服的...”。",
            "why": "可迁移到天气、地点、体验和人物印象。",
            "teacher_note": "很常见。",
            "difficulty": "B1 日常交流",
            "cloze": "Honestly, it's ____ Monday morning.",
            "learning_goal": "训练 such a nice + 名词表达自然赞叹。",
        }
        quality = worker.assess_card_quality(card, {"text": card["english"]}, "ai", "B1")

        self.assertNotEqual(quality["status"], "recommended")
        self.assertIn("释义太泛", quality["issues"])
        self.assertIn("老师提示缺少具体用法", quality["issues"])

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
        self.assertIn("每个 learning_point 最多生成 1 张统一学习卡", prompt)
        self.assertNotIn("cards 必须包含全部需要卡型", prompt)

    def test_prompt_requests_learning_action_fields_and_examples(self):
        prompt = worker.build_prompt(
            {"card_types": ["phrase"], "language": "English", "level": "B1", "language_focus": ["grammar"]},
            [
                {
                    "id": "seg_0001",
                    "source_time": "00:00:01.000 - 00:00:04.000",
                    "text": "Honestly, it's such a nice Monday morning.",
                    "phrase": "such a nice",
                    "recommendation": 5,
                    "phrase_value_score": 5,
                    "phrase_review_status": "recommended",
                    "phrase_card_focus": "训练 such a nice + 名词表达自然赞叹。",
                }
            ],
        )

        self.assertIn("语言学习卡片编辑老师", prompt)
        self.assertIn("pronunciation_meta", prompt)
        self.assertIn("learning_target", prompt)
        self.assertIn("why_it_matters", prompt)
        self.assertIn("how_to_use_it", prompt)
        self.assertIn("replacement_examples", prompt)
        self.assertIn("语法框架", prompt)
        self.assertIn("请只围绕这些重点判断和制卡", prompt)
        self.assertIn("such a nice Monday morning", prompt)
        self.assertIn("talk about", prompt)

    def test_card_planner_defaults_to_one_main_card(self):
        segment = {
            "id": "seg_0001",
            "text": "By the way, how long will it take?",
            "phrase": "by the way",
        }
        cards = worker.fallback_cards(segment, ["listening", "phrase", "cloze"], "B1")

        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["type"], "phrase")
        self.assertEqual(cards[0]["type_label"], "学习卡")
        self.assertEqual(cards[0]["card_role"], "primary")

    def test_card_planner_does_not_make_cloze_just_because_guide_exists(self):
        segment = {
            "id": "seg_0001",
            "text": "Okay, Mike, you go first.",
            "phrase": "go first",
        }
        cards = worker.fallback_cards(segment, ["listening", "phrase", "cloze"], "B1")

        self.assertEqual([card["type"] for card in cards], ["phrase"])

    def test_fallback_listening_without_phrase_stays_reviewable(self):
        segment = {
            "id": "seg_0001",
            "text": "My name is Walter Hartwell White.",
            "phrase": "key expression",
        }
        cards = worker.fallback_cards(segment, ["listening", "phrase", "cloze"], "B1")

        self.assertEqual([card["type"] for card in cards], ["phrase"])
        self.assertEqual(cards[0]["quality"]["status"], "needs_review")
        self.assertFalse(cards[0]["enabled"])
        self.assertIn("预览草稿，需要人工确认", cards[0]["quality"]["issues"])
        self.assertNotIn("缺少明确目标表达", cards[0]["quality"]["issues"])
        self.assertIn("目标表达像整句而不是词伙", cards[0]["quality"]["issues"])
        self.assertIn("例句只是照抄原句", cards[0]["quality"]["issues"])

    def test_curated_fallback_phrase_is_recommended_and_enabled(self):
        segment = {
            "id": "seg_0001",
            "text": "Why don't you just hang out here for a second?",
            "phrase": "hang out",
        }
        cards = worker.fallback_cards(segment, ["listening", "phrase", "cloze"], "B1")

        phrase_card = next(card for card in cards if card["type"] == "phrase")

        self.assertEqual(phrase_card["quality"]["status"], "recommended")
        self.assertTrue(phrase_card["enabled"])
        self.assertIn("本地规则卡，需要人工确认", phrase_card["quality"]["issues"])
        self.assertNotIn("预览草稿，需要人工确认", phrase_card["quality"]["issues"])
        self.assertNotIn("字段像模板废话", phrase_card["quality"]["issues"])
        self.assertNotIn("预览草稿", phrase_card["difficulty_reason"])

    def test_local_generate_warning_counts_curated_recommendations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video_path = root / "clip.mkv"
            subtitle_path = root / "clip.srt"
            video_path.write_bytes(b"placeholder")
            subtitle_path.write_text(
                "\n".join(
                    [
                        "1",
                        "00:00:01,000 --> 00:00:03,000",
                        "Why don't you just hang out here for a second?",
                        "",
                        "2",
                        "00:00:04,000 --> 00:00:06,000",
                        "My name is Walter Hartwell White.",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            project = worker.handle_generate(
                {
                    "source_mode": "local",
                    "title": "local curated smoke",
                    "video_path": str(video_path),
                    "subtitle_path": str(subtitle_path),
                    "api_config": {"provider": "local", "model": "local-fallback", "api_key": ""},
                    "language": "English",
                    "level": "B1",
                    "collection_levels": ["A2", "B1", "B2"],
                    "card_types": ["listening", "phrase", "cloze"],
                    "max_segments": 3,
                    "content_toggles": {"slang": True, "daily": True},
                }
            )

        self.assertGreaterEqual(project["quality_funnel"]["recommended_cards"], 1)
        self.assertIn("预览卡", project["warning"])
        self.assertIn("正式抽取学习点和制卡请先配置并测试模型 API", project["warning"])

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

        self.assertEqual([card["type"] for card in merged[0]["cards"]], ["phrase"])
        self.assertTrue(all(card["enabled"] for card in merged[0]["cards"]))

    def test_english_subtitle_selection_prefers_original_tracks(self):
        self.assertEqual(worker.subtitle_language_args("English"), "en,en-orig,en-GB,en-US")

    def test_project_media_prefix_is_unique_per_source(self):
        from acg.anki_export import project_media_prefix

        first = worker.project_media_prefix({"title": "Deck", "source_url": "https://youtu.be/one", "created_at": 1})
        second = worker.project_media_prefix({"title": "Deck", "source_url": "https://youtu.be/two", "created_at": 2})
        third = worker.project_media_prefix({"title": "Deck", "source_url": "https://youtu.be/one", "created_at": 1}, 177)

        self.assertNotEqual(first, second)
        self.assertNotEqual(first, third)
        self.assertTrue(first.startswith("Deck_"))
        self.assertEqual(first, project_media_prefix({"title": "Deck", "source_url": "https://youtu.be/one", "created_at": 1}))

    def test_anki_export_naming_helpers_match_worker_boundary(self):
        from acg.anki_export import anki_deck_name, anki_deck_part, batch_export_deck_specs, safe_filename, stable_id

        self.assertEqual(worker.safe_filename("Bad / Deck: Name?"), safe_filename("Bad / Deck: Name?"))
        self.assertEqual(worker.anki_deck_part("Parent::Bad / Child", "Fallback"), anki_deck_part("Parent::Bad / Child", "Fallback"))
        self.assertEqual(worker.anki_deck_name("Parent::Bad / Child", "Fallback"), anki_deck_name("Parent::Bad / Child", "Fallback"))
        self.assertEqual(worker.stable_id("anki-card-model", 1000), stable_id("anki-card-model", 1000))

        project = {
            "title": "Batch / Root",
            "batch_items": [
                {"id": "a", "title": "Clip One"},
                {"id": "b", "deck_name": "Custom::Deck"},
                {"id": "c", "title": "Clip One"},
                {"id": "disabled", "title": "Skipped", "enabled": False},
            ],
        }
        self.assertEqual(worker.batch_export_deck_specs(project), batch_export_deck_specs(project))

    def _first_apkg_note_fields(self, apkg_path: str) -> dict[str, str]:
        import sqlite3
        import zipfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with zipfile.ZipFile(apkg_path) as apkg:
                apkg.extract("collection.anki2", root)
            connection = sqlite3.connect(root / "collection.anki2")
            try:
                models = json.loads(connection.execute("select models from col").fetchone()[0])
                mid, flds = connection.execute("select mid, flds from notes order by id limit 1").fetchone()
            finally:
                connection.close()
        names = [field["name"] for field in models[str(mid)]["flds"]]
        values = flds.split("\x1f")
        return {name: values[index] if index < len(values) else "" for index, name in enumerate(names)}

    def test_document_reading_export_does_not_put_full_source_evidence_in_usage_context(self):
        try:
            import genanki  # noqa: F401
        except ImportError:
            self.skipTest("genanki is required for export smoke")

        source_evidence = (
            "Chapter 1 Why English cards need source evidence "
            "A learner can recognize a phrase in a textbook and still fail to use it in conversation. "
            "Chapter 2 Boundaries prevent fake fluency If a learner writes I'm not in mood, the missing article matters."
        )
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            output_dir.mkdir()
            result = worker.handle_export(
                {
                    "project": {
                        "id": "doc-reading-context-regression",
                        "title": "EPUB 精读字段回归",
                        "source_mode": "document",
                        "document_study_mode": "language_reading",
                        "template_id": "immersive_v11",
                        "language": "en",
                        "level": "B1",
                        "segments": [
                            {
                                "id": "doc_0001",
                                "text": "这段资料里值得精读的表达是什么：in the mood",
                                "source_time": "文档精读点 1",
                                "cards": [
                                    {
                                        "id": "doc_0001_knowledge",
                                        "type": "knowledge",
                                        "enabled": True,
                                        "document_card_kind": "language_reading",
                                        "english": "I'm not in the mood.",
                                        "answer_core": "我没心情（做这件事）。",
                                        "phrase": "in the mood",
                                        "chinese": "我没心情（做这件事）。",
                                        "definition": "表示当前有做某事的意愿或心情。",
                                        "collocations": "be in the mood for sth / be in the mood to do sth",
                                        "context": "用于委婉拒绝或推迟某事。",
                                        "source_evidence": source_evidence,
                                        "example": "I'm not in the mood for pizza tonight.",
                                        "teacher_note": "不要漏掉 the；不说 in mood。",
                                        "quality": {"score": 82, "status": "recommended", "issues": []},
                                    }
                                ],
                            }
                        ],
                    },
                    "output_dir": str(output_dir),
                }
            )
            fields = self._first_apkg_note_fields(result["apkg_path"])

        self.assertIn("用于委婉拒绝或推迟某事", fields["Context"])
        self.assertNotIn("Chapter 1", fields["Context"])
        self.assertLessEqual(len(fields["Context"]), 80)

    def test_document_knowledge_export_uses_source_evidence_even_when_ciba_template_selected(self):
        try:
            import genanki  # noqa: F401
        except ImportError:
            self.skipTest("genanki is required for export smoke")

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            output_dir.mkdir()
            result = worker.handle_export(
                {
                    "project": {
                        "id": "doc-knowledge-evidence-regression",
                        "title": "词霸文档知识字段回归",
                        "source_mode": "document",
                        "document_study_mode": "knowledge",
                        "template_id": "ciba_tianxia_v1",
                        "language": "en",
                        "level": "B2",
                        "segments": [
                            {
                                "id": "doc_0001",
                                "text": "这段资料的核心知识点是什么：语境义优先",
                                "source_time": "文档知识点 1",
                                "cards": [
                                    {
                                        "id": "doc_0001_knowledge",
                                        "type": "knowledge",
                                        "enabled": True,
                                        "document_card_kind": "knowledge",
                                        "english": "run 在这句里为什么不是“跑”？",
                                        "answer_core": "run = 操作/负责",
                                        "phrase": "run the register",
                                        "chinese": "run 是操作、负责；register 是收银机。",
                                        "definition": "掌握 run the register 的地道搭配。",
                                        "context": "零售、餐饮等需要操作收银机的场景。",
                                        "source_evidence": "run 不是跑步，而是“操作、负责”，register 也不是注册，而是收银机。",
                                        "teacher_note": "不要翻译成跑去注册。",
                                        "quality": {"score": 86, "status": "recommended", "issues": []},
                                    }
                                ],
                            }
                        ],
                    },
                    "output_dir": str(output_dir),
                }
            )
            fields = self._first_apkg_note_fields(result["apkg_path"])

        self.assertIn("run 不是跑步", fields["Context"])
        self.assertNotEqual(fields["Context"], "零售、餐饮等需要操作收银机的场景。")

    def test_document_knowledge_audit_accepts_concept_answer_when_source_evidence_exists(self):
        audit = worker._legacy_worker.export_quality_audit(
            {
                "source_mode": "document",
                "document_study_mode": "knowledge",
                "template_id": "ciba_tianxia_v1",
                "language": "en",
                "level": "B2",
            },
            [
                {
                    "id": "doc_0003",
                    "text": "这段资料的核心知识点是什么：中文脑子最容易错的地方",
                    "document_excerpt": "中文母语者常把中文词逐字搬到英文里：负责收银会想成 do the register，看问题的方式不对会硬说 see it wrong。",
                    "source_time": "文档知识点 3",
                    "cards": [
                        {
                            "id": "doc_0003_knowledge",
                            "type": "knowledge",
                            "enabled": True,
                            "english": "中文母语者最容易犯的根本错误是什么？",
                            "answer_core": "中文脑子易错点",
                            "phrase": "中文脑子易错点",
                            "chinese": "把中文词逐字搬到英文里。",
                            "definition": "识别中文母语负迁移。",
                            "context": "输出英语时容易逐字直译。",
                            "source_evidence": "中文母语者常把中文词逐字搬到英文里：负责收银会想成 do the register，看问题的方式不对会硬说 see it wrong。",
                            "teacher_note": "不是每个中文概念都要逐字出现在英文原句里；看 source evidence 是否支撑即可。",
                            "quality": {"score": 86, "status": "recommended", "issues": []},
                        }
                    ],
                }
            ],
        )

        self.assertEqual(audit["answer_not_in_source"], 0)

    def test_export_quality_audit_reports_blocked_document_card_details(self):
        audit = worker._legacy_worker.export_quality_audit(
            {
                "source_mode": "document",
                "document_study_mode": "knowledge",
                "template_id": "immersive_v11",
                "language": "en",
                "level": "B2",
            },
            [
                {
                    "id": "doc_draft",
                    "text": "什么是语境义优先？",
                    "source_time": "文档知识点 1",
                    "cards": [
                        {
                            "id": "doc_draft_card",
                            "type": "knowledge",
                            "enabled": True,
                            "english": "什么是语境义优先？",
                            "answer_core": "语境义优先",
                            "phrase": "语境义优先",
                            "chinese": "本地文档草稿，需要人工确认。",
                            "definition": "内部提示：正式导出前需要人工确认。",
                            "teacher_note": "请重新生成。",
                            "quality": {"score": 65, "status": "needs_review", "issues": ["自动草稿卡"]},
                        }
                    ],
                }
            ],
        )

        self.assertGreater(audit["blocked_text_values"], 0)
        self.assertEqual(len(audit["blocked_cards"]), 1)
        blocked = audit["blocked_cards"][0]
        self.assertEqual(blocked["card_id"], "doc_draft_card")
        self.assertEqual(blocked["segment_id"], "doc_draft")
        self.assertIn("语境义优先", blocked["title"])
        self.assertIn("人工确认", blocked["matched_text"])
        self.assertIn("matched_fields", blocked)
        self.assertIn("重新生成", blocked["suggested_action"])

    def test_export_quality_audit_blocks_document_draft_text_in_planning_fields(self):
        audit = worker._legacy_worker.export_quality_audit(
            {
                "source_mode": "document",
                "document_study_mode": "knowledge",
                "template_id": "immersive_v11",
                "language": "en",
                "level": "B2",
            },
            [
                {
                    "id": "doc_draft",
                    "text": "什么是间隔重复？",
                    "source_time": "文档知识点 1",
                    "cards": [
                        {
                            "id": "doc_draft_card",
                            "type": "knowledge",
                            "enabled": True,
                            "english": "什么是间隔重复？",
                            "answer_core": "间隔重复",
                            "phrase": "间隔重复",
                            "chinese": "按间隔安排复习。",
                            "definition": "一种长期记忆策略。",
                            "teacher_note": "先回忆，再核对答案。",
                            "difficulty_reason": "本地文档草稿按当前水平和文本复杂度估计。",
                            "quality": {"score": 90, "status": "recommended", "issues": []},
                        }
                    ],
                }
            ],
        )

        self.assertGreater(audit["blocked_text_values"], 0)
        self.assertEqual(len(audit["blocked_cards"]), 1)
        blocked = audit["blocked_cards"][0]
        self.assertEqual(blocked["card_id"], "doc_draft_card")
        self.assertEqual(blocked["matched_field"], "DifficultyReason")
        self.assertIn("本地文档草稿", blocked["matched_text"])

    def test_export_quality_audit_does_not_block_generic_human_review_issue_only(self):
        audit = worker._legacy_worker.export_quality_audit(
            {
                "source_mode": "local",
                "template_id": "immersive_v11",
                "language": "en",
                "level": "B1",
            },
            [
                {
                    "id": "video_seg",
                    "text": "Dad, come check this out.",
                    "source_time": "00:00:00.000 - 00:00:02.000",
                    "cards": [
                        {
                            "id": "video_card",
                            "type": "phrase",
                            "enabled": True,
                            "english": "Dad, come check this out.",
                            "answer_core": "check this out",
                            "phrase": "check this out",
                            "chinese": "看看这个。",
                            "definition": "用来邀请别人注意某个东西。",
                            "context": "Dad, come check this out.",
                            "teacher_note": "适合口语场景。",
                            "quality": {"score": 80, "status": "recommended", "issues": ["本地规则卡，需要人工确认。"]},
                        }
                    ],
                }
            ],
        )

        self.assertEqual(audit["blocked_text_values"], 0)
        self.assertEqual(audit["blocked_cards"], [])

    def test_export_quality_gate_failure_includes_blocked_card_details(self):
        try:
            import genanki  # noqa: F401
        except ImportError:
            self.skipTest("genanki is required for export smoke")

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            output_dir.mkdir()
            stderr = io.StringIO()
            with self.assertRaises(SystemExit):
                with redirect_stderr(stderr):
                    worker.handle_export(
                        {
                            "project": {
                                "id": "doc-quality-gate-details",
                                "title": "文档坏卡导出诊断",
                                "source_mode": "document",
                                "document_study_mode": "knowledge",
                                "template_id": "immersive_v11",
                                "language": "en",
                                "level": "B2",
                                "segments": [
                                    {
                                        "id": "doc_draft",
                                        "text": "什么是语境义优先？",
                                        "source_time": "文档知识点 1",
                                        "cards": [
                                            {
                                                "id": "doc_draft_card",
                                                "type": "knowledge",
                                                "enabled": True,
                                                "english": "什么是语境义优先？",
                                                "answer_core": "语境义优先",
                                                "phrase": "语境义优先",
                                                "chinese": "本地文档草稿，需要人工确认。",
                                                "definition": "内部提示：正式导出前需要人工确认。",
                                                "context": "",
                                                "source_evidence": "文档说明语境义优先。",
                                                "teacher_note": "请重新生成。",
                                                "quality": {
                                                    "score": 65,
                                                    "status": "needs_review",
                                                    "issues": ["自动草稿卡"],
                                                },
                                            }
                                        ],
                                    }
                                ],
                            },
                            "output_dir": str(output_dir),
                        }
                    )

            error_line = next(line for line in stderr.getvalue().splitlines() if line.startswith("__ANKI_CARD_ERROR__"))
            payload = json.loads(error_line.replace("__ANKI_CARD_ERROR__", "", 1))
            self.assertEqual(payload["error_code"], "EXPORT_QUALITY_GATE_FAILED")
            self.assertEqual(payload["stage"], "quality_audit")
            self.assertEqual(payload["details"]["blocked_cards"][0]["card_id"], "doc_draft_card")
            self.assertIn("人工确认", payload["details"]["blocked_cards"][0]["matched_text"])

    def test_azw3_document_auto_converts_with_ebook_convert_when_available(self):
        import subprocess
        import zipfile
        from unittest.mock import patch

        readers = importlib.import_module("acg.documents.readers")
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "book.azw3"
            source.write_bytes(b"BOOKMOBI")

            def fake_run(command, **kwargs):
                self.assertEqual(command[0], "ebook-convert")
                self.assertEqual(Path(command[1]), source)
                output_epub = Path(command[2])
                with zipfile.ZipFile(output_epub, "w") as archive:
                    archive.writestr(
                        "chapter.xhtml",
                        "<html><body><p>run the register means operate the cash register.</p></body></html>",
                    )
                return subprocess.CompletedProcess(command, 0, stdout="converted", stderr="")

            with patch.object(readers.shutil, "which", return_value="ebook-convert"), patch.object(
                readers.subprocess, "run", side_effect=fake_run
            ):
                text = worker.read_document_source(str(source))

        self.assertIn("run the register", text)
        self.assertIn("operate the cash register", text)

    def test_azw3_document_error_is_actionable_without_converter(self):
        from unittest.mock import patch

        readers = importlib.import_module("acg.documents.readers")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "book.azw3"
            path.write_bytes(b"BOOKMOBI")
            stderr = io.StringIO()
            with patch.object(readers.shutil, "which", return_value=None):
                with self.assertRaises(SystemExit):
                    with redirect_stderr(stderr):
                        worker.read_document_source(str(path))
        message = stderr.getvalue()
        self.assertIn("AZW3", message)
        self.assertIn("EPUB", message)
        self.assertIn("Calibre", message)
        self.assertIn("ebook-convert", message)

    def test_ciba_knowledge_back_keeps_boundary_compact(self):
        card = {
            "chinese_learner_trap": "不要把 run 当成“跑”，register 当成“注册”。",
            "usage_boundary": "只在操作机器、系统或收银机这类语境里用。",
            "confusable_note": "不要写成 do the register。",
            "teacher_note": "复习时先看原句再判断动作。",
        }

        self.assertEqual(worker._legacy_worker.ciba_boundary_text(card), "不要把 run 当成“跑”，register 当成“注册”")
        self.assertNotIn("{{#Collocations}}<p>{{Collocations}}</p>{{/Collocations}}", worker.KNOWLEDGE_BACK_TEMPLATE)

    def test_document_knowledge_front_answer_prefers_short_concept_label(self):
        fields = worker._legacy_worker.card_front_fields(
            {
                "type": "knowledge",
                "document_card_kind": "knowledge",
                "english": "为什么在真实英语中，不能孤立地背单词的中文意思？",
                "phrase": "语境义优先",
                "chinese": "词的意义是在句子关系、场景动作和搭配中被激活的。例如 run the register 中 run 是操作/负责。",
                "definition": "单词意义由句子、场景和搭配决定。",
            }
        )

        self.assertEqual(fields["answer"], "语境义优先")
        self.assertLessEqual(len(fields["answer"]), 24)

    def test_ciba_language_action_joins_lines_as_sentences(self):
        text = worker._legacy_worker.ciba_language_action_text(
            {
                "learning_target": "掌握 run 在特定搭配中的语境义。",
                "how_to_use_it": "当你想表达“操作某个机器/负责某个岗位”时，检查是否能用 run 而不是机械翻译“负责”。",
                "definition": "操作或负责某项设备/岗位。",
            }
        )

        self.assertEqual(
            text,
            "掌握 run 在特定搭配中的语境义。当你想表达“操作某个机器/负责某个岗位”时，检查是否能用 run 而不是机械翻译“负责”",
        )
        self.assertNotIn("语境义 当你", text)

    def test_ciba_boundary_prefers_compact_boundary_field(self):
        card = {
            "boundary": "易错点：不要孤立地把 run 翻译成“跑”，也不要用 do 来搭配 register。",
            "teacher_note": "记住，动词的意义是由它后面的宾语决定的，不要脱离搭配背单词。；易错点：不要孤立地把 run 翻译成“跑”，也不要用 do 来搭配 register。",
        }

        self.assertEqual(
            worker._legacy_worker.ciba_boundary_text(card),
            "易错点：不要孤立地把 run 翻译成“跑”，也不要用 do 来搭配 register",
        )
        self.assertNotIn("；", worker._legacy_worker.ciba_boundary_text(card))

    def test_document_knowledge_export_removes_duplicate_transfer_and_direct_cloze_hint(self):
        try:
            import genanki  # noqa: F401
        except ImportError:
            self.skipTest("genanki is required for export smoke")

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            output_dir.mkdir()
            result = worker.handle_export(
                {
                    "project": {
                        "id": "doc-knowledge-dedupe-regression",
                        "title": "知识卡去重复回归",
                        "source_mode": "document",
                        "document_study_mode": "knowledge",
                        "template_id": "ciba_tianxia_v1",
                        "language": "en",
                        "level": "B2",
                        "segments": [
                            {
                                "id": "doc_0001",
                                "text": "这段资料的核心知识点是什么：run the register",
                                "source_time": "文档知识点 1",
                                "cards": [
                                    {
                                        "id": "doc_0001_knowledge",
                                        "type": "knowledge",
                                        "enabled": True,
                                        "document_card_kind": "knowledge",
                                        "english": "run the register 在真实语境里是什么意思？",
                                        "answer_core": "操作收银机",
                                        "phrase": "run the register",
                                        "chinese": "操作/负责收银机。",
                                        "definition": "听到 run the register 时，应反应为操作收银机，而不是跑。",
                                        "context": "零售或餐饮场景。",
                                        "source_evidence": "run 不是跑步，而是“操作、负责”，register 也不是注册，而是收银机。",
                                        "teacher_note": "不要把 run 固定理解为“跑”，也不要把 register 固定理解为“注册”。",
                                        "collocations": "run a business；run the register",
                                        "why": "不要把 run 固定理解为“跑”，也不要把 register 固定理解为“注册”。",
                                        "cloze": "Can you ___ the register for a minute?（负责操作收银机）",
                                        "quality": {"score": 88, "status": "recommended", "issues": []},
                                    }
                                ],
                            }
                        ],
                    },
                    "output_dir": str(output_dir),
                }
            )
            fields = self._first_apkg_note_fields(result["apkg_path"])

        self.assertEqual(fields["Why"], "")
        self.assertIn("___", fields["Cloze"])
        self.assertNotIn("负责操作收银机", fields["Cloze"])
        self.assertLessEqual(fields["Cloze"].count("___"), 1)

    def test_knowledge_back_hides_transfer_section_when_why_is_empty(self):
        self.assertIn('{{#Why}}<section class="card-section knowledge-transfer-check transfer-block">', worker.KNOWLEDGE_BACK_TEMPLATE)
        self.assertNotIn('<section class="card-section knowledge-transfer-check transfer-block">\n    <strong class="subtle">迁移检查</strong>\n    {{#Why}}', worker.KNOWLEDGE_BACK_TEMPLATE)

    def test_card_template_uses_responsive_canvas_and_fit_text(self):
        self.assertIn(".review-card", worker.CARD_CSS)
        self.assertIn("overflow-y: auto !important", worker.CARD_CSS)
        self.assertIn("height: auto", worker.CARD_CSS)
        self.assertIn("grid-template-columns: repeat(auto-fit, minmax(220px, 1fr))", worker.CARD_CSS)
        self.assertNotIn("calc(100vw - 18px)", worker.CARD_CSS)
        self.assertIn("width: min(900px, 100%)", worker.CARD_CSS)
        self.assertIn("overflow-wrap: anywhere", worker.CARD_CSS)
        self.assertIn("media-strip", worker.BACK_TEMPLATE)
        self.assertIn("audio-actions", worker.BACK_TEMPLATE)
        self.assertNotIn("data-fit", worker.BACK_TEMPLATE)
        self.assertNotIn("fitResponsiveText", worker.BACK_TEMPLATE)
        self.assertNotIn("fitAdaptiveCard", worker.BACK_TEMPLATE)
        self.assertNotIn("hasHiddenOverflow", worker.BACK_TEMPLATE)
        self.assertNotIn("audio-missing", worker.BACK_TEMPLATE)
        self.assertNotIn("AI 朗读未生成", worker.BACK_TEMPLATE)
        self.assertNotIn("scale.toFixed", worker.BACK_TEMPLATE)
        self.assertIn("核心答案", worker.BACK_TEMPLATE)
        self.assertIn("老师提醒", worker.BACK_TEMPLATE)
        self.assertIn("{{UnderstandLabel}}", worker.BACK_TEMPLATE)
        self.assertIn("{{UseLabel}}", worker.BACK_TEMPLATE)
        self.assertIn("再造一句", worker.BACK_TEMPLATE)
        self.assertIn("block-grid", worker.CARD_CSS)
        self.assertNotIn("@media (max-height: 980px)", worker.CARD_CSS)

    def test_audio_audit_includes_source_sentence_provenance(self):
        items = worker.build_audio_audit_items(
            [
                {
                    "card_id": "card-1",
                    "learning_point_id": "lp-1",
                    "segment_id": "seg-1",
                    "source_mode": "local",
                    "source_title": "The power of poetry",
                    "source_video_path": "E:\\ANKI\\materials\\poetry.mp4",
                    "source_video_fingerprint": "cff7c10a1bda8f7f",
                    "source_video_sha256": "cff7c10a1bda8f7f03c605a778c547ffc5374d91cd3c9c208f8f8e168c874935",
                    "source_subtitle_path": "E:\\ANKI\\materials\\poetry.srt",
                    "source_subtitle_fingerprint": "3b138e73805d4f50",
                    "source_subtitle_sha256": "3b138e73805d4f50c5925bca643f7dcb7b0aead07734e0eb791043848c346d35",
                    "source_subtitle_status": "loaded",
                    "source_time": "00:00:45.791 - 00:00:53.911",
                    "media_source_time": "00:00:45.671 - 00:00:54.091",
                    "source_cue_ids": [12, 13],
                    "source_cue_count": 2,
                    "source_cue_start": 45.791,
                    "source_cue_end": 53.911,
                    "source_cue_time": "00:00:45.791 - 00:00:53.911",
                    "source_cue_texts": [
                        "It's sort of like a mini English that works in your everyday",
                        "You're confident with it.",
                    ],
                    "source_merge_reason": "merged_until_sentence_boundary",
                    "source_sentence_quality_flags": ["possible_bad_join"],
                    "source_sentence_quality_status": "needs_review",
                    "sentence_tts_text": "It's sort of like a mini English that works in your everyday You're confident with it.",
                    "phrase_tts_text": "You're confident with",
                    "sentence_tts_audio": "sentence.wav",
                    "phrase_tts_audio": "phrase.wav",
                }
            ],
            {
                "sentence.wav": {"sha256": "sentence-sha", "tts_text_hash": "sentence-text"},
                "phrase.wav": {"sha256": "phrase-sha", "tts_text_hash": "phrase-text"},
            },
            deck_name="Video Deck",
            model_name="Anki Card Generator V12 - 沉浸复读 V11 · 快速复读",
            deck_kind="video_language",
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["source_mode"], "local")
        self.assertEqual(items[0]["source_title"], "The power of poetry")
        self.assertEqual(items[0]["source_video_fingerprint"], "cff7c10a1bda8f7f")
        self.assertEqual(
            items[0]["source_video_sha256"],
            "cff7c10a1bda8f7f03c605a778c547ffc5374d91cd3c9c208f8f8e168c874935",
        )
        self.assertEqual(items[0]["source_subtitle_fingerprint"], "3b138e73805d4f50")
        self.assertEqual(
            items[0]["source_subtitle_sha256"],
            "3b138e73805d4f50c5925bca643f7dcb7b0aead07734e0eb791043848c346d35",
        )
        self.assertEqual(items[0]["source_subtitle_status"], "loaded")
        self.assertEqual(items[0]["source_cue_ids"], [12, 13])
        self.assertEqual(items[0]["source_cue_start"], 45.791)
        self.assertEqual(items[0]["source_cue_end"], 53.911)
        self.assertEqual(items[0]["source_cue_texts"][1], "You're confident with it.")
        self.assertEqual(items[0]["source_sentence_quality_flags"], ["possible_bad_join"])
        self.assertEqual(items[0]["source_sentence_quality_status"], "needs_review")
        summary = worker.audio_audit_summary(items, deck_kind="video_language", expected_items=1)
        self.assertEqual(summary["source_sentence_quality"]["needs_review"], 1)
        self.assertEqual(summary["source_sentence_quality"]["clean"], 0)

    def test_audio_audit_module_preserves_text_hashes_and_failure_details(self):
        from acg.audio_audit import (
            audio_audit_failure_details,
            audio_audit_summary,
            build_audio_audit_items,
            media_text_hash,
        )

        items = build_audio_audit_items(
            [
                {
                    "card_id": "card-tts",
                    "learning_point_id": "lp-tts",
                    "segment_id": "seg-tts",
                    "source_time": "00:00:01.000 - 00:00:04.000",
                    "sentence_tts_text": "Tell you what, I'll let you off for a 10.",
                    "phrase_tts_text": "Tell you what",
                    "sentence_tts_audio": "sentence.mp3",
                    "phrase_tts_audio": "phrase.mp3",
                    "answer": "Tell you what",
                }
            ],
            {
                "sentence.mp3": {
                    "sha256": "sentence-sha",
                    "semantic_verification": "passed",
                    "text_hash": media_text_hash("Tell you what, I'll let you off for a 10."),
                },
                "phrase.mp3": {
                    "sha256": "phrase-sha",
                    "semantic_verification": "mismatch",
                    "text_hash": media_text_hash("Tell you what"),
                    "semantic_review_reasons": ["tts provider returned wrong phrase"],
                },
            },
            deck_name="Video Deck",
            model_name="Anki Card Generator V12 - 沉浸复读 V11",
            deck_kind="video_language",
        )

        self.assertEqual(items[0]["tts_text_hashes"]["sentence_tts"], media_text_hash("Tell you what, I'll let you off for a 10."))
        self.assertEqual(items[0]["tts_text_hashes"]["phrase_tts"], media_text_hash("Tell you what"))
        self.assertEqual(items[0]["semantic_review_reasons"], ["tts provider returned wrong phrase"])
        summary = audio_audit_summary(items, deck_kind="video_language", expected_items=1)
        self.assertEqual(summary["status"], "mismatch")
        details = audio_audit_failure_details(
            items,
            [
                {
                    "file": "phrase.mp3",
                    "role": "phrase_tts",
                    "tts_text": "Tell you what",
                    "semantic_verification": "mismatch",
                }
            ],
        )
        self.assertEqual(details["audio_failures"][0]["card_id"], "card-tts")
        self.assertEqual(details["audio_failures"][0]["expected_text"], "Tell you what")


if __name__ == "__main__":
    unittest.main()
