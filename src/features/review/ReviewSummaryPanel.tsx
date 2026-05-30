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
          <span>有效卡片</span>
          <strong>{`${selectedCardCount}/${qualityCounts.total}`}</strong>
          <small>当前勾选后会进入导出</small>
        </div>
        <div className="metric-card">
          <span>推荐保留</span>
          <strong>{qualityCounts.recommended}</strong>
          <small>{`${qualityCounts.review} 张待审 · ${qualityCounts.rejected} 张建议删除`}</small>
        </div>
        <div className="metric-card">
          <span>片段预算</span>
          <strong>{project.segments.length}</strong>
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
          <span>{labels.score}</span>
          <strong>{qualityDiagnostics.avgScore === null ? '-' : qualityDiagnostics.avgScore.toFixed(1)}</strong>
          <small>{`${labels.candidate} ${qualityDiagnostics.candidates} · ${labels.duplicate} ${qualityDiagnostics.duplicate}`}</small>
        </div>
        <div className="metric-card">
          <span>拒绝原因</span>
          <strong>{qualityDiagnostics.rejectedSegments}</strong>
          <small>
            {qualityDiagnostics.shortReason ||
              qualityDiagnostics.rejectReasons[0] ||
              (project.skip_video_slicing ? '字幕-only 导出，不含视频切片。' : '推荐数量正常')}
          </small>
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
          <strong>{`${labels.candidate} ${qualityFunnel.candidate_segments ?? '-'} · ${labels.recommended} ${
            qualityFunnel.recommended_cards ?? '-'
          }`}</strong>
        </summary>
        <div className="quality-funnel" aria-label="质量漏斗">
          <span>
            <strong>{qualityFunnel.subtitle_cues ?? '-'}</strong>
            <small>{labels.sourceUnits}</small>
          </span>
          <span>
            <strong>{qualityFunnel.candidate_segments ?? '-'}</strong>
            <small>{labels.candidate}</small>
          </span>
          <span>
            <strong>{qualityFunnel.reviewed_keep ?? '-'}</strong>
            <small>{labels.reviewed}</small>
          </span>
          <span>
            <strong>{qualityFunnel.recommended_cards ?? '-'}</strong>
            <small>{labels.recommended}</small>
          </span>
          <span>
            <strong>{qualityFunnel.review_cards ?? '-'}</strong>
            <small>{labels.review}</small>
          </span>
          <span>
            <strong>{qualityFunnel.duplicate_segments ?? '-'}</strong>
            <small>{labels.duplicate}</small>
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
