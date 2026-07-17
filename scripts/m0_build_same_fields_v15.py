from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKERS = ROOT / "workers"
if str(WORKERS) not in sys.path:
    sys.path.insert(0, str(WORKERS))

import genanki  # noqa: E402

from acg.anki_model_contracts import (  # noqa: E402
    note_model_field_names,
    note_model_field_specs,
    resolve_export_note_model_contract,
)
from acg.anki_note_identity import note_guid_for_model  # noqa: E402
from acg.legacy_worker import (  # noqa: E402
    anki_template_assets,
    anki_template_family,
    anki_template_version,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_frozen_note(apkg_path: Path, scratch: Path) -> tuple[int, str, list[str], list[str]]:
    with zipfile.ZipFile(apkg_path) as archive:
        collection_name = next(
            name for name in ("collection.anki2", "collection.anki21") if name in archive.namelist()
        )
        database_path = scratch / collection_name
        database_path.write_bytes(archive.read(collection_name))

    connection = sqlite3.connect(database_path)
    try:
        row = connection.execute("SELECT mid, guid, flds, tags FROM notes ORDER BY id LIMIT 1").fetchone()
    finally:
        connection.close()
    if row is None:
        raise RuntimeError("Frozen V14 fixture contains no notes.")
    model_id, guid, raw_fields, raw_tags = row
    fields = str(raw_fields).split("\x1f")
    tags = [tag for tag in str(raw_tags).strip().split() if tag]
    return int(model_id), str(guid), fields, tags


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a V15 APKG whose field values exactly match the frozen V14 fixture."
    )
    parser.add_argument(
        "--v14-apkg",
        type=Path,
        default=ROOT / "tests" / "fixtures" / "apkg" / "v14-immersive-one-card.apkg",
    )
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()

    v14_apkg = args.v14_apkg.resolve()
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=False)

    with tempfile.TemporaryDirectory(dir=output_root) as scratch_dir:
        v14_model_id, v14_guid, values, source_tags = _read_frozen_note(
            v14_apkg, Path(scratch_dir)
        )

    label, css, qfmt, afmt = anki_template_assets(
        "immersive_v11", "video_language", "warm_paper", "full"
    )
    family = anki_template_family(
        "immersive_v11", "video_language", "warm_paper", "full"
    )
    schema = anki_template_version("immersive_v11", "video_language")
    contract = resolve_export_note_model_contract(family, schema, label)
    if contract.template_schema != "V15":
        raise RuntimeError(f"Expected current schema V15, received {contract.template_schema!r}.")

    field_names = list(note_model_field_names(True))
    if len(values) != len(field_names):
        raise RuntimeError(
            f"Field-count mismatch: frozen V14 has {len(values)}, current V15 has {len(field_names)}."
        )

    v15_guid = note_guid_for_model(contract.note_model_id, values)
    if v15_guid == v14_guid:
        raise RuntimeError("Model-scoped V15 GUID unexpectedly matches the frozen V14 GUID.")

    model = genanki.Model(
        contract.note_model_id,
        contract.model_name,
        fields=note_model_field_specs(True),
        templates=[{"name": label, "qfmt": qfmt, "afmt": afmt}],
        css=css,
    )
    deck = genanki.Deck(2071717150, "M0 Compatibility - Same Fields V15")
    tags = [tag for tag in source_tags if not tag.startswith("anki_card_generator_v")]
    tags.append("anki_card_generator_v15")
    deck.add_note(genanki.Note(model=model, fields=values, tags=tags, guid=v15_guid))

    v15_apkg = output_root / "m0-same-fields-v15.apkg"
    package = genanki.Package(deck)
    old_tempdir = tempfile.tempdir
    tempfile.tempdir = str(output_root)
    try:
        package.write_to_file(str(v15_apkg), timestamp=1_784_280_000.0)
    finally:
        tempfile.tempdir = old_tempdir

    serialized_fields = json.dumps(
        list(zip(field_names, values)), ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    summary = {
        "ok": True,
        "v14_apkg": str(v14_apkg),
        "v14_apkg_sha256": _sha256(v14_apkg),
        "v14_note_model_id": v14_model_id,
        "v14_note_guid": v14_guid,
        "v15_apkg": str(v15_apkg),
        "v15_apkg_sha256": _sha256(v15_apkg),
        "v15_note_model_id": contract.note_model_id,
        "v15_note_guid": v15_guid,
        "field_count": len(values),
        "field_values_sha256": hashlib.sha256(serialized_fields).hexdigest(),
        "note_model_contract_digest": contract.contract_digest,
    }
    summary_path = output_root / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
