# Anki Card Generator v0.9.5-beta

This beta publishes the Windows no-console release. It keeps the existing video-to-Anki workflow intact while closing the remaining places where Windows could show a black terminal window during normal desktop use.

## Downloads

| Asset | Purpose |
| --- | --- |
| `AnkiCardGenerator-v0.9.5-beta-windows-portable.zip` | Portable Windows build. |
| `Anki.Card.Generator_0.9.5_x64-setup.exe` | Windows NSIS installer. |
| `Anki.Card.Generator_0.9.5_x64_en-US.msi` | Windows MSI installer. |
| `SHA256SUMS-v0.9.5-beta.txt` | Download checksums. |

## What Changed

- Normal installed-app startup stays in GUI mode and does not open an extra terminal window.
- Development startup still hides Vite/Tauri helper windows by default; `desktop:dev:debug` remains available when a visible debug console is needed.
- Python worker subprocesses now hide Windows console windows when calling tools such as Calibre `ebook-convert` and `ffprobe`.
- Logs and diagnostic output remain available through existing log files and smoke/verification reports.

## Validation

- `npm.cmd run check:versions`
- `npm.cmd run lint`
- `npm.cmd run test:unit`
- `npm.cmd run test:ui`
- `npm.cmd run test:worker`
- `npm.cmd run smoke:release`
- `npm.cmd run build`
- `cargo check --manifest-path src-tauri/Cargo.toml`
- `npm.cmd run tauri:build`

## Beta Notes

This release is still Windows desktop only. Video downloading, model calls, TTS, AnkiConnect, and media playback depend on local environment, third-party services, network access, provider limits, and source-media rights. Do not publish API keys, private videos, private subtitles, local caches, or generated APKG evidence.