import { describe, expect, it } from 'vitest'

import {
  batchSelectableLearningPoint,
  cardableLearningPoint,
  defaultSelectedLearningPointIds,
  learningPointGenerationBatchSize,
  selectedLearningPoints,
  type LearningPointItem,
} from './learningPoints'

function point(overrides: Partial<LearningPointItem>): LearningPointItem {
  return {
    id: 'lp-base',
    source_segment_id: 'src-1',
    source_sentence: 'Can you run the register for a minute?',
    source_time: '00:00:01.000 - 00:00:03.000',
    exact_span: 'run the register',
    answer_core: 'run the register',
    normalized_answer: 'run the register',
    type: 'phrase',
    candidate_kind: 'expression',
    phrase_type: 'collocation',
    level: 'B1',
    learning_action: '训练服务业场景搭配。',
    learning_action_key: 'expression:run the register',
    value_score: 4.5,
    final_score: 4.5,
    reason: '可迁移词伙。',
    confidence: 'high',
    status: 'recommended',
    status_reason: '推荐。',
    source: 'model_review',
    ...overrides,
  }
}

describe('defaultSelectedLearningPointIds', () => {
  it('keeps small full review batches selected by default', () => {
    const ids = defaultSelectedLearningPointIds([
      point({ id: 'lp-1', source_segment_id: 'src-1', answer_core: 'run the register', final_score: 4.8 }),
      point({ id: 'lp-2', source_segment_id: 'src-1', answer_core: 'register', final_score: 4.2 }),
      point({ id: 'lp-3', source_segment_id: 'src-2', answer_core: 'turns out', final_score: 4.6 }),
    ])

    expect([...ids].sort()).toEqual(['lp-1', 'lp-2', 'lp-3'])
  })

  it('caps large recommended sets to the strongest 12 learning points by default', () => {
    const ids = defaultSelectedLearningPointIds(
      Array.from({ length: 18 }, (_, index) =>
        point({ id: `lp-${index + 1}`, source_segment_id: `src-${index + 1}`, final_score: 18 - index }),
      ),
    )

    expect(ids.size).toBe(12)
    expect([...ids]).toEqual(Array.from({ length: 12 }, (_, index) => `lp-${index + 1}`))
  })

  it('prioritizes teachable spoken phrases and sentence frames over short collocations', () => {
    const ids = defaultSelectedLearningPointIds(
      [
        point({
          id: 'lp-demanding-job',
          source_segment_id: 'src-1',
          answer_core: 'demanding job',
          exact_span: 'demanding job',
          phrase_type: 'collocation',
          final_score: 4.3,
          value_score: 4.3,
        }),
        point({
          id: 'lp-gave-out',
          source_segment_id: 'src-2',
          answer_core: 'gave out',
          exact_span: 'gave out',
          phrase_type: 'spoken_phrase',
          final_score: 4.3,
          value_score: 4.3,
        }),
        point({
          id: 'lp-struck-me',
          source_segment_id: 'src-3',
          answer_core: 'what struck me was that',
          exact_span: 'what struck me was that',
          phrase_type: 'sentence_frame',
          final_score: 4.3,
          value_score: 4.3,
        }),
      ],
      { maxSelected: 2 },
    )

    expect([...ids]).toEqual(['lp-struck-me', 'lp-gave-out'])
  })

  it('allows callers to explicitly select every recommended learning point', () => {
    const ids = defaultSelectedLearningPointIds(
      Array.from({ length: 18 }, (_, index) =>
        point({ id: `lp-${index + 1}`, source_segment_id: `src-${index + 1}` }),
      ),
      { maxSelected: null },
    )

    expect(ids.size).toBe(18)
  })

  it('selects every recommended learning point when explicitly requested, even in fast review mode', () => {
    const ids = defaultSelectedLearningPointIds(
      [
        point({ id: 'lp-register', source_segment_id: 'src-1', answer_core: 'register', final_score: 4.2 }),
        point({ id: 'lp-run-register', source_segment_id: 'src-1', answer_core: 'run the register', final_score: 4.9 }),
        point({ id: 'lp-turns-out', source_segment_id: 'src-2', answer_core: 'turns out', final_score: 4.6 }),
      ],
      { reviewDensity: 'fast', maxSelected: null },
    )

    expect([...ids].sort()).toEqual(['lp-register', 'lp-run-register', 'lp-turns-out'])
  })

  it('selects only the highest-value recommended learning point per source in fast review mode', () => {
    const ids = defaultSelectedLearningPointIds(
      [
        point({ id: 'lp-register', source_segment_id: 'src-1', answer_core: 'register', candidate_kind: 'contextual_vocab', final_score: 4.2, value_score: 4.2 }),
        point({ id: 'lp-run-register', source_segment_id: 'src-1', answer_core: 'run the register', candidate_kind: 'expression', final_score: 4.9, value_score: 4.9 }),
        point({ id: 'lp-right-now', source_segment_id: 'src-1', answer_core: 'right now', final_score: 3.8, value_score: 3.8 }),
        point({ id: 'lp-turns-out', source_segment_id: 'src-2', answer_core: 'turns out', final_score: 4.6, value_score: 4.6 }),
      ],
      { reviewDensity: 'fast' },
    )

    expect([...ids].sort()).toEqual(['lp-run-register', 'lp-turns-out'])
  })

  it('does not default-select risky source sentences even if stale data marks them recommended', () => {
    const ids = defaultSelectedLearningPointIds([
      point({ id: 'lp-clean', source_segment_id: 'src-1', answer_core: 'run the register', final_score: 4.2 }),
      point({
        id: 'lp-risky',
        source_segment_id: 'src-2',
        source_sentence: 'they they are from a a different time before the internet',
        answer_core: 'different time',
        final_score: 5,
        source_sentence_quality_status: 'needs_review',
        source_sentence_quality_flags: ['repeated_adjacent_words'],
      }),
    ])

    expect([...ids]).toEqual(['lp-clean'])
  })

  it('does not default-select overly long source sentences even if stale data marks them recommended', () => {
    const ids = defaultSelectedLearningPointIds([
      point({ id: 'lp-clean', source_segment_id: 'src-1', answer_core: 'run the register', final_score: 4.2 }),
      point({
        id: 'lp-too-long',
        source_segment_id: 'src-2',
        source_sentence:
          'The speaker moves through the setup, the example, the warning, the contrast, and the takeaway so quickly that this subtitle is better reviewed before it becomes a default card.',
        answer_core: 'the takeaway',
        final_score: 5,
        source_sentence_quality_status: 'needs_review',
        source_sentence_quality_flags: ['too_long'],
      }),
    ])

    expect([...ids]).toEqual(['lp-clean'])
  })

  it('keeps risky source sentences out of bulk selection while preserving explicit manual selection', () => {
    const risky = point({
      id: 'lp-risky',
      source_sentence: 'they they are from a a different time before the internet',
      answer_core: 'different time',
      source_sentence_quality_status: 'needs_review',
      source_sentence_quality_flags: ['repeated_adjacent_words'],
      status: 'candidate_only',
    })

    expect(batchSelectableLearningPoint(risky)).toBe(false)
    expect(cardableLearningPoint(risky)).toBe(true)
    expect(selectedLearningPoints([risky], new Set(['lp-risky']))).toEqual([risky])
  })

  it('keeps subtitle-join artifacts out of bulk selection while preserving explicit manual selection', () => {
    const joined = point({
      id: 'lp-joined',
      source_sentence: 'Samra has traveled to She was in Puerto Rico where I just was.',
      answer_core: 'where I just was',
      exact_span: 'where I just was',
      status: 'candidate_only',
    })

    expect(batchSelectableLearningPoint(joined)).toBe(false)
    expect(cardableLearningPoint(joined)).toBe(true)
    expect(selectedLearningPoints([joined], new Set(['lp-joined']))).toEqual([joined])
  })

  it('keeps proper-name fragments out of bulk selection while preserving explicit manual selection', () => {
    const nameFragment = point({
      id: 'lp-name-fragment',
      source_sentence: "I'm not a Sam.",
      answer_core: 'a Sam',
      exact_span: 'a Sam',
      status: 'candidate_only',
    })

    expect(batchSelectableLearningPoint(nameFragment)).toBe(false)
    expect(cardableLearningPoint(nameFragment)).toBe(true)
    expect(selectedLearningPoints([nameFragment], new Set(['lp-name-fragment']))).toEqual([nameFragment])
  })

  it('keeps obvious auto-caption grammar artifacts out of bulk selection', () => {
    const captionArtifact = point({
      id: 'lp-caption-artifact',
      source_sentence: 'Nobody say Sam in the comments.',
      answer_core: 'Nobody say',
      exact_span: 'Nobody say',
      status: 'recommended',
    })

    expect(batchSelectableLearningPoint(captionArtifact)).toBe(false)
    expect(cardableLearningPoint(captionArtifact)).toBe(true)
    expect(selectedLearningPoints([captionArtifact], new Set(['lp-caption-artifact']))).toEqual([captionArtifact])
  })

  it('keeps visibly unfinished subtitle tails out of bulk selection', () => {
    const unfinishedTail = point({
      id: 'lp-unfinished-tail',
      source_sentence: "also like hatching chicks, we have like some mixed breeds and yeah, they're really cute and they all",
      answer_core: 'mixed breeds',
      exact_span: 'mixed breeds',
      status: 'candidate_only',
    })

    expect(batchSelectableLearningPoint(unfinishedTail)).toBe(false)
    expect(cardableLearningPoint(unfinishedTail)).toBe(true)
    expect(selectedLearningPoints([unfinishedTail], new Set(['lp-unfinished-tail']))).toEqual([unfinishedTail])
  })

  it('excludes duplicates and hard-blocked items from cardable full selection', () => {
    expect(cardableLearningPoint(point({ status: 'recommended' }))).toBe(true)
    expect(cardableLearningPoint(point({ status: 'candidate_only' }))).toBe(true)
    expect(cardableLearningPoint(point({ status: 'hidden_duplicate' }))).toBe(false)
    expect(cardableLearningPoint(point({ status: 'hard_blocked' }))).toBe(false)
  })
})

describe('learningPointGenerationBatchSize', () => {
  it('keeps small queues conservative and scales large queues to reduce sequential worker jobs', () => {
    expect(learningPointGenerationBatchSize(0)).toBe(12)
    expect(learningPointGenerationBatchSize(1)).toBe(12)
    expect(learningPointGenerationBatchSize(12)).toBe(12)
    expect(learningPointGenerationBatchSize(13)).toBe(12)
    expect(learningPointGenerationBatchSize(48)).toBe(12)
    expect(learningPointGenerationBatchSize(49)).toBe(12)
    expect(learningPointGenerationBatchSize(120)).toBe(12)
    expect(learningPointGenerationBatchSize(121)).toBe(12)
    expect(learningPointGenerationBatchSize(314)).toBe(12)
  })
})
