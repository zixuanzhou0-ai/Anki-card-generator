from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = ROOT / "workers" / "anki_worker.py"


def load_worker():
    spec = importlib.util.spec_from_file_location("anki_worker_import_preflight_tests", WORKER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


worker = load_worker()
legacy = worker._legacy_worker


class AnkiImportPreflightTests(unittest.TestCase):
    def setUp(self):
        self.original_inspector = getattr(
            legacy.anki_model_contracts_module,
            "inspect_apkg_note_model_contract",
            None,
        )
        self.original_package_validator = (
            legacy.apkg_package_contract_module.validate_apkg_package_contract
        )

    def tearDown(self):
        if self.original_inspector is None:
            try:
                delattr(legacy.anki_model_contracts_module, "inspect_apkg_note_model_contract")
            except AttributeError:
                pass
        else:
            legacy.anki_model_contracts_module.inspect_apkg_note_model_contract = self.original_inspector
        legacy.apkg_package_contract_module.validate_apkg_package_contract = (
            self.original_package_validator
        )

    def _fixture(self, root: Path) -> tuple[dict, dict]:
        apkg_path = root / "trusted.apkg"
        apkg_path.write_bytes(b"opaque APKG fixture inspected through a contract stub")
        media_dir = root / "media"
        media_dir.mkdir()
        media_name = "sample_original.mp3"
        media_bytes = b"trusted media fixture bytes"
        (media_dir / media_name).write_bytes(media_bytes)
        media_sha256 = hashlib.sha256(media_bytes).hexdigest()
        note_content_digest = legacy.note_content_sha256(
            ["Answer"],
            ["trusted fixture answer"],
        )
        contract = {
            "compatibilityContractVersion": 1,
            "templateFamily": "language-immersive-v11",
            "templateSchema": "V14",
            "noteModelId": 3157735470,
            "modelName": "Anki Card Generator V14 - 沉浸复读 V11",
            "contractDigest": "a" * 64,
        }
        export_result = {
            "apkg_path": str(apkg_path),
            "apkg_sha256": hashlib.sha256(apkg_path.read_bytes()).hexdigest(),
            "apkg_size_bytes": apkg_path.stat().st_size,
            "apkg_mtime_ms": int(apkg_path.stat().st_mtime * 1000),
            "media_dir": str(media_dir),
            "media_manifest": {
                media_name: {
                    "sha256": media_sha256,
                    "bytes": len(media_bytes),
                }
            },
            "media_summary": {
                "media_files": 1,
                "media_bytes": len(media_bytes),
            },
            "deck_name": "Trusted Deck",
            "deck_kind": "video_language",
            "anki_tag": "anki_card_generator_v14",
            "cards": 1,
            "card_media_ledger": [
                {
                    "card_id": "card-1",
                    "segment_id": "segment-1",
                    "deck_name": "Trusted Deck",
                    "note_tags": [
                        "anki_card_generator_v14",
                        "lang_english",
                        "level_b1",
                        "template_immersive_v11",
                        "type_expression",
                        "layout_phrase",
                    ],
                    "note_content_sha256": note_content_digest,
                }
            ],
            "template_family": "language-immersive-v11",
            "template_schema": "V14",
            "template_version": "V14",
            "note_model_id": 3157735470,
            "model_name": "Anki Card Generator V14 - 沉浸复读 V11",
            "compatibility_contract_version": 1,
            "note_model_contract_digest": "a" * 64,
        }
        return export_result, contract

    def _install_report(self, contract: dict, issues=None):
        legacy.apkg_package_contract_module.validate_apkg_package_contract = (
            lambda _path, _export_result: {
                "ok": True,
                "issues": [],
                "summary": {"notes": 1, "cards": 1, "media": 1},
            }
        )
        legacy.anki_model_contracts_module.inspect_apkg_note_model_contract = (
            lambda _path: {"issues": list(issues or []), "contracts": [dict(contract)]}
        )

    def _assert_write_contract_failure(
        self,
        export_result: dict,
        expected_check: str,
    ) -> None:
        inspector_calls: list[Path] = []
        legacy.anki_model_contracts_module.inspect_apkg_note_model_contract = (
            lambda path: inspector_calls.append(Path(path)) or {}
        )

        result = legacy.preflight_anki_import_apkg({}, export_result)

        self.assertFalse(result["ok"], result)
        self.assertEqual(result["failed_checks"], [expected_check])
        self.assertEqual(
            inspector_calls,
            [],
            "strict export write-contract failures must stop before APKG inspection",
        )

    def test_valid_trusted_export_passes_before_anki_write(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            export_result, contract = self._fixture(Path(temp_dir))
            self._install_report(contract)

            result = legacy.preflight_anki_import_apkg({}, export_result)

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["apkg_sha256"], export_result["apkg_sha256"])
        self.assertEqual(result["note_model_contract"]["noteModelId"], 3157735470)

    def test_strict_write_contract_rejects_card_and_summary_shape_failures(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            export_result, _contract = self._fixture(Path(temp_dir))
            cases: list[tuple[str, dict, str]] = []

            invalid_cards = copy.deepcopy(export_result)
            invalid_cards["cards"] = True
            cases.append(
                (
                    "boolean card count",
                    invalid_cards,
                    "apkg_export_card_count_invalid",
                )
            )

            missing_manifest = copy.deepcopy(export_result)
            missing_manifest.pop("media_manifest")
            cases.append(
                (
                    "missing media manifest",
                    missing_manifest,
                    "apkg_export_media_manifest_missing",
                )
            )

            missing_media_bytes = copy.deepcopy(export_result)
            missing_media_bytes["media_summary"].pop("media_bytes")
            cases.append(
                (
                    "missing media byte total",
                    missing_media_bytes,
                    "apkg_export_media_summary_invalid",
                )
            )

            boolean_media_count = copy.deepcopy(export_result)
            boolean_media_count["media_summary"]["media_files"] = True
            cases.append(
                (
                    "boolean media count",
                    boolean_media_count,
                    "apkg_export_media_summary_invalid",
                )
            )

            for name, candidate, expected_check in cases:
                with self.subTest(name=name):
                    self._assert_write_contract_failure(candidate, expected_check)

    def test_strict_write_contract_rejects_manifest_hash_and_byte_mismatches(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            export_result, _contract = self._fixture(Path(temp_dir))
            media_name = next(iter(export_result["media_manifest"]))
            cases: list[tuple[str, dict, str]] = []

            unsafe_name = copy.deepcopy(export_result)
            entry = unsafe_name["media_manifest"].pop(media_name)
            unsafe_name["media_manifest"]["../sample_original.mp3"] = entry
            cases.append(
                (
                    "unsafe media name",
                    unsafe_name,
                    "apkg_export_media_manifest_invalid",
                )
            )

            invalid_digest = copy.deepcopy(export_result)
            invalid_digest["media_manifest"][media_name]["sha256"] = "A" * 64
            cases.append(
                (
                    "non-canonical media digest",
                    invalid_digest,
                    "apkg_export_media_manifest_invalid",
                )
            )

            invalid_bytes = copy.deepcopy(export_result)
            invalid_bytes["media_manifest"][media_name]["bytes"] = True
            cases.append(
                (
                    "boolean media byte count",
                    invalid_bytes,
                    "apkg_export_media_manifest_invalid",
                )
            )

            empty_media = copy.deepcopy(export_result)
            empty_media["media_manifest"][media_name]["bytes"] = 0
            empty_media["media_summary"]["media_bytes"] = 0
            cases.append(
                (
                    "zero-byte media",
                    empty_media,
                    "apkg_export_media_manifest_invalid",
                )
            )

            count_mismatch = copy.deepcopy(export_result)
            count_mismatch["media_summary"]["media_files"] = 2
            cases.append(
                (
                    "media file count mismatch",
                    count_mismatch,
                    "apkg_export_media_manifest_mismatch",
                )
            )

            byte_total_mismatch = copy.deepcopy(export_result)
            byte_total_mismatch["media_summary"]["media_bytes"] += 1
            cases.append(
                (
                    "media byte total mismatch",
                    byte_total_mismatch,
                    "apkg_export_media_manifest_mismatch",
                )
            )

            for name, candidate, expected_check in cases:
                with self.subTest(name=name):
                    self._assert_write_contract_failure(candidate, expected_check)

    def test_strict_write_contract_rejects_full_manifest_item_limit_before_inspection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            export_result, _contract = self._fixture(Path(temp_dir))
            item_count = legacy.ANKI_MEDIA_MAX_ITEMS + 1
            export_result["media_manifest"] = {
                f"media-{index:04d}.mp3": {
                    "sha256": "0" * 64,
                    "bytes": 1,
                }
                for index in range(item_count)
            }
            export_result["media_summary"] = {
                "media_files": item_count,
                "media_bytes": item_count,
            }

            self._assert_write_contract_failure(
                export_result,
                "apkg_export_media_contract_limit_exceeded",
            )

    def test_strict_write_contract_rejects_incomplete_or_ambiguous_card_ledger(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            export_result, _contract = self._fixture(Path(temp_dir))
            cases: list[tuple[str, dict]] = []

            missing_ledger = copy.deepcopy(export_result)
            missing_ledger.pop("card_media_ledger")
            cases.append(("missing ledger", missing_ledger))

            count_mismatch = copy.deepcopy(export_result)
            count_mismatch["cards"] = 2
            cases.append(("ledger count mismatch", count_mismatch))

            duplicate_card_id = copy.deepcopy(export_result)
            duplicate_card_id["cards"] = 2
            duplicate_card_id["card_media_ledger"].append(
                copy.deepcopy(duplicate_card_id["card_media_ledger"][0])
            )
            cases.append(("duplicate card id", duplicate_card_id))

            missing_card_id = copy.deepcopy(export_result)
            missing_card_id["card_media_ledger"][0]["card_id"] = ""
            cases.append(("missing card id", missing_card_id))

            invalid_content_digest = copy.deepcopy(export_result)
            invalid_content_digest["card_media_ledger"][0][
                "note_content_sha256"
            ] = "A" * 64
            cases.append(("non-canonical note content digest", invalid_content_digest))

            for name, candidate in cases:
                with self.subTest(name=name):
                    self._assert_write_contract_failure(
                        candidate,
                        "apkg_export_card_ledger_invalid",
                    )

    def test_payload_cannot_override_trusted_path_or_identity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            export_result, contract = self._fixture(Path(temp_dir))
            self._install_report(contract)
            cases = {
                "apkg_path": str(Path(temp_dir) / "different.apkg"),
                "media_dir": str(Path(temp_dir) / "different-media"),
                "deck_name": "Other Deck",
                "deck_kind": "document_knowledge",
                "model_name": f" {export_result['model_name']}",
                "note_model_id": str(export_result["note_model_id"]),
                "expected_cards": 2,
            }
            for field, value in cases.items():
                with self.subTest(field=field):
                    result = legacy.preflight_anki_import_apkg({field: value}, export_result)
                    self.assertFalse(result["ok"])
                    self.assertEqual(result["failed_checks"], ["apkg_export_identity_mismatch"])

    def test_unknown_or_contract_incompatible_deck_kind_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            export_result, contract = self._fixture(Path(temp_dir))
            self._install_report(contract)

            export_result["deck_kind"] = "future_kind"
            unknown = legacy.preflight_anki_import_apkg({}, export_result)
            self.assertEqual(unknown["failed_checks"], ["apkg_deck_kind_unsupported"])

            export_result["deck_kind"] = "document_knowledge"
            incompatible = legacy.preflight_anki_import_apkg({}, export_result)
            self.assertEqual(incompatible["failed_checks"], ["apkg_deck_kind_contract_mismatch"])

    def test_modified_apkg_hash_or_size_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            export_result, contract = self._fixture(Path(temp_dir))
            self._install_report(contract)
            apkg_path = Path(export_result["apkg_path"])
            apkg_path.write_bytes(apkg_path.read_bytes() + b"tamper")

            result = legacy.preflight_anki_import_apkg({}, export_result)

        self.assertFalse(result["ok"])
        self.assertEqual(result["failed_checks"], ["apkg_integrity_mismatch"])

    def test_contract_issue_or_identity_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            export_result, contract = self._fixture(Path(temp_dir))
            self._install_report(contract, [{"code": "NOTE_MODEL_TEMPLATE_MISMATCH"}])
            issue = legacy.preflight_anki_import_apkg({}, export_result)
            self.assertEqual(issue["failed_checks"], ["apkg_note_model_contract_mismatch"])

            changed = dict(contract)
            changed["contractDigest"] = "b" * 64
            self._install_report(changed)
            mismatch = legacy.preflight_anki_import_apkg({}, export_result)
            self.assertEqual(
                mismatch["failed_checks"],
                ["apkg_note_model_contract_identity_mismatch"],
            )

    def test_contract_failure_calls_neither_media_prepare_nor_import_package(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            export_result, contract = self._fixture(Path(temp_dir))
            self._install_report(contract, [{"code": "UNSUPPORTED_NOTE_MODEL"}])
            anki_actions: list[str] = []
            wait_calls: list[str] = []
            original_connect = legacy.anki_connect
            original_wait = legacy.wait_for_anki_media_directory
            try:
                legacy.anki_connect = lambda action, *_args, **_kwargs: anki_actions.append(action)
                legacy.wait_for_anki_media_directory = (
                    lambda *_args, **_kwargs: wait_calls.append("wait")
                )
                result = worker.handle_verify_anki_import(
                    {"import_apkg": True, "export_result": export_result}
                )
            finally:
                legacy.anki_connect = original_connect
                legacy.wait_for_anki_media_directory = original_wait

        self.assertFalse(result["ok"])
        self.assertEqual(result["failed_checks"], ["apkg_note_model_contract_mismatch"])
        self.assertEqual(wait_calls, [])
        self.assertEqual(anki_actions, [])

    def test_model_name_preserves_wrapping_characters_for_exact_allowlist(self):
        trusted = "Anki Card Generator V14 - 沉浸复读 V11"
        for wrapped in (
            f" {trusted}",
            f"{trusted} ",
            f"\u00a0{trusted}\u00a0",
            f"\u2003{trusted}\u2003",
            f"\u200b{trusted}\u200b",
        ):
            with self.subTest(wrapped=repr(wrapped)):
                actual = legacy.anki_card_model_name({"modelName": wrapped})
                self.assertEqual(actual, wrapped)
                mismatches = legacy.imported_model_template_mismatches(
                    [actual], strict_video_import=True
                )
                self.assertEqual(mismatches["video_template_mismatches"], [wrapped])


    def test_rechecks_integrity_immediately_before_import_package(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            export_result, contract = self._fixture(Path(temp_dir))
            self._install_report(contract)
            apkg_path = Path(export_result["apkg_path"])
            anki_dir = Path(temp_dir) / "anki-media"
            anki_dir.mkdir()
            for media_name in export_result["media_manifest"]:
                shutil.copyfile(
                    Path(export_result["media_dir"]) / media_name,
                    anki_dir / media_name,
                )
            actions: list[str] = []
            wait_calls: list[str] = []
            original_connect = legacy.anki_connect
            original_wait = legacy.wait_for_anki_media_directory
            tampered = False

            def fake_connect(action, _params=None, _url=""):
                nonlocal tampered
                actions.append(action)
                if action == "findCards":
                    if not tampered:
                        apkg_path.write_bytes(apkg_path.read_bytes() + b"changed after media prepare")
                        tampered = True
                    return []
                if action == "importPackage":
                    raise AssertionError("changed APKG must never reach importPackage")
                raise AssertionError(action)

            try:
                legacy.anki_connect = fake_connect
                legacy.wait_for_anki_media_directory = (
                    lambda *_args, **_kwargs: wait_calls.append("wait") or anki_dir
                )
                result = worker.handle_verify_anki_import(
                    {"import_apkg": True, "export_result": export_result}
                )
            finally:
                legacy.anki_connect = original_connect
                legacy.wait_for_anki_media_directory = original_wait

        self.assertFalse(result["ok"])
        self.assertEqual(
            result["failed_checks"],
            ["apkg_integrity_changed_before_import"],
        )
        self.assertEqual(wait_calls, ["wait"])
        self.assertNotIn("importPackage", actions)

    def test_relative_or_missing_media_paths_fail_before_anki_actions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            export_result, contract = self._fixture(Path(temp_dir))
            self._install_report(contract)

            relative_apkg = dict(export_result, apkg_path="relative.apkg")
            result = legacy.preflight_anki_import_apkg({}, relative_apkg)
            self.assertEqual(result["failed_checks"], ["apkg_export_path_invalid"])

            relative_media = dict(export_result, media_dir="relative-media")
            result = legacy.preflight_anki_import_apkg({}, relative_media)
            self.assertEqual(result["failed_checks"], ["apkg_export_media_path_invalid"])

            missing_media = dict(export_result)
            missing_media["media_dir"] = str(Path(temp_dir) / "missing-media")
            missing_media["media_manifest"] = {
                "required.mp3": {"sha256": "b" * 64, "bytes": 1}
            }
            missing_media["media_summary"] = {
                "media_files": 1,
                "media_bytes": 1,
            }
            result = legacy.preflight_anki_import_apkg({}, missing_media)
            self.assertEqual(result["failed_checks"], ["apkg_export_media_path_missing"])

    def _export_real_v15_package(self, root: Path) -> dict:
        phrase = "contract phrase"
        sentence = f"Please remember {phrase} in this example."
        output_dir = root / "export"
        output_dir.mkdir()
        return worker.handle_export(
            {
                "project": {
                    "id": "real-import-preflight-contract",
                    "title": "Real import preflight contract",
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
                            "id": "seg_1",
                            "start": 0,
                            "end": 1,
                            "source_time": "00:00:00.000 - 00:00:01.000",
                            "text": sentence,
                            "cards": [
                                {
                                    "id": "card_1",
                                    "type": "expression",
                                    "type_label": "表达卡",
                                    "enabled": True,
                                    "english": sentence,
                                    "chinese": "这是一条真实合同负例。",
                                    "phrase": phrase,
                                    "answer_core": phrase,
                                    "exact_span": phrase,
                                    "exact_span_start": sentence.index(phrase),
                                    "exact_span_end": sentence.index(phrase) + len(phrase),
                                    "definition": "这是需要回忆的表达。",
                                    "teacher_note": "完整说出目标表达。",
                                }
                            ],
                        }
                    ],
                },
                "output_dir": str(output_dir),
            }
        )

    def _tamper_real_package_model_name(self, source: Path, target: Path) -> None:
        unpacked = target.parent / "tampered-unpacked"
        if unpacked.exists():
            shutil.rmtree(unpacked)
        unpacked.mkdir()
        with zipfile.ZipFile(source) as archive:
            archive.extractall(unpacked)
        collection_name = (
            "collection.anki2"
            if (unpacked / "collection.anki2").exists()
            else "collection.anki21"
        )
        database = unpacked / collection_name
        con = sqlite3.connect(database)
        try:
            models = json.loads(con.execute("select models from col").fetchone()[0])
            referenced_mid = int(con.execute("select mid from notes limit 1").fetchone()[0])
            models[str(referenced_mid)]["name"] += " tampered"
            con.execute(
                "update col set models = ?",
                (json.dumps(models, ensure_ascii=False),),
            )
            con.commit()
        finally:
            con.close()
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(unpacked.rglob("*")):
                if item.is_file():
                    archive.write(item, item.relative_to(unpacked).as_posix())

    def test_real_tampered_apkg_contract_stops_before_media_or_import(self):
        if not callable(
            getattr(legacy.anki_model_contracts_module, "inspect_apkg_note_model_contract", None)
        ):
            self.skipTest("shared APKG contract inspector is not available yet")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            export_result = self._export_real_v15_package(root)
            tampered = root / "tampered.apkg"
            self._tamper_real_package_model_name(Path(export_result["apkg_path"]), tampered)
            tampered_stat = tampered.stat()
            export_result = {
                **export_result,
                "apkg_path": str(tampered),
                "apkg_sha256": hashlib.sha256(tampered.read_bytes()).hexdigest(),
                "apkg_size_bytes": tampered_stat.st_size,
                "apkg_mtime_ms": int(tampered_stat.st_mtime * 1000),
            }
            actions: list[str] = []
            wait_calls: list[str] = []
            original_connect = legacy.anki_connect
            original_wait = legacy.wait_for_anki_media_directory
            try:
                legacy.anki_connect = lambda action, *_args, **_kwargs: actions.append(action)
                legacy.wait_for_anki_media_directory = (
                    lambda *_args, **_kwargs: wait_calls.append("wait")
                )
                result = worker.handle_verify_anki_import(
                    {"import_apkg": True, "export_result": export_result}
                )
            finally:
                legacy.anki_connect = original_connect
                legacy.wait_for_anki_media_directory = original_wait

        self.assertFalse(result["ok"], result)
        self.assertEqual(result["failed_checks"], ["apkg_package_contract_mismatch"])
        self.assertIn(
            "NOTE_MODEL_NAME_MISMATCH",
            result["apkg_package_contract_issue_codes"],
        )
        self.assertEqual(wait_calls, [])
        self.assertEqual(actions, [])

    def test_real_v15_export_passes_complete_production_preflight(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            export_result = self._export_real_v15_package(Path(temp_dir))
            result = legacy.preflight_anki_import_apkg({}, export_result)

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["cards"], 1)
        self.assertEqual(
            result["apkg_package_contract_summary"]["notes"],
            1,
        )

    def test_complete_package_contract_failure_stops_before_media_or_import(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            export_result, contract = self._fixture(Path(temp_dir))
            self._install_report(contract)
            legacy.apkg_package_contract_module.validate_apkg_package_contract = (
                lambda _path, _export_result: {
                    "ok": False,
                    "issues": [{"code": "APKG_NOTE_CONTENT_SHA256_MISMATCH"}],
                    "summary": {"issue_count": 1},
                }
            )
            actions: list[str] = []
            wait_calls: list[str] = []
            original_connect = legacy.anki_connect
            original_wait = legacy.wait_for_anki_media_directory
            try:
                legacy.anki_connect = lambda action, *_args, **_kwargs: actions.append(action)
                legacy.wait_for_anki_media_directory = (
                    lambda *_args, **_kwargs: wait_calls.append("wait")
                )
                result = worker.handle_verify_anki_import(
                    {"import_apkg": True, "export_result": export_result}
                )
            finally:
                legacy.anki_connect = original_connect
                legacy.wait_for_anki_media_directory = original_wait

        self.assertFalse(result["ok"], result)
        self.assertEqual(
            result["failed_checks"],
            ["apkg_package_contract_mismatch"],
        )
        self.assertEqual(
            result["apkg_package_contract_issue_codes"],
            ["APKG_NOTE_CONTENT_SHA256_MISMATCH"],
        )
        self.assertEqual(wait_calls, [])
        self.assertEqual(actions, [])

if __name__ == "__main__":
    unittest.main()
