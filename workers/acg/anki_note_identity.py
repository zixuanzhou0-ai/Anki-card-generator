from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import genanki

from .anki_model_contracts import CONTRACTS_BY_MODEL_ID


LEGACY_NOTE_GUID_ALGORITHM = "genanki-guid-for-fields-v1"
MODEL_SCOPED_NOTE_GUID_ALGORITHM = "anki-card-generator-model-scoped-guid-v1"
MODEL_SCOPED_NOTE_GUID_NAMESPACE = "anki-card-generator:model-scoped-note-guid:v1"

_LEGACY_TEMPLATE_SCHEMAS = frozenset({"V10", "V12", "V14"})
_MODEL_SCOPED_TEMPLATE_SCHEMAS = frozenset({"V15"})
_SUPPORTED_TEMPLATE_SCHEMAS = _LEGACY_TEMPLATE_SCHEMAS | _MODEL_SCOPED_TEMPLATE_SCHEMAS

_unknown_schemas = {
    contract.template_schema
    for contract in CONTRACTS_BY_MODEL_ID.values()
    if contract.template_schema not in _SUPPORTED_TEMPLATE_SCHEMAS
}
if _unknown_schemas:
    raise RuntimeError(
        "Note GUID algorithm must be explicitly selected for new template schemas: "
        + ", ".join(sorted(_unknown_schemas))
    )

NOTE_GUID_ALGORITHM_BY_MODEL_ID = {
    contract.note_model_id: (
        MODEL_SCOPED_NOTE_GUID_ALGORITHM
        if contract.template_schema in _MODEL_SCOPED_TEMPLATE_SCHEMAS
        else LEGACY_NOTE_GUID_ALGORITHM
    )
    for contract in CONTRACTS_BY_MODEL_ID.values()
}


def normalize_note_values(field_values: Sequence[Any]) -> tuple[str, ...]:
    return tuple("" if value is None else str(value) for value in field_values)


def canonical_note_values_json(field_values: Sequence[Any]) -> str:
    return json.dumps(
        list(normalize_note_values(field_values)),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def note_guid_for_model(note_model_id: int, field_values: Sequence[Any]) -> str:
    """Return the frozen deterministic note GUID for a registered Note Model.

    V10/V12/V14 retain genanki 0.13.1's historical field-only identity.
    V15 scopes identity to the exact Note Model so same-field V14 and V15 notes
    can coexist without Anki merging or skipping either note.
    """

    algorithm = NOTE_GUID_ALGORITHM_BY_MODEL_ID.get(note_model_id)
    if algorithm is None:
        raise ValueError(f"Unregistered Note Model ID: {note_model_id}")
    values = normalize_note_values(field_values)
    if algorithm == LEGACY_NOTE_GUID_ALGORITHM:
        return genanki.guid_for(*values)
    if algorithm == MODEL_SCOPED_NOTE_GUID_ALGORITHM:
        return genanki.guid_for(
            MODEL_SCOPED_NOTE_GUID_NAMESPACE,
            str(note_model_id),
            canonical_note_values_json(values),
        )
    raise RuntimeError(f"Unsupported Note GUID algorithm: {algorithm}")


__all__ = [
    "LEGACY_NOTE_GUID_ALGORITHM",
    "MODEL_SCOPED_NOTE_GUID_ALGORITHM",
    "MODEL_SCOPED_NOTE_GUID_NAMESPACE",
    "NOTE_GUID_ALGORITHM_BY_MODEL_ID",
    "canonical_note_values_json",
    "normalize_note_values",
    "note_guid_for_model",
]
