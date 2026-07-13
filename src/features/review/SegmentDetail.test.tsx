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
      learning_target: '练解决问题时的自然表达',
      why_it_matters: '它比 understand 更像口语里的“弄明白”。',
      how_to_use_it: '下次说搞清楚原因或办法时，用 figure out + what/why/how。',
      phrase: 'figure out',
      quality: { issues: ['语境清楚'], score: 5, status: 'recommended' },
      teacher_note: '很常见。',
      type: 'phrase',
      type_label: '表达卡',
      why: '',
    },
  ],
  duration: 2,
  end: 2,
  id: 'seg-1',
  phrase: 'figure out',
  phrase_card_focus: '解决问题时的自然表达',
  phrase_decision_reason: '可迁移，口语常用。',
  phrase_type: 'collocation',
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
        onSetSegmentCardsEnabled={vi.fn()}
        onUpdateCard={onUpdateCard}
      />,
    )

    fireEvent.change(screen.getByLabelText(/中文意思/), { target: { value: '想出办法' } })

    expect(screen.getByText('I figured it out.')).toBeInTheDocument()
    expect(screen.getByText(/可导出卡片/)).toBeInTheDocument()
    expect(screen.getByText(/自然搭配：解决问题时的自然表达/)).toBeInTheDocument()
    expect(screen.getByText(/表达类型：自然搭配/)).toBeInTheDocument()
    expect(screen.getByText(/为什么值得学：它比 understand 更像口语里的“弄明白”。/)).toBeInTheDocument()
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
        onSetSegmentCardsEnabled={onSetSegmentCardsEnabled}
        onUpdateCard={vi.fn()}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: '本段停用' }))

    expect(onSetSegmentCardsEnabled).toHaveBeenCalledWith(false, 'seg-1')
  })

  it('shows a useful error instead of a silent black preview', () => {
    render(
      <SegmentDetail
        motionDuration={0}
        prefersReducedMotion
        previewRate={1}
        segment={segment}
        videoSrc=""
        videoError="视频预览不可用：文件未获授权"
        onSetSegmentCardsEnabled={vi.fn()}
        onUpdateCard={vi.fn()}
      />,
    )

    expect(screen.getByRole('alert')).toHaveTextContent('视频预览不可用：文件未获授权')
  })
  it('shows real pronunciation fields without inferred placeholder status', () => {
    render(
      <SegmentDetail
        language="en"
        motionDuration={0}
        prefersReducedMotion
        previewRate={1}
        segment={{
          ...segment,
          cards: [
            {
              ...segment.cards[0],
              phonetic_ipa: '/wʌt ɪf/',
              spoken_ipa: '/wəd ɪf/',
              source_spoken_ipa: '/wəd ɪf wi/',
              pronunciation_note: '弱读 what if。',
              pronunciation_meta: {
                language_code: 'en',
                accent_profile: 'en-US-general',
                notation_system: 'ipa_en_connected',
                generation_basis: 'subtitle_inferred',
                field_confidence: { phonetic_ipa: 'high', spoken_ipa: 'medium', source_spoken_ipa: 'medium' },
                same_as_standard_reason: null,
                validation_issues: [],
                field_changes: [
                  {
                    field: 'source_spoken_ipa',
                    action: 'hidden',
                    code: 'SOURCE_PRONUNCIATION_TOO_SHORT',
                    message: '原句听感只覆盖答案词，已隐藏。',
                  },
                ],
              },
            },
          ],
        }}
        videoSrc=""
        onSetSegmentCardsEnabled={vi.fn()}
        onUpdateCard={vi.fn()}
      />,
    )

    expect(screen.getByText(/标准读法（IPA）：\/wʌt ɪf\//)).toBeInTheDocument()
    expect(screen.getByText(/推测口语读法：\/wəd ɪf\//)).toBeInTheDocument()
    expect(screen.getByText(/推测原句读法：\/wəd ɪf wi\//)).toBeInTheDocument()
    expect(screen.queryByText(/推测原句读法状态：已隐藏/)).not.toBeInTheDocument()
    expect(screen.queryByText(/未实听/)).not.toBeInTheDocument()
  })
})
