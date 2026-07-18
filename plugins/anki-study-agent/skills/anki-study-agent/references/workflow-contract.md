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
9. imported into Anki;
10. verified in Anki.

Never infer a later state from an earlier artifact.

## Tool order

Use available public tools in this order:

1. `system.get_capabilities`, then `system.list_profiles` when needed.
2. Trusted grants: `system.request_source_grant`, `system.request_network_grant`, or `system.request_output_grant`.
3. `study.create_project` and `study.update_learning_contract`.
4. `study.register_inputs`, `study.start_source_inspection`, and `study.get_source_inspection`.
5. `study.start_discovery`; poll `study.get_task`.
6. `study.list_candidates`, `study.get_candidate`, and `study.preview_evidence`.
7. `study.set_selection`, `study.plan_cards`, `study.list_card_plans`, and `study.validate_card_plans`.
8. `cards.generate`, then `cards.export_apkg`.
9. `anki.prepare_import`, trusted import confirmation, then `anki.import_and_verify`.
10. `study.get_artifact` and `study.get_audit` for evidence and handoff.

Do not call tools that are not exposed by the installed plugin version.

## Tasks and recovery

- Treat `study.get_task` as authoritative; prose progress is not state.
- Use `study.cancel_task` for explicit cancellation.
- Use `study.list_recoverable_tasks` and `study.resume_task` after interruption.
- Preserve completed batches and validated artifacts.
- Retry the active or failed stage only.
- Honor stale/invalidation state after inputs, learning contract, provider configuration, template, APKG hash, or authorization changes.
- Never reuse a finished result whose input fingerprint no longer matches.

## Completion language

Use exact claims:

- “candidates discovered”;
- “card plans validated”;
- “cards generated”;
- “APKG exported”;
- “imported, verification pending”;
- “verified in Anki”.

For partial success, report counts for kept, excluded, needs-repair, and failed items.
