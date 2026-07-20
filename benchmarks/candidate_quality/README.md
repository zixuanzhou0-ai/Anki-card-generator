# 候选筛选质量基准

这是候选发现与推荐的离线评测基础设施，对应
`docs/codex-plugin/BENCHMARK_AND_EVALUATION.md` 第 8 节。

## 数据合同

- `schema/candidate-annotations-v1.schema.json`：一行一个标注集合。
- `schema/candidate-predictions-v1.schema.json`：一行一个系统运行结果。
- 字符位置使用 Python/Unicode code point 的半开区间 `[start, end)`。
- 同一 case 的标注者必须用相同 `targetId` 对齐同一个学习目标；如果两人只在其中一方发现该目标，另一方直接不写该 ID。
- `complete=false` 的标注不参与召回评分或一致性计算。
- `annotationRole=adjudication` 是第三人裁决；存在时只用裁决结果作 gold。
- 没有裁决时分别对每位完整标注者评分后做 macro average，并把报告标为 `provisional_no_adjudication`。
- `matchedTargetId` 是离线 benchmark 的对齐字段，不是生产候选字段。无法对齐的预测写 `null`。
- `declaredOmissions` 用于区分系统明确暴露的缺口与静默遗漏；不能把它当作召回成功。

`provenance=synthetic_demo` 只用于让格式、验证器和评分器可执行，永远不具有真人内容质量证据。合成标注者 ID 必须以 `synthetic-demo-` 开头，报告会强制给出 `releaseGateEligible=false`。

## 运行

~~~powershell
python scripts/evaluate_candidate_benchmark.py `
  --annotations benchmarks/candidate_quality/fixtures/synthetic_demo_annotations_v1.jsonl `
  --predictions benchmarks/candidate_quality/fixtures/synthetic_demo_predictions_v1.jsonl
~~~

仅验证格式：

~~~powershell
python scripts/evaluate_candidate_benchmark.py `
  --annotations benchmarks/candidate_quality/fixtures/synthetic_demo_annotations_v1.jsonl `
  --predictions benchmarks/candidate_quality/fixtures/synthetic_demo_predictions_v1.jsonl `
  --validate-only
~~~

输出包含 candidate recall、recommendation precision、exact-span accuracy、route accuracy、duplicate precision/recall/F1、高置信错误率、静默遗漏率，以及双标的 Cohen's kappa、跨度一致率、重复关系一致性和逐项分歧。

## 真人基准的发布边界

合成 fixture 不能锁定质量阈值。发布门槛前仍必须：

1. 对每份正式语料完成至少两位真人独立完整标注。
2. 对分歧做第三人裁决并保留原始两份标注。
3. 固定语料许可、来源、版本和 SHA-256。
4. 在首轮真人 benchmark 后再锁定推荐 precision/recall 阈值。
5. 单独报告不同素材类型、语言对和学习路线，不能只看总体平均数。
