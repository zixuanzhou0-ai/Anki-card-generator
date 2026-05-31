# v0.9.2-beta

This beta refresh focuses on the visible desktop experience and release assets.

## Highlights

- Refined the desktop UI toward a cleaner black-and-white Apple-style tool surface.
- Updated the app icon and generated Tauri icon assets to match the new visual direction.
- Collapsed secondary Inspector options so the left side feels less like a long form.
- Kept the desktop baseline as a two-pane layout: left Inspector and right Workspace, without the extra Rail.
- Added a desktop minimum window guard at `1180 x 780` while keeping the two-pane layout usable on common laptop displays.
- Kept the background worker flow for generation/export so the UI remains responsive while jobs run.
- Refreshed README and user-guide screenshots to match the current interface.
- Split the frontend entry into an app shell/controller and split option presets into domain modules.
- Moved the Python worker entrypoint to a small command router and added schema metadata to worker responses.
- Split document input into a default knowledge-absorption path and an opt-in language-reading path. Knowledge mode hides video-language controls such as CEFR level, listening cards, and phrase-card toggles.
- Added the first Deep Study pipeline: generation now stores a hidden `material_context` and feeds it into candidate review and card writing, so stronger thinking models can judge the whole material before producing cards.
- Added contextual vocabulary cards. `vocabulary` is now part of the default video learning focus, and `vocabulary_usage` cards export with the `语境生词卡` label while keeping V10 APKG fields compatible.
- Added the default `沉浸复读 V11` Anki template for video/subtitle cards. The front is now a focused shadowing card with autoplaying muted loop video and custom `原声` / `慢读` buttons; the back prioritizes core expression, Chinese intuition, source sentence, phrase TTS, and compact explanation blocks while preserving compatible fields.
- Generalized candidate review language from MIMO-only phrase review toward OpenAI-compatible AI candidate review, including Qwen / DashScope-compatible reasoning models.
- Added DeepSeek V4 Pro and DeepSeek V4 Flash presets. DeepSeek V4 thinking output is streamed as progress and stripped before JSON parsing, so the model can keep reasoning without stalling generation at an unchanged percent.
- Hardened TTS export so resolved provider settings are used during APKG export, including saved/reused TTS API keys.
- Updated Qwen3 TTS presets for English cards: `Jennifer` is now the default American English female voice, `Aiden` is available as an American English male voice, and Qwen3 voice-design model IDs are exposed for advanced setup.

## Verified

- `npm run build`
- `npm run test:unit`
- `npm run test:ui`
- `npm run test:worker`
- `cargo build --manifest-path src-tauri/Cargo.toml --locked`
- `npm run tauri:build`

## Known Limits

- YouTube import can still fail because of 429 limits, subtitle availability, region limits, or yt-dlp challenge changes.
- The Windows installer does not include Python, FFmpeg, Node/Deno, or Anki. Use the portable package and run `scripts/setup_runtime.ps1` first.
- Model and TTS calls send selected text to the configured third-party provider and may incur API costs.
- TTS voice quality varies by provider and voice. For English learning cards, prefer original audio or MiMo V2.5 TTS; if using Qwen3 TTS, try `Jennifer` or `Aiden` before `Cherry`.
- Deep Study can be slower and use more model tokens because it asks the model to understand the material before selecting cards. Use “快速生成” when validating a workflow quickly.
