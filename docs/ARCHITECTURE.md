# Architecture

This document describes the `v0.9.2-beta` desktop architecture at the level needed for maintenance and release checks.

## Product Pipelines

```mermaid
flowchart TB
  A["URL / local video + SRT"] --> B["Subtitle parsing and segment building"]
  B --> C["Deep Study material_context"]
  C --> D["Language candidate mining"]
  D --> E["AI candidate review"]
  E --> F["Language card field generation"]
  F --> O["Media slicing and optional TTS"]

  G["Document"] --> H{"Document study mode"}
  H --> I["knowledge: concepts, arguments, terms, examples"]
  H --> J["language_reading: expressions, vocabulary, grammar"]
  I --> K["Knowledge QA cards"]
  J --> L["Document reading review cards"]

  O --> M["APKG packaging"]
  K --> M
  L --> M
  M --> N["APKG verification and Anki import"]
```

## Frontend

The React app uses a two-pane desktop layout:

- Left Inspector: source input, source-specific study settings, card/template preferences, and readiness summaries.
- Right Workspace: empty/ready/running/review/exported states, quality summary, segment list, card editor, and export result.

The top-level entry is intentionally thin:

- `src/App.tsx` mounts the app.
- `src/app/useAppController.ts` owns request/project/job state and user actions.
- `src/app/AppShell.tsx` renders the desktop shell.
- `src/domain/*` stores types, options, defaults, providers, selectors, and worker error mapping.
- `src/services/*` wraps Tauri worker jobs, secret storage, project storage, and media helpers.

Complex settings should stay collapsed in the Inspector, but every collapsed section must keep a useful summary such as source type, API status, TTS mode, or segment budget.

Document mode is intentionally separated from the video language-learning controls:

- `knowledge` is the default path and hides CEFR levels, listening cards, phrase cards, and language content toggles.
- `language_reading` is opt-in and only exposes document reading settings for expressions, vocabulary, and grammar. It does not generate listening cards because documents do not have source audio.
- The frontend persists document study fields on both `GenerateRequest` and `Project`, and old stored requests fall back to knowledge defaults.

Video and URL language learning now have a material-understanding layer:

- `study_depth` is stored on `GenerateRequest` and `Project`; the default is `deep`.
- In deep mode, the worker builds a hidden `material_context` before candidate review. It captures the material summary, scene or argument flow, tone, key points, and learning opportunities.
- Candidate review and card-generation prompts receive `material_context`, so DeepSeek V4, Qwen / DashScope, MIMO, and other OpenAI-compatible models can use reasoning/thinking to judge context before writing cards. For DeepSeek V4 / Qwen / MIMO, worker calls stream `reasoning_content` / thinking deltas for progress updates and parse only the final JSON content.
- `language_focus` defaults to `phrases + vocabulary + listening`. `vocabulary` produces contextual vocabulary cards through `phrase_type: "vocabulary_usage"` and the exported card label `语境生词卡`; it does not create isolated dictionary cards.
- The review merge path is intentionally stricter than the prompt. `exact_span` must be recoverable from the source sentence, `answer_core` must be a clean English learning object instead of mixed Chinese / IPA / grammar explanation text, and different learning-point kinds can coexist in the same source sentence after grouped dedupe. AI-rejected candidates are not revived by the local minimum-count fallback.
- APKG field names stay compatible, but video/subtitle language cards now add V12 pronunciation fields: `PhoneticIpa`, `SpokenIpa`, `SourceSpokenIpa`, `PronunciationNote`, and `PronunciationConfidence`. New identity is stored in project/card metadata such as `study_depth`, `material_context`, `phrase_type`, `content_kind`, `source_evidence`, `learning_point_id`, and validation status fields.
- APKG export now splits visual note-model families by `deck_kind` and template version. Video/subtitle language cards default to `immersive_v11` (`沉浸复读 V12`): the front is a click-to-play shadowing surface with custom `原声` / `慢读` buttons, and the back prioritizes core expression, Chinese intuition, IPA / connected-speech notes, source sentence, phrase TTS, and compact explanation blocks. `document_knowledge` keeps a knowledge-answer layout, and `document_reading` keeps a reading layout. The generated model id includes the template family/version to avoid mixing different front/back HTML under one Anki note model. Export results carry `template_version`, `anki_tag`, `media_manifest`, and `media_ledger`, so import verification checks the actual package tag plus media/TTS ledger consistency.

## Tauri Boundary

The Rust backend is the trusted local boundary between the WebView and Python worker.

- Worker commands are whitelisted.
- Long-running generate/export work uses job IDs and emits progress/finished events.
- `open_anki_import` only accepts `.apkg` files.
- `reveal_path` is restricted to app/project/release output locations.
- Secret persistence goes through the Tauri backend and Windows Credential Manager when the user explicitly enables remembering a key.

## Worker

`workers/anki_worker.py` is now a small command router. The legacy implementation remains in `workers/acg/legacy_worker.py` while command boundaries are being extracted. New shared protocol helpers live under `workers/acg/`.

Current command modules:

- `workers/acg/commands/check_env.py`
- `workers/acg/commands/generate.py`
- `workers/acg/commands/export.py`
- `workers/acg/commands/test_api.py`
- `workers/acg/commands/test_tts.py`
- `workers/acg/commands/verify.py`

The worker response protocol is backward-compatible and can add:

- `schema_version`
- `warnings`
- `error_code`
- `stage`
- `retryable`
- `fallbacks`

Do not change APKG field names or Anki template field compatibility without a migration note.

## Release Gates

Local full gate:

```powershell
npm run check:full
npm run tauri:build
```

Release package gate:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/package_portable.ps1 -ReleaseExe "src-tauri/target/release/anki-card-generator.exe"
powershell -ExecutionPolicy Bypass -File scripts/smoke_portable.ps1 -PortableZip "release/AnkiCardGenerator-v0.9.2-beta-windows-portable.zip"
```

CI runs frontend build, lint, unit tests, UI smoke, Rust build, worker tests, version checks, and the release smoke test on Windows.
