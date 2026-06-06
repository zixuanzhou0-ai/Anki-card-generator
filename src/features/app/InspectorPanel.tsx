import { CheckCircle2, CircleDot, ClipboardCheck, Download, FileVideo2, SlidersHorizontal, X } from 'lucide-react'

import type {
  CardKind,
  ContentToggles,
  DocumentFocus,
  GenerateRequest,
  LanguageFocus,
  Level,
  SelectionStrategy,
  SourceMode,
  TemplateId,
  WorkerProgress,
  WorkspaceStage,
} from '../../domain/types'
import type { WorkerErrorAction, WorkerErrorActionId } from '../../domain/workerErrors'
import { CardTemplatePanel } from '../generation/CardTemplatePanel'
import { ReadinessPanel } from '../generation/ReadinessPanel'
import type { ReadinessItem } from '../generation/ReadinessPanel'
import { StatusPanel } from '../generation/StatusPanel'
import { WorkerProgressPanel } from '../generation/WorkerProgressPanel'
import { DocumentStudyPanel } from '../learning/DocumentStudyPanel'
import { LearningSettingsPanel } from '../learning/LearningSettingsPanel'
import { SourceSetupPanel } from '../source/SourceSetupPanel'

type LevelOption = {
  id: Level
  label: string
  note: string
}

type ContentOption = {
  key: keyof ContentToggles
  label: string
  defaultOn: boolean
}

type LanguageFocusOption = {
  id: LanguageFocus
  label: string
  note: string
  defaultOn: boolean
}

type SelectionStrategyOption = {
  id: SelectionStrategy
  label: string
  note: string
  badge: string
}

type DocumentFocusOption = {
  id: DocumentFocus
  label: string
  note: string
  defaultOn: boolean
}

type CardOption = {
  id: CardKind
  label: string
  note: string
}

type TemplateOption = {
  id: TemplateId
  label: string
  note: string
  locked?: boolean
}

type CollectionPreset = 'current' | 'below' | 'around'

type InspectorPanelProps = {
  activeWorkspaceStage: WorkspaceStage
  activeTemplateLabel: string
  appBusy: boolean
  cardOptions: CardOption[]
  cardTypes: CardKind[]
  contentOptions: ContentOption[]
  diagnosticCount: number
  documentFocusOptions: DocumentFocusOption[]
  generatedCardCount: number
  hasExportableCards: boolean
  hasProject: boolean
  inspectorSheetOpen: boolean
  languageFocusOptions: LanguageFocusOption[]
  levels: LevelOption[]
  previewRate: number
  readiness: ReadinessItem[]
  request: GenerateRequest
  requestEditedDuringRun: boolean
  selectedCardCount: number
  status: string
  statusTone: string
  templateId: TemplateId
  templateOptions: TemplateOption[]
  selectionStrategyOptions: SelectionStrategyOption[]
  workerBusy: boolean
  workerErrorActions: WorkerErrorAction[]
  workerProgress: WorkerProgress | null
  onApplyCollectionPreset: (preset: CollectionPreset) => void
  onCloseSheet: () => void
  onExport: () => void
  onPatchRequest: (patch: Partial<GenerateRequest>) => void
  onPreviewRateChange: (rate: number) => void
  onSelectCurrentLevel: (level: Level) => void
  onSelectPath: (kind: 'video' | 'subtitle' | 'document') => void
  onSelectSourceMode: (mode: SourceMode) => void
  onSelectTemplate: (templateId: TemplateId) => void
  onToggleCardType: (type: CardKind) => void
  onToggleCollectionLevel: (level: Level) => void
  onToggleContent: (key: keyof ContentToggles) => void
  onToggleDocumentFocus: (focus: DocumentFocus) => void
  onToggleLanguageFocus: (focus: LanguageFocus) => void
  onWorkspaceStageChange: (stage: WorkspaceStage) => void
  onWorkerErrorAction: (actionId: WorkerErrorActionId) => void
}

export function InspectorPanel({
  activeWorkspaceStage,
  activeTemplateLabel,
  appBusy,
  cardOptions,
  cardTypes,
  contentOptions,
  diagnosticCount,
  documentFocusOptions,
  generatedCardCount,
  hasExportableCards,
  hasProject,
  inspectorSheetOpen,
  languageFocusOptions,
  levels,
  previewRate,
  readiness,
  request,
  requestEditedDuringRun,
  selectedCardCount,
  status,
  statusTone,
  templateId,
  templateOptions,
  selectionStrategyOptions,
  workerBusy,
  workerErrorActions,
  workerProgress,
  onApplyCollectionPreset,
  onCloseSheet,
  onExport,
  onPatchRequest,
  onPreviewRateChange,
  onSelectCurrentLevel,
  onSelectPath,
  onSelectSourceMode,
  onSelectTemplate,
  onToggleCardType,
  onToggleCollectionLevel,
  onToggleContent,
  onToggleDocumentFocus,
  onToggleLanguageFocus,
  onWorkspaceStageChange,
  onWorkerErrorAction,
}: InspectorPanelProps) {
  const completedReadiness = readiness.filter((item) => item.done).length
  const sourceLabel =
    request.source_mode === 'document' ? '文档资料' : request.source_mode === 'url' ? '视频链接' : '本地视频'
  const levelSummary = request.level_mode === 'auto' ? '自动判断' : request.level
  const stageItems: Array<{
    id: WorkspaceStage
    label: string
    summary: string
    icon: typeof FileVideo2
    complete: boolean
  }> = [
    {
      id: 'source',
      label: '素材配置',
      summary: `${sourceLabel} · ${completedReadiness}/${readiness.length} 就绪`,
      icon: FileVideo2,
      complete: completedReadiness === readiness.length,
    },
    {
      id: 'generate',
      label: '生成设置',
      summary: hasProject
        ? `已生成 · ${generatedCardCount} 张`
        : workerProgress
          ? `${Math.round(workerProgress.percent)}% · ${workerProgress.message}`
          : `${levelSummary} · ${activeTemplateLabel}`,
      icon: SlidersHorizontal,
      complete: hasProject,
    },
    {
      id: 'review',
      label: '审核导出',
      summary: hasProject ? `${selectedCardCount}/${generatedCardCount} 张已选 · 更多 ${diagnosticCount}` : '生成后检查并导出',
      icon: ClipboardCheck,
      complete: hasProject && selectedCardCount > 0,
    },
  ]
  const stageTitle = stageItems.find((item) => item.id === activeWorkspaceStage)?.label ?? '素材配置'

  return (
    <aside className={`control-column ${inspectorSheetOpen ? 'sheet-open' : ''}`} aria-label="制卡流程控制台">
      <div className="compact-inspector-head">
        <div>
          <span>流程控制台</span>
          <strong>{stageTitle}</strong>
        </div>
        <button type="button" className="icon-button" onClick={onCloseSheet} aria-label="关闭素材设置">
          <X size={18} />
        </button>
      </div>

      <section className="panel workflow-panel" aria-label="制卡流程">
        <div className="workflow-panel-head">
          <span>制卡流程</span>
          <strong>{stageTitle}</strong>
        </div>
        <div className="workflow-stage-nav" role="tablist" aria-label="工作阶段">
          {stageItems.map((item, index) => {
            const Icon = item.icon
            const selected = item.id === activeWorkspaceStage
            return (
              <button
                key={item.id}
                type="button"
                className={`workflow-stage-button ${selected ? 'selected' : ''}`}
                role="tab"
                aria-selected={selected}
                onClick={() => onWorkspaceStageChange(item.id)}
              >
                <span className="workflow-stage-index">{index + 1}</span>
                <Icon size={17} />
                <span className="workflow-stage-copy">
                  <strong>{item.label}</strong>
                  <small>{item.summary}</small>
                </span>
                {item.complete ? (
                  <CheckCircle2 className="workflow-stage-check complete" size={17} aria-hidden="true" />
                ) : selected ? (
                  <CircleDot className="workflow-stage-check current" size={17} aria-hidden="true" />
                ) : null}
              </button>
            )
          })}
        </div>
      </section>

      <section className="workflow-stage-body" aria-label={stageTitle}>
        {activeWorkspaceStage === 'source' ? (
          <>
            <ReadinessPanel items={readiness} />
            <SourceSetupPanel
              request={request}
              onPatchRequest={onPatchRequest}
              onSelectPath={onSelectPath}
              onSelectSourceMode={onSelectSourceMode}
            />
            <div className="workflow-stage-actions">
              <button type="button" className="primary-button" onClick={() => onWorkspaceStageChange('generate')}>
                <SlidersHorizontal size={18} />
                下一步：生成设置
              </button>
            </div>
          </>
        ) : null}

        {activeWorkspaceStage === 'generate' ? (
          <>
            <StatusPanel
              appBusy={appBusy}
              requestEditedDuringRun={requestEditedDuringRun}
              status={status}
              statusTone={statusTone}
              workerBusy={workerBusy}
              workerErrorActions={workerErrorActions}
              onWorkerErrorAction={onWorkerErrorAction}
            />
            {workerProgress ? <WorkerProgressPanel progress={workerProgress} /> : null}
            {request.source_mode === 'document' ? (
              <DocumentStudyPanel
                documentFocusOptions={documentFocusOptions}
                languageFocusOptions={languageFocusOptions}
                levels={levels}
                request={request}
                onPatchRequest={onPatchRequest}
                onSelectCurrentLevel={onSelectCurrentLevel}
                onToggleDocumentFocus={onToggleDocumentFocus}
                onToggleLanguageFocus={onToggleLanguageFocus}
              />
            ) : (
              <LearningSettingsPanel
                contentOptions={contentOptions}
                languageFocusOptions={languageFocusOptions}
                levels={levels}
                previewRate={previewRate}
                request={request}
                selectionStrategyOptions={selectionStrategyOptions}
                onApplyCollectionPreset={onApplyCollectionPreset}
                onPatchRequest={onPatchRequest}
                onPreviewRateChange={onPreviewRateChange}
                onSelectCurrentLevel={onSelectCurrentLevel}
                onToggleCollectionLevel={onToggleCollectionLevel}
                onToggleContent={onToggleContent}
                onToggleLanguageFocus={onToggleLanguageFocus}
              />
            )}
            <CardTemplatePanel
              activeTemplateLabel={activeTemplateLabel}
              cardOptions={cardOptions}
              cardTypes={cardTypes}
              documentStudyMode={request.document_study_mode}
              sourceMode={request.source_mode}
              templateId={templateId}
              templateOptions={templateOptions}
              onSelectTemplate={onSelectTemplate}
              onToggleCardType={onToggleCardType}
            />
          </>
        ) : null}

        {activeWorkspaceStage === 'review' ? (
          <>
            <StatusPanel
              appBusy={appBusy}
              requestEditedDuringRun={requestEditedDuringRun}
              status={status}
              statusTone={statusTone}
              workerBusy={workerBusy}
              workerErrorActions={workerErrorActions}
              onWorkerErrorAction={onWorkerErrorAction}
            />
            {workerProgress ? <WorkerProgressPanel progress={workerProgress} /> : null}
            <div className="panel workflow-review-card">
              <div className="workflow-review-title">
                <span>审核导出</span>
                <strong>{hasProject ? '检查卡片后导出 APKG' : '生成后进入审核'}</strong>
              </div>
              <div className="workflow-review-compact" aria-label="审核阶段摘要">
                <strong>{selectedCardCount}/{generatedCardCount}</strong>
                <span>张已选导出</span>
                <small>{diagnosticCount > 0 ? `更多学习点 ${diagnosticCount}` : '暂无未制卡学习点'}</small>
              </div>
              <div className="workflow-stage-actions split">
                <button type="button" className="ghost-button" onClick={() => onWorkspaceStageChange('generate')}>
                  <SlidersHorizontal size={18} />
                  调整生成
                </button>
                <button type="button" className="primary-button" onClick={onExport} disabled={appBusy || !hasExportableCards}>
                  <Download size={18} />
                  导出已选
                </button>
              </div>
            </div>
          </>
        ) : null}
      </section>
    </aside>
  )
}
