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
2. `system.request_source_grant` for a local file or directory.
3. `study.create_project`.
4. `study.register_inputs`, `study.start_source_inspection`, and `study.get_source_inspection`.
5. `system.authorize_candidate_discovery` with only the fixed `hermes_grok_4_5` preset; after approval call `study.start_discovery` and poll `study.get_task`.
6. `study.list_candidates`, `study.get_candidate`, and `study.preview_evidence`.
7. `study.set_selection`, `study.plan_cards`, `study.list_card_plans`, `study.edit_card_plan`, and `study.validate_card_plans`.
8. `cards.generate`, then `cards.list`.
9. `system.request_output_grant`, then `cards.export_apkg`; poll `study.get_task` and use `study.cancel_task` only on explicit cancellation.
10. `anki.prepare_import`, `anki.request_import_confirmation`, then `anki.import_and_verify`; poll `study.get_task`.
11. On startup or after an interrupted discovery, call `study.list_recoverable_tasks`; use `study.resume_task` only for a returned candidate-discovery task.

Do not call tools that are not exposed by the installed plugin version.

## Planned but unavailable tools

Do not call `system.list_profiles`, `system.open_local_settings`, `system.request_network_grant`, `system.request_operation_confirmation`, `system.revoke_grant`, `system.validate_profile`, `study.list_projects`, `study.get_project`, `study.update_learning_contract`, `study.edit_candidate`, `study.get_artifact`, or `study.get_audit` until a future runtime exposes them.

## Tasks and recovery

- Treat `study.get_task` as authoritative; prose progress is not state.
- Use `study.cancel_task` for explicit cancellation.
- Use `study.list_recoverable_tasks` as the only public recovery inventory. `study.resume_task` currently accepts only returned failed, cancelled, or interrupted candidate-discovery tasks and creates or reuses an authenticated successor.
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
