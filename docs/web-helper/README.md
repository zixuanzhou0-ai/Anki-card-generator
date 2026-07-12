# Browser App + Local Helper Plan

This folder is the planning hub for the cross-platform browser edition of Anki Card Generator.

The main product rule is separation first:

- The existing Windows desktop app remains a Windows desktop product.
- The browser app is a separate product surface.
- The local helper is a separate native service used by the browser app.
- Shared contracts and pure domain logic may live in a shared package, but UI shells and platform code must not be mixed.

## Document Map

- [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) describes the full staged implementation plan.
- [REPOSITORY_BOUNDARIES.md](REPOSITORY_BOUNDARIES.md) defines the required folder split, public GitHub explanation, and no-mess rules.
- [LOCAL_HELPER_API.md](LOCAL_HELPER_API.md) defines the helper protocol, security model, API shape, and job lifecycle.
- [ACCEPTANCE_CHECKLIST.md](ACCEPTANCE_CHECKLIST.md) defines the final validation gates for browser-only mode, helper mode, and GitHub release clarity.

## Target Repository Shape

The final repository should make the product split obvious before a user reads any source code:

```text
apps/
  windows-desktop/
    README.md
    src/
    src-tauri/
    workers/
  web-static/
    README.md
    src/
    public/
  local-helper/
    README.md
    src/
    installers/
packages/
  shared-contracts/
  shared-card-logic/
docs/
  web-helper/
```

The current repository does not yet have this shape. The migration must happen deliberately, with tests after each move, instead of dumping the browser app into the current root.

## Product Modes

The browser edition has two modes.

Browser-only mode works without installation:

- User opens the static web app.
- User manually provides files through browser file pickers.
- API settings are stored locally in the browser.
- The app can parse subtitles, call compatible model APIs when CORS allows it, review cards, and download exports.

Helper mode unlocks desktop-grade capability:

- User installs a small local helper for Windows, macOS, or Linux.
- The web app connects to `http://127.0.0.1:17321`.
- The helper handles local files, FFmpeg, worker execution, APKG export, cache, logs, and optional Anki verification.

The same browser UI may support both modes, but the runtime layer must make the difference explicit.

