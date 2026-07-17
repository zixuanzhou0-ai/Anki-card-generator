from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any


def _anki_connect(url: str, action: str, params: dict[str, Any] | None = None) -> Any:
    payload = json.dumps(
        {"action": action, "version": 6, "params": params or {}},
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        result = json.loads(response.read().decode("utf-8"))
    if result.get("error"):
        raise RuntimeError(f"AnkiConnect {action} failed: {result['error']}")
    return result.get("result")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture real-Anki evidence for the final 20-card V15 media deck."
    )
    parser.add_argument("--url", default="http://127.0.0.1:18820")
    parser.add_argument("--export-result", required=True, type=Path)
    parser.add_argument("--media-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    export_result = json.loads(args.export_result.read_text(encoding="utf-8"))
    deck_name = str(export_result["deck_name"])
    expected_model = str(export_result["model_name"])
    expected_tag = str(export_result["anki_tag"])
    expected_manifest = dict(export_result["media_manifest"])
    apkg_path = Path(export_result["apkg_path"])
    expected_apkg_sha256 = str(export_result["apkg_sha256"])

    note_ids = list(
        _anki_connect(args.url, "findNotes", {"query": f'deck:"{deck_name}"'}) or []
    )
    notes = list(_anki_connect(args.url, "notesInfo", {"notes": note_ids}) or [])
    card_ids = sorted(
        int(card_id)
        for note in notes
        for card_id in list(note.get("cards") or [])
    )
    cards = list(_anki_connect(args.url, "cardsInfo", {"cards": card_ids}) or [])

    if len(note_ids) != 20 or len(notes) != 20:
        raise RuntimeError(
            f"Expected 20 V15 notes in real Anki; received {len(note_ids)} IDs and "
            f"{len(notes)} note records."
        )
    if len(card_ids) != 20 or len(cards) != 20:
        raise RuntimeError(
            f"Expected 20 V15 cards in real Anki; received {len(card_ids)} IDs and "
            f"{len(cards)} card records."
        )
    if len(set(note_ids)) != 20 or len(set(card_ids)) != 20:
        raise RuntimeError("Real Anki returned duplicate V15 note or card IDs.")
    if any(note.get("modelName") != expected_model for note in notes):
        raise RuntimeError("At least one real-Anki note uses the wrong V15 model.")
    if any(expected_tag not in list(note.get("tags") or []) for note in notes):
        raise RuntimeError("At least one real-Anki note is missing the V15 schema tag.")
    if any(card.get("deckName") != deck_name for card in cards):
        raise RuntimeError("At least one real-Anki card resolved outside the expected deck.")

    media_dir = args.media_dir.resolve()
    actual_files = {
        path.name: path
        for path in media_dir.iterdir()
        if path.is_file() and not path.name.startswith("_")
    }
    expected_names = set(expected_manifest)
    actual_names = set(actual_files)
    missing_media = sorted(expected_names - actual_names)
    unexpected_media = sorted(actual_names - expected_names)
    hash_mismatches = []
    for name in sorted(expected_names & actual_names):
        expected_sha256 = str(expected_manifest[name]["sha256"]).lower()
        actual_sha256 = _sha256(actual_files[name])
        if actual_sha256 != expected_sha256:
            hash_mismatches.append(
                {
                    "name": name,
                    "expected_sha256": expected_sha256,
                    "actual_sha256": actual_sha256,
                }
            )
    if missing_media or unexpected_media or hash_mismatches:
        raise RuntimeError(
            "Real-Anki media evidence mismatch: "
            f"missing={len(missing_media)}, unexpected={len(unexpected_media)}, "
            f"hash_mismatches={len(hash_mismatches)}."
        )
    if len(expected_names) != 52:
        raise RuntimeError(f"Expected a 52-file export manifest; received {len(expected_names)}.")
    actual_apkg_sha256 = _sha256(apkg_path)
    if actual_apkg_sha256 != expected_apkg_sha256:
        raise RuntimeError("The APKG hash changed after export.")

    queue_counts = Counter(str(card.get("queue")) for card in cards)
    type_counts = Counter(str(card.get("type")) for card in cards)
    result = {
        "schema_version": 1,
        "ok": True,
        "anki_connect_version": _anki_connect(args.url, "version"),
        "deck_name": deck_name,
        "model_name": expected_model,
        "template_schema": export_result["template_schema"],
        "note_model_id": export_result["note_model_id"],
        "note_model_contract_digest": export_result["note_model_contract_digest"],
        "anki_tag": expected_tag,
        "apkg_sha256": actual_apkg_sha256,
        "note_count": len(notes),
        "card_count": len(cards),
        "unique_note_ids": len(set(note_ids)),
        "unique_card_ids": len(set(card_ids)),
        "media_count": len(actual_files),
        "media_hash_matches": len(expected_names),
        "missing_media": missing_media,
        "unexpected_media": unexpected_media,
        "media_hash_mismatches": hash_mismatches,
        "queue_counts": dict(sorted(queue_counts.items())),
        "type_counts": dict(sorted(type_counts.items())),
    }

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
