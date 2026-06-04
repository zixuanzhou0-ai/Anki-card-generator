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
        project={{
          ...project,
          source_mode: 'local',
          source_info: { subtitle_source: 'auto_matched', subtitle_path: 'F:\\demo.srt' },
        }}
        qualityCounts={{ total: 4, recommended: 2, review: 1, rejected: 1 }}
        qualityDiagnostics={{
          avgScore: 4.2,
          candidates: 8,
          duplicate: 1,
          rejectReasons: [],
          rejectedSegments: 1,
          shortReason: '',
        }}
        qualityFunnel={{
          candidate_segments: 8,
          card_count: 4,
          usable_card_count: 3,
          selected_card_count: 3,
          filtered_learning_point_count: 2,
          duplicate_learning_point_count: 1,
          low_value_filtered_count: 1,
        }}
        selectedCardCount={3}
        segmentFilter="all"
        segmentReviewCounts={{ all: 8, selected: 3, unselected: 5 }}
        onSegmentFilterChange={vi.fn()}
      />,
    )

    expect(screen.getByText('3/3')).toBeInTheDocument()
    expect(screen.getByText('已生成 3 张可用卡，默认全选')).toBeInTheDocument()
    expect(screen.getByText(/每句最多 4 个学习点/)).toBeInTheDocument()
    expect(screen.getByText('生成卡片数')).toBeInTheDocument()
    expect(screen.getAllByText('发现学习点').length).toBeGreaterThan(0)
    expect(screen.getAllByText('过滤学习点').length).toBeGreaterThan(0)
    expect(screen.getByText(/平均词伙评分/)).toBeInTheDocument()
    expect(screen.getByText('字幕句')).toBeInTheDocument()
    expect(screen.getByText(/自动匹配字幕/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /只看未选\s*5/ })).toBeInTheDocument()
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
        qualityFunnel={{ candidate_segments: 2, usable_card_count: 2, filtered_learning_point_count: 0 }}
        selectedCardCount={1}
        segmentFilter="all"
        segmentReviewCounts={{ all: 2, selected: 1, unselected: 1 }}
        onSegmentFilterChange={vi.fn()}
      />,
    )

    expect(screen.getByText(/知识点质量/)).toBeInTheDocument()
    expect(screen.getByText('文档知识诊断')).toBeInTheDocument()
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
        qualityFunnel={{ candidate_segments: 2, usable_card_count: 2, filtered_learning_point_count: 0 }}
        selectedCardCount={0}
        segmentFilter="all"
        segmentReviewCounts={{ all: 2, selected: 0, unselected: 2 }}
        onSegmentFilterChange={vi.fn()}
      />,
    )

    expect(screen.getByText(/精读点质量/)).toBeInTheDocument()
    expect(screen.getByText('文档精读诊断')).toBeInTheDocument()
    expect(screen.getByText('可用精读卡')).toBeInTheDocument()
    expect(screen.queryByText('平均词伙评分')).not.toBeInTheDocument()
    expect(screen.queryByText('字幕句')).not.toBeInTheDocument()
  })
})
