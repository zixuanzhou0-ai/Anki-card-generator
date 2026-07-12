# Repository Boundaries

This document is the anti-mess rulebook for adding the browser app and local helper.

## Non-Negotiable Separation

The Windows desktop app and the browser app must not live in the same product folder.

Do not add browser-only code under the current desktop source tree just because it is convenient. Do not add helper daemon code into the Tauri backend unless it is intentionally extracted into a shared package. Do not make one root `src/` carry both desktop and browser application shells.

The target structure is:

```text
apps/windows-desktop/
apps/web-static/
apps/local-helper/
packages/shared-contracts/
packages/shared-card-logic/
docs/web-helper/
```

## Folder Responsibilities

`apps/windows-desktop/` is the existing Tauri desktop application. It owns:

- Tauri config.
- Windows desktop packaging.
- Desktop window behavior.
- Desktop-specific launch scripts.
- Desktop UI shell.
- Desktop worker bridge.
- Windows release notes and screenshots.

`apps/web-static/` is the static browser application. It owns:

- Web app routing and layout.
- Browser-only runtime.
- Helper runtime client.
- Browser settings storage.
- Project/session UI for web users.
- Static deployment config.
- Web screenshots and usage guide.

`apps/local-helper/` is the native helper. It owns:

- Local HTTP server on `127.0.0.1`.
- Pairing and origin allowlist.
- File and folder picker bridge.
- FFmpeg and worker execution.
- APKG export.
- Anki verification bridge.
- Cross-platform installer definitions.
- Helper logs and diagnostics.

`packages/shared-contracts/` owns TypeScript/Rust/Python-compatible schema definitions where practical:

- Runtime capability shapes.
- Job status shapes.
- Learning point contracts.
- Card generation payload contracts.
- Export result contracts.
- Error code contracts.

`packages/shared-card-logic/` owns pure logic only:

- Card field shaping.
- Review mode mapping.
- Source metadata normalization.
- Non-platform-specific validation.

It must not import Tauri, browser DOM APIs, Node-only APIs, or OS-specific file APIs.

## Migration Rules

The repository should be migrated in phases.

Phase 1 creates folders and documentation without moving product code.

Phase 2 creates the web-static skeleton and helper skeleton.

Phase 3 extracts shared contracts.

Phase 4 moves desktop code into `apps/windows-desktop/`, if and only if tests and packaging can be updated safely.

Phase 5 updates GitHub README and release docs so users can choose the correct product.

Never do a massive blind move without validation. After each movement phase, run the relevant tests and keep the commit easy to review.

## Public GitHub Explanation

The root README must contain a clear "Choose Your Product" section:

```text
Windows Desktop App
- Best for Windows users who want the full desktop workflow.
- Download the Windows installer from Releases.
- Source folder: apps/windows-desktop.

Browser Web App
- Best for cross-platform users who want a web UI.
- Works in browser-only mode with limited local system access.
- Full local media support requires Local Helper.
- Source folder: apps/web-static.

Local Helper
- Optional native service for browser users.
- Required for FFmpeg, folder access, APKG export parity, and Anki verify.
- Source folder: apps/local-helper.
```

Every GitHub Release that contains browser/helper assets must state exactly which asset is for which user:

- `Anki.Card.Generator_*.exe`: Windows desktop app.
- `acg-helper-windows-*.msi`: helper for browser app on Windows.
- `acg-helper-macos-*.dmg`: helper for browser app on macOS.
- `acg-helper-linux-*.AppImage`: helper for browser app on Linux.
- `web-static-*.zip`: static site build artifact, if published.

## Staging Rules

Use whitelist staging only.

Allowed public files:

- Product source under the correct app folder.
- Shared packages.
- Public docs.
- CI config.
- Tests.
- Public screenshots after manual sensitive-data review.

Forbidden files:

- API keys.
- `.env` and local config files.
- User project caches.
- `test_runs/`.
- APKG exports.
- Raw videos/audio.
- Local logs.
- Internal handoff documents unless explicitly intended.

## Review Gate

Before pushing:

- `git diff --cached --name-status` must show only expected files.
- A secret scan must run on the staged diff.
- The root README must explain the folder split.
- Each app folder must have its own README.
- The browser app must not import desktop app internals.
- The helper must not expose an arbitrary command execution endpoint.

