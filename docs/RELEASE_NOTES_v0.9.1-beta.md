# v0.9.1-beta

This beta refresh updates the public Windows package with the Apple-style desktop UI, cancellable background worker jobs, and the V10 Anki template.

## Highlights

- Redesigned the desktop app with a lighter Apple-style visual system, cleaner panels, and a right-side settings sheet.
- Added lightweight motion for settings, segment switching, and card editing, with reduced-motion support.
- Moved long generate/export/verify operations into background worker jobs so the UI remains scrollable and the current job can be cancelled.
- Updated the Anki template to V10 with a lighter white/gray/blue style while keeping the existing APKG fields compatible.
- Added public beta hardening around local runtime setup, portable smoke testing, API key storage, and release verification.

## Verified

- `npm run check`
- `npm run test:ui`
- `cargo build --manifest-path src-tauri/Cargo.toml --locked`
- `npm run smoke:release`
- `npm run tauri:build`
- `scripts/package_portable.ps1`
- `scripts/smoke_portable.ps1`

## Known Limits

- YouTube import can still fail because of 429 limits, subtitle availability, region limits, or yt-dlp challenge changes.
- The Windows installer does not include Python, FFmpeg, Node/Deno, or Anki. The portable package includes setup scripts and is still the recommended beta download.
- Model and TTS calls send the selected text to the configured third-party provider and may incur API costs.
