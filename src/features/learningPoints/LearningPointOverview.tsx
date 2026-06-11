import { useMemo, useState } from 'react'
import { Filter, Layers3, ListChecks, Sparkles } from 'lucide-react'

import type { LearningPointExtractionResult, LearningPointItem, LearningPointStatus, LearningPointType } from '../../domain/learningPoints'
import {
  learningPointStatusLabels,
  learningPointTypeLabels,
  selectableLearningPoint,
  selectedLearningPoints,
} from '../../domain/learningPoints'

type LearningPointOverviewProps = {
  result: LearningPointExtractionResult
  selectedIds: Set<string>
  workerBusy: boolean
  onGenerateCards: () => void
  onSelectDefaults: () => void
  onSetSelectedIds: (ids: Set<string>) => void
}

type TypeFilter = 'all' | LearningPointType
type LevelFilter = 'all' | 'A1' | 'A2' | 'B1' | 'B2' | 'C1' | 'C2' | 'B1+' | 'B2+'
type StatusFilter = 'selectable' | 'all' | LearningPointStatus

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
  { id: 'selectable', label: '可选择' },
  { id: 'all', label: '全部状态' },
  { id: 'recommended', label: '推荐' },
  { id: 'candidate_only', label: '候选' },
  { id: 'hidden_duplicate', label: '重复' },
  { id: 'hard_blocked', label: '阻断' },
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
  onGenerateCards,
  onSelectDefaults,
  onSetSelectedIds,
}: LearningPointOverviewProps) {
  const [typeFilter, setTypeFilter] = useState<TypeFilter>('all')
  const [levelFilter, setLevelFilter] = useState<LevelFilter>('all')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('selectable')
  const points = useMemo(() => result.learning_points ?? [], [result.learning_points])
  const modelLabel = [result.ai_model_provider, result.ai_model_name].filter(Boolean).join(' · ')
  const selected = selectedLearningPoints(points, selectedIds)
  const sourceSentenceCount = Number(result.quality_funnel?.source_sentence_count ?? result.source_sentences?.length ?? 0)
  const reviewedSourceCount = Number(result.ai_reviewed_source_count ?? result.quality_funnel?.ai_reviewed_source_count ?? 0)
  const cacheHits = Number(result.quality_funnel?.ai_review_cache_hits ?? 0)
  const cacheMisses = Number(result.quality_funnel?.ai_review_cache_misses ?? 0)
  const cacheSummary =
    cacheHits > 0
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
        if (typeFilter !== 'all' && point.type !== typeFilter) return false
        if (statusFilter === 'selectable' && !selectableLearningPoint(point)) return false
        if (statusFilter !== 'selectable' && statusFilter !== 'all' && point.status !== statusFilter) return false
        if (!levelMatches(String(point.level || point.estimated_level || ''), levelFilter)) return false
        return true
      }),
    [levelFilter, points, statusFilter, typeFilter],
  )
  const selectableVisibleIds = visiblePoints.filter(selectableLearningPoint).map((point) => point.id)
  const allVisibleSelected =
    selectableVisibleIds.length > 0 && selectableVisibleIds.every((id) => selectedIds.has(id))

  const replaceSelection = (ids: string[]) => onSetSelectedIds(new Set(ids))
  const togglePoint = (point: LearningPointItem) => {
    if (!selectableLearningPoint(point)) return
    const next = new Set(selectedIds)
    if (next.has(point.id)) next.delete(point.id)
    else next.add(point.id)
    onSetSelectedIds(next)
  }
  const toggleVisible = () => {
    const next = new Set(selectedIds)
    if (allVisibleSelected) {
      selectableVisibleIds.forEach((id) => next.delete(id))
    } else {
      selectableVisibleIds.forEach((id) => next.add(id))
    }
    onSetSelectedIds(next)
  }

  return (
    <div className="learning-point-overview" aria-label="学习点总览">
      <div className="learning-point-hero">
        <div>
          <span className="hero-kicker">学习点清单</span>
          <h2>
            {hasSourceScanStats
              ? `AI 已扫描 ${reviewedSourceCount || sourceSentenceCount}/${sourceSentenceCount || reviewedSourceCount} 句字幕`
              : `AI 已精筛 ${result.learning_point_summary.total} 个学习点`}
          </h2>
          <p>
            精筛出 {result.learning_point_summary.total} 个学习点。推荐 {result.learning_point_summary.recommended} 个，默认已选；候选{' '}
            {result.learning_point_summary.candidate_only} 个，可手动加入制卡；诊断 {diagnosticCount} 个。
            {modelLabel ? `${modelLabel} 已参与精筛。` : '当前结果来自 AI 精筛。'}
            {cacheSummary ? ` ${cacheSummary}` : ''}
          </p>
        </div>
        <div className="learning-point-primary-count">
          <strong>{selected.length}</strong>
          <span>个已选学习点</span>
          <button type="button" className="primary-button" onClick={onGenerateCards} disabled={workerBusy || selected.length === 0}>
            <ListChecks size={18} />
            生成选中卡片
          </button>
        </div>
      </div>

      <div className="learning-point-metrics" aria-label="学习点统计">
        <Metric label="AI 扫描源句" value={reviewedSourceCount || sourceSentenceCount} />
        <Metric label="发现学习点" value={result.learning_point_summary.total} />
        <Metric label="AI 推荐" value={result.ai_recommended_count ?? result.learning_point_summary.recommended} />
        <Metric label="可手选候选" value={result.ai_candidate_count ?? result.learning_point_summary.candidate_only} />
        <Metric label="重复折叠" value={result.learning_point_summary.hidden_duplicate} />
        <Metric label="诊断项" value={diagnosticCount} />
        <Metric label="缓存命中批" value={cacheHits} />
        <Metric label="实时调用批" value={cacheMisses} />
      </div>

      <div className="learning-point-toolbar" aria-label="学习点筛选">
        <div className="learning-point-filter-row">
          <Filter size={16} />
          {typeFilters.map((filter) => (
            <button
              key={filter.id}
              type="button"
              className={typeFilter === filter.id ? 'selected' : ''}
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
              onClick={() => setStatusFilter(filter.id)}
            >
              {filter.label}
            </button>
          ))}
        </div>
        <div className="learning-point-actions">
          <button type="button" className="ghost-button" onClick={onSelectDefaults}>
            全选推荐
          </button>
          <button type="button" className="ghost-button" onClick={toggleVisible}>
            {allVisibleSelected ? '取消当前筛选' : '选择当前筛选'}
          </button>
          <button type="button" className="ghost-button" onClick={() => replaceSelection([])}>
            清空选择
          </button>
        </div>
      </div>

      <div className="learning-point-list" aria-label="学习点列表">
        {visiblePoints.map((point) => {
          const selectable = selectableLearningPoint(point)
          const checked = selectedIds.has(point.id)
          return (
            <article key={point.id} className={`learning-point-row status-${point.status} ${checked ? 'selected' : ''}`}>
              <label className="learning-point-check">
                <input type="checkbox" checked={checked} disabled={!selectable} onChange={() => togglePoint(point)} />
                <span>{selectable ? '选择' : '不可制卡'}</span>
              </label>
              <div className="learning-point-main">
                <div className="learning-point-title">
                  <strong>{pointLabel(point)}</strong>
                  <span>{learningPointTypeLabels[point.type] ?? point.type}</span>
                  <span>{point.level || point.estimated_level || '未分级'}</span>
                  <em>{learningPointStatusLabels[point.status]}</em>
                </div>
                <p>{point.source_sentence}</p>
                <small>训练：{point.learning_action || point.reason}</small>
                <small>原因：{point.status_reason || point.reason}</small>
              </div>
            </article>
          )
        })}
        {visiblePoints.length === 0 ? (
          <div className="filter-empty-state">
            <strong>当前筛选下没有学习点</strong>
            <span>换一个级别、类型或状态筛选，再决定要生成哪些卡。</span>
          </div>
        ) : null}
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
