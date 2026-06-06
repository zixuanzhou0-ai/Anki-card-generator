# Troubleshooting

This guide covers the current desktop app behavior.

## Local Environment Check Fails

Open `设置 -> 本地环境` and click `检查环境`.

The app now separates these cases:

- Python runtime missing.
- Python worker dependencies missing.
- FFmpeg missing.
- Deno/Node missing.
- Anki desktop missing.
- Anki installed but not running.
- AnkiConnect not installed or not connected.

Click `一键修复全部可修复项` first.

What the repair can do:

- Install recommended Python 3.12 through winget.
- Create project `.venv`.
- Install/upgrade `genanki`, `yt-dlp`, `pypdf`.
- Install FFmpeg through winget.
- Install Deno through winget.
- Install Anki through winget.

What still needs user confirmation:

- AnkiConnect must be installed inside Anki with plugin code `2055492159`.
- If winget is not available, system dependencies need manual installation.

## Python Worker Cannot Start

If the Python worker cannot start, the Tauri native bootstrap layer should still show a local environment report. Use `一键修复全部可修复项` to install recommended Python 3.12, then restart the app and run the check again.

The app intentionally does not install “latest Python”. It targets Python 3.12 for stability.

## AnkiConnect Is Not Connected

Check the exact status in `设置 -> 本地环境`:

- `Anki 桌面端` blocked: install Anki or use the repair button.
- `Anki 桌面端` installed but not running: open Anki.
- `AnkiConnect 插件` not connected: install/enable the plugin.

Plugin install steps:

1. Open Anki.
2. Tools -> Add-ons -> Get Add-ons.
3. Enter `2055492159`.
4. Restart Anki.
5. Return to the app and click `检查环境`.

You can still export `.apkg` without AnkiConnect; you just cannot run automatic import verification.

## YouTube URL Fails

Common causes:

- HTTP 429: YouTube is rate limiting requests.
- n challenge / EJS warning: yt-dlp needs Deno or Node.
- Captions unavailable.
- Region/login restriction.

Recommended actions:

1. Switch to subtitle-only generation if captions are available.
2. Use local video + SRT.
3. Run `一键修复全部可修复项` to refresh yt-dlp and Deno.
4. Wait or change network if YouTube returns 429.

## No SRT File

Current V1 does not include ASR or forced alignment.

Fallback order:

1. If the video has embedded subtitles, the app can try to extract them.
2. If there is a same-directory `.srt` or `.vtt`, the app can try to match it.
3. If there is no subtitle, transcribe with Whisper/local ASR/online ASR first, then import the SRT.

## Generation Feels Slow

The current workflow does more than old simple subtitle splitting:

- material understanding
- learning point recall
- hard validation
- dedupe
- multilingual pronunciation metadata
- card body generation
- optional TTS and media ledger

Cost/time controls:

- Use shorter source clips for testing.
- Disable TTS while checking card quality.
- Use subtitle-only when video slicing is not needed.
- Keep learning level on auto unless you need a manual preference.

## Generated Card Count Looks Low

The app no longer exposes “recommended / review / reject” as the main user workflow. It now shows:

- generated usable cards
- selected cards
- discovered learning points
- learning point diagnostics
- duplicate/hard-blocked counts

If generated cards are fewer than expected, open `学习点诊断`. It will show whether learning points were:

- legal but not generated yet
- duplicate training actions
- hard-blocked because `exact_span` was not in the source sentence
- hard-blocked because `answer_core` contained Chinese, IPA, or explanation text

The current V1 does not automatically generate complete media/TTS/Anki fields for every candidate-only learning point.

## TTS Fails

Check `设置 -> 语音 TTS`:

- Provider/model/voice match.
- API key exists when the provider needs one.
- Vertex TTS uses local `gcloud` auth and does not need an API key field.
- FFmpeg is available, because some providers return PCM that needs conversion.

You can disable TTS and still export cards with original video/audio.

## TTS Audio Does Not Match Card Text

The exporter uses different text sources:

- `TtsAudio`: full source sentence.
- `PhraseTtsAudio`: visible core answer / answer_core.

If phrase audio sounds wrong, inspect the card before export. The answer field must not contain Chinese explanation, IPA, or pronunciation notes. Those belong in pronunciation/explanation fields.

The export writes a media ledger with TTS text hash, segment id, card id, and learning point id. APKG verification should report zero media/TTS hash mismatches.

## TTS Is Much Louder Than Original Video

Exported AI TTS is lowered by default to 65%. This affects exported Anki media only. It does not change in-app preview and does not boost original video volume.

If it still feels unbalanced, lower the TTS export volume in settings.

## Pronunciation Fields Are Hidden Or Marked Low Confidence

This is usually intentional.

V1 does not do ASR or forced alignment. When pronunciation is inferred from subtitles:

```text
generation_basis = subtitle_inferred
```

The UI should call it inferred/spoken approximation rather than audio-verified performance. If a field is cleared or hidden, `PronunciationMeta.field_changes` records the reason.

## Japanese Pitch Or Russian Stress Looks Suspicious

V1 does not connect external dictionaries such as NHK/OJAD or Russian stress dictionaries.

Rules:

- Japanese kana reading is required; pitch accent is only shown when confidence is acceptable.
- Russian multi-syllable words should mark stress; uncertain stress should lower confidence.

If the model guesses too confidently, treat the card as needing manual review.

## APKG Export Or Anki Import Fails

Check:

- The export path ends in `.apkg`.
- The APKG passes `workers/verify_apkg.py`.
- Anki is installed if you want the app to open the package.
- AnkiConnect is installed and running if you want import verification.
- `PronunciationMeta` JSON is parseable.
- Media manifest and TTS ledger have no missing/hash mismatch entries.

## Privacy Checks

Before sharing screenshots or logs:

- Redact API keys and Authorization headers.
- Hide private file paths if needed.
- Do not share private videos, subtitles, generated decks, or cache folders.
