import { useEffect, useMemo, useRef, useState } from 'react'
import { Filter, Layers3, ListChecks, Search, Sparkles, Trash2 } from 'lucide-react'

import type { WorkflowReadinessSnapshot } from '../../app/readiness'

import type {
  GenerationQueueSummary,
  LearningPointExtractionResult,
  LearningPointItem,
  LearningPointStatus,
  LearningPointType,
} from '../../domain/learningPoints'
import {
  cardableLearningPoint,
  learningPointNeedsSourceReview,
  learningPointStatusLabels,
  learningPointTypeLabels,
  selectedLearningPoints,
} from '../../domain/learningPoints'

type LearningPointOverviewProps = {
  result: LearningPointExtractionResult
  selectedIds: Set<string>
  workerBusy: boolean
  generationConfirmOpen: boolean
  generationQueuePoints: LearningPointItem[]
  generationQueueSummary: GenerationQueueSummary
  workflowReadiness?: WorkflowReadinessSnapshot
  onCloseGenerationConfirm: () => void
  onConfirmGenerateCards: () => void
  onExtractWithoutCache: () => void
  onGenerateCards: () => void
  onGenerateSinglePoint: (pointId: string) => void
  onRemoveGenerationQueuePoint: (pointId: string) => void
  onSetSelectedIds: (ids: Set<string>) => void
}

type TypeFilter = 'all' | LearningPointType
type LevelFilter = 'all' | 'A1' | 'A2' | 'B1' | 'B2' | 'C1' | 'C2' | 'B1+' | 'B2+'
type StatusFilter = 'cardable' | 'needs_review' | 'all' | LearningPointStatus

const typeFilters: Array<{ id: TypeFilter; label: string }> = [
  { id: 'all', label: '全部类型' },
  { id: 'phrase', label: '词伙' },
  { id: 'spoken', label: '口语' },
  { id: 'vocab_usage', label: '单词用法' },
  { id: 'grammar', label: '语法' },
  { id: 'listening', label: '听力' },
  { id: 'pragmatic', label: '语气' },
]

const levelFilters: LevelFilter[] = ['all', 'A1', 'A2', 'B1', 'B2', 'C1', 'C2', 'B1+', 'B2+']
const statusFilters: Array<{ id: StatusFilter; label: string }> = [
  { id: 'cardable', label: '可制卡' },
  { id: 'needs_review', label: '需复查' },
  { id: 'all', label: '全部状态' },
  { id: 'recommended', label: '推荐' },
  { id: 'candidate_only', label: '候选' },
  { id: 'hidden_duplicate', label: '重复折叠' },
  { id: 'hard_blocked', label: '不可制卡' },
]

const levelOrder = ['A1', 'A2', 'B1', 'B2', 'C1', 'C2']

function levelMatches(level: string | undefined, filter: LevelFilter) {
  if (filter === 'all') return true
  const normalized = level && levelOrder.includes(level) ? level : ''
  if (!normalized) return false
  if (filter === 'B1+') return levelOrder.indexOf(normalized) >= levelOrder.indexOf('B1')
  if (filter === 'B2+') return levelOrder.indexOf(normalized) >= levelOrder.indexOf('B2')
  return normalized === filter
}

function pointLabel(point: LearningPointItem) {
  return point.answer_core || point.exact_span || '未命名学习点'
}

export function LearningPointOverview({
  result,
  selectedIds,
  workerBusy,
  generationConfirmOpen,
  generationQueuePoints,
  generationQueueSummary,
  workflowReadiness,
  onCloseGenerationConfirm,
  onConfirmGenerateCards,
  onExtractWithoutCache,
  onGenerateCards,
  onGenerateSinglePoint,
  onRemoveGenerationQueuePoint,
  onSetSelectedIds,
}: LearningPointOverviewProps) {
  const [typeFilter, setTypeFilter] = useState<TypeFilter>('all')
  const [levelFilter, setLevelFilter] = useState<LevelFilter>('all')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>(() =>
    result.learning_point_summary.recommended > 0 ? 'recommended' : 'cardable',
  )
  const [searchQuery, setSearchQuery] = useState('')
  const [showFilters, setShowFilters] = useState(false)
  const [showGenerationDetails, setShowGenerationDetails] = useState(false)
  const [showLearningDiagnostics, setShowLearningDiagnostics] = useState(false)
  const confirmPanelRef = useRef<HTMLElement>(null)
  const returnFocusIdRef = useRef<string | null>(null)
  const closeConfirmationRef = useRef(onCloseGenerationConfirm)
  const points = useMemo(() => result.learning_points ?? [], [result.learning_points])
  const hasRecommendedPoints = result.learning_point_summary.recommended > 0

  useEffect(() => {
    setStatusFilter(hasRecommendedPoints ? 'recommended' : 'cardable')
    setSearchQuery('')
    setShowFilters(false)
  }, [hasRecommendedPoints, result.id])

  useEffect(() => {
    closeConfirmationRef.current = onCloseGenerationConfirm
  }, [onCloseGenerationConfirm])

  useEffect(() => {
    if (!generationConfirmOpen) {
      const returnFocusId = returnFocusIdRef.current
      if (returnFocusId) {
        const target = Array.from(document.querySelectorAll<HTMLElement>('[data-focus-return]')).find(
          (element) => element.dataset.focusReturn === returnFocusId,
        )
        target?.focus()
        returnFocusIdRef.current = null
      }
      return
    }
    const panel = confirmPanelRef.current
    panel?.focus()

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        closeConfirmationRef.current()
        return
      }
      if (event.key !== 'Tab' || !panel) return
      const focusable = Array.from(
        panel.querySelectorAll<HTMLElement>(
          'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      )
      if (!focusable.length) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [generationConfirmOpen])
  const rememberReturnFocus = (element: HTMLElement) => {
    returnFocusIdRef.current = element.dataset.focusReturn ?? null
  }

  const modelLabel = [result.ai_model_provider, result.ai_model_name].filter(Boolean).join(' · ')
  const selected = selectedLearningPoints(points, selectedIds)
  const selectedRecommendedCount = selected.filter((point) => point.status === 'recommended').length
  const sourceSentenceCount = Number(result.quality_funnel?.source_sentence_count ?? result.source_sentences?.length ?? 0)
  const reviewedSourceCount = Number(result.ai_reviewed_source_count ?? result.quality_funnel?.ai_reviewed_source_count ?? 0)
  const cacheHits = Number(result.quality_funnel?.ai_review_cache_hits ?? 0)
  const cacheMisses = Number(result.quality_funnel?.ai_review_cache_misses ?? 0)
  const cacheReadEnabled = result.quality_funnel?.ai_review_cache_read_enabled !== false
  const cacheSummary =
    !cacheReadEnabled
      ? '本次未使用 AI 精筛缓存。'
      : cacheHits > 0
      ? `本次复用了 ${cacheHits} 批 AI 精筛缓存，实时调用 ${cacheMisses} 批。`
      : cacheMisses > 0
        ? `本次实时调用 ${cacheMisses} 批 AI 精筛，没有复用缓存。`
        : ''
  const hasSourceScanStats = sourceSentenceCount > 0 || reviewedSourceCount > 0
  const diagnosticCount =
    (result.ai_rejected_count ?? 0) + result.learning_point_summary.hidden_duplicate + result.learning_point_summary.hard_blocked
  const visiblePoints = useMemo(
    () =>
      points.filter((point) => {
        const query = searchQuery.trim().toLocaleLowerCase()
        if (
          query &&
          ![pointLabel(point), point.source_sentence, point.exact_span, point.learning_action]
            .filter(Boolean)
            .some((value) => String(value).toLocaleLowerCase().includes(query))
        ) {
          return false
        }        if (typeFilter !== 'all' && point.type !== typeFilter) return false
        if (statusFilter === 'cardable' && !cardableLearningPoint(point)) return false
        if (statusFilter === 'needs_review' && !(cardableLearningPoint(point) && learningPointNeedsSourceReview(point))) return false
        if (
          statusFilter !== 'cardable' &&
          statusFilter !== 'needs_review' &&
          statusFilter !== 'all' &&
          point.status !== statusFilter
        ) {
          return false
        }
        if (!levelMatches(String(point.level || point.estimated_level || ''), levelFilter)) return false
        return true
      }),
    [levelFilter, points, searchQuery, statusFilter, typeFilter],
  )
  const visibleCardablePoints = visiblePoints.filter(cardableLearningPoint)
  const cardableVisibleIds = visibleCardablePoints.map((point) => point.id)
  const visibleRecommendedCount = visibleCardablePoints.filter((point) => point.status === 'recommended').length
  const visibleNeedsReviewCardableCount = visibleCardablePoints.filter(learningPointNeedsSourceReview).length
  const visibleSelectedCount = visibleCardablePoints.filter((point) => selectedIds.has(point.id)).length
  const recommendedIds = points
    .filter((point) => point.status === 'recommended' && cardableLearningPoint(point))
    .map((point) => point.id)
  const cardableIds = points.filter(cardableLearningPoint).map((point) => point.id)
  const duplicateCount = points.filter((point) => point.status === 'hidden_duplicate').length
  const hardBlockedCount = points.filter((point) => point.status === 'hard_blocked').length
  const sourceQualityCounts = result.quality_funnel?.source_sentence_quality_counts as Record<string, number> | undefined
  const sourceQualitySignals = sourceQualityCounts
    ? [
        ['too_long', '长句'],
        ['possible_bad_join', '疑似拼接'],
        ['rolling_caption_uncertain', '滚动字幕'],
        ['repeated_adjacent_words', '重复词'],
        ['fragment', '残句'],
      ]
        .map(([key, label]) => {
          const value = Number(sourceQualityCounts[key] ?? 0)
          return value > 0 ? `${label} ${value}` : ''
        })
        .filter(Boolean)
    : []
  const sourceReviewHint = sourceQualitySignals.length ? `字幕质量信号：${sourceQualitySignals.slice(0, 4).join(' · ')}` : ''
  const allCardableSelected = cardableIds.length > 0 && cardableIds.every((id) => selectedIds.has(id))
  const allRecommendedSelected = recommendedIds.length > 0 && recommendedIds.every((id) => selectedIds.has(id))
  const allVisibleSelected =
    cardableVisibleIds.length > 0 && cardableVisibleIds.every((id) => selectedIds.has(id))

  const replaceSelection = (ids: string[]) => onSetSelectedIds(new Set(ids))
  const selectAllCardable = () => {
    onSetSelectedIds(new Set(cardableIds))
  }
  const selectOnlyRecommended = () => {
    onSetSelectedIds(new Set(recommendedIds))
  }
  const togglePoint = (point: LearningPointItem) => {
    if (!cardableLearningPoint(point)) return
    const next = new Set(selectedIds)
    if (next.has(point.id)) next.delete(point.id)
    else next.add(point.id)
    onSetSelectedIds(next)
  }
  const toggleVisible = () => {
    const next = new Set(selectedIds)
    if (allVisibleSelected) {
      cardableVisibleIds.forEach((id) => next.delete(id))
    } else {
      cardableVisibleIds.forEach((id) => next.add(id))
    }
    onSetSelectedIds(next)
  }

  return (
    <div className="learning-point-overview" aria-label="学习点总览">
      <div className="learning-point-hero compact-learning-point-hero">
        <div>
          <span className="hero-kicker">学习点清单</span>
          <h2>
            {hasSourceScanStats
              ? `AI 已扫描 ${reviewedSourceCount || sourceSentenceCount}/${sourceSentenceCount || reviewedSourceCount} 句字幕`
              : `AI 已精筛 ${result.learning_point_summary.total} 个学习点`}
          </h2>
          <p>
            发现 {result.learning_point_summary.total} 个；推荐 {result.learning_point_summary.recommended} 个，候选{' '}
            {result.learning_point_summary.candidate_only} 个。默认先勾选高质量推荐；“全选可制卡项”会包含候选和需复查但合法的学习点，重复折叠和不可制卡不会进入队列。
          </p>
        </div>
        <div className="learning-point-primary-count">
          <strong>{selected.length}</strong>
          <span>已选学习点 {selected.length} / 可制卡 {cardableIds.length}</span>
          {generationConfirmOpen ? (
            <span className="generation-confirm-open-badge">确认区已打开</span>
          ) : (
            <button
              type="button"
              className="primary-button"
              data-focus-return="generate-selected"
              onClick={(event) => {
                rememberReturnFocus(event.currentTarget)
                onGenerateCards()
              }}
              disabled={workerBusy || selected.length === 0}
            >
              <ListChecks size={18} />
              {workflowReadiness?.canProceed === false
                ? workflowReadiness.primaryActionLabel
                : `生成选中的 ${selected.length} 张`}
            </button>
          )}
          <small className="learning-point-selection-hint">
            筛选只改变列表；批量勾选才会改变队列。当前推荐已勾选{' '}
            {selectedRecommendedCount}/{recommendedIds.length} 个。
          </small>
          <button type="button" className="ghost-button compact-secondary-action" onClick={onExtractWithoutCache} disabled={workerBusy}>
            重新分析素材
          </button>
        </div>
      </div>

      <div className={`learning-point-review-grid ${generationConfirmOpen ? 'has-confirm' : ''}`}>
        {generationConfirmOpen ? (
          <section
            className="generation-confirm-panel"
            aria-label="生成确认"
            aria-modal="true"
            ref={confirmPanelRef}
            role="dialog"
            tabIndex={-1}
          >
            <div className="generation-confirm-header">
              <div>
                <span className="hero-kicker">生成确认</span>
                <h3>
                  准备生成 APKG · {generationQueueSummary.count} 个学习点
                </h3>
                <p>
                  {generationQueueSummary.sourceLabel} · {generationQueueSummary.modeLabel}。每个学习点默认生成 1 张统一学习卡；点击开始后会先选择保存目录，再自动完成正文、TTS、媒体切片和 APKG 打包。
                </p>
              </div>
              <div className="generation-confirm-actions">
                <button
                  type="button"
                  className="primary-button generation-confirm-primary"
                  onClick={onConfirmGenerateCards}
                  disabled={
                    workerBusy ||
                    generationQueueSummary.count === 0 ||
                    workflowReadiness?.canProceed === false
                  }
                >
                  <ListChecks size={18} />
                  {workflowReadiness?.canProceed === false
                    ? workflowReadiness.primaryActionLabel
                    : '生成 APKG'}
                </button>
                <button type="button" className="ghost-button" onClick={onCloseGenerationConfirm} disabled={workerBusy}>
                  返回调整
                </button>
              </div>
            </div>

            {workflowReadiness && workflowReadiness.blockers.length > 0 ? (
              <div className="generation-confirm-blockers" role="status">
                <strong>{workflowReadiness.primaryActionLabel}</strong>
                {workflowReadiness.blockers.map((blocker) => (
                  <span key={blocker.id}>
                    <b>{blocker.title}</b>
                    <small>{blocker.detail}</small>
                  </span>
                ))}
              </div>
            ) : null}

            <div className="generation-run-summary-strip" aria-label="生成运行状态">
              <span>
                <small>已选</small>
                <strong>{generationQueueSummary.count}</strong>
              </span>
              <span>
                <small>已处理</small>
                <strong>{generationQueueSummary.completedCount}</strong>
              </span>
              <span>
                <small>已生成</small>
                <strong>{generationQueueSummary.generatedCount}</strong>
              </span>
              <span>
                <small>可导出</small>
                <strong>{generationQueueSummary.exportableCount}</strong>
              </span>
              <span>
                <small>硬失败</small>
                <strong>{generationQueueSummary.missingCount}</strong>
              </span>
            </div>

            <div className="generation-confirm-minor">
              <span>
                {generationQueueSummary.batchMode
                  ? `内部将分 ${generationQueueSummary.batchCount} 批稳定处理，每批最多 ${generationQueueSummary.batchSize} 张；用户只需要点一次。`
                  : '本轮会直接进入一键生成 APKG。'}
              </span>
              <button type="button" className="link-button" onClick={() => setShowGenerationDetails((current) => !current)}>
                {showGenerationDetails ? '收起生成详情' : '查看生成详情'}
              </button>
            </div>

            {showGenerationDetails ? (
              <div className="generation-confirm-details" aria-label="生成详情">
                <div className="generation-confirm-metrics" aria-label="生成队列信息">
                  <Metric label="学习点" value={generationQueueSummary.count} />
                  <Metric label="批次数" value={generationQueueSummary.batchCount} />
                  <Metric label="每批上限" value={generationQueueSummary.batchSize} />
                  <BooleanMetric label="视频" enabled={generationQueueSummary.includesVideo} />
                  <BooleanMetric label="原声" enabled={generationQueueSummary.includesOriginalAudio} />
                  <BooleanMetric label="整句 TTS" enabled={generationQueueSummary.includesSentenceTts} />
                  <BooleanMetric label="表达 TTS" enabled={generationQueueSummary.includesPhraseTts} />
                  {generationQueueSummary.highRiskShortExpressionCount ? (
                    <Metric label="短表达" value={generationQueueSummary.highRiskShortExpressionCount} />
                  ) : null}
                </div>
                {generationQueueSummary.highRisk ? (
                  <p className="generation-risk-note">本轮达到 50 张以上，模型、TTS 和媒体任务会明显变慢；建议先用少量样本确认质量。</p>
                ) : null}
                {generationQueueSummary.batchMode ? (
                  <p className="generation-batch-note">
                    已启用稳定分批：当前已完成 {generationQueueSummary.completedBatches}/{generationQueueSummary.batchCount} 批；已处理{' '}
                    {generationQueueSummary.completedCount}/{generationQueueSummary.count}，已生成 {generationQueueSummary.generatedCount}，
                    未生成 {generationQueueSummary.missingCount}。
                  </p>
                ) : null}
                {generationQueueSummary.securityWarnings.length ? (
                  <div className="generation-security-note" aria-label="生成安全提示">
                    {generationQueueSummary.securityWarnings.map((warning) => (
                      <span key={warning}>{warning}</span>
                    ))}
                  </div>
                ) : null}
                <div className="generation-queue-heading">
                  <strong>本轮队列</strong>
                  <span>
                    预览前 {Math.min(generationQueuePoints.length, 4)} 条；队列里的每个学习点默认只生成一张学习卡。
                    {generationQueuePoints.length > 4 ? ` 还有 ${generationQueuePoints.length - 4} 条已在队列中。` : ''}
                  </span>
                </div>
                <div className="generation-queue-list" aria-label="本轮生成队列">
                  {generationQueuePoints.slice(0, 4).map((point) => (
                    <div key={point.id} className="generation-queue-item">
                      <span>
                        <strong>{pointLabel(point)}</strong>
                        <small>{point.source_time || point.source_segment_id}</small>
                      </span>
                      <button
                        type="button"
                        className="icon-text-button"
                        onClick={() => onRemoveGenerationQueuePoint(point.id)}
                        disabled={workerBusy}
                        aria-label={`从生成队列移除 ${pointLabel(point)}`}
                      >
                        <Trash2 size={15} />
                        移除
                      </button>
                    </div>
                  ))}
                  {generationQueuePoints.length > 4 ? (
                    <span className="generation-queue-more">
                      其余 {generationQueuePoints.length - 4} 条会一起生成，可用“返回调整”回到列表调整勾选。
                    </span>
                  ) : null}
                </div>
              </div>
            ) : null}
          </section>
        ) : null}

        <div className="learning-point-main-column">
          <div className="learning-point-diagnostic-toggle">
            <span>
              当前显示 {visiblePoints.length} 个；已选学习点 {selected.length} 个；推荐已选 {selectedRecommendedCount}/{recommendedIds.length} 个。
            </span>
            <button type="button" className="link-button" onClick={() => setShowLearningDiagnostics((current) => !current)}>
              {showLearningDiagnostics ? '收起高级诊断' : '高级诊断'}
            </button>
          </div>
          {showLearningDiagnostics ? (
            <div className="learning-point-compact-stats" aria-label="学习点统计">
              <span>源句 {reviewedSourceCount || sourceSentenceCount}</span>
              <span>学习点 {result.learning_point_summary.total}</span>
              <span>推荐 {result.ai_recommended_count ?? result.learning_point_summary.recommended}</span>
              <span>候选 {result.ai_candidate_count ?? result.learning_point_summary.candidate_only}</span>
              <span>重复 {result.learning_point_summary.hidden_duplicate}</span>
              <span>诊断 {diagnosticCount}</span>
              <span>缓存 {cacheHits}</span>
              <span>实时 {cacheMisses}</span>
              {modelLabel ? <span>{modelLabel}</span> : null}
              {cacheSummary ? <span>{cacheSummary}</span> : null}
            </div>
          ) : null}

          <div className="learning-point-view-controls" aria-label="学习点视图">
            <div className="learning-point-view-switch">
              <button
                type="button"
                className={statusFilter === 'recommended' ? 'selected' : ''}
                aria-pressed={statusFilter === 'recommended'}
                disabled={!hasRecommendedPoints}
                onClick={() => setStatusFilter('recommended')}
              >
                推荐 {recommendedIds.length}
              </button>
              <button
                type="button"
                className={statusFilter === 'cardable' ? 'selected' : ''}
                aria-pressed={statusFilter === 'cardable'}
                onClick={() => setStatusFilter('cardable')}
              >
                全部可制卡 {cardableIds.length}
              </button>
            </div>
            <label className="learning-point-search">
              <Search size={16} />
              <input
                aria-label="搜索学习点"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder="搜索表达、原句或学习动作"
              />
            </label>
            <button
              type="button"
              className="ghost-button learning-point-filter-toggle"
              aria-expanded={showFilters}
              onClick={() => setShowFilters((current) => !current)}
            >
              <Filter size={16} />
              {showFilters ? '收起筛选' : '筛选'}
            </button>
          </div>
          {!hasRecommendedPoints ? (
            <div className="learning-point-recommended-fallback" role="status">
              本次没有高置信推荐项，已自动显示全部可制卡项；请结合原句与“需复查”标记选择。
            </div>
          ) : null}

          <div className="learning-point-toolbar" aria-label="学习点筛选">
            {showFilters ? (
              <>
            <div className="learning-point-filter-row">
              <Filter size={16} />
              {typeFilters.map((filter) => (
                <button
                  key={filter.id}
                  type="button"
                  className={typeFilter === filter.id ? 'selected' : ''}
                  aria-pressed={typeFilter === filter.id}
                  onClick={() => setTypeFilter(filter.id)}
                >
                  {filter.label}
                </button>
              ))}
            </div>
            <div className="learning-point-filter-row">
              <Layers3 size={16} />
              {levelFilters.map((filter) => (
                <button
                  key={filter}
                  type="button"
                  className={levelFilter === filter ? 'selected' : ''}
                  aria-pressed={levelFilter === filter}
                  onClick={() => setLevelFilter(filter)}
                >
                  {filter === 'all' ? '全部级别' : filter}
                </button>
              ))}
            </div>
            <div className="learning-point-filter-row">
              <Sparkles size={16} />
              {statusFilters.map((filter) => (
                <button
                  key={filter.id}
                  type="button"
                  className={statusFilter === filter.id ? 'selected' : ''}
                  aria-pressed={statusFilter === filter.id}
                  onClick={() => setStatusFilter(filter.id)}
                >
                  {filter.label}
                </button>
              ))}
            </div>
              </>
            ) : null}
            <div className="learning-point-selection-panel" aria-label="批量选择学习点">
              <div className="learning-point-selection-copy">
                <strong>批量选择</strong>
                <span>
                  可制卡项 {cardableIds.length} 个；当前筛选显示 {visiblePoints.length} 个，其中可制卡 {visibleCardablePoints.length} 个、需复查{' '}
                  {visibleNeedsReviewCardableCount} 个、推荐 {visibleRecommendedCount} 个；已选当前筛选 {visibleSelectedCount} 个。
                  重复折叠 {duplicateCount} 个、不可制卡 {hardBlockedCount} 个不会进入队列。
                  {sourceReviewHint ? ` ${sourceReviewHint}。` : ''}
                </span>
                {cardableIds.length === 0 ? (
                  <em className="learning-point-warning">
                    当前没有可制卡项；请重新抽取或检查字幕质量，重复折叠和不可制卡项不会进入生成队列。
                  </em>
                ) : null}
              </div>
              <div className="learning-point-actions">
                <button type="button" className="ghost-button" onClick={selectAllCardable} disabled={cardableIds.length === 0 || allCardableSelected}>
                  全选可制卡项 {cardableIds.length}
                </button>
                <button type="button" className="ghost-button" onClick={selectOnlyRecommended} disabled={recommendedIds.length === 0 || allRecommendedSelected}>
                  只选推荐 {recommendedIds.length}
                </button>
                <button type="button" className="ghost-button" onClick={toggleVisible} disabled={cardableVisibleIds.length === 0}>
                  {allVisibleSelected ? `取消当前筛选 ${cardableVisibleIds.length}` : `勾选当前筛选 ${cardableVisibleIds.length}`}
                </button>
                <button type="button" className="ghost-button" onClick={() => replaceSelection([])} disabled={selected.length === 0}>
                  清空选择
                </button>
              </div>
            </div>
          </div>

          <div className="learning-point-list-shell">
            <div className="learning-point-list-top">
              <strong>学习点列表</strong>
              <span>
                当前显示 {visiblePoints.length} 个；已选学习点 {selected.length} 个。
              </span>
            </div>
            <div className="learning-point-list" aria-label="学习点列表">
              {visiblePoints.map((point) => {
                const selectable = cardableLearningPoint(point)
                const needsSourceReview = learningPointNeedsSourceReview(point)
                const checked = selectedIds.has(point.id)
                const checkLabel = !selectable ? '不可制卡' : needsSourceReview ? '可制卡 · 需复查' : '选择'
                return (
                  <article key={point.id} className={`learning-point-row status-${point.status} ${checked ? 'selected' : ''}`}>
                    <label className="learning-point-check">
                      <input
                        type="checkbox"
                        checked={checked}
                        disabled={!selectable}
                        aria-label={`${checkLabel}: ${pointLabel(point)}`}
                        onChange={() => togglePoint(point)}
                      />
                      <span>{checkLabel}</span>
                    </label>
                    <div className="learning-point-main">
                      <div className="learning-point-title">
                        <strong>{pointLabel(point)}</strong>
                        <span>{learningPointTypeLabels[point.type] ?? point.type}</span>
                        <span>{point.level || point.estimated_level || '未分级'}</span>
                        <em>{learningPointStatusLabels[point.status]}</em>
                        {needsSourceReview ? <em>需复查</em> : null}
                      </div>
                      <p>{point.source_sentence}</p>
                      <small>{point.source_time || point.source_segment_id || '未记录时间点'}</small>
                      {point.learning_action || point.status_reason || point.reason ? (
                        <details className="learning-point-row-detail">
                          <summary>详情</summary>
                          <span>{point.learning_action || point.reason}</span>
                          <span>{point.status_reason || point.reason}</span>
                        </details>
                      ) : null}
                      {selectable ? (
                        <div className="learning-point-row-actions">
                          <button
                             type="button"
                             className="ghost-button"
                             data-focus-return={`single-${point.id}`}
                             onClick={(event) => {
                               rememberReturnFocus(event.currentTarget)
                               onGenerateSinglePoint(point.id)
                             }}
                             disabled={workerBusy}
                           >
                            只生成这一条
                          </button>
                        </div>
                      ) : null}
                    </div>
                  </article>
                )
              })}
              {visiblePoints.length === 0 ? (
                <div className="filter-empty-state">
                  <strong>当前筛选下没有学习点</strong>
                  <span>换一个级别、类型或状态筛选，再决定要生成哪些学习卡。</span>
                </div>
              ) : null}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <span>
      <small>{label}</small>
      <strong>{value}</strong>
    </span>
  )
}

function BooleanMetric({ label, enabled }: { label: string; enabled: boolean }) {
  return (
    <span>
      <small>{label}</small>
      <strong>{enabled ? '有' : '无'}</strong>
    </span>
  )
}
