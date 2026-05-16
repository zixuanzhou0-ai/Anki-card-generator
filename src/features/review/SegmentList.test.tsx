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
      type_label: '词伙卡',
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

    expect(screen.getByText(/推荐 · 5\/5/)).toBeInTheDocument()
    expect(screen.getByText(/训练点：练 figure out 的口语解决问题表达/)).toBeInTheDocument()
    expect(screen.getByText('1/1 张已选 · 推荐 5/5')).toBeInTheDocument()
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
})
