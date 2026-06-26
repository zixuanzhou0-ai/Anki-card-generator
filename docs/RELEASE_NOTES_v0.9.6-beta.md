# Anki Card Generator v0.9.6-beta

This beta focuses on card quality, a cleaner single-card learning model, and user-visible copyright/source information.

## Download Assets

| Asset | Purpose |
| --- | --- |
| `Anki.Card.Generator_0.9.6_x64-setup.exe` | Recommended Windows NSIS installer. |
| `Anki.Card.Generator_0.9.6_x64_en-US.msi` | Windows MSI installer. |
| `AnkiCardGenerator-v0.9.6-beta-windows-portable.zip` | Portable Windows build. |
| `SHA256SUMS-v0.9.6-beta.txt` | Checksums for release assets. |

## What Changed

- Unified video cards into one default `学习卡` per selected learning point. Listening, expression, contextual vocabulary, grammar, and cloze-style hints now merge into one card instead of producing multiple similar cards.
- Tightened recommendation quality. Low-transfer answers such as `talk about` or targets that cannot be located in the source sentence are kept as candidates/review items instead of default recommendations.
- Added `设置 -> 关于 / 版权` with version, copyright notice, Anki independence notice, privacy/key boundary, and a GitHub repository entry.
- Added Vertex `gemini-3.5-flash` to the model catalog while keeping Vertex authentication on local `gcloud` OAuth.
- Kept the no-console Windows behavior from v0.9.5: normal installed startup and worker subprocesses should not open black terminal windows.
- Preserved the compact left-panel layout so batch/folder controls and bottom CTA remain reachable at minimum desktop window sizes.

## Validation Checklist

- `npm.cmd run check:versions`
- `npm.cmd run lint`
- `npm.cmd run test:unit`
- `npm.cmd run test:ui`
- `npm.cmd run test:worker`
- `cargo check --manifest-path src-tauri/Cargo.toml`
- `npm.cmd run build`
- `npm.cmd run tauri:build`
- Release smoke: generate learning points, create unified cards, export APKG, and verify with Anki/AnkiConnect when available.

## Notes

This is still a Windows desktop beta. macOS/Linux desktop installers and the browser/local-helper version are not included in this release. Third-party model, TTS, and video-download behavior depends on the user’s providers, network, permissions, and costs.

Do not upload API keys, private media, APKG files, local caches, or raw test runs when reporting issues.