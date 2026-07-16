import '@testing-library/jest-dom/vitest'
import { useState } from 'react'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { LearningPointExtractionResult } from '../../domain/learningPoints'
import type { ActionGate, WorkflowActionId } from '../../app/workflowState'
import { learningPointGenerationBatchSize, selectedLearningPoints } from '../../domain/learningPoints'
import { LearningPointOverview } from './LearningPointOverview'

afterEach(() => cleanup())

const result: LearningPointExtractionResult = {
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
    {
      id: 'lp-2',
      source_segment_id: 'src-2',
      source_sentence: 'Take it easy and listen first.',
      source_time: '00:00:04.000 - 00:00:06.000',
      exact_span: 'take it easy',
      answer_core: 'take it easy',
      normalized_answer: 'take it easy',
      type: 'phrase',
      candidate_kind: 'expression',
      phrase_type: 'collocation',
      level: 'B1',
      learning_action: '训练安抚别人放轻松。',
      learning_action_key: 'expression:take it easy',
      value_score: 4.3,
      reason: '常见口语表达。',
      confidence: 'high',
      status: 'candidate_only',
      status_reason: '候选项，可手动加入。',
      source: 'model_review',
    },
  ],
  learning_point_summary: {
    total: 2,
    recommended: 1,
    candidate_only: 1,
    hidden_duplicate: 0,
    hard_blocked: 0,
    by_type: { phrase: 2 },
    by_level: { B1: 2 },
  },
}

function renderOverview(
  initialSelectedIds = ['lp-1', 'lp-2'],
  activeResult = result,
  primaryActionOverride?: ActionGate,
  initialGenerationConfirmOpen = false,
) {
  const onRunWorkflowAction = vi.fn()
  const onResolveBlockers = vi.fn()
  const onConfirmGenerateCards = vi.fn()

  function Harness() {
    const [selectedIds, setSelectedIds] = useState(() => new Set(initialSelectedIds))
    const [confirmOpen, setConfirmOpen] = useState(initialGenerationConfirmOpen)
    const [queueIds, setQueueIds] = useState<Set<string> | null>(() =>
      initialGenerationConfirmOpen ? new Set(initialSelectedIds) : null,
    )
    const primaryAction: ActionGate = primaryActionOverride ?? {
      action: 'generate_cards',
      state: selectedIds.size > 0 ? 'available' : 'blocked',
      primaryLabel: selectedIds.size > 0 ? '生成选中的 ' + String(selectedIds.size) + ' 张' : '至少选择 1 个学习点',
      blockers: [],
      warnings: [],
    }
    const queueSelectedIds = queueIds ?? selectedIds
    const queuePoints = selectedLearningPoints(activeResult.learning_points, queueSelectedIds)
    const batchSize = learningPointGenerationBatchSize(queuePoints.length)
    const queueSummary = {
      count: queuePoints.length,
      batchSize,
      batchCount: queuePoints.length > 0 ? Math.ceil(queuePoints.length / batchSize) : 0,
      batchMode: queuePoints.length > batchSize,
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
      estimatedModelBatches: queuePoints.length > 0 ? 1 : 0,
      estimatedMediaTasks: queuePoints.length * 6,
      estimatedTtsSemanticChecks: queuePoints.length * 2,
      highRiskShortExpressionCount: queuePoints.filter(
        (point) => point.answer_core.split(/\s+/).filter(Boolean).length <= 2,
      ).length,
      ttsSemanticPassed: 0,
      ttsSemanticFailed: 0,
      ttsSemanticManualReview: 0,
      securityWarnings: ['本地文件路径将在本轮确认后读取'],
      highRisk: queuePoints.length >= 50,
    }
    const runWorkflowAction = (action: WorkflowActionId) => {
      onRunWorkflowAction(action)
      if (action !== 'generate_cards') return
      const nextQueue = selectedLearningPoints(activeResult.learning_points, selectedIds)
      setQueueIds(new Set(nextQueue.map((point) => point.id)))
      setConfirmOpen(true)
    }
    return (
      <LearningPointOverview
        result={activeResult}
        selectedIds={selectedIds}
        workerBusy={false}
        generationConfirmOpen={confirmOpen}
        generationQueuePoints={queuePoints}
        generationQueueSummary={queueSummary}
        primaryAction={primaryAction}
        onCloseGenerationConfirm={() => setConfirmOpen(false)}
        onConfirmGenerateCards={onConfirmGenerateCards}
        onExtractWithoutCache={vi.fn()}
        onResolveBlockers={onResolveBlockers}
        onRunWorkflowAction={runWorkflowAction}
        onGenerateSinglePoint={(pointId) => {
          const single = new Set([pointId])
          setSelectedIds(single)
          setQueueIds(single)
          setConfirmOpen(true)
        }}
        onRemoveGenerationQueuePoint={(pointId) => {
          setQueueIds((current) => {
            const next = new Set(current ?? selectedIds)
            next.delete(pointId)
            return next
          })
        }}
        onSetSelectedIds={setSelectedIds}
      />
    )
  }

  render(<Harness />)
  return { onConfirmGenerateCards, onResolveBlockers, onRunWorkflowAction }
}

describe('LearningPointOverview', () => {
  it('keeps row clicks as view-only and only checkboxes change generation selection', () => {
    renderOverview()

    expect(screen.getByRole('button', { name: /生成选中的 2 张/ })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: /全部可制卡 2/ }))

    fireEvent.click(screen.getByText('Take it easy and listen first.').closest('article')!)
    expect(screen.getByRole('button', { name: /生成选中的 2 张/ })).toBeEnabled()

    fireEvent.click(screen.getAllByRole('checkbox')[1])
    expect(screen.getByRole('button', { name: /生成选中的 1 张/ })).toBeEnabled()
  })

  it('supports the controlled one-card path: unselect all, check one point, then generate one card', () => {
    const { onConfirmGenerateCards, onRunWorkflowAction } = renderOverview()

    fireEvent.click(screen.getByRole('button', { name: '清空选择' }))
    expect(screen.getByRole('button', { name: '至少选择 1 个学习点' })).toBeDisabled()

    fireEvent.click(screen.getAllByRole('checkbox')[0])
    const generateButton = screen.getByRole('button', { name: /生成选中的 1 张/ })
    expect(generateButton).toBeEnabled()

    fireEvent.click(generateButton)
    expect(onRunWorkflowAction).toHaveBeenCalledWith('generate_cards')
    expect(screen.getByRole('heading', { name: '准备生成卡片草稿 · 1 个学习点' })).toBeInTheDocument()
    expect(screen.getByText('确认区已打开')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /生成选中的 1 张/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '生成卡片草稿' })).toBeEnabled()
    expect(screen.queryByRole('button', { name: '只生成草稿' })).not.toBeInTheDocument()
    expect(document.querySelectorAll('.primary-button')).toHaveLength(1)
    expect(screen.queryByText('卡片数')).not.toBeInTheDocument()
    expect(screen.queryByText('TTS 核验项')).not.toBeInTheDocument()
    expect(screen.queryByText('自动核验，失败阻止导出')).not.toBeInTheDocument()
    expect(screen.queryByText('本地文件路径将在本轮确认后读取')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '查看生成详情' }))
    expect(screen.getByText('学习点')).toBeInTheDocument()
    expect(screen.getByText('本地文件路径将在本轮确认后读取')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '只生成草稿' })).not.toBeInTheDocument()
    expect(screen.queryByText(/只生成草稿/)).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '生成卡片草稿' }))
    expect(onConfirmGenerateCards).toHaveBeenCalledOnce()
  })

  it('opens a one-item confirmation queue from the safe single-card action', () => {
    const { onConfirmGenerateCards } = renderOverview()

    fireEvent.click(screen.getByRole('button', { name: /全部可制卡 2/ }))
    fireEvent.click(screen.getAllByRole('button', { name: '只生成这一条' })[1])

    expect(screen.getByText('确认区已打开')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /生成选中的 1 张/ })).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '准备生成卡片草稿 · 1 个学习点' })).toBeInTheDocument()
    expect(screen.getAllByText('take it easy').length).toBeGreaterThanOrEqual(1)

    fireEvent.click(screen.getByRole('button', { name: '生成卡片草稿' }))
    expect(onConfirmGenerateCards).toHaveBeenCalledOnce()
  })

  it('does not expose draft-only generation as a public secondary action', () => {
    const { onConfirmGenerateCards } = renderOverview()

    fireEvent.click(screen.getByRole('button', { name: /生成选中的 2 张/ }))
    expect(screen.queryByRole('button', { name: '只生成草稿' })).not.toBeInTheDocument()
    expect(document.querySelectorAll('.primary-button')).toHaveLength(1)

    fireEvent.click(screen.getByRole('button', { name: '查看生成详情' }))
    expect(screen.queryByRole('button', { name: '只生成草稿' })).not.toBeInTheDocument()
    expect(screen.queryByText(/只生成草稿/)).not.toBeInTheDocument()

    expect(onConfirmGenerateCards).not.toHaveBeenCalled()
  })

  it('separates global recommended selection from the current filtered selection', () => {
    renderOverview([])
    fireEvent.click(screen.getByRole('button', { name: /全部可制卡 2/ }))

    expect(screen.getByRole('button', { name: /全选可制卡项 2/ })).toBeEnabled()
    expect(screen.getByRole('button', { name: /只选推荐 1/ })).toBeEnabled()
    expect(screen.getByRole('button', { name: /勾选当前筛选 2/ })).toBeEnabled()

    fireEvent.click(screen.getByRole('button', { name: /只选推荐 1/ }))
    expect(screen.getByRole('button', { name: /生成选中的 1 张/ })).toBeEnabled()
    expect(
      screen.getAllByText(
        (_, element) =>
          element?.tagName === 'SMALL' && (element.textContent?.includes('当前推荐已勾选 1/1 个。') ?? false),
      ).length,
    ).toBeGreaterThanOrEqual(1)
    fireEvent.click(screen.getByRole('button', { name: /勾选当前筛选 2/ }))
    expect(screen.getByRole('button', { name: /生成选中的 2 张/ })).toBeEnabled()
    expect(screen.getByRole('button', { name: /取消当前筛选 2/ })).toBeEnabled()
  })

  it('selects only the current level filter when using the current filtered bulk action', () => {
    const leveledResult: LearningPointExtractionResult = {
      ...result,
      learning_points: [
        ...result.learning_points,
        {
          ...result.learning_points[1],
          id: 'lp-3',
          source_segment_id: 'src-3',
          source_sentence: 'Could you slow down a little?',
          exact_span: 'slow down',
          answer_core: 'slow down',
          normalized_answer: 'slow down',
          level: 'A2',
          status: 'candidate_only',
        },
      ],
      learning_point_summary: {
        ...result.learning_point_summary,
        total: 3,
        candidate_only: 2,
        by_level: { B1: 2, A2: 1 },
      },
    }

    renderOverview([], leveledResult)

    fireEvent.click(screen.getByRole('button', { name: /全部可制卡 3/ }))
    fireEvent.click(screen.getByRole('button', { name: '筛选' }))
    fireEvent.click(screen.getByRole('button', { name: 'A2' }))
    expect(screen.getByText(/当前筛选显示 1 个/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /勾选当前筛选 1/ }))
    expect(screen.getByRole('button', { name: /生成选中的 1 张/ })).toBeEnabled()
    expect(screen.getByRole('button', { name: /取消当前筛选 1/ })).toBeEnabled()
  })

  it('keeps source-review legal learning points visible as cardable items', () => {
    const allRiskyResult: LearningPointExtractionResult = {
      ...result,
      learning_points: [
        {
          ...result.learning_points[1],
          id: 'lp-all-risky',
          source_sentence: 'they they are from a a different time before the internet',
          exact_span: 'different time',
          answer_core: 'different time',
          normalized_answer: 'different time',
          status: 'candidate_only',
          source_sentence_quality_status: 'needs_review',
          source_sentence_quality_flags: ['too_long', 'rolling_caption_uncertain'],
        },
      ],
      learning_point_summary: {
        ...result.learning_point_summary,
        total: 1,
        recommended: 0,
        candidate_only: 1,
      },
      quality_funnel: {
        source_sentence_quality_counts: { too_long: 1, rolling_caption_uncertain: 1 },
      },
    }

    renderOverview([], allRiskyResult)

    expect(screen.getByText(/可制卡项 1 个/)).toBeInTheDocument()
    expect(screen.getAllByText(/需复查/).length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/字幕质量信号：长句 1 · 滚动字幕 1/)).toBeInTheDocument()
    expect(screen.getByText('different time')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /全选可制卡项 1/ }))
    expect(screen.getByRole('button', { name: /生成选中的 1 张/ })).toBeEnabled()
  })

  it('includes source-review legal learning points in full cardable selection', () => {
    const riskyResult: LearningPointExtractionResult = {
      ...result,
      learning_points: [
        result.learning_points[0],
        {
          ...result.learning_points[1],
          id: 'lp-risky',
          source_segment_id: 'src-risky',
          source_sentence: 'they they are from a a different time before the internet',
          exact_span: 'different time',
          answer_core: 'different time',
          normalized_answer: 'different time',
          status: 'candidate_only',
          source_sentence_quality_status: 'needs_review',
          source_sentence_quality_flags: ['repeated_adjacent_words'],
        },
      ],
      learning_point_summary: {
        ...result.learning_point_summary,
        total: 2,
        recommended: 1,
        candidate_only: 1,
      },
    }

    renderOverview([], riskyResult)

    expect(screen.getByText(/可制卡项 2 个/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /全部可制卡 2/ }))
    expect(screen.getByText('different time')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /全选可制卡项 2/ }))
    expect(screen.getByRole('button', { name: /生成选中的 2 张/ })).toBeEnabled()

    fireEvent.click(screen.getByRole('button', { name: '筛选' }))
    fireEvent.click(screen.getByRole('button', { name: '需复查' }))
    expect(screen.getByText('different time')).toBeInTheDocument()
    expect(screen.getAllByText('需复查').length).toBeGreaterThanOrEqual(2)
  })
  it('supports removing a learning point from the confirmation queue without changing row selection', () => {
    renderOverview()

    fireEvent.click(screen.getByRole('button', { name: /生成选中的 2 张/ }))
    expect(screen.getByRole('heading', { name: '准备生成卡片草稿 · 2 个学习点' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '查看生成详情' }))
    fireEvent.click(screen.getByRole('button', { name: /从生成队列移除 take it easy/i }))

    expect(screen.getByRole('heading', { name: '准备生成卡片草稿 · 1 个学习点' })).toBeInTheDocument()
    expect(screen.getByText('确认区已打开')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /生成选中的 2 张/ })).not.toBeInTheDocument()
  })

  it('shows batch generation language for queues larger than the adaptive stable batch size', () => {
    const manyPoints = Array.from({ length: 49 }, (_, index) => ({
      ...result.learning_points[index % result.learning_points.length],
      id: `lp-many-${index + 1}`,
      source_segment_id: `src-many-${index + 1}`,
      exact_span: `phrase ${index + 1}`,
      answer_core: `phrase ${index + 1}`,
      normalized_answer: `phrase ${index + 1}`,
      status: 'candidate_only' as const,
    }))
    const manyResult: LearningPointExtractionResult = {
      ...result,
      learning_points: manyPoints,
      learning_point_summary: {
        ...result.learning_point_summary,
        total: manyPoints.length,
        recommended: 0,
        candidate_only: manyPoints.length,
      },
    }

    renderOverview(
      manyPoints.map((point) => point.id),
      manyResult,
    )

    fireEvent.click(screen.getByRole('button', { name: /生成选中的 49 张/ }))

    expect(screen.getByRole('heading', { name: /准备生成卡片草稿 · 49 个学习点/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '生成卡片草稿' })).toBeEnabled()
    expect(screen.getByText(/内部将分 5 批稳定处理，每批最多 12 张/)).toBeInTheDocument()
  })
  it('defaults to recommended items, preserves hidden selection, and searches across cardable points', () => {
    renderOverview()

    expect(screen.getByText("I'm not really in the mood for this right now.")).toBeInTheDocument()
    expect(screen.queryByText('Take it easy and listen first.')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /生成选中的 2 张/ })).toBeEnabled()

    fireEvent.click(screen.getByRole('button', { name: /全部可制卡 2/ }))
    fireEvent.change(screen.getByRole('textbox', { name: '搜索学习点' }), { target: { value: '安抚' } })

    expect(screen.getByText('Take it easy and listen first.')).toBeInTheDocument()
    expect(screen.queryByText("I'm not really in the mood for this right now.")).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /生成选中的 2 张/ })).toBeEnabled()
  })

  it('falls back to all cardable items when there are no recommended points', () => {
    const fallbackResult: LearningPointExtractionResult = {
      ...result,
      learning_points: result.learning_points.map((point) => ({ ...point, status: 'candidate_only' as const })),
      learning_point_summary: {
        ...result.learning_point_summary,
        recommended: 0,
        candidate_only: 2,
      },
    }

    renderOverview([], fallbackResult)

    expect(screen.getByRole('status')).toHaveTextContent('本次没有高置信推荐项，已自动显示全部可制卡项')
    expect(screen.getByText('Take it easy and listen first.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^推荐 0$/ })).toBeDisabled()
  })

  it('closes confirmation with Escape and restores focus to the generating control', () => {
    renderOverview(['lp-1'])
    const generateButton = screen.getByRole('button', { name: /生成选中的 1 张/ })
    generateButton.focus()
    fireEvent.click(generateButton)

    expect(screen.getByRole('dialog', { name: '生成确认' })).toHaveFocus()
    fireEvent.keyDown(document, { key: 'Escape' })

    expect(screen.queryByRole('dialog', { name: '生成确认' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /生成选中的 1 张/ })).toHaveFocus()
  })
  it('portals one modal dialog above the workbench and keeps keyboard focus inside it', () => {
    renderOverview(['lp-1'], result, undefined, true)

    const dialog = screen.getByRole('dialog', { name: '生成确认' })
    const modalLayer = dialog.closest('[data-generation-confirm-modal="true"]')
    expect(document.querySelectorAll('[role="dialog"]')).toHaveLength(1)
    expect(modalLayer).toHaveClass('generation-confirm-modal-layer')
    expect(dialog.closest('.learning-point-overview')).toBeNull()
    expect(dialog).toHaveFocus()

    fireEvent.keyDown(document, { key: 'Tab' })
    expect(screen.getByRole('button', { name: '生成卡片草稿' })).toHaveFocus()

    const lastModalButton = screen.getByRole('button', { name: '查看生成详情' })
    lastModalButton.focus()
    fireEvent.keyDown(document, { key: 'Tab' })
    expect(screen.getByRole('button', { name: '生成卡片草稿' })).toHaveFocus()

    screen.getByRole('button', { name: '重新分析素材' }).focus()
    expect(dialog).toHaveFocus()
  })

  it('resolves blockers from the selection action without starting generation', () => {
    const blockedAction: ActionGate = {
      action: 'generate_cards',
      state: 'blocked',
      blockers: [
        {
          id: 'tts',
          severity: 'blocker',
          action: 'generate_cards',
          title: 'TTS 尚未通过测试',
          detail: '已授权，但必须先完成一次真实语音测试。',
          resolutionLabel: '测试语音',
        },
      ],
      warnings: [],
      primaryLabel: '还需完成 1 项准备',
    }

    const { onConfirmGenerateCards, onResolveBlockers, onRunWorkflowAction } = renderOverview(
      ['lp-1'],
      result,
      blockedAction,
    )
    fireEvent.click(screen.getByRole('button', { name: '还需完成 1 项准备' }))

    expect(onResolveBlockers).toHaveBeenCalledWith(blockedAction.blockers)
    expect(onRunWorkflowAction).not.toHaveBeenCalled()
    expect(onConfirmGenerateCards).not.toHaveBeenCalled()
    expect(screen.queryByRole('dialog', { name: '生成确认' })).not.toBeInTheDocument()
  })

  it('turns a blocked confirmation action into the same recovery action', () => {
    const blockedAction: ActionGate = {
      action: 'generate_cards',
      state: 'blocked',
      blockers: [
        {
          id: 'tts',
          severity: 'blocker',
          action: 'generate_cards',
          title: 'TTS 尚未通过测试',
          detail: '已授权，但必须先完成一次真实语音测试。',
          resolutionLabel: '测试语音',
        },
      ],
      warnings: [],
      primaryLabel: '还需完成 1 项准备',
    }

    const { onConfirmGenerateCards, onResolveBlockers, onRunWorkflowAction } = renderOverview(
      ['lp-1'],
      result,
      blockedAction,
      true,
    )
    const recoveryButton = screen.getByRole('button', { name: '还需完成 1 项准备' })
    expect(recoveryButton).toBeEnabled()
    fireEvent.click(recoveryButton)

    expect(screen.getByText('TTS 尚未通过测试')).toBeInTheDocument()
    expect(screen.getByText('已授权，但必须先完成一次真实语音测试。')).toBeInTheDocument()
    expect(onResolveBlockers).toHaveBeenCalledWith(blockedAction.blockers)
    expect(onRunWorkflowAction).not.toHaveBeenCalled()
    expect(onConfirmGenerateCards).not.toHaveBeenCalled()
  })
  it.each([50, 100])('shows stable batching and high-volume risk guidance for %i cards', (count) => {
    const manyPoints = Array.from({ length: count }, (_, index) => ({
      ...result.learning_points[index % result.learning_points.length],
      id: `lp-boundary-${count}-${index + 1}`,
      source_segment_id: `src-boundary-${count}-${index + 1}`,
      exact_span: `boundary phrase ${index + 1}`,
      answer_core: `boundary phrase ${index + 1}`,
      normalized_answer: `boundary phrase ${index + 1}`,
      status: 'candidate_only' as const,
    }))
    const manyResult: LearningPointExtractionResult = {
      ...result,
      learning_points: manyPoints,
      learning_point_summary: {
        ...result.learning_point_summary,
        total: count,
        recommended: 0,
        candidate_only: count,
      },
    }

    renderOverview(
      manyPoints.map((point) => point.id),
      manyResult,
    )
    fireEvent.click(screen.getByRole('button', { name: new RegExp(`生成选中的 ${count} 张`) }))

    expect(screen.getByRole('heading', { name: new RegExp(`准备生成卡片草稿 · ${count} 个学习点`) })).toBeInTheDocument()
    expect(
      screen.getByText(new RegExp(`内部将分 ${Math.ceil(count / 12)} 批稳定处理，每批最多 12 张`)),
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '查看生成详情' }))
    expect(
      screen.getByText('本轮达到 50 张以上，模型、TTS 和媒体任务会明显变慢；建议先用少量样本确认质量。'),
    ).toBeInTheDocument()
    cleanup()
  })
})
