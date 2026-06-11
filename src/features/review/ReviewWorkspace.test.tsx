import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { createDemoProject } from '../../domain/demoProject'
import { defaultRequest } from '../../domain/options'
import {
  countSelectedCards,
  getQualityCounts,
  getQualityDiagnostics,
  getQualityFunnel,
  getSegmentReviewCounts,
} from '../../domain/projectMetrics'
import type { Project, SegmentFilter } from '../../domain/types'
import { ReviewWorkspace } from './ReviewWorkspace'

afterEach(() => cleanup())

function renderWorkspace(project: Project | null, overrides = {}) {
  const qualityCounts = getQualityCounts(project)
  const qualityDiagnostics = getQualityDiagnostics(project, qualityCounts.recommended)
  const firstSegment = project?.segments[0]
  const props = {
    activeSegment: firstSegment,
    activeSegmentId: firstSegment?.id ?? null,
    activeSegmentVideoSrc: '',
    activeTemplateLabel: '沉浸语言 V10',
    ankiVerifying: false,
    ankiVerifyResult: null,
    lastExport: null,
    language: 'English',
    level: 'B1' as const,
    learningPointResult: null,
    maxSegments: 0,
    motionDuration: 0,
    prefersReducedMotion: true,
    previewPanelRef: { current: null },
    previewRate: 1,
    project,
    qualityCounts,
    qualityDiagnostics,
    qualityFunnel: getQualityFunnel(project, qualityCounts, qualityDiagnostics),
    selectedCardCount: countSelectedCards(project),
    selectedLearningPointIds: new Set<string>(),
    segmentFilter: 'all' as SegmentFilter,
    segmentReviewCounts: getSegmentReviewCounts(project),
    sourceMode: 'local' as const,
    templateId: 'immersive',
    visibleSegments: project?.segments ?? [],
    workerBusy: false,
    workerProgress: null,
    status: '准备生成 Anki 卡片。',
    onOpenAnkiImport: vi.fn(),
    onRevealExport: vi.fn(),
    onSegmentFilterChange: vi.fn(),
    onGenerateCardsFromLearningPoints: vi.fn(),
    onInvertCardSelection: vi.fn(),
    onSelectDefaultLearningPoints: vi.fn(),
    onSelectSegment: vi.fn(),
    onSetCardsEnabled: vi.fn(),
    onSetSelectedLearningPointIds: vi.fn(),
    onUpdateCard: vi.fn(),
    onVerifyAnkiImport: vi.fn(),
    ...overrides,
  }

  render(<ReviewWorkspace {...props} />)
  return props
}

describe('ReviewWorkspace', () => {
  it('renders the empty workbench and forwards primary actions', () => {
    renderWorkspace(null)

    expect(screen.getByRole('heading', { name: '生成工作台' })).toBeInTheDocument()
    expect(screen.getByText('审核区会在生成后展开')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /开始生成/ })).not.toBeInTheDocument()
  })

  it('renders generation progress in the workbench while cards are being created', () => {
    renderWorkspace(null, {
      workerBusy: true,
      workerProgress: {
        command: 'generate',
        stage: 'ai',
        percent: 37,
        message: '正在生成卡片正文：第 3/8 批。',
      },
      status: '正在解析字幕、筛选片段并生成卡片草稿。',
    })

    expect(screen.getByRole('heading', { name: '生成中' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '正在制作 Anki 卡片' })).toBeInTheDocument()
    expect(screen.getByText('37%')).toBeInTheDocument()
    expect(screen.getByText('正在生成卡片正文：第 3/8 批。')).toBeInTheDocument()
    expect(screen.getByText('设置已锁定')).toBeInTheDocument()
  })

  it('renders learning point overview before cards are generated', () => {
    const onGenerateCardsFromLearningPoints = vi.fn()
    renderWorkspace(null, {
      learningPointResult: {
        id: 'lp-project',
        title: '字幕素材',
        source_mode: 'local',
        video_path: '',
        subtitle_path: '',
        language: 'en',
        level_mode: 'manual',
        level: 'B1',
        source_sentences: [],
        learning_points: [
          {
            id: 'lp-1',
            source_segment_id: 'src-1',
            source_sentence: "I'm not really in the mood for this right now.",
            source_time: '00:00:01.000 - 00:00:03.000',
            exact_span: 'in the mood for',
            answer_core: 'in the mood for',
            normalized_answer: 'in the mood for',
            type: 'phrase',
            candidate_kind: 'expression',
            phrase_type: 'collocation',
            level: 'B1',
            learning_action: '训练表达“有/没心情做某事”。',
            learning_action_key: 'expression:in the mood for',
            value_score: 4.5,
            reason: '高频口语词伙。',
            confidence: 'high',
            status: 'recommended',
            status_reason: '高价值、合法、不重复。',
            source: 'local_rule',
          },
        ],
        learning_point_summary: {
          total: 1,
          recommended: 1,
          candidate_only: 0,
          hidden_duplicate: 0,
          hard_blocked: 0,
          by_type: { phrase: 1 },
          by_level: { B1: 1 },
        },
        quality_funnel: {
          ai_review_cache_hits: 2,
          ai_review_cache_misses: 3,
        },
      },
      selectedLearningPointIds: new Set(['lp-1']),
      onGenerateCardsFromLearningPoints,
    })

    expect(screen.getByRole('heading', { name: '学习点总览' })).toBeInTheDocument()
    expect(screen.getByText('AI 已精筛 1 个学习点')).toBeInTheDocument()
    expect(screen.getByText(/本次复用了 2 批 AI 精筛缓存，实时调用 3 批/)).toBeInTheDocument()
    expect(screen.getByText('缓存命中批')).toBeInTheDocument()
    expect(screen.getByText('实时调用批')).toBeInTheDocument()
    expect(screen.getByText('in the mood for')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '生成选中卡片' }))
    expect(onGenerateCardsFromLearningPoints).toHaveBeenCalledOnce()
  })

  it('renders review controls and forwards selection actions', () => {
    const project = createDemoProject(defaultRequest)
    const onSetCardsEnabled = vi.fn()
    const onInvertCardSelection = vi.fn()
    const onSelectSegment = vi.fn()

    renderWorkspace(project, { onInvertCardSelection, onSelectSegment, onSetCardsEnabled })

    fireEvent.click(screen.getByRole('button', { name: '全不选' }))
    fireEvent.click(screen.getByRole('button', { name: '反选' }))
    fireEvent.click(screen.getByRole('button', { name: /in the mood/ }))

    expect(screen.getByRole('heading', { name: '审核导出' })).toBeInTheDocument()
    expect(screen.getByText('本次将导出')).toBeInTheDocument()
    expect(onSetCardsEnabled).toHaveBeenCalledWith(false)
    expect(onInvertCardSelection).toHaveBeenCalledOnce()
    expect(onSelectSegment).toHaveBeenCalledWith('seg_demo_001')
  })

  it('shows learning point diagnostics with kind filters', async () => {
    const project: Project = {
      ...createDemoProject(defaultRequest),
      learning_point_inventory: [
        {
          id: 'lp-blocked',
          source_segment_id: 'src-1',
          source_time: '00:00:01 - 00:00:03',
          source_sentence: "I'm gonna run the register.",
          exact_span: 'register',
          answer_core: 'register',
          normalized_answer: 'register',
          candidate_kind: 'contextual_vocab',
          phrase_type: 'vocabulary_usage',
          value_score: 3,
          learning_action: '理解 register 在服务业场景里是收银机。',
          reason: '常见词在本句里有语境义。',
          status: 'hard_blocked',
          block_reason: 'answer_core 不在原句中，不能安全制卡。',
        },
      ],
      quality_funnel: {
        candidate_only_learning_point_count: 0,
        hidden_duplicate_learning_point_count: 0,
        hard_blocked_learning_point_count: 1,
      },
    }

    renderWorkspace(project)

    fireEvent.click(screen.getByRole('button', { name: /更多学习点\s*1/ }))

    expect(screen.getAllByText('更多学习点').length).toBeGreaterThan(0)
    expect(await screen.findByText('register')).toBeInTheDocument()
    expect(screen.getByText(/理解 register/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /语境生词\s*1/ })).toBeInTheDocument()
    expect(screen.getByText('原因：answer_core 不在原句中，不能安全制卡。')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '加入为草稿卡' })).not.toBeInTheDocument()
  })
})
