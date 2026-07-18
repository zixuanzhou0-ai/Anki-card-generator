---
name: anki-study-agent
description: Turn authorized local videos, subtitles, YouTube links, folders, web pages, PDFs, podcasts, and other Codex-readable files into evidence-backed Anki study tasks. Use when Codex needs to discover worthwhile learning objectives, select language or general-knowledge candidates, generate or resume cards, export APKG, or import and verify a deck in Anki.
---

# Anki Study Agent

Create cards as verifiable memory-retrieval tasks, not saved summaries. Preserve source evidence, make each answer scoreable, minimize review debt, and distinguish generated, exported, imported, and verified states.

## Check runtime capability

1. Inspect the available tools for `system.get_capabilities` and the `study.*`, `cards.*`, and `anki.*` namespaces.
2. Call `system.get_capabilities` before starting a workflow when it is available.
3. If the Card Service tools are unavailable, say that the local plugin runtime is not registered. Do not claim that an APKG, media file, import, or verification exists.
4. Do not replace a missing Card Service with arbitrary shell commands or direct provider calls.

## Build the learning contract

1. Infer the learner's desired future behavior, current level, review budget, language, evidence policy, and exclusions.
2. Ask only when different answers would materially change what should be learned, what may leave the device, or how much review debt will be created.
3. Otherwise choose conservative, reversible defaults and state them briefly.
4. Create the project and versioned learning contract before discovery. Never let a later model silently redefine the goal.

Read [learning-contract.md](references/learning-contract.md) when selecting objectives, card routes, or a candidate portfolio.

## Run the workflow

1. Obtain source or network grants through trusted local surfaces. Never pass raw local paths, credentials, cookies, signed URLs, or unrestricted origins as model text.
2. Register inputs and inspect source integrity before discovery.
3. Start discovery, poll the authoritative task, and resume from safe checkpoints instead of repeating completed expensive work.
4. List candidates with evidence and reason codes. Apply hard gates before ranking.
5. Select a diverse portfolio within the review budget; avoid a simple top-N list of near-duplicates.
6. Plan cards, then validate evidence, answer leakage, scoreability, media alignment, and review cost.
7. Generate only validated plans. Export only cards that pass the export gate.
8. Import into Anki only after an explicit user action. Verify notes, cards, deck, fields, media, and audio after import.
9. Report the exact terminal stage and remaining issues.

Read [workflow-contract.md](references/workflow-contract.md) for stage vocabulary, tool order, recovery rules, and completion claims.

## Enforce reliability

- Keep every card traceable to a stable evidence anchor or clearly labeled explanation source.
- Prefer no card over a plausible but unsupported card.
- Keep one scoreable retrieval target per card. Split compound or ambiguous targets.
- Keep raw text separate from presentation markup and TTS input.
- Never treat model confidence, successful HTML rendering, or an APKG file as Anki verification.
- Do not hide blocked, stale, partial, cancelled, interrupted, or needs-repair states.
- Preserve completed artifacts and retry only the failed or active stage when the contract allows it.
- Require trusted local confirmation for new source scope, data egress, cost expansion, batch expansion, and Anki import.
- Never expose secrets, sensitive paths, OAuth material, cookies, or signed media queries in prompts, logs, snapshots, or results.

Read [source-and-safety.md](references/source-and-safety.md) before handling local files, URLs, provider calls, media tools, or Anki writes.

## Communicate with the user

- Lead with what was obtained: candidates, validated plans, cards, APKG, import, or verification.
- Surface only blockers and decisions that require the user; keep normal internal checks quiet.
- Explain recommendations with evidence and learning-value reasons, not opaque decimal scores.
- For partial success, state what is safe to keep and the exact next action.
- Never say “done” unless the requested terminal state is actually reached.
