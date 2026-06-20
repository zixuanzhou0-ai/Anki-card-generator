import '@testing-library/jest-dom/vitest'
import { useState } from 'react'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { LearningPointExtractionResult } from '../../domain/learningPoints'
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

function renderOverview(initialSelectedIds = ['lp-1', 'lp-2'], activeResult = result) {
  const onGenerateCards = vi.fn()
  const onConfirmGenerateCards = vi.fn()

  function Harness() {
    const [selectedIds, setSelectedIds] = useState(() => new Set(initialSelectedIds))
    const [confirmOpen, setConfirmOpen] = useState(false)
    const [queueIds, setQueueIds] = useState<Set<string> | null>(null)
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
      highRiskShortExpressionCount: queuePoints.filter((point) => point.answer_core.split(/\s+/).filter(Boolean).length <= 2).length,
      ttsSemanticPassed: 0,
      ttsSemanticFailed: 0,
      ttsSemanticManualReview: 0,
      securityWarnings: ['本地文件路径将在本轮确认后读取'],
      highRisk: queuePoints.length >= 50,
    }
    const openConfirm = () => {
      const nextQueue = selectedLearningPoints(activeResult.learning_points, selectedIds)
      setQueueIds(new Set(nextQueue.map((point) => point.id)))
      setConfirmOpen(true)
      onGenerateCards()
    }
    return (
      <LearningPointOverview
        result={activeResult}
        selectedIds={selectedIds}
        workerBusy={false}
        generationConfirmOpen={confirmOpen}
        generationQueuePoints={queuePoints}
        generationQueueSummary={queueSummary}
        onCloseGenerationConfirm={() => setConfirmOpen(false)}
        onConfirmGenerateCards={onConfirmGenerateCards}
        onExtractWithoutCache={vi.fn()}
        onGenerateCards={openConfirm}
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
  return { onConfirmGenerateCards, onGenerateCards }
}

describe('LearningPointOverview', () => {
  it('keeps row clicks as view-only and only checkboxes change generation selection', () => {
    renderOverview()

    expect(screen.getByRole('button', { name: /生成 APKG · 2 张/ })).toBeEnabled()

    fireEvent.click(screen.getByText('Take it easy and listen first.').closest('article')!)
    expect(screen.getByRole('button', { name: /生成 APKG · 2 张/ })).toBeEnabled()

    fireEvent.click(screen.getAllByRole('checkbox')[1])
    expect(screen.getByRole('button', { name: /生成 APKG · 1 张/ })).toBeEnabled()
  })

  it('supports the controlled one-card path: unselect all, check one point, then generate one card', () => {
    const { onConfirmGenerateCards, onGenerateCards } = renderOverview()

    fireEvent.click(screen.getByRole('button', { name: '清空勾选' }))
    expect(screen.getByRole('button', { name: /生成 APKG · 0 张/ })).toBeDisabled()

    fireEvent.click(screen.getAllByRole('checkbox')[0])
    const generateButton = screen.getByRole('button', { name: /生成 APKG · 1 张/ })
    expect(generateButton).toBeEnabled()

    fireEvent.click(generateButton)
    expect(onGenerateCards).toHaveBeenCalledOnce()
    expect(screen.getByRole('heading', { name: '准备生成 APKG · 1 张' })).toBeInTheDocument()
    expect(screen.getByText('确认区已打开')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /生成 APKG · 1 张/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '生成 APKG' })).toBeEnabled()
    expect(screen.queryByRole('button', { name: '只生成草稿' })).not.toBeInTheDocument()
    expect(document.querySelectorAll('.primary-button')).toHaveLength(1)
    expect(screen.queryByText('卡片数')).not.toBeInTheDocument()
    expect(screen.queryByText('TTS 核验项')).not.toBeInTheDocument()
    expect(screen.queryByText('自动核验，失败阻止导出')).not.toBeInTheDocument()
    expect(screen.queryByText('本地文件路径将在本轮确认后读取')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '查看生成详情' }))
    expect(screen.getByText('卡片数')).toBeInTheDocument()
    expect(screen.getByText('本地文件路径将在本轮确认后读取')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '只生成草稿' })).not.toBeInTheDocument()
    expect(screen.queryByText(/只生成草稿/)).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '生成 APKG' }))
    expect(onConfirmGenerateCards).toHaveBeenCalledOnce()
  })

  it('opens a one-item confirmation queue from the safe single-card action', () => {
    const { onConfirmGenerateCards } = renderOverview()

    fireEvent.click(screen.getAllByRole('button', { name: '只生成这一条' })[1])

    expect(screen.getByText('确认区已打开')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /生成 APKG · 1 张/ })).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '准备生成 APKG · 1 张' })).toBeInTheDocument()
    expect(screen.getAllByText('take it easy').length).toBeGreaterThanOrEqual(1)

    fireEvent.click(screen.getByRole('button', { name: '生成 APKG' }))
    expect(onConfirmGenerateCards).toHaveBeenCalledOnce()
  })

  it('does not expose draft-only generation as a public secondary action', () => {
    const { onConfirmGenerateCards } = renderOverview()

    fireEvent.click(screen.getByRole('button', { name: /生成 APKG · 2 张/ }))
    expect(screen.queryByRole('button', { name: '只生成草稿' })).not.toBeInTheDocument()
    expect(document.querySelectorAll('.primary-button')).toHaveLength(1)

    fireEvent.click(screen.getByRole('button', { name: '查看生成详情' }))
    expect(screen.queryByRole('button', { name: '只生成草稿' })).not.toBeInTheDocument()
    expect(screen.queryByText(/只生成草稿/)).not.toBeInTheDocument()

    expect(onConfirmGenerateCards).not.toHaveBeenCalled()
  })

  it('separates global recommended selection from the current filtered selection', () => {
    renderOverview([])

    expect(screen.getByRole('button', { name: /全选全部可批量制卡 2/ })).toBeEnabled()
    expect(screen.getByRole('button', { name: /勾选全部推荐 1/ })).toBeEnabled()
    expect(screen.getByRole('button', { name: /勾选当前筛选 2/ })).toBeEnabled()

    fireEvent.click(screen.getByRole('button', { name: /勾选全部推荐 1/ }))
    expect(screen.getByRole('button', { name: /生成 APKG · 1 张/ })).toBeEnabled()
    expect(screen.getByText(/当前推荐已勾选 1\/1 个/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /勾选当前筛选 2/ }))
    expect(screen.getByRole('button', { name: /生成 APKG · 2 张/ })).toBeEnabled()
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

    fireEvent.click(screen.getByRole('button', { name: 'A2' }))
    expect(screen.getByText(/当前筛选显示 1 个/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /勾选当前筛选 1/ }))
    expect(screen.getByRole('button', { name: /生成 APKG · 1 张/ })).toBeEnabled()
    expect(screen.getByRole('button', { name: /取消当前筛选 1/ })).toBeEnabled()
  })

  it('keeps source-review learning points out of bulk selection while still allowing explicit manual selection', () => {
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

    expect(screen.getByText(/另有 1 个学习点需复查，不会被批量勾选/)).toBeInTheDocument()
    expect(screen.getByText('需复查')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /全选全部可批量制卡 1/ }))
    expect(screen.getByRole('button', { name: /生成 APKG · 1 张/ })).toBeEnabled()

    fireEvent.click(screen.getAllByRole('checkbox')[1])
    expect(screen.getByRole('button', { name: /生成 APKG · 2 张/ })).toBeEnabled()
  })

  it('supports removing a learning point from the confirmation queue without changing row selection', () => {
    renderOverview()

    fireEvent.click(screen.getByRole('button', { name: /生成 APKG · 2 张/ }))
    expect(screen.getByRole('heading', { name: '准备生成 APKG · 2 张' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '查看生成详情' }))
    fireEvent.click(screen.getByRole('button', { name: /从生成队列移除 take it easy/i }))

    expect(screen.getByRole('heading', { name: '准备生成 APKG · 1 张' })).toBeInTheDocument()
    expect(screen.getByText('确认区已打开')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /生成 APKG · 2 张/ })).not.toBeInTheDocument()
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

    renderOverview(manyPoints.map((point) => point.id), manyResult)

    fireEvent.click(screen.getByRole('button', { name: /生成 APKG · 49 张/ }))

    expect(screen.getByRole('heading', { name: /准备生成 APKG · 49 张/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '生成 APKG' })).toBeEnabled()
    expect(screen.getByText(/每批最多 36 张/)).toBeInTheDocument()
  })
})
