from __future__ import annotations

import json
import re
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")


MODEL_PREFIXES = (
    "Anki Card Generator V12",
    "Anki Card Generator V11",
    "Anki Card Generator V10",
    "Anki Card Generator V9",
    "Anki Card Generator V8",
    "Anki Card Generator V1",
    "Drama Anki V1",
)
FIELD_SEPARATOR = "\x1f"


def clean_tts_input_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    text = re.sub(r"\[[^\]]+\]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def media_text_hash(value: str) -> str:
    import hashlib

    text = clean_tts_input_text(value).lower()
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12] if text else ""


def extract_media_references(value: str) -> list[str]:
    refs: list[str] = []
    for attr in ("src", "poster"):
        for match in re.finditer(rf"\b{attr}\s*=\s*([\"'])(.*?)\1", str(value or ""), flags=re.IGNORECASE):
            name = match.group(2).strip()
            if name and not re.match(r"^[a-z]+://", name, flags=re.IGNORECASE):
                refs.append(Path(name).name)
    return list(dict.fromkeys(refs))


def field_dicts_from_note_rows(rows: list[tuple], models: dict) -> list[dict]:
    model_fields = {
        str(model_id): [field.get("name", "") for field in model.get("flds", [])]
        for model_id, model in models.items()
    }
    notes: list[dict] = []
    for mid, fields_raw in rows:
        names = model_fields.get(str(mid), [])
        values = str(fields_raw or "").split(FIELD_SEPARATOR)
        notes.append({name: values[index] if index < len(values) else "" for index, name in enumerate(names)})
    return notes


def note_field_dicts(con: sqlite3.Connection, models: dict) -> list[dict]:
    return field_dicts_from_note_rows(con.execute("select mid, flds from notes").fetchall(), models)


def offline_field_report(notes: list[dict], media_names: set[str]) -> dict:
    required_fields = {
        "CardId",
        "TtsAudio",
        "PhraseTtsAudio",
        "Answer",
        "PronunciationMeta",
        "English",
        "Phrase",
    }
    present_fields = set().union(*(note.keys() for note in notes)) if notes else set()
    missing_fields = sorted(required_fields - present_fields)
    referenced_media: set[str] = set()
    pronunciation_meta_errors: list[dict] = []
    tts_hash_mismatches: list[dict] = []
    phrase_tts_hash_mismatches: list[dict] = []

    for index, note in enumerate(notes, start=1):
        for field_name in ("Video", "Audio", "TtsAudio", "PhraseTtsAudio"):
            referenced_media.update(extract_media_references(note.get(field_name, "")))
        meta_text = clean_tts_input_text(note.get("PronunciationMeta", ""))
        if meta_text:
            try:
                meta = json.loads(meta_text)
                if not isinstance(meta, dict):
                    raise ValueError("PronunciationMeta is not an object")
            except Exception as err:
                pronunciation_meta_errors.append({"note": index, "error": str(err)})
        for media_name in extract_media_references(note.get("TtsAudio", "")):
            expected = media_text_hash(note.get("English", ""))
            if expected and f"_{expected}" not in media_name:
                tts_hash_mismatches.append(
                    {"note": index, "file": media_name, "expected_text_hash": expected, "field": "English"}
                )
        phrase_text = note.get("Answer") or note.get("Phrase")
        for media_name in extract_media_references(note.get("PhraseTtsAudio", "")):
            expected = media_text_hash(phrase_text)
            if expected and f"_{expected}" not in media_name:
                phrase_tts_hash_mismatches.append(
                    {"note": index, "file": media_name, "expected_text_hash": expected, "field": "Answer"}
                )

    return {
        "missing_required_fields": missing_fields,
        "referenced_media": sorted(referenced_media),
        "missing_referenced_media": sorted(referenced_media - media_names),
        "unreferenced_media": sorted(media_names - referenced_media),
        "pronunciation_meta_parse_errors": pronunciation_meta_errors,
        "tts_text_hash_mismatches": tts_hash_mismatches,
        "phrase_tts_text_hash_mismatches": phrase_tts_hash_mismatches,
    }


def sqlite_fallback_report(apkg: Path) -> dict:
    with zipfile.ZipFile(apkg) as archive:
        names = archive.namelist()
        collection_name = "collection.anki2" if "collection.anki2" in names else "collection.anki21"
        media_map = json.loads(archive.read("media").decode("utf-8"))
        media_names = {Path(str(name)).name for name in media_map.values()}
        missing_archive_media = [
            file_name
            for index, file_name in media_map.items()
            if str(index) not in names and Path(str(file_name)).name not in names
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / collection_name
            db_path.write_bytes(archive.read(collection_name))
            con = sqlite3.connect(db_path)
            try:
                models = json.loads(con.execute("select models from col").fetchone()[0])
                model_values = list(models.values())
                matched_models = [
                    model
                    for model in model_values
                    if str(model.get("name", "")).startswith(MODEL_PREFIXES)
                ]
                notes = [row[0] for row in con.execute("select flds from notes").fetchall()]
                field_notes = note_field_dicts(con, models)
                field_report = offline_field_report(field_notes, media_names)
                note_fields = "\n".join(notes)
                failed_checks = []
                if missing_archive_media:
                    failed_checks.append("missing_archive_media")
                for key in (
                    "missing_required_fields",
                    "missing_referenced_media",
                    "pronunciation_meta_parse_errors",
                    "tts_text_hash_mismatches",
                    "phrase_tts_text_hash_mismatches",
                ):
                    if field_report.get(key):
                        failed_checks.append(key)
                return {
                    "ok": not failed_checks,
                    "mode": "sqlite_fallback",
                    "apkg": str(apkg),
                    "added": None,
                    "note_count": len(notes),
                    "card_count": con.execute("select count() from cards").fetchone()[0],
                    "failed_checks": failed_checks,
                    "models": [model.get("name") for model in matched_models],
                    "template_names": [
                        template.get("name")
                        for model in matched_models
                        for template in model.get("tmpls", [])
                    ],
                    "has_video_html_field": "<video" in note_fields,
                    "has_mp4_video_source": ".mp4" in note_fields,
                    "has_webm_video_source": ".webm" in note_fields,
                    "has_poster_html_field": 'poster="' in note_fields,
                    "has_audio_html_field": any("<audio" in fields and ".mp3" in fields for fields in notes),
                    "media_files": sorted(media_map.values()),
                    "missing_archive_media": missing_archive_media,
                    **field_report,
                    "media_dir": "",
                }
            finally:
                con.close()


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python workers/verify_apkg.py <deck.apkg> [out_dir]")

    apkg = Path(sys.argv[1])
    if not apkg.exists():
        raise SystemExit(f"APKG not found: {apkg}")

    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path.cwd() / "anki_apkg_verify"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    try:
        import anki.lang
        from anki.collection import Collection
        from anki.importing.apkg import AnkiPackageImporter
    except ModuleNotFoundError:
        print(json.dumps(sqlite_fallback_report(apkg), ensure_ascii=False, indent=2))
        return

    anki.lang.set_lang("en_US")
    col = Collection(str(out_dir / "collection.anki2"))
    try:
        importer = AnkiPackageImporter(col, str(apkg))
        importer.run()
        models = [
            model
            for model in col.models.all()
            if str(model.get("name", "")).startswith(MODEL_PREFIXES)
        ]
        notes = col.db.list("select flds from notes")
        media_dir = Path(col.media.dir())
        media_files = sorted(path.name for path in media_dir.iterdir()) if media_dir.exists() else []
        models_by_id = {str(model["id"]): model for model in col.models.all()}
        try:
            field_rows = col.db.all("select mid, flds from notes")
        except Exception:
            field_rows = []
        field_notes = field_dicts_from_note_rows(field_rows, models_by_id)
        field_report = offline_field_report(field_notes, set(media_files))
        note_fields = "\n".join(notes)
        failed_checks = []
        for key in (
            "missing_required_fields",
            "missing_referenced_media",
            "pronunciation_meta_parse_errors",
            "tts_text_hash_mismatches",
            "phrase_tts_text_hash_mismatches",
        ):
            if field_report.get(key):
                failed_checks.append(key)
        report = {
            "ok": not failed_checks,
            "apkg": str(apkg),
            "added": getattr(importer, "added", None),
            "note_count": len(notes),
            "card_count": col.db.scalar("select count() from cards"),
            "failed_checks": failed_checks,
            "models": [model.get("name") for model in models],
            "template_names": [template.get("name") for model in models for template in model.get("tmpls", [])],
            "has_video_html_field": "<video" in note_fields,
            "has_mp4_video_source": ".mp4" in note_fields,
            "has_webm_video_source": ".webm" in note_fields,
            "has_poster_html_field": 'poster="' in note_fields,
            "has_audio_html_field": any("<audio" in fields and ".mp3" in fields for fields in notes),
            "media_files": media_files,
            **field_report,
            "media_dir": str(media_dir),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        col.close(downgrade=False)


if __name__ == "__main__":
    main()
