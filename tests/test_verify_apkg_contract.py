from __future__ import annotations

import importlib.util
import hashlib
import json
import shutil
import subprocess
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from io import BytesIO
from unittest.mock import patch
from pathlib import Path
from typing import Callable


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


worker = load_module("anki_worker_for_contract_tests", WORKERS / "anki_worker.py")
verify_apkg = load_module("verify_apkg_for_contract_tests", WORKERS / "verify_apkg.py")

from acg.anki_model_contracts import (  # noqa: E402
    COMPATIBILITY_CONTRACT_VERSION,
    NOTE_MODEL_CONTRACTS,
    PRESENTATION_NOTE_FIELDS_SHA256,
    inspect_referenced_note_models,
    note_model_field_names,
    resolve_export_note_model_contract,
    validate_generated_note_model,
)
from acg.apkg_package_contract import validate_apkg_package_contract  # noqa: E402


class VerifyApkgContractTests(unittest.TestCase):
    def test_numeric_media_extraction_streams_and_enforces_the_limit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "stream.apkg"
            with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as archive:
                archive.writestr("0", b"a" * (verify_apkg.ZIP_STREAM_CHUNK_BYTES + 17))

            original_read = zipfile.ZipFile.read

            def guarded_read(archive, member, *args, **kwargs):
                name = member.filename if isinstance(member, zipfile.ZipInfo) else str(member)
                if name == "0":
                    raise AssertionError("numeric media entry must be streamed")
                return original_read(archive, member, *args, **kwargs)

            with zipfile.ZipFile(archive_path) as archive, patch.object(
                zipfile.ZipFile, "read", new=guarded_read
            ):
                target = BytesIO()
                copied = verify_apkg.copy_zip_entry_limited(archive, "0", target)
                self.assertEqual(copied, verify_apkg.ZIP_STREAM_CHUNK_BYTES + 17)
                self.assertEqual(len(target.getvalue()), copied)

                with self.assertRaisesRegex(ValueError, "UNSAFE_APKG_ARCHIVE"):
                    verify_apkg.copy_zip_entry_limited(
                        archive,
                        "0",
                        BytesIO(),
                        max_bytes=verify_apkg.ZIP_STREAM_CHUNK_BYTES,
                    )

    def make_project(self, card_count: int, review_density: str = "full") -> dict:
        segments = []
        for index in range(card_count):
            phrase = f"contract phrase {index + 1}"
            sentence = f"Please remember {phrase} in this example."
            segments.append(
                {
                    "id": f"seg_{index + 1}",
                    "start": index * 2,
                    "end": index * 2 + 1,
                    "source_time": f"00:00:{index:02d}.000 - 00:00:{index + 1:02d}.000",
                    "text": sentence,
                    "cards": [
                        {
                            "id": f"card_{index + 1}",
                            "type": "expression",
                            "type_label": "表达卡",
                            "enabled": True,
                            "english": sentence,
                            "chinese": "这是一条合同测试卡。",
                            "phrase": phrase,
                            "answer_core": phrase,
                            "exact_span": phrase,
                            "exact_span_start": sentence.index(phrase),
                            "exact_span_end": sentence.index(phrase) + len(phrase),
                            "definition": f"{phrase} 是本卡需要回忆的表达。",
                            "teacher_note": f"复习时完整说出 {phrase}。",
                        }
                    ],
                }
            )
        return {
            "id": f"v14-contract-{review_density}-{card_count}",
            "title": f"V14 contract {review_density} {card_count}",
            "source_mode": "local",
            "video_path": "",
            "subtitle_path": "",
            "language": "English",
            "level": "B1",
            "template_id": "immersive_v11",
            "review_density": review_density,
            "skip_video_slicing": True,
            "segments": segments,
        }

    def export_project(self, root: Path, card_count: int = 1, review_density: str = "full") -> dict:
        output_dir = root / f"export-{review_density}-{card_count}"
        output_dir.mkdir(parents=True)
        return worker.handle_export(
            {
                "project": self.make_project(card_count, review_density),
                "output_dir": str(output_dir),
            }
        )

    def mutate_package(
        self,
        source: Path,
        target: Path,
        mutate: Callable[[sqlite3.Connection, dict, int], None],
    ) -> None:
        unpacked = target.parent / f"unpacked-{target.stem}"
        if unpacked.exists():
            shutil.rmtree(unpacked)
        unpacked.mkdir(parents=True)
        with zipfile.ZipFile(source) as archive:
            archive.extractall(unpacked)
        collection_name = "collection.anki2" if (unpacked / "collection.anki2").exists() else "collection.anki21"
        database = unpacked / collection_name
        con = sqlite3.connect(database)
        try:
            models = json.loads(con.execute("select models from col").fetchone()[0])
            referenced_mid = int(con.execute("select mid from notes limit 1").fetchone()[0])
            mutate(con, models, referenced_mid)
            con.execute("update col set models = ?", (json.dumps(models, ensure_ascii=False),))
            con.commit()
        finally:
            con.close()
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(unpacked.rglob("*")):
                if item.is_file():
                    archive.write(item, item.relative_to(unpacked).as_posix())

    def rewrite_archive(
        self,
        source: Path,
        target: Path,
        extra_entries: list[tuple[str, bytes]],
    ) -> None:
        with zipfile.ZipFile(source) as archive:
            entries = [(info.filename, archive.read(info)) for info in archive.infolist()]
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, payload in [*entries, *extra_entries]:
                archive.writestr(name, payload)

    def read_model_payload(self, source: Path) -> tuple[dict, int]:
        with zipfile.ZipFile(source) as archive:
            names = archive.namelist()
            collection_name = "collection.anki2" if "collection.anki2" in names else "collection.anki21"
            payload = archive.read(collection_name)
        with tempfile.NamedTemporaryFile(suffix=".anki2", delete=False) as handle:
            database = Path(handle.name)
            handle.write(payload)
        con = sqlite3.connect(database)
        try:
            models = json.loads(con.execute("select models from col").fetchone()[0])
            referenced_mid = con.execute("select mid from notes limit 1").fetchone()[0]
            return models, referenced_mid
        finally:
            con.close()
            database.unlink(missing_ok=True)
    def run_cli(self, apkg: Path, output_dir: Path) -> dict:
        completed = subprocess.run(
            [sys.executable, str(WORKERS / "verify_apkg.py"), str(apkg), str(output_dir)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        report = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 0 if report.get("ok") else 1, completed.stderr)
        return report
    def test_all_current_generator_variants_are_frozen(self):
        variants = [
            ("immersive_v11", "video_language", "warm_paper", "full"),
            ("immersive_v11", "video_language", "warm_paper", "fast"),
            ("ciba_tianxia_v1", "video_language", "warm_paper", "full"),
            ("ciba_tianxia_v1", "video_language", "minimal_white", "full"),
            ("ciba_tianxia_v1", "video_language", "dark_immersive", "full"),
            ("immersive", "video_language", "warm_paper", "full"),
            ("dictionary", "video_language", "warm_paper", "full"),
            ("minimal", "video_language", "warm_paper", "full"),
            ("immersive", "document_knowledge", "warm_paper", "full"),
            ("immersive", "document_reading", "warm_paper", "full"),
        ]
        self.assertEqual(len(NOTE_MODEL_CONTRACTS), len(variants) + 2)
        for template_id, deck_kind, card_style, review_density in variants:
            with self.subTest(template_id=template_id, deck_kind=deck_kind, card_style=card_style):
                label, css, qfmt, afmt = worker._legacy_worker.anki_template_assets(
                    template_id,
                    deck_kind,
                    card_style,
                    review_density,
                )
                family = worker._legacy_worker.anki_template_family(
                    template_id,
                    deck_kind,
                    card_style,
                    review_density,
                )
                schema = worker._legacy_worker.anki_template_version(template_id, deck_kind)
                contract = resolve_export_note_model_contract(family, schema, label)
                validate_generated_note_model(
                    contract,
                    field_names=note_model_field_names(
                        contract.ordered_fields_sha256 == PRESENTATION_NOTE_FIELDS_SHA256
                    ),
                    css=css,
                    qfmt=qfmt,
                    afmt=afmt,
                )

    def test_v14_contract_identity_remains_frozen_beside_v15(self):
        expected_v14 = {
            3157735470: (
                "Anki Card Generator V14 - 沉浸复读 V11",
                "532ce91006678d1241e2bc198c6ed9cfded60a81ef6a41d466fc8d7dcdffb800",
                "2c6104616c72026d5f83f7a11ba4c4af6f802c110ab5c360454ebd8ad47ff421",
                "cbf770412b097c10a647d52c0bb044b1bff93a1c13135ca8ec368c30530c1ca4",
            ),
            3446541562: (
                "Anki Card Generator V14 - 沉浸复读 V11 · 快速复读",
                "5b629c8f163f93e0a8785e41a27fcccbb6fe3df5db329f747185168e8af3f3e3",
                "5df6319768cfd1465fed37f22100bb951c2b09b8c17b395f5ab6a10a733fafd9",
                "d682bf9c66b9ceb0c1fb2acfd12935f538bb1b5bd056fa22027eb8d703507ff7",
            ),
        }
        contracts_by_id = {contract.note_model_id: contract for contract in NOTE_MODEL_CONTRACTS}
        self.assertEqual(len(contracts_by_id), len(NOTE_MODEL_CONTRACTS))
        for model_id, (name, qfmt, afmt, digest) in expected_v14.items():
            contract = contracts_by_id[model_id]
            self.assertEqual(contract.template_schema, "V14")
            self.assertEqual(contract.model_name, name)
            self.assertEqual(contract.qfmt_sha256, qfmt)
            self.assertEqual(contract.afmt_sha256, afmt)
            self.assertEqual(contract.contract_digest, digest)

        self.assertEqual(
            worker._legacy_worker.anki_template_version("immersive_v11", "video_language"),
            "V15",
        )

    def test_frozen_v14_apkg_remains_accepted_by_the_current_verifier(self):
        fixture_dir = ROOT / "tests" / "fixtures" / "apkg"
        apkg_path = fixture_dir / "v14-immersive-one-card.apkg"
        manifest = json.loads(
            (fixture_dir / "v14-immersive-one-card.manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(apkg_path.stat().st_size, manifest["size_bytes"])
        self.assertEqual(hashlib.sha256(apkg_path.read_bytes()).hexdigest(), manifest["sha256"])

        report = verify_apkg.sqlite_fallback_report(apkg_path)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["failed_checks"], [])
        self.assertEqual(report["note_count"], manifest["note_count"])
        self.assertEqual(report["card_count"], manifest["card_count"])
        self.assertEqual(report["note_model_contracts"][0]["templateSchema"], "V14")
        self.assertEqual(
            report["note_model_contracts"][0]["noteModelId"],
            manifest["note_model_id"],
        )
        self.assertEqual(
            report["note_model_contracts"][0]["contractDigest"],
            manifest["note_model_contract_digest"],
        )

    def test_real_v15_full_and_fast_packages_pass_exact_contract(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for density, card_count, expected_id in (
                ("full", 1, 1028904201),
                ("fast", 20, 5074019806),
            ):
                with self.subTest(density=density, card_count=card_count):
                    result = self.export_project(root, card_count, density)
                    self.assertEqual(result["template_family"], f"language-immersive-v11{'-fast' if density == 'fast' else ''}")
                    self.assertEqual(result["template_schema"], "V15")
                    self.assertEqual(result["template_version"], "V15")
                    self.assertEqual(result["note_model_id"], expected_id)
                    self.assertEqual(result["compatibility_contract_version"], COMPATIBILITY_CONTRACT_VERSION)
                    self.assertEqual(len(result["note_model_contract_digest"]), 64)
                    report = verify_apkg.sqlite_fallback_report(Path(result["apkg_path"]))
                    self.assertTrue(report["ok"], report)
                    self.assertEqual(report["failed_checks"], [])
                    self.assertEqual(report["note_model_contract_issues"], [])
                    self.assertEqual(report["note_count"], card_count)
                    self.assertEqual(report["note_model_contracts"][0]["noteModelId"], expected_id)

    def test_production_cli_accepts_exact_v15_and_rejects_tampered_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result = self.export_project(root)
            source = Path(result["apkg_path"])
            positive = self.run_cli(source, root / "verify-positive")
            self.assertTrue(positive["ok"], positive)
            self.assertEqual(positive["note_model_contract_issues"], [])

            target = root / "cli-invalid-name.apkg"

            def rename(_con, models, referenced_mid):
                models[str(referenced_mid)]["name"] += " copy"

            self.mutate_package(source, target, rename)
            negative = self.run_cli(target, root / "verify-negative")
            self.assertFalse(negative["ok"], negative)
            self.assertIn("note_model_contract_mismatch", negative["failed_checks"])
            self.assertIn(
                "NOTE_MODEL_NAME_MISMATCH",
                {issue["code"] for issue in negative["note_model_contract_issues"]},
            )
    def test_version_aliases_and_near_prefixes_fail_closed(self):
        invalid_names = (
            "Anki Card Generator V13 - 沉浸复读 V11",
            "Anki Card Generator V16 - 沉浸复读 V11",
            "Anki Card Generator V199 - 沉浸复读 V11",
            "Anki Card Generator V15evil - 沉浸复读 V11",
            "Anki Card Generator V15.0 - 沉浸复读 V11",
            "Anki Card Generator V015 - 沉浸复读 V11",
            " Anki Card Generator V15 - 沉浸复读 V11",
            "Anki Card Generator V15 - 沉浸复读 V11 ",
            "Anki Card Generator V15 - 沉浸复读 V11 copy",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result = self.export_project(root)
            source = Path(result["apkg_path"])
            for index, invalid_name in enumerate(invalid_names):
                with self.subTest(model_name=invalid_name):
                    target = root / f"invalid-name-{index}.apkg"

                    def mutate(_con, models, referenced_mid, name=invalid_name):
                        models[str(referenced_mid)]["name"] = name

                    self.mutate_package(source, target, mutate)
                    report = verify_apkg.sqlite_fallback_report(target)
                    self.assertFalse(report["ok"], report)
                    self.assertIn("note_model_contract_mismatch", report["failed_checks"])
                    self.assertIn(
                        "NOTE_MODEL_NAME_MISMATCH",
                        {issue["code"] for issue in report["note_model_contract_issues"]},
                    )

    def test_template_fields_and_id_tampering_fail_closed(self):
        mutations = {
            "qfmt": lambda _con, models, mid: models[str(mid)]["tmpls"][0].__setitem__("qfmt", "tampered"),
            "afmt": lambda _con, models, mid: models[str(mid)]["tmpls"][0].__setitem__("afmt", "tampered"),
            "css": lambda _con, models, mid: models[str(mid)].__setitem__("css", "tampered"),
            "field-delete": lambda _con, models, mid: models[str(mid)]["flds"].pop(),
            "field-add": lambda _con, models, mid: models[str(mid)]["flds"].append(
                {"name": "Injected", "ord": len(models[str(mid)]["flds"])}
            ),
            "field-reorder": lambda _con, models, mid: models[str(mid)]["flds"].reverse(),
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result = self.export_project(root)
            source = Path(result["apkg_path"])
            for label, mutation in mutations.items():
                with self.subTest(mutation=label):
                    target = root / f"tampered-{label}.apkg"
                    self.mutate_package(source, target, mutation)
                    report = verify_apkg.sqlite_fallback_report(target)
                    self.assertFalse(report["ok"], report)
                    self.assertIn("note_model_contract_mismatch", report["failed_checks"])

            target = root / "wrong-id.apkg"

            def change_id(con, models, referenced_mid):
                fake_mid = referenced_mid + 1
                model = models.pop(str(referenced_mid))
                model["id"] = fake_mid
                models[str(fake_mid)] = model
                con.execute("update notes set mid = ?", (fake_mid,))

            self.mutate_package(source, target, change_id)
            report = verify_apkg.sqlite_fallback_report(target)
            self.assertFalse(report["ok"], report)
            self.assertIn("UNSUPPORTED_NOTE_MODEL_ID", {issue["code"] for issue in report["note_model_contract_issues"]})

    def test_unreferenced_supported_decoy_cannot_hide_referenced_fake_model(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result = self.export_project(root)
            source = Path(result["apkg_path"])
            target = root / "decoy.apkg"

            def add_decoy(con, models, referenced_mid):
                fake_mid = referenced_mid + 777
                fake_model = json.loads(json.dumps(models[str(referenced_mid)]))
                fake_model["id"] = fake_mid
                fake_model["name"] = "Basic"
                models[str(fake_mid)] = fake_model
                con.execute("update notes set mid = ?", (fake_mid,))

            self.mutate_package(source, target, add_decoy)
            report = verify_apkg.sqlite_fallback_report(target)
            self.assertFalse(report["ok"], report)
            self.assertEqual(report["note_model_contracts"], [])
            self.assertIn("UNSUPPORTED_NOTE_MODEL_ID", {issue["code"] for issue in report["note_model_contract_issues"]})

    def test_empty_notes_and_missing_referenced_model_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result = self.export_project(root)
            source = Path(result["apkg_path"])

            empty_target = root / "empty-notes.apkg"

            def delete_notes(con, _models, _referenced_mid):
                con.execute("delete from cards")
                con.execute("delete from notes")

            self.mutate_package(source, empty_target, delete_notes)
            empty_report = verify_apkg.sqlite_fallback_report(empty_target)
            self.assertFalse(empty_report["ok"], empty_report)
            self.assertIn("NO_REFERENCED_NOTE_MODEL", {issue["code"] for issue in empty_report["note_model_contract_issues"]})

            missing_target = root / "missing-model.apkg"

            def delete_model(_con, models, referenced_mid):
                models.pop(str(referenced_mid))

            self.mutate_package(source, missing_target, delete_model)
            missing_report = verify_apkg.sqlite_fallback_report(missing_target)
            self.assertFalse(missing_report["ok"], missing_report)
            self.assertIn(
                "REFERENCED_NOTE_MODEL_MISSING",
                {issue["code"] for issue in missing_report["note_model_contract_issues"]},
            )

    def test_every_generator_variant_passes_complete_raw_model_contract(self):
        variants = [
            ("immersive_v11", "video_language", "warm_paper", "full"),
            ("immersive_v11", "video_language", "warm_paper", "fast"),
            ("ciba_tianxia_v1", "video_language", "warm_paper", "full"),
            ("ciba_tianxia_v1", "video_language", "minimal_white", "full"),
            ("ciba_tianxia_v1", "video_language", "dark_immersive", "full"),
            ("immersive", "video_language", "warm_paper", "full"),
            ("dictionary", "video_language", "warm_paper", "full"),
            ("minimal", "video_language", "warm_paper", "full"),
            ("immersive", "document_knowledge", "warm_paper", "full"),
            ("immersive", "document_reading", "warm_paper", "full"),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for index, (template_id, deck_kind, card_style, review_density) in enumerate(variants):
                with self.subTest(template_id=template_id, deck_kind=deck_kind, card_style=card_style):
                    project = self.make_project(1, review_density)
                    project.update(
                        {
                            "id": f"variant-{index}",
                            "template_id": template_id,
                            "card_style": card_style,
                        }
                    )
                    if deck_kind in {"document_knowledge", "document_reading"}:
                        project["source_mode"] = "document"
                        project["document_study_mode"] = (
                            "language_reading"
                            if deck_kind == "document_reading"
                            else "knowledge"
                        )
                        for segment in project["segments"]:
                            for card in segment["cards"]:
                                card["type"] = "knowledge"
                                card["document_card_kind"] = project["document_study_mode"]
                                card["source_evidence"] = segment["text"]
                    output_dir = root / f"variant-{index}"
                    output_dir.mkdir()
                    result = worker.handle_export({"project": project, "output_dir": str(output_dir)})
                    report = verify_apkg.sqlite_fallback_report(Path(result["apkg_path"]))
                    self.assertTrue(report["ok"], report)
                    self.assertEqual(report["note_model_contract_issues"], [])
                    package_report = validate_apkg_package_contract(
                        result["apkg_path"],
                        result,
                    )
                    self.assertTrue(package_report["ok"], package_report)
                    self.assertEqual(result["deck_kind"], deck_kind if deck_kind.startswith("document_") else "subtitle_language")
                    contract = report["note_model_contracts"][0]
                    self.assertEqual(contract["note_model_id"], result["note_model_id"])
                    self.assertEqual(
                        contract["note_model_contract_digest"],
                        result["note_model_contract_digest"],
                    )

    def test_embedded_ids_and_integer_behavior_fields_are_strict(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = Path(self.export_project(root)["apkg_path"])
            _, mid = self.read_model_payload(source)
            full_width = str(mid).translate(str.maketrans("0123456789", "０１２３４５６７８９"))
            mutations = {
                "id-missing": lambda _con, models, value: models[str(value)].pop("id"),
                "id-native-int": lambda _con, models, value: models[str(value)].__setitem__("id", value),
                "id-space": lambda _con, models, value: models[str(value)].__setitem__("id", f" {value}"),
                "id-plus": lambda _con, models, value: models[str(value)].__setitem__("id", f"+{value}"),
                "id-leading-zero": lambda _con, models, value: models[str(value)].__setitem__("id", f"0{value}"),
                "id-full-width": lambda _con, models, value: models[str(value)].__setitem__("id", full_width),
                "id-float": lambda _con, models, value: models[str(value)].__setitem__("id", float(value)),
                "id-bool": lambda _con, models, value: models[str(value)].__setitem__("id", True),
                "type-string": lambda _con, models, value: models[str(value)].__setitem__("type", "0"),
                "sortf-bool": lambda _con, models, value: models[str(value)].__setitem__("sortf", False),
                "field-ord-float": lambda _con, models, value: models[str(value)]["flds"][0].__setitem__("ord", 0.0),
                "template-ord-string": lambda _con, models, value: models[str(value)]["tmpls"][0].__setitem__("ord", "0"),
            }
            for label, mutation in mutations.items():
                with self.subTest(mutation=label):
                    target = root / f"strict-{label}.apkg"
                    self.mutate_package(source, target, mutation)
                    report = verify_apkg.sqlite_fallback_report(target)
                    self.assertFalse(report["ok"], report)
                    self.assertIn("note_model_contract_mismatch", report["failed_checks"])

            models, _ = self.read_model_payload(source)
            for bad_reference in (str(mid), float(mid), True, f" {mid}"):
                with self.subTest(reference=bad_reference):
                    report = inspect_referenced_note_models(
                        models,
                        [bad_reference],
                        require_exact_registry=True,
                        require_single_referenced_model=True,
                    )
                    self.assertIn(
                        "NOTE_MODEL_REFERENCE_ID_INVALID",
                        {issue["code"] for issue in report["issues"]},
                    )

    def test_complete_field_model_and_template_extras_are_frozen(self):
        mutations = {
            "latex-pre": lambda _con, models, mid: models[str(mid)].__setitem__("latexPre", "tampered"),
            "latex-post": lambda _con, models, mid: models[str(mid)].__setitem__("latexPost", "tampered"),
            "latex-svg": lambda _con, models, mid: models[str(mid)].__setitem__("latexsvg", True),
            "requirements": lambda _con, models, mid: models[str(mid)].__setitem__("req", []),
            "field-font": lambda _con, models, mid: models[str(mid)]["flds"][0].__setitem__("font", "Arial"),
            "field-media": lambda _con, models, mid: models[str(mid)]["flds"][0].__setitem__("media", ["x"]),
            "field-rtl": lambda _con, models, mid: models[str(mid)]["flds"][0].__setitem__("rtl", True),
            "field-size": lambda _con, models, mid: models[str(mid)]["flds"][0].__setitem__("size", 21),
            "field-sticky": lambda _con, models, mid: models[str(mid)]["flds"][0].__setitem__("sticky", True),
            "template-did": lambda _con, models, mid: models[str(mid)]["tmpls"][0].__setitem__("did", 1),
            "template-font": lambda _con, models, mid: models[str(mid)]["tmpls"][0].__setitem__("bfont", "Arial"),
            "template-size": lambda _con, models, mid: models[str(mid)]["tmpls"][0].__setitem__("bsize", 12),
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = Path(self.export_project(root)["apkg_path"])
            for label, mutation in mutations.items():
                with self.subTest(mutation=label):
                    target = root / f"behavior-{label}.apkg"
                    self.mutate_package(source, target, mutation)
                    report = verify_apkg.sqlite_fallback_report(target)
                    self.assertFalse(report["ok"], report)
                    codes = {issue["code"] for issue in report["note_model_contract_issues"]}
                    self.assertTrue(
                        codes
                        & {
                            "NOTE_MODEL_FIELD_SPECS_MISMATCH",
                            "NOTE_MODEL_EXTRAS_MISMATCH",
                            "NOTE_MODEL_TEMPLATE_EXTRAS_MISMATCH",
                        },
                        report,
                    )

    def test_non_dict_trailing_entries_and_unused_models_fail_closed(self):
        mutations = {
            "field-non-dict": lambda _con, models, mid: models[str(mid)]["flds"].append("bad"),
            "template-non-dict": lambda _con, models, mid: models[str(mid)]["tmpls"].append("bad"),
            "model-extra-key": lambda _con, models, mid: models[str(mid)].__setitem__("injected", True),
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = Path(self.export_project(root)["apkg_path"])
            for label, mutation in mutations.items():
                with self.subTest(mutation=label):
                    target = root / f"structure-{label}.apkg"
                    self.mutate_package(source, target, mutation)
                    report = verify_apkg.sqlite_fallback_report(target)
                    self.assertFalse(report["ok"], report)

            target = root / "unused-malicious-model.apkg"

            def add_unused(_con, models, referenced_mid):
                fake_mid = referenced_mid + 123
                fake_model = json.loads(json.dumps(models[str(referenced_mid)]))
                fake_model["id"] = str(fake_mid)
                fake_model["name"] = "Malicious unused model"
                models[str(fake_mid)] = fake_model

            self.mutate_package(source, target, add_unused)
            report = verify_apkg.sqlite_fallback_report(target)
            self.assertFalse(report["ok"], report)
            self.assertIn(
                "NOTE_MODEL_REGISTRY_SET_MISMATCH",
                {issue["code"] for issue in report["note_model_contract_issues"]},
            )

            target = root / "noncanonical-registry-id.apkg"

            def change_registry_key(_con, models, referenced_mid):
                models[f"0{referenced_mid}"] = models.pop(str(referenced_mid))

            self.mutate_package(source, target, change_registry_key)
            report = verify_apkg.sqlite_fallback_report(target)
            self.assertFalse(report["ok"], report)
            self.assertIn(
                "NOTE_MODEL_REGISTRY_ID_INVALID",
                {issue["code"] for issue in report["note_model_contract_issues"]},
            )

    def test_export_runs_complete_model_validation_before_packaging(self):
        legacy = worker._legacy_worker
        original = legacy.validate_generated_note_model
        calls = []

        def recording_validator(*args, **kwargs):
            calls.append(kwargs)
            return original(*args, **kwargs)

        legacy.validate_generated_note_model = recording_validator
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                result = self.export_project(Path(temp_dir))
                self.assertTrue(Path(result["apkg_path"]).is_file())
        finally:
            legacy.validate_generated_note_model = original

        complete_calls = [call for call in calls if isinstance(call.get("model_json"), dict)]
        self.assertEqual(len(complete_calls), 1)
        self.assertTrue(complete_calls[0]["deck_ids"])

    def test_generation_time_complete_model_validator_matches_package_validator(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = Path(self.export_project(root)["apkg_path"])
            models, mid = self.read_model_payload(source)
            model = models[str(mid)]
            contract = next(item for item in NOTE_MODEL_CONTRACTS if item.note_model_id == mid)
            template = model["tmpls"][0]
            validate_generated_note_model(
                contract,
                field_names=[field["name"] for field in model["flds"]],
                css=model["css"],
                qfmt=template["qfmt"],
                afmt=template["afmt"],
                model_json=model,
            )

            tampered = json.loads(json.dumps(model))
            tampered["flds"][0]["font"] = "Arial"
            with self.assertRaisesRegex(ValueError, "NOTE_MODEL_FIELD_SPECS_MISMATCH"):
                validate_generated_note_model(
                    contract,
                    field_names=[field["name"] for field in tampered["flds"]],
                    css=tampered["css"],
                    qfmt=tampered["tmpls"][0]["qfmt"],
                    afmt=tampered["tmpls"][0]["afmt"],
                    model_json=tampered,
                )
    def test_ambiguous_or_duplicate_critical_zip_entries_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = Path(self.export_project(root)["apkg_path"])
            with zipfile.ZipFile(source) as archive:
                collection_name = next(name for name in archive.namelist() if name in {"collection.anki2", "collection.anki21"})
                collection_payload = archive.read(collection_name)
                media_payload = archive.read("media")
            variants = {
                "both-collections": (
                    [("collection.anki21" if collection_name == "collection.anki2" else "collection.anki2", collection_payload)],
                    "APKG_COLLECTION_ENTRY_INVALID",
                ),
                "duplicate-collection": ([(collection_name, collection_payload)], "APKG_COLLECTION_ENTRY_INVALID"),
                "duplicate-media": ([("media", media_payload)], "APKG_MEDIA_MAP_ENTRY_INVALID"),
            }
            for label, (extra_entries, expected_code) in variants.items():
                with self.subTest(archive=label):
                    target = root / f"{label}.apkg"
                    self.rewrite_archive(source, target, extra_entries)
                    report = verify_apkg.sqlite_fallback_report(target)
                    self.assertFalse(report["ok"], report)
                    self.assertIn(
                        expected_code,
                        {issue["code"] for issue in report["note_model_contract_issues"]},
                    )

if __name__ == "__main__":
    unittest.main()
