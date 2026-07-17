# Anki Card Generator Media Shortcut Bridge

This repository-local Anki add-on closes one narrow V15 review-host gap: Anki
registers Space, Return, and Enter as main-window shortcuts before card-page
JavaScript can reliably stop them. The bridge routes those keys to a focused
V15 media control and otherwise delegates to Anki's original reviewer action.

It is intentionally not the trusted runtime verifier designed for later plugin
milestones. It does not use the network, read or write the collection, alter
scheduling, or expose AnkiConnect. It only wraps Anki's existing reviewer
shortcuts for the two exact V15 Note Model IDs frozen in
`runtime-contract.v1.json`.

## Supported runtime

- Anki point version: `260500` (Anki 26.05), fail closed outside that version.
- Note Models: V15 full `1028904201`, V15 fast `5074019806`.
- Media roles: original, slow, phrase, video.
- Keys: Space, Return, Enter.

V14 and unrelated Note Models retain Anki's original shortcut behavior.

## Build

From the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_anki_media_shortcut_addon.ps1
```

The command creates a no-overwrite `.ankiaddon` package under
`dist/anki-addon/`. The archive contains the files inside the add-on directory,
not the directory itself, as required by Anki.

## Install for isolated verification

Install the generated `.ankiaddon` through Anki's add-on installer, restart the
isolated Anki process, and verify its manifest and implementation hashes against
the runtime contract. Do not install an unverified development directory into a
user's normal profile.

If the add-on is unavailable or disabled, mouse activation remains functional
and the card template retains Shift+Space/Shift+Enter as a page-level fallback;
unmodified Space/Enter then revert to stock Anki behavior.
