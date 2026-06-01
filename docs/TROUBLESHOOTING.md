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

Reasoning models such as DeepSeek V4, Qwen / DashScope, MiMo, or Gemini Vertex may spend longer in material understanding or candidate review. The app keeps the reasoning path alive and strips thinking before JSON parsing, so a longer wait is not automatically an error. If progress stays at the same percent but the message says “thinking 已保留”, the model is still working.

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

Gemini Vertex uses local `gcloud` auth instead of an API key:

- Install Google Cloud SDK and sign in with `gcloud auth login`.
- Set the project with `gcloud config set project <project-id>`.
- Use provider `Gemini Vertex`, Base URL `https://aiplatform.googleapis.com`, and model `gemini-3.1-pro-preview`.
- If `gemini-3.1-pro` returns 404, use the preview model that is enabled in the current Vertex project.

Gemini Vertex TTS uses the same local `gcloud` auth path:

- In TTS settings, choose `Gemini 3.1 TTS Vertex`.
- Use Base URL `https://aiplatform.googleapis.com`, model `gemini-3.1-flash-tts-preview`, and a voice such as `Kore`, `Aoede`, `Puck`, or `Charon`.
- Leave the TTS API Key empty. The app calls Vertex AI with a short-lived `gcloud auth print-access-token` token.
- If you need a regional endpoint, use an `aiplatform.googleapis.com` regional base such as `https://us-central1-aiplatform.googleapis.com`.
- The Vertex response is raw 24 kHz PCM, so FFmpeg must be available to convert it into the MP3 files Anki imports.

The app should never require a real key in source files, docs, logs, or release artifacts.

## Cards Do Not Match The Current Video

Use local video + the exact SRT file for that video, then regenerate with Deep Study enabled. The review dashboard should show a “素材理解” card; if its summary describes the wrong material, cancel and check that the selected source mode is still “本地视频” and the paths point to the current video/SRT. If the summary is correct but individual cards are weak, disable that card or switch off the irrelevant learning focus such as “单词用法” or “听力难点”.

The current review pipeline keeps a `source_segment_id` for every candidate, requires `exact_span` to appear in the source sentence, and caps each subtitle sentence at two learning points. If a model returns an explanation as the learning answer, for example `run the register = 负责收银`, the candidate is rejected instead of becoming a broken card title.

If stale cards still appear after switching source type:

1. Confirm the left source selector is still `本地视频`.
2. Clear the previous generated project by starting a new generation from the selected video/SRT pair.
3. Check the top summary; it should describe the current material, not an older YouTube URL or document.
4. Avoid manually reusing old card edits after changing source files.

## TTS Fails

Common causes:

- Invalid TTS key.
- Wrong TTS base URL.
- Unsupported voice/model/format.
- Balance or quota exhausted.

You can disable TTS and still generate cards with original audio/video. TTS is only needed for extra sentence or phrase audio.

## TTS Audio Does Not Match The Card Text

The exporter generates two different AI audio fields:

- Sentence TTS reads the full `English` source sentence.
- Phrase TTS reads the visible core answer, normally `answer_core` or the cleaned phrase.

If the phrase audio sounds unrelated, inspect the card in the review panel before export. The core answer must be the English expression only. Chinese meaning, IPA, pronunciation explanations, and teacher notes belong in `phonetic_ipa`, `spoken_ipa`, `source_spoken_ipa`, `pronunciation_note`, or explanation fields, not in `answer_core`. The worker now repairs or rejects mixed-language `answer_core`, and export writes a `media_ledger` so TTS files can be traced back to the segment, card, learning point, and text hash.

## TTS Sounds Slow or Unnatural

First switch the in-app preview speed to `1x`. The `0.75x` control only changes review-page playback and does not slow down the exported Anki MP3.

For English cards:

- Prefer original video audio when the source clip already has clear speech.
- MiMo V2.5 TTS is currently the safer default for natural English learning audio.
- Qwen3 TTS users should try `Jennifer` for American English female voice or `Aiden` for American English male voice before using `Cherry`.
- Gemini Vertex TTS users should start with `Kore`, `Aoede`, `Puck`, or `Charon`, then compare with the original video audio before making it the default for a deck.
- Use `qwen3-tts-instruct-flash` only when you need explicit style, emotion, or pacing instructions.

## FFmpeg Missing or Media Slicing Fails

Install FFmpeg and make sure it is available on PATH, then restart the app. If only the media step fails, export text cards first and revisit slicing later.

## APKG Export or Anki Import Fails

Check:

- The export path ends in `.apkg`.
- Anki is installed if you want the app to open the package directly.
- The generated APKG passes `workers/verify_apkg.py`.
- The import verifier is looking for the correct template tag: V10 packages use `anki_card_generator_v10`; V12 language packages use `anki_card_generator_v12`.

Release smoke output includes `verify_apkg.json`, which is the fastest way to inspect missing cards, media files, or template problems.

## Privacy Checks

Before sharing logs or screenshots:

- Redact API keys and Authorization headers.
- Hide personal file paths if needed.
- Do not share private videos, subtitles, generated decks, or cache folders.
