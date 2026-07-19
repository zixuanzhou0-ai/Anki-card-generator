from __future__ import annotations

from pathlib import Path

from card_service.anki_import_execution import materialize_anki_worker_request
from card_service.artifact_registry import ArtifactRegistry
from workers.acg.apkg_package_contract import validate_apkg_package_contract


def test_authenticated_package_is_reconstructed_for_worker_without_caller_paths(
    tmp_path: Path,
) -> None:
    from tests.test_apkg_package_contract import ApkgPackageContractTests

    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    export = ApkgPackageContractTests()._fixture(
        fixture_root, card_count=2, with_media=True
    )
    registry = ArtifactRegistry(
        tmp_path / "registry",
        authentication_key=b"w" * 32,
        service_instance_id="service-anki-materialization-test",
    )
    blob = registry.put_blob_path(
        Path(export["apkg_path"]),
        media_type="application/vnd.anki.apkg",
        maximum_bytes=2 * 1024 * 1024 * 1024,
    )
    bundle = {
        "schemaVersion": 1,
        "apkgBlobRef": blob,
        "apkgSha256": export["apkg_sha256"],
        "sizeBytes": export["apkg_size_bytes"],
        "deckNames": list(export["deck_names"]),
        "cardCount": export["cards"],
        "mediaCount": len(export["media_manifest"]),
        "templateFamily": export["template_family"],
        "templateSchemaVersion": export["template_schema"],
        "cardIdentities": [
            {
                "cardId": item["card_id"],
                "sourceCardId": item["source_card_id"],
                "noteContentSha256": item["note_content_sha256"],
                "deckName": item["deck_name"],
            }
            for item in export["card_media_ledger"]
        ],
        "mediaEntries": [
            {**item, "fileName": name}
            for name, item in export["media_manifest"].items()
        ],
    }

    request = materialize_anki_worker_request(
        bundle,
        (tmp_path / "task-workspace").resolve(),
        registry,
    )

    assert set(request) == {
        "export_result",
        "import_apkg",
        "anki_connect_url",
        "wait_for_anki_seconds",
    }
    assert request["import_apkg"] is True
    assert request["anki_connect_url"] == "http://127.0.0.1:8765"
    reconstructed = request["export_result"]
    assert reconstructed["apkg_sha256"] == export["apkg_sha256"]
    assert reconstructed["cards"] == 2
    assert reconstructed["media_summary"] == {
        "media_files": 1,
        "media_bytes": len(b"offline-package-contract-audio-fixture"),
        "card_media_ledger_items": 2,
    }
    assert Path(reconstructed["apkg_path"]).is_file()
    assert (Path(reconstructed["media_dir"]) / "fixture-audio.mp3").is_file()
    assert (
        validate_apkg_package_contract(reconstructed["apkg_path"], reconstructed)["ok"]
        is True
    )

    custom_request = materialize_anki_worker_request(
        bundle,
        (tmp_path / "custom-port-workspace").resolve(),
        registry,
        anki_connect_url="http://127.0.0.1:8785/",
    )
    assert custom_request["anki_connect_url"] == "http://127.0.0.1:8785"
