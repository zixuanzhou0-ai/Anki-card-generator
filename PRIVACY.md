# Privacy

This document describes the data flow for Anki Card Generator `v0.9.0-beta`.

## Data kept on this device

The app may create local working files, including:

- downloaded video and subtitle files;
- extracted video clips, audio clips, poster images, and TTS audio;
- generated `.apkg` decks;
- temporary JSON project data and smoke-test output;
- local settings such as provider, model, base URL, selected template, and learning options.

Generated media, decks, caches, and `.venv/` are ignored by Git by default.

## Data sent to third parties

When model review or TTS is enabled, the app sends selected text to the provider configured by the user. Depending on the selected feature, this may include:

- subtitle segments;
- document excerpts;
- candidate phrases;
- generated card fields;
- text used for TTS generation.

Providers shown in the UI may include MIMO, DeepSeek, OpenRouter, Claude, Gemini, xAI, and custom OpenAI-compatible endpoints. Each provider has its own privacy policy and retention behavior.

## YouTube and external downloads

YouTube URL import uses yt-dlp. Video and subtitle download behavior depends on YouTube, yt-dlp, network conditions, and local JavaScript runtime support.

## API keys

Do not commit or share API keys. The desktop UI keeps API keys in memory for the current session and strips text/TTS key fields before writing request settings to browser localStorage. Closing or refreshing the app may require entering keys again.

The target design is to move keys to system secure storage / keychain. Until then, avoid screenshots, logs, or support bundles that expose key fields.

## Deleting local data

To remove generated data, delete the chosen project/output folders and the `release/`, `projects/`, and generated media directories. For a portable package, you can also delete the local `.venv/` and re-run `scripts/setup_runtime.ps1` later.

## Copyright

The app can create decks containing video clips, subtitles, and document excerpts. Users are responsible for ensuring they have the right to use the source material. Generated decks are intended for personal study unless the user has permission to distribute the underlying media and text.
