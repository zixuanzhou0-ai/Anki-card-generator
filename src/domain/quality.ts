import type { Card, DocumentFocus, DocumentStudyMode, Project, Segment, SegmentFilter } from './types'
import { CARD_VERIFICATION_STALE, FALLBACK_CARD_REQUIRES_REVIEW } from './reliability'

type InternalReviewStatus = 'recommended' | 'needs_review' | 'reject' | 'duplicate' | 'unreviewed'

export function badgeText(count: number) {
  return count > 0 ? `${count} 张已选` : '未选择卡片'
}

export function qualityLabel(card: Card) {
  if (cardHasExportBlockingContent(card)) return '需修复'
  const status = card.quality?.status
  if (status === 'recommended') return '可导出'
  if (status === 'needs_review') return '需复查'
  if (status === 'reject') return '已过滤'
  return '未验证'
}

export function qualityClass(card: Card) {
  if (cardHasExportBlockingContent(card)) return 'blocked'
  const status = card.quality?.status
  if (status === 'recommended') return 'usable'
  if (status === 'needs_review') return 'review'
  return status === 'reject' ? 'filtered' : 'blocked'
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

const exportBlockingTextPatterns = [
  '待精修',
  '本地 fallback',
  '本地草稿',
  '本地文档草稿',
  '本地文档精读草稿',
  '自动草稿卡',
  '预览草稿',
  '本地待审',
  '正式导出前',
  '内部提示',
  '需要人工确认',
  '需人工确认',
  '需要 AI 精修',
  '模型未完整返回',
  '模型未返回',
  '系统保底生成',
  '保底生成',
  '兜底生成',
  '只保证结构完整',
  '不建议直接作为正式学习内容',
  '当作本句目标表达',
  'natural object',
  'complete sentence',
]

const manualConfirmationOnlyPatterns = ['需要人工确认', '需人工确认']

const exportBlockingCardFields: Array<keyof Card> = [
  'learning_goal',
  'decision_reason',
  'phrase_decision_reason',
  'phrase_reject_reason',
  'phrase_card_focus',
  'learning_action',
  'chinese',
  'definition',
  'collocations',
  'teacher_note',
  'context',
  'example',
  'chinese_feel',
  'why',
  'difficulty_reason',
  'phrase',
  'answer_core',
  'learning_target',
  'why_it_matters',
  'how_to_use_it',
  'natural_chinese',
  'usage_boundary',
  'confusable_note',
  'replacement_examples',
  'avoid_reason',
]

export function containsExportBlockingText(value: unknown) {
  const text = Array.isArray(value) ? value.join(' ') : String(value ?? '')
  if (!text.trim()) return false
  const lowered = text.toLowerCase()
  return exportBlockingTextPatterns.some((pattern) => text.includes(pattern) || lowered.includes(pattern.toLowerCase()))
}

function exportBlockingPatternsForText(value: unknown) {
  const text = Array.isArray(value) ? value.join(' ') : String(value ?? '')
  if (!text.trim()) return []
  const lowered = text.toLowerCase()
  return exportBlockingTextPatterns.filter((pattern) => text.includes(pattern) || lowered.includes(pattern.toLowerCase()))
}

function containsExportBlockingQualityIssue(value: unknown) {
  const patterns = exportBlockingPatternsForText(value)
  if (!patterns.length) return false
  return patterns.some((pattern) => !manualConfirmationOnlyPatterns.includes(pattern))
}

const exportBlockingCardFieldLabels: Partial<Record<keyof Card, string>> = {
  chinese: '中文意思',
  definition: '释义 / 搭配',
  collocations: '搭配 / 理由',
  teacher_note: '老师评语',
  context: '语境',
  example: '例句',
  chinese_feel: '中文语感',
  why: '学习理由',
  difficulty_reason: '难度说明',
  phrase: '学习点',
  answer_core: '答案',
  learning_goal: '学习目标',
  decision_reason: '选择理由',
  phrase_decision_reason: '学习点理由',
  phrase_reject_reason: '过滤理由',
  phrase_card_focus: '卡片重点',
  learning_action: '学习动作',
  learning_target: '记忆目标',
  why_it_matters: '重要性',
  how_to_use_it: '使用方式',
  natural_chinese: '自然中文',
  usage_boundary: '使用边界',
  confusable_note: '易混提醒',
  replacement_examples: '替换例句',
  avoid_reason: '过滤原因',
}

export type ExportRepairItem = {
  segmentId: string
  cardId: string
  sourceTime: string
  title: string
  reasons: string[]
}

export type ExportSelectionStats = {
  totalCards: number
  exportableCards: number
  repairRequiredCards: number
  selectedCards: number
  selectedExportableCards: number
  selectedRepairRequiredCards: number
}

export function exportBlockingReasonsForCard(card: Card) {
  const reasons = exportBlockingCardFields
    .filter((field) => containsExportBlockingText(card[field]))
    .map((field) => {
      const label = exportBlockingCardFieldLabels[field] ?? String(field)
      return `${label}：${clipText(String(card[field] ?? ''), 72)}`
    })
  const issueReasons = (card.quality?.issues ?? [])
    .filter((issue) => containsExportBlockingQualityIssue(issue))
    .map((issue) => `质量提示：${clipText(issue, 72)}`)
  const reliabilityReasons: string[] = []
  if (
    card.generation_source === 'fallback_from_selected_learning_point' ||
    card.generation_source === 'basic_from_selected_learning_point'
  ) {
    reliabilityReasons.push(`可靠性门禁：${FALLBACK_CARD_REQUIRES_REVIEW}`)
  }
  if (card.verification_status && card.verification_status !== 'verified') {
    reliabilityReasons.push(
      `可靠性门禁：${card.verification_status === 'stale' ? CARD_VERIFICATION_STALE : 'CARD_VERIFICATION_NOT_PASSED'}`,
    )
  }
  return [...reasons, ...issueReasons, ...reliabilityReasons]
}

export function cardHasExportBlockingContent(card: Card) {
  if (
    card.generation_source === 'fallback_from_selected_learning_point' ||
    card.generation_source === 'basic_from_selected_learning_point'
  ) return true
  if (card.verification_status && card.verification_status !== 'verified') return true
  if (exportBlockingCardFields.some((field) => containsExportBlockingText(card[field]))) return true
  return (card.quality?.issues ?? []).some((issue) => containsExportBlockingQualityIssue(issue))
}

function exportRepairTitle(segment: Segment, card: Card) {
  return (
    card.answer_core ||
    card.phrase ||
    segment.phrase ||
    card.english ||
    segment.text ||
    '未命名卡片'
  )
}

export function exportRepairItems(project: Project | null, maxItems = 5): ExportRepairItem[] {
  const items: ExportRepairItem[] = []
  for (const segment of project?.segments ?? []) {
    for (const card of segment.cards) {
      if (!cardHasExportBlockingContent(card)) continue
      items.push({
        segmentId: segment.id,
        cardId: card.id,
        sourceTime: segment.source_time || '',
        title: clipText(exportRepairTitle(segment, card), 48),
        reasons: exportBlockingReasonsForCard(card).slice(0, 3),
      })
      if (items.length >= maxItems) return items
    }
  }
  return items
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
  if (cardHasExportBlockingContent(card)) return false
  const quality = card.quality?.status
  if (quality === 'recommended') return true
  if (quality === 'needs_review') return false
  if (quality === 'reject') return false
  const reviewStatus = segmentReviewStatus(segment)
  const score = phraseValueScore(card.phrase_value_score ?? segment.phrase_value_score)
  return reviewStatus === 'recommended' || Boolean(score && score >= 4)
}

export function isReviewableCardForExport(segment: Segment, card: Card) {
  if (cardHasExportBlockingContent(card)) return false
  if (card.quality?.status === 'reject') return false
  if (isRecommendedCardForExport(segment, card)) return true
  const reviewStatus = segmentReviewStatus(segment)
  const score = phraseValueScore(card.phrase_value_score ?? segment.phrase_value_score)
  return card.quality?.status === 'needs_review' || reviewStatus === 'needs_review' || Boolean(score && score >= 3)
}

export function isUsableCardForExport(segment: Segment, card: Card) {
  return isRecommendedCardForExport(segment, card)
}

export function getExportSelectionStats(project: Project | null): ExportSelectionStats {
  const stats: ExportSelectionStats = {
    totalCards: 0,
    exportableCards: 0,
    repairRequiredCards: 0,
    selectedCards: 0,
    selectedExportableCards: 0,
    selectedRepairRequiredCards: 0,
  }
  for (const segment of project?.segments ?? []) {
    for (const card of segment.cards) {
      const exportable = isUsableCardForExport(segment, card)
      const repairRequired = cardHasExportBlockingContent(card)
      stats.totalCards += 1
      if (exportable) stats.exportableCards += 1
      if (repairRequired) stats.repairRequiredCards += 1
      if (card.enabled) {
        stats.selectedCards += 1
        if (exportable) stats.selectedExportableCards += 1
        if (repairRequired) stats.selectedRepairRequiredCards += 1
      }
    }
  }
  return stats
}

export function applyCardSelection(project: Project, mode: 'recommended' | 'reviewable') {
  let selected = 0
  let selectedExportable = 0
  const segments = project.segments.map((segment) => ({
    ...segment,
    cards: segment.cards.map((card) => {
      const enabled =
        mode === 'recommended'
          ? isRecommendedCardForExport(segment, card)
          : isReviewableCardForExport(segment, card)
      if (enabled) selected += 1
      if (enabled && isUsableCardForExport(segment, card)) selectedExportable += 1
      return { ...card, enabled }
    }),
  }))
  const nextProject = {
    ...project,
    quality_funnel: project.quality_funnel
      ? {
          ...project.quality_funnel,
          selected_card_count: selected,
          selected_exportable_card_count: selectedExportable,
          selected_repair_required_card_count: 0,
        }
      : {
          selected_card_count: selected,
          selected_exportable_card_count: selectedExportable,
          selected_repair_required_card_count: 0,
        },
    segments,
  }
  return { project: nextProject, selected }
}

export function removeExportBlockedCardSelection(project: Project) {
  let removed = 0
  let selected = 0
  const segments = project.segments.map((segment) => ({
    ...segment,
    cards: segment.cards.map((card) => {
      if (card.enabled && !isUsableCardForExport(segment, card)) {
        removed += 1
        return { ...card, enabled: false }
      }
      if (card.enabled) selected += 1
      return card
    }),
  }))
  if (removed === 0) return { project, removed, selected }
  const nextProject = {
    ...project,
    quality_funnel: project.quality_funnel
      ? {
          ...project.quality_funnel,
          selected_card_count: selected,
          selected_exportable_card_count: selected,
          selected_repair_required_card_count: 0,
        }
      : {
          selected_card_count: selected,
          selected_exportable_card_count: selected,
          selected_repair_required_card_count: 0,
        },
    segments,
  }
  return {
    project: nextProject,
    removed,
    selected,
  }
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
          selected_exportable_card_count: selected,
          selected_repair_required_card_count: 0,
        }
      : {
          usable_card_count: selected,
          selected_card_count: selected,
          selected_exportable_card_count: selected,
          selected_repair_required_card_count: 0,
        },
    segments,
  }
  return { project: nextProject, selected }
}
