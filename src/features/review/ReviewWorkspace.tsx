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
  WorkerProgress,
  WorkerFinishedEvent,
} from '../../domain/types'
import type {
  GenerationQueueSummary,
  LearningPointExtractionResult,
  LearningPointItem,
} from '../../domain/learningPoints'
import type { QualityCounts, QualityDiagnostics } from '../../domain/projectMetrics'
import { candidateKindLabel, clipText, phraseTypeLabel } from '../../domain/quality'
import { WorkerProgressPanel } from '../generation/WorkerProgressPanel'
import { LearningPointOverview } from '../learningPoints/LearningPointOverview'
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
  lastWorkerError?: WorkerFinishedEvent | null
  language: string
  level: Level
  learningPointResult: LearningPointExtractionResult | null
  motionDuration: number
  prefersReducedMotion: boolean
  previewPanelRef: RefObject<HTMLElement | null>
  previewRate: number
  project: Project | null
  qualityCounts: QualityCounts
  qualityDiagnostics: QualityDiagnostics
  qualityFunnel: QualityFunnel
  selectedCardCount: number
  selectedLearningPointIds: Set<string>
  generationConfirmOpen: boolean
  generationQueuePoints: LearningPointItem[]
  generationQueueSummary: GenerationQueueSummary
  segmentFilter: SegmentFilter
  segmentReviewCounts: SegmentReviewCounts
  sourceMode: SourceMode
  templateId: string
  visibleSegments: Segment[]
  workerBusy: boolean
  workerProgress: WorkerProgress | null
  status: string
  onOpenAnkiImport: () => void
  onRevealExport: () => void
  onSegmentFilterChange: (filter: SegmentFilter) => void
  onCloseGenerationConfirm: () => void
  onConfirmGenerateCardsFromLearningPoints: () => void
  onExport: () => void
  onExtractLearningPointsWithoutCache: () => void
  onGenerateCardsFromLearningPoints: () => void
  onGenerateSingleLearningPoint: (pointId: string) => void
  onInvertCardSelection: () => void
  onRemoveGenerationQueueLearningPoint: (pointId: string) => void
  onRetryMissingLearningPoints: () => void
  onSelectSegment: (segmentId: string) => void
  onSetCardsEnabled: (enabled: boolean, segmentId?: string) => void
  onSetSelectedLearningPointIds: (ids: Set<string>) => void
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
  lastWorkerError,
  language,
  level,
  learningPointResult,
  motionDuration,
  prefersReducedMotion,
  previewPanelRef,
  previewRate,
  project,
  qualityCounts,
  qualityDiagnostics,
  qualityFunnel,
  selectedCardCount,
  selectedLearningPointIds,
  generationConfirmOpen,
  generationQueuePoints,
  generationQueueSummary,
  segmentFilter,
  segmentReviewCounts,
  sourceMode,
  templateId,
  visibleSegments,
  workerBusy,
  workerProgress,
  status,
  onOpenAnkiImport,
  onRevealExport,
  onSegmentFilterChange,
  onCloseGenerationConfirm,
  onConfirmGenerateCardsFromLearningPoints,
  onExport,
  onExtractLearningPointsWithoutCache,
  onGenerateCardsFromLearningPoints,
  onGenerateSingleLearningPoint,
  onInvertCardSelection,
  onRemoveGenerationQueueLearningPoint,
  onRetryMissingLearningPoints,
  onSelectSegment,
  onSetCardsEnabled,
  onSetSelectedLearningPointIds,
  onUpdateCard,
  onVerifyAnkiImport,
}: ReviewWorkspaceProps) {
  const [reviewView, setReviewView] = useState<'cards' | 'inventory'>('cards')
  const [showAdvancedReview, setShowAdvancedReview] = useState(false)
  const [showSegmentDetail, setShowSegmentDetail] = useState(false)
  const showProgressWorkbench = Boolean(
    !project && workerProgress && (workerBusy || workerProgress.stage === 'select_output_dir'),
  )
  const inventory = project?.learning_point_inventory ?? []
  const diagnosticInventory = inventory.filter((item) => item.status !== 'card_generated')
  const generatedCardCount = project?.segments.reduce((total, segment) => total + segment.cards.length, 0) ?? 0
  const generationDiagnostics = project?.card_generation_diagnostics
  const missingGenerationCount = generationDiagnostics?.missing_learning_point_count ?? 0
  const showExportFailureNotice = Boolean(
    lastWorkerError?.command === 'export' &&
      !lastWorkerError.ok &&
      (project || lastWorkerError.error_code === 'RELEASE_APKG_TARGET_INVALID'),
  )
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
            <h3 id="preview-title">
              {workerBusy && !project
                ? '生成中'
                : project
                  ? '审核导出'
                  : learningPointResult
                    ? '学习点总览'
                    : '生成工作台'}
            </h3>
            <p className="panel-subtitle">
              {workerBusy && !project
                ? '正在按当前素材和学习设置处理字幕，完成后会自动进入下一步。'
                : project
                  ? '确认要导出的学习卡；这里只能选择可导出项，导出时仍会执行媒体、TTS 和字段核验。'
                  : learningPointResult
                    ? 'AI 已精筛学习点；默认先选推荐项，也可以全选可制卡项。'
                    : '先选择素材，再抽取学习点；结果会在这里展开。'}
            </p>
          </div>
        </div>
        {project ? (
          <div className="preview-actions">
            <button className="ghost-button" type="button" onClick={() => onSetCardsEnabled(true)}>
              全选可导出
            </button>
            <button className="ghost-button" type="button" onClick={() => onSetCardsEnabled(false)}>
              全不选
            </button>
            <button className="ghost-button" type="button" onClick={onInvertCardSelection}>
              反选可导出
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
            可导出卡片
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

      {project && workerProgress ? (
        <div className="review-task-progress" aria-live="polite">
          <WorkerProgressPanel progress={workerProgress} />
        </div>
      ) : null}

      {showExportFailureNotice && lastWorkerError ? (
        <ExportFailureNotice error={lastWorkerError} workerBusy={workerBusy} onRetryExport={onExport} />
      ) : null}

      {project && missingGenerationCount > 0 ? (
        <PartialGenerationNotice
          diagnostics={generationDiagnostics}
          exportableCount={qualityCounts.recommended}
          workerBusy={workerBusy}
          onExport={onExport}
          onRetryMissing={onRetryMissingLearningPoints}
          onReviewInventory={() => setReviewView('inventory')}
        />
      ) : null}

      {project ? (
        <div className="review-simple-summary" aria-label="卡片概览">
          <span>
            <strong>{selectedCardCount}</strong>
            <small>已选卡片</small>
          </span>
          <span>
            <strong>{qualityCounts.recommended}</strong>
            <small>可导出</small>
          </span>
          <span>
            <strong>{generatedCardCount}</strong>
            <small>生成总数</small>
          </span>
          <button
            className="ghost-button"
            type="button"
            onClick={() => setShowSegmentDetail((current) => !current)}
            disabled={!activeSegment}
          >
            {showSegmentDetail ? '收起详情' : '查看选中卡'}
          </button>
          <button className="ghost-button" type="button" onClick={() => setShowAdvancedReview((current) => !current)}>
            {showAdvancedReview ? '收起诊断' : '高级诊断'}
          </button>
          <button
            className="ghost-button"
            type="button"
            onClick={onExtractLearningPointsWithoutCache}
            disabled={workerBusy}
          >
            不使用缓存重新抽取
          </button>
        </div>
      ) : null}

      {project && showAdvancedReview ? (
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

      {project && lastExport ? (
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
          key={
            project
              ? reviewView
              : showProgressWorkbench
                ? 'generating'
                : learningPointResult
                  ? 'learning-points'
                  : 'empty'
          }
          className="review-view-body"
          initial={{ opacity: 0, y: prefersReducedMotion ? 0 : 5 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: prefersReducedMotion ? 0 : -3 }}
          transition={{ duration: prefersReducedMotion ? 0 : Math.min(motionDuration, 0.16), ease: 'easeOut' }}
        >
          {showProgressWorkbench && workerProgress ? (
            <GenerationProgressWorkbench progress={workerProgress} status={status} />
          ) : !project && learningPointResult ? (
            <LearningPointOverview
              result={learningPointResult}
              selectedIds={selectedLearningPointIds}
              workerBusy={workerBusy}
              generationConfirmOpen={generationConfirmOpen}
              generationQueuePoints={generationQueuePoints}
              generationQueueSummary={generationQueueSummary}
              onCloseGenerationConfirm={onCloseGenerationConfirm}
              onConfirmGenerateCards={onConfirmGenerateCardsFromLearningPoints}
              onExtractWithoutCache={onExtractLearningPointsWithoutCache}
              onGenerateCards={onGenerateCardsFromLearningPoints}
              onGenerateSinglePoint={onGenerateSingleLearningPoint}
              onRemoveGenerationQueuePoint={onRemoveGenerationQueueLearningPoint}
              onSetSelectedIds={onSetSelectedLearningPointIds}
            />
          ) : !project ? (
            <EmptyWorkbench level={level} sourceMode={sourceMode} templateLabel={activeTemplateLabel} />
          ) : reviewView === 'inventory' ? (
            <LearningPointInventoryPanel items={diagnosticInventory} />
          ) : (
            <div className={`preview-layout ${showSegmentDetail ? 'show-detail' : 'list-only'}`}>
              <SegmentList
                activeSegmentId={activeSegmentId}
                documentStudyMode={project.document_study_mode}
                motionDuration={motionDuration}
                prefersReducedMotion={prefersReducedMotion}
                segments={visibleSegments}
                onSelectSegment={onSelectSegment}
                onSetSegmentCardsEnabled={onSetCardsEnabled}
              />

              {showSegmentDetail && activeSegment ? (
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

function PartialGenerationNotice({
  diagnostics,
  exportableCount,
  workerBusy,
  onExport,
  onRetryMissing,
  onReviewInventory,
}: {
  diagnostics: Project['card_generation_diagnostics']
  exportableCount: number
  workerBusy: boolean
  onExport: () => void
  onRetryMissing: () => void
  onReviewInventory: () => void
}) {
  const processed = diagnostics?.processed_learning_point_count ?? diagnostics?.selected_learning_point_count ?? 0
  const generated = diagnostics?.generated_card_count ?? diagnostics?.successful_learning_point_count ?? 0
  const missing = diagnostics?.missing_learning_point_count ?? 0
  const items = diagnostics?.items ?? []
  const reasonCounts = items.reduce<Record<string, number>>((acc, item) => {
    const status =
      item.status === 'model_missing' || item.status === 'hard_failed'
        ? '硬失败'
        : item.status === 'fallback_from_selected_learning_point'
          ? '保底生成'
          : item.status === 'ai_repaired'
            ? '字段补齐'
            : item.status === 'filtered'
              ? '质量过滤'
              : item.status === 'skipped'
                ? '不可制卡跳过'
                : item.status || '其他'
    acc[status] = (acc[status] ?? 0) + 1
    return acc
  }, {})
  return (
    <details className="partial-generation-notice" open>
      <summary>
        <div>
          <strong>
            已选 {processed} 个学习点，成功生成 {generated} 张学习卡；{missing} 个未生成
          </strong>
          <span>
            {Object.entries(reasonCounts)
              .map(([label, count]) => `${label} ${count}`)
              .join(' · ') || '部分学习点没有生成可导出的学习卡。'}
          </span>
        </div>
        <em>查看原因</em>
      </summary>
      <div className="partial-generation-actions">
        <button
          className="primary-button"
          type="button"
          onClick={onRetryMissing}
          disabled={workerBusy || missing === 0}
        >
          重试失败项 {missing} 个
        </button>
        <button
          className="ghost-button"
          type="button"
          onClick={onExport}
          disabled={workerBusy || exportableCount === 0}
        >
          继续导出 {exportableCount} 张
        </button>
        <button className="ghost-button" type="button" onClick={onReviewInventory} disabled={workerBusy}>
          返回学习点调整
        </button>
      </div>
      {items.length ? (
        <ul>
          {items.slice(0, 50).map((item) => (
            <li key={`${item.learning_point_id}-${item.status}-${item.reason}`}>
              <strong>{item.answer_core || item.learning_point_id}</strong>
              <small>{item.reason}</small>
            </li>
          ))}
        </ul>
      ) : null}
      {items.length > 50 ? <small>还有 {items.length - 50} 个未显示；完整清单保存在生成诊断中。</small> : null}
    </details>
  )
}

function ttsRoleLabel(role: string) {
  if (role === 'sentence_tts') return '整句 TTS'
  if (role === 'phrase_tts') return '表达 TTS'
  return role || 'TTS'
}

function friendlyTtsFailureMessage(record: Record<string, unknown>) {
  const raw = String(record.http_error || record.error || '')
  if (/INVALID_ARGUMENT|invalid argument/i.test(raw)) {
    return 'TTS 服务拒绝了这段文本，系统已重试但仍未生成音频。'
  }
  if (/quota|rate limit|resource exhausted/i.test(raw)) {
    return 'TTS 服务限流或额度不足，稍后重试通常可以恢复。'
  }
  if (/timeout|timed out|deadline/i.test(raw)) {
    return 'TTS 服务超时，建议重试失败音频。'
  }
  if (/unauthorized|permission|forbidden|401|403/i.test(raw)) {
    return 'TTS 授权或权限检查失败，请检查语音配置。'
  }
  return raw ? 'TTS provider 没有返回可用音频，建议重试。' : 'TTS provider 没有返回可用音频。'
}

function ExportFailureNotice({
  error,
  workerBusy,
  onRetryExport,
}: {
  error: WorkerFinishedEvent
  workerBusy: boolean
  onRetryExport: () => void
}) {
  const details = error.details ?? {}
  const blockedCards = Array.isArray(details.blocked_cards) ? details.blocked_cards : []
  const ttsFailureItems = Array.isArray(details.tts_failure_items) ? details.tts_failure_items : []
  const ttsFailureCount = Number(details.tts_failure_count || ttsFailureItems.length || 0)
  const isMissingTts = error.error_code === 'MISSING_TTS_MEDIA' || ttsFailureItems.length > 0
  const sentenceGenerated = Number(details.sentence_tts_generated ?? 0)
  const sentenceRequested = Number(details.sentence_tts_requested ?? 0)
  const phraseGenerated = Number(details.phrase_tts_generated ?? 0)
  const phraseRequested = Number(details.phrase_tts_requested ?? 0)
  return (
    <div className="export-failure-notice" role="alert" aria-label="导出失败详情">
      <div>
        <strong>{isMissingTts ? 'TTS 生成失败，未生成 APKG' : '导出没有生成 APKG'}</strong>
        <span>
          {isMissingTts
            ? `${ttsFailureCount || '部分'} 条 TTS 生成失败，因此没有生成 APKG。已生成的卡片仍保留，可重试失败音频。`
            : error.error || '导出前质量审计未通过。'}
          {error.error_code ? ` 错误码：${error.error_code}` : ''}
          {error.stage ? `；阶段：${error.stage}` : ''}
        </span>
      </div>
      {isMissingTts ? (
        <div className="export-failure-actions">
          <button className="primary-button" type="button" onClick={onRetryExport} disabled={workerBusy}>
            重试失败 TTS 并导出
          </button>
          <span>
            整句 TTS {sentenceGenerated}/{sentenceRequested}
            {phraseRequested ? ` · 表达 TTS ${phraseGenerated}/${phraseRequested}` : ''}
          </span>
        </div>
      ) : null}
      {ttsFailureItems.length ? (
        <ul>
          {ttsFailureItems.slice(0, 8).map((item, index) => {
            const record = item && typeof item === 'object' ? (item as Record<string, unknown>) : {}
            const title = String(
              record.answer || record.expected_text || record.learning_point_id || `TTS 失败 ${index + 1}`,
            )
            const role = ttsRoleLabel(String(record.role || ''))
            const sourceTime = String(record.source_time || record.segment_id || '')
            const message = friendlyTtsFailureMessage(record)
            return (
              <li key={`${String(record.segment_id || record.key || index)}-${role}-${index}`}>
                <strong>{title}</strong>
                <small>{[sourceTime, role, message].filter(Boolean).join(' · ')}</small>
              </li>
            )
          })}
        </ul>
      ) : null}
      {blockedCards.length ? (
        <ul>
          {blockedCards.slice(0, 6).map((item, index) => {
            const record = item && typeof item === 'object' ? (item as Record<string, unknown>) : {}
            const title = String(record.title || record.answer_summary || record.card_id || `坏卡 ${index + 1}`)
            const sourceTime = String(record.source_time || record.segment_id || '')
            const matchedText = String(record.matched_text || '')
            const action = String(record.suggested_action || '请移除这张卡，或重新生成/手动修正后再导出。')
            return (
              <li key={`${String(record.card_id || index)}-${index}`}>
                <strong>{title}</strong>
                <small>
                  {[sourceTime, matchedText ? `命中：${matchedText}` : '', action].filter(Boolean).join(' · ')}
                </small>
              </li>
            )
          })}
        </ul>
      ) : null}
    </div>
  )
}

function GenerationProgressWorkbench({ progress, status }: { progress: WorkerProgress; status: string }) {
  const isExtracting = progress.command === 'extract_learning_points'
  const isExporting = progress.command === 'export'
  const isSelectingOutputDir = progress.stage === 'select_output_dir'
  const stepLabel = isSelectingOutputDir ? '准备中' : isExporting ? '正在打包' : isExtracting ? '正在筛选' : '正在生成'
  return (
    <div className="generation-progress-workbench" aria-label="生成进度">
      <div className="generation-progress-hero">
        <span className="hero-kicker">{stepLabel}</span>
        <h2>
          {isSelectingOutputDir
            ? '正在准备 APKG'
            : isExporting
              ? '正在打包 APKG'
              : isExtracting
                ? '正在抽取学习点'
                : '正在生成 APKG'}
        </h2>
        <p>{status}</p>
      </div>
      <WorkerProgressPanel progress={progress} variant="wide" />
      <div className="generation-progress-steps" aria-label="生成阶段说明">
        <span>
          <strong>素材已确认</strong>
          <small>视频和字幕会按当前配置处理。</small>
        </span>
        <span>
          <strong>设置已锁定</strong>
          <small>生成期间不会再打开学习设置，避免参数混乱。</small>
        </span>
        <span>
          <strong>下一步</strong>
          <small>
            {isExtracting
              ? '学习点清单完成后，你可以先筛选再生成 APKG。'
              : isExporting
                ? '导出完成后可以打开 Anki 或核验媒体。'
                : '正文完成后会自动生成音频、切片并打包 APKG。'}
          </small>
        </span>
      </div>
    </div>
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
  return (
    item.block_reason ||
    item.filter_reason ||
    item.reason ||
    item.learning_action ||
    '系统已记录该学习点，等待进一步取舍。'
  )
}

function LearningPointInventoryPanel({ items }: { items: LearningPointInventoryItem[] }) {
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
          <span>可直接学习的内容已经生成到“可导出卡片”；这里说明为什么有些学习点没有制成卡片。</span>
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
          <article
            key={`${item.id}-${item.status}-${item.source_segment_id}`}
            className={`inventory-item status-${item.status}`}
          >
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
              <span>不可制卡项不会导出；原因通常是 answer_core 异常、跨度不在原句中，或模型返回了不适合直接制卡的内容。</span>
            </div>
          </article>
        ))}
        {filteredItems.length === 0 ? (
          <div className="filter-empty-state">
            <strong>当前没有更多未制卡学习点</strong>
            <span>合法学习点已经自动生成到“可导出卡片”，导出前可以在那里选择或取消。</span>
          </div>
        ) : null}
      </div>
    </div>
  )
}
