# Troubleshooting

This guide covers the current desktop app behavior.

## Desktop App Starts Slowly Or Shows Localhost Errors

Development startup uses two processes:

1. Vite starts the local frontend at `http://127.0.0.1:<selected-dev-port>/`.
2. Tauri/Cargo compiles and starts the desktop window.

If the desktop window is slow after code changes, wait for Cargo to finish. A cold Tauri build can take around a minute. A browser page showing `localhost refused connection` only means the frontend dev server is not ready or has stopped; it does not by itself prove the desktop app build is broken.

Recommended developer startup:

```powershell
cd path\to\Anki-card-generator
npm.cmd run desktop:dev
```

`desktop:dev` is the recommended entrypoint. It starts Vite and Tauri as child processes, keeps stdout/stderr in log files, and hides the Tauri dev console by default so only the desktop UI appears. If you need a visible debug console, run:

```powershell
npm.cmd run desktop:dev:debug
```

Avoid judging the app by an old installed portable release; use the current workspace when testing active changes.

Startup diagnostics:

- `.tauri-dev-current.out`
- `.tauri-dev-current.err`
- `.tauri-launch-current.json`
- `.tauri-startup-current.json`

The intended behavior is that, if `desktop:dev` fails, it exits non-zero and stops only the half-started workspace process tree so the next run starts cleanly. `npm.cmd run tauri:dev` is still available as the raw Tauri command for low-level debugging, but it is no longer the recommended everyday entrypoint.

Windows can reserve local port ranges dynamically, which previously made fixed dev ports fail with `EACCES`. The desktop startup script now probes a small candidate list starting at `5173` and writes the selected URL into the temporary Tauri dev config.

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

### AnkiConnect Works But Anki Path Is Not Detected

On some Windows installs, Anki may live under the current user's local app directory, for example:

```text
%LOCALAPPDATA%\AnkiProgramFiles\.venv\Scripts\ankiw.exe
```

If another run shows a mixed state:

```text
anki_installed=false
anki_running=false
anki_connect=true
```

In that case, treat AnkiConnect as the stronger signal for import verification. It means the worker can talk to Anki through `http://127.0.0.1:8765`, even if the app did not locate `anki.exe` for launch/repair actions.

Quick confirmation:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8765 -Method Post -ContentType 'application/json' -Body '{"action":"version","version":6}'
```

Expected result:

```json
{"result":6,"error":null}
```

If import verification needs to read `collection.media`, remember that Anki stores it under the user profile, outside the repository. Sandboxed commands may need explicit permission to read that directory.

## Document Entry Is Not Visible

This is expected in the current public workflow. Document card generation has been hidden from the ordinary desktop flow so the release can focus on reliable video language cards.

What should be visible:

- `本地视频`
- `视频链接`
- Video file picker filters such as MP4, MKV, MOV, AVI, WEBM.
- Optional SRT subtitle picker.

If a restored old project or localStorage entry still contains `source_mode=document`, the app should fall back to the public video flow instead of showing document controls.

## YouTube URL Fails

Common causes:

- HTTP 429: YouTube is rate limiting requests.
- n challenge / EJS warning: yt-dlp needs Deno or Node.
- Captions unavailable.
- Region/login restriction.

Recommended actions:

1. Use local video + SRT if you already have a downloaded copy.
2. Run `一键修复全部可修复项` to refresh yt-dlp and Deno.
3. Wait or change network if YouTube returns 429.
4. Confirm the video has usable captions/subtitles before retrying.

## No SRT File

Current V1 does not include ASR or forced alignment.

Fallback order:

1. If the video has embedded subtitles, the app can try to extract them.
2. If there is a same-directory `.srt` or `.vtt`, the app can try to match it.
3. If there is no subtitle, transcribe with Whisper/local ASR/online ASR first, then import the SRT.

## Generation Feels Slow

The current workflow does more than old simple subtitle splitting:

- local learning point recall
- AI learning point review and missing-point expansion
- user selection of recommended/candidate learning points
- hard validation
- dedupe
- multilingual pronunciation metadata
- card body generation
- required TTS and media ledger for video-card export

The main slow stages are usually:

- full-subtitle AI review
- card body generation with a slower high-quality model
- two TTS files per video card
- ffmpeg slicing for video, poster, original audio, and webm/mp4 variants
- APKG packaging and verification

Switching from a Pro/Preview reasoning model to a faster model can speed AI review and card body generation, but it will not remove TTS or media slicing time. A safer product direction is hybrid routing: use a fast model for obvious cards, and use a stronger model only for complex, low-confidence, C1/C2, or repair cases.

Cost/time controls:

- Use shorter source clips for testing.
- For early draft inspection, generate fewer selected cards first.
- Use fast mode when you only need the lighter review template.
- Reuse cache for repeated local tests, but use fresh material and cold settings for real benchmarks.
- Keep learning level on auto unless you need a manual preference.

## Generated Card Count Looks Low

For selected learning points, the current product expectation is:

```text
selected learning points ~= generated cards
```

If the model omits optional fields, the app should create a fallback card from the selected learning point and subtitle context, then record the missing fields in advanced diagnostics. The UI should not present “model did not return this learning point” as a normal reason to drop a user-selected card.

If generated cards are fewer than selected cards, it should be treated as a hard failure or a bug unless the diagnostic says one of these concrete failures happened:

- source media cannot be read
- video slicing failed
- sentence TTS or phrase TTS still failed after retry
- media ledger or manifest hash mismatch
- Anki/APKG verification failed

Open advanced diagnostics only for the reason distribution. Ordinary users should mainly see selected, generated, exportable, and failed-hard counts.

## Learning Point Extraction Finishes In A Few Seconds

Formal extraction should call the configured model API. If it finishes in a few seconds, check these cases:

- You are looking at cached/demo/browser preview behavior rather than desktop worker behavior.
- `reuse_ai_review_cache` is enabled and the same batch was already reviewed.
- The task failed early but the UI is showing stale previous results.
- API readiness was not tested and the app blocked formal extraction.

For quality checks, use the desktop app, confirm the settings page shows the model API test passed, and start a fresh `抽取学习点` run.

## Hidden Experimental Template Export Still Looks Like V11

The ordinary video/subtitle workflow no longer exposes experimental templates. It should use `沉浸复读 V11` with either `完整复读` or `快速复读`.

This section is only for developer or regression checks that intentionally create a `template_id=ciba_tianxia_v1` project.

`词霸天下实验 V1` changes the bottom-layer behavior:

- AI learning point review prompt.
- scoring preference for language actions.
- final card-generation prompt.
- exported Anki card face.

It now provides a separate exported Anki visual template. The back side should use Ciba labels such as `语言动作`、`语境义`、`迁移句`、`搭配边界 / 别这么用` and `原句场景`.

If an exported Ciba APKG still shows the V11 blocks `怎么用 / 别误用 / 自己造句`, check that the project `template_id` is `ciba_tianxia_v1`, rebuild the current desktop package, and confirm `anki_template_assets("ciba_tianxia_v1", ...)` is returning the Ciba template assets.

## TTS Fails

Check `设置 -> 语音 TTS`:

- Provider/model/voice match.
- API key exists when the provider needs one.
- Vertex TTS uses local `gcloud` auth and does not need an API key field.
- FFmpeg is available, because some providers return PCM that needs conversion.

For the public video-card workflow, sentence TTS and phrase TTS are required media. If TTS is disabled or missing, use that only as an intermediate debugging state; a final video APKG should not be exported with broken or missing TTS.

### Export Says TTS Failed And No APKG Was Generated

This means the app protected the package because one or more required TTS files were missing. The generated card bodies are still kept; the app did not intentionally discard the whole project.

Current expected UI behavior:

- show how many TTS items failed
- show the failed card/expression/source sentence when available
- show provider/model/voice details
- offer `重试失败 TTS 并导出`

If retry still fails:

1. Open `设置 -> 语音 TTS`.
2. Test the TTS configuration.
3. Try a different voice/model if the provider rejects a specific text.
4. Inspect the structured `MISSING_TTS_MEDIA` details in the worker result.

Missing TTS remains a hard export gate for video cards because exporting a card with broken audio would create a bad Anki package.

## TTS Audio Does Not Match Card Text

The exporter uses different text sources:

- `TtsAudio`: full source sentence.
- `PhraseTtsAudio`: visible core answer / answer_core.

If phrase audio sounds wrong, inspect the card before export. The answer field must not contain Chinese explanation, IPA, or pronunciation notes. Those belong in pronunciation/explanation fields.

The export writes a media ledger with TTS text hash, segment id, card id, and learning point id. APKG verification should report zero media/TTS hash mismatches.

ASR / Whisper is not part of the current public export gate. A local ASR model is not required to use the app, and ASR mismatch should not block ordinary video card export.

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

