import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { Segment } from '../../domain/types'
import { SegmentList } from './SegmentList'

const segment: Segment = {
  cards: [
    {
      chinese: '弄明白',
      chinese_feel: '',
      cloze: '',
      collocations: '',
      context: '',
      definition: '',
      difficulty: 'B1',
      enabled: true,
      english: 'I figured it out.',
      example: '',
      id: 'card-1',
      learning_goal: '练 figure out 的口语解决问题表达',
      phrase: 'figure out',
      teacher_note: '',
      type: 'phrase',
      type_label: '表达卡',
      why: '',
    },
  ],
  duration: 2,
  end: 2,
  id: 'seg-1',
  phrase: 'figure out',
  phrase_review_status: 'recommended',
  phrase_value_score: 5,
  recommendation: 5,
  source_time: '00:00:01.000 - 00:00:03.000',
  start: 1,
  text: 'I figured it out.',
}

describe('SegmentList', () => {
  it('renders segment status and selection callback', () => {
    const onSelectSegment = vi.fn()
    const onSetSegmentCardsEnabled = vi.fn()

    render(
      <SegmentList
        activeSegmentId="seg-1"
        motionDuration={0}
        prefersReducedMotion
        segments={[segment]}
        onSelectSegment={onSelectSegment}
        onSetSegmentCardsEnabled={onSetSegmentCardsEnabled}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /figure out/ }))

    expect(screen.getByText(/学习点 · 5\/5/)).toBeInTheDocument()
    expect(screen.getByText('I figured it out.')).toBeInTheDocument()
    expect(screen.queryByText(/训练点：/)).not.toBeInTheDocument()
    expect(screen.getByText('1/1 张可导出')).toBeInTheDocument()
    expect(onSelectSegment).toHaveBeenCalledWith('seg-1')

    fireEvent.click(screen.getByRole('checkbox', { name: /选择片段：figure out/ }))
    expect(onSetSegmentCardsEnabled).toHaveBeenCalledWith(false, 'seg-1')
  })

  it('shows an empty filter state', () => {
    render(
      <SegmentList
        activeSegmentId={null}
        motionDuration={0}
        prefersReducedMotion
        segments={[]}
        onSelectSegment={vi.fn()}
        onSetSegmentCardsEnabled={vi.fn()}
      />,
    )

    expect(screen.getByText('当前筛选下没有片段')).toBeInTheDocument()
  })

  it('renders long segment lists progressively', () => {
    const segments = Array.from({ length: 55 }, (_, index) => ({
      ...segment,
      id: `seg-${index + 1}`,
      phrase: `phrase ${index + 1}`,
      cards: segment.cards.map((card) => ({ ...card, id: `card-${index + 1}` })),
    }))

    render(
      <SegmentList
        activeSegmentId="seg-1"
        motionDuration={0}
        prefersReducedMotion
        segments={segments}
        onSelectSegment={vi.fn()}
        onSetSegmentCardsEnabled={vi.fn()}
      />,
    )

    expect(screen.getByText('phrase 48')).toBeInTheDocument()
    expect(screen.queryByText('phrase 49')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /显示更多 7 条/ }))

    expect(screen.getByText('phrase 55')).toBeInTheDocument()
  })
})
