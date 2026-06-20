from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: seed_smoke_tts_cache.py WORKER_ROOT")

    worker_root = Path(sys.argv[1])
    sys.path.insert(0, str(worker_root))

    from acg.export_fields import card_sentence_tts_text
    from acg.legacy_worker import (
        card_front_fields,
        card_phrase_tts_text,
        normalized_tts_config,
        tts_cache_path,
        uses_v11_repetition_front,
    )

    project = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
    deck_kind = str(project.get("deck_kind") or project.get("project_kind") or "")
    if not deck_kind:
        deck_kind = "document_knowledge" if project.get("source_mode") == "document" else "video_language"
    template_id = str(project.get("template_id") or "immersive_v11")
    project_uses_repetition = uses_v11_repetition_front(template_id, deck_kind)
    tts = normalized_tts_config(project)

    items: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add_item(kind: str, text: object) -> None:
        normalized_text = str(text or "").strip()
        if not normalized_text:
            return
        key = (kind, normalized_text.lower())
        if key in seen:
            return
        seen.add(key)
        path, cache_key = tts_cache_path(tts, normalized_text, project.get("language", "en"))
        items.append(
            {
                "kind": kind,
                "text": normalized_text,
                "path": str(path),
                "cache_key": cache_key,
            }
        )

    for segment in project.get("segments") or []:
        cards = [card for card in segment.get("cards") or [] if card.get("enabled", True)]
        add_item("sentence", card_sentence_tts_text(segment, cards))
        for card in cards:
            repetition_mode = project_uses_repetition or str(card.get("card_layout") or "").lower() == "repetition"
            front_fields = card_front_fields(card, repetition_mode=repetition_mode)
            add_item("phrase", card_phrase_tts_text(card, front_fields))

    print(json.dumps(items, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
