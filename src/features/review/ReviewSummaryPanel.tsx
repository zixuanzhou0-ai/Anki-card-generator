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
  const selectedLearningPointCount = qualityFunnel.selected_learning_point_count
  const successfulLearningPointCount = qualityFunnel.successful_learning_point_count
  const modelMissingLearningPointCount = qualityFunnel.card_generation_missing_learning_point_count ?? 0
  const cardGenerationFilteredCount = qualityFunnel.card_generation_filtered_card_count ?? 0
  const cardGenerationSkippedCount = qualityFunnel.card_generation_skipped_learning_point_count ?? 0
  const cardGenerationDiagnosticItems = project.card_generation_diagnostics?.items ?? []
  const hasCardGenerationDiagnostics =
    selectedLearningPointCount !== undefined ||
    successfulLearningPointCount !== undefined ||
    modelMissingLearningPointCount > 0 ||
    cardGenerationFilteredCount > 0 ||
    cardGenerationSkippedCount > 0 ||
    cardGenerationDiagnosticItems.length > 0
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
      <div className="review-export-summary" aria-label="导出数量概览">
        <div className="export-count-card">
          <span>本次将导出</span>
          <div>
            <strong>{selectedCount}</strong>
            <em>张卡片</em>
          </div>
          <small>{`只导出当前勾选的卡片；已选 ${selectedCount} / 生成 ${usableCount}`}</small>
        </div>
        <div className="export-side-metrics">
          <span>
            <strong>{usableCount}</strong>
            <small>生成可用卡</small>
          </span>
          <span>
            <strong>{segmentReviewCounts.all}</strong>
            <small>片段</small>
          </span>
          <span>
            <strong>{diagnosticCount}</strong>
            <small>更多学习点</small>
          </span>
        </div>
      </div>

      {materialSummary ? (
        <div className="material-context-card" aria-label="素材理解">
          <span>{project.study_depth === 'deep' ? '深入解析' : '素材理解'}</span>
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
            生成诊断
          </span>
          <strong>
            {`${labels.pipeline} · 发现 ${qualityFunnel.learning_point_count ?? qualityDiagnostics.candidates} 个学习点 · 重复 ${hiddenDuplicateCount} · 阻断 ${hardBlockedCount}`}
          </strong>
        </summary>
        <div className="quality-context-line">
          <span>
            {project.max_segments
              ? `${project.auto_max_segments ? '自动预算' : '预算'} ${project.max_segments} · `
              : ''}
            {`每句最多 ${maxLearningPoints} 个学习点 · `}
            {levelLabel} · {displayLanguage} · {activeTemplateLabel}
            {localSubtitleSource ? ` · ${localSubtitleSource}` : ''}
            {project.source_mode === 'local' && project.skip_video_slicing ? ' · 字幕-only' : ''}
          </span>
        </div>
        {hasCardGenerationDiagnostics ? (
          <div className="quality-context-line">
            <span>
              {`学习点制卡：已选 ${selectedLearningPointCount ?? '-'} · 成功 ${successfulLearningPointCount ?? usableCount} · 模型未返回 ${modelMissingLearningPointCount} · 质量过滤 ${cardGenerationFilteredCount}${
                cardGenerationSkippedCount ? ` · 跳过 ${cardGenerationSkippedCount}` : ''
              }`}
            </span>
          </div>
        ) : null}
        {cardGenerationDiagnosticItems.length ? (
          <div className="card-generation-diagnostics" aria-label="未生成学习点明细">
            {cardGenerationDiagnosticItems.slice(0, 5).map((item) => (
              <span key={`${item.learning_point_id}-${item.status}`}>
                <strong>{item.answer_core || item.learning_point_id}</strong>
                <small>
                  {item.status === 'model_missing'
                    ? '模型未返回'
                    : item.status === 'filtered'
                      ? '质量过滤'
                      : item.status === 'skipped'
                        ? '已跳过'
                        : item.status}
                  ：{item.reason}
                </small>
              </span>
            ))}
            {cardGenerationDiagnosticItems.length > 5 ? <em>{`还有 ${cardGenerationDiagnosticItems.length - 5} 个未显示`}</em> : null}
          </div>
        ) : null}
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

      <div className="review-filter-heading">
        <span>片段筛选</span>
        <small>左侧列表按片段显示；一个片段里可能包含多张卡。</small>
      </div>
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
