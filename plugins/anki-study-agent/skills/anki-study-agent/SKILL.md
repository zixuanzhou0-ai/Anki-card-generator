---
name: anki-study-agent
description: Use a registered local Anki Card Service to turn authorized text, Markdown, code, HTML, subtitle files, bounded directories, static HTTPS webpages, or YouTube subtitle snapshots into evidence-backed Anki cards. Use when Codex needs to inspect a supported source, authorize fixed Hermes Grok 4.5 candidate discovery, safely resume interrupted discovery, select language-learning candidates, generate validated text cards, export APKG, or explicitly import and data-verify a deck in Anki. Treat full video/audio acquisition, podcasts, PDF/Office parsing, media generation, export/import task resumption, and runtime rendering/playback/restart verification as unavailable unless the installed tool capability explicitly exposes them.
---

# Anki Study Agent

Create cards as verifiable memory-retrieval tasks, not saved summaries. Preserve source evidence, make each answer scoreable, minimize review debt, and distinguish generated, exported, imported, data-verified, and runtime-verified states.

## Check runtime capability

1. Inspect the available tools for `system.get_capabilities` and the `study.*`, `cards.*`, and `anki.*` namespaces.
2. Call `system.get_capabilities` before starting a workflow when it is available, and treat its exposed-tool list as authoritative.
3. When `system.list_profiles` is exposed, read the exact selected profile state. If an existing profile reports `CREDENTIAL_REQUIRED`, use `system.open_local_settings` to open the trusted local window and poll only its returned `configurationSessionRef`; never ask for or accept the credential in conversation. If the exact binding is unknown, stale, or failed and `system.validate_profile` is exposed, validate that fingerprint and credential revision. For model/TTS, route `confirmation_required` through `system.request_operation_confirmation`, poll the trusted local decision, then retry validation with the same idempotency key. Never treat conversation consent as the trusted decision or reuse this one-call diagnostic authorization for a learning task.
4. Call `system.revoke_grant` only when the user explicitly asks to view, manage, or revoke permissions. Open it with no target selector, let the user choose inside the trusted local window, then poll only its returned `authorizationSessionRef`. Never infer a target or claim that completed calls, reads, artifacts, or Anki writes were rolled back.
5. If the Card Service tools are unavailable, say that the local plugin runtime is not registered. Do not claim that an APKG, media file, import, or verification exists.
6. Stop at the last proven stage when a required tool is absent. Do not call a planned tool, reconstruct a hidden handle, or replace the Card Service with shell commands or direct provider calls.

## Build the learning contract

1. Infer the learner's desired future behavior, current level, review budget, language, evidence policy, and exclusions.
2. Ask only when different answers would materially change what should be learned, what may leave the device, or how much review debt will be created.
3. Otherwise choose conservative, reversible defaults and state them briefly.
4. Create the project and versioned learning contract before discovery. Never let a later model silently redefine the goal.
5. For an existing project, change those fields only through `study.update_learning_contract` with current project/contract revisions and the fixed semantic operation union. Treat its invalidation result as authoritative; never use JSON Patch or silently recreate the project.

Read [learning-contract.md](references/learning-contract.md) when selecting objectives, card routes, or a candidate portfolio.

## Run the workflow

1. Obtain only grants exposed by the current trusted local surface. Use local selection for files/directories and `system.request_network_grant` for a static webpage or YouTube subtitle source; the complete URL must be entered only in the trusted local window. Never pass raw local paths, URLs, credentials, cookies, signed queries, or unrestricted origins as model text or tool arguments.
2. Register inputs and inspect source integrity before discovery. Stop with the inspection result when the source is unsupported or incomplete.
3. When discovery tools are exposed, request the fixed Hermes Grok 4.5 discovery authorization through the trusted local surface, start discovery, and poll the authoritative task. Do not invent a custom provider, endpoint, credential, prompt, or budget.
4. List candidates with evidence and reason codes. Apply hard gates before ranking.
5. Select a diverse portfolio within the review budget; avoid a simple top-N list of near-duplicates.
6. Plan cards, then validate evidence, answer leakage, scoreability, media alignment, and review cost.
7. Generate only validated plans. Export only cards that pass the export gate.
8. Import into Anki only after the trusted local confirmation returns approved. Poll the import task and distinguish `apkg_ready`, `imported_unverified`, and `anki_data_verified`.
9. Treat `runtimeVerification=not_assessed` as the current ceiling. Do not claim that rendering, playback, focus behavior, or restart review was verified.
10. When a current artifact handle is available, use `study.get_artifact` for its bounded authenticated summary. Use `study.get_audit` only for requested evidence or to support a completion claim; the audit certificate does not upgrade `runtimeVerification=not_assessed`.
11. On restart, list projects and read the selected project's authoritative workflow snapshot before acting. Then list recoverable tasks and resume only a candidate-discovery task returned by the service. Never use that route to replay export or Anki writes.

Read [workflow-contract.md](references/workflow-contract.md) for stage vocabulary, tool order, recovery rules, and completion claims.

## Enforce reliability

- Keep every card traceable to a stable evidence anchor or clearly labeled explanation source.
- Prefer no card over a plausible but unsupported card.
- Keep one scoreable retrieval target per card. Split compound or ambiguous targets.
- Keep raw text separate from presentation markup and TTS input.
- Never treat model confidence, successful HTML rendering, or an APKG file as Anki verification.
- Do not hide blocked, stale, partial, cancelled, interrupted, or needs-repair states.
- Preserve completed artifacts and retry only when the returned task contract permits it. Public list/resume is limited to candidate discovery; an interrupted export or Anki write requires its own inspection before any retry.
- Require trusted local confirmation for new source scope, data egress, cost expansion, batch expansion, and Anki import. A network grant is not proof that a parser exists: stop on podcast/other/full-media adapter errors rather than silently substituting a web fetch.
- Never expose secrets, sensitive paths, OAuth material, cookies, or signed media queries in prompts, logs, snapshots, or results.

Read [source-and-safety.md](references/source-and-safety.md) before handling local files, URLs, provider calls, media tools, or Anki writes.

## Communicate with the user

- Lead with what was obtained: candidates, validated plans, cards, APKG, import, or verification.
- Surface only blockers and decisions that require the user; keep normal internal checks quiet.
- Explain recommendations with evidence and learning-value reasons, not opaque decimal scores.
- For partial success, state what is safe to keep and the exact next action.
- Never say “done” unless the requested terminal state is actually reached.
