# Next Session Handoff

Use this file when opening a fresh Codex / GPT review window for the Anki Card Generator project.

## Current Repository State

- Local repo: `E:\ANKI`
- GitHub repo: `zixuanzhou0-ai/Anki-card-generator`
- Active branch: `codex/complete-refactor-hardening`
- Active PR: https://github.com/zixuanzhou0-ai/Anki-card-generator/pull/6
- PR base: `main`
- Current status when this handoff was written: PR #6 contains the document-study split plus local-video, API-key persistence, TTS export, Qwen3 TTS voice hardening, and the first Deep Study / contextual vocabulary card pipeline. Local working tree should be clean after pushing the latest commit.

Important: ask reviewers to inspect PR #6, not only `main`. The latest document-study work is on the PR branch.

## What PR #6 Contains

PR #6 adds the first complete document-study split:

- Document input now defaults to `knowledge` / knowledge absorption.
- Document input can opt into `language_reading` / language reading.
- Document knowledge mode hides video-language controls such as CEFR level, listening cards, phrase-card toggles, and language content toggles.
- Language reading mode exposes document expression / vocabulary / grammar settings and does not generate listening cards.
- New document study fields are carried through request defaults, project data, localStorage migration, demo data, UI, worker payloads, and worker project output.
- Worker document prompts now distinguish knowledge absorption from language reading.
- Language-reading document cards default to review instead of being treated as high-confidence export cards.
- README, architecture docs, user guide, release notes, and screenshots were refreshed to explain the two learning paths.

Recent hardening added after the initial document-study split:

- Local video + SRT generation/export was tested end to end with real model API, real TTS, APKG verification, and Anki import.
- TTS export now uses the resolved TTS configuration, so saved/reused provider keys are honored during APKG export.
- API keys can be remembered locally through Windows Credential Manager or a DPAPI-encrypted local fallback when keyring is unavailable.
- Qwen3 TTS defaults were changed from `Cherry` to `Jennifer` for English cards; `Aiden` is available as the American English male preset, and the Qwen3 voice-design model entry is exposed for advanced custom voices.
- Deep Study is now represented by `study_depth` on requests/projects. The default is `deep`; the UI also exposes `快速生成`.
- The worker now builds and stores a hidden `material_context` before candidate review/card writing, so thinking models can use whole-material context before producing cards.
- `language_focus` now defaults to `phrases + vocabulary + listening`. `vocabulary_usage` exports as `语境生词卡` while keeping V10 APKG fields compatible.
- Candidate review is no longer worded as MIMO-only; OpenAI-compatible providers such as Qwen / DashScope can run the same AI candidate review path.
- V10 APKG visual templates are now split by export family: video/subtitle language cards, document knowledge cards, and document reading cards use different front/back HTML while keeping the existing field names. The templates no longer rely on JS overflow fitting and allow stable vertical scrolling.

## Key Files

Frontend domain and defaults:

- `src/domain/types.ts`
- `src/domain/defaults.ts`
- `src/domain/documentStudy.ts`
- `src/domain/documentFocus.ts`
- `src/domain/learningFocus.ts`
- `src/domain/studyDepth.ts`
- `src/domain/options.ts`
- `src/domain/demoProject.ts`
- `src/domain/ttsProviders.ts`

Frontend UI:

- `src/features/settings/TtsSettingsPanel.tsx`
- `src/features/learning/DocumentStudyPanel.tsx`
- `src/features/app/InspectorPanel.tsx`
- `src/features/source/SourceSetupPanel.tsx`
- `src/features/generation/CardTemplatePanel.tsx`
- `src/features/review/SegmentList.tsx`
- `src/features/review/SegmentDetail.tsx`
- `src/features/review/ReviewSummaryPanel.tsx`

Storage and tests:

- `src/services/apiConfig.ts`
- `src/services/apiConfig.test.ts`
- `src/services/projectStorage.ts`
- `src/services/projectStorage.test.ts`
- `src/features/settings/TtsSettingsPanel.test.tsx`
- `src/features/learning/DocumentStudyPanel.test.tsx`
- `src/features/app/InspectorPanel.test.tsx`
- `tests/ui-smoke.spec.ts`

Worker:

- `workers/acg/legacy_worker.py`
- `tests/test_worker_quality.py`

Docs and screenshots:

- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/USER_GUIDE.md`
- `docs/BETA_LIMITATIONS.md`
- `docs/TROUBLESHOOTING.md`
- `docs/RELEASE_NOTES_v0.9.2-beta.md`
- `docs/screenshots/document-knowledge-review.png`
- `docs/screenshots/settings-modal.png`

## Verified Commands

These commands passed before pushing PR #6:

```powershell
git diff --check
npm run check
npm run test:ui
```

`npm run check` includes:

```powershell
npm run check:versions
npm run lint
npm run test:unit
npm run build
npm run test:worker
```

Also run before commit:

```powershell
# Changed-file scan for API-key-like strings
sk-..., tp-..., AIza..., Bearer ...
```

No API-key-like secrets were found in changed files.

Latest targeted checks for TTS hardening:

```powershell
npm run test:unit -- src/features/settings/TtsSettingsPanel.test.tsx src/services/apiConfig.test.ts
python -m pytest tests/test_worker_quality.py -k qwen_tts_audio -q
npm run build
```

Latest targeted checks for Deep Study / contextual vocabulary:

```powershell
python -m py_compile workers\acg\legacy_worker.py
npm run test:unit -- src/features/learning/LearningSettingsPanel.test.tsx src/features/review/ReviewSummaryPanel.test.tsx src/features/review/SegmentDetail.test.tsx src/domain/demoProject.test.ts src/services/projectStorage.test.ts
python -m pytest tests/test_worker_quality.py -q
```

## Current Product Decisions

- Keep the two-pane layout: left Inspector, right Workspace. Do not restore the old left Rail.
- Keep document input independent from video-language learning.
- Default document mode is knowledge absorption.
- Language reading is opt-in under document input.
- For Qwen3 TTS English cards, prefer `Jennifer` or `Aiden`; `Cherry` remains available but is no longer the default.
- Use one responsive Anki template family rather than asking the user to choose desktop/mobile templates.
- Do not create isolated dictionary vocabulary cards. Vocabulary cards must be contextual `语境生词卡` tied to an original sentence and scene.
- Keep Deep Study on by default for model-backed generation, but allow `快速生成` for quick workflow checks.
- Do not add OCR, RAG, more providers, more templates, or multi-platform packaging until the beta core is steadier.
- Do not change APKG field names casually; compatibility still matters.

## Known Remaining Work

The next iteration should focus on the strongest remaining beta gaps:

1. Run a real local video + SRT Deep Study generation using Qwen / DashScope and inspect whether `material_context` improves selected cards.
2. Continue visually tuning the split Anki template families with real Anki desktop/mobile screenshots.
3. Add a real document generate + export + APKG verify smoke test.
4. Add packaged portable zip smoke to catch release resource issues.
5. Improve pending-review indicators and mobile screenshots for the split Anki templates.
6. Continue simplifying the left Inspector with large sections and drawers.
7. Continue checking whether the lowered `1180 x 780` minimum window is sufficient across common Windows scaling settings.
8. Continue extracting `workers/acg/legacy_worker.py` into real document, LLM, media, TTS, and Anki modules.

## Prompt For A Fresh Codex Window

Paste this into a new Codex window:

```text
We are continuing the Anki Card Generator project.

Repo: E:\ANKI
GitHub PR to inspect: https://github.com/zixuanzhou0-ai/Anki-card-generator/pull/6
Branch: codex/complete-refactor-hardening

Please read docs/HANDOFF_FOR_NEXT_CHAT.md first, then inspect PR #6 and the local repository.

Current shipped direction:
- Video / URL = English context learning.
- Video / URL now use Deep Study by default: understand material -> review candidates -> write cards.
- Contextual vocabulary cards are in scope and labeled `语境生词卡`.
- Document input = knowledge absorption by default.
- Document input has optional language_reading mode.
- Two-pane desktop layout stays; do not restore the left Rail.

Next likely work:
1. Real Deep Study local-video generation QA with Qwen / DashScope and APKG import.
2. Continue visual QA on the split language / knowledge / document-reading Anki templates.
3. Add document generate/export/APKG verify smoke.
4. Improve pending-review cues and mobile screenshots for the Anki templates.
5. Prepare public-beta release reliability.

Before editing, run:
git status --short --branch

When implementing, keep APKG compatibility in mind, do not commit secrets, and run the relevant tests before reporting completion.
```

## Prompt For GPT 5.5 Pro Review

Use this if asking GPT 5.5 Pro for another review:

```text
Please review PR #6, not just main:
https://github.com/zixuanzhou0-ai/Anki-card-generator/pull/6

Focus on whether the document input path is now genuinely independent from video-language learning:
- Deep Study material_context data flow
- contextual vocabulary cards and labels
- Qwen / DashScope candidate review behavior
- document study types and defaults
- DocumentStudyPanel UI behavior
- localStorage migration
- worker knowledge vs language_reading prompts
- document card review/default export behavior
- README / ARCHITECTURE / USER_GUIDE consistency
- screenshot freshness

Please identify any remaining inconsistency between source code, tests, documentation, screenshots, and release behavior.
Return P0/P1/P2 issues with file paths and concrete fixes.
```
