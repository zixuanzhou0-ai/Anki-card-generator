# Browser App + Local Helper Implementation Plan

## Purpose

Build a cross-platform browser edition of Anki Card Generator while keeping the current Windows desktop app cleanly separated.

The browser edition must not become a pile of mixed Tauri, web, helper, and worker code. The first implementation goal is product clarity, not just feature parity.

## Product Split

There will be three related but separate deliverables:

1. Windows Desktop App.
2. Static Browser App.
3. Local Helper.

The Windows Desktop App remains the current high-completeness Windows experience.

The Static Browser App is the universal UI entry. It can run in browser-only mode and can connect to the helper for full local capabilities.

The Local Helper is a small native service for Windows, macOS, and Linux. It gives the browser app controlled access to local files, FFmpeg, APKG export, worker execution, and Anki verification.

## Phase 0: Documentation And Guardrails

Deliver:

- `docs/web-helper/README.md`.
- `docs/web-helper/REPOSITORY_BOUNDARIES.md`.
- `docs/web-helper/LOCAL_HELPER_API.md`.
- `docs/web-helper/IMPLEMENTATION_PLAN.md`.
- `docs/web-helper/ACCEPTANCE_CHECKLIST.md`.
- `docs/GOAL_WEB_STATIC_APP_LOCAL_HELPER.md`.

Acceptance:

- Documents clearly state the folder split.
- Documents explain browser-only mode versus helper mode.
- Documents include GitHub README/release explanation requirements.
- The goal file has a direct path to the plan documents.

## Phase 1: Repository Skeleton

Create folders:

```text
apps/windows-desktop/
apps/web-static/
apps/local-helper/
packages/shared-contracts/
packages/shared-card-logic/
```

Do not move all existing code yet.

Add README files:

```text
apps/windows-desktop/README.md
apps/web-static/README.md
apps/local-helper/README.md
packages/shared-contracts/README.md
packages/shared-card-logic/README.md
```

Acceptance:

- A new contributor can identify which product lives where.
- Root README links to each product folder.
- No browser app code is placed under the desktop app folder.
- No helper daemon code is placed under the browser app folder.

## Phase 2: Shared Contracts

Extract or recreate pure contracts:

- Runtime capabilities.
- Source input references.
- Learning point payloads.
- Card generation payloads.
- Export job status.
- Error codes.

These contracts should be plain TypeScript first. If helper is Rust, mirror the contract in Rust with generated or manually aligned schemas.

Acceptance:

- Browser app and helper can agree on `/health`, `/capabilities`, and job status types.
- Contract tests verify sample payloads.
- No platform imports exist in shared contracts.

## Phase 3: Static Web App POC

Build a static React/Vite app under `apps/web-static`.

Minimum UI:

- Product shell clearly labeled Browser App.
- Helper connection status.
- Browser-only mode badge.
- Settings page for model provider, Base URL, model, and API key.
- Source input page for subtitle and video link placeholders.
- Review placeholder page.
- Export placeholder page.

Runtime:

- `BrowserRuntime`.
- `HelperRuntime`.
- Runtime selector that attempts `GET http://127.0.0.1:17321/health`.

Acceptance:

- `npm run dev:web` starts only the web app.
- `npm run build:web` produces static assets.
- When helper is absent, UI enters browser-only mode.
- When a fake helper responds to `/health`, UI enters helper mode.

## Phase 4: Local Helper POC

Build helper under `apps/local-helper`.

Recommended implementation: Rust with a small HTTP server.

Minimum endpoints:

```text
GET /health
GET /capabilities
POST /auth/pair
GET /jobs/:id
GET /jobs/:id/events
```

For POC, pairing can be development-only, but production must require real local approval.

Acceptance:

- Helper starts on `127.0.0.1:17321`.
- Browser app detects helper.
- `/health` returns version, platform, and capabilities.
- Helper exits cleanly.
- Logs do not include secrets.

## Phase 5: Single-Source APKG Flow

Implement one complete flow:

1. User opens web app.
2. Web app detects helper.
3. User selects one local video and one SRT.
4. Helper creates file refs.
5. User configures learning settings.
6. Helper or model layer extracts learning points.
7. User reviews cards.
8. Helper generates APKG.
9. Browser downloads APKG.

Acceptance:

- One small test asset produces a valid APKG.
- APKG imports into Anki manually.
- No API key appears in logs, screenshots, or exported diagnostics.

## Phase 6: Browser-Only Fallback

Implement a useful mode without helper.

Allowed:

- Manual file upload.
- SRT/VTT parsing.
- Browser local settings.
- Model API calls when CORS allows them.
- Card review.
- Download JSON/CSV/APKG if JS export is implemented.

Not required in browser-only MVP:

- Folder scanning.
- Local FFmpeg.
- Native Anki verify.
- Arbitrary local paths.

Acceptance:

- Web app remains useful without helper.
- UI explicitly explains which features need helper.
- No confusing "broken desktop feature" states appear in browser-only mode.

## Phase 7: Cross-Platform Helper Packaging

Package helper separately:

- Windows: MSI or EXE.
- macOS: DMG or PKG with signing/notarization plan.
- Linux: AppImage first, then DEB/RPM later.

Acceptance:

- Each asset name clearly says helper and platform.
- Release notes explain helper is for the browser app, not the Windows desktop app.
- SHA256SUMS includes all helper assets.

## Phase 8: GitHub Documentation

Update root README:

- Choose Your Product.
- Windows desktop quick start.
- Browser app quick start.
- Local helper installation.
- Feature comparison table.
- Privacy and API key handling.

Add product READMEs:

- `apps/windows-desktop/README.md`.
- `apps/web-static/README.md`.
- `apps/local-helper/README.md`.

Acceptance:

- A user can tell which asset to download within 30 seconds.
- A developer can tell which folder to edit within 30 seconds.
- Browser app limitations are stated plainly.
- Helper security model is documented.

## Phase 9: Full Regression

Tests:

- Web unit tests.
- Helper API tests.
- Shared contract tests.
- Browser-only Playwright smoke.
- Helper-mode Playwright smoke.
- Windows desktop regression smoke.
- Secret scan.
- Release asset SHA verification.

Acceptance:

- Browser-only MVP passes.
- Helper-mode MVP passes on Windows first.
- Windows desktop app still builds and launches.
- No public docs expose API keys, local private paths, or internal test evidence.

