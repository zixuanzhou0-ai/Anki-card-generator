import base64
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
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
    def test_mimo_token_plan_key_uses_token_plan_base_url(self):
        base_url = worker.compatible_base_url(
            {
                "provider": "mimo",
                "api_key": "tp-test-token",
                "base_url": "https://api.xiaomimimo.com/v1",
            }
        )

        self.assertEqual(base_url, worker.MIMO_TOKEN_PLAN_SGP_BASE_URL)

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

    def test_ytdlp_node_runtime_enables_remote_ejs_components(self):
        original_which = worker.shutil.which
        try:
            worker.shutil.which = lambda name: "C:/node/node.exe" if name == "node" else None

            args = worker.yt_dlp_js_runtime_args()
        finally:
            worker.shutil.which = original_which

        self.assertEqual(args, ["--js-runtimes", "node", "--remote-components", "ejs:github"])

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
        self.assertEqual(len([card for card in merged[0]["cards"] if card["type"] == "phrase"]), 2)

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

    def test_export_keeps_text_cards_when_local_media_slicing_fails(self):
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
                    card["enabled"] = True

            original_synthesize_tts = worker._legacy_worker.synthesize_tts
            try:
                worker._legacy_worker.synthesize_tts = lambda *args, **kwargs: self.fail(
                    "TTS synthesis should not run when TTS is disabled"
                )
                result = worker.handle_export({"project": project, "output_dir": str(output_dir)})
            finally:
                worker._legacy_worker.synthesize_tts = original_synthesize_tts

            self.assertTrue(Path(result["apkg_path"]).exists())
            self.assertGreater(result["cards"], 0)
            self.assertEqual(result["media_summary"]["video_segments"], 0)
            self.assertEqual(result["media_summary"]["phrase_tts_files"], 0)
            self.assertTrue(any("视频/原声切片失败" in warning for warning in result["warnings"]))

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

            self.assertIn("沉浸复读 V12", model["name"])
            self.assertIn("v11-front-copy", template["qfmt"])
            self.assertIn("{{FrontPrompt}}", template["qfmt"])
            self.assertIn("慢读", template["qfmt"])
            self.assertIn("点画面开始复读", template["qfmt"])
            self.assertIn("复读循环中", template["qfmt"])
            self.assertIn("video.muted = false", template["qfmt"])
            self.assertIn("表达 / 词义", template["afmt"])
            self.assertIn("原句</div>", template["afmt"])
            self.assertIn("别误用", template["afmt"])
            self.assertNotIn("<audio controls", template["qfmt"] + template["afmt"])
            self.assertIn("CardLayout", field_names)
            self.assertIn("CardVisualRole", field_names)
            self.assertIn("FrontKicker", field_names)
            self.assertIn("SourceLabel", field_names)
            self.assertIn("PhoneticIpa", field_names)
            self.assertIn("SpokenIpa", field_names)
            self.assertIn("SourceSpokenIpa", field_names)
            self.assertIn("PronunciationNote", field_names)
            self.assertIn("PronunciationMeta", field_names)
            self.assertIn("SpokenPronunciationLabel", field_names)
            self.assertIn("StandardPronunciationHint", field_names)
            self.assertIn("标准读法", template["afmt"])
            self.assertIn("{{SpokenPronunciationLabel}}", template["afmt"])
            self.assertIn("{{^SourceSpokenIpa}}", template["afmt"])
            self.assertIn("原句听感</span><strong>未单独标注</strong>", template["afmt"])
            exported_fields = note_fields.split("\x1f")
            meta = json.loads(exported_fields[field_names.index("PronunciationMeta")])
            self.assertIn(meta["language_code"], {"en", "fr", "es", "ja", "ru"})
            self.assertIn("generation_basis", meta)

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

            def fake_synthesize_tts(project_arg, segment_arg, output_path, text_override=None):
                captured.append(text_override)
                Path(output_path).write_bytes(b"ID3")
                return True

            try:
                worker._legacy_worker.synthesize_tts = fake_synthesize_tts
                result = worker.handle_export({"project": project, "output_dir": str(output_dir)})
            finally:
                worker._legacy_worker.synthesize_tts = original_synthesize_tts

            self.assertTrue(Path(result["apkg_path"]).exists())
            self.assertEqual(captured[0], None)
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
        self.assertIn("中文理解为主", prompt)
        self.assertIn("深入掌握", prompt)
        self.assertIn("详细答案", prompt)
        self.assertIn("读书笔记老师", prompt)
        self.assertIn("不要照抄整段原文", prompt)
        self.assertIn('"knowledge_type":"concepts|arguments|terms|examples"', prompt)

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
        self.assertIn("tag:anki_card_generator_v11", find_query)
        self.assertNotIn("tag:anki_card_generator_v10", find_query)

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
        self.assertEqual(calls["body"]["contents"][0]["parts"][0]["text"], "This is a local video card.")

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
            if text == "Tell you what, I'll let you off for a 10.":
                raise RuntimeError("API HTTP 400: invalid argument")
            if text == "Tell you what, I'll let you off for a ten.":
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
            ["Tell you what, I'll let you off for a 10.", "Tell you what, I'll let you off for a ten."],
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
            if text == "in style":
                return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "in style"}]}}]}
            if text == "Read exactly this expression: in style.":
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
        self.assertEqual(calls["texts"], ["in style", "in style.", "Read exactly this expression: in style."])

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

    def test_segment_display_source_time_prefers_media_source_time(self):
        segment = {
            "source_time": "00:01:40.000 - 00:01:52.000",
            "media_source_time": "00:01:42.100 - 00:01:45.400",
        }

        self.assertEqual(
            worker.segment_display_source_time(segment),
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
        self.assertEqual(card["type_label"], "语境生词卡")
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
        self.assertEqual(worker.card_label_for_learning_card("", "vocabulary"), "语境生词卡")
        self.assertEqual(worker.card_label_for_learning_card("idiom", "phrase"), "表达卡")

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

    def test_v11_back_template_labels_pronunciation_note_and_empty_spoken_status(self):
        self.assertIn("发音说明", worker.LANGUAGE_BACK_TEMPLATE_V11)
        self.assertIn("未单独标注", worker.LANGUAGE_BACK_TEMPLATE_V11)
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
        self.assertIn("这句里表示某个中文意思的自然表达是什么", prompt)
        self.assertIn("typed learning point", prompt)
        self.assertIn("某个词在这句里是什么意思/怎么用", prompt)

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
        self.assertIn("未实听", card["pronunciation_note"])

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
        self.assertIn("原句听感未可靠生成", card["pronunciation_note"])
        self.assertEqual(card["pronunciation_confidence"], "low")

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
        language = worker.anki_template_assets("immersive", "video_language")
        knowledge = worker.anki_template_assets("immersive", "document_knowledge")
        reading = worker.anki_template_assets("immersive", "document_reading")

        self.assertEqual(v11[0], "沉浸复读 V12")
        self.assertIn("v11-video-stage", v11[2])
        self.assertIn("playV11Audio", v11[2] + v11[3])
        self.assertIn("toggleV11Video", v11[2] + v11[3])
        self.assertIn("点画面开始复读", v11[2] + v11[3])
        self.assertIn("复读循环中", v11[2] + v11[3])
        self.assertIn("只听原声", v11[2] + v11[3])
        self.assertIn("慢读跟读", v11[2] + v11[3])
        self.assertIn("表达 / 词义", v11[3])
        self.assertIn("{{#Context}}<p class=\"v11-source-translation\">{{Context}}</p>{{/Context}}", v11[3])
        self.assertIn("怎么用", v11[3])
        self.assertIn("别误用", v11[3])
        self.assertIn("自己造句", v11[3])
        self.assertNotIn("怎么理解", v11[3])
        self.assertNotIn("怎么迁移", v11[3])
        self.assertNotIn("老师提醒", v11[3])
        self.assertIn("v11-answer-title.is-long", v11[1])
        self.assertIn("setupV11TextSizing", v11[2] + v11[3])
        self.assertIn("{{#ChineseFeel}}<p class=\"v11-answer-note\">{{ChineseFeel}}</p>{{/ChineseFeel}}", v11[3])
        self.assertIn("{{#PhoneticIpa}}", v11[3])
        self.assertIn("标准读法", v11[3])
        self.assertIn("{{SpokenPronunciationLabel}}", v11[3])
        self.assertIn("v11-ipa-row is-spoken", v11[3])
        self.assertIn(".v11-source-block", v11[1])
        self.assertIn("grid-template-columns: max-content minmax(0, 1fr)", v11[1])
        self.assertLess(v11[3].index("<p class=\"v11-source\">{{English}}</p>"), v11[3].index("v11-source-ipa"))
        self.assertLess(v11[3].index("v11-source-ipa"), v11[3].index("v11-source-translation"))
        self.assertNotIn("overflow-wrap: anywhere", v11[1])
        self.assertIn("white-space: pre-line", v11[1])
        self.assertNotIn("<audio controls", v11[2] + v11[3])
        self.assertEqual(language[0], "视频语言 V10")
        self.assertEqual(knowledge[0], "文档知识 V10")
        self.assertEqual(reading[0], "文档精读 V10")
        self.assertIn("{{SourceLabel}}", language[3])
        self.assertIn("{{UnderstandLabel}}", knowledge[3])
        self.assertIn("边界 / 易错", reading[3])
        self.assertNotEqual(worker.anki_template_family("immersive_v11", "video_language"), worker.anki_template_family("immersive", "video_language"))
        self.assertNotEqual(worker.anki_template_family("immersive", "video_language"), worker.anki_template_family("immersive", "document_knowledge"))

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

    def test_vertex_thinking_final_card_batch_size_is_not_clamped_to_three(self):
        api = {"provider": "gemini-vertex", "model": "gemini-3.1-pro-preview"}
        self.assertEqual(worker.final_card_batch_size(api, 10), 8)
        self.assertEqual(worker.final_card_generation_concurrency(api, 4), 2)

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

    def test_default_catch_all_selection_includes_review_but_never_reject(self):
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

        self.assertEqual([card["enabled"] for card in selected[0]["cards"]], [True, True, False])

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
        self.assertIn("默认每个片段只生成 1 张主卡", prompt)
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
        self.assertEqual(cards[0]["type_label"], "表达卡")
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

        self.assertEqual([card["type"] for card in cards], ["listening"])
        self.assertEqual(cards[0]["quality"]["status"], "needs_review")
        self.assertFalse(cards[0]["enabled"])
        self.assertIn("本地草稿，需要人工确认", cards[0]["quality"]["issues"])
        self.assertNotIn("缺少明确目标表达", cards[0]["quality"]["issues"])
        self.assertNotIn("例句只是照抄原句", cards[0]["quality"]["issues"])

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
        self.assertNotIn("本地草稿，需要人工确认", phrase_card["quality"]["issues"])
        self.assertNotIn("字段像模板废话", phrase_card["quality"]["issues"])

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
        self.assertIn("本地可用卡", project["warning"])
        self.assertIn("可用卡已默认全选", project["warning"])

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
        self.assertIn(".review-card", worker.CARD_CSS)
        self.assertIn("overflow-y: auto !important", worker.CARD_CSS)
        self.assertIn("height: auto", worker.CARD_CSS)
        self.assertIn("grid-template-columns: repeat(auto-fit, minmax(220px, 1fr))", worker.CARD_CSS)
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


if __name__ == "__main__":
    unittest.main()
