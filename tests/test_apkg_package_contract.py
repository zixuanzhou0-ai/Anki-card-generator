from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr
from pathlib import Path
from typing import Callable
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
WORKERS = ROOT / "workers"
if str(WORKERS) not in sys.path:
    sys.path.insert(0, str(WORKERS))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


worker = load_module("anki_worker_for_package_contract_tests", WORKERS / "anki_worker.py")

from acg.anki_media import anki_audio_html  # noqa: E402
from acg.anki_export import windows_basename_key, windows_safe_basename  # noqa: E402
from acg.anki_model_contracts import (  # noqa: E402
    COMPATIBILITY_CONTRACT_VERSION,
    MAX_ARCHIVE_COLLECTION_BYTES,
    MAX_ARCHIVE_MEDIA_BYTES,
    MAX_ARCHIVE_MEDIA_MAP_BYTES,
    note_model_field_names,
    note_model_field_specs,
    resolve_export_note_model_contract,
    validate_apkg_archive_limits,
)
from acg.anki_note_identity import (  # noqa: E402
    LEGACY_NOTE_GUID_ALGORITHM,
    MODEL_SCOPED_NOTE_GUID_ALGORITHM,
    NOTE_GUID_ALGORITHM_BY_MODEL_ID,
    note_guid_for_model,
)
from acg.apkg_package_contract import (  # noqa: E402
    note_content_sha256,
    validate_apkg_package_contract,
)


class ApkgPackageContractTests(unittest.TestCase):
    def _temp_root(self):
        explicit = os.environ.get("ACG_TEST_TEMP_ROOT")
        return tempfile.TemporaryDirectory(dir=explicit or None)

    def _fixture(
        self,
        root: Path,
        *,
        card_count: int = 1,
        with_media: bool = True,
        media_role: str = "original_audio",
    ) -> dict:
        import genanki

        label, css, qfmt, afmt = worker._legacy_worker.anki_template_assets(
            "immersive_v11",
            "video_language",
            "warm_paper",
            "full",
        )
        family = worker._legacy_worker.anki_template_family(
            "immersive_v11",
            "video_language",
            "warm_paper",
            "full",
        )
        schema = worker._legacy_worker.anki_template_version("immersive_v11", "video_language")
        contract = resolve_export_note_model_contract(family, schema, label)
        fields = list(note_model_field_names(True))
        model = genanki.Model(
            contract.note_model_id,
            contract.model_name,
            fields=note_model_field_specs(True),
            templates=[{"name": label, "qfmt": qfmt, "afmt": afmt}],
            css=css,
        )
        deck_id = 1919191919
        deck_name = "Contract Fixture"
        deck = genanki.Deck(deck_id, deck_name)
        note_tags = [
            f"anki_card_generator_{contract.template_schema.lower()}",
            "lang_en",
            "level_b1",
            "template_immersive_v11",
            "type_phrase",
            "layout_phrase",
        ]

        media_name = "fixture-audio.mp3"
        media_file = root / media_name
        media_payload = b"offline-package-contract-audio-fixture"
        if with_media:
            media_file.write_bytes(media_payload)

        ledgers: list[dict] = []
        for index in range(card_count):
            card_id = f"contract-card-{index + 1}"
            values = [""] * len(fields)
            field_index = {name: position for position, name in enumerate(fields)}
            values[field_index["CardId"]] = card_id
            values[field_index["CardType"]] = "表达卡"
            values[field_index["FrontPrompt"]] = "请回忆目标表达"
            values[field_index["FrontContent"]] = f"contract phrase {index + 1}"
            values[field_index["Answer"]] = f"contract phrase {index + 1}"
            values[field_index["English"]] = f"Please remember contract phrase {index + 1}."
            values[field_index["EnglishDisplay"]] = (
                f'Please remember <mark class="target-expression">contract phrase {index + 1}</mark>.'
            )
            values[field_index["TransferExamplesDisplay"]] = (
                '<ul class="v11-example-list"><li>Use '
                f'<mark class="target-expression">contract phrase {index + 1}</mark>'
                " today.</li></ul>"
            )
            if with_media:
                field_name = "PhraseTtsAudio" if media_role == "phrase_tts" else "Audio"
                values[field_index[field_name]] = anki_audio_html(
                    media_name,
                    controls=False,
                    role="phrase" if media_role == "phrase_tts" else "original",
                )
            deck.add_note(
                genanki.Note(
                    model=model,
                    fields=values,
                    tags=note_tags,
                    guid=note_guid_for_model(contract.note_model_id, values),
                )
            )
            ledgers.append(
                {
                    "card_id": card_id,
                    "source_card_id": f"source-{index + 1}",
                    "segment_id": "segment-1",
                    "deck_name": deck_name,
                    "note_tags": note_tags,
                    "note_content_sha256": note_content_sha256(fields, values),
                    "video_webm": "",
                    "video_mp4": "",
                    "poster": "",
                    "original_audio": media_name if with_media and media_role == "original_audio" else "",
                    "sentence_tts_audio": "",
                    "phrase_tts_audio": media_name if with_media and media_role == "phrase_tts" else "",
                }
            )

        package = genanki.Package(deck)
        package.media_files = [str(media_file)] if with_media else []
        apkg = root / "contract-fixture.apkg"
        old_tempdir = tempfile.tempdir
        tempfile.tempdir = str(root)
        try:
            package.write_to_file(str(apkg), timestamp=1_700_000_000.0)
        finally:
            tempfile.tempdir = old_tempdir

        media_manifest = (
            {
                media_name: {
                    "sha256": hashlib.sha256(media_payload).hexdigest(),
                    "bytes": len(media_payload),
                    "role": media_role,
                    "segment_id": "segment-1",
                    **({"card_id": ledgers[0]["card_id"]} if media_role == "phrase_tts" else {}),
                }
            }
            if with_media
            else {}
        )
        result = {
            "schema_version": 2,
            "apkg_path": str(apkg.resolve()),
            "apkg_sha256": hashlib.sha256(apkg.read_bytes()).hexdigest(),
            "apkg_size_bytes": apkg.stat().st_size,
            "deck_name": deck_name,
            "deck_names": [deck_name],
            "deck_kind": "video_language",
            "template_family": contract.template_family,
            "template_schema": contract.template_schema,
            "template_version": contract.template_schema,
            "template_name": contract.template_name,
            "note_model_id": contract.note_model_id,
            "model_name": contract.model_name,
            "compatibility_contract_version": COMPATIBILITY_CONTRACT_VERSION,
            "note_model_contract_digest": contract.contract_digest,
            "anki_tag": f"anki_card_generator_{contract.template_schema.lower()}",
            "media_manifest": media_manifest,
            "media_ledger": (
                [
                    {
                        "file": media_name,
                        "role": media_role,
                        "segment_id": "segment-1",
                        "card_id": ledger["card_id"] if media_role == "phrase_tts" else "",
                        "field": "PhraseTtsAudio" if media_role == "phrase_tts" else "Audio",
                    }
                    for ledger in (ledgers if media_role == "phrase_tts" else ledgers[:1])
                ]
                if with_media
                else []
            ),
            "card_media_ledger": ledgers,
            "note_content_fingerprint": {
                "schema_version": 1,
                "algorithm": "sha256",
                "serialization": "json-field-pairs-v1",
                "field_names": fields,
                "card_count": card_count,
            },
            "cards": card_count,
            "media_summary": {
                "media_files": len(media_manifest),
                "media_bytes": sum(entry["bytes"] for entry in media_manifest.values()),
                "card_media_ledger_items": card_count,
            },
        }
        return result

    def _rewrite_database(
        self,
        source: Path,
        target: Path,
        mutate: Callable[[sqlite3.Connection], None],
    ) -> None:
        with zipfile.ZipFile(source) as archive:
            entries = [(info.filename, archive.read(info)) for info in archive.infolist()]
        collection_name = next(
            name for name, _payload in entries if name in {"collection.anki2", "collection.anki21"}
        )
        db_path = target.parent / f"{target.stem}.sqlite"
        db_path.write_bytes(dict(entries)[collection_name])
        connection = sqlite3.connect(db_path)
        try:
            mutate(connection)
            connection.commit()
        finally:
            connection.close()
        replacement = db_path.read_bytes()
        db_path.unlink()
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, payload in entries:
                archive.writestr(name, replacement if name == collection_name else payload)

    def _rewrite_archive(
        self,
        source: Path,
        target: Path,
        transform: Callable[[str, bytes], tuple[str, bytes]],
        extras: list[tuple[str, bytes]] | None = None,
    ) -> None:
        with zipfile.ZipFile(source) as archive:
            entries = [transform(info.filename, archive.read(info)) for info in archive.infolist()]
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, payload in [*entries, *(extras or [])]:
                archive.writestr(name, payload)

    @staticmethod
    def _retarget(result: dict, apkg: Path) -> dict:
        changed = copy.deepcopy(result)
        changed["apkg_path"] = str(apkg.resolve())
        changed["apkg_sha256"] = hashlib.sha256(apkg.read_bytes()).hexdigest()
        changed["apkg_size_bytes"] = apkg.stat().st_size
        return changed

    @staticmethod
    def _codes(report: dict) -> set[str]:
        return {str(item.get("code")) for item in report.get("issues", [])}

    @staticmethod
    def _real_project(*, title: str = "Real package contract") -> dict:
        sentence = "Please remember contract phrase in this example."
        phrase = "contract phrase"
        return {
            "id": "real-package-contract",
            "title": title,
            "source_mode": "url",
            "source_url": "https://example.com/watch?v=contract",
            "url_import_mode": "subtitles",
            "video_path": "",
            "subtitle_path": "",
            "language": "English",
            "level": "B1",
            "template_id": "immersive_v11",
            "review_density": "full",
            "skip_video_slicing": True,
            "segments": [
                {
                    "id": "segment-1",
                    "start": 0,
                    "end": 1,
                    "source_time": "00:00:00.000 - 00:00:01.000",
                    "text": sentence,
                    "cards": [
                        {
                            "id": "real-card-1",
                            "type": "expression",
                            "type_label": "表达卡",
                            "enabled": True,
                            "english": sentence,
                            "chinese": "这是一条真实导出合同测试卡。",
                            "phrase": phrase,
                            "answer_core": phrase,
                            "exact_span": phrase,
                            "exact_span_start": sentence.index(phrase),
                            "exact_span_end": sentence.index(phrase) + len(phrase),
                            "definition": "本卡用于验证最终 APKG 的完整合同。",
                            "teacher_note": "复习时完整说出目标表达。",
                        }
                    ],
                }
            ],
        }

    def test_exact_v15_fixture_with_media_and_safe_display_markup_passes(self):
        with self._temp_root() as temp_dir:
            result = self._fixture(Path(temp_dir), card_count=2, with_media=True)
            report = validate_apkg_package_contract(result["apkg_path"], result)

        self.assertTrue(report["ok"], report)
        self.assertEqual(report["issues"], [])
        self.assertEqual(report["summary"]["notes"], 2)
        self.assertEqual(report["summary"]["cards"], 2)
        self.assertEqual(report["summary"]["media"], 1)

    def test_note_tag_builder_is_namespaced_deterministic_and_ascii_safe(self):
        kwargs = {
            "anki_tag": "anki_card_generator_v14",
            "language": "简体 中文",
            "level": "B 1",
            "template_id": "沉浸复读",
            "card_type": "词 块",
            "layout": "复读",
        }
        tags = worker._legacy_worker.build_anki_note_tags(**kwargs)

        self.assertEqual(tags, worker._legacy_worker.build_anki_note_tags(**kwargs))
        self.assertEqual(tags[0], "anki_card_generator_v14")
        self.assertEqual(
            [tag.split("_", 1)[0] for tag in tags[1:]],
            ["lang", "level", "template", "type", "layout"],
        )
        self.assertEqual(len(tags), 6)
        self.assertEqual(len(set(tags)), 6)
        self.assertTrue(
            all(
                tag
                and tag.isascii()
                and tag == tag.lower()
                and not any(character.isspace() for character in tag)
                for tag in tags
            )
        )

    def test_note_guid_contract_preserves_legacy_and_scopes_v15_models(self):
        import genanki

        values = ["same answer", "同一内容", "[sound:same.mp3]"]
        legacy_id = 3157735470
        v15_full_id = 1028904201
        v15_fast_id = 5074019806

        legacy_guid = note_guid_for_model(legacy_id, values)
        full_guid = note_guid_for_model(v15_full_id, values)
        fast_guid = note_guid_for_model(v15_fast_id, values)

        self.assertEqual(legacy_guid, genanki.guid_for(*values))
        self.assertEqual(
            NOTE_GUID_ALGORITHM_BY_MODEL_ID[legacy_id],
            LEGACY_NOTE_GUID_ALGORITHM,
        )
        self.assertEqual(
            NOTE_GUID_ALGORITHM_BY_MODEL_ID[v15_full_id],
            MODEL_SCOPED_NOTE_GUID_ALGORITHM,
        )
        self.assertEqual(len({legacy_guid, full_guid, fast_guid}), 3)
        with self.assertRaisesRegex(ValueError, "Unregistered Note Model ID"):
            note_guid_for_model(9999999999, values)

    def test_frozen_v14_fixture_keeps_the_genanki_field_only_guid(self):
        fixture = ROOT / "tests" / "fixtures" / "apkg" / "v14-immersive-one-card.apkg"
        with self._temp_root() as temp_dir, zipfile.ZipFile(fixture) as archive:
            collection_name = (
                "collection.anki2"
                if "collection.anki2" in archive.namelist()
                else "collection.anki21"
            )
            database = Path(temp_dir) / collection_name
            database.write_bytes(archive.read(collection_name))
            con = sqlite3.connect(database)
            try:
                guid, model_id, field_text = con.execute(
                    "select guid, mid, flds from notes"
                ).fetchone()
            finally:
                con.close()

        values = field_text.split("\x1f")
        self.assertEqual(model_id, 3157735470)
        self.assertEqual(guid, note_guid_for_model(model_id, values))

    def test_real_handle_export_v15_result_passes_the_complete_package_contract(self):
        sentence = "Please remember contract phrase in this example."
        phrase = "contract phrase"
        project = {
            "id": "real-v15-package-contract",
            "title": "Real V15 package contract",
            "source_mode": "local",
            "video_path": "",
            "subtitle_path": "",
            "language": "English",
            "level": "B1",
            "template_id": "immersive_v11",
            "review_density": "full",
            "skip_video_slicing": True,
            "segments": [
                {
                    "id": "segment-1",
                    "start": 0,
                    "end": 1,
                    "source_time": "00:00:00.000 - 00:00:01.000",
                    "text": sentence,
                    "cards": [
                        {
                            "id": "real-v15-card-1",
                            "type": "expression",
                            "type_label": "表达卡",
                            "enabled": True,
                            "english": sentence,
                            "chinese": "这是一条真实导出合同测试卡。",
                            "phrase": phrase,
                            "answer_core": phrase,
                            "exact_span": phrase,
                            "exact_span_start": sentence.index(phrase),
                            "exact_span_end": sentence.index(phrase) + len(phrase),
                            "definition": "本卡用于验证最终 APKG 的完整合同。",
                            "teacher_note": "复习时完整说出目标表达。",
                        }
                    ],
                }
            ],
        }
        with self._temp_root() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "real-export"
            output_dir.mkdir()
            result = worker.handle_export(
                {
                    "project": project,
                    "output_dir": str(output_dir),
                }
            )
            report = validate_apkg_package_contract(result["apkg_path"], result)

        self.assertTrue(report["ok"], report)
        self.assertEqual(report["summary"]["notes"], 1)
        self.assertEqual(report["summary"]["cards"], 1)
        self.assertEqual(
            result["card_media_ledger"][0]["note_tags"],
            [
                "anki_card_generator_v15",
                "lang_english",
                "level_b1",
                "template_immersive_v11",
                "type_expression",
                "layout_phrase",
            ],
        )

    def test_handle_export_does_not_deliver_apkg_when_complete_contract_fails(self):
        sentence = "Please remember blocked contract phrase in this example."
        phrase = "blocked contract phrase"
        project = {
            "id": "blocked-package-contract",
            "title": "Blocked package contract",
            "source_mode": "local",
            "video_path": "",
            "subtitle_path": "",
            "language": "English",
            "level": "B1",
            "template_id": "immersive_v11",
            "skip_video_slicing": True,
            "segments": [
                {
                    "id": "segment-1",
                    "start": 0,
                    "end": 1,
                    "source_time": "00:00:00.000 - 00:00:01.000",
                    "text": sentence,
                    "cards": [
                        {
                            "id": "blocked-card-1",
                            "type": "expression",
                            "type_label": "表达卡",
                            "enabled": True,
                            "english": sentence,
                            "chinese": "这张卡必须被最终合同门禁拦截。",
                            "phrase": phrase,
                            "answer_core": phrase,
                            "exact_span": phrase,
                            "exact_span_start": sentence.index(phrase),
                            "exact_span_end": sentence.index(phrase) + len(phrase),
                            "definition": "最终合同负例。",
                            "teacher_note": "不得交付半成品。",
                        }
                    ],
                }
            ],
        }
        with self._temp_root() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "blocked-export"
            output_dir.mkdir()
            stderr = io.StringIO()
            with (
                patch.object(
                    worker._legacy_worker.apkg_package_contract_module,
                    "validate_apkg_package_contract",
                    return_value={
                        "ok": False,
                        "issues": [{"code": "APKG_NOTE_CONTENT_SHA256_MISMATCH"}],
                        "summary": {"issue_count": 1},
                    },
                ),
                redirect_stderr(stderr),
                self.assertRaises(SystemExit),
            ):
                worker.handle_export(
                    {
                        "project": project,
                        "output_dir": str(output_dir),
                    }
                )
            delivered = list(output_dir.rglob("*.apkg"))
            partials = list(output_dir.rglob("*.partial"))

        self.assertEqual(delivered, [])
        self.assertEqual(partials, [])
        self.assertIn("APKG_PACKAGE_CONTRACT_INVALID", stderr.getvalue())
        self.assertNotIn('"stage": "done"', stderr.getvalue())

    def test_wrong_card_did_and_deck_name_fail_closed(self):
        with self._temp_root() as temp_dir:
            root = Path(temp_dir)
            result = self._fixture(root)
            source = Path(result["apkg_path"])

            wrong_did = root / "wrong-did.apkg"
            self._rewrite_database(source, wrong_did, lambda con: con.execute("update cards set did=999999999"))
            did_report = validate_apkg_package_contract(wrong_did, self._retarget(result, wrong_did))

            wrong_deck = root / "wrong-deck.apkg"

            def rename_deck(con: sqlite3.Connection) -> None:
                raw = con.execute("select decks from col").fetchone()[0]
                decks = json.loads(raw)
                custom_id = next(key for key, value in decks.items() if value["name"] != "Default")
                decks[custom_id]["name"] = "Different Deck"
                con.execute("update col set decks=?", (json.dumps(decks, ensure_ascii=False),))

            self._rewrite_database(source, wrong_deck, rename_deck)
            deck_report = validate_apkg_package_contract(wrong_deck, self._retarget(result, wrong_deck))

        self.assertIn("APKG_CARD_DECK_LINK_INVALID", self._codes(did_report))
        self.assertIn("APKG_DECK_NAME_SET_MISMATCH", self._codes(deck_report))

    def test_extra_and_tampered_media_fail_closed_even_with_retargeted_apkg_hash(self):
        with self._temp_root() as temp_dir:
            root = Path(temp_dir)
            result = self._fixture(root)
            source = Path(result["apkg_path"])

            extra = root / "extra-media.apkg"
            self._rewrite_archive(source, extra, lambda name, payload: (name, payload), [("1", b"rogue")])
            extra_report = validate_apkg_package_contract(extra, self._retarget(result, extra))

            tampered = root / "tampered-media.apkg"
            self._rewrite_archive(
                source,
                tampered,
                lambda name, payload: (name, b"tampered" if name == "0" else payload),
            )
            tampered_report = validate_apkg_package_contract(
                tampered,
                self._retarget(result, tampered),
            )

        self.assertIn("APKG_ARCHIVE_ENTRY_SET_MISMATCH", self._codes(extra_report))
        self.assertTrue(
            {"APKG_MEDIA_SIZE_MISMATCH", "APKG_MEDIA_SHA256_MISMATCH"}
            & self._codes(tampered_report),
            tampered_report,
        )

    def test_dangerous_field_html_is_rejected_after_content_hash_is_updated(self):
        with self._temp_root() as temp_dir:
            root = Path(temp_dir)
            result = self._fixture(root, with_media=False)
            source = Path(result["apkg_path"])
            target = root / "dangerous-html.apkg"
            fields = result["note_content_fingerprint"]["field_names"]
            answer_index = fields.index("Answer")
            changed_values: list[str] = []

            def inject_script(con: sqlite3.Connection) -> None:
                nonlocal changed_values
                flds = con.execute("select flds from notes").fetchone()[0]
                changed_values = flds.split("\x1f")
                changed_values[answer_index] = '<script src="javascript:alert(1)"></script>'
                con.execute("update notes set flds=?", ("\x1f".join(changed_values),))

            self._rewrite_database(source, target, inject_script)
            changed_result = self._retarget(result, target)
            changed_result["card_media_ledger"][0]["note_content_sha256"] = note_content_sha256(
                fields,
                changed_values,
            )
            report = validate_apkg_package_contract(target, changed_result)

        self.assertIn("APKG_NOTE_FIELD_HTML_UNSAFE", self._codes(report))
        self.assertNotIn("APKG_NOTE_CONTENT_SHA256_MISMATCH", self._codes(report))

    def test_malformed_ledgers_manifest_and_counts_fail_strictly(self):
        with self._temp_root() as temp_dir:
            result = self._fixture(Path(temp_dir), with_media=False)
            cases = {
                "schema-version": (
                    {**result, "schema_version": 1},
                    "EXPORT_SCHEMA_VERSION_INVALID",
                ),
                "card-ledger": ({**result, "card_media_ledger": {}}, "EXPORT_CARD_LEDGER_INVALID"),
                "media-ledger": ({**result, "media_ledger": {}}, "EXPORT_MEDIA_LEDGER_INVALID"),
                "manifest": ({**result, "media_manifest": []}, "EXPORT_MEDIA_MANIFEST_INVALID"),
                "card-count": ({**result, "cards": True}, "EXPORT_CARD_COUNT_INVALID"),
                "summary-count": (
                    {**result, "media_summary": {**result["media_summary"], "media_files": "0"}},
                    "EXPORT_MEDIA_COUNT_INVALID",
                ),
            }
            for label, (changed, code) in cases.items():
                with self.subTest(case=label):
                    report = validate_apkg_package_contract(result["apkg_path"], changed)
                    self.assertIn(code, self._codes(report), report)

    def test_multiple_col_rows_and_duplicate_json_keys_fail_closed(self):
        with self._temp_root() as temp_dir:
            root = Path(temp_dir)
            result = self._fixture(root, with_media=False)
            source = Path(result["apkg_path"])

            multi_col = root / "multi-col.apkg"

            def duplicate_col(con: sqlite3.Connection) -> None:
                con.execute(
                    "insert into col select 2,crt,mod,scm,ver,dty,usn,ls,conf,models,decks,dconf,tags from col where id=1"
                )

            self._rewrite_database(source, multi_col, duplicate_col)
            multi_report = validate_apkg_package_contract(multi_col, self._retarget(result, multi_col))

            duplicate_models = root / "duplicate-model-key.apkg"

            def duplicate_model_key(con: sqlite3.Connection) -> None:
                raw = con.execute("select models from col").fetchone()[0]
                models = json.loads(raw)
                key = next(iter(models))
                duplicate = raw[:-1] + f',"{key}":' + json.dumps(models[key], ensure_ascii=False) + "}"
                con.execute("update col set models=?", (duplicate,))

            self._rewrite_database(source, duplicate_models, duplicate_model_key)
            model_report = validate_apkg_package_contract(
                duplicate_models,
                self._retarget(result, duplicate_models),
            )

            duplicate_decks = root / "duplicate-deck-key.apkg"

            def duplicate_deck_key(con: sqlite3.Connection) -> None:
                raw = con.execute("select decks from col").fetchone()[0]
                decks = json.loads(raw)
                key = next(iter(decks))
                duplicate = raw[:-1] + f',"{key}":' + json.dumps(decks[key], ensure_ascii=False) + "}"
                con.execute("update col set decks=?", (duplicate,))

            self._rewrite_database(source, duplicate_decks, duplicate_deck_key)
            deck_report = validate_apkg_package_contract(
                duplicate_decks,
                self._retarget(result, duplicate_decks),
            )

        self.assertIn("APKG_COL_ROW_INVALID", self._codes(multi_report))
        self.assertIn("APKG_MODELS_JSON_DUPLICATE_KEY", self._codes(model_report))
        self.assertIn("APKG_DECKS_JSON_DUPLICATE_KEY", self._codes(deck_report))

    def test_note_card_relationship_mid_guid_and_field_count_are_enforced(self):
        mutations: dict[str, tuple[Callable[[sqlite3.Connection], None], str]] = {
            "card-link": (lambda con: con.execute("delete from cards"), "APKG_NOTE_CARD_RELATION_INVALID"),
            "mid": (lambda con: con.execute("update notes set mid=999999999"), "REFERENCED_NOTE_MODEL_MISSING"),
            "guid": (lambda con: con.execute("update notes set guid=''"), "APKG_NOTE_GUID_INVALID"),
            "field-count": (
                lambda con: con.execute(
                    "update notes set flds=substr(flds,1,length(flds)-1) where instr(flds,char(31))>0"
                ),
                "APKG_NOTE_FIELD_COUNT_MISMATCH",
            ),
        }
        with self._temp_root() as temp_dir:
            root = Path(temp_dir)
            result = self._fixture(root, with_media=False)
            source = Path(result["apkg_path"])
            for label, (mutation, expected_code) in mutations.items():
                with self.subTest(mutation=label):
                    target = root / f"{label}.apkg"
                    self._rewrite_database(source, target, mutation)
                    report = validate_apkg_package_contract(target, self._retarget(result, target))
                    self.assertIn(expected_code, self._codes(report), report)

    def test_note_tags_and_guid_must_match_the_frozen_ledger_contract(self):
        mutations: dict[str, tuple[Callable[[sqlite3.Connection], None], str]] = {
            "tags": (
                lambda con: con.execute(
                    "update notes set tags=' anki_card_generator_v15 lang_wrong level_wrong template_wrong type_wrong layout_wrong '"
                ),
                "APKG_NOTE_TAGS_MISMATCH",
            ),
            "guid": (
                lambda con: con.execute("update notes set guid='valid-but-not-derived'"),
                "APKG_NOTE_GUID_MISMATCH",
            ),
        }
        with self._temp_root() as temp_dir:
            root = Path(temp_dir)
            result = self._fixture(root, with_media=False)
            source = Path(result["apkg_path"])
            for label, (mutation, expected_code) in mutations.items():
                with self.subTest(mutation=label):
                    target = root / f"frozen-{label}.apkg"
                    self._rewrite_database(source, target, mutation)
                    report = validate_apkg_package_contract(target, self._retarget(result, target))
                    self.assertIn(expected_code, self._codes(report), report)

    def test_v15_export_and_ledger_cannot_claim_the_v14_version_tag(self):
        with self._temp_root() as temp_dir:
            root = Path(temp_dir)
            result = self._fixture(root, with_media=False)
            wrong = copy.deepcopy(result)
            wrong["anki_tag"] = "anki_card_generator_v14"
            for item in wrong["card_media_ledger"]:
                item["note_tags"][0] = "anki_card_generator_v14"
            report = validate_apkg_package_contract(wrong["apkg_path"], wrong)

        codes = self._codes(report)
        self.assertIn("EXPORT_ANKI_TAG_SCHEMA_MISMATCH", codes)
        self.assertIn("EXPORT_NOTE_VERSION_TAG_MISMATCH", codes)

    def test_card_id_and_complete_note_content_fingerprint_must_match_ledger(self):
        with self._temp_root() as temp_dir:
            root = Path(temp_dir)
            result = self._fixture(root, with_media=False)

            wrong_id = copy.deepcopy(result)
            wrong_id["card_media_ledger"][0]["card_id"] = "another-card"
            id_report = validate_apkg_package_contract(result["apkg_path"], wrong_id)

            wrong_hash = copy.deepcopy(result)
            wrong_hash["card_media_ledger"][0]["note_content_sha256"] = "0" * 64
            hash_report = validate_apkg_package_contract(result["apkg_path"], wrong_hash)

        self.assertIn("APKG_NOTE_LEDGER_LINK_MISSING", self._codes(id_report))
        self.assertIn("APKG_NOTE_CARD_ID_SET_MISMATCH", self._codes(id_report))
        self.assertIn("APKG_NOTE_CONTENT_SHA256_MISMATCH", self._codes(hash_report))

    def test_same_second_exports_use_distinct_directories_and_preserve_both_packages(self):
        with self._temp_root() as temp_dir:
            output_dir = Path(temp_dir) / "out"
            output_dir.mkdir()
            with patch.object(worker._legacy_worker, "export_run_timestamp", return_value=1_700_000_000.25):
                first = worker.handle_export(
                    {"project": copy.deepcopy(self._real_project()), "output_dir": str(output_dir)}
                )
                first_bytes = Path(first["apkg_path"]).read_bytes()
                second = worker.handle_export(
                    {"project": copy.deepcopy(self._real_project()), "output_dir": str(output_dir)}
                )

            first_path = Path(first["apkg_path"])
            second_path = Path(second["apkg_path"])
            self.assertNotEqual(first_path, second_path)
            self.assertNotEqual(first_path.parent, second_path.parent)
            self.assertEqual(first_path.read_bytes(), first_bytes)
            self.assertTrue(second_path.is_file())

    def test_final_publish_race_never_replaces_a_newly_created_apkg(self):
        with self._temp_root() as temp_dir:
            output_dir = Path(temp_dir) / "out"
            output_dir.mkdir()
            canonical = output_dir / "race.apkg"
            original_validator = validate_apkg_package_contract

            def validate_then_race(apkg_path, export_result):
                report = original_validator(apkg_path, export_result)
                canonical.write_bytes(b"existing-race-winner")
                return report

            stderr = io.StringIO()
            with (
                patch.object(
                    worker._legacy_worker.apkg_package_contract_module,
                    "validate_apkg_package_contract",
                    side_effect=validate_then_race,
                ),
                redirect_stderr(stderr),
                self.assertRaises(SystemExit),
            ):
                worker.handle_export(
                    {
                        "project": self._real_project(),
                        "output_dir": str(output_dir),
                        "canonical_apkg_path": str(canonical),
                    }
                )

            self.assertEqual(canonical.read_bytes(), b"existing-race-winner")
            self.assertEqual(list(output_dir.rglob("*.partial")), [])
            self.assertIn("APKG_FINAL_PATH_COLLISION", stderr.getvalue())

    def test_export_source_identity_scrubs_url_userinfo_and_sensitive_query_values(self):
        project = self._real_project()
        project["source_url"] = (
            "https://alice:super-secret@example.com/watch?v=kept&token=url-canary&sig=bad"
            "#code=also-bad&section=kept"
        )
        project["source_info"] = {
            "webpage_url": project["source_url"],
            "authorization": "header-canary",
        }
        with self._temp_root() as temp_dir:
            output_dir = Path(temp_dir) / "out"
            output_dir.mkdir()
            result = worker.handle_export({"project": project, "output_dir": str(output_dir)})

        self.assertEqual(
            result["source_identity"]["source_url"],
            "https://example.com/watch?v=kept#section=kept",
        )
        serialized = json.dumps(result, ensure_ascii=False)
        for marker in ("super-secret", "url-canary", "header-canary", "also-bad"):
            self.assertNotIn(marker, serialized)

    def test_note_card_history_collection_and_deck_metadata_are_frozen(self):
        mutations: dict[str, tuple[Callable[[sqlite3.Connection], None], str]] = {
            "note-tags": (
                lambda con: con.execute("update notes set tags=' unexpected '"),
                "APKG_NOTE_METADATA_INVALID",
            ),
            "note-sfld": (
                lambda con: con.execute("update notes set sfld='wrong-sort-field'"),
                "APKG_NOTE_METADATA_INVALID",
            ),
            "note-csum": (
                lambda con: con.execute("update notes set csum=7"),
                "APKG_NOTE_METADATA_INVALID",
            ),
            "note-flags": (
                lambda con: con.execute("update notes set flags=1"),
                "APKG_NOTE_METADATA_INVALID",
            ),
            "note-data": (
                lambda con: con.execute("update notes set data='rogue'"),
                "APKG_NOTE_METADATA_INVALID",
            ),
            "card-queue": (
                lambda con: con.execute("update cards set queue=2"),
                "APKG_CARD_SCHEDULING_INVALID",
            ),
            "card-due": (
                lambda con: con.execute("update cards set due=10"),
                "APKG_CARD_SCHEDULING_INVALID",
            ),
            "card-data": (
                lambda con: con.execute("update cards set data='rogue'"),
                "APKG_CARD_SCHEDULING_INVALID",
            ),
            "revlog": (
                lambda con: con.execute("insert into revlog values(1,1,-1,1,1,1,2500,10,0)"),
                "APKG_REVLOG_NOT_EMPTY",
            ),
            "graves": (
                lambda con: con.execute("insert into graves values(-1,1,0)"),
                "APKG_GRAVES_NOT_EMPTY",
            ),
            "col": (
                lambda con: con.execute("update col set crt=0"),
                "APKG_COL_METADATA_INVALID",
            ),
        }
        with self._temp_root() as temp_dir:
            root = Path(temp_dir)
            result = self._fixture(root, with_media=False)
            source = Path(result["apkg_path"])
            for label, (mutation, code) in mutations.items():
                with self.subTest(label=label):
                    target = root / f"metadata-{label}.apkg"
                    self._rewrite_database(source, target, mutation)
                    report = validate_apkg_package_contract(target, self._retarget(result, target))
                    self.assertIn(code, self._codes(report), report)

            extra_deck_key = root / "deck-extra-key.apkg"

            def add_deck_key(con: sqlite3.Connection) -> None:
                decks = json.loads(con.execute("select decks from col").fetchone()[0])
                custom = next(value for value in decks.values() if value["name"] != "Default")
                custom["rogue"] = True
                con.execute("update col set decks=?", (json.dumps(decks),))

            self._rewrite_database(source, extra_deck_key, add_deck_key)
            deck_report = validate_apkg_package_contract(
                extra_deck_key,
                self._retarget(result, extra_deck_key),
            )
            self.assertIn("APKG_DECK_METADATA_INVALID", self._codes(deck_report), deck_report)

    def test_media_ownership_is_exact_and_shared_phrase_tts_is_explicit(self):
        with self._temp_root() as temp_dir:
            result = self._fixture(
                Path(temp_dir),
                card_count=2,
                with_media=True,
                media_role="phrase_tts",
            )
            positive_report = validate_apkg_package_contract(result["apkg_path"], result)
            self.assertTrue(positive_report["ok"], positive_report)

            duplicate = copy.deepcopy(result)
            duplicate["media_ledger"].append(copy.deepcopy(duplicate["media_ledger"][0]))
            duplicate_report = validate_apkg_package_contract(result["apkg_path"], duplicate)
            self.assertIn("EXPORT_MEDIA_LEDGER_DUPLICATE", self._codes(duplicate_report))

            wrong_owner = copy.deepcopy(result)
            wrong_owner["media_ledger"][0]["card_id"] = "wrong-card"
            wrong_owner_report = validate_apkg_package_contract(result["apkg_path"], wrong_owner)
            self.assertIn("EXPORT_CARD_MEDIA_OWNERSHIP_MISMATCH", self._codes(wrong_owner_report))

            wrong_segment = copy.deepcopy(result)
            wrong_segment["card_media_ledger"][0]["segment_id"] = ""
            wrong_segment_report = validate_apkg_package_contract(result["apkg_path"], wrong_segment)
            self.assertIn("EXPORT_CARD_SEGMENT_ID_INVALID", self._codes(wrong_segment_report))

            wrong_role = copy.deepcopy(result)
            wrong_role["media_manifest"]["fixture-audio.mp3"]["role"] = "original_audio"
            wrong_role_report = validate_apkg_package_contract(result["apkg_path"], wrong_role)
            self.assertIn("EXPORT_MEDIA_MANIFEST_ROLE_MISMATCH", self._codes(wrong_role_report))

            wrong_card_field = copy.deepcopy(result)
            wrong_card_field["card_media_ledger"][0]["phrase_tts_audio"] = ""
            wrong_field_report = validate_apkg_package_contract(result["apkg_path"], wrong_card_field)
            self.assertIn("EXPORT_CARD_MEDIA_OWNERSHIP_MISMATCH", self._codes(wrong_field_report))
            self.assertIn("APKG_NOTE_CARD_MEDIA_MISMATCH", self._codes(wrong_field_report))

    def test_batch_card_ledger_deck_name_must_match_cardid_note_and_card_did(self):
        project = self._real_project(title="Batch deck mapping")
        project["batch_enabled"] = True
        project["batch_items"] = [
            {"id": "episode-1", "enabled": True, "subdeck_title": "Episode 1"},
            {"id": "episode-2", "enabled": True, "subdeck_title": "Episode 2"},
        ]
        project["segments"][0]["batch_item_id"] = "episode-1"
        second = copy.deepcopy(project["segments"][0])
        second["id"] = "segment-2"
        second["batch_item_id"] = "episode-2"
        second["cards"][0]["id"] = "real-card-2"
        project["segments"].append(second)
        with self._temp_root() as temp_dir:
            output_dir = Path(temp_dir) / "out"
            output_dir.mkdir()
            result = worker.handle_export({"project": project, "output_dir": str(output_dir)})
            self.assertTrue(
                validate_apkg_package_contract(result["apkg_path"], result)["ok"],
                result,
            )
            wrong = copy.deepcopy(result)
            first_name = wrong["card_media_ledger"][0]["deck_name"]
            second_name = wrong["card_media_ledger"][1]["deck_name"]
            self.assertNotEqual(first_name, second_name)
            wrong["card_media_ledger"][0]["deck_name"] = second_name
            wrong["card_media_ledger"][1]["deck_name"] = first_name
            report = validate_apkg_package_contract(result["apkg_path"], wrong)

        self.assertIn("APKG_NOTE_LEDGER_DECK_MISMATCH", self._codes(report), report)

    def test_windows_basename_rules_collisions_and_archive_limits_fail_closed(self):
        self.assertIsNone(windows_safe_basename("CON"))
        self.assertIsNone(windows_safe_basename("CLOCK$"))
        self.assertIsNone(windows_safe_basename("CLOCK$.mp3"))
        self.assertIsNone(windows_safe_basename("trail."))
        self.assertIsNone(windows_safe_basename("bad:name.mp3"))
        self.assertIsNone(windows_safe_basename("e\u0301.mp3"))
        self.assertIsNone(windows_safe_basename("café.mp3"))
        self.assertIsNone(windows_safe_basename("straße.mp3"))
        self.assertIsNone(windows_safe_basename("媒体.mp3"))
        self.assertIsNone(windows_safe_basename(("a" * 252) + ".mp3"))
        self.assertEqual(windows_basename_key("Media.MP3"), windows_basename_key("media.mp3"))

        class FakeInfo:
            def __init__(self, filename: str, file_size: int):
                self.filename = filename
                self.file_size = file_size

        class FakeArchive:
            def __init__(self, infos):
                self._infos = infos

            def infolist(self):
                return self._infos

        with self.assertRaisesRegex(RuntimeError, "UNSAFE_APKG_ARCHIVE"):
            validate_apkg_archive_limits(
                FakeArchive([FakeInfo("collection.anki2", MAX_ARCHIVE_COLLECTION_BYTES + 1)])
            )
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_APKG_ARCHIVE"):
            validate_apkg_archive_limits(
                FakeArchive([FakeInfo("0", MAX_ARCHIVE_MEDIA_BYTES + 1)])
            )
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_APKG_ARCHIVE"):
            validate_apkg_archive_limits(
                FakeArchive([FakeInfo("media", MAX_ARCHIVE_MEDIA_MAP_BYTES + 1)])
            )

        with self._temp_root() as temp_dir:
            root = Path(temp_dir)
            result = self._fixture(root)
            collision = copy.deepcopy(result)
            collision["media_manifest"]["FIXTURE-AUDIO.MP3"] = copy.deepcopy(
                collision["media_manifest"]["fixture-audio.mp3"]
            )
            collision["media_summary"]["media_files"] = 2
            collision["media_summary"]["media_bytes"] *= 2
            report = validate_apkg_package_contract(result["apkg_path"], collision)
            self.assertIn("EXPORT_MEDIA_NAME_INVALID", self._codes(report), report)
            import_report = worker._legacy_worker.validate_export_result_write_contract(collision)
            self.assertFalse(import_report["ok"], import_report)
            self.assertIn("apkg_export_media_manifest_invalid", import_report["failed_checks"])

            source = Path(result["apkg_path"])
            with zipfile.ZipFile(source) as archive:
                media_payload = archive.read("0")
            archive_collision = root / "archive-windows-collision.apkg"

            def duplicate_media_name(name: str, payload: bytes) -> tuple[str, bytes]:
                if name != "media":
                    return name, payload
                media_map = json.loads(payload)
                media_map["1"] = "FIXTURE-AUDIO.MP3"
                return name, json.dumps(media_map).encode("utf-8")

            self._rewrite_archive(
                source,
                archive_collision,
                duplicate_media_name,
                extras=[("1", media_payload)],
            )
            archive_report = validate_apkg_package_contract(
                archive_collision,
                self._retarget(result, archive_collision),
            )
            self.assertIn(
                "APKG_MEDIA_FILE_NAME_INVALID",
                self._codes(archive_report),
                archive_report,
            )

    def test_packaged_media_hashing_uses_zip_stream_not_whole_entry_read(self):
        with self._temp_root() as temp_dir:
            result = self._fixture(Path(temp_dir), with_media=True)
            original_read = zipfile.ZipFile.read

            def guarded_read(archive, member, *args, **kwargs):
                name = member.filename if isinstance(member, zipfile.ZipInfo) else str(member)
                if name.isdigit():
                    raise AssertionError("numeric media entry must be streamed")
                return original_read(archive, member, *args, **kwargs)

            with patch.object(zipfile.ZipFile, "read", new=guarded_read):
                report = validate_apkg_package_contract(result["apkg_path"], result)

        self.assertTrue(report["ok"], report)

    def test_report_does_not_echo_note_content_paths_or_exception_strings(self):
        secret_marker = "do-not-echo-this-note-content"
        report = validate_apkg_package_contract(
            ROOT / f"missing-{secret_marker}.apkg",
            {"private_key": secret_marker},
        )
        serialized = json.dumps(report, ensure_ascii=False)
        self.assertFalse(report["ok"])
        self.assertNotIn(secret_marker, serialized)
        self.assertNotIn(str(ROOT), serialized)


if __name__ == "__main__":
    unittest.main()
