import { describe, expect, it } from 'vitest'

import { createDemoProject } from './demoProject'
import { materializeLearningPointInventory } from './inventoryDrafts'
import { defaultRequest } from './options'
import { countSelectedCards } from './projectMetrics'
import type { LearningPointInventoryItem, Project } from './types'

function inventoryItem(
  id: string,
  status: LearningPointInventoryItem['status'],
  overrides: Partial<LearningPointInventoryItem> = {},
): LearningPointInventoryItem {
  return {
    id,
    source_segment_id: 'seg_demo_001',
    source_time: '00:00:01 - 00:00:03',
    source_sentence: "I'm gonna run the register.",
    exact_span: id === 'lp-listening' ? "I'm gonna" : 'register',
    answer_core: id === 'lp-listening' ? "I'm gonna" : 'register',
    normalized_answer: id === 'lp-listening' ? "I'm gonna" : 'register',
    candidate_kind: id === 'lp-listening' ? 'listening_feature' : 'contextual_vocab',
    phrase_type: id === 'lp-listening' ? 'listening_sentence' : 'vocabulary_usage',
    estimated_level: 'B1',
    value_score: 3,
    learning_action: id === 'lp-listening' ? '识别 gonna 的弱读。' : '理解 register 在服务业场景里是收银机。',
    reason: '合法学习点，应进入可用卡片区。',
    status,
    ...overrides,
  }
}

describe('materializeLearningPointInventory', () => {
  it('turns every non-blocked inventory item into an enabled draft card', () => {
    const base = createDemoProject(defaultRequest)
    const project: Project = {
      ...base,
      learning_point_inventory: [
        inventoryItem('lp-vocab', 'candidate_only'),
        inventoryItem('lp-listening', 'hidden_duplicate'),
        inventoryItem('lp-blocked', 'hard_blocked', {
          block_reason: 'answer_core 不在原句中。',
        }),
      ],
      quality_funnel: {
        candidate_only_learning_point_count: 1,
        hidden_duplicate_learning_point_count: 1,
        hard_blocked_learning_point_count: 1,
      },
    }

    const result = materializeLearningPointInventory(project)
    const cards = result.project.segments.flatMap((segment) => segment.cards)

    expect(result.added).toBe(2)
    expect(cards.some((card) => card.learning_point_id === 'lp-vocab' && card.enabled)).toBe(true)
    expect(cards.some((card) => card.learning_point_id === 'lp-listening' && card.enabled)).toBe(true)
    expect(cards.some((card) => card.learning_point_id === 'lp-blocked')).toBe(false)
    expect(result.project.learning_point_inventory?.find((item) => item.id === 'lp-vocab')?.status).toBe('card_generated')
    expect(result.project.learning_point_inventory?.find((item) => item.id === 'lp-listening')?.status).toBe('card_generated')
    expect(result.project.learning_point_inventory?.find((item) => item.id === 'lp-blocked')?.status).toBe('hard_blocked')
    expect(result.project.quality_funnel?.candidate_only_learning_point_count).toBe(0)
    expect(result.project.quality_funnel?.hidden_duplicate_learning_point_count).toBe(0)
    expect(result.project.quality_funnel?.hard_blocked_learning_point_count).toBe(1)
    expect(result.project.quality_funnel?.selected_card_count).toBe(countSelectedCards(result.project))
  })

  it('does not duplicate draft cards when materialized more than once', () => {
    const base = createDemoProject(defaultRequest)
    const project: Project = {
      ...base,
      learning_point_inventory: [inventoryItem('lp-vocab', 'candidate_only')],
    }

    const first = materializeLearningPointInventory(project)
    const second = materializeLearningPointInventory(first.project)
    const matchingCards = second.project.segments
      .flatMap((segment) => segment.cards)
      .filter((card) => card.learning_point_id === 'lp-vocab')

    expect(first.added).toBe(1)
    expect(second.added).toBe(0)
    expect(matchingCards).toHaveLength(1)
  })
})
