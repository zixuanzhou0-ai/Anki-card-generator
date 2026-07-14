import type { CandidateKind, GenerateRequest, Level, ReviewDensity } from './types'

export const DEFAULT_INITIAL_SELECTED_LEARNING_POINT_LIMIT = 12
export const MIN_LEARNING_POINT_GENERATION_BATCH_SIZE = 12
export const MAX_LEARNING_POINT_GENERATION_BATCH_SIZE = 12

export function learningPointGenerationBatchSize(count: number) {
  void count
  return MAX_LEARNING_POINT_GENERATION_BATCH_SIZE
}

export type LearningPointType = 'phrase' | 'spoken' | 'vocab_usage' | 'grammar' | 'listening' | 'pragmatic'
export type LearningPointLevel = Level
export type LearningPointStatus = 'recommended' | 'candidate_only' | 'hidden_duplicate' | 'hard_blocked'
export type LearningPointSource = 'local_rule' | 'model_expansion' | 'model_review' | 'user_added' | string

export type LearningPointRepair = {
  field: string
  action: 'trimmed' | 'normalized' | 'repaired' | 'downgraded' | 'cleared' | string
  reason: string
}

export type LearningPointItem = {
  id: string
  source_segment_id: string
  source_sentence: string
  source_time: string
  start?: number
  end?: number
  exact_span: string
  answer_core: string
  normalized_answer: string
  type: LearningPointType
  candidate_kind: CandidateKind
  phrase_type: string
  level?: LearningPointLevel | string
  estimated_level?: LearningPointLevel | string
  level_reason?: string
  learning_action: string
  learning_action_key: string
  value_score?: number
  level_fit_score?: number
  final_score?: number
  reason: string
  is_spoken_common?: boolean
  confidence: 'high' | 'medium' | 'low' | string
  status: LearningPointStatus
  status_reason: string
  source: LearningPointSource
  validation_status?: string
  validation_issues?: string[]
  repair_history?: LearningPointRepair[]
  ai_decision?: string
  ai_value_score?: number
  ai_reason?: string
  ai_batch_id?: string
  review_source?: 'ai' | 'local_seed' | string
  source_cue_ids?: number[]
  source_cue_count?: number
  source_cue_start?: number
  source_cue_end?: number
  source_cue_time?: string
  source_cue_texts?: string[]
  source_merge_reason?: string
  source_sentence_quality_flags?: string[]
  source_sentence_quality_status?: string
}

export type LearningPointSummary = {
  total: number
  recommended: number
  candidate_only: number
  hidden_duplicate: number
  hard_blocked: number
  by_type: Record<string, number>
  by_level: Record<string, number>
  by_candidate_kind?: Record<string, number>
}

export type SourceSentence = {
  id: string
  source_segment_id: string
  source_sentence: string
  text: string
  previous_sentence?: string
  next_sentence?: string
  start: number
  end: number
  source_time: string
  source_cue_ids?: number[]
  source_cue_count?: number
  source_cue_start?: number
  source_cue_end?: number
  source_cue_time?: string
  source_cue_texts?: string[]
  source_merge_reason?: string
  source_sentence_quality_flags?: string[]
  source_sentence_quality_status?: string
}

export type LearningPointExtractionResult = {
  id: string
  title: string
  source_mode: GenerateRequest['source_mode']
  video_path: string
  subtitle_path: string
  language: GenerateRequest['language'] | string
  level_mode: GenerateRequest['level_mode'] | string
  level: Level | string
  source_sentences: SourceSentence[]
  learning_points: LearningPointItem[]
  learning_point_summary: LearningPointSummary
  timing_ms?: Record<string, number>
  review_basis?: 'ai_reviewed' | string
  ai_model_provider?: string
  ai_model_name?: string
  local_candidate_count?: number
  ai_reviewed_source_count?: number
  ai_reviewed_candidate_count?: number
  ai_recommended_count?: number
  ai_candidate_count?: number
  ai_rejected_count?: number
  quality_funnel?: {
    source_sentence_count?: number
    ai_reviewed_source_count?: number
    learning_point_count?: number
    recommended_learning_point_count?: number
    candidate_only_learning_point_count?: number
    hidden_duplicate_learning_point_count?: number
    hard_blocked_learning_point_count?: number
    [key: string]: unknown
  }
  ai_model_errors?: Array<Record<string, unknown>>
  warnings?: string[]
}

export type GenerationQueueSummary = {
  count: number
  batchSize: number
  batchCount: number
  batchMode: boolean
  completedBatches: number
  completedCount: number
  generatedCount: number
  missingCount: number
  exportableCount: number
  modeLabel: string
  sourceLabel: string
  includesVideo: boolean
  includesOriginalAudio: boolean
  includesSentenceTts: boolean
  includesPhraseTts: boolean
  estimatedModelBatches: number
  estimatedMediaTasks: number
  estimatedTtsSemanticChecks: number
  highRiskShortExpressionCount: number
  ttsSemanticPassed: number
  ttsSemanticFailed: number
  ttsSemanticManualReview: number
  securityWarnings: string[]
  highRisk: boolean
}

export const learningPointTypeLabels: Record<LearningPointType | string, string> = {
  phrase: '词伙',
  spoken: '口语',
  vocab_usage: '单词用法',
  grammar: '语法框架',
  listening: '听力点',
  pragmatic: '语气边界',
}

export const learningPointStatusLabels: Record<LearningPointStatus, string> = {
  recommended: '推荐',
  candidate_only: '候选',
  hidden_duplicate: '重复折叠',
  hard_blocked: '不可制卡',
}

const SOURCE_SENTENCE_REVIEW_FLAGS = new Set([
  'fragment',
  'possible_bad_join',
  'repeated_adjacent_words',
  'too_long',
  'rolling_caption_uncertain',
  'rolling_caption_overlap',
])

const BAD_SUBTITLE_JOIN_PATTERN =
  /\b(?:to|from|for|with|about|at|in|on|of|by)\s+(?:I|you|he|she|it|we|they)\s+(?:am|is|are|was|were|have|has|had|do|does|did|will|would|can|could|should|used)\b/i

const PROPER_NAME_FRAGMENT_PATTERN = /^(?:a|an|the)\s+[A-Z][a-z]+(?:['’]s)?$/
const INDEFINITE_PRONOUN_BARE_VERB_PATTERN =
  /^(?:nobody|somebody|someone|everybody|everyone|anybody|anyone)\s+(?:say|go|do|have|make|get|take|come|look|seem|sound|call|need|want|like|know|think|mean|tell|use|work|live|feel|try|walk|drive|eat|feed|remember|believe)\b/i
const INCOMPLETE_SOURCE_SENTENCE_TAIL_PATTERN =
  /\b(?:and|or|but|because|which is|who is|that is|they all|we all|you all|do|does|did|am|is|are|was|were|have|has|had|will|would|can|could|should|to|for|with|from|about|of|in|on|at|by|as|like)\s*[.!?"]?$/i

export function selectableLearningPoint(point: LearningPointItem) {
  return point.status === 'recommended' || point.status === 'candidate_only'
}

export function cardableLearningPoint(point: LearningPointItem) {
  return selectableLearningPoint(point)
}

export function learningPointNeedsSourceReview(point: LearningPointItem) {
  if (point.source_sentence_quality_status === 'needs_review') return true
  if ((point.source_sentence_quality_flags ?? []).some((flag) => SOURCE_SENTENCE_REVIEW_FLAGS.has(String(flag)))) {
    return true
  }

  const sourceSentence = String(point.source_sentence || '').trim()
  if (BAD_SUBTITLE_JOIN_PATTERN.test(sourceSentence)) return true
  if (INCOMPLETE_SOURCE_SENTENCE_TAIL_PATTERN.test(sourceSentence)) return true

  const answer = String(point.answer_core || point.exact_span || point.normalized_answer || '').trim()
  return PROPER_NAME_FRAGMENT_PATTERN.test(answer) || INDEFINITE_PRONOUN_BARE_VERB_PATTERN.test(answer)
}

export function batchSelectableLearningPoint(point: LearningPointItem) {
  return selectableLearningPoint(point) && !learningPointNeedsSourceReview(point)
}

export function defaultSelectedLearningPointIds(
  points: LearningPointItem[],
  options: { reviewDensity?: ReviewDensity; maxSelected?: number | null } = {},
) {
  const recommended = rankLearningPointsForDefaultSelection(
    points.filter((point) => point.status === 'recommended' && batchSelectableLearningPoint(point)),
  )
  if (options.maxSelected === null) {
    return new Set(recommended.map((point) => point.id))
  }

  const limit = Math.max(0, options.maxSelected ?? DEFAULT_INITIAL_SELECTED_LEARNING_POINT_LIMIT)
  const cap = <T,>(items: T[]) => items.slice(0, limit)

  if (options.reviewDensity !== 'fast') {
    return new Set(cap(recommended).map((point) => point.id))
  }

  const bestBySource = new Map<string, LearningPointItem>()
  for (const point of recommended) {
    const sourceId = point.source_segment_id || point.source_sentence || point.id
    const current = bestBySource.get(sourceId)
    if (!current || learningPointSelectionScore(point) > learningPointSelectionScore(current)) {
      bestBySource.set(sourceId, point)
    }
  }
  return new Set(cap([...bestBySource.values()]).map((point) => point.id))
}

export function rankLearningPointsForDefaultSelection(points: LearningPointItem[]) {
  return points
    .map((point, index) => ({ point, index }))
    .sort((left, right) => {
      const delta = learningPointSelectionScore(right.point) - learningPointSelectionScore(left.point)
      return Math.abs(delta) > 0.0001 ? delta : left.index - right.index
    })
    .map(({ point }) => point)
}

export function learningPointSelectionScore(point: LearningPointItem) {
  const baseScore = Number(point.final_score ?? point.ai_value_score ?? point.value_score ?? 0)
  const phraseType = String(point.phrase_type || '').toLowerCase()
  const answer = String(point.answer_core || point.exact_span || '').trim()
  const wordCount = answer.split(/\s+/).filter(Boolean).length
  const kindBonus =
    point.candidate_kind === 'expression' ? 0.08 : point.candidate_kind === 'contextual_vocab' ? 0.04 : 0
  const teachabilityBonus =
    phraseType === 'sentence_frame'
      ? 0.35
      : phraseType === 'spoken_phrase'
        ? 0.32
        : phraseType === 'phrasal_verb'
          ? 0.3
          : phraseType === 'listening_sentence'
            ? 0.18
            : phraseType === 'vocabulary_usage'
              ? 0.08
              : 0
  const collocationPenalty = phraseType === 'collocation' && wordCount <= 2 ? 0.22 : 0
  return baseScore + kindBonus + teachabilityBonus - collocationPenalty
}

export function selectedLearningPoints(points: LearningPointItem[], selectedIds: Set<string>) {
  return points.filter((point) => selectedIds.has(point.id) && selectableLearningPoint(point))
}
