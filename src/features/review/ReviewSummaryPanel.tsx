import { Sparkles } from 'lucide-react'

import type { Project, QualityFunnel, SegmentFilter } from '../../domain/types'
import { learningLanguageLabel } from '../../domain/options'
import { segmentFilterOptions } from '../../domain/quality'
import type { QualityCounts, QualityDiagnostics } from '../../domain/projectMetrics'

type SegmentReviewCounts = Record<SegmentFilter, number>

type ReviewSummaryPanelProps = {
  activeTemplateLabel: string
  language: string
  level: string
  project: Project
  qualityCounts: QualityCounts
  qualityDiagnostics: QualityDiagnostics
  qualityFunnel: QualityFunnel
  selectedCardCount: number
  segmentFilter: SegmentFilter
  segmentReviewCounts: SegmentReviewCounts
  onSegmentFilterChange: (filter: SegmentFilter) => void
}

function subtitleSourceLabel(project: Project) {
  if (project.source_mode !== 'local') return ''
  const sourceInfo = project.source_info
  const source = sourceInfo && 'subtitle_source' in sourceInfo ? String(sourceInfo.subtitle_source || '').trim() : ''
  if (source === 'manual') return '手动字幕'
  if (source === 'auto_matched') return '自动匹配字幕'
  if (source === 'embedded') return '内嵌字幕'
  return source ? '字幕来源已记录' : ''
}

export function ReviewSummaryPanel({
  activeTemplateLabel,
  language,
  level,
  project,
  qualityCounts,
  qualityDiagnostics,
  qualityFunnel,
  selectedCardCount,
  segmentFilter,
  segmentReviewCounts,
  onSegmentFilterChange,
}: ReviewSummaryPanelProps) {
  const isDocument = project.source_mode === 'document'
  const isReading = isDocument && project.document_study_mode === 'language_reading'
  const localSubtitleSource = subtitleSourceLabel(project)
  const displayLanguage = learningLanguageLabel(language)
  const materialContext = project.material_context
  const materialSummary = materialContext?.summary || materialContext?.topic || ''
  const maxLearningPoints = qualityFunnel.max_learning_points_per_source ?? 4
  const usableCount = qualityFunnel.usable_card_count ?? qualityFunnel.card_count ?? qualityCounts.total
  const selectedCount = selectedCardCount
  const duplicateCount = qualityFunnel.duplicate_learning_point_count ?? qualityDiagnostics.duplicate
  const candidateOnlyCount = qualityFunnel.candidate_only_learning_point_count ?? 0
  const hiddenDuplicateCount = qualityFunnel.hidden_duplicate_learning_point_count ?? duplicateCount
  const hardBlockedCount = qualityFunnel.hard_blocked_learning_point_count ?? qualityFunnel.blocked_quality_issue_count ?? 0
  const diagnosticCount = candidateOnlyCount + hiddenDuplicateCount + hardBlockedCount
  const levelLabel = project.level_mode === 'manual' ? level : '自动判断'
  const sourceSentenceCount = qualityFunnel.source_sentence_count ?? qualityFunnel.subtitle_cues
  const labels = isReading
    ? {
        score: '精读点质量',
        candidate: '精读点',
        pipeline: '文档精读过程',
        sourceUnits: '文档片段',
        usable: '可用精读卡',
        duplicate: '重复精读点',
      }
    : isDocument
      ? {
          score: '知识点质量',
          candidate: '知识点',
          pipeline: '文档制卡过程',
          sourceUnits: '文档片段',
          usable: '可用知识卡',
          duplicate: '重复知识点',
        }
      : {
          score: '平均词伙评分',
          candidate: '候选片段',
          pipeline: '智能筛选过程',
          sourceUnits: '字幕句',
          usable: '可用卡片',
          duplicate: '重复合并',
        }

  return (
    <>
      <div className="review-dashboard" aria-label="生成审核概览">
        <div className="metric-card primary">
          <span>已选导出 / 生成卡片</span>
          <strong>{`${selectedCardCount}/${usableCount}`}</strong>
          <small>{`已生成 ${usableCount} 张可用卡，默认全选`}</small>
        </div>
        <div className="metric-card">
          <span>生成卡片数</span>
          <strong>{usableCount}</strong>
          <small>通过质量 gate，可直接勾选导出</small>
        </div>
        <div className="metric-card">
          <span>已选卡片数</span>
          <strong>{selectedCount}</strong>
          <small>导出只包含当前勾选的卡片</small>
        </div>
        <div className="metric-card">
          <span>发现学习点</span>
          <strong>{qualityFunnel.learning_point_count ?? qualityDiagnostics.candidates}</strong>
          <small>
            {project.max_segments
              ? `${project.auto_max_segments ? '自动预算' : '预算'} ${project.max_segments} · `
              : ''}
            {`每句最多 ${maxLearningPoints} 个学习点 · `}
            {levelLabel} · {displayLanguage} · {activeTemplateLabel}
            {localSubtitleSource ? ` · ${localSubtitleSource}` : ''}
            {project.source_mode === 'local' && project.skip_video_slicing ? ' · 字幕-only' : ''}
          </small>
        </div>
        <div className="metric-card">
          <span>更多学习点</span>
          <strong>{diagnosticCount}</strong>
          <small>{diagnosticCount ? '有些学习点未制卡，可打开“更多学习点”查看原因' : '合法学习点已自动生成卡片'}</small>
        </div>
        <div className="metric-card">
          <span>重复 / 硬阻断</span>
          <strong>{`${hiddenDuplicateCount}/${hardBlockedCount}`}</strong>
          <small>{`${labels.candidate} ${qualityDiagnostics.candidates} · ${labels.score} ${
            qualityDiagnostics.avgScore === null ? '-' : qualityDiagnostics.avgScore.toFixed(1)
          }`}</small>
        </div>
      </div>

      {materialSummary ? (
        <div className="material-context-card" aria-label="素材理解">
          <span>{project.study_depth === 'deep' ? '深度理解' : '素材理解'}</span>
          <strong>{materialSummary}</strong>
          {materialContext?.learning_opportunities?.length ? (
            <small>{materialContext.learning_opportunities.slice(0, 4).join(' / ')}</small>
          ) : null}
        </div>
      ) : null}

      <details className="quality-funnel-details">
        <summary>
          <span className="funnel-summary-title">
            <Sparkles size={14} />
            {labels.pipeline}
          </span>
          <strong>{`可用 ${usableCount} · 已选 ${selectedCount} · 更多 ${diagnosticCount}`}</strong>
        </summary>
        <div className="quality-funnel" aria-label="质量漏斗">
          <span>
            <strong>{sourceSentenceCount ?? '-'}</strong>
            <small>{labels.sourceUnits}</small>
          </span>
          <span>
            <strong>{qualityFunnel.learning_point_count ?? qualityFunnel.candidate_segments ?? '-'}</strong>
            <small>学习点</small>
          </span>
          <span>
            <strong>{qualityFunnel.card_count ?? qualityCounts.total}</strong>
            <small>生成卡片</small>
          </span>
          <span>
            <strong>{usableCount}</strong>
            <small>{labels.usable}</small>
          </span>
          <span>
            <strong>{diagnosticCount}</strong>
            <small>更多学习点</small>
          </span>
          <span>
            <strong>{hiddenDuplicateCount}</strong>
            <small>重复折叠</small>
          </span>
          <span>
            <strong>{hardBlockedCount}</strong>
            <small>硬阻断</small>
          </span>
          <span>
            <strong>{selectedCount}</strong>
            <small>已选导出</small>
          </span>
        </div>
      </details>

      <div className="review-filters" aria-label="卡片选择筛选">
        {segmentFilterOptions.map((option) => (
          <button
            key={option.id}
            type="button"
            className={segmentFilter === option.id ? 'selected' : ''}
            aria-pressed={segmentFilter === option.id}
            onClick={() => onSegmentFilterChange(option.id)}
          >
            <span>{option.label}</span>
            <strong>{segmentReviewCounts[option.id]}</strong>
          </button>
        ))}
      </div>
    </>
  )
}
