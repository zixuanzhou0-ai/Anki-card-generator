# Next Session Handoff

Use this file when opening a fresh Codex / GPT review window for the Anki Card Generator project.

## Current Repository State

- Local repo: `E:\ANKI`
- GitHub repo: `zixuanzhou0-ai/Anki-card-generator`
- Active branch: `codex/complete-refactor-hardening`
- Active PR: https://github.com/zixuanzhou0-ai/Anki-card-generator/pull/6
- PR base: `main`
- Current status when this handoff was written: PR #6 contains the document-study split plus local-video, API-key persistence, TTS export, Qwen3 TTS voice hardening, Gemini Vertex TTS setup, the Deep Study / contextual vocabulary pipeline, the default `沉浸复读 V12` Anki template for video/subtitle cards, strict learning-point validation, English IPA / connected-speech fields, TTS media ledger export, and candidate-review hardening from GPT Pro feedback.
- Latest local state on 2026-06-02: a follow-up hardening pass is present in the working tree unless the previous window has committed it. Run `git status --short --branch` first. Expected modified files are `workers/acg/legacy_worker.py`, `workers/acg/phrases/lexicon.py`, `tests/test_worker_quality.py`, `docs/HANDOFF_FOR_NEXT_CHAT.md`, `docs/TROUBLESHOOTING.md`, and `docs/RELEASE_NOTES_v0.9.2-beta.md`.

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
- Candidate review is no longer worded as MIMO-only; OpenAI-compatible providers such as DeepSeek V4 and Qwen / DashScope can run the same AI candidate review path.
- DeepSeek V4 Pro / Flash presets were added with official model IDs `deepseek-v4-pro` and `deepseek-v4-flash`. The worker now treats DeepSeek V4 as a thinking model: streaming `reasoning_content` keeps progress alive while final JSON parsing ignores thinking text.
- Gemini Vertex TTS is documented and available through the Vertex / `gcloud` auth path. It uses local `gcloud auth print-access-token` rather than storing a TTS API key.
- V10 APKG visual templates are now split by export family: video/subtitle language cards, document knowledge cards, and document reading cards use different front/back HTML while keeping the existing field names. The templates no longer rely on JS overflow fitting and allow stable vertical scrolling.
- Video/subtitle language cards now default to `immersive_v11` / `沉浸复读 V12`: front side is shadowing-first with click-to-play video and custom `原声` / `慢读` buttons; back side shows core expression, Chinese intuition, standard IPA, spoken IPA, source-sentence listening notes, phrase TTS, compact replay video, and explanation blocks. `immersive` remains as the old V10 fallback option.
- GPT Pro review follow-up added hard gates to the AI candidate-review merge path:
  - `exact_span` must be recoverable from the original sentence.
  - `answer_core` must be a clean English answer, not mixed Chinese/IPA/explanation text.
  - pronunciation, connected speech, non-standard forms, and IPA live in `phonetic_ipa`, `spoken_ipa`, `source_spoken_ipa`, `pronunciation_note`, or teacher notes.
  - same-sentence expression / vocabulary / grammar / listening / pragmatic learning points can coexist after grouped dedupe; low-value points become review/reject instead of being hard-capped to two.
  - AI-rejected candidates are not revived by the local minimum-count fallback.
  - export results now carry `template_version` / `anki_tag`, and Anki import verification uses the actual V10/V12 tag.
- TTS/media hardening now writes `media_ledger` alongside `media_manifest`. Sentence TTS filenames include a source-text hash, phrase TTS filenames include the visible answer hash, and Anki import verification checks ledger/manifests for missing files and text-hash mismatches.
- Local projects now store `video_fingerprint` and `subtitle_fingerprint` in `source_info`, in addition to source-mode path isolation. Local mode clears stale URL/document paths; URL/document modes clear unrelated local paths before worker calls.
- README, user guide, troubleshooting, release notes, release checklist, beta limitations, handoff, screenshots, PR body, and repo About description were refreshed after this hardening pass.
- User later tested a V11 APKG export and saw two concrete issues:
  - Phrase TTS warning: `seg_0147` / `seg_0173` failed because Gemini Vertex TTS returned no `inlineData` audio for a few phrase-level requests while sentence TTS and most phrase TTS files succeeded. This points to partial provider/voice/model/region behavior, not a fully broken TTS setup.
  - Some card backs only showed the original sentence plus media. APKG inspection showed those notes had sparse fields: `Answer`, `English`, `Phrase`, `Example`, `Difficulty`, and `SourceTime`, but no usable `Chinese`, `Definition`, `Context`, `Why`, or `TeacherNote`.
- Local follow-up fix added after that test:
  - `TEMPLATE_NOISE_PATTERNS` now catches placeholder export text such as `本地待审`, `待精修`, `正式导出前`, `本句目标表达`, and `use ... in a complete sentence`.
  - AI phrase/cloze cards must have specific meaning, usage, and guidance before they can be recommended; otherwise quality includes `AI 解释字段不足` and the card remains disabled/review-only.
  - `normalize_learning_action_fields()` now backfills the newer action fields from specific legacy fields, so older valid AI card payloads are not wrongly rejected.
  - Added `test_sparse_ai_phrase_card_is_not_recommended`.
- Vertex setup follow-up on 2026-06-03:
  - Local `gcloud config get-value core/project` and `gcloud auth print-access-token` both worked.
  - Real worker `handle_test_api` calls succeeded for `gemini-3.1-pro-preview`, `gemini-2.5-pro`, and `gemini-2.5-flash`.
  - `gemini-3.1-pro` returned Vertex 404 in the current project, so the app now removes it from the suggested Vertex model list and normalizes saved `gemini-3.1-pro` settings to `gemini-3.1-pro-preview` before worker requests.
  - Real Vertex TTS tests succeeded for `gemini-3.1-flash-tts-preview`, `gemini-2.5-flash-tts`, and `gemini-2.5-pro-tts` with voice `Kore`.

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

Latest targeted checks for candidate-review hardening, V12 pronunciation fields, TTS ledger, and docs refresh:

```powershell
python -m unittest tests.test_worker_quality
npm run build
npm run test:ui
git diff --check
```

Latest checks for this handoff update:

```powershell
python -m unittest tests.test_worker_quality
npm run test:unit
npm run build
```

Latest checks for the sparse-card / phrase-TTS documentation follow-up:

```powershell
python -m unittest tests.test_worker_quality.WorkerQualityTests.test_sparse_ai_phrase_card_is_not_recommended tests.test_worker_quality.WorkerQualityTests.test_merge_ai_cards_preserves_multiple_same_type_learning_points
python -m unittest tests.test_worker_quality
python -m py_compile workers\acg\legacy_worker.py workers\acg\phrases\lexicon.py
```

Latest checks for Vertex settings repair:

```powershell
npm run test:unit -- src/services/apiConfig.test.ts src/features/settings/ApiSettingsPanel.test.tsx
python -m unittest tests.test_worker_quality.WorkerQualityTests.test_gemini_vertex_generate_content_uses_gcloud_auth_and_global_endpoint tests.test_worker_quality.WorkerQualityTests.test_gemini_vertex_model_alias_falls_back_to_preview
python -m py_compile workers\acg\legacy_worker.py
# Real local check: worker.handle_test_api with model gemini-3.1-pro reports and uses gemini-3.1-pro-preview successfully.
```

## Current Product Decisions

- Keep the two-pane layout: left Inspector, right Workspace. Do not restore the old left Rail.
- Keep document input independent from video-language learning.
- Default document mode is knowledge absorption.
- Language reading is opt-in under document input.
- For Qwen3 TTS English cards, prefer `Jennifer` or `Aiden`; `Cherry` remains available but is no longer the default.
- Use one responsive Anki template family rather than asking the user to choose desktop/mobile templates. The current default for video cards is `沉浸复读 V12`.
- Do not create isolated dictionary vocabulary cards. Vocabulary cards must be contextual `语境生词卡` tied to an original sentence and scene.
- Keep Deep Study on by default for model-backed generation, but allow `快速生成` for quick workflow checks.
- Do not add OCR, RAG, more providers, more templates, or multi-platform packaging until the beta core is steadier.
- Do not change APKG field names casually; compatibility still matters.

## Known Remaining Work

The next iteration should focus on the strongest remaining beta gaps:

1. If the sparse-card fix is still uncommitted, review, commit, and push it after any additional validation.
2. Restart/rebuild the latest desktop app before user testing. The user's last APKG was still `Anki Card Generator V11 - 沉浸复读 V11`, so do not diagnose V12 behavior from that old export.
3. Run a real local video + SRT Deep Study generation using Qwen / DashScope / Gemini Vertex and inspect whether sparse AI cards are now disabled/review-only and whether phrase TTS warnings identify the exact failed expressions.
4. Continue visually tuning the V12 Anki template with real Anki desktop/mobile screenshots, especially long expressions and IPA rows.
5. Add a real document generate + export + APKG verify smoke test.
6. Add packaged portable zip smoke to catch release resource issues.
7. Improve pending-review indicators and mobile screenshots for the split Anki templates.
8. Continue simplifying the left Inspector with large sections and drawers.
9. Continue checking whether the lowered `1180 x 780` minimum window is sufficient across common Windows scaling settings.
10. Continue extracting `workers/acg/legacy_worker.py` into real document, LLM, media, TTS, and Anki modules.

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
- AI candidate review now has strict `exact_span` / `answer_core` validation, same-sentence grouped learning points, and English pronunciation fields for V12 cards.
- Sparse AI expression/cloze cards should not become recommended cards; look for the `AI 解释字段不足` quality issue if a card has only the original sentence and media.
- Document input = knowledge absorption by default.
- Document input has optional language_reading mode.
- Two-pane desktop layout stays; do not restore the left Rail.

Next likely work:
1. Check whether the latest sparse-card hardening is committed/pushed. Start with `git status --short --branch`.
2. Rebuild/restart the latest desktop app before testing; the last user APKG was still V11.
3. Real Deep Study local-video generation QA with Qwen / DashScope / Gemini Vertex and APKG import.
4. Confirm sparse AI cards are disabled/review-only and phrase-TTS partial failures are clearly reported.
5. Continue visual QA on the split language / knowledge / document-reading Anki templates.
6. Add document generate/export/APKG verify smoke.
7. Improve pending-review cues and mobile screenshots for the Anki templates.
8. Prepare public-beta release reliability.

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
- README / GitHub PR body / repository About description freshness
- candidate-review hard gates: exact_span, answer_core, grouped same-sentence learning points, no revival of AI rejects
- English IPA / connected-speech fields in V12 language cards
- TTS media ledger and import verification consistency

Please identify any remaining inconsistency between source code, tests, documentation, screenshots, and release behavior.
Return P0/P1/P2 issues with file paths and concrete fixes.
```
