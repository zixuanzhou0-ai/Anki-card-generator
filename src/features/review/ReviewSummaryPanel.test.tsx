import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { Project } from '../../domain/types'
import { ReviewSummaryPanel } from './ReviewSummaryPanel'

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
    expect(screen.getByRole('button', { name: /待审1/ })).toBeInTheDocument()
  })
})
