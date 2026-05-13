import type { RefObject } from 'react'
import { MessageSquareText } from 'lucide-react'

import type {
  AnkiVerifyResult,
  Card,
  ExportResult,
  Level,
  Project,
  QualityFunnel,
  Segment,
  SegmentFilter,
  SourceMode,
} from '../../domain/types'
import type { QualityCounts, QualityDiagnostics } from '../../domain/projectMetrics'
import { EmptyWorkbench } from './EmptyWorkbench'
import { ExportResultPanel } from './ExportResultPanel'
import { ReviewSummaryPanel } from './ReviewSummaryPanel'
import { SegmentDetail } from './SegmentDetail'
import { SegmentList } from './SegmentList'

type SegmentReviewCounts = Record<SegmentFilter, number>

type ReviewWorkspaceProps = {
  activeSegment?: Segment
  activeSegmentId: string | null
  activeSegmentVideoSrc: string
  activeTemplateLabel: string
  ankiVerifying: boolean
  ankiVerifyResult: AnkiVerifyResult | null
  appBusy: boolean
  lastExport: ExportResult | null
  language: string
  level: Level
  maxSegments: number
  motionDuration: number
  prefersReducedMotion: boolean
  previewPanelRef: RefObject<HTMLElement | null>
  previewRate: number
  project: Project | null
  qualityCounts: QualityCounts
  qualityDiagnostics: QualityDiagnostics
  qualityFunnel: QualityFunnel
  selectedCardCount: number
  segmentFilter: SegmentFilter
  segmentReviewCounts: SegmentReviewCounts
  sourceMode: SourceMode
  templateId: string
  visibleSegments: Segment[]
  onGenerate: () => void
  onOpenAnkiImport: () => void
  onOpenSettings: () => void
  onPreviewRateChange: (rate: number) => void
  onRevealExport: () => void
  onSegmentFilterChange: (filter: SegmentFilter) => void
  onSelectCardsByQuality: (quality: 'recommended' | 'reviewable') => void
  onSelectSegment: (segmentId: string) => void
  onSetCardsEnabled: (enabled: boolean, segmentId?: string) => void
  onUpdateCard: (segmentId: string, cardId: string, patch: Partial<Card>) => void
  onVerifyAnkiImport: () => void
}

export function ReviewWorkspace({
  activeSegment,
  activeSegmentId,
  activeSegmentVideoSrc,
  activeTemplateLabel,
  ankiVerifying,
  ankiVerifyResult,
  appBusy,
  lastExport,
  language,
  level,
  maxSegments,
  motionDuration,
  prefersReducedMotion,
  previewPanelRef,
  previewRate,
  project,
  qualityCounts,
  qualityDiagnostics,
  qualityFunnel,
  selectedCardCount,
  segmentFilter,
  segmentReviewCounts,
  sourceMode,
  templateId,
  visibleSegments,
  onGenerate,
  onOpenAnkiImport,
  onOpenSettings,
  onPreviewRateChange,
  onRevealExport,
  onSegmentFilterChange,
  onSelectCardsByQuality,
  onSelectSegment,
  onSetCardsEnabled,
  onUpdateCard,
  onVerifyAnkiImport,
}: ReviewWorkspaceProps) {
  return (
    <section
      className={`panel preview-panel template-${templateId}`}
      ref={previewPanelRef}
      tabIndex={-1}
      aria-labelledby="preview-title"
    >
      <div className="preview-header">
        <div className="panel-heading">
          <MessageSquareText size={20} />
          <div>
            <h3 id="preview-title">{project ? 'AI 评审工作台' : '生成工作台'}</h3>
            <p className="panel-subtitle">
              {project ? '查看模型留下的表达、判断理由和可导出的卡片草稿。' : '先选择素材，再生成卡片；结果会在这里展开。'}
            </p>
          </div>
        </div>
        {project ? (
          <div className="preview-actions">
            <button className="ghost-button" type="button" onClick={() => onSetCardsEnabled(true)}>
              全选
            </button>
            <button className="ghost-button" type="button" onClick={() => onSetCardsEnabled(false)}>
              全不选
            </button>
            <button className="ghost-button" type="button" onClick={() => onSelectCardsByQuality('recommended')}>
              只保留推荐
            </button>
            <button className="ghost-button" type="button" onClick={() => onSelectCardsByQuality('reviewable')}>
              推荐+待审
            </button>
          </div>
        ) : null}
      </div>

      {project ? (
        <ReviewSummaryPanel
          activeTemplateLabel={activeTemplateLabel}
          language={language}
          level={level}
          project={project}
          qualityCounts={qualityCounts}
          qualityDiagnostics={qualityDiagnostics}
          qualityFunnel={qualityFunnel}
          selectedCardCount={selectedCardCount}
          segmentFilter={segmentFilter}
          segmentReviewCounts={segmentReviewCounts}
          onSegmentFilterChange={onSegmentFilterChange}
        />
      ) : null}

      {lastExport ? (
        <ExportResultPanel
          ankiVerifying={ankiVerifying}
          ankiVerifyResult={ankiVerifyResult}
          lastExport={lastExport}
          onOpenAnkiImport={onOpenAnkiImport}
          onRevealExport={onRevealExport}
          onVerifyAnkiImport={onVerifyAnkiImport}
        />
      ) : null}

      {!project ? (
        <EmptyWorkbench
          appBusy={appBusy}
          level={level}
          maxSegments={maxSegments}
          sourceMode={sourceMode}
          templateLabel={activeTemplateLabel}
          onGenerate={onGenerate}
          onOpenSettings={onOpenSettings}
        />
      ) : (
        <div className="preview-layout">
          <SegmentList
            activeSegmentId={activeSegmentId}
            motionDuration={motionDuration}
            prefersReducedMotion={prefersReducedMotion}
            segments={visibleSegments}
            onSelectSegment={onSelectSegment}
          />

          {activeSegment ? (
            <SegmentDetail
              motionDuration={motionDuration}
              prefersReducedMotion={prefersReducedMotion}
              previewRate={previewRate}
              segment={activeSegment}
              videoSrc={activeSegmentVideoSrc}
              onPreviewRateChange={onPreviewRateChange}
              onSetSegmentCardsEnabled={onSetCardsEnabled}
              onUpdateCard={onUpdateCard}
            />
          ) : null}
        </div>
      )}
    </section>
  )
}
