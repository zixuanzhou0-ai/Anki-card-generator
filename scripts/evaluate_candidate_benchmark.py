from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from card_service.candidate_benchmark import (  # noqa: E402
    CandidateBenchmarkError,
    evaluate_candidate_benchmark_files,
    load_jsonl,
    validate_annotation_records,
    validate_prediction_records,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and score the candidate-quality JSONL benchmark."
    )
    parser.add_argument("--annotations", required=True, type=Path)
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--high-confidence-threshold", type=float, default=0.8)
    parser.add_argument("--compact", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.validate_only:
            annotations = validate_annotation_records(load_jsonl(args.annotations))
            predictions = validate_prediction_records(load_jsonl(args.predictions))
            report = {
                "ok": True,
                "annotationRecords": len(annotations),
                "predictionRecords": len(predictions),
            }
        else:
            report = evaluate_candidate_benchmark_files(
                args.annotations,
                args.predictions,
                high_confidence_threshold=args.high_confidence_threshold,
            )
    except (CandidateBenchmarkError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    rendered = json.dumps(
        report,
        ensure_ascii=False,
        sort_keys=True,
        indent=None if args.compact else 2,
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
