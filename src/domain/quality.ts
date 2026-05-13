import type { Card, Project, Segment, SegmentFilter } from './types'

export function badgeText(count: number) {
  return count > 0 ? `${count} 张已选` : '未选择卡片'
}

export function qualityLabel(card: Card) {
  const status = card.quality?.status
  if (status === 'recommended') return '推荐保留'
  if (status === 'needs_review') return '需要检查'
  if (status === 'reject') return '建议删除'
  return '未评分'
}

export function qualityClass(card: Card) {
  return card.quality?.status ?? 'unknown'
}

export const segmentFilterOptions: Array<{ id: SegmentFilter; label: string }> = [
  { id: 'all', label: '全部' },
  { id: 'recommended', label: '推荐' },
  { id: 'needs_review', label: '待审' },
  { id: 'reject', label: '已拒绝' },
  { id: 'duplicate', label: '重复合并' },
]

export function phraseValueScore(value: number | string | null | undefined) {
  const score = Number(value)
  return Number.isFinite(score) ? score : null
}

export function isPlaceholderPhrase(value: string | null | undefined) {
  const phrase = String(value ?? '').trim().toLowerCase()
  return !phrase || phrase === 'key expression' || phrase === 'n/a'
}

export function clipText(value: string, maxLength: number) {
  const text = value.replace(/\s+/g, ' ').trim()
  if (text.length <= maxLength) return text
  return `${text.slice(0, Math.max(0, maxLength - 1)).trim()}…`
}

export function segmentPhraseTitle(segment: Segment) {
  if (!isPlaceholderPhrase(segment.phrase)) return segment.phrase
  return segment.text ? `待选：${clipText(segment.text, 34)}` : '待模型挑选表达'
}

export function segmentPhraseLabel(segment: Segment) {
  return isPlaceholderPhrase(segment.phrase) ? '待模型挑选表达' : segment.phrase
}

export function segmentReviewStatus(segment: Segment): SegmentFilter | 'unreviewed' {
  const status = String(segment.phrase_review_status ?? '').trim()
  if (status === 'recommended' || status === 'needs_review' || status === 'reject' || status === 'duplicate') {
    return status
  }
  if (segment.cards.some((card) => card.quality?.status === 'recommended')) return 'recommended'
  if (segment.cards.some((card) => card.quality?.status === 'needs_review')) return 'needs_review'
  if (!segment.cards.length || segment.cards.every((card) => card.quality?.status === 'reject')) return 'reject'
  return 'unreviewed'
}

export function segmentStatusLabel(status: SegmentFilter | 'unreviewed') {
  if (status === 'recommended') return '推荐'
  if (status === 'needs_review') return '待审'
  if (status === 'reject') return '已拒绝'
  if (status === 'duplicate') return '重复合并'
  return '未评审'
}

export function segmentMatchesFilter(segment: Segment, filter: SegmentFilter) {
  if (filter === 'all') return true
  return segmentReviewStatus(segment) === filter
}

export function segmentMediaStart(segment: Segment) {
  return Number.isFinite(Number(segment.media_start)) ? Number(segment.media_start) : segment.start
}

export function segmentMediaEnd(segment: Segment) {
  return Number.isFinite(Number(segment.media_end)) ? Number(segment.media_end) : segment.end
}

export function segmentBudgetLabel(value: number | undefined) {
  return value && value > 0 ? `${value} 段上限` : '自动片段'
}

export function isRecommendedCardForExport(segment: Segment, card: Card) {
  const quality = card.quality?.status
  if (quality === 'recommended') return true
  if (quality === 'reject') return false
  const reviewStatus = segmentReviewStatus(segment)
  const score = phraseValueScore(card.phrase_value_score ?? segment.phrase_value_score)
  return reviewStatus === 'recommended' || Boolean(score && score >= 4)
}

export function isReviewableCardForExport(segment: Segment, card: Card) {
  if (card.quality?.status === 'reject') return false
  if (isRecommendedCardForExport(segment, card)) return true
  const reviewStatus = segmentReviewStatus(segment)
  const score = phraseValueScore(card.phrase_value_score ?? segment.phrase_value_score)
  return card.quality?.status === 'needs_review' || reviewStatus === 'needs_review' || Boolean(score && score >= 3)
}

export function applyCardSelection(project: Project, mode: 'recommended' | 'reviewable') {
  let selected = 0
  const nextProject = {
    ...project,
    segments: project.segments.map((segment) => ({
      ...segment,
      cards: segment.cards.map((card) => {
        const enabled =
          mode === 'recommended'
            ? isRecommendedCardForExport(segment, card)
            : isReviewableCardForExport(segment, card)
        if (enabled) selected += 1
        return { ...card, enabled }
      }),
    })),
  }
  return { project: nextProject, selected }
}
