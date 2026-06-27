from __future__ import annotations

import re
from typing import Any

from acg import legacy_worker
from acg.learning_types import candidate_kind_allowed_by_focus, phrase_type_for_candidate_kind
from acg.learning_spans import normalize_candidate_span, normalized_phrase_key

LOCAL_PATTERNS: list[tuple[str, str, str, str, float, str]] = [
    (r"\bfigure\s+(?:it\s+)?out\b", "phrase", "expression", "collocation", 4.2, "训练 figure out 表达“弄明白/解决”。"),
    (r"\bmake\s+sure\b", "phrase", "expression", "collocation", 4.0, "训练 make sure 表达确认、确保。"),
    (r"\bright\s+now\b", "spoken", "expression", "spoken_phrase", 3.2, "训练 right now 表达当前时间或当下语气。"),
    (r"\bend\s+up\b(?:\s+\w+){0,3}", "phrase", "expression", "spoken_phrase", 4.0, "训练 end up 表达最终结果。"),
    (r"\bturns?\s+out\b", "spoken", "expression", "discourse_marker", 4.1, "训练 it turns out 引出真实结果或反转。"),
    (r"\bin\s+the\s+mood\s+for\b", "phrase", "expression", "collocation", 4.3, "训练表达“有心情/没心情做某事”。"),
    (r"\bcome\s+up\s+with\b", "phrase", "expression", "collocation", 4.1, "训练 come up with 表达想出方案。"),
    (r"\bget\s+away\s+with\b", "phrase", "expression", "collocation", 4.2, "训练 get away with 表达做了坏事没受罚。"),
    (r"\bmessing\s+with\s+(?:me|you|him|her|us|them)\b", "phrase", "expression", "spoken_phrase", 4.2, "训练 messing with someone 表达戏弄、耍人或干扰。"),
    (r"\btake\s+it\s+personally\b", "phrase", "expression", "spoken_phrase", 4.1, "训练 take it personally 表达往心里去。"),
    (r"\b(?:take|takes|took|taken|taking)\s+a\s+toll\s+on\b", "phrase", "expression", "collocation", 4.3, "训练 take a toll on 表示对身心或状态造成负面影响的搭配。"),
    (r"\bunder\s+pressure\b", "phrase", "expression", "collocation", 4.0, "训练 under pressure 表示处于压力下的自然搭配。"),
    (r"\bhave\s+a\s+break\s+for\b(?:\s+\w+){0,3}", "phrase", "expression", "collocation", 3.8, "训练 have a break for + 时长表示休息一段时间。"),
    (r"\brun\s+into\b", "phrase", "expression", "collocation", 4.0, "训练 run into 表达偶遇或遇到问题。"),
    (r"\blet\s+(?:me|you|him|her|us|them|someone|somebody)\s+down\b", "phrase", "expression", "spoken_phrase", 4.0, "训练 let someone down 表达让人失望。"),
    (r"\btaste\s+the\s+difference\b", "phrase", "expression", "collocation", 4.0, "训练 taste the difference 这种广告/生活场景表达。"),
    (r"\brun\s+the\s+register\b", "phrase", "expression", "collocation", 4.4, "训练服务业场景里“负责收银/操作收银机”。"),
    (r"\bor\s+something\b", "spoken", "expression", "discourse_marker", 3.8, "训练 or something 表达不确定补充。"),
    (r"\bkind\s+of\b", "spoken", "expression", "discourse_marker", 3.8, "训练 kind of 表达弱化、模糊或语气缓冲。"),
    (r"\bsort\s+of\b", "spoken", "expression", "discourse_marker", 3.8, "训练 sort of 表达弱化、模糊或语气缓冲。"),
    (r"\bi\s+mean\b", "spoken", "expression", "discourse_marker", 3.9, "训练 I mean 作为解释或修正话语标记。"),
    (r"\byou\s+know\b", "spoken", "expression", "discourse_marker", 3.6, "训练 you know 作为口语填充/确认共识。"),
    (r"\bi\s+guess\b", "spoken", "expression", "spoken_phrase", 3.8, "训练 I guess 表达保留态度。"),
    (r"\bnot\s+really\b", "spoken", "expression", "spoken_phrase", 4.0, "训练 not really 的自然否定和缓冲。"),
    (r"\bjust\b", "spoken", "expression", "discourse_marker", 3.2, "训练 just 在口语中弱化、强调或补充语气。"),
    (r"\bthe\s+thing\s+is\b", "spoken", "expression", "discourse_marker", 4.1, "训练 the thing is 引出关键解释。"),
    (r"\bby\s+the\s+way\b", "spoken", "expression", "discourse_marker", 3.9, "训练 by the way 转换话题。"),
    (r"\bwhat'?s\s+up\s+for\b(?:\s+\w+){0,3}", "spoken", "expression", "spoken_phrase", 4.0, "训练 what's up for + 时间，询问安排。"),
    (r"\bit'?s\s+not\s+that\b.+?\bit'?s\s+just\s+that\b", "grammar", "grammar_pattern", "grammar_pattern", 4.5, "训练 It's not that..., it's just that... 解释原因框架。"),
    (r"\bwhat\s+i\s+don'?t\s+understand\s+is\b", "grammar", "grammar_pattern", "grammar_pattern", 4.2, "训练 What I don't understand is... 提出疑问焦点。"),
    (r"\bthe\s+more\b.+?\bthe\s+more\b", "grammar", "grammar_pattern", "grammar_pattern", 4.4, "训练 The more..., the more... 递进比较框架。"),
    (r"\bi\s+was\s+wondering\s+if\b", "grammar", "grammar_pattern", "grammar_pattern", 4.1, "训练 I was wondering if... 的委婉请求。"),
    (r"\b(?:want\s+to|wanna|going\s+to|gonna|did\s+you|kind\s+of|sort\s+of)\b", "listening", "listening_feature", "listening_sentence", 3.6, "训练字幕推测的弱读、缩读或连读听辨点。"),
    (r"\bno\s+offense,\s+but\b", "pragmatic", "pragmatic_risk", "discourse_marker", 4.0, "识别 no offense, but... 的冒犯风险和语气边界。"),
    (r"\bi\s+don'?t\s+mean\s+to\s+be\s+rude,\s+but\b", "pragmatic", "pragmatic_risk", "discourse_marker", 4.2, "识别带冒犯风险的缓冲开头。"),
    (r"\bwith\s+all\s+due\s+respect\b", "pragmatic", "pragmatic_risk", "discourse_marker", 4.3, "识别正式但可能带反驳意味的语气。"),
    (r"\byeah,\s+right\b", "pragmatic", "pragmatic_risk", "spoken_phrase", 4.2, "识别 yeah, right 的反讽语气。"),
]


def _span_from_match(text: str, match: re.Match[str]) -> str:
    return normalize_candidate_span(text[match.start() : match.end()])


def _add_candidate(
    items: list[dict[str, Any]],
    seen: set[tuple[str, str]],
    *,
    text: str,
    exact_span: str,
    point_type: str,
    candidate_kind: str,
    phrase_type: str,
    value_score: float,
    reason: str,
    source: str,
) -> None:
    answer = normalize_candidate_span(exact_span)
    if not answer:
        return
    key = (candidate_kind, normalized_phrase_key(answer))
    if key in seen:
        return
    seen.add(key)
    items.append(
        {
            "type": point_type,
            "candidate_kind": candidate_kind,
            "phrase_type": phrase_type,
            "exact_span": answer,
            "answer_core": answer,
            "normalized_answer": answer,
            "value_score": value_score,
            "reason": reason,
            "learning_action": reason,
            "source_evidence": text,
            "source": source,
            "confidence": "high" if value_score >= 4.2 else "medium",
        }
    )


def recall_local_learning_points(source_segment: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, Any]]:
    text = str(source_segment.get("text") or source_segment.get("source_sentence") or "").strip()
    if not text:
        return []
    level = str(payload.get("level") or "B1")
    base_score = legacy_worker.score_text(
        text,
        level,
        payload.get("content_toggles") or {},
        legacy_worker.collection_levels_from_payload(payload, level),
    )
    phrase = legacy_worker.find_phrase(text, level, legacy_worker.collection_levels_from_payload(payload, level))
    seen: set[tuple[str, str]] = set()
    items: list[dict[str, Any]] = []

    for typed in legacy_worker.typed_learning_point_candidates(text, phrase, base_score, level, payload):
        candidate_kind = str(typed.get("candidate_kind") or "expression")
        point_type = {
            "expression": "phrase",
            "contextual_vocab": "vocab_usage",
            "grammar_pattern": "grammar",
            "listening_feature": "listening",
            "pragmatic_risk": "pragmatic",
        }.get(candidate_kind, "phrase")
        _add_candidate(
            items,
            seen,
            text=text,
            exact_span=str(typed.get("exact_span") or typed.get("phrase") or ""),
            point_type=point_type,
            candidate_kind=candidate_kind,
            phrase_type=str(typed.get("phrase_type") or phrase_type_for_candidate_kind(candidate_kind)),
            value_score=float(typed.get("score") or base_score),
            reason=str(typed.get("phrase_card_focus") or "训练原句里的可迁移学习点。"),
            source="local_rule",
        )

    for pattern, point_type, candidate_kind, phrase_type, value_score, reason in LOCAL_PATTERNS:
        if not candidate_kind_allowed_by_focus(candidate_kind, payload):
            continue
        for match in re.finditer(pattern, text, re.IGNORECASE):
            _add_candidate(
                items,
                seen,
                text=text,
                exact_span=_span_from_match(text, match),
                point_type=point_type,
                candidate_kind=candidate_kind,
                phrase_type=phrase_type,
                value_score=value_score,
                reason=reason,
                source="local_rule",
            )

    return items
