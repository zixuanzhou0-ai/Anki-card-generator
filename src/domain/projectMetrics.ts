import type { Project, QualityFunnel } from './types'
import {
  getExportSelectionStats,
  isRecommendedCardForExport,
  isReviewableCardForExport,
  isUsableCardForExport,
  phraseValueScore,
  segmentReviewStatus,
} from './quality'

export type QualityCounts = {
  total: number
  recommended: number
  review: number
  rejected: number
}

export type QualityDiagnostics = {
  candidates: number
  avgScore: number | null
  duplicate: number
  rejectedSegments: number
  rejectReasons: string[]
  shortReason: string
}

export function countSelectedCards(project: Project | null): number {
  return (
    project?.segments.reduce(
      (total, segment) => total + segment.cards.filter((card) => card.enabled).length,
      0,
    ) ?? 0
  )
}

export function getQualityCounts(project: Project | null): QualityCounts {
  const segments = project?.segments ?? []
  const cards = segments.flatMap((segment) => segment.cards)
  const usable = segments.reduce(
    (total, segment) => total + segment.cards.filter((card) => isUsableCardForExport(segment, card)).length,
    0,
  )
  return {
    total: cards.length,
    recommended: usable,
    review: segments.reduce(
      (total, segment) =>
        total +
        segment.cards.filter(
          (card) => !isRecommendedCardForExport(segment, card) && isReviewableCardForExport(segment, card),
        ).length,
      0,
    ),
    rejected: segments.reduce(
      (total, segment) => total + segment.cards.filter((card) => !isReviewableCardForExport(segment, card)).length,
      0,
    ),
  }
}

export function getQualityDiagnostics(project: Project | null, recommendedCount: number): QualityDiagnostics {
  const segments = project?.segments ?? []
  const isDocument = project?.source_mode === 'document'
  const isReading = isDocument && project?.document_study_mode === 'language_reading'
  const scored = segments
    .map((segment) => phraseValueScore(segment.phrase_value_score))
    .filter((score): score is number => typeof score === 'number')
  const avgScore = scored.length ? scored.reduce((total, score) => total + score, 0) / scored.length : null
  const usableCount = segments.reduce(
    (total, segment) => total + segment.cards.filter((card) => isUsableCardForExport(segment, card)).length,
    0,
  )
  const rejectReasons = segments
    .filter((segment) => segmentReviewStatus(segment) === 'reject')
    .map((segment) => segment.phrase_reject_reason || segment.phrase_decision_reason || '未给出拒绝理由')
    .slice(0, 3)
  const shortReason =
    project && recommendedCount < 5
      ? project.segments.length < 6
        ? isDocument
          ? '文档分段较少或可制卡片段不足。'
          : '字幕片段太少或切分后有效候选不足。'
        : recommendedCount === 0
          ? usableCount > 0
            ? isReading
              ? `当前生成了 ${usableCount} 张精读卡，默认已选；可以手动取消不需要的卡。`
              : isDocument
                ? `当前生成了 ${usableCount} 张知识卡，默认已选；可以手动取消不需要的卡。`
                : `当前生成了 ${usableCount} 张可用卡，默认已选；可以手动取消不需要的卡。`
            : isReading
              ? '当前没有生成可用精读卡，可能是模型返回空或语言点被质量 gate 过滤。'
              : isDocument
                ? '当前没有生成可用知识卡，可能是模型返回空或知识点被质量 gate 过滤。'
                : '当前没有生成可用卡，可能是词伙评分不足、模型返回空或学习点被质量 gate 过滤。'
          : isReading
            ? '可用精读卡偏少，通常是语言点价值较弱或模型评审较严格。'
            : isDocument
              ? '可用知识卡偏少，通常是文档片段信息不足或模型评审较严格。'
              : '可用卡偏少，通常是重复合并、低价值表达或模型评审较严格。'
      : ''

  return {
    candidates: segments.length,
    avgScore,
    duplicate: segments.filter((segment) => segmentReviewStatus(segment) === 'duplicate').length,
    rejectedSegments: segments.filter((segment) => segmentReviewStatus(segment) === 'reject').length,
    rejectReasons,
    shortReason,
  }
}

export function getQualityFunnel(
  project: Project | null,
  qualityCounts: QualityCounts,
  diagnostics: QualityDiagnostics,
): QualityFunnel {
  const segments = project?.segments ?? []
  const provided = project?.quality_funnel ?? {}
  const sourceIds = new Set(
    segments.map((segment) => segment.source_segment_id || `${segment.start}:${segment.end}:${segment.text}`),
  )
  const learningPointCount = segments.reduce(
    (total, segment) => total + (segment.learning_points?.length || (segment.cards.length ? 1 : 0)),
    0,
  )
  const distribution = <T,>(items: T[], valueForItem: (item: T) => number) =>
    items.reduce<Record<string, number>>((acc, item) => {
      const key = String(valueForItem(item))
      acc[key] = (acc[key] ?? 0) + 1
      return acc
    }, {})
  const sourceGroups = Array.from(
    segments.reduce<Map<string, typeof segments>>((acc, segment) => {
      const key = segment.source_segment_id || `${segment.start}:${segment.end}:${segment.text}`
      acc.set(key, [...(acc.get(key) ?? []), segment])
      return acc
    }, new Map()),
  ).map(([, group]) => group)
  const learningPointsPerSource = distribution(sourceGroups, (group) =>
    group.reduce((total, segment) => total + (segment.learning_points?.length || (segment.cards.length ? 1 : 0)), 0),
  )
  const enabledCardsPerSource = distribution(sourceGroups, (group) =>
    group.reduce((total, segment) => total + segment.cards.filter((card) => card.enabled).length, 0),
  )
  const selectedCardCount = countSelectedCards(project)
  const inventory = Array.isArray(project?.learning_point_inventory) ? project.learning_point_inventory : []
  const inventoryCounts = inventory.reduce(
    (acc, item) => {
      if (item.status === 'candidate_only') acc.candidateOnly += 1
      if (item.status === 'hidden_duplicate') acc.hiddenDuplicate += 1
      if (item.status === 'hard_blocked') acc.hardBlocked += 1
      return acc
    },
    { candidateOnly: 0, hiddenDuplicate: 0, hardBlocked: 0 },
  )
  const scored = segments
    .map((segment) => phraseValueScore(segment.phrase_value_score))
    .filter((score): score is number => typeof score === 'number')
  const averageScore = scored.length ? scored.reduce((total, score) => total + score, 0) / scored.length : null
  const exportStats = getExportSelectionStats(project)
  return {
    ...provided,
    source_sentence_count: provided.source_sentence_count ?? sourceIds.size,
    candidate_segments: provided.candidate_segments ?? segments.length,
    learning_point_count: provided.learning_point_count ?? Math.max(learningPointCount, inventory.length),
    recommended_learning_point_count: provided.recommended_learning_point_count ?? qualityCounts.recommended,
    review_learning_point_count: provided.review_learning_point_count ?? qualityCounts.review,
    card_count: provided.card_count ?? qualityCounts.total,
    selected_card_count: selectedCardCount,
    exportable_card_count: exportStats.exportableCards,
    repair_required_card_count: exportStats.repairRequiredCards,
    selected_exportable_card_count: exportStats.selectedExportableCards,
    selected_repair_required_card_count: exportStats.selectedRepairRequiredCards,
    usable_card_count: qualityCounts.recommended,
    filtered_learning_point_count:
      provided.filtered_learning_point_count ??
      (provided.rejected_learning_point_count ?? 0) + (provided.duplicate_learning_point_count ?? 0),
    low_value_filtered_count: provided.low_value_filtered_count ?? provided.rejected_learning_point_count ?? 0,
    blocked_quality_issue_count:
      provided.blocked_quality_issue_count ?? Math.max(provided.rejected_cards ?? 0, exportStats.repairRequiredCards),
    candidate_only_learning_point_count:
      provided.candidate_only_learning_point_count ?? inventoryCounts.candidateOnly,
    hidden_duplicate_learning_point_count:
      provided.hidden_duplicate_learning_point_count ?? inventoryCounts.hiddenDuplicate,
    hard_blocked_learning_point_count:
      provided.hard_blocked_learning_point_count ?? inventoryCounts.hardBlocked,
    level_mode: provided.level_mode ?? project?.level_mode ?? 'auto',
    recommended_card_count: provided.recommended_card_count ?? qualityCounts.recommended,
    review_card_count: provided.review_card_count ?? qualityCounts.review,
    rejected_learning_point_count:
      provided.rejected_learning_point_count ??
      segments.filter((segment) => segmentReviewStatus(segment) === 'reject').length,
    duplicate_learning_point_count:
      provided.duplicate_learning_point_count ??
      segments.filter((segment) => segmentReviewStatus(segment) === 'duplicate').length,
    learning_points_per_source_distribution:
      provided.learning_points_per_source_distribution ?? learningPointsPerSource,
    enabled_cards_per_source_distribution: provided.enabled_cards_per_source_distribution ?? enabledCardsPerSource,
    max_learning_points_per_source:
      provided.max_learning_points_per_source ?? 4,
    reviewed_keep:
      provided.reviewed_keep ??
      segments.filter((segment) => {
        const status = segmentReviewStatus(segment)
        return status !== 'reject' && status !== 'duplicate'
      }).length,
    recommended_cards: qualityCounts.recommended,
    review_cards: qualityCounts.review,
    rejected_cards: qualityCounts.rejected,
    rejected_segments:
      provided.rejected_segments ?? segments.filter((segment) => segmentReviewStatus(segment) === 'reject').length,
    duplicate_segments:
      provided.duplicate_segments ?? segments.filter((segment) => segmentReviewStatus(segment) === 'duplicate').length,
    average_phrase_score: provided.average_phrase_score ?? averageScore,
    short_reason: provided.short_reason ?? diagnostics.shortReason,
  }
}

export function getSegmentReviewCounts(project: Project | null) {
  const segments = project?.segments ?? []
  return {
    all: segments.length,
    selected: segments.filter((segment) => segment.cards.some((card) => card.enabled)).length,
    unselected: segments.filter((segment) => !segment.cards.some((card) => card.enabled)).length,
  }
}
