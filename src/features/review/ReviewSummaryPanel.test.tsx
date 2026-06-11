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
          card_generation_diagnostics: {
            items: [
              {
                learning_point_id: 'lp-missing',
                answer_core: 'get this over with',
                status: 'model_missing',
                reason: '模型没有返回这个学习点的完整卡片内容。',
              },
              {
                learning_point_id: 'lp-filtered',
                answer_core: 'bad point',
                status: 'filtered',
                reason: '字段像模板废话。',
              },
            ],
          },
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
          candidate_only_learning_point_count: 2,
          hidden_duplicate_learning_point_count: 1,
          hard_blocked_learning_point_count: 0,
          selected_learning_point_count: 5,
          successful_learning_point_count: 3,
          card_generation_missing_learning_point_count: 1,
          card_generation_filtered_card_count: 1,
        }}
        selectedCardCount={3}
        segmentFilter="all"
        segmentReviewCounts={{ all: 8, selected: 3, unselected: 5 }}
        onSegmentFilterChange={vi.fn()}
      />,
    )

    expect(screen.getByText('本次将导出')).toBeInTheDocument()
    expect(screen.getByText('张卡片')).toBeInTheDocument()
    expect(screen.getByText('只导出当前勾选的卡片；已选 3 / 生成 3')).toBeInTheDocument()
    expect(screen.getByText(/每句最多 4 个学习点/)).toBeInTheDocument()
    expect(screen.getByText('生成可用卡')).toBeInTheDocument()
    expect(screen.getByText('片段')).toBeInTheDocument()
    expect(screen.getByText(/智能筛选过程 · 发现 8 个学习点/)).toBeInTheDocument()
    expect(screen.getAllByText('更多学习点').length).toBeGreaterThan(0)
    expect(screen.getByText(/重复 1 · 阻断 0/)).toBeInTheDocument()
    expect(screen.getByText(/学习点制卡：已选 5 · 成功 3 · 模型未返回 1 · 质量过滤 1/)).toBeInTheDocument()
    expect(screen.getByText('get this over with')).toBeInTheDocument()
    expect(screen.getByText(/模型未返回：模型没有返回这个学习点的完整卡片内容/)).toBeInTheDocument()
    expect(screen.getByText('bad point')).toBeInTheDocument()
    expect(screen.getByText(/质量过滤：字段像模板废话/)).toBeInTheDocument()
    expect(screen.getByText('片段筛选')).toBeInTheDocument()
    expect(screen.getByText(/一个片段里可能包含多张卡/)).toBeInTheDocument()
    expect(screen.getByText('字幕句')).toBeInTheDocument()
    expect(screen.getByText(/自动匹配字幕/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /无已选卡片\s*5/ })).toBeInTheDocument()
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

    expect(screen.getByText(/文档制卡过程 · 发现 2 个学习点/)).toBeInTheDocument()
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

    expect(screen.getByText(/文档精读过程 · 发现 2 个学习点/)).toBeInTheDocument()
    expect(screen.getByText('可用精读卡')).toBeInTheDocument()
    expect(screen.queryByText('平均词伙评分')).not.toBeInTheDocument()
    expect(screen.queryByText('字幕句')).not.toBeInTheDocument()
  })
})
