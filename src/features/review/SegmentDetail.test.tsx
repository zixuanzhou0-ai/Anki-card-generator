import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { Segment } from '../../domain/types'
import { SegmentDetail } from './SegmentDetail'

afterEach(() => cleanup())

const segment: Segment = {
  cards: [
    {
      chinese: '弄明白',
      chinese_feel: '',
      cloze: '',
      collocations: 'figure out why',
      context: '',
      definition: 'understand or solve something',
      difficulty: 'B1',
      enabled: true,
      english: 'I figured it out.',
      example: '',
      id: 'card-1',
      learning_goal: '掌握 figure out',
      phrase: 'figure out',
      quality: { issues: ['语境清楚'], score: 5, status: 'recommended' },
      teacher_note: '很常见。',
      type: 'phrase',
      type_label: '词伙卡',
      why: '',
    },
  ],
  duration: 2,
  end: 2,
  id: 'seg-1',
  phrase: 'figure out',
  phrase_card_focus: '解决问题时的自然表达',
  phrase_decision_reason: '可迁移，口语常用。',
  phrase_review_status: 'recommended',
  phrase_value_score: 5,
  recommendation: 5,
  source_time: '00:00:01.000 - 00:00:03.000',
  start: 1,
  text: 'I figured it out.',
}

describe('SegmentDetail', () => {
  it('renders segment fields and edits a card', () => {
    const onUpdateCard = vi.fn()

    render(
      <SegmentDetail
        motionDuration={0}
        prefersReducedMotion
        previewRate={0.75}
        segment={segment}
        videoSrc=""
        onPreviewRateChange={vi.fn()}
        onSetSegmentCardsEnabled={vi.fn()}
        onUpdateCard={onUpdateCard}
      />,
    )

    fireEvent.change(screen.getByLabelText(/中文意思/), { target: { value: '想出办法' } })

    expect(screen.getByText('I figured it out.')).toBeInTheDocument()
    expect(screen.getByText(/AI 词伙评审/)).toBeInTheDocument()
    expect(onUpdateCard).toHaveBeenCalledWith('seg-1', 'card-1', { chinese: '想出办法' })
  })

  it('can enable or disable all cards in the segment', () => {
    const onSetSegmentCardsEnabled = vi.fn()

    render(
      <SegmentDetail
        motionDuration={0}
        prefersReducedMotion
        previewRate={1}
        segment={segment}
        videoSrc=""
        onPreviewRateChange={vi.fn()}
        onSetSegmentCardsEnabled={onSetSegmentCardsEnabled}
        onUpdateCard={vi.fn()}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: '本段停用' }))

    expect(onSetSegmentCardsEnabled).toHaveBeenCalledWith(false, 'seg-1')
  })
})
