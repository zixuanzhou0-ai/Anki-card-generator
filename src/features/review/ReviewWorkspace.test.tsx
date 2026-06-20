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
    generationConfirmOpen: false,
    generationQueuePoints: [],
    generationQueueSummary: {
      count: 0,
      batchSize: 12,
      batchCount: 0,
      batchMode: false,
      completedBatches: 0,
      completedCount: 0,
      generatedCount: 0,
      missingCount: 0,
      exportableCount: 0,
      modeLabel: '完整复读',
      sourceLabel: '本地视频 + SRT',
      includesVideo: true,
      includesOriginalAudio: true,
      includesSentenceTts: true,
      includesPhraseTts: true,
      estimatedModelBatches: 0,
      estimatedMediaTasks: 0,
      estimatedTtsSemanticChecks: 0,
      highRiskShortExpressionCount: 0,
      ttsSemanticPassed: 0,
      ttsSemanticFailed: 0,
      ttsSemanticManualReview: 0,
      securityWarnings: [],
      highRisk: false,
    },
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
    onCloseGenerationConfirm: vi.fn(),
    onConfirmGenerateCardsFromLearningPoints: vi.fn(),
    onGenerateCardsFromLearningPoints: vi.fn(),
    onGenerateSingleLearningPoint: vi.fn(),
    onInvertCardSelection: vi.fn(),
    onRemoveGenerationQueueLearningPoint: vi.fn(),
    onSelectSegment: vi.fn(),
    onSetCardsEnabled: vi.fn(),
    onSetSelectedLearningPointIds: vi.fn(),
    onUpdateCard: vi.fn(),
    onExport: vi.fn(),
    onExtractLearningPointsWithoutCache: vi.fn(),
    onRetryMissingLearningPoints: vi.fn(),
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

  it('does not expose APKG actions when stale export state has no current project', () => {
    renderWorkspace(null, {
      lastExport: {
        apkg_path: 'E:\\ANKI\\out\\stale.apkg',
        media_dir: 'E:\\ANKI\\out\\media',
        cards: 2,
        segments: 2,
      },
    })

    expect(screen.queryByText('导出完成')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /用 Anki 打开 APKG/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /导入并核验本次牌组/ })).not.toBeInTheDocument()
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
      status: '正在解析字幕、筛选片段并生成卡片。',
    })

    expect(screen.getByRole('heading', { name: '生成中' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '正在生成 APKG' })).toBeInTheDocument()
    expect(screen.getByText('37%')).toBeInTheDocument()
    expect(screen.getByText('生成卡片正文')).toBeInTheDocument()
    expect(screen.queryByText('正在生成卡片正文：第 3/8 批。')).not.toBeInTheDocument()
    expect(screen.getByText('设置已锁定')).toBeInTheDocument()
  })

  it('shows a preparation workbench before the native APKG folder dialog opens', () => {
    renderWorkspace(null, {
      workerBusy: false,
      workerProgress: {
        command: 'generate_cards_from_learning_points',
        stage: 'select_output_dir',
        percent: 0,
        message: '正在打开 APKG 保存目录选择器。',
      },
      status: '正在打开 APKG 保存目录选择器。选择后会自动生成卡片正文、TTS、视频片段并打包。',
    })

    expect(screen.getByRole('heading', { name: '生成工作台' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '正在准备 APKG' })).toBeInTheDocument()
    expect(screen.getByText('选择保存目录')).toBeInTheDocument()
    expect(screen.getByText(/正在打开 APKG 保存目录选择器/)).toBeInTheDocument()
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
    expect(screen.getByRole('button', { name: '高级诊断' })).toBeInTheDocument()
    expect(screen.queryByText(/本次复用了 2 批 AI 精筛缓存，实时调用 3 批/)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '高级诊断' }))
    expect(screen.getByText(/本次复用了 2 批 AI 精筛缓存，实时调用 3 批/)).toBeInTheDocument()
    expect(screen.getByText('缓存 2')).toBeInTheDocument()
    expect(screen.getByText('实时 3')).toBeInTheDocument()
    expect(screen.getByText('in the mood for')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /生成 APKG · 1 张/ }))
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
    expect(screen.getByText('已选卡片')).toBeInTheDocument()
    expect(screen.getByText('可导出')).toBeInTheDocument()
    expect(screen.getByText('生成总数')).toBeInTheDocument()
    expect(onSetCardsEnabled).toHaveBeenCalledWith(false)
    expect(onInvertCardSelection).toHaveBeenCalledOnce()
    expect(onSelectSegment).toHaveBeenCalledWith('seg_demo_001')
  })

  it('explains partial generation instead of treating the queue size as generated cards', () => {
    const project: Project = {
      ...createDemoProject(defaultRequest),
      card_generation_diagnostics: {
        selected_learning_point_count: 107,
        processed_learning_point_count: 107,
        successful_learning_point_count: 74,
        generated_card_count: 74,
        exportable_card_count: 74,
        missing_learning_point_count: 33,
        items: [
          {
            learning_point_id: 'lp-missing-1',
            answer_core: 'blend together',
            status: 'hard_failed',
            reason: 'AI 未覆盖该学习点，且保底生成未完成。',
          },
          {
            learning_point_id: 'lp-filtered-1',
            answer_core: 'completely lost',
            status: 'filtered',
            reason: '质量过滤后没有可导出的卡。',
          },
          {
            learning_point_id: 'lp-skipped-1',
            answer_core: 'never fear',
            status: 'skipped',
            reason: '该学习点不可制卡，已跳过。',
          },
        ],
      },
    }
    const onExport = vi.fn()
    const onRetryMissingLearningPoints = vi.fn()

    renderWorkspace(project, {
      onExport,
      onRetryMissingLearningPoints,
      qualityCounts: { total: 107, recommended: 74, review: 0, rejected: 33 },
    })

    expect(screen.getByText('处理 107 个学习点，生成 74 张；33 个未生成')).toBeInTheDocument()
    expect(screen.getByText(/硬失败 1/)).toBeInTheDocument()
    expect(screen.getByText(/质量过滤 1/)).toBeInTheDocument()
    expect(screen.getByText(/不可制卡跳过 1/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '只重试未生成 33 个' }))
    fireEvent.click(screen.getByRole('button', { name: '导出已生成 74 张' }))

    expect(onRetryMissingLearningPoints).toHaveBeenCalledOnce()
    expect(onExport).toHaveBeenCalledOnce()
  })

  it('shows export quality gate details in the review area', () => {
    const project = createDemoProject(defaultRequest)
    renderWorkspace(project, {
      lastWorkerError: {
        job_id: 'job-export',
        command: 'export',
        ok: false,
        error: '导出前质量审计未通过：草稿/内部文本 1。',
        error_code: 'EXPORT_QUALITY_GATE_FAILED',
        stage: 'quality_audit',
        details: {
          blocked_cards: [
            {
              card_id: 'card-draft',
              segment_id: 'seg_demo_001',
              source_time: '00:00:01.000 - 00:00:03.000',
              title: '本地文档草稿',
              matched_text: '本地文档草稿，需要人工确认。',
              suggested_action: '移除这张需修复卡，或重新生成/手动修正草稿字段后再导出。',
            },
          ],
        },
      },
    })

    expect(screen.getByText('导出没有生成 APKG')).toBeInTheDocument()
    expect(screen.getByText(/EXPORT_QUALITY_GATE_FAILED/)).toBeInTheDocument()
    expect(screen.getByText('本地文档草稿')).toBeInTheDocument()
    expect(screen.getByText(/需要人工确认/)).toBeInTheDocument()
  })

  it('shows release APKG target guard failures without APKG success actions', () => {
    const project = createDemoProject(defaultRequest)
    renderWorkspace(project, {
      lastWorkerError: {
        job_id: 'release-apkg-target',
        command: 'export',
        ok: false,
        error:
          '已取消导出：当前是 release case 验收（local_srt_full1_cold），保存目录必须是 ...\\video_release_hardening_YYYYMMDD_HHMMSS\\cases\\local_srt_full1_cold\\apkg；不能选择 Documents、素材目录或 case 下的其他目录。',
        error_code: 'RELEASE_APKG_TARGET_INVALID',
        stage: 'select_output_dir',
        details: {
          release_case_id: 'local_srt_full1_cold',
          selected_output_dir: 'D:\\Administrator\\Documents',
          expected_directory_pattern:
            '...\\video_release_hardening_YYYYMMDD_HHMMSS\\cases\\local_srt_full1_cold\\apkg',
        },
      },
    })

    expect(screen.getByText('导出没有生成 APKG')).toBeInTheDocument()
    expect(screen.getByText(/RELEASE_APKG_TARGET_INVALID/)).toBeInTheDocument()
    expect(screen.getByText(/cases\\local_srt_full1_cold\\apkg/)).toBeInTheDocument()
    expect(screen.queryByText('导出完成')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /用 Anki 打开 APKG/ })).not.toBeInTheDocument()
  })

  it('shows release APKG target guard failures before a project exists', () => {
    renderWorkspace(null, {
      lastWorkerError: {
        job_id: 'release-apkg-target-before-project',
        command: 'export',
        ok: false,
        error:
          '已暂停生成：当前是 release case 验收（local_srt_full1_cold），保存目录必须是 ...\\video_release_hardening_YYYYMMDD_HHMMSS\\cases\\local_srt_full1_cold\\apkg。',
        error_code: 'RELEASE_APKG_TARGET_INVALID',
        stage: 'select_output_dir',
        details: {
          release_case_id: 'local_srt_full1_cold',
          selected_output_dir: 'D:\\Administrator\\Documents',
          expected_directory_pattern:
            '...\\video_release_hardening_YYYYMMDD_HHMMSS\\cases\\local_srt_full1_cold\\apkg',
        },
      },
    })

    expect(screen.getByRole('heading', { name: '生成工作台' })).toBeInTheDocument()
    expect(screen.getByText('导出没有生成 APKG')).toBeInTheDocument()
    expect(screen.getByText(/RELEASE_APKG_TARGET_INVALID/)).toBeInTheDocument()
    expect(screen.getByText(/cases\\local_srt_full1_cold\\apkg/)).toBeInTheDocument()
    expect(screen.queryByText('导出完成')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /用 Anki 打开 APKG/ })).not.toBeInTheDocument()
  })

  it('does not surface stale ordinary export failures without a current project', () => {
    renderWorkspace(null, {
      lastWorkerError: {
        job_id: 'stale-export-failure',
        command: 'export',
        ok: false,
        error: '旧项目导出失败。',
        error_code: 'MISSING_TTS_MEDIA',
        stage: 'tts',
        details: { tts_failure_count: 1 },
      },
    })

    expect(screen.getByRole('heading', { name: '生成工作台' })).toBeInTheDocument()
    expect(screen.queryByText('TTS 生成失败，未生成 APKG')).not.toBeInTheDocument()
    expect(screen.queryByText(/MISSING_TTS_MEDIA/)).not.toBeInTheDocument()
  })

  it('shows missing TTS media details and retries export', () => {
    const project = createDemoProject(defaultRequest)
    const onExport = vi.fn()
    renderWorkspace(project, {
      onExport,
      lastWorkerError: {
        job_id: 'job-export-tts',
        command: 'export',
        ok: false,
        error: 'TTS 生成失败：2 条 TTS 未完成，因此没有生成 APKG。',
        error_code: 'MISSING_TTS_MEDIA',
        stage: 'tts',
        details: {
          tts_failure_count: 2,
          sentence_tts_requested: 142,
          sentence_tts_generated: 140,
          phrase_tts_requested: 142,
          phrase_tts_generated: 142,
          tts_failure_items: [
            {
              segment_id: 'seg_lp_0047',
              source_time: '00:06:55.290 - 00:07:03.300',
              role: 'sentence_tts',
              expected_text: 'These are the things that these guys are missing out on.',
              answer: 'missing out on',
              error:
                'Gemini Vertex TTS 请求失败：API HTTP 400 {"error":{"code":400,"message":"Request contains an invalid argument.","status":"INVALID_ARGUMENT"}}',
              http_error:
                'Gemini Vertex TTS 请求失败：API HTTP 400 {"error":{"code":400,"message":"Request contains an invalid argument.","status":"INVALID_ARGUMENT"}}',
            },
          ],
        },
      },
    })

    expect(screen.getByText('TTS 生成失败，未生成 APKG')).toBeInTheDocument()
    expect(screen.getByText(/2 条 TTS 生成失败/)).toBeInTheDocument()
    expect(screen.getByText(/整句 TTS 140\/142/)).toBeInTheDocument()
    expect(screen.getByText('missing out on')).toBeInTheDocument()
    expect(screen.getByText(/TTS 服务拒绝了这段文本/)).toBeInTheDocument()
    expect(screen.queryByText(/Request contains an invalid argument/)).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '重试失败 TTS 并导出' }))

    expect(onExport).toHaveBeenCalledOnce()
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
