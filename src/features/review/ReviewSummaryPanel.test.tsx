import '@testing-library/jest-dom/vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { Project } from '../../domain/types'
import { ReviewSummaryPanel } from './ReviewSummaryPanel'

afterEach(() => cleanup())

const project: Project = {
  card_types: ['phrase'],
  content_toggles: {
    business: false,
    culture: false,
    daily: true,
    profanity: false,
    rare: false,
    romance: false,
    sarcasm: false,
    slang: true,
  },
  created_at: 1,
  id: 'p1',
  language: 'English',
  level: 'B1',
  segments: [],
  template_id: 'immersive',
  title: 'Demo',
  video_path: '',
  subtitle_path: '',
}

describe('ReviewSummaryPanel', () => {
  it('shows review metrics and filter counts', () => {
    render(
      <ReviewSummaryPanel
        activeTemplateLabel="沉浸语言"
        language="English"
        level="B1"
        project={project}
        qualityCounts={{ total: 4, recommended: 2, review: 1, rejected: 1 }}
        qualityDiagnostics={{
          avgScore: 4.2,
          candidates: 8,
          duplicate: 1,
          rejectReasons: [],
          rejectedSegments: 1,
          shortReason: '',
        }}
        qualityFunnel={{ candidate_segments: 8, recommended_cards: 2, review_cards: 1, duplicate_segments: 1 }}
        selectedCardCount={3}
        segmentFilter="all"
        segmentReviewCounts={{ all: 8, recommended: 2, needs_review: 1, reject: 1, duplicate: 1 }}
        onSegmentFilterChange={vi.fn()}
      />,
    )

    expect(screen.getByText('3/4')).toBeInTheDocument()
    expect(screen.getByText('推荐保留')).toBeInTheDocument()
    expect(screen.getByText('平均词伙评分')).toBeInTheDocument()
    expect(screen.getByText('字幕句')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /待审1/ })).toBeInTheDocument()
  })

  it('uses document knowledge labels instead of subtitle phrase labels', () => {
    render(
      <ReviewSummaryPanel
        activeTemplateLabel="沉浸语言"
        language="English"
        level="B1"
        project={{ ...project, source_mode: 'document', document_study_mode: 'knowledge' }}
        qualityCounts={{ total: 2, recommended: 1, review: 1, rejected: 0 }}
        qualityDiagnostics={{
          avgScore: null,
          candidates: 2,
          duplicate: 0,
          rejectReasons: [],
          rejectedSegments: 0,
          shortReason: '文档分段较少或可制卡片段不足。',
        }}
        qualityFunnel={{ candidate_segments: 2, recommended_cards: 1, review_cards: 1 }}
        selectedCardCount={1}
        segmentFilter="all"
        segmentReviewCounts={{ all: 2, recommended: 1, needs_review: 1, reject: 0, duplicate: 0 }}
        onSegmentFilterChange={vi.fn()}
      />,
    )

    expect(screen.getByText('知识点质量')).toBeInTheDocument()
    expect(screen.getByText('文档知识流水线')).toBeInTheDocument()
    expect(screen.getByText('文档片段')).toBeInTheDocument()
    expect(screen.queryByText('平均词伙评分')).not.toBeInTheDocument()
    expect(screen.queryByText('字幕句')).not.toBeInTheDocument()
  })

  it('uses document reading labels for language reading projects', () => {
    render(
      <ReviewSummaryPanel
        activeTemplateLabel="沉浸语言"
        language="English"
        level="B1"
        project={{ ...project, source_mode: 'document', document_study_mode: 'language_reading' }}
        qualityCounts={{ total: 2, recommended: 0, review: 2, rejected: 0 }}
        qualityDiagnostics={{
          avgScore: null,
          candidates: 2,
          duplicate: 0,
          rejectReasons: [],
          rejectedSegments: 0,
          shortReason: '多数语言点仍需人工确认。',
        }}
        qualityFunnel={{ candidate_segments: 2, recommended_cards: 0, review_cards: 2 }}
        selectedCardCount={0}
        segmentFilter="all"
        segmentReviewCounts={{ all: 2, recommended: 0, needs_review: 2, reject: 0, duplicate: 0 }}
        onSegmentFilterChange={vi.fn()}
      />,
    )

    expect(screen.getByText('精读点质量')).toBeInTheDocument()
    expect(screen.getByText('文档精读流水线')).toBeInTheDocument()
    expect(screen.getByText('待审精读卡')).toBeInTheDocument()
    expect(screen.queryByText('平均词伙评分')).not.toBeInTheDocument()
    expect(screen.queryByText('字幕句')).not.toBeInTheDocument()
  })
})
