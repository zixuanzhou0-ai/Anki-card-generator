import type { Card, DocumentFocus, DocumentStudyMode, Project, Segment, SegmentFilter } from './types'

type InternalReviewStatus = 'recommended' | 'needs_review' | 'reject' | 'duplicate' | 'unreviewed'

export function badgeText(count: number) {
  return count > 0 ? `${count} 张已选` : '未选择卡片'
}

export function qualityLabel(card: Card) {
  const status = card.quality?.status
  if (status === 'reject') return '已过滤'
  return '可用卡'
}

export function qualityClass(card: Card) {
  return card.quality?.status === 'reject' ? 'filtered' : 'usable'
}

export const segmentFilterOptions: Array<{ id: SegmentFilter; label: string }> = [
  { id: 'all', label: '全部片段' },
  { id: 'selected', label: '含已选卡片' },
  { id: 'unselected', label: '无已选卡片' },
]

export function phraseValueScore(value: number | string | null | undefined) {
  const score = Number(value)
  return Number.isFinite(score) ? score : null
}

export function isPlaceholderPhrase(value: string | null | undefined) {
  const phrase = String(value ?? '').trim().toLowerCase()
  return !phrase || phrase === 'key expression' || phrase === 'n/a' || phrase === '核心知识点'
}

export function clipText(value: string, maxLength: number) {
  const text = value.replace(/\s+/g, ' ').trim()
  if (text.length <= maxLength) return text
  return `${text.slice(0, Math.max(0, maxLength - 1)).trim()}…`
}

export function isKnowledgeSegment(segment: Segment) {
  return segment.cards.some((card) => card.type === 'knowledge')
}

export function isDocumentReadingSegment(segment: Segment, documentStudyMode?: DocumentStudyMode) {
  return (
    documentStudyMode === 'language_reading' ||
    segment.document_card_kind === 'language_reading' ||
    segment.cards.some((card) => card.document_card_kind === 'language_reading')
  )
}

export function segmentPhraseTitle(segment: Segment, documentStudyMode?: DocumentStudyMode) {
  if (isDocumentReadingSegment(segment, documentStudyMode)) {
    if (!isPlaceholderPhrase(segment.phrase)) return segment.phrase
    const cardPhrase = segment.cards.find((card) => !isPlaceholderPhrase(card.phrase))?.phrase
    if (cardPhrase) return cardPhrase
    return segment.text ? `精读点：${clipText(segment.text, 34)}` : '待模型提炼精读点'
  }
  if (isKnowledgeSegment(segment)) {
    if (!isPlaceholderPhrase(segment.phrase)) return segment.phrase
    const cardPhrase = segment.cards.find((card) => !isPlaceholderPhrase(card.phrase))?.phrase
    if (cardPhrase) return cardPhrase
    return segment.text ? `知识点：${clipText(segment.text, 34)}` : '待模型提炼知识点'
  }
  if (!isPlaceholderPhrase(segment.phrase)) return segment.phrase
  return segment.text ? `待选：${clipText(segment.text, 34)}` : '待模型挑选表达'
}

export function segmentPhraseLabel(segment: Segment, documentStudyMode?: DocumentStudyMode) {
  if (isDocumentReadingSegment(segment, documentStudyMode)) {
    if (!isPlaceholderPhrase(segment.phrase)) return segment.phrase
    return segment.cards.find((card) => !isPlaceholderPhrase(card.phrase))?.phrase ?? '待模型提炼精读点'
  }
  if (isKnowledgeSegment(segment)) {
    if (!isPlaceholderPhrase(segment.phrase)) return segment.phrase
    return segment.cards.find((card) => !isPlaceholderPhrase(card.phrase))?.phrase ?? '待模型提炼知识点'
  }
  return isPlaceholderPhrase(segment.phrase) ? '待模型挑选表达' : segment.phrase
}

export function phraseTypeLabel(value: string | null | undefined) {
  const type = String(value ?? '').trim()
  if (type === 'spoken_phrase') return '口语短句'
  if (type === 'sentence_frame') return '句型框架'
  if (type === 'collocation') return '自然搭配'
  if (type === 'discourse_marker') return '话语标记'
  if (type === 'listening_sentence') return '听力句'
  if (type === 'vocabulary_usage') return '语境生词'
  if (type === 'grammar_pattern') return '语法框架'
  return ''
}

export function candidateKindLabel(value: string | null | undefined) {
  const type = String(value ?? '').trim()
  if (type === 'expression') return '表达'
  if (type === 'contextual_vocab') return '语境生词'
  if (type === 'grammar_pattern') return '语法框架'
  if (type === 'listening_feature') return '听力难点'
  if (type === 'pragmatic_risk') return '语气 / 风险'
  return type
}

export function knowledgeTypeLabel(value: DocumentFocus | string | null | undefined) {
  const type = String(value ?? '').trim()
  if (type === 'concepts') return '概念卡'
  if (type === 'arguments') return '观点卡'
  if (type === 'terms') return '术语卡'
  if (type === 'examples') return '例子卡'
  return type
}

export function segmentTrainingFocus(segment: Segment, documentStudyMode?: DocumentStudyMode) {
  if (isDocumentReadingSegment(segment, documentStudyMode)) {
    const card = segment.cards.find((item) => item.type === 'knowledge') ?? segment.cards[0]
    const focus =
      card?.learning_target ||
      card?.learning_goal ||
      card?.how_to_use_it ||
      card?.why_it_matters ||
      card?.teacher_note ||
      segment.phrase_card_focus ||
      ''
    const typeLabel = phraseTypeLabel(segment.phrase_type) || knowledgeTypeLabel(segment.knowledge_type ?? card?.knowledge_type)
    if (typeLabel && focus) return `${typeLabel}：${focus}`
    return focus || typeLabel || '等待模型提炼精读动作'
  }
  if (isKnowledgeSegment(segment)) {
    const card = segment.cards.find((item) => item.type === 'knowledge') ?? segment.cards[0]
    const typeLabel = knowledgeTypeLabel(segment.knowledge_type ?? card?.knowledge_type)
    const focus =
      card?.learning_target ||
      card?.learning_goal ||
      card?.why_it_matters ||
      card?.why ||
      card?.teacher_note ||
      ''
    if (typeLabel && focus) return `${typeLabel}：${focus}`
    return focus || typeLabel || '等待模型提炼记忆动作'
  }
  const typeLabel = phraseTypeLabel(segment.phrase_type)
  const focus = segment.phrase_card_focus || segment.cards.find((card) => card.learning_goal)?.learning_goal || ''
  if (typeLabel && focus) return `${typeLabel}：${focus}`
  return focus || typeLabel || '等待模型给出训练点'
}

export function segmentReviewStatus(segment: Segment): InternalReviewStatus {
  const status = String(segment.phrase_review_status ?? '').trim()
  if (segment.cards.length > 0 && segment.cards.every((card) => card.quality?.status === 'reject')) return 'reject'
  if (status === 'recommended' || status === 'needs_review' || status === 'reject' || status === 'duplicate') {
    return status
  }
  if (segment.cards.some((card) => card.quality?.status === 'recommended')) return 'recommended'
  if (segment.cards.some((card) => card.quality?.status === 'needs_review')) return 'needs_review'
  if (!segment.cards.length || segment.cards.every((card) => card.quality?.status === 'reject')) return 'reject'
  return 'unreviewed'
}

export function segmentStatusLabel(status: InternalReviewStatus) {
  if (status === 'recommended' || status === 'needs_review') return '可用'
  if (status === 'reject') return '已过滤'
  if (status === 'duplicate') return '重复过滤'
  return '未检查'
}

export function segmentMatchesFilter(segment: Segment, filter: SegmentFilter) {
  if (filter === 'all') return true
  const selectedCards = segment.cards.filter((card) => card.enabled).length
  if (filter === 'selected') return selectedCards > 0
  if (filter === 'unselected') return selectedCards === 0
  return true
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
  if (quality === 'needs_review') return false
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

export function isUsableCardForExport(segment: Segment, card: Card) {
  return isReviewableCardForExport(segment, card)
}

export function applyCardSelection(project: Project, mode: 'recommended' | 'reviewable') {
  let selected = 0
  const segments = project.segments.map((segment) => ({
    ...segment,
    cards: segment.cards.map((card) => {
      const enabled =
        mode === 'recommended'
          ? isRecommendedCardForExport(segment, card)
          : isReviewableCardForExport(segment, card)
      if (enabled) selected += 1
      return { ...card, enabled }
    }),
  }))
  const nextProject = {
    ...project,
    quality_funnel: project.quality_funnel
      ? {
          ...project.quality_funnel,
          selected_card_count: selected,
        }
      : {
          selected_card_count: selected,
        },
    segments,
  }
  return { project: nextProject, selected }
}

export function applyUsableCardSelection(project: Project) {
  let selected = 0
  const segments = project.segments.map((segment) => ({
    ...segment,
    cards: segment.cards.map((card) => {
      const enabled = isUsableCardForExport(segment, card)
      if (enabled) selected += 1
      return { ...card, enabled }
    }),
  }))
  const nextProject = {
    ...project,
    selection_strategy: 'catch_all' as const,
    quality_funnel: project.quality_funnel
      ? {
          ...project.quality_funnel,
          usable_card_count: selected,
          selected_card_count: selected,
        }
      : {
          usable_card_count: selected,
          selected_card_count: selected,
        },
    segments,
  }
  return { project: nextProject, selected }
}
