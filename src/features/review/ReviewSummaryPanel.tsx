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
            {project.max_segments ? `${project.auto_max_segments ? '自动预算' : '预算'} ${project.max_segments} · ` : ''}
            {level} · {language} · {activeTemplateLabel}
          </small>
        </div>
        <div className="metric-card">
          <span>平均词伙评分</span>
          <strong>{qualityDiagnostics.avgScore === null ? '-' : qualityDiagnostics.avgScore.toFixed(1)}</strong>
          <small>{`候选 ${qualityDiagnostics.candidates} · 重复合并 ${qualityDiagnostics.duplicate}`}</small>
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

      <details className="quality-funnel-details">
        <summary>
          <span className="funnel-summary-title">
            <Sparkles size={14} />
            AI 评审流水线
          </span>
          <strong>{`候选 ${qualityFunnel.candidate_segments ?? '-'} · 推荐 ${qualityFunnel.recommended_cards ?? '-'}`}</strong>
        </summary>
        <div className="quality-funnel" aria-label="质量漏斗">
          <span>
            <strong>{qualityFunnel.subtitle_cues ?? '-'}</strong>
            <small>字幕句</small>
          </span>
          <span>
            <strong>{qualityFunnel.candidate_segments ?? '-'}</strong>
            <small>候选片段</small>
          </span>
          <span>
            <strong>{qualityFunnel.reviewed_keep ?? '-'}</strong>
            <small>评审保留</small>
          </span>
          <span>
            <strong>{qualityFunnel.recommended_cards ?? '-'}</strong>
            <small>推荐卡</small>
          </span>
          <span>
            <strong>{qualityFunnel.review_cards ?? '-'}</strong>
            <small>待审卡</small>
          </span>
          <span>
            <strong>{qualityFunnel.duplicate_segments ?? '-'}</strong>
            <small>重复合并</small>
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
