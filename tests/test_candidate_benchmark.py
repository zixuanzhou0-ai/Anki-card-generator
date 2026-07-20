from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from card_service.candidate_benchmark import (
    CandidateBenchmarkError,
    evaluate_candidate_benchmark,
    evaluate_candidate_benchmark_files,
    load_jsonl,
    validate_annotation_records,
    validate_prediction_records,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "benchmarks" / "candidate_quality" / "fixtures"
ANNOTATIONS = FIXTURES / "synthetic_demo_annotations_v1.jsonl"
PREDICTIONS = FIXTURES / "synthetic_demo_predictions_v1.jsonl"


def demo_records():
    return load_jsonl(ANNOTATIONS), load_jsonl(PREDICTIONS)


def test_synthetic_demo_is_scored_but_never_release_evidence():
    report = evaluate_candidate_benchmark_files(ANNOTATIONS, PREDICTIONS)

    assert report["provenance"] == "synthetic_demo"
    assert report["releaseGateEligible"] is False
    assert report["doubleAnnotationComplete"] is False
    assert report["status"] == "provisional_no_adjudication"
    assert report["caseCount"] == 1
    assert report["goldScoreCount"] == 2
    assert report["metrics"] == pytest.approx(
        {
            "candidateRecall": (2 / 3 + 1) / 2,
            "recommendationPrecision": 1.0,
            "exactSpanAccuracy": 1.0,
            "routeAccuracy": 1.0,
            "duplicatePrecision": 1.0,
            "duplicateRecall": 1.0,
            "duplicateF1": 1.0,
            "highConfidenceErrorRate": 0.0,
            "silentOmissionRate": 0.0,
        }
    )
    assert report["agreement"]["pairCount"] == 1
    assert report["agreement"]["disagreementCount"] == 1
    assert "synthetic_demo" in report["limitations"][0]


def test_declared_omission_is_not_recall_but_is_not_silent():
    annotations, predictions = demo_records()
    predictions[0]["declaredOmissions"] = []

    report = evaluate_candidate_benchmark(annotations, predictions)

    assert report["metrics"]["candidateRecall"] == pytest.approx((2 / 3 + 1) / 2)
    assert report["metrics"]["silentOmissionRate"] == pytest.approx((1 / 3 + 0) / 2)
    assert report["perGoldSet"][0]["silentOmissionTargetIds"] == [
        "target-look-after"
    ]


def test_high_confidence_error_checks_span_route_gate_and_recommendation():
    annotations, predictions = demo_records()
    item = predictions[0]["items"][0]
    item["span"] = {
        "nodeId": "node-1",
        "start": 1,
        "end": 14,
        "text": "in good shape",
    }
    item["route"] = "reading_recognition"

    report = evaluate_candidate_benchmark(annotations, predictions)

    assert report["metrics"]["exactSpanAccuracy"] == pytest.approx(0.5)
    assert report["metrics"]["routeAccuracy"] == pytest.approx(0.5)
    assert report["metrics"]["highConfidenceErrorRate"] == pytest.approx(0.5)


def test_duplicate_pair_false_positive_changes_precision_but_not_recall():
    annotations, predictions = demo_records()
    predictions[0]["items"].append(
        {
            "predictionId": "prediction-unmatched",
            "matchedTargetId": None,
            "route": "production",
            "span": {
                "nodeId": "node-4",
                "start": 0,
                "end": 5,
                "text": "noise",
            },
            "recommended": False,
            "confidence": 0.2,
            "duplicateGroup": "predicted-shape",
            "status": "candidate",
        }
    )

    report = evaluate_candidate_benchmark(annotations, predictions)

    assert report["metrics"]["duplicatePrecision"] == pytest.approx(1 / 3)
    assert report["metrics"]["duplicateRecall"] == 1.0
    assert report["metrics"]["duplicateF1"] == pytest.approx(0.5)


def test_human_adjudication_is_the_only_gold_and_can_be_release_eligible():
    annotations, predictions = demo_records()
    human_annotations = []
    for index, record in enumerate(annotations, start=1):
        human = copy.deepcopy(record)
        human["annotatorId"] = f"human-{index}"
        human["annotationSetId"] = f"human-set-{index}"
        human["provenance"] = "human"
        human_annotations.append(human)
    adjudication = copy.deepcopy(human_annotations[0])
    adjudication["annotationSetId"] = "adjudication-set"
    adjudication["annotatorId"] = "human-adjudicator"
    adjudication["annotationRole"] = "adjudication"
    human_annotations.append(adjudication)

    report = evaluate_candidate_benchmark(human_annotations, predictions)

    assert report["provenance"] == "human"
    assert report["releaseGateEligible"] is True
    assert report["doubleAnnotationComplete"] is True
    assert report["status"] == "adjudicated"
    assert report["goldScoreCount"] == 1
    assert report["agreement"]["pairCount"] == 1


def test_adjudication_without_two_complete_human_annotations_is_not_release_eligible():
    annotations, predictions = demo_records()
    adjudication = copy.deepcopy(annotations[0])
    adjudication["annotationSetId"] = "adjudication-set"
    adjudication["annotatorId"] = "human-adjudicator"
    adjudication["annotationRole"] = "adjudication"
    adjudication["provenance"] = "human"

    report = evaluate_candidate_benchmark([adjudication], predictions)

    assert report["status"] == "adjudicated"
    assert report["doubleAnnotationComplete"] is False
    assert report["releaseGateEligible"] is False


def test_annotation_validator_rejects_synthetic_identity_claiming_human():
    annotations, _ = demo_records()
    annotations[0]["provenance"] = "human"

    with pytest.raises(CandidateBenchmarkError, match="cannot claim human"):
        validate_annotation_records(annotations)


def test_annotation_validator_rejects_span_text_length_mismatch():
    annotations, _ = demo_records()
    annotations[0]["targets"][0]["span"]["end"] = 12

    with pytest.raises(CandidateBenchmarkError, match="text length"):
        validate_annotation_records(annotations)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -0.01, 1.01])
def test_prediction_validator_rejects_invalid_confidence(value):
    _, predictions = demo_records()
    predictions[0]["items"][0]["confidence"] = value

    with pytest.raises(CandidateBenchmarkError, match="confidence"):
        validate_prediction_records(predictions)


def test_jsonl_loader_rejects_duplicate_keys_and_nonfinite_numbers(tmp_path):
    duplicate = tmp_path / "duplicate.jsonl"
    duplicate.write_text('{"schema":1,"schema":2}\n', encoding="utf-8")
    with pytest.raises(CandidateBenchmarkError, match="duplicate JSON key"):
        load_jsonl(duplicate)

    nonfinite = tmp_path / "nonfinite.jsonl"
    nonfinite.write_text('{"value":NaN}\n', encoding="utf-8")
    with pytest.raises(CandidateBenchmarkError, match="non-finite"):
        load_jsonl(nonfinite)


def test_schema_documents_are_valid_json_and_frozen_to_v1():
    schema_dir = ROOT / "benchmarks" / "candidate_quality" / "schema"
    annotations = json.loads(
        (schema_dir / "candidate-annotations-v1.schema.json").read_text(encoding="utf-8")
    )
    predictions = json.loads(
        (schema_dir / "candidate-predictions-v1.schema.json").read_text(encoding="utf-8")
    )

    assert annotations["properties"]["schemaVersion"] == {"const": 1}
    assert predictions["properties"]["schemaVersion"] == {"const": 1}
    assert annotations["additionalProperties"] is False
    assert predictions["additionalProperties"] is False


def test_cli_validates_and_scores_demo_fixture(tmp_path):
    output = tmp_path / "report.json"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "evaluate_candidate_benchmark.py"),
            "--annotations",
            str(ANNOTATIONS),
            "--predictions",
            str(PREDICTIONS),
            "--output",
            str(output),
            "--compact",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["releaseGateEligible"] is False
    assert json.loads(output.read_text(encoding="utf-8")) == report
