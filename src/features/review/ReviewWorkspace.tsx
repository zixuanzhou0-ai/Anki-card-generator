import { useMemo, useState, type RefObject } from 'react'
import { MessageSquareText } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'

import type {
  AnkiVerifyResult,
  Card,
  LearningPointInventoryItem,
  ExportResult,
  Level,
  Project,
  QualityFunnel,
  Segment,
  SegmentFilter,
  SourceMode,
} from '../../domain/types'
import type { QualityCounts, QualityDiagnostics } from '../../domain/projectMetrics'
import { candidateKindLabel, clipText, phraseTypeLabel } from '../../domain/quality'
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
  onOpenAnkiImport: () => void
  onRevealExport: () => void
  onSegmentFilterChange: (filter: SegmentFilter) => void
  onInvertCardSelection: () => void
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
  onOpenAnkiImport,
  onRevealExport,
  onSegmentFilterChange,
  onInvertCardSelection,
  onSelectSegment,
  onSetCardsEnabled,
  onUpdateCard,
  onVerifyAnkiImport,
}: ReviewWorkspaceProps) {
  const [reviewView, setReviewView] = useState<'cards' | 'inventory'>('cards')
  const inventory = project?.learning_point_inventory ?? []
  const diagnosticInventory = inventory.filter((item) => item.status !== 'card_generated')
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
            <h3 id="preview-title">{project ? '审核导出' : '生成工作台'}</h3>
            <p className="panel-subtitle">
              {project ? '按片段检查卡片、音频和更多学习点，导出时只包含已选卡片。' : '先选择素材，再生成卡片；结果会在这里展开。'}
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
            <button className="ghost-button" type="button" onClick={onInvertCardSelection}>
              反选
            </button>
          </div>
        ) : null}
      </div>

      {project ? (
        <div className="review-view-tabs" aria-label="审核视图">
          <button
            type="button"
            className={reviewView === 'cards' ? 'selected' : ''}
            aria-pressed={reviewView === 'cards'}
            onClick={() => setReviewView('cards')}
          >
            可用卡片
          </button>
          <button
            type="button"
            className={reviewView === 'inventory' ? 'selected' : ''}
            aria-pressed={reviewView === 'inventory'}
            onClick={() => setReviewView('inventory')}
          >
            更多学习点
            <strong>{diagnosticInventory.length}</strong>
          </button>
        </div>
      ) : null}

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

      <AnimatePresence mode="wait">
        <motion.div
          key={project ? reviewView : 'empty'}
          className="review-view-body"
          initial={{ opacity: 0, y: prefersReducedMotion ? 0 : 5 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: prefersReducedMotion ? 0 : -3 }}
          transition={{ duration: prefersReducedMotion ? 0 : Math.min(motionDuration, 0.16), ease: 'easeOut' }}
        >
          {!project ? (
            <EmptyWorkbench
              level={level}
              maxSegments={maxSegments}
              sourceMode={sourceMode}
              templateLabel={activeTemplateLabel}
            />
          ) : reviewView === 'inventory' ? (
            <LearningPointInventoryPanel items={diagnosticInventory} />
          ) : (
            <div className="preview-layout">
              <SegmentList
                activeSegmentId={activeSegmentId}
                documentStudyMode={project.document_study_mode}
                motionDuration={motionDuration}
                prefersReducedMotion={prefersReducedMotion}
                segments={visibleSegments}
                onSelectSegment={onSelectSegment}
                onSetSegmentCardsEnabled={onSetCardsEnabled}
              />

              {activeSegment ? (
                <SegmentDetail
                  documentStudyMode={project.document_study_mode}
                  language={project.language || language}
                  motionDuration={motionDuration}
                  prefersReducedMotion={prefersReducedMotion}
                  previewRate={previewRate}
                  segment={activeSegment}
                  videoSrc={activeSegmentVideoSrc}
                  onSetSegmentCardsEnabled={onSetCardsEnabled}
                  onUpdateCard={onUpdateCard}
                />
              ) : null}
            </div>
          )}
        </motion.div>
      </AnimatePresence>
    </section>
  )
}

type InventoryKindFilter =
  | 'all'
  | 'expression'
  | 'contextual_vocab'
  | 'grammar_pattern'
  | 'listening_feature'
  | 'pragmatic_risk'

const inventoryKindFilters: Array<{ id: InventoryKindFilter; label: string }> = [
  { id: 'all', label: '全部' },
  { id: 'expression', label: '表达' },
  { id: 'contextual_vocab', label: '语境生词' },
  { id: 'grammar_pattern', label: '语法框架' },
  { id: 'listening_feature', label: '听力难点' },
  { id: 'pragmatic_risk', label: '语气 / 风险' },
]

function inventoryStatusLabel(status: LearningPointInventoryItem['status']) {
  if (status === 'candidate_only') return '候选'
  if (status === 'hidden_duplicate') return '重复折叠'
  if (status === 'hard_blocked') return '硬阻断'
  return '已制卡'
}

function inventoryReason(item: LearningPointInventoryItem) {
  return item.block_reason || item.filter_reason || item.reason || item.learning_action || '系统已记录该学习点，等待进一步取舍。'
}

function LearningPointInventoryPanel({
  items,
}: {
  items: LearningPointInventoryItem[]
}) {
  const [kindFilter, setKindFilter] = useState<InventoryKindFilter>('all')
  const filteredItems = useMemo(
    () => items.filter((item) => kindFilter === 'all' || item.candidate_kind === kindFilter),
    [items, kindFilter],
  )
  const counts = useMemo(
    () =>
      items.reduce<Record<InventoryKindFilter, number>>(
        (acc, item) => {
          acc.all += 1
          if (item.candidate_kind in acc) {
            acc[item.candidate_kind as InventoryKindFilter] += 1
          }
          return acc
        },
        {
          all: 0,
          expression: 0,
          contextual_vocab: 0,
          grammar_pattern: 0,
          listening_feature: 0,
          pragmatic_risk: 0,
        },
      ),
    [items],
  )

  return (
    <div className="learning-point-inventory" aria-label="更多学习点">
      <div className="inventory-header">
        <div>
          <strong>更多学习点</strong>
          <span>可直接学习的内容已经生成到“可用卡片”；这里说明为什么有些学习点没有制成卡片。</span>
        </div>
      </div>
      <div className="inventory-filters" aria-label="候选类型筛选">
        {inventoryKindFilters.map((filter) => (
          <button
            key={filter.id}
            type="button"
            className={kindFilter === filter.id ? 'selected' : ''}
            aria-pressed={kindFilter === filter.id}
            onClick={() => setKindFilter(filter.id)}
          >
            <span>{filter.label}</span>
            <strong>{counts[filter.id]}</strong>
          </button>
        ))}
      </div>
      <div className="inventory-list">
        {filteredItems.map((item) => (
          <article key={`${item.id}-${item.status}-${item.source_segment_id}`} className={`inventory-item status-${item.status}`}>
            <div className="inventory-item-top">
              <span>{item.source_time}</span>
              <em>{inventoryStatusLabel(item.status)}</em>
            </div>
            <div className="inventory-item-title">
              <strong>{item.answer_core || item.exact_span}</strong>
              <span className={`kind-chip kind-${item.candidate_kind}`}>{candidateKindLabel(item.candidate_kind)}</span>
              {item.phrase_type ? <span>{phraseTypeLabel(item.phrase_type) || item.phrase_type}</span> : null}
              {item.value_score ? <span>{item.value_score}/5</span> : null}
            </div>
            <p>{clipText(item.source_sentence, 180)}</p>
            <small>训练点：{item.learning_action}</small>
            <small>原因：{inventoryReason(item)}</small>
            <div className="inventory-item-actions">
              <span>硬阻断项不会导出；原因通常是 answer_core 异常、跨度不在原句中，或模型返回了不可制卡内容。</span>
            </div>
          </article>
        ))}
        {filteredItems.length === 0 ? (
          <div className="filter-empty-state">
            <strong>当前没有更多未制卡学习点</strong>
            <span>合法学习点已经自动生成到“可用卡片”，导出前可以在那里勾选或取消。</span>
          </div>
        ) : null}
      </div>
    </div>
  )
}
