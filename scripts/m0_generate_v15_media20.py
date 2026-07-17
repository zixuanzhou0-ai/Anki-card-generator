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

import anki_worker as worker  # noqa: E402
import verify_apkg  # noqa: E402
from acg.anki_note_identity import note_guid_for_model  # noqa: E402
from acg.apkg_package_contract import validate_apkg_package_contract  # noqa: E402


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def inspect_note_guids(apkg_path: Path, note_model_id: int, work_dir: Path) -> dict:
    work_dir.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(apkg_path) as archive:
        collection_name = (
            "collection.anki2"
            if "collection.anki2" in archive.namelist()
            else "collection.anki21"
        )
        database = work_dir / collection_name
        database.write_bytes(archive.read(collection_name))
    con = sqlite3.connect(database)
    try:
        notes = con.execute("select guid, mid, flds from notes order by id").fetchall()
    finally:
        con.close()
    mismatches = []
    for guid, model_id, field_text in notes:
        values = field_text.split("\x1f")
        expected = note_guid_for_model(model_id, values)
        if model_id != note_model_id or guid != expected:
            mismatches.append(
                {
                    "guid": guid,
                    "expected_guid": expected,
                    "note_model_id": model_id,
                }
            )
    return {
        "notes": len(notes),
        "note_model_id": note_model_id,
        "model_scoped_guid_mismatches": mismatches,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--title", default="M0 V15 Model-Scoped GUID Media20")
    args = parser.parse_args()

    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=False)
    export_dir = output_root / "export"
    export_dir.mkdir()
    temp_dir = output_root / "tmp"
    temp_dir.mkdir()

    project = json.loads(args.project.read_text(encoding="utf-8"))
    project["id"] = "m0_v15_model_scoped_guid_media20"
    project["title"] = args.title

    previous_tempdir = tempfile.tempdir
    tempfile.tempdir = str(temp_dir)
    try:
        result = worker.handle_export(
            {
                "project": project,
                "output_dir": str(export_dir),
            }
        )
    finally:
        tempfile.tempdir = previous_tempdir

    serialized = json.dumps(result, ensure_ascii=False)
    if "smoke-test-key" in serialized or "api_key" in serialized.lower():
        raise RuntimeError("Export evidence leaked a test credential field.")
    apkg_path = Path(result["apkg_path"])
    package_report = validate_apkg_package_contract(apkg_path, result)
    verify_report = verify_apkg.sqlite_fallback_report(apkg_path)
    guid_report = inspect_note_guids(
        apkg_path,
        int(result["note_model_id"]),
        output_root / "guid-inspection",
    )

    expected = {
        "template_schema": "V15",
        "note_model_id": 1028904201,
        "anki_tag": "anki_card_generator_v15",
        "cards": 20,
        "notes": 20,
        "media": 52,
    }
    observed = {
        "template_schema": result.get("template_schema"),
        "note_model_id": result.get("note_model_id"),
        "anki_tag": result.get("anki_tag"),
        "cards": verify_report.get("card_count"),
        "notes": verify_report.get("note_count"),
        "media": len(verify_report.get("media_files") or []),
    }
    if observed != expected:
        raise RuntimeError(f"V15 evidence mismatch: expected {expected!r}, observed {observed!r}")
    if not package_report.get("ok") or not verify_report.get("ok"):
        raise RuntimeError("V15 APKG verification failed.")
    if guid_report["model_scoped_guid_mismatches"]:
        raise RuntimeError("V15 APKG contains a note outside the model-scoped GUID contract.")

    write_json(output_root / "export-result.json", result)
    write_json(output_root / "package-contract.json", package_report)
    write_json(output_root / "verify-report.json", verify_report)
    write_json(output_root / "guid-report.json", guid_report)
    summary = {
        "ok": True,
        "apkg_path": str(apkg_path),
        "apkg_sha256": hashlib.sha256(apkg_path.read_bytes()).hexdigest(),
        "observed": observed,
        "note_model_contract_digest": result["note_model_contract_digest"],
        "guid_report": guid_report,
    }
    write_json(output_root / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
