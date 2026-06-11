import type { CandidateKind, GenerateRequest, Level, ReviewDensity } from './types'

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
  hard_blocked: '硬阻断',
}

export function selectableLearningPoint(point: LearningPointItem) {
  return point.status === 'recommended' || point.status === 'candidate_only'
}

export function defaultSelectedLearningPointIds(
  points: LearningPointItem[],
  options: { reviewDensity?: ReviewDensity } = {},
) {
  const recommended = points.filter((point) => point.status === 'recommended')
  if (options.reviewDensity !== 'fast') {
    return new Set(recommended.map((point) => point.id))
  }

  const bestBySource = new Map<string, LearningPointItem>()
  for (const point of recommended) {
    const sourceId = point.source_segment_id || point.source_sentence || point.id
    const current = bestBySource.get(sourceId)
    if (!current || learningPointSelectionScore(point) > learningPointSelectionScore(current)) {
      bestBySource.set(sourceId, point)
    }
  }
  return new Set([...bestBySource.values()].map((point) => point.id))
}

function learningPointSelectionScore(point: LearningPointItem) {
  const baseScore = Number(point.final_score ?? point.ai_value_score ?? point.value_score ?? 0)
  const kindBonus = point.candidate_kind === 'expression' ? 0.08 : point.candidate_kind === 'contextual_vocab' ? 0.04 : 0
  return baseScore + kindBonus
}

export function selectedLearningPoints(points: LearningPointItem[], selectedIds: Set<string>) {
  return points.filter((point) => selectedIds.has(point.id) && selectableLearningPoint(point))
}
