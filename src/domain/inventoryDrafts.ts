import type { Card, LearningContentKind, LearningPointInventoryItem, Project, Segment } from './types'

function secondsFromTimestamp(value: string) {
  const parts = value.trim().split(':').map(Number)
  if (!value.trim() || parts.some((part) => !Number.isFinite(part))) return 0
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2]
  if (parts.length === 2) return parts[0] * 60 + parts[1]
  return parts[0] ?? 0
}

function timeRangeFromSourceTime(value: string) {
  const [startRaw, endRaw] = value.split(/\s+-\s+|\s+–\s+/)
  const start = secondsFromTimestamp(startRaw || '0')
  const end = secondsFromTimestamp(endRaw || '') || start + 2.5
  return { start, end: Math.max(end, start + 0.5) }
}

function clozeForCandidate(sentence: string, answer: string) {
  const source = sentence.trim()
  const escaped = answer.trim().replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  if (!source || !escaped) return `${answer} -> ____`
  const pattern = new RegExp(escaped, 'i')
  if (pattern.test(source)) return source.replace(pattern, '____')
  return `${source}\n____ = ${answer}`
}

function candidateTypeLabel(kind: string | undefined) {
  if (kind === 'contextual_vocab') return '语境生词'
  if (kind === 'grammar_pattern') return '语法框架'
  if (kind === 'listening_feature') return '听力难点'
  if (kind === 'pragmatic_risk') return '语气 / 风险'
  return '表达'
}

function contentKindForCandidate(kind: LearningPointInventoryItem['candidate_kind']): LearningContentKind {
  if (kind === 'contextual_vocab') return 'vocabulary'
  if (kind === 'grammar_pattern') return 'grammar'
  if (kind === 'listening_feature') return 'listening'
  return 'phrase'
}

function stableDraftCardId(item: LearningPointInventoryItem) {
  return `draft_${item.id.replace(/[^a-zA-Z0-9_-]/g, '_')}`
}

export function draftCardFromInventoryItem(item: LearningPointInventoryItem): Card {
  const answer = item.answer_core || item.exact_span || item.normalized_answer || '候选学习点'
  const reason = item.reason || item.filter_reason || item.learning_action || '从学习点清单自动生成的草稿卡。'
  const level = item.estimated_level || '自动'
  const duplicateHint =
    item.status === 'hidden_duplicate' ? '该学习点曾被系统折叠为重复风险项，请确认是否确实需要单独学习。' : ''
  return {
    id: stableDraftCardId(item),
    type: 'phrase',
    type_label: `${candidateTypeLabel(item.candidate_kind)}草稿`,
    enabled: true,
    card_role: 'primary',
    learning_goal: item.learning_action,
    decision_reason: reason,
    phrase_value_score: item.value_score ?? 3,
    phrase_decision_reason: reason,
    phrase_card_focus: item.learning_action,
    phrase_review_status: 'needs_review',
    phrase_type: item.phrase_type,
    learning_point_id: item.id,
    candidate_kind: item.candidate_kind,
    exact_span: item.exact_span,
    normalized_answer: item.normalized_answer || answer,
    candidate_source: 'learning_point_inventory',
    learning_point_schema_version: 1,
    source_evidence: item.source_sentence,
    english: item.source_sentence,
    chinese: '',
    phrase: answer,
    definition: item.learning_action || '自动草稿卡：请补充准确释义。',
    collocations: reason,
    context: item.source_sentence,
    example: item.source_sentence,
    chinese_feel: '',
    why: reason,
    difficulty: level,
    estimated_level: item.estimated_level,
    difficulty_reason: '由合法学习点自动生成；请在导出前确认难度和释义。',
    teacher_note: `${duplicateHint ? `${duplicateHint} ` : ''}自动草稿卡：已进入可用卡片区，建议检查中文释义、例句和发音后导出。`,
    cloze: clozeForCandidate(item.source_sentence, answer),
    learning_target: item.learning_action,
    why_it_matters: reason,
    how_to_use_it: item.learning_action,
    natural_chinese: '',
    retrieval_prompt: item.source_sentence,
    answer_core: answer,
    usage_boundary: duplicateHint,
    confusable_note: '',
    quality: {
      score: item.status === 'hidden_duplicate' ? 55 : 62,
      status: 'needs_review',
      issues: [item.status === 'hidden_duplicate' ? '重复风险草稿，需人工确认。' : '自动草稿卡，需人工检查。'],
    },
  }
}

function draftSegmentFromInventoryItem(item: LearningPointInventoryItem, card: Card): Segment {
  const range = timeRangeFromSourceTime(item.source_time)
  return {
    id: `candidate_${item.id}`,
    start: range.start,
    end: range.end,
    media_start: range.start,
    media_end: range.end,
    media_source_time: item.source_time,
    source_time: item.source_time,
    text: item.source_sentence,
    duration: range.end - range.start,
    recommendation: Math.max(1, Math.min(5, Math.round(Number(item.value_score) || 3))),
    phrase: item.answer_core || item.exact_span,
    phrase_value_score: item.value_score ?? 3,
    phrase_decision_reason: item.reason,
    phrase_reject_reason: '',
    phrase_card_focus: item.learning_action,
    phrase_review_status: 'needs_review',
    phrase_review_source: 'learning_point_inventory',
    phrase_type: item.phrase_type,
    learning_point_id: item.id,
    candidate_kind: item.candidate_kind,
    exact_span: item.exact_span,
    normalized_answer: item.normalized_answer || item.answer_core,
    answer_core: item.answer_core,
    candidate_source: 'learning_point_inventory',
    learning_point_schema_version: 1,
    source_segment_id: item.source_segment_id,
    content_kind: contentKindForCandidate(item.candidate_kind),
    source_evidence: item.source_sentence,
    learning_points: [
      {
        id: item.id,
        kind: item.candidate_kind,
        exact_span: item.exact_span,
        answer_core: item.answer_core,
        difficulty: item.estimated_level,
        value_score: item.value_score,
        reason: item.reason,
        suggested_card_type: 'phrase',
        content_kind: contentKindForCandidate(item.candidate_kind),
        normalized_answer: item.normalized_answer,
        source_evidence: item.source_sentence,
      },
    ],
    cards: [card],
  }
}

function cardExistsForInventoryItem(segments: Segment[], item: LearningPointInventoryItem) {
  const draftId = stableDraftCardId(item)
  for (const segment of segments) {
    for (const card of segment.cards) {
      if (card.learning_point_id === item.id || card.id === item.card_id || card.id === draftId) {
        return card.id
      }
    }
  }
  return null
}

function appendLearningPoint(segment: Segment, item: LearningPointInventoryItem) {
  if (segment.learning_points?.some((point) => point.id === item.id)) return segment.learning_points
  return [
    ...(segment.learning_points ?? []),
    {
      id: item.id,
      kind: item.candidate_kind,
      exact_span: item.exact_span,
      answer_core: item.answer_core,
      difficulty: item.estimated_level,
      value_score: item.value_score,
      reason: item.reason,
      suggested_card_type: 'phrase',
      content_kind: contentKindForCandidate(item.candidate_kind),
      normalized_answer: item.normalized_answer,
      source_evidence: item.source_sentence,
    },
  ]
}

function findTargetSegmentIndex(segments: Segment[], item: LearningPointInventoryItem) {
  return segments.findIndex(
    (segment) =>
      segment.source_segment_id === item.source_segment_id ||
      segment.id === item.source_segment_id ||
      (segment.text === item.source_sentence && segment.source_time === item.source_time),
  )
}

function projectCardStats(segments: Segment[]) {
  const cardCount = segments.reduce((total, segment) => total + segment.cards.length, 0)
  const selected = segments.reduce((total, segment) => total + segment.cards.filter((card) => card.enabled).length, 0)
  return { cardCount, selected }
}

export function materializeLearningPointInventory(project: Project) {
  const inventory = project.learning_point_inventory ?? []
  if (!inventory.length) return { project, added: 0 }

  let added = 0
  let segments = project.segments
  const nextInventory = inventory.map((item) => {
    if (item.status === 'hard_blocked') return item
    const existingCardId = cardExistsForInventoryItem(segments, item)
    if (existingCardId) {
      return {
        ...item,
        status: 'card_generated' as const,
        card_id: item.card_id || existingCardId,
        filter_reason: item.filter_reason || '已存在对应可用卡片。',
      }
    }

    const card = draftCardFromInventoryItem(item)
    const targetIndex = findTargetSegmentIndex(segments, item)
    if (targetIndex >= 0) {
      segments = segments.map((segment, index) =>
        index === targetIndex
          ? {
              ...segment,
              learning_points: appendLearningPoint(segment, item),
              cards: [...segment.cards, card],
            }
          : segment,
      )
    } else {
      segments = [...segments, draftSegmentFromInventoryItem(item, card)]
    }
    added += 1
    return {
      ...item,
      status: 'card_generated' as const,
      card_id: card.id,
      filter_reason:
        item.filter_reason ||
        (item.status === 'hidden_duplicate'
          ? '已自动生成为重复风险草稿卡，请在导出前确认是否保留。'
          : '已自动生成为草稿卡。'),
    }
  })

  if (!added && nextInventory === inventory) return { project, added }

  const { cardCount, selected } = projectCardStats(segments)
  const candidateOnlyCount = nextInventory.filter((item) => item.status === 'candidate_only').length
  const hiddenDuplicateCount = nextInventory.filter((item) => item.status === 'hidden_duplicate').length
  const hardBlockedCount = nextInventory.filter((item) => item.status === 'hard_blocked').length

  return {
    project: {
      ...project,
      learning_point_inventory: nextInventory,
      quality_funnel: {
        ...(project.quality_funnel ?? {}),
        card_count: cardCount,
        usable_card_count: cardCount,
        selected_card_count: selected,
        candidate_only_learning_point_count: candidateOnlyCount,
        hidden_duplicate_learning_point_count: hiddenDuplicateCount,
        hard_blocked_learning_point_count: hardBlockedCount,
      },
      segments,
    },
    added,
  }
}
