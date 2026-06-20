from __future__ import annotations

import json
import html
import re
import shutil
import sqlite3
import subprocess
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

REQUIRED_STUDY_TEXT_FIELDS = ("Chinese", "Definition", "TeacherNote")
CORRUPTED_STUDY_TEXT_FIELDS = (
    "Chinese",
    "ChineseFeel",
    "TeacherNote",
    "Why",
    "Context",
    "ChineseLearnerTrap",
    "ConceptualAction",
)
ASCII_REPLACEMENT_RUN_RE = re.compile(r"\?{3,}")
BLOCKED_STUDY_TEXT_PATTERNS = (
    "待精修",
    "本地 fallback",
    "本地草稿",
    "预览草稿",
    "正式导出前应使用模型精修",
    "本地待审字段",
    "适合快速预览流程",
    "不建议直接作为正式学习内容",
)
MEDIA_MIN_BYTES = {
    ".jpg": 1024,
    ".jpeg": 1024,
    ".mp3": 1024,
    ".mp4": 4096,
    ".webm": 4096,
}
VERIFY_WORKSPACE_MARKER = ".anki_apkg_verify_workspace"
MAX_ARCHIVE_MEDIA_ENTRIES = 2000
MAX_ARCHIVE_ENTRY_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
LEGACY_VERIFY_ARTIFACT_NAMES = {
    "collection.anki2",
    "collection.anki21",
    "collection.media",
    "collection.log",
    "collection.anki2-shm",
    "collection.anki2-wal",
    "collection.anki21-shm",
    "collection.anki21-wal",
    "media",
}


def archive_limit_error(message: str) -> RuntimeError:
    return RuntimeError(f"UNSAFE_APKG_ARCHIVE: {message}")


def validate_apkg_archive_limits(archive: zipfile.ZipFile) -> None:
    media_entries = 0
    total_size = 0
    for info in archive.infolist():
        if info.file_size > MAX_ARCHIVE_ENTRY_BYTES:
            raise archive_limit_error(f"{info.filename} 超过单文件上限。")
        total_size += int(info.file_size)
        if total_size > MAX_ARCHIVE_TOTAL_BYTES:
            raise archive_limit_error("解压后总大小超过上限。")
        if info.filename not in {"collection.anki2", "collection.anki21", "media"}:
            media_entries += 1
    if media_entries > MAX_ARCHIVE_MEDIA_ENTRIES:
        raise archive_limit_error("媒体文件数量超过上限。")


def is_dangerous_output_root(path: Path) -> bool:
    resolved = path.resolve()
    if resolved.parent == resolved:
        return True
    try:
        if resolved == Path.home().resolve():
            return True
    except Exception:
        pass
    return False


def legacy_verify_dir_safe_to_clean(path: Path) -> bool:
    try:
        entries = list(path.iterdir())
    except OSError:
        return False
    if not entries:
        return True
    for entry in entries:
        if entry.name == VERIFY_WORKSPACE_MARKER:
            return True
    return all(entry.name in LEGACY_VERIFY_ARTIFACT_NAMES for entry in entries)


def prepare_verify_output_dir(out_dir: Path) -> Path:
    out_dir = out_dir.resolve()
    if is_dangerous_output_root(out_dir):
        raise SystemExit(f"UNSAFE_VERIFY_OUTPUT_DIR: 拒绝使用危险输出目录：{out_dir}")
    if out_dir.exists():
        if not out_dir.is_dir():
            raise SystemExit(f"UNSAFE_VERIFY_OUTPUT_DIR: 输出路径不是目录：{out_dir}")
        if not legacy_verify_dir_safe_to_clean(out_dir):
            raise SystemExit(
                "UNSAFE_VERIFY_OUTPUT_DIR: 输出目录已存在且不像 APKG 验证工作目录，已拒绝删除。"
                f"请换一个空目录或专用验证目录：{out_dir}"
            )
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    (out_dir / VERIFY_WORKSPACE_MARKER).write_text("safe to clean by verify_apkg.py\n", encoding="utf-8")
    return out_dir


def media_header_valid(file_name: str, size: int, header: bytes) -> bool:
    suffix = Path(str(file_name)).suffix.lower()
    if size < MEDIA_MIN_BYTES.get(suffix, 1):
        return False
    if suffix in {".jpg", ".jpeg"}:
        return header.startswith(b"\xff\xd8")
    if suffix == ".mp3":
        return header.startswith(b"ID3") or (
            len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0
        )
    if suffix == ".mp4":
        return b"ftyp" in header
    if suffix == ".webm":
        return header.startswith(b"\x1a\x45\xdf\xa3")
    return size > 0


def media_file_valid(path: Path) -> bool:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            header = handle.read(64)
    except OSError:
        return False
    return media_header_valid(path.name, size, header)


def ffprobe_video(path: Path) -> dict:
    executable = shutil.which("ffprobe")
    if not executable:
        return {"ok": False, "error": "ffprobe not found"}
    completed = subprocess.run(
        [
            executable,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,profile,width,height",
            "-of",
            "json",
            str(path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
    )
    if completed.returncode:
        return {"ok": False, "error": completed.stderr.strip()[:300]}
    stream = (json.loads(completed.stdout or "{}").get("streams") or [{}])[0]
    return {
        "ok": True,
        "codec": stream.get("codec_name", ""),
        "profile": stream.get("profile", ""),
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
    }


def video_compatibility_issues(name: str, probe: dict) -> list[dict]:
    issues: list[dict] = []
    suffix = Path(str(name)).suffix.lower()
    if not probe.get("ok"):
        issues.append({"file": name, "code": "VIDEO_PROBE_FAILED", "message": probe.get("error", "")})
        return issues
    height = int(probe.get("height") or 0)
    if height > 540:
        issues.append(
            {
                "file": name,
                "code": "VIDEO_RESOLUTION_TOO_HIGH",
                "message": f"视频为 {probe.get('width')}x{height}，Anki 卡面建议不高于 540p。",
            }
        )
    if suffix == ".mp4" and probe.get("profile") not in {"Constrained Baseline", "Baseline"}:
        issues.append(
            {
                "file": name,
                "code": "MP4_PROFILE_NOT_ANKI_FRIENDLY",
                "message": f"MP4 profile 为 {probe.get('profile') or 'unknown'}，建议使用 H.264 Baseline。",
            }
        )
    return issues


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


def plain_field_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html.unescape(str(value or "")))
    return re.sub(r"\s+", " ", text).strip()


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
    empty_required_text_fields: list[dict] = []
    blocked_study_text_values: list[dict] = []
    corrupted_study_text_values: list[dict] = []
    video_reference_compatibility_issues: list[dict] = []

    for index, note in enumerate(notes, start=1):
        card_id = plain_field_text(note.get("CardId", ""))
        for field_name in REQUIRED_STUDY_TEXT_FIELDS:
            if field_name in note and not plain_field_text(note.get(field_name, "")):
                empty_required_text_fields.append({"note": index, "card_id": card_id, "field": field_name})
        for field_name in (
            "Chinese",
            "Definition",
            "TeacherNote",
            "ChineseFeel",
            "Why",
            "Context",
        ):
            text = plain_field_text(note.get(field_name, ""))
            blocked = next((pattern for pattern in BLOCKED_STUDY_TEXT_PATTERNS if pattern in text), "")
            if blocked:
                blocked_study_text_values.append(
                    {"note": index, "card_id": card_id, "field": field_name, "pattern": blocked}
                )
        for field_name in CORRUPTED_STUDY_TEXT_FIELDS:
            text = plain_field_text(note.get(field_name, ""))
            match = ASCII_REPLACEMENT_RUN_RE.search(text)
            if match:
                corrupted_study_text_values.append(
                    {
                        "note": index,
                        "card_id": card_id,
                        "field": field_name,
                        "pattern": match.group(0),
                        "excerpt": text[:160],
                    }
                )
        for field_name in ("Video", "Audio", "TtsAudio", "PhraseTtsAudio"):
            referenced_media.update(extract_media_references(note.get(field_name, "")))
        video_refs = extract_media_references(note.get("Video", ""))
        mp4_refs = [name for name in video_refs if name.lower().endswith(".mp4")]
        webm_refs = [name for name in video_refs if name.lower().endswith(".webm")]
        if mp4_refs and not webm_refs:
            video_reference_compatibility_issues.append(
                {
                    "note": index,
                    "card_id": card_id,
                    "code": "NO_WEBM_FALLBACK",
                    "message": "视频卡只有 MP4，没有 WebM 兜底，Anki 桌面端可能无法稳定播放。",
                    "files": mp4_refs,
                }
            )
        meta_text = html.unescape(str(note.get("PronunciationMeta", "") or "").strip())
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
        "empty_required_text_fields": empty_required_text_fields,
        "blocked_study_text_values": blocked_study_text_values,
        "corrupted_study_text_values": corrupted_study_text_values,
        "video_reference_compatibility_issues": video_reference_compatibility_issues,
    }


def sqlite_fallback_report(apkg: Path) -> dict:
    with zipfile.ZipFile(apkg) as archive:
        validate_apkg_archive_limits(archive)
        names = archive.namelist()
        collection_name = "collection.anki2" if "collection.anki2" in names else "collection.anki21"
        media_map = json.loads(archive.read("media").decode("utf-8"))
        media_names = {Path(str(name)).name for name in media_map.values()}
        missing_archive_media = [
            file_name
            for index, file_name in media_map.items()
            if str(index) not in names and Path(str(file_name)).name not in names
        ]
        invalid_archive_media = []
        video_media_compatibility_issues = []
        for index, file_name in media_map.items():
            archive_entry = str(index) if str(index) in names else Path(str(file_name)).name
            if archive_entry not in names:
                continue
            try:
                info = archive.getinfo(archive_entry)
                with archive.open(archive_entry) as handle:
                    header = handle.read(64)
            except (KeyError, OSError):
                continue
            if not media_header_valid(str(file_name), info.file_size, header):
                invalid_archive_media.append(file_name)
            if Path(str(file_name)).suffix.lower() in {".mp4", ".webm"}:
                with tempfile.NamedTemporaryFile(suffix=Path(str(file_name)).suffix, delete=False) as tmp_media:
                    tmp_path = Path(tmp_media.name)
                    tmp_media.write(archive.read(archive_entry))
                try:
                    video_media_compatibility_issues.extend(
                        video_compatibility_issues(str(file_name), ffprobe_video(tmp_path))
                    )
                finally:
                    tmp_path.unlink(missing_ok=True)
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
                if invalid_archive_media:
                    failed_checks.append("invalid_archive_media")
                for key in (
                    "missing_required_fields",
                    "missing_referenced_media",
                    "pronunciation_meta_parse_errors",
                    "tts_text_hash_mismatches",
                    "phrase_tts_text_hash_mismatches",
                    "empty_required_text_fields",
                    "blocked_study_text_values",
                    "corrupted_study_text_values",
                    "video_reference_compatibility_issues",
                ):
                    if field_report.get(key):
                        failed_checks.append(key)
                if video_media_compatibility_issues:
                    failed_checks.append("video_media_compatibility_issues")
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
                    "invalid_archive_media": invalid_archive_media,
                    "video_media_compatibility_issues": video_media_compatibility_issues,
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

    out_dir = prepare_verify_output_dir(Path(sys.argv[2]) if len(sys.argv) > 2 else Path.cwd() / "anki_apkg_verify")

    try:
        import anki.lang
        from anki.collection import Collection
        from anki.importing.apkg import AnkiPackageImporter
    except ModuleNotFoundError:
        print(json.dumps(sqlite_fallback_report(apkg), ensure_ascii=False, indent=2))
        return

    anki.lang.set_lang("en_US")
    with zipfile.ZipFile(apkg) as archive:
        validate_apkg_archive_limits(archive)
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
        invalid_media_files = [
            name
            for name in media_files
            if not media_file_valid(media_dir / name)
        ]
        video_media_compatibility_issues = []
        for name in media_files:
            if Path(name).suffix.lower() in {".mp4", ".webm"}:
                video_media_compatibility_issues.extend(
                    video_compatibility_issues(name, ffprobe_video(media_dir / name))
                )
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
            "empty_required_text_fields",
            "blocked_study_text_values",
            "corrupted_study_text_values",
            "video_reference_compatibility_issues",
        ):
            if field_report.get(key):
                failed_checks.append(key)
        if invalid_media_files:
            failed_checks.append("invalid_media_files")
        if video_media_compatibility_issues:
            failed_checks.append("video_media_compatibility_issues")
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
            "invalid_media_files": invalid_media_files,
            "video_media_compatibility_issues": video_media_compatibility_issues,
            **field_report,
            "media_dir": str(media_dir),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        col.close(downgrade=False)


if __name__ == "__main__":
    main()
