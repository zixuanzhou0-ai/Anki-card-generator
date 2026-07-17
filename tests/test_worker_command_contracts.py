from __future__ import annotations

import ast
import copy
import io
import json
import re
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
WORKERS = ROOT / "workers"
SCHEMA_PATH = WORKERS / "worker-command-contract.v1.schema.json"
GOLDEN_PATH = ROOT / "tests" / "worker-command-contract.v1.golden.json"

if str(WORKERS) not in sys.path:
    sys.path.insert(0, str(WORKERS))

from acg import errors as worker_errors  # noqa: E402
from acg import protocol  # noqa: E402


EXPECTED_COMMANDS = {
    "check_env",
    "repair_env",
    "test_api",
    "test_tts",
    "extract_learning_points",
    "generate_cards_from_learning_points",
    "generate",
    "export",
    "verify_anki_import",
}


class ContractValidationError(AssertionError):
    pass


def _resolve_ref(root_schema: dict[str, Any], reference: str) -> Any:
    if not reference.startswith("#/"):
        raise ContractValidationError(f"unsupported external reference: {reference}")
    current: Any = root_schema
    for raw_part in reference[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        current = current[part]
    return current


def _matches_type(instance: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(instance, dict)
    if expected == "array":
        return isinstance(instance, list)
    if expected == "string":
        return isinstance(instance, str)
    if expected == "boolean":
        return isinstance(instance, bool)
    if expected == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    if expected == "number":
        return isinstance(instance, (int, float)) and not isinstance(instance, bool)
    if expected == "null":
        return instance is None
    raise ContractValidationError(f"unsupported JSON Schema type in contract test: {expected}")


def _validate(instance: Any, schema: Any, root_schema: dict[str, Any], path: str = "$") -> None:
    if schema is True or schema == {}:
        return
    if schema is False:
        raise ContractValidationError(f"{path}: false schema")
    if not isinstance(schema, dict):
        raise ContractValidationError(f"{path}: schema is not an object")

    reference = schema.get("$ref")
    if reference:
        _validate(instance, _resolve_ref(root_schema, reference), root_schema, path)

    for subschema in schema.get("allOf", []):
        _validate(instance, subschema, root_schema, path)

    if "not" in schema:
        try:
            _validate(instance, schema["not"], root_schema, path)
        except ContractValidationError:
            pass
        else:
            raise ContractValidationError(f"{path}: forbidden schema matched")

    any_of = schema.get("anyOf")
    if any_of:
        matches = 0
        failures: list[str] = []
        for subschema in any_of:
            try:
                _validate(instance, subschema, root_schema, path)
                matches += 1
            except ContractValidationError as error:
                failures.append(str(error))
        if matches == 0:
            raise ContractValidationError(f"{path}: no anyOf branch matched: {failures}")

    one_of = schema.get("oneOf")
    if one_of:
        matches = 0
        failures: list[str] = []
        for subschema in one_of:
            try:
                _validate(instance, subschema, root_schema, path)
                matches += 1
            except ContractValidationError as error:
                failures.append(str(error))
        if matches != 1:
            raise ContractValidationError(
                f"{path}: expected exactly one oneOf match, got {matches}; failures={failures}"
            )

    if "const" in schema and instance != schema["const"]:
        raise ContractValidationError(f"{path}: expected const {schema['const']!r}, got {instance!r}")
    if "enum" in schema and instance not in schema["enum"]:
        raise ContractValidationError(f"{path}: {instance!r} is not in {schema['enum']!r}")

    expected_type = schema.get("type")
    if expected_type is not None:
        expected_types = expected_type if isinstance(expected_type, list) else [expected_type]
        if not any(_matches_type(instance, item) for item in expected_types):
            raise ContractValidationError(
                f"{path}: expected type {expected_types!r}, got {type(instance).__name__}"
            )

    if isinstance(instance, dict):
        required = schema.get("required", [])
        missing = [key for key in required if key not in instance]
        if missing:
            raise ContractValidationError(f"{path}: missing required keys {missing!r}")

        properties = schema.get("properties", {})
        for key, subschema in properties.items():
            if key in instance:
                _validate(instance[key], subschema, root_schema, f"{path}.{key}")

        extra_keys = set(instance) - set(properties)
        additional = schema.get("additionalProperties", True)
        if additional is False and extra_keys:
            raise ContractValidationError(f"{path}: additional keys are forbidden: {sorted(extra_keys)!r}")
        if isinstance(additional, dict):
            for key in extra_keys:
                _validate(instance[key], additional, root_schema, f"{path}.{key}")

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < int(schema["minItems"]):
            raise ContractValidationError(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(instance) > int(schema["maxItems"]):
            raise ContractValidationError(f"{path}: more than {schema['maxItems']} items")
        item_schema = schema.get("items")
        if item_schema is not None:
            for index, item in enumerate(instance):
                _validate(item, item_schema, root_schema, f"{path}[{index}]")
        if schema.get("uniqueItems"):
            canonical_items = [
                json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                for item in instance
            ]
            if len(set(canonical_items)) != len(canonical_items):
                raise ContractValidationError(f"{path}: array items must be unique")

    if isinstance(instance, str) and "minLength" in schema and len(instance) < int(schema["minLength"]):
        raise ContractValidationError(f"{path}: string is shorter than {schema['minLength']}")
    if isinstance(instance, str) and "pattern" in schema and re.search(str(schema["pattern"]), instance) is None:
        raise ContractValidationError(f"{path}: string does not match pattern {schema['pattern']!r}")

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            raise ContractValidationError(f"{path}: {instance} is below minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            raise ContractValidationError(f"{path}: {instance} is above maximum {schema['maximum']}")


def _load_contract() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    return schema, golden


def _dispatch_table_from_source() -> dict[str, str]:
    source_path = WORKERS / "anki_worker.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    for node in tree.body:
        target: ast.expr | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.AnnAssign):
            target = node.target
            value = node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            value = node.value
        if not isinstance(target, ast.Name) or target.id != "COMMANDS" or not isinstance(value, ast.Dict):
            continue
        mapping: dict[str, str] = {}
        for key, handler in zip(value.keys, value.values, strict=True):
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                raise AssertionError("COMMANDS must keep literal string keys")
            if not isinstance(handler, ast.Name):
                raise AssertionError(f"handler for {key.value} must remain a named callable")
            mapping[key.value] = handler.id
        return mapping
    raise AssertionError("workers/anki_worker.py does not define a literal COMMANDS mapping")


def _literal_progress_pairs() -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    emit_pattern = re.compile(
        r"emit_progress\(\s*['\"](?P<command>[^'\"]+)['\"]\s*,\s*['\"](?P<stage>[^'\"]+)['\"]",
        re.DOTALL,
    )
    export_pattern = re.compile(r"emit_export_progress\(\s*['\"](?P<stage>[^'\"]+)['\"]", re.DOTALL)
    repair_pattern = re.compile(r"run_repair_step\(\s*['\"](?P<stage>[^'\"]+)['\"]", re.DOTALL)
    for source_path in (WORKERS / "acg").rglob("*.py"):
        source = source_path.read_text(encoding="utf-8")
        pairs.update((match.group("command"), match.group("stage")) for match in emit_pattern.finditer(source))
        if source_path.name == "legacy_worker.py":
            pairs.update(("export", match.group("stage")) for match in export_pattern.finditer(source))
            pairs.update(("repair_env", match.group("stage")) for match in repair_pattern.finditer(source))
    return pairs


def _secret_key_paths(value: Any, path: str = "$") -> list[str]:
    from acg.commands.generate_cards_from_learning_points import _is_runtime_secret_key

    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if _is_runtime_secret_key(key):
                found.append(child_path)
            found.extend(_secret_key_paths(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_secret_key_paths(child, f"{path}[{index}]"))
    return found

class WorkerCommandContractTests(unittest.TestCase):
    def test_golden_exchanges_validate_against_versioned_schema(self) -> None:
        schema, golden = _load_contract()
        _validate(golden, schema, schema)
        metadata = schema["x-acg-contract"]
        self.assertEqual(metadata["contract_version"], "1.0.0")
        self.assertEqual(metadata["worker_schema_version"], worker_errors.SCHEMA_VERSION)
        self.assertEqual({item["command"] for item in golden}, EXPECTED_COMMANDS)
        self.assertEqual(len({item["command"] for item in golden}), len(golden))
        self.assertTrue(all(item["result"]["schema_version"] == worker_errors.SCHEMA_VERSION for item in golden))
        self.assertTrue(all(item["error"]["schema_version"] == worker_errors.SCHEMA_VERSION for item in golden))

    def test_contract_command_set_matches_live_dispatch_table(self) -> None:
        dispatch = _dispatch_table_from_source()
        self.assertEqual(set(dispatch), EXPECTED_COMMANDS)
        self.assertTrue(all(name.startswith("handle_") for name in dispatch.values()))
        _, golden = _load_contract()
        self.assertEqual({item["command"] for item in golden}, set(dispatch))

    def test_declared_progress_stages_cover_literal_worker_emitters(self) -> None:
        schema, golden = _load_contract()
        metadata = schema["x-acg-contract"]
        declared = {command: set(stages) for command, stages in metadata["progress_stages"].items()}
        observed = _literal_progress_pairs()
        unknown = sorted((command, stage) for command, stage in observed if stage not in declared.get(command, set()))
        self.assertEqual(unknown, [])
        observed_commands = {command for command, _ in observed if command in EXPECTED_COMMANDS}
        self.assertEqual(observed_commands, set(metadata["progress_emitting_commands"]))
        for exchange in golden:
            command = exchange["command"]
            for progress in exchange["progress"]:
                self.assertEqual(progress["command"], command)
                self.assertIn(progress["stage"], declared[command])

    def test_core_error_codes_are_frozen_but_wire_error_code_is_open(self) -> None:
        schema, _ = _load_contract()
        metadata = schema["x-acg-contract"]
        self.assertEqual(metadata["core_error_codes"], sorted(worker_errors.WORKER_ERROR_CODES))
        error_code_schema = schema["$defs"]["WorkerError"]["properties"]["error_code"]
        self.assertNotIn("enum", error_code_schema)

    def test_wire_protocol_prefixes_and_schema_injection_match_contract(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            protocol.emit({"ok": True})
        success = json.loads(stdout.getvalue())
        self.assertEqual(success, {"schema_version": worker_errors.SCHEMA_VERSION, "ok": True})

        stderr = io.StringIO()
        with redirect_stderr(stderr):
            protocol.emit_progress(
                "export",
                "package",
                150,
                "Writing fixture APKG.",
                **{
                    "schema_version": 999,
                    "command": "forged_command",
                    "stage": "forged_stage",
                    "percent": -1,
                    "message": "forged message",
                },
                completed_batches=1,
                total_batches=1,
            )
        progress_line = stderr.getvalue().strip()
        self.assertTrue(progress_line.startswith(protocol.PROGRESS_PREFIX))
        progress = json.loads(progress_line[len(protocol.PROGRESS_PREFIX) :])
        self.assertEqual(progress["percent"], 100)
        self.assertEqual(progress["schema_version"], worker_errors.SCHEMA_VERSION)
        self.assertEqual(progress["command"], "export")
        self.assertEqual(progress["stage"], "package")
        self.assertEqual(progress["message"], "Writing fixture APKG.")
        self.assertEqual(progress["completed_batches"], 1)
        self.assertEqual(progress["total_batches"], 1)

        stderr = io.StringIO()
        with redirect_stderr(stderr), self.assertRaises(SystemExit) as exit_context:
            protocol.fail(
                "Fixture failure.",
                code=7,
                error_code="FIXTURE_EXTENSION_CODE",
                stage="fixture",
                retryable=True,
                fallbacks=["retry_fixture"],
                details={"fixture": True},
            )
        self.assertEqual(exit_context.exception.code, 7)
        error_lines = stderr.getvalue().splitlines()
        self.assertTrue(error_lines[0].startswith(protocol.ERROR_PREFIX))
        error = json.loads(error_lines[0][len(protocol.ERROR_PREFIX) :])
        self.assertEqual(error["schema_version"], worker_errors.SCHEMA_VERSION)
        self.assertEqual(error["error_code"], "FIXTURE_EXTENSION_CODE")
        self.assertEqual(error_lines[1], "Fixture failure.")

    def test_stdin_transport_tolerates_bom_and_empty_payload(self) -> None:
        original_stdin = sys.stdin
        try:
            sys.stdin = io.StringIO("\ufeff{\"fixture\": true}")
            self.assertEqual(protocol.read_payload(), {"fixture": True})
            sys.stdin = io.StringIO("  \n")
            self.assertEqual(protocol.read_payload(), {})
        finally:
            sys.stdin = original_stdin

    def test_anki_verify_query_progress_never_regresses_after_import(self) -> None:
        from acg.legacy_worker import anki_verify_query_progress_percent

        self.assertEqual(anki_verify_query_progress_percent(False), 18)
        self.assertEqual(anki_verify_query_progress_percent(True), 62)

        _, golden = _load_contract()
        verify_exchange = next(item for item in golden if item["command"] == "verify_anki_import")
        import_index = next(
            index for index, frame in enumerate(verify_exchange["progress"]) if frame["stage"] == "import"
        )
        query_index = next(
            index for index, frame in enumerate(verify_exchange["progress"]) if frame["stage"] == "query"
        )
        self.assertLess(import_index, query_index)
        self.assertEqual(verify_exchange["progress"][import_index]["percent"], 55)
        self.assertEqual(verify_exchange["progress"][query_index]["percent"], 62)

    def test_export_contract_requires_all_production_anki_verify_evidence(self) -> None:
        schema, golden = _load_contract()
        export_schema = schema["$defs"]["ExportResult"]
        required = set(export_schema["required"])
        preflight_required = {
            "schema_version",
            "apkg_path",
            "apkg_sha256",
            "apkg_size_bytes",
            "apkg_mtime_ms",
            "media_dir",
            "deck_name",
            "deck_names",
            "deck_kind",
            "template_family",
            "template_schema",
            "template_version",
            "template_name",
            "note_model_id",
            "model_name",
            "compatibility_contract_version",
            "note_model_contract_digest",
            "anki_tag",
            "media_manifest",
            "media_ledger",
            "card_media_ledger",
            "media_summary",
            "note_content_fingerprint",
            "cards",
        }
        verify_evidence_required = {
            *preflight_required,
            "segments",
            "timing_ms",
            "warnings",
        }
        self.assertEqual(set(export_schema["x-anki-import-preflight-required"]), preflight_required)
        self.assertLessEqual(verify_evidence_required, required)
        self.assertLessEqual(verify_evidence_required, set(export_schema["properties"]))

        export_result = next(item["result"] for item in golden if item["command"] == "export")
        for field in sorted(verify_evidence_required):
            invalid = copy.deepcopy(export_result)
            invalid.pop(field)
            with self.subTest(field=field), self.assertRaises(ContractValidationError):
                _validate(invalid, export_schema, schema, "$.export.result")

    def test_golden_current_export_result_is_the_complete_verify_input(self) -> None:
        from acg.anki_model_contracts import NOTE_MODEL_CONTRACTS, note_model_field_names

        schema, golden = _load_contract()
        export_exchange = next(item for item in golden if item["command"] == "export")
        verify_exchange = next(item for item in golden if item["command"] == "verify_anki_import")
        export_result = export_exchange["result"]
        self.assertEqual(verify_exchange["request"]["export_result"], export_result)
        _validate(
            verify_exchange["request"],
            schema["$defs"]["VerifyAnkiImportRequest"],
            schema,
            "$.verify.request",
        )

        current_contract = next(
            contract
            for contract in NOTE_MODEL_CONTRACTS
            if contract.template_family == "language-immersive-v11"
            and contract.template_schema == "V15"
        )
        self.assertEqual(export_result["template_family"], current_contract.template_family)
        self.assertEqual(export_result["template_schema"], current_contract.template_schema)
        self.assertEqual(export_result["template_version"], current_contract.template_schema)
        self.assertEqual(export_result["note_model_id"], current_contract.note_model_id)
        self.assertEqual(export_result["model_name"], current_contract.model_name)
        self.assertEqual(export_result["note_model_contract_digest"], current_contract.contract_digest)
        fingerprint = export_result["note_content_fingerprint"]
        self.assertEqual(fingerprint["field_names"], list(note_model_field_names(True)))
        self.assertEqual(fingerprint["card_count"], export_result["cards"])
        self.assertEqual(fingerprint["card_count"], len(export_result["card_media_ledger"]))

    def test_media_ledger_schema_requires_runtime_ownership_fields(self) -> None:
        schema, golden = _load_contract()
        media_schema = schema["$defs"]["ExportMediaLedgerItem"]
        media_item = copy.deepcopy(
            next(item["result"] for item in golden if item["command"] == "export")["media_ledger"][0]
        )
        for field in ("segment_id", "card_id", "field"):
            invalid = copy.deepcopy(media_item)
            invalid.pop(field)
            with self.subTest(field=field), self.assertRaises(ContractValidationError):
                _validate(invalid, media_schema, schema, "$.export.result.media_ledger[0]")

    def test_card_media_ledger_schema_requires_exact_note_tags(self) -> None:
        schema, golden = _load_contract()
        ledger_schema = schema["$defs"]["ExportCardMediaLedgerItem"]
        ledger_item = copy.deepcopy(
            next(item["result"] for item in golden if item["command"] == "export")[
                "card_media_ledger"
            ][0]
        )
        _validate(ledger_item, ledger_schema, schema, "$.export.result.card_media_ledger[0]")

        invalid_items = {
            "missing": {key: value for key, value in ledger_item.items() if key != "note_tags"},
            "too_few": {**ledger_item, "note_tags": ledger_item["note_tags"][:-1]},
            "too_many": {**ledger_item, "note_tags": [*ledger_item["note_tags"], "extra_tag"]},
            "duplicate": {
                **ledger_item,
                "note_tags": [*ledger_item["note_tags"][:-1], ledger_item["note_tags"][0]],
            },
            "blank": {**ledger_item, "note_tags": [*ledger_item["note_tags"][:-1], ""]},
            "whitespace": {
                **ledger_item,
                "note_tags": [*ledger_item["note_tags"][:-1], "invalid tag"],
            },
        }
        for case, invalid in invalid_items.items():
            with self.subTest(case=case), self.assertRaises(ContractValidationError):
                _validate(invalid, ledger_schema, schema, "$.export.result.card_media_ledger[0]")

    def test_anki_write_requests_require_the_complete_export_result(self) -> None:
        schema, golden = _load_contract()
        request_schema = schema["$defs"]["VerifyAnkiImportRequest"]
        export_result = next(item["result"] for item in golden if item["command"] == "export")

        valid_requests = [
            {"export_result": export_result, "import_apkg": True},
            {"export_result": export_result, "import_apkg": False, "prepare_media_only": True},
            {"anki_query": "deck:fixture"},
        ]
        for request in valid_requests:
            _validate(request, request_schema, schema, "$.verify.request")

        invalid_requests = [
            {"apkg_path": "E:\\fixture\\output\\Fixture.apkg", "import_apkg": True},
            {"deck_name": "Fixture lesson", "prepare_media_only": True},
            {"anki_query": "deck:fixture", "import_apkg": True},
            {"anki_query": "deck:fixture", "export_result": export_result},
        ]
        for request in invalid_requests:
            with self.assertRaises(ContractValidationError):
                _validate(request, request_schema, schema, "$.verify.request")

    def test_note_content_fingerprint_contract_is_strict(self) -> None:
        schema, golden = _load_contract()
        fingerprint_schema = schema["$defs"]["NoteContentFingerprint"]
        export_result = next(item["result"] for item in golden if item["command"] == "export")
        fingerprint = export_result["note_content_fingerprint"]
        _validate(fingerprint, fingerprint_schema, schema, "$.export.result.note_content_fingerprint")

        invalid_fingerprints = {
            "empty_fields": {**fingerprint, "field_names": []},
            "blank_field": {**fingerprint, "field_names": ["CardId", ""]},
            "whitespace_field": {**fingerprint, "field_names": ["CardId", "  "]},
            "padded_field": {**fingerprint, "field_names": ["CardId", " Answer"]},
            "duplicate_fields": {**fingerprint, "field_names": ["CardId", "CardId"]},
            "zero_cards": {**fingerprint, "card_count": 0},
            "wrong_schema": {**fingerprint, "schema_version": 2},
            "wrong_algorithm": {**fingerprint, "algorithm": "sha1"},
            "wrong_serialization": {**fingerprint, "serialization": "json-v0"},
            "extra_property": {**fingerprint, "unexpected": True},
        }
        for case, invalid in invalid_fingerprints.items():
            with self.subTest(case=case), self.assertRaises(ContractValidationError):
                _validate(invalid, fingerprint_schema, schema, "$.fingerprint")

        invalid_export = copy.deepcopy(export_result)
        invalid_export["card_media_ledger"][0]["note_content_sha256"] = "not-a-sha256"
        with self.assertRaises(ContractValidationError):
            _validate(invalid_export, schema["$defs"]["ExportResult"], schema, "$.export.result")

        zero_card_export = copy.deepcopy(export_result)
        zero_card_export["cards"] = 0
        with self.assertRaises(ContractValidationError):
            _validate(zero_card_export, schema["$defs"]["ExportResult"], schema, "$.export.result")

    def test_project_result_runtime_configs_are_recursively_scrubbed(self) -> None:
        from acg.commands.generate_cards_from_learning_points import _without_runtime_secrets

        source = {
            "provider": "fixture",
            "api_key": "model-secret",
            "client_secret": "client-secret",
            "privateKey": "private-secret",
            "token_value": "token-secret",
            "nested": {
                "access_token": "access-secret",
                "headers": {"Authorization": "Bearer secret"},
                "tts_config": {"voice": "fixture", "api_key": "tts-secret"},
            },
            "items": [{"cookie": "cookie-secret", "model": "fixture-model"}],
            "credential_revision": 4,
            "client_secret_ref": "keyring:model",
            "has_api_key": True,
        }
        sanitized = _without_runtime_secrets(source)
        self.assertEqual(sanitized["provider"], "fixture")
        self.assertEqual(sanitized["nested"]["tts_config"]["voice"], "fixture")
        self.assertEqual(sanitized["items"][0]["model"], "fixture-model")
        self.assertEqual(sanitized["api_key"], "")
        self.assertEqual(sanitized["nested"]["access_token"], "")
        self.assertEqual(sanitized["nested"]["tts_config"]["api_key"], "")
        self.assertEqual(sanitized["items"][0]["cookie"], "")
        self.assertEqual(sanitized["client_secret"], "")
        self.assertEqual(sanitized["privateKey"], "")
        self.assertEqual(sanitized["token_value"], "")
        self.assertEqual(sanitized["nested"]["headers"]["Authorization"], "")
        self.assertEqual(sanitized["credential_revision"], 4)
        self.assertEqual(sanitized["client_secret_ref"], "keyring:model")
        self.assertTrue(sanitized["has_api_key"])
        self.assertEqual(source["api_key"], "model-secret")
    def test_genanki_note_model_serializer_is_exactly_pinned(self) -> None:
        requirements = (WORKERS / "requirements.txt").read_text(encoding="utf-8").splitlines()
        self.assertIn("genanki==0.13.1", requirements)
        self.assertIn("yt-dlp[default,curl-cffi]==2026.7.4", requirements)
        self.assertIn("pypdf==6.14.2", requirements)
        self.assertIn("cryptography==49.0.0", requirements)
        self.assertFalse(any(">=" in line or "~=" in line for line in requirements))
    def test_golden_fixtures_do_not_contain_secrets(self) -> None:
        _, golden = _load_contract()
        self.assertEqual(_secret_key_paths(golden), [])
        schema, _ = _load_contract()
        self.assertEqual(schema["x-acg-contract"]["sensitive_result_passthrough_paths"], [])


if __name__ == "__main__":
    unittest.main()
