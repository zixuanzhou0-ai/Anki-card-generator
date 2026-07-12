# GOAL: Cross-Platform Browser App With Local Helper

## Primary Objective

Build a cleanly separated cross-platform browser edition of Anki Card Generator, backed by an optional Local Helper, without turning the existing Windows desktop repository into another mixed-code mess.

The browser app and the Windows desktop app must be treated as two different product surfaces. They may share contracts, card logic, and selected pure utilities, but they must not share the same app folder, must not hide platform differences behind unclear code, and must not confuse users on GitHub about what to download or how to run the project.

The detailed execution plan lives at:

`E:\ANKI\docs\web-helper\README.md`

Read these documents before coding:

- `E:\ANKI\docs\web-helper\IMPLEMENTATION_PLAN.md`
- `E:\ANKI\docs\web-helper\REPOSITORY_BOUNDARIES.md`
- `E:\ANKI\docs\web-helper\LOCAL_HELPER_API.md`
- `E:\ANKI\docs\web-helper\ACCEPTANCE_CHECKLIST.md`

This goal should be pursued in loops until the browser app, helper, documentation, tests, and GitHub release experience are all complete.

## Why This Exists

The current Windows desktop application is useful because Tauri gives the React UI a native backend. It can call local workers, use FFmpeg, write files, export APKG packages, and verify Anki behavior on the user machine. A pure static webpage cannot automatically do all of that because normal browsers are sandboxed. The right product direction is not to pretend the browser has no limits, and not to rebuild the entire desktop app in a fragile single-page frontend. The right direction is to create a web app that can run in two modes: browser-only mode for lightweight cross-platform usage, and helper mode for desktop-grade local operations.

The final user experience should feel simple. A user opens the browser app. If no helper is installed, the app still works for basic subtitle and card workflows and clearly explains which features need the helper. If the helper is installed, the app connects to `http://127.0.0.1:17321`, confirms that the local service is healthy, and unlocks local files, FFmpeg, worker execution, APKG export, and optional Anki verification. From the user point of view, this can feel very close to the desktop product. From the engineering point of view, the architecture must be explicit and safe.

## Non-Negotiable Repository Rule

Do not put the browser application into the existing desktop source tree. Do not add helper service code into random Tauri files. Do not keep all product variants in one root `src` folder. This is exactly how the project becomes unreadable.

The target structure is:

```text
apps/
  windows-desktop/
  web-static/
  local-helper/
packages/
  shared-contracts/
  shared-card-logic/
docs/
  web-helper/
```

The repository may migrate toward this structure gradually, but every step must preserve clarity. If moving the existing Windows desktop code is too risky in the first loop, create the new folders and documentation first, then move the desktop product in a later controlled phase with tests. Never perform a giant blind move. Never rely on `git add .`. Use whitelist staging and inspect staged diffs.

## Product Definitions

The Windows Desktop App is the current Tauri product. It is for Windows users who want the most complete local workflow. It owns its desktop packaging, Tauri configuration, Windows-specific launch behavior, worker bridge, desktop screenshots, and release assets.

The Browser Web App is a static web application. It should be deployable to GitHub Pages, Cloudflare Pages, or another static host. It owns the browser UI, browser settings storage, helper connection status, browser-only runtime, helper runtime client, and cross-platform user guidance.

The Local Helper is a native service installed on the user's machine. It owns the local loopback API, pairing, file and folder picker bridge, FFmpeg execution, worker execution, APKG export, Anki verification, local logs, and platform installers. It is not a public cloud backend. It must run only on the user's computer.

Shared packages are allowed only for pure contracts and pure logic. Shared packages must not import Tauri APIs, browser DOM APIs, Node-only APIs, or OS-specific file APIs unless that package is explicitly platform scoped. The purpose of shared packages is to reduce duplication while keeping product boundaries obvious.

## Required Browser App Behavior

The browser app must start in a clear runtime state. It should check for a helper at `http://127.0.0.1:17321/health`. If the helper is reachable, the UI enters helper mode after the required security checks. If the helper is missing, blocked, outdated, or unpaired, the UI enters browser-only mode and explains what is available.

Browser-only mode should be useful, not a dead demo. It should support local settings, manual file uploads, SRT/VTT parsing, source preview, card review, and export options that are practical in a browser. If direct model calls are blocked by CORS, the UI must explain the issue clearly and offer helper mode or provider-specific guidance. It must never silently fail or pretend that local FFmpeg, folder scanning, or Anki verify are available without a helper.

Helper mode should unlock the desktop-grade path. It should support local video and subtitle selection, source analysis, learning point extraction, card generation, APKG export, job progress, cancellation, logs, and optional Anki verify. Long-running tasks must be modeled as jobs. The web app must not freeze while a helper job runs. Progress should be visible, understandable, and recoverable.

## Required Local Helper Behavior

The helper must bind only to loopback. The default endpoint is `http://127.0.0.1:17321`. It must not listen on LAN interfaces. The first useful endpoint is `GET /health`, which returns helper version, platform, API version, pairing state, and capabilities.

The helper must implement a real security model before public release. Localhost is not automatically safe. Browser pages can attempt to call localhost services. Therefore, privileged helper operations require an origin allowlist, a pairing flow, and a local session token. The helper must accept only known origins in production. It must never expose a generic command execution endpoint. All operations must be typed: pick file, pick folder, analyze source, extract learning points, generate cards, export APKG, verify Anki, read sanitized diagnostics, cancel job.

File access must require user intent. Prefer native file and folder pickers controlled by the helper. Return opaque file references to the web app instead of handing the browser arbitrary path power. The helper may internally map file refs to paths for the active session. If persistent project access is implemented later, it needs explicit user approval and clear revocation.

Logs must be useful but safe. Private local logs can include enough detail for debugging, but any copied/exported diagnostics must redact API keys, bearer tokens, local session tokens, and private full paths when appropriate. Screenshots and release docs must be manually checked for secrets before publication.

## Required GitHub Experience

The GitHub repository must explain the product split before users get lost. The root README needs a "Choose Your Product" section. It must say: choose Windows Desktop App if you want the existing full Windows desktop workflow; choose Browser Web App if you want cross-platform browser access; install Local Helper if you want local files, FFmpeg, APKG parity, and Anki verify from the browser.

Each product folder needs its own README. `apps/windows-desktop/README.md` explains the desktop app. `apps/web-static/README.md` explains browser-only and helper mode. `apps/local-helper/README.md` explains installation, security, health check, and supported platforms.

Every release must label assets precisely. Users should not have to guess whether a file is the desktop app or helper. Example labels: Windows desktop installer, Windows browser helper, macOS browser helper, Linux browser helper, static web build. Release notes must include a "Which file should I download?" section. SHA256SUMS must include all published binary assets.

## Implementation Loops

Loop 1 is documentation and skeleton. Create the docs, create folder placeholders, add product READMEs, and update the root README with a clear product split. Do not move the desktop app yet unless there is enough time to validate the move.

Loop 2 is shared contracts and runtime abstraction. Define capability, file ref, folder ref, job, error, learning point, generation, export, and verify contracts. Add a browser runtime interface. Implement a fake helper runtime for tests.

Loop 3 is browser app POC. Create `apps/web-static`, build a small React/Vite static app, show helper status, browser-only mode, settings, source input, and a placeholder review/export flow. Add tests for helper absent and helper present.

Loop 4 is helper POC. Create `apps/local-helper`, implement `/health`, `/capabilities`, and development pairing. Start the helper locally and verify the web app detects it. Keep this minimal and secure.

Loop 5 is one real source-to-APKG flow. Use one small video/SRT or SRT-only test asset. Let the helper create file refs, run the card generation path, export APKG, and make the browser download it. Verify the APKG imports into Anki manually.

Loop 6 is browser-only fallback. Make the app genuinely useful without helper: manual upload, subtitle parsing, review, and at least one export route. Clearly label unavailable features.

Loop 7 is packaging. Build helper installers for Windows first, then macOS and Linux. Add SHA256SUMS. Add release docs and screenshots.

Loop 8 is public hardening. Run CI, E2E tests, secret scans, release asset scans, docs review, and GitHub README review. Make sure no internal evidence, APKG files, raw media, API keys, or local logs are committed.

## Acceptance Definition

This goal is complete only when all of these are true:

- The repository has clear product folders or a documented migration step with no mixed new browser code in the desktop tree.
- Browser web app can run in browser-only mode.
- Browser web app can detect helper mode.
- Local helper responds on loopback and exposes a safe `/health`.
- A helper-mode E2E can produce an APKG from a real small source.
- Root README explains Windows Desktop App, Browser Web App, and Local Helper.
- Each product folder has a README.
- GitHub release notes clearly label every asset.
- Secret scan passes.
- Windows desktop app still works.
- The final docs are understandable to a new user and a new contributor.

Do not mark this goal complete just because a prototype launches. Completion requires product clarity, safety, tests, documentation, and release usability.
