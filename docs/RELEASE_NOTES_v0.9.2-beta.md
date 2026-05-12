# v0.9.2-beta

This beta refresh focuses on the visible desktop experience and release assets.

## Highlights

- Refined the desktop UI toward a cleaner black-and-white Apple-style tool surface.
- Updated the app icon and generated Tauri icon assets to match the new visual direction.
- Collapsed secondary Inspector options so the left side feels less like a long form.
- Added a stronger minimum window guard at `1180 x 780` to protect the three-pane layout.
- Kept the background worker flow for generation/export so the UI remains responsive while jobs run.
- Refreshed README and user-guide screenshots to match the current interface.

## Verified

- `npm run build`
- `npm run test:ui`
- `cargo build --manifest-path src-tauri/Cargo.toml --locked`
- `npm run tauri:build`

## Known Limits

- YouTube import can still fail because of 429 limits, subtitle availability, region limits, or yt-dlp challenge changes.
- The Windows installer does not include Python, FFmpeg, Node/Deno, or Anki. Use the portable package and run `scripts/setup_runtime.ps1` first.
- Model and TTS calls send selected text to the configured third-party provider and may incur API costs.
