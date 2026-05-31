# Troubleshooting

This guide covers the common failures for `v0.9.2-beta`.

## YouTube URL Fails

Common causes:

- HTTP 429: YouTube is rate limiting requests.
- n challenge / EJS warning: yt-dlp needs a supported JavaScript runtime and challenge solver.
- Subtitles unavailable: the video has no usable English captions.
- Region/login restriction: the video cannot be fetched anonymously from the current network.

Recommended actions:

1. Switch to subtitle-only generation if subtitles are available.
2. Download or provide your own SRT and use local video + SRT.
3. Run `scripts/setup_runtime.ps1` again to refresh yt-dlp dependencies.
4. Try a different video or wait before retrying if the error is 429.

## Generation Gets Stuck

The progress message should show the current stage: subtitle parsing, material understanding, candidate building, model review, card generation, media slicing, TTS, export, or verification.

If the UI stays on one stage for a long time:

1. Click cancel.
2. Retry with TTS disabled.
3. Switch “理解深度” to “快速生成” to skip the extra material-context call.
4. Retry with video slicing disabled or subtitle-only mode.
5. Use a shorter local SRT to confirm the model/API path works.

Reasoning models such as DeepSeek V4, Qwen / DashScope, or MiMo may spend longer in material understanding or candidate review. The app streams their `reasoning_content` / thinking deltas for progress updates, then strips thinking before JSON parsing, so a longer wait is not automatically an error. If progress stays at the same percent but the message says “正在思考” and the thinking character count is increasing, the model is still working.

## API Test Fails

Check:

- Provider preset matches the API key.
- Base URL is correct.
- Model name is lowercase when the provider requires it.
- The key has enough quota.

DeepSeek V4 presets use:

- Base URL: `https://api.deepseek.com`
- Pro model: `deepseek-v4-pro`
- Flash model: `deepseek-v4-flash`

The app should never require a real key in source files, docs, logs, or release artifacts.

## Cards Do Not Match The Current Video

Use local video + the exact SRT file for that video, then regenerate with Deep Study enabled. The review dashboard should show a “素材理解” card; if its summary describes the wrong material, cancel and check that the selected source mode is still “本地视频” and the paths point to the current video/SRT. If the summary is correct but individual cards are weak, disable that card or switch off the irrelevant learning focus such as “单词用法” or “听力难点”.

## TTS Fails

Common causes:

- Invalid TTS key.
- Wrong TTS base URL.
- Unsupported voice/model/format.
- Balance or quota exhausted.

You can disable TTS and still generate cards with original audio/video. TTS is only needed for extra sentence or phrase audio.

## TTS Sounds Slow or Unnatural

First switch the in-app preview speed to `1x`. The `0.75x` control only changes review-page playback and does not slow down the exported Anki MP3.

For English cards:

- Prefer original video audio when the source clip already has clear speech.
- MiMo V2.5 TTS is currently the safer default for natural English learning audio.
- Qwen3 TTS users should try `Jennifer` for American English female voice or `Aiden` for American English male voice before using `Cherry`.
- Use `qwen3-tts-instruct-flash` only when you need explicit style, emotion, or pacing instructions.

## FFmpeg Missing or Media Slicing Fails

Install FFmpeg and make sure it is available on PATH, then restart the app. If only the media step fails, export text cards first and revisit slicing later.

## APKG Export or Anki Import Fails

Check:

- The export path ends in `.apkg`.
- Anki is installed if you want the app to open the package directly.
- The generated APKG passes `workers/verify_apkg.py`.

Release smoke output includes `verify_apkg.json`, which is the fastest way to inspect missing cards, media files, or template problems.

## Privacy Checks

Before sharing logs or screenshots:

- Redact API keys and Authorization headers.
- Hide personal file paths if needed.
- Do not share private videos, subtitles, generated decks, or cache folders.
