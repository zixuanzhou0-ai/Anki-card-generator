import { Sparkles } from 'lucide-react'

import type { Project, QualityFunnel, SegmentFilter } from '../../domain/types'
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
  const materialContext = project.material_context
  const materialSummary = materialContext?.summary || materialContext?.topic || ''
  const labels = isReading
    ? {
        score: '精读点质量',
        candidate: '精读点',
        pipeline: '文档精读流水线',
        sourceUnits: '文档片段',
        reviewed: '精读保留',
        recommended: '推荐精读卡',
        review: '待审精读卡',
        duplicate: '重复精读点',
      }
    : isDocument
      ? {
          score: '知识点质量',
          candidate: '知识点',
          pipeline: '文档知识流水线',
          sourceUnits: '文档片段',
          reviewed: '知识保留',
          recommended: '推荐知识卡',
          review: '待审知识卡',
          duplicate: '重复知识点',
        }
      : {
          score: '平均词伙评分',
          candidate: '候选片段',
          pipeline: 'AI 评审流水线',
          sourceUnits: '字幕句',
          reviewed: '评审保留',
          recommended: '推荐卡',
          review: '待审卡',
          duplicate: '重复合并',
        }

  return (
    <>
      <div className="review-dashboard" aria-label="生成审核概览">
        <div className="metric-card primary">
          <span>已选导出 / 全部卡片</span>
          <strong>{`${selectedCardCount}/${qualityFunnel.card_count ?? qualityCounts.total}`}</strong>
          <small>勾选的卡会进入 APKG</small>
        </div>
        <div className="metric-card">
          <span>推荐可导出</span>
          <strong>{qualityFunnel.recommended_card_count ?? qualityCounts.recommended}</strong>
          <small>质量通过，默认建议保留</small>
        </div>
        <div className="metric-card">
          <span>待人工确认</span>
          <strong>{qualityFunnel.review_card_count ?? qualityCounts.review}</strong>
          <small>{`${qualityCounts.rejected} 张建议删除`}</small>
        </div>
        <div className="metric-card">
          <span>发现学习点</span>
          <strong>{qualityFunnel.learning_point_count ?? qualityDiagnostics.candidates}</strong>
          <small>
            {project.max_segments
              ? `${project.auto_max_segments ? '自动预算' : '预算'} ${project.max_segments} · `
              : ''}
            {level} · {language} · {activeTemplateLabel}
            {localSubtitleSource ? ` · ${localSubtitleSource}` : ''}
            {project.source_mode === 'local' && project.skip_video_slicing ? ' · 字幕-only' : ''}
          </small>
        </div>
        <div className="metric-card">
          <span>已拒绝 / 重复</span>
          <strong>{`${qualityFunnel.rejected_learning_point_count ?? qualityDiagnostics.rejectedSegments}/${
            qualityFunnel.duplicate_learning_point_count ?? qualityDiagnostics.duplicate
          }`}</strong>
          <small>{qualityDiagnostics.shortReason || qualityDiagnostics.rejectReasons[0] || labels.score}</small>
        </div>
        <div className="metric-card">
          <span>{labels.score}</span>
          <strong>{qualityDiagnostics.avgScore === null ? '-' : qualityDiagnostics.avgScore.toFixed(1)}</strong>
          <small>{`${labels.candidate} ${qualityDiagnostics.candidates} · ${labels.duplicate} ${qualityDiagnostics.duplicate}`}</small>
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
          <strong>{`学习点 ${qualityFunnel.learning_point_count ?? qualityFunnel.candidate_segments ?? '-'} · 已选 ${
            qualityFunnel.selected_card_count ?? selectedCardCount
          }`}</strong>
        </summary>
        <div className="quality-funnel" aria-label="质量漏斗">
          <span>
            <strong>{qualityFunnel.subtitle_cues ?? '-'}</strong>
            <small>{labels.sourceUnits}</small>
          </span>
          <span>
            <strong>{qualityFunnel.learning_point_count ?? qualityFunnel.candidate_segments ?? '-'}</strong>
            <small>学习点</small>
          </span>
          <span>
            <strong>{qualityFunnel.card_count ?? qualityCounts.total}</strong>
            <small>全部卡片</small>
          </span>
          <span>
            <strong>{qualityFunnel.recommended_card_count ?? qualityFunnel.recommended_cards ?? '-'}</strong>
            <small>{labels.recommended}</small>
          </span>
          <span>
            <strong>{qualityFunnel.review_card_count ?? qualityFunnel.review_cards ?? '-'}</strong>
            <small>{labels.review}</small>
          </span>
          <span>
            <strong>{qualityFunnel.selected_card_count ?? selectedCardCount}</strong>
            <small>已选导出</small>
          </span>
        </div>
      </details>

      <div className="review-filters" aria-label="片段质量筛选">
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
