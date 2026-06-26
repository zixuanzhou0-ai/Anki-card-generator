import { describe, expect, it } from 'vitest'

import type { Card, Segment } from './types'
import {
  applyCardSelection,
  cardHasExportBlockingContent,
  getExportSelectionStats,
  isRecommendedCardForExport,
  isUsableCardForExport,
  qualityClass,
  qualityLabel,
  removeExportBlockedCardSelection,
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

  it('does not select cards that still contain draft or internal export text', () => {
    const draft = {
      ...baseCard,
      definition: '本地文档草稿，需要人工确认。',
      quality: { score: 90, status: 'recommended' as const, issues: ['本地文档草稿，需要人工确认。'] },
    }
    const recommended = { ...baseCard, id: 'card-2', quality: { score: 90, status: 'recommended' as const, issues: [] } }
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
      segments: [{ ...baseSegment, cards: [draft, recommended] }],
      created_at: 1,
    }

    expect(cardHasExportBlockingContent(draft)).toBe(true)
    expect(isRecommendedCardForExport(baseSegment, draft)).toBe(false)
    const result = applyCardSelection(project, 'recommended')

    expect(result.selected).toBe(1)
    expect(result.project.segments[0].cards.map((card) => card.enabled)).toEqual([false, true])
  })

  it('does not block a card only because a quality note asks for human review', () => {
    const reviewNoteOnly = {
      ...baseCard,
      quality: { score: 80, status: 'recommended' as const, issues: ['本地规则卡，需要人工确认。'] },
    }

    expect(cardHasExportBlockingContent(reviewNoteOnly)).toBe(false)
    expect(qualityLabel(reviewNoteOnly)).toBe('可用卡')
    expect(qualityClass(reviewNoteOnly)).toBe('usable')
    expect(isRecommendedCardForExport(baseSegment, reviewNoteOnly)).toBe(true)
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

  it('removes already selected draft cards before export while preserving safe selections', () => {
    const draft = {
      ...baseCard,
      enabled: true,
      teacher_note: '正式导出前需要 AI 精修。',
      quality: { score: 62, status: 'needs_review' as const, issues: ['需要 AI 精修。'] },
    }
    const safe = {
      ...baseCard,
      id: 'card-2',
      enabled: true,
      quality: { score: 90, status: 'recommended' as const, issues: [] },
    }
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
      quality_funnel: { selected_card_count: 2 },
      segments: [{ ...baseSegment, cards: [draft, safe] }],
      created_at: 1,
    }

    const result = removeExportBlockedCardSelection(project)

    expect(result.removed).toBe(1)
    expect(result.selected).toBe(1)
    expect(result.project.segments[0].cards.map((card) => card.enabled)).toEqual([false, true])
    expect(result.project.quality_funnel?.selected_card_count).toBe(1)
  })

  it('treats model fallback cards as repair-required instead of exportable', () => {
    const fallback = {
      ...baseCard,
      enabled: true,
      quality: {
        score: 58,
        status: 'needs_review' as const,
        issues: ['\u7528\u6237\u5df2\u52fe\u9009\uff0c\u6a21\u578b\u672a\u5b8c\u6574\u8fd4\u56de\u65f6\u7531\u7cfb\u7edf\u4fdd\u5e95\u751f\u6210\u3002'],
      },
    }
    const safe = {
      ...baseCard,
      id: 'safe-card',
      enabled: true,
      quality: { score: 90, status: 'recommended' as const, issues: [] },
    }
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
      quality_funnel: { selected_card_count: 2 },
      segments: [{ ...baseSegment, cards: [fallback, safe] }],
      created_at: 1,
    }

    expect(cardHasExportBlockingContent(fallback)).toBe(true)
    expect(isUsableCardForExport(baseSegment, fallback)).toBe(false)

    const result = removeExportBlockedCardSelection(project)

    expect(result.removed).toBe(1)
    expect(result.selected).toBe(1)
    expect(result.project.segments[0].cards.map((card) => card.enabled)).toEqual([false, true])
  })

  it('marks document draft and manual-confirmation cards as repair-required, not exportable', () => {
    const draft = {
      ...baseCard,
      enabled: true,
      phrase: '自动草稿卡：需要人工确认',
      teacher_note: '内部提示：正式导出前需要人工确认。',
      quality: { score: 70, status: 'needs_review' as const, issues: [] },
    }
    const safe = {
      ...baseCard,
      id: 'safe-card',
      enabled: true,
      quality: { score: 90, status: 'recommended' as const, issues: [] },
    }
    const project = {
      id: 'project-1',
      title: 'Document Project',
      source_mode: 'document' as const,
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
      card_types: ['knowledge' as const],
      segments: [{ ...baseSegment, cards: [draft, safe] }],
      created_at: 1,
    }

    const stats = getExportSelectionStats(project)

    expect(cardHasExportBlockingContent(draft)).toBe(true)
    expect(qualityLabel(draft)).toBe('需修复')
    expect(qualityClass(draft)).toBe('blocked')
    expect(stats).toMatchObject({
      totalCards: 2,
      exportableCards: 1,
      repairRequiredCards: 1,
      selectedCards: 2,
      selectedExportableCards: 1,
      selectedRepairRequiredCards: 1,
    })
  })

  it('blocks document draft text leaked through visible planning fields', () => {
    const draft = {
      ...baseCard,
      enabled: true,
      difficulty_reason: '本地文档草稿按当前水平和文本复杂度估计。',
      quality: { score: 90, status: 'recommended' as const, issues: [] },
    }
    const project = {
      id: 'project-1',
      title: 'Document Project',
      source_mode: 'document' as const,
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
      card_types: ['knowledge' as const],
      segments: [{ ...baseSegment, cards: [draft] }],
      created_at: 1,
    }

    const stats = getExportSelectionStats(project)

    expect(cardHasExportBlockingContent(draft)).toBe(true)
    expect(qualityLabel(draft)).toBe('需修复')
    expect(stats).toMatchObject({
      totalCards: 1,
      exportableCards: 0,
      repairRequiredCards: 1,
      selectedCards: 1,
      selectedExportableCards: 0,
      selectedRepairRequiredCards: 1,
    })
  })
})
