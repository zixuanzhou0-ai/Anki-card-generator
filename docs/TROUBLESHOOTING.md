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

The progress message should show the current stage: subtitle parsing, candidate building, model review, card generation, media slicing, TTS, export, or verification.

If the UI stays on one stage for a long time:

1. Click cancel.
2. Retry with TTS disabled.
3. Retry with video slicing disabled or subtitle-only mode.
4. Use a shorter local SRT to confirm the model/API path works.

## API Test Fails

Check:

- Provider preset matches the API key.
- Base URL is correct.
- Model name is lowercase when the provider requires it.
- The key has enough quota.

The app should never require a real key in source files, docs, logs, or release artifacts.

## TTS Fails

Common causes:

- Invalid TTS key.
- Wrong TTS base URL.
- Unsupported voice/model/format.
- Balance or quota exhausted.

You can disable TTS and still generate cards with original audio/video. TTS is only needed for extra sentence or phrase audio.

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
