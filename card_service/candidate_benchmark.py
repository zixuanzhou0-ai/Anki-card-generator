"""Deterministic offline evaluation for learning-candidate discovery.

The benchmark format is intentionally independent from production candidate
artifacts.  A benchmark maintainer aligns predictions to annotation target IDs;
the scorer then checks that alignment against spans, routes, recommendation
labels, duplicate groups, and declared omissions.
"""

from __future__ import annotations

import itertools
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


ANNOTATION_SCHEMA = "anki.card-candidate-annotation"
PREDICTION_SCHEMA = "anki.card-candidate-prediction"
SCHEMA_VERSION = 1
MAX_JSONL_BYTES = 64 * 1024 * 1024
MAX_LINE_BYTES = 4 * 1024 * 1024
MAX_RECORDS = 10_000
MAX_ITEMS_PER_RECORD = 10_000
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_ROLES = {"annotator", "adjudication"}
_PROVENANCE = {"human", "synthetic_demo"}
_PREDICTION_STATUS = {"candidate", "hard_blocked"}


class CandidateBenchmarkError(ValueError):
    """A benchmark fixture or prediction violates the frozen v1 contract."""


def _reject_constant(value: str) -> None:
    raise CandidateBenchmarkError(f"non-finite JSON number is not allowed: {value}")


def _reject_duplicate_keys(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CandidateBenchmarkError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Load bounded JSONL while rejecting duplicate keys and NaN/Infinity."""

    source = Path(path)
    size = source.stat().st_size
    if size > MAX_JSONL_BYTES:
        raise CandidateBenchmarkError(
            f"JSONL file exceeds {MAX_JSONL_BYTES} bytes: {source}"
        )
    records: list[dict[str, Any]] = []
    with source.open("rb") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            if len(raw_line) > MAX_LINE_BYTES:
                raise CandidateBenchmarkError(
                    f"{source}:{line_number} exceeds {MAX_LINE_BYTES} bytes"
                )
            if not raw_line.strip():
                continue
            if len(records) >= MAX_RECORDS:
                raise CandidateBenchmarkError(
                    f"JSONL file exceeds {MAX_RECORDS} records: {source}"
                )
            try:
                value = json.loads(
                    raw_line.decode("utf-8"),
                    parse_constant=_reject_constant,
                    object_pairs_hook=_reject_duplicate_keys,
                )
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise CandidateBenchmarkError(
                    f"{source}:{line_number} is not valid UTF-8 JSON: {exc}"
                ) from exc
            if not isinstance(value, dict):
                raise CandidateBenchmarkError(
                    f"{source}:{line_number} must contain a JSON object"
                )
            records.append(value)
    if not records:
        raise CandidateBenchmarkError(f"JSONL file is empty: {source}")
    return records


def _exact_keys(value: Mapping[str, Any], keys: set[str], where: str) -> None:
    actual = set(value)
    if actual != keys:
        missing = sorted(keys - actual)
        extra = sorted(actual - keys)
        raise CandidateBenchmarkError(
            f"{where} has invalid fields; missing={missing}, extra={extra}"
        )


def _identifier(value: Any, where: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise CandidateBenchmarkError(f"{where} must be a stable identifier")
    return value


def _boolean(value: Any, where: str) -> bool:
    if type(value) is not bool:
        raise CandidateBenchmarkError(f"{where} must be a boolean")
    return value


def _number(value: Any, where: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CandidateBenchmarkError(f"{where} must be a number")
    converted = float(value)
    if not math.isfinite(converted) or not minimum <= converted <= maximum:
        raise CandidateBenchmarkError(
            f"{where} must be finite and between {minimum} and {maximum}"
        )
    return converted


def _span(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CandidateBenchmarkError(f"{where} must be an object")
    _exact_keys(value, {"nodeId", "start", "end", "text"}, where)
    node_id = _identifier(value["nodeId"], f"{where}.nodeId")
    start = value["start"]
    end = value["end"]
    text = value["text"]
    if isinstance(start, bool) or not isinstance(start, int) or start < 0:
        raise CandidateBenchmarkError(f"{where}.start must be a non-negative integer")
    if isinstance(end, bool) or not isinstance(end, int) or end <= start:
        raise CandidateBenchmarkError(f"{where}.end must be greater than start")
    if not isinstance(text, str) or not text:
        raise CandidateBenchmarkError(f"{where}.text must be non-empty")
    if len(text) != end - start:
        raise CandidateBenchmarkError(
            f"{where}.text length must equal end - start in Unicode code points"
        )
    return {"nodeId": node_id, "start": start, "end": end, "text": text}


def _target(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CandidateBenchmarkError(f"{where} must be an object")
    _exact_keys(
        value,
        {
            "targetId",
            "worthy",
            "recommended",
            "hardBlocked",
            "route",
            "span",
            "duplicateGroup",
        },
        where,
    )
    target_id = _identifier(value["targetId"], f"{where}.targetId")
    worthy = _boolean(value["worthy"], f"{where}.worthy")
    recommended = _boolean(value["recommended"], f"{where}.recommended")
    hard_blocked = _boolean(value["hardBlocked"], f"{where}.hardBlocked")
    if recommended and (not worthy or hard_blocked):
        raise CandidateBenchmarkError(
            f"{where}.recommended requires worthy=true and hardBlocked=false"
        )
    route = _identifier(value["route"], f"{where}.route")
    duplicate_group = value["duplicateGroup"]
    if duplicate_group is not None:
        duplicate_group = _identifier(
            duplicate_group, f"{where}.duplicateGroup"
        )
    return {
        "targetId": target_id,
        "worthy": worthy,
        "recommended": recommended,
        "hardBlocked": hard_blocked,
        "route": route,
        "span": _span(value["span"], f"{where}.span"),
        "duplicateGroup": duplicate_group,
    }


def validate_annotation_records(
    records: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    identities: set[tuple[str, str, str]] = set()
    for index, value in enumerate(records):
        where = f"annotation[{index}]"
        if not isinstance(value, Mapping):
            raise CandidateBenchmarkError(f"{where} must be an object")
        _exact_keys(
            value,
            {
                "schema",
                "schemaVersion",
                "corpusId",
                "caseId",
                "sourceId",
                "annotationSetId",
                "annotationRole",
                "annotatorId",
                "provenance",
                "complete",
                "targets",
            },
            where,
        )
        if value["schema"] != ANNOTATION_SCHEMA or value["schemaVersion"] != 1:
            raise CandidateBenchmarkError(f"{where} uses an unsupported schema")
        corpus_id = _identifier(value["corpusId"], f"{where}.corpusId")
        case_id = _identifier(value["caseId"], f"{where}.caseId")
        source_id = _identifier(value["sourceId"], f"{where}.sourceId")
        annotation_set_id = _identifier(
            value["annotationSetId"], f"{where}.annotationSetId"
        )
        annotator_id = _identifier(value["annotatorId"], f"{where}.annotatorId")
        role = value["annotationRole"]
        provenance = value["provenance"]
        if role not in _ROLES:
            raise CandidateBenchmarkError(f"{where}.annotationRole is invalid")
        if provenance not in _PROVENANCE:
            raise CandidateBenchmarkError(f"{where}.provenance is invalid")
        if provenance == "synthetic_demo" and not annotator_id.startswith(
            "synthetic-demo-"
        ):
            raise CandidateBenchmarkError(
                f"{where}: synthetic_demo annotatorId must start with synthetic-demo-"
            )
        if provenance == "human" and annotator_id.startswith("synthetic-demo-"):
            raise CandidateBenchmarkError(
                f"{where}: synthetic demo identity cannot claim human provenance"
            )
        complete = _boolean(value["complete"], f"{where}.complete")
        targets_value = value["targets"]
        if not isinstance(targets_value, list) or len(targets_value) > MAX_ITEMS_PER_RECORD:
            raise CandidateBenchmarkError(
                f"{where}.targets must be a bounded array"
            )
        targets = [
            _target(item, f"{where}.targets[{item_index}]")
            for item_index, item in enumerate(targets_value)
        ]
        target_ids = [item["targetId"] for item in targets]
        if len(target_ids) != len(set(target_ids)):
            raise CandidateBenchmarkError(f"{where}.targets contains duplicate targetId")
        identity = (corpus_id, case_id, annotation_set_id)
        if identity in identities:
            raise CandidateBenchmarkError(f"duplicate annotation identity: {identity}")
        identities.add(identity)
        normalized.append(
            {
                "schema": ANNOTATION_SCHEMA,
                "schemaVersion": SCHEMA_VERSION,
                "corpusId": corpus_id,
                "caseId": case_id,
                "sourceId": source_id,
                "annotationSetId": annotation_set_id,
                "annotationRole": role,
                "annotatorId": annotator_id,
                "provenance": provenance,
                "complete": complete,
                "targets": targets,
            }
        )
    _validate_annotation_cases(normalized)
    return normalized


def _validate_annotation_cases(records: Sequence[Mapping[str, Any]]) -> None:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[(record["corpusId"], record["caseId"])].append(record)
    for case_key, case_records in grouped.items():
        source_ids = {record["sourceId"] for record in case_records}
        if len(source_ids) != 1:
            raise CandidateBenchmarkError(
                f"case {case_key} has inconsistent sourceId values"
            )
        adjudications = [
            record for record in case_records if record["annotationRole"] == "adjudication"
        ]
        if len(adjudications) > 1:
            raise CandidateBenchmarkError(f"case {case_key} has multiple adjudications")
        if adjudications and not adjudications[0]["complete"]:
            raise CandidateBenchmarkError(
                f"case {case_key} adjudication must have complete=true"
            )


def _prediction_item(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CandidateBenchmarkError(f"{where} must be an object")
    _exact_keys(
        value,
        {
            "predictionId",
            "matchedTargetId",
            "route",
            "span",
            "recommended",
            "confidence",
            "duplicateGroup",
            "status",
        },
        where,
    )
    matched_target_id = value["matchedTargetId"]
    if matched_target_id is not None:
        matched_target_id = _identifier(
            matched_target_id, f"{where}.matchedTargetId"
        )
    duplicate_group = value["duplicateGroup"]
    if duplicate_group is not None:
        duplicate_group = _identifier(
            duplicate_group, f"{where}.duplicateGroup"
        )
    status = value["status"]
    if status not in _PREDICTION_STATUS:
        raise CandidateBenchmarkError(f"{where}.status is invalid")
    return {
        "predictionId": _identifier(
            value["predictionId"], f"{where}.predictionId"
        ),
        "matchedTargetId": matched_target_id,
        "route": _identifier(value["route"], f"{where}.route"),
        "span": _span(value["span"], f"{where}.span"),
        "recommended": _boolean(value["recommended"], f"{where}.recommended"),
        "confidence": _number(value["confidence"], f"{where}.confidence", 0.0, 1.0),
        "duplicateGroup": duplicate_group,
        "status": status,
    }


def validate_prediction_records(
    records: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    case_keys: set[tuple[str, str]] = set()
    for index, value in enumerate(records):
        where = f"prediction[{index}]"
        if not isinstance(value, Mapping):
            raise CandidateBenchmarkError(f"{where} must be an object")
        _exact_keys(
            value,
            {
                "schema",
                "schemaVersion",
                "corpusId",
                "caseId",
                "sourceId",
                "systemId",
                "runId",
                "items",
                "declaredOmissions",
            },
            where,
        )
        if value["schema"] != PREDICTION_SCHEMA or value["schemaVersion"] != 1:
            raise CandidateBenchmarkError(f"{where} uses an unsupported schema")
        corpus_id = _identifier(value["corpusId"], f"{where}.corpusId")
        case_id = _identifier(value["caseId"], f"{where}.caseId")
        case_key = (corpus_id, case_id)
        if case_key in case_keys:
            raise CandidateBenchmarkError(f"duplicate prediction case: {case_key}")
        case_keys.add(case_key)
        items_value = value["items"]
        omissions_value = value["declaredOmissions"]
        if not isinstance(items_value, list) or len(items_value) > MAX_ITEMS_PER_RECORD:
            raise CandidateBenchmarkError(f"{where}.items must be a bounded array")
        if not isinstance(omissions_value, list) or len(omissions_value) > MAX_ITEMS_PER_RECORD:
            raise CandidateBenchmarkError(
                f"{where}.declaredOmissions must be a bounded array"
            )
        items = [
            _prediction_item(item, f"{where}.items[{item_index}]")
            for item_index, item in enumerate(items_value)
        ]
        prediction_ids = [item["predictionId"] for item in items]
        if len(prediction_ids) != len(set(prediction_ids)):
            raise CandidateBenchmarkError(f"{where}.items contains duplicate predictionId")
        omissions: list[dict[str, str]] = []
        omission_ids: set[str] = set()
        for omission_index, omission in enumerate(omissions_value):
            omission_where = f"{where}.declaredOmissions[{omission_index}]"
            if not isinstance(omission, dict):
                raise CandidateBenchmarkError(f"{omission_where} must be an object")
            _exact_keys(omission, {"targetId", "reason"}, omission_where)
            target_id = _identifier(omission["targetId"], f"{omission_where}.targetId")
            reason = omission["reason"]
            if not isinstance(reason, str) or not reason.strip() or len(reason) > 500:
                raise CandidateBenchmarkError(
                    f"{omission_where}.reason must be 1-500 characters"
                )
            if target_id in omission_ids:
                raise CandidateBenchmarkError(
                    f"{where}.declaredOmissions contains duplicate targetId"
                )
            omission_ids.add(target_id)
            omissions.append({"targetId": target_id, "reason": reason.strip()})
        normalized.append(
            {
                "schema": PREDICTION_SCHEMA,
                "schemaVersion": SCHEMA_VERSION,
                "corpusId": corpus_id,
                "caseId": case_id,
                "sourceId": _identifier(value["sourceId"], f"{where}.sourceId"),
                "systemId": _identifier(value["systemId"], f"{where}.systemId"),
                "runId": _identifier(value["runId"], f"{where}.runId"),
                "items": items,
                "declaredOmissions": omissions,
            }
        )
    return normalized


def _ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None:
        return None
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _same_span(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return all(left[key] == right[key] for key in ("nodeId", "start", "end", "text"))


def _duplicate_pairs(items: Sequence[Mapping[str, Any]], id_key: str) -> set[tuple[str, str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for item in items:
        group = item.get("duplicateGroup")
        if group is not None:
            groups[group].append(item[id_key])
    result: set[tuple[str, str]] = set()
    for members in groups.values():
        for left, right in itertools.combinations(sorted(set(members)), 2):
            result.add((left, right))
    return result


def _score_case(
    gold: Mapping[str, Any],
    prediction: Mapping[str, Any],
    high_confidence_threshold: float,
) -> dict[str, Any]:
    targets = {target["targetId"]: target for target in gold["targets"]}
    worthy = {target_id for target_id, target in targets.items() if target["worthy"]}
    items = prediction["items"]
    matched_worthy = {
        item["matchedTargetId"]
        for item in items
        if item["matchedTargetId"] in worthy
    }
    recommended_items = [item for item in items if item["recommended"]]
    recommendation_correct = sum(
        1
        for item in recommended_items
        if item["matchedTargetId"] in targets
        and targets[item["matchedTargetId"]]["recommended"]
    )
    aligned_items = [
        item for item in items if item["matchedTargetId"] in targets
    ]
    exact_spans = sum(
        _same_span(item["span"], targets[item["matchedTargetId"]]["span"])
        for item in aligned_items
    )
    correct_routes = sum(
        item["route"] == targets[item["matchedTargetId"]]["route"]
        for item in aligned_items
    )

    gold_duplicate_pairs = _duplicate_pairs(
        [target for target in targets.values() if target["worthy"]], "targetId"
    )
    predicted_duplicate_pairs: set[tuple[str, str]] = set()
    predicted_groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in items:
        if item["duplicateGroup"] is not None:
            predicted_groups[item["duplicateGroup"]].append(item)
    duplicate_tp = 0
    duplicate_fp = 0
    for members in predicted_groups.values():
        for left, right in itertools.combinations(members, 2):
            left_target = left["matchedTargetId"]
            right_target = right["matchedTargetId"]
            if left_target is None or right_target is None or left_target == right_target:
                duplicate_fp += 1
                continue
            pair = tuple(sorted((left_target, right_target)))
            if pair in predicted_duplicate_pairs:
                continue
            predicted_duplicate_pairs.add(pair)
            if pair in gold_duplicate_pairs:
                duplicate_tp += 1
            else:
                duplicate_fp += 1
    duplicate_fn = len(gold_duplicate_pairs - predicted_duplicate_pairs)
    duplicate_precision = _ratio(duplicate_tp, duplicate_tp + duplicate_fp)
    duplicate_recall = _ratio(duplicate_tp, duplicate_tp + duplicate_fn)

    high_confidence = [
        item for item in items if item["confidence"] >= high_confidence_threshold
    ]
    high_confidence_errors = 0
    for item in high_confidence:
        target = targets.get(item["matchedTargetId"])
        correct = (
            target is not None
            and target["worthy"]
            and _same_span(item["span"], target["span"])
            and item["route"] == target["route"]
            and (item["status"] == "hard_blocked") == target["hardBlocked"]
            and (not item["recommended"] or target["recommended"])
        )
        if not correct:
            high_confidence_errors += 1

    omissions = {item["targetId"] for item in prediction["declaredOmissions"]}
    missed = worthy - matched_worthy
    silent_missed = missed - omissions
    return {
        "corpusId": gold["corpusId"],
        "caseId": gold["caseId"],
        "goldAnnotationSetId": gold["annotationSetId"],
        "goldRole": gold["annotationRole"],
        "goldProvenance": gold["provenance"],
        "candidateRecall": _ratio(len(matched_worthy), len(worthy)),
        "recommendationPrecision": _ratio(
            recommendation_correct, len(recommended_items)
        ),
        "exactSpanAccuracy": _ratio(exact_spans, len(aligned_items)),
        "routeAccuracy": _ratio(correct_routes, len(aligned_items)),
        "duplicatePrecision": duplicate_precision,
        "duplicateRecall": duplicate_recall,
        "duplicateF1": _f1(duplicate_precision, duplicate_recall),
        "highConfidenceErrorRate": _ratio(
            high_confidence_errors, len(high_confidence)
        ),
        "silentOmissionRate": _ratio(len(silent_missed), len(worthy)),
        "counts": {
            "goldWorthy": len(worthy),
            "matchedWorthy": len(matched_worthy),
            "recommendedPredictions": len(recommended_items),
            "correctRecommendations": recommendation_correct,
            "alignedPredictions": len(aligned_items),
            "exactSpans": exact_spans,
            "correctRoutes": correct_routes,
            "duplicateTruePositive": duplicate_tp,
            "duplicateFalsePositive": duplicate_fp,
            "duplicateFalseNegative": duplicate_fn,
            "highConfidencePredictions": len(high_confidence),
            "highConfidenceErrors": high_confidence_errors,
            "missedWorthy": len(missed),
            "declaredMissed": len(missed & omissions),
            "silentMissed": len(silent_missed),
        },
        "silentOmissionTargetIds": sorted(silent_missed),
    }


def _cohen_kappa(left: Sequence[Any], right: Sequence[Any]) -> float | None:
    if len(left) != len(right):
        raise CandidateBenchmarkError("kappa vectors must have equal length")
    if not left:
        return None
    observed = sum(a == b for a, b in zip(left, right)) / len(left)
    labels = set(left) | set(right)
    expected = sum(
        (left.count(label) / len(left)) * (right.count(label) / len(right))
        for label in labels
    )
    if expected == 1.0:
        return 1.0 if observed == 1.0 else 0.0
    return (observed - expected) / (1.0 - expected)


def _agreement_pair(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    left_targets = {item["targetId"]: item for item in left["targets"]}
    right_targets = {item["targetId"]: item for item in right["targets"]}
    target_ids = sorted(set(left_targets) | set(right_targets))
    left_worthy = [
        bool(left_targets.get(target_id, {}).get("worthy", False))
        for target_id in target_ids
    ]
    right_worthy = [
        bool(right_targets.get(target_id, {}).get("worthy", False))
        for target_id in target_ids
    ]
    left_recommended = [
        bool(left_targets.get(target_id, {}).get("recommended", False))
        for target_id in target_ids
    ]
    right_recommended = [
        bool(right_targets.get(target_id, {}).get("recommended", False))
        for target_id in target_ids
    ]
    left_routes = [
        left_targets.get(target_id, {}).get("route", "__missing__")
        for target_id in target_ids
    ]
    right_routes = [
        right_targets.get(target_id, {}).get("route", "__missing__")
        for target_id in target_ids
    ]
    jointly_worthy = [
        target_id
        for target_id in target_ids
        if left_targets.get(target_id, {}).get("worthy", False)
        and right_targets.get(target_id, {}).get("worthy", False)
    ]
    exact_span_matches = sum(
        _same_span(left_targets[target_id]["span"], right_targets[target_id]["span"])
        for target_id in jointly_worthy
    )
    left_pairs = _duplicate_pairs(list(left_targets.values()), "targetId")
    right_pairs = _duplicate_pairs(list(right_targets.values()), "targetId")
    pair_tp = len(left_pairs & right_pairs)
    pair_precision = _ratio(pair_tp, len(right_pairs))
    pair_recall = _ratio(pair_tp, len(left_pairs))
    disagreements: list[dict[str, Any]] = []
    for target_id in target_ids:
        left_target = left_targets.get(target_id)
        right_target = right_targets.get(target_id)
        fields: list[str] = []
        if left_target is None or right_target is None:
            fields.append("presence")
        else:
            for field in ("worthy", "recommended", "hardBlocked", "route", "duplicateGroup"):
                if left_target[field] != right_target[field]:
                    fields.append(field)
            if not _same_span(left_target["span"], right_target["span"]):
                fields.append("span")
        if fields:
            disagreements.append({"targetId": target_id, "fields": fields})
    return {
        "corpusId": left["corpusId"],
        "caseId": left["caseId"],
        "leftAnnotationSetId": left["annotationSetId"],
        "rightAnnotationSetId": right["annotationSetId"],
        "targetUniverse": len(target_ids),
        "worthyKappa": _cohen_kappa(left_worthy, right_worthy),
        "recommendationKappa": _cohen_kappa(left_recommended, right_recommended),
        "routeKappa": _cohen_kappa(left_routes, right_routes),
        "exactSpanAgreement": _ratio(exact_span_matches, len(jointly_worthy)),
        "duplicatePairPrecision": pair_precision,
        "duplicatePairRecall": pair_recall,
        "duplicatePairF1": _f1(pair_precision, pair_recall),
        "disagreements": disagreements,
    }


def _macro_average(
    scores: Sequence[Mapping[str, Any]], field: str
) -> float | None:
    values = [float(score[field]) for score in scores if score[field] is not None]
    return None if not values else sum(values) / len(values)


def evaluate_candidate_benchmark(
    annotation_records: Sequence[Mapping[str, Any]],
    prediction_records: Sequence[Mapping[str, Any]],
    *,
    high_confidence_threshold: float = 0.8,
) -> dict[str, Any]:
    """Validate and score predictions against adjudication or each annotator.

    When a case has an adjudication record, only that record is used as gold.
    Otherwise every complete annotator record is scored and macro-averaged; the
    report remains provisional so synthetic or unresolved data cannot be used as
    release evidence by accident.
    """

    threshold = _number(
        high_confidence_threshold, "high_confidence_threshold", 0.0, 1.0
    )
    annotations = validate_annotation_records(annotation_records)
    predictions = validate_prediction_records(prediction_records)
    annotation_by_case: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    prediction_by_case = {
        (record["corpusId"], record["caseId"]): record for record in predictions
    }
    for annotation in annotations:
        annotation_by_case[(annotation["corpusId"], annotation["caseId"])].append(
            annotation
        )
    if set(annotation_by_case) != set(prediction_by_case):
        missing = sorted(set(annotation_by_case) - set(prediction_by_case))
        extra = sorted(set(prediction_by_case) - set(annotation_by_case))
        raise CandidateBenchmarkError(
            f"annotation/prediction case mismatch; missing={missing}, extra={extra}"
        )

    scores: list[dict[str, Any]] = []
    agreements: list[dict[str, Any]] = []
    unresolved_cases: list[str] = []
    all_human = True
    double_annotation_complete = True
    for case_key, case_annotations in sorted(annotation_by_case.items()):
        prediction = prediction_by_case[case_key]
        if prediction["sourceId"] != case_annotations[0]["sourceId"]:
            raise CandidateBenchmarkError(f"case {case_key} has mismatched sourceId")
        annotators = [
            item for item in case_annotations if item["annotationRole"] == "annotator"
        ]
        complete_annotators = [item for item in annotators if item["complete"]]
        double_annotation_complete = double_annotation_complete and (
            len(complete_annotators) >= 2
            and all(item["provenance"] == "human" for item in complete_annotators)
        )
        for left, right in itertools.combinations(complete_annotators, 2):
            agreements.append(_agreement_pair(left, right))
        adjudications = [
            item for item in case_annotations if item["annotationRole"] == "adjudication"
        ]
        if adjudications:
            gold_records = adjudications
        else:
            gold_records = complete_annotators
            unresolved_cases.append(f"{case_key[0]}:{case_key[1]}")
        if not gold_records:
            raise CandidateBenchmarkError(
                f"case {case_key} has neither a complete annotator nor adjudication"
            )
        all_human = all_human and all(
            item["provenance"] == "human" for item in case_annotations
        )
        for gold in gold_records:
            scores.append(_score_case(gold, prediction, threshold))

    fields = (
        "candidateRecall",
        "recommendationPrecision",
        "exactSpanAccuracy",
        "routeAccuracy",
        "duplicatePrecision",
        "duplicateRecall",
        "duplicateF1",
        "highConfidenceErrorRate",
        "silentOmissionRate",
    )
    provenance = "human" if all_human else "synthetic_demo"
    release_gate_eligible = (
        all_human and double_annotation_complete and not unresolved_cases
    )
    return {
        "schema": "anki.card-candidate-benchmark-report",
        "schemaVersion": SCHEMA_VERSION,
        "provenance": provenance,
        "releaseGateEligible": release_gate_eligible,
        "doubleAnnotationComplete": double_annotation_complete,
        "status": "adjudicated" if not unresolved_cases else "provisional_no_adjudication",
        "highConfidenceThreshold": threshold,
        "caseCount": len(annotation_by_case),
        "goldScoreCount": len(scores),
        "metrics": {field: _macro_average(scores, field) for field in fields},
        "perGoldSet": scores,
        "agreement": {
            "pairCount": len(agreements),
            "pairs": agreements,
            "disagreementCount": sum(
                len(pair["disagreements"]) for pair in agreements
            ),
        },
        "unresolvedCases": unresolved_cases,
        "limitations": (
            [
                "synthetic_demo data is executable documentation only and is not human quality evidence"
            ]
            if not all_human
            else []
        )
        + (
            ["cases without adjudication are scored per annotator and macro-averaged"]
            if unresolved_cases
            else []
        ),
    }


def evaluate_candidate_benchmark_files(
    annotation_path: str | Path,
    prediction_path: str | Path,
    *,
    high_confidence_threshold: float = 0.8,
) -> dict[str, Any]:
    return evaluate_candidate_benchmark(
        load_jsonl(annotation_path),
        load_jsonl(prediction_path),
        high_confidence_threshold=high_confidence_threshold,
    )
