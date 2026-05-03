from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path


MODEL_PREFIXES = (
    "Anki Card Generator V9",
    "Anki Card Generator V8",
    "Anki Card Generator V1",
    "Drama Anki V1",
)


def sqlite_fallback_report(apkg: Path) -> dict:
    with zipfile.ZipFile(apkg) as archive:
        names = archive.namelist()
        collection_name = "collection.anki2" if "collection.anki2" in names else "collection.anki21"
        media_map = json.loads(archive.read("media").decode("utf-8"))
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
                note_fields = "\n".join(notes)
                return {
                    "ok": True,
                    "mode": "sqlite_fallback",
                    "apkg": str(apkg),
                    "added": None,
                    "note_count": len(notes),
                    "card_count": con.execute("select count() from cards").fetchone()[0],
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
        note_fields = "\n".join(notes)
        report = {
            "ok": True,
            "apkg": str(apkg),
            "added": getattr(importer, "added", None),
            "note_count": len(notes),
            "card_count": col.db.scalar("select count() from cards"),
            "models": [model.get("name") for model in models],
            "template_names": [template.get("name") for model in models for template in model.get("tmpls", [])],
            "has_video_html_field": "<video" in note_fields,
            "has_mp4_video_source": ".mp4" in note_fields,
            "has_webm_video_source": ".webm" in note_fields,
            "has_poster_html_field": 'poster="' in note_fields,
            "has_audio_html_field": any("<audio" in fields and ".mp3" in fields for fields in notes),
            "media_files": media_files,
            "media_dir": str(media_dir),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        col.close(downgrade=False)


if __name__ == "__main__":
    main()
