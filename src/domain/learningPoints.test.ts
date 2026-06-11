import { describe, expect, it } from 'vitest'

import { defaultSelectedLearningPointIds, type LearningPointItem } from './learningPoints'

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
  it('keeps full review mode behavior by selecting every recommended learning point', () => {
    const ids = defaultSelectedLearningPointIds([
      point({ id: 'lp-1', source_segment_id: 'src-1', answer_core: 'run the register', final_score: 4.8 }),
      point({ id: 'lp-2', source_segment_id: 'src-1', answer_core: 'register', final_score: 4.2 }),
      point({ id: 'lp-3', source_segment_id: 'src-2', answer_core: 'turns out', final_score: 4.6 }),
    ])

    expect([...ids].sort()).toEqual(['lp-1', 'lp-2', 'lp-3'])
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
})
