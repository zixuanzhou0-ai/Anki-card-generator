import { describe, expect, it } from 'vitest'

import type { Card, Project, SelectedPointOutcome } from './types'
import {
  applyCardPatchWithReliabilityInvalidation,
  buildReliabilityManifest,
  evaluateProjectReliabilityGate,
  mergeReliabilityManifests,
} from './reliability'

function card(overrides: Partial<Card> = {}): Card {
  return {
    id: 'card-1',
    type: 'phrase',
    type_label: '学习卡',
    enabled: true,
    learning_point_id: 'lp-1',
    english: 'We need to get this over with.',
    chinese: '我们得把这件事赶紧做完。',
    phrase: 'get this over with',
    definition: '把不愉快的事情尽快做完。',
    collocations: '',
    context: '',
    example: '',
    chinese_feel: '',
    why: '',
    difficulty: 'B1',
    teacher_note: '',
    cloze: '',
    generation_source: 'ai_complete',
    verification_status: 'verified',
    quality: { score: 90, status: 'recommended', issues: [] },
    ...overrides,
  }
}

function project(outcomes: SelectedPointOutcome[], cards = [card()]): Project {
  return {
    id: 'project-1',
    title: 'Reliability',
    video_path: '',
    subtitle_path: '',
    language: 'en',
    level: 'B1',
    template_id: 'immersive_v11',
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
    card_types: ['phrase'],
    segments: [
      {
        id: 'seg-1',
        start: 0,
        end: 2,
        source_time: '00:00:00 - 00:00:02',
        text: 'We need to get this over with.',
        duration: 2,
        recommendation: 5,
        phrase: 'get this over with',
        learning_point_id: 'lp-1',
        cards,
      },
    ],
    reliability_manifest: buildReliabilityManifest({ outcomes }),
    created_at: 1,
  }
}

describe('card reliability contract', () => {
  it('fails closed when selected-point accounting is incomplete', () => {
    const manifest = buildReliabilityManifest({
      selectedPointCount: 2,
      outcomes: [{ learning_point_id: 'lp-1', status: 'verified', card_id: 'card-1', blocker_codes: [] }],
    })

    expect(manifest.accounting_complete).toBe(false)
    expect(manifest.decision).toBe('block')
    expect(manifest.blocker_codes).toContain('SELECTED_POINT_ACCOUNTING_INCOMPLETE')
  })

  it('blocks fallback cards even if an old project marks them recommended', () => {
    const target = project(
      [{ learning_point_id: 'lp-1', status: 'verified', card_id: 'card-1', blocker_codes: [] }],
      [card({ generation_source: 'basic_from_selected_learning_point', verification_status: undefined })],
    )

    expect(evaluateProjectReliabilityGate(target)).toMatchObject({
      decision: 'block',
      blockerCodes: expect.arrayContaining(['FALLBACK_CARD_REQUIRES_REVIEW']),
    })
  })

  it('invalidates semantic edits but not selection toggles', () => {
    const target = project([
      { learning_point_id: 'lp-1', status: 'verified', card_id: 'card-1', blocker_codes: [] },
    ])

    const toggled = applyCardPatchWithReliabilityInvalidation(target, 'seg-1', 'card-1', { enabled: false })
    expect(toggled.reliability_manifest?.decision).toBe('pass')
    expect(toggled.segments[0].cards[0].verification_status).toBe('verified')

    const edited = applyCardPatchWithReliabilityInvalidation(target, 'seg-1', 'card-1', {
      chinese: '用户修改后的翻译',
    })
    expect(edited.segments[0].cards[0]).toMatchObject({
      enabled: false,
      verification_status: 'stale',
      verification_stale_fields: ['chinese'],
      quality: { status: 'needs_review' },
    })
    expect(edited.reliability_manifest).toMatchObject({
      decision: 'block',
      verified_count: 0,
      needs_review_count: 1,
    })
    expect(edited.reliability_manifest?.selected_point_outcomes[0].blocker_codes).toContain(
      'USER_EDIT_REQUIRES_REVERIFICATION',
    )
  })

  it('merges batch manifests without losing a terminal outcome', () => {
    const first = buildReliabilityManifest({
      outcomes: [{ learning_point_id: 'lp-1', status: 'verified', card_id: 'card-1', blocker_codes: [] }],
      createdAt: 1,
    })
    const second = buildReliabilityManifest({
      outcomes: [
        {
          learning_point_id: 'lp-2',
          status: 'needs_review',
          card_id: 'card-2',
          blocker_codes: ['FALLBACK_CARD_REQUIRES_REVIEW'],
        },
      ],
      createdAt: 2,
    })

    expect(mergeReliabilityManifests(first, second)).toMatchObject({
      selected_point_count: 2,
      accounting_complete: true,
      verified_count: 1,
      needs_review_count: 1,
      decision: 'block',
    })
  })
})
