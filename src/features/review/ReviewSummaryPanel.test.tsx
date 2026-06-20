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
                status: 'hard_failed',
                reason: 'AI 未覆盖该学习点，且保底生成未完成。',
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

    expect(screen.getByText('本次可导出')).toBeInTheDocument()
    expect(screen.getByText('张卡片')).toBeInTheDocument()
    expect(screen.getByText('已选 3 张；其中可导出 3 张。生成总数 4 张。')).toBeInTheDocument()
    expect(screen.getByText(/每句最多 4 个学习点/)).toBeInTheDocument()
    expect(screen.getByText('可导出卡')).toBeInTheDocument()
    expect(screen.getByText('生成总数')).toBeInTheDocument()
    expect(screen.getByText(/智能筛选过程 · 发现 8 个学习点/)).toBeInTheDocument()
    expect(screen.getAllByText('更多学习点').length).toBeGreaterThan(0)
    expect(screen.getByText(/重复 1 · 阻断 0/)).toBeInTheDocument()
    expect(screen.getByText(/学习点制卡：已选 5 · 成功 3 · 硬失败 1 · 质量过滤 1/)).toBeInTheDocument()
    expect(screen.getByText('get this over with')).toBeInTheDocument()
    expect(screen.getByText(/硬失败：AI 未覆盖该学习点，且保底生成未完成/)).toBeInTheDocument()
    expect(screen.getByText('bad point')).toBeInTheDocument()
    expect(screen.getByText(/质量过滤：字段像模板废话/)).toBeInTheDocument()
    expect(screen.getByText('片段筛选')).toBeInTheDocument()
    expect(screen.getByText(/一个片段里可能包含多张卡/)).toBeInTheDocument()
    expect(screen.getByText('字幕句')).toBeInTheDocument()
    expect(screen.getByText(/自动匹配字幕/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /无已选卡片\s*5/ })).toBeInTheDocument()
  })

  it('marks restored document projects as historical and keeps public video labels', () => {
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

    expect(screen.getByText('历史项目')).toBeInTheDocument()
    expect(screen.getByText(/当前发布版只支持本地视频和视频链接/)).toBeInTheDocument()
    expect(screen.getByText(/智能筛选过程 · 发现 2 个学习点/)).toBeInTheDocument()
    expect(screen.getByText('字幕句')).toBeInTheDocument()
    expect(screen.queryByText('文档制卡过程')).not.toBeInTheDocument()
    expect(screen.queryByText('文档片段')).not.toBeInTheDocument()
  })

  it('separates document repair-required draft cards from exportable cards', () => {
    render(
      <ReviewSummaryPanel
        activeTemplateLabel="知识问答卡"
        language="English"
        level="B1"
        project={{
          ...project,
          source_mode: 'document',
          document_study_mode: 'knowledge',
          segments: [
            {
              id: 'doc-1',
              start: 0,
              end: 0,
              source_time: '文档知识点 1',
              text: '什么是语境义优先？',
              duration: 0,
              recommendation: 5,
              phrase: '语境义优先',
              cards: [
                {
                  id: 'draft-card',
                  type: 'knowledge',
                  type_label: '知识卡',
                  enabled: true,
                  english: '什么是语境义优先？',
                  chinese: '本地文档草稿，需要人工确认。',
                  phrase: '语境义优先',
                  definition: '内部提示：正式导出前需要人工确认。',
                  collocations: '',
                  context: '',
                  example: '',
                  chinese_feel: '',
                  why: '',
                  difficulty: 'B1',
                  teacher_note: '',
                  cloze: '',
                },
                {
                  id: 'safe-card',
                  type: 'knowledge',
                  type_label: '知识卡',
                  enabled: true,
                  english: '为什么不能孤立背单词？',
                  chinese: '意义由语境、动作和搭配决定。',
                  phrase: '语境义优先',
                  definition: '在句子关系中理解词义。',
                  collocations: '',
                  context: '阅读真实材料时使用。',
                  example: '',
                  chinese_feel: '',
                  why: '',
                  difficulty: 'B1',
                  teacher_note: '先看证据再记答案。',
                  cloze: '',
                  quality: { score: 90, status: 'recommended', issues: [] },
                },
              ],
            },
          ],
        }}
        qualityCounts={{ total: 2, recommended: 1, review: 0, rejected: 1 }}
        qualityDiagnostics={{
          avgScore: null,
          candidates: 1,
          duplicate: 0,
          rejectReasons: [],
          rejectedSegments: 0,
          shortReason: '',
        }}
        qualityFunnel={{
          candidate_segments: 1,
          card_count: 2,
          exportable_card_count: 1,
          repair_required_card_count: 1,
          selected_card_count: 2,
          selected_exportable_card_count: 1,
          selected_repair_required_card_count: 1,
          usable_card_count: 1,
        }}
        selectedCardCount={2}
        segmentFilter="all"
        segmentReviewCounts={{ all: 1, selected: 1, unselected: 0 }}
        onSegmentFilterChange={vi.fn()}
      />,
    )

    expect(screen.getByText('已选 2 张；其中可导出 1 张，已选需修复 1 张。生成总数 2 张。')).toBeInTheDocument()
    expect(screen.getByText('1 张需修复卡不会导出')).toBeInTheDocument()
    expect(screen.getByText('语境义优先')).toBeInTheDocument()
    expect(screen.getByText(/中文意思：本地文档草稿/)).toBeInTheDocument()
  })

  it('does not expose document reading labels for restored reading projects', () => {
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

    expect(screen.getByText('历史项目')).toBeInTheDocument()
    expect(screen.getByText(/智能筛选过程 · 发现 2 个学习点/)).toBeInTheDocument()
    expect(screen.getByText('可用卡片')).toBeInTheDocument()
    expect(screen.getByText('字幕句')).toBeInTheDocument()
    expect(screen.queryByText('文档精读过程')).not.toBeInTheDocument()
    expect(screen.queryByText('可用精读卡')).not.toBeInTheDocument()
  })
})
