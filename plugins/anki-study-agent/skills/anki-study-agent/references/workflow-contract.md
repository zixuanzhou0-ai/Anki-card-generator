# Workflow contract

## Authoritative stages

Keep these states distinct:

1. source authorized and registered;
2. source inspected;
3. candidates discovered;
4. selection saved;
5. card plans created;
6. card plans validated;
7. cards generated;
8. APKG exported;
9. imported into Anki but not data-verified;
10. Anki data verified;
11. Anki runtime verified.

Never infer a later state from an earlier artifact.

## Current public tool workflow

Treat the exposed tool list returned by the installed runtime as authoritative. The current workflow uses only these public tools, in this order:

1. `system.get_capabilities`.
2. `system.list_profiles`. When an existing selected profile reports `CREDENTIAL_REQUIRED`, call `system.open_local_settings` with its exact profile/capability, then poll only the returned `configurationSessionRef`. Never place a credential in tool arguments or conversation. For an exact selected profile that is unknown, stale, or failed, call `system.validate_profile` with the returned configuration fingerprint and credential revision plus a stable idempotency key. Model/TTS validation first returns `confirmation_required`; call `system.request_operation_confirmation` with only its `operationIntentId`, poll the trusted local decision, then retry `system.validate_profile` with the same idempotency key. A declined, expired, revoked, cancelled, interrupted, or failed result is not ready. AnkiConnect loopback validation is bounded locally and does not use the remote-operation confirmation.
3. Only when the user explicitly asks to manage or revoke permissions, call `system.revoke_grant` with `{}`. The user—not the Agent—selects items in the trusted local manager. Poll only the returned `authorizationSessionRef`; do not submit resource, import, profile, ledger, or authorization IDs. A completed result blocks future use but never means prior reads, remote calls, artifacts, or Anki writes were rolled back.
4. On startup, call `study.list_projects`; use `study.get_project` for the selected project before deciding whether to resume or create new work. If the user changes the learning purpose, target behavior, learner level, routes, budget, languages, evidence policy, or project exclusions, call `study.update_learning_contract` with the exact current project/contract revisions and semantic operations. Treat its `invalidatedStages` as the update result, then call `study.get_project` for the unique current workflow; never recreate the project or submit JSON Patch.
5. `system.request_source_grant` for a local file or directory. For a static webpage or YouTube subtitle source, call `system.request_network_grant` only with a stable `grantRequestId`, `kind=trusted_entry`, and the source type; the user enters the complete address in the trusted local window, never in tool arguments. Current `web` registration makes an anonymous static HTTPS snapshot; current `public_video` supports YouTube subtitles only. Treat podcast, other, full media, dynamic/login pages, and unsupported parsers as explicit blockers.
6. `study.create_project` for new work.
7. `study.register_inputs`, `study.start_source_inspection`, and `study.get_source_inspection`.
8. `system.authorize_candidate_discovery` with only the fixed `hermes_grok_4_5` preset; after approval call `study.start_discovery` and poll `study.get_task`.
9. `study.list_candidates`, `study.get_candidate`, and `study.preview_evidence`.
10. `study.set_selection`, `study.plan_cards`, `study.list_card_plans`, `study.edit_card_plan`, and `study.validate_card_plans`.
11. `cards.generate`, then `cards.list`.
12. `system.request_output_grant`, then `cards.export_apkg`; poll `study.get_task` and use `study.cancel_task` only on explicit cancellation.
13. `anki.prepare_import`, `anki.request_import_confirmation`, then `anki.import_and_verify`; poll `study.get_task`.
14. After generation, export, or Anki data verification, use `study.get_artifact` for the current authenticated artifact summary. Use `study.get_audit` only when the user requests evidence or when a completion claim needs its integrity, lineage, gate, and limitation certificate.
15. On startup or after an interrupted discovery, call `study.list_recoverable_tasks`; follow `nextCursor` until null when searching beyond the first page, and use `study.resume_task` only for a returned candidate-discovery task.

Do not call tools that are not exposed by the installed plugin version.

## Planned but unavailable tools

Do not call `study.edit_candidate` until a future runtime exposes it. The current `system.open_local_settings` only manages credentials for an already configured profile; it does not let the Agent create a profile or inject provider/URL/model fields. The current `system.validate_profile` likewise validates only an exact saved binding; it is not a profile editor, a general network client, or reusable authorization for later learning tasks.

`study.get_artifact` and `study.get_audit` accept only a current-session opaque artifact handle. They never return arbitrary files, raw source/card payloads, local paths, internal ArtifactRefs, or a runtime-verification claim. Unknown schemas are metadata-only; use dedicated candidate/card review tools for content.

## Tasks and recovery

- Treat `study.get_task` as authoritative; prose progress is not state.
- Use `study.cancel_task` for explicit cancellation.
- Use `study.list_projects` and `study.get_project` to recover the authoritative project/revision/stage view. Use `study.list_recoverable_tasks` as the only public task-resume inventory, and continue with its authenticated `nextCursor` until null when needed. A returned interrupted discovery may represent either a recoverable failed run or completed model work whose local project commit is pending; `study.resume_task` decides from authenticated state and must never trigger a second model call for the latter.
- Export and Anki-import tasks have no public generic resume contract. Never use discovery recovery to replay either write boundary.
- Retry the active or failed stage only when the returned task state and next action permit it.
- For Anki import, `resumability=none`. If cancellation or failure crosses a possible write boundary, require `inspect_before_retry`; never blindly repeat the import.
- Honor stale/invalidation state after inputs, learning contract, provider configuration, template, APKG hash, or authorization changes.
- Never reuse a finished result whose input fingerprint no longer matches.

## Completion language

Use exact claims:

- “candidates discovered”;
- “card plans validated”;
- “cards generated”;
- “APKG exported”;
- “imported, data verification pending”;
- “Anki data verified; runtime rendering, playback, and restart review not assessed”.

Use “runtime verified in Anki” only after a future trusted runtime verifier returns the corresponding authenticated evidence.

For partial success, report counts for kept, excluded, needs-repair, and failed items.
