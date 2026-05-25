import type { Project, QualityFunnel } from './types'
import {
  isRecommendedCardForExport,
  isReviewableCardForExport,
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
  return {
    total: cards.length,
    recommended: segments.reduce(
      (total, segment) => total + segment.cards.filter((card) => isRecommendedCardForExport(segment, card)).length,
      0,
    ),
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
          ? isReading
            ? '当前筛选没有推荐精读卡，可能是模型返回空或多数语言点仍需人工确认。'
            : isDocument
              ? '当前筛选没有推荐知识卡，可能是模型返回空或多数知识点仍需人工确认。'
              : '当前筛选没有推荐卡，可能是词伙评分不足、模型返回空或筛选太严格。'
          : isReading
            ? '推荐精读卡偏少，通常是语言点价值较弱或模型评审较严格。'
            : isDocument
              ? '推荐知识卡偏少，通常是文档片段信息不足或模型评审较严格。'
              : '推荐卡偏少，通常是重复合并、低价值表达或模型评审较严格。'
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
  const scored = segments
    .map((segment) => phraseValueScore(segment.phrase_value_score))
    .filter((score): score is number => typeof score === 'number')
  const averageScore = scored.length ? scored.reduce((total, score) => total + score, 0) / scored.length : null
  return {
    ...provided,
    candidate_segments: provided.candidate_segments ?? segments.length,
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
    recommended: segments.filter((segment) => segmentReviewStatus(segment) === 'recommended').length,
    needs_review: segments.filter((segment) => segmentReviewStatus(segment) === 'needs_review').length,
    reject: segments.filter((segment) => segmentReviewStatus(segment) === 'reject').length,
    duplicate: segments.filter((segment) => segmentReviewStatus(segment) === 'duplicate').length,
  }
}
