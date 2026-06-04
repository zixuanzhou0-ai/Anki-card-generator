import { describe, expect, it } from 'vitest'

import type { Card, Segment } from './types'
import {
  applyCardSelection,
  isRecommendedCardForExport,
  segmentMatchesFilter,
  segmentPhraseTitle,
  segmentReviewStatus,
} from './quality'

const baseCard: Card = {
  id: 'card-1',
  type: 'phrase',
  type_label: '表达卡',
  enabled: false,
  english: 'It turns out this works.',
  chinese: '结果这真的有用。',
  phrase: 'it turns out',
  definition: '',
  collocations: '',
  context: '',
  example: '',
  chinese_feel: '',
  why: '',
  difficulty: 'B1',
  teacher_note: '',
  cloze: '____ this works.',
}

const baseSegment: Segment = {
  id: 'seg-1',
  start: 1,
  end: 3,
  source_time: '00:00:01.000 - 00:00:03.000',
  text: 'It turns out this works.',
  duration: 2,
  recommendation: 5,
  phrase: 'it turns out',
  cards: [baseCard],
}

describe('review quality helpers', () => {
  it('does not show key expression placeholders as phrase titles', () => {
    const title = segmentPhraseTitle({ ...baseSegment, phrase: 'key expression' })

    expect(title).toContain('待选')
    expect(title).not.toBe('key expression')
  })

  it('matches segments by selected and unselected card state', () => {
    const segment = { ...baseSegment, cards: [{ ...baseCard, enabled: true }] }

    expect(segmentMatchesFilter(segment, 'selected')).toBe(true)
    expect(segmentMatchesFilter(segment, 'unselected')).toBe(false)
  })

  it('lets rejected card quality override a conflicting recommended segment status', () => {
    const rejected = { ...baseCard, quality: { score: 16, status: 'reject' as const, issues: ['too formal'] } }
    const segment = { ...baseSegment, phrase_review_status: 'recommended', cards: [rejected] }

    expect(segmentReviewStatus(segment)).toBe('reject')
    expect(segmentMatchesFilter(segment, 'selected')).toBe(false)
    expect(segmentMatchesFilter(segment, 'unselected')).toBe(true)
  })

  it('selects only recommended cards in recommended mode', () => {
    const recommended = { ...baseCard, quality: { score: 90, status: 'recommended' as const, issues: [] } }
    const rejected = { ...baseCard, id: 'card-2', quality: { score: 20, status: 'reject' as const, issues: [] } }
    const project = {
      id: 'project-1',
      title: 'Project',
      video_path: '',
      subtitle_path: '',
      language: 'English',
      level: 'B1' as const,
      template_id: 'immersive' as const,
      content_toggles: {
        daily: true,
        slang: true,
        sarcasm: true,
        business: true,
        culture: true,
        profanity: false,
        romance: false,
        rare: false,
      },
      card_types: ['phrase' as const],
      segments: [{ ...baseSegment, cards: [recommended, rejected] }],
      created_at: 1,
    }

    expect(isRecommendedCardForExport(baseSegment, recommended)).toBe(true)
    const result = applyCardSelection(project, 'recommended')

    expect(result.selected).toBe(1)
    expect(result.project.segments[0].cards.map((card) => card.enabled)).toEqual([true, false])
  })

  it('does not auto-export review cards just because their segment is recommended', () => {
    const recommended = { ...baseCard, quality: { score: 90, status: 'recommended' as const, issues: [] } }
    const review = { ...baseCard, id: 'card-2', quality: { score: 62, status: 'needs_review' as const, issues: ['needs human check'] } }
    const project = {
      id: 'project-1',
      title: 'Project',
      video_path: '',
      subtitle_path: '',
      language: 'English',
      level: 'B1' as const,
      template_id: 'immersive' as const,
      content_toggles: {
        daily: true,
        slang: true,
        sarcasm: true,
        business: true,
        culture: true,
        profanity: false,
        romance: false,
        rare: false,
      },
      card_types: ['phrase' as const],
      segments: [{ ...baseSegment, phrase_review_status: 'recommended', cards: [recommended, review] }],
      created_at: 1,
    }

    const result = applyCardSelection(project, 'recommended')

    expect(result.selected).toBe(1)
    expect(result.project.segments[0].cards.map((card) => card.enabled)).toEqual([true, false])
  })

  it('selects recommended plus needs_review cards in reviewable mode', () => {
    const recommended = { ...baseCard, quality: { score: 90, status: 'recommended' as const, issues: [] } }
    const review = { ...baseCard, id: 'card-2', quality: { score: 62, status: 'needs_review' as const, issues: [] } }
    const rejected = { ...baseCard, id: 'card-3', quality: { score: 20, status: 'reject' as const, issues: [] } }
    const project = {
      id: 'project-1',
      title: 'Project',
      video_path: '',
      subtitle_path: '',
      language: 'en',
      level: 'B1' as const,
      template_id: 'immersive' as const,
      content_toggles: {
        daily: true,
        slang: true,
        sarcasm: true,
        business: true,
        culture: true,
        profanity: false,
        romance: false,
        rare: false,
      },
      card_types: ['phrase' as const],
      selection_strategy: 'catch_all' as const,
      segments: [{ ...baseSegment, cards: [recommended, review, rejected] }],
      created_at: 1,
    }

    const result = applyCardSelection(project, 'reviewable')

    expect(result.selected).toBe(2)
    expect(result.project.segments[0].cards.map((card) => card.enabled)).toEqual([true, true, false])
    expect(result.project.quality_funnel?.selected_card_count).toBe(2)
  })
})
