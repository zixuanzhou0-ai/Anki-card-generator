# Anki Card Generator v0.9.4-beta

This beta publishes the left-sidebar usability fix tested after `v0.9.3-beta`.

## Downloads

| Asset | Purpose |
| --- | --- |
| `AnkiCardGenerator-v0.9.4-beta-windows-portable.zip` | Portable Windows build. |
| `Anki Card Generator_0.9.4_x64-setup.exe` | Windows NSIS installer. |
| `Anki Card Generator_0.9.4_x64_en-US.msi` | Windows MSI installer. |
| `SHA256SUMS-v0.9.4-beta.txt` | Download checksums. |

## What Changed

- The left workflow console no longer becomes unusable when the window is compressed.
- At the desktop minimum width, the app now enters compact “素材面板” mode instead of squeezing the two-column layout.
- Workflow state stays fixed while stage content scrolls independently, so primary actions remain reachable.
- Batch video-folder controls and the bottom continue/export actions are covered by Playwright reachability checks at `1180x780`.

## Validation

- `npm.cmd run lint`
- `npm.cmd run build`
- `npm.cmd run test:unit`
- `npm.cmd run test:ui`
- `npm.cmd run tauri:build`

## Beta Notes

Video downloading, model calls, TTS, AnkiConnect, and media playback still depend on local environment, third-party services, network access, provider limits, and source-media rights.
