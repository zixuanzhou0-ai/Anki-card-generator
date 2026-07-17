from __future__ import annotations

import argparse
import json
import urllib.request
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


def _capture_tag(url: str, tag: str) -> dict[str, Any]:
    note_ids = _anki_connect(url, "findNotes", {"query": f"tag:{tag}"})
    notes = _anki_connect(url, "notesInfo", {"notes": note_ids}) if note_ids else []
    return {
        "tag": tag,
        "note_ids": note_ids,
        "notes": [
            {
                "note_id": note["noteId"],
                "model_name": note["modelName"],
                "card_ids": note["cards"],
                "tags": sorted(note["tags"]),
                "field_names": list(note["fields"]),
                "field_values": [note["fields"][name]["value"] for name in note["fields"]],
            }
            for note in notes
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture real-Anki V14/V15 coexistence evidence.")
    parser.add_argument("--url", default="http://127.0.0.1:18819")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "schema_version": 1,
        "anki_connect_version": _anki_connect(args.url, "version"),
        "v14": _capture_tag(args.url, "anki_card_generator_v14"),
        "v15": _capture_tag(args.url, "anki_card_generator_v15"),
    }

    v14_notes = result["v14"]["notes"]
    v15_notes = result["v15"]["notes"]
    if len(v14_notes) != 1 or len(v15_notes) != 1:
        raise RuntimeError(
            f"Expected one V14 and one V15 note; received {len(v14_notes)} and {len(v15_notes)}."
        )
    if v14_notes[0]["note_id"] == v15_notes[0]["note_id"]:
        raise RuntimeError("V14 and V15 resolved to the same real-Anki note ID.")
    if v14_notes[0]["model_name"] == v15_notes[0]["model_name"]:
        raise RuntimeError("V14 and V15 unexpectedly share one real-Anki model name.")
    if v14_notes[0]["field_names"] != v15_notes[0]["field_names"]:
        raise RuntimeError("V14 and V15 field names differ in real Anki.")
    if v14_notes[0]["field_values"] != v15_notes[0]["field_values"]:
        raise RuntimeError("V14 and V15 field values differ in real Anki.")
    if len(v14_notes[0]["card_ids"]) != 1 or len(v15_notes[0]["card_ids"]) != 1:
        raise RuntimeError("Expected exactly one card for each compatibility note.")

    result["ok"] = True
    result["observed"] = {
        "v14_notes": 1,
        "v15_notes": 1,
        "cards": 2,
        "same_field_names": True,
        "same_field_values": True,
        "distinct_note_ids": True,
        "distinct_model_names": True,
    }
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["observed"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
