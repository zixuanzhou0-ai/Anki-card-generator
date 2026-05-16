import { X } from 'lucide-react'

import type {
  CardKind,
  ContentToggles,
  DocumentFocus,
  GenerateRequest,
  LanguageFocus,
  Level,
  SourceMode,
  TemplateId,
  WorkerProgress,
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
  activeTemplateLabel: string
  appBusy: boolean
  cardOptions: CardOption[]
  cardTypes: CardKind[]
  contentOptions: ContentOption[]
  documentFocusOptions: DocumentFocusOption[]
  inspectorSheetOpen: boolean
  languageFocusOptions: LanguageFocusOption[]
  levels: LevelOption[]
  readiness: ReadinessItem[]
  request: GenerateRequest
  requestEditedDuringRun: boolean
  status: string
  statusTone: string
  templateId: TemplateId
  templateOptions: TemplateOption[]
  workerBusy: boolean
  workerErrorActions: WorkerErrorAction[]
  workerProgress: WorkerProgress | null
  onApplyCollectionPreset: (preset: CollectionPreset) => void
  onCloseSheet: () => void
  onPatchRequest: (patch: Partial<GenerateRequest>) => void
  onSelectCurrentLevel: (level: Level) => void
  onSelectPath: (kind: 'video' | 'subtitle' | 'document') => void
  onSelectSourceMode: (mode: SourceMode) => void
  onSelectTemplate: (templateId: TemplateId) => void
  onToggleCardType: (type: CardKind) => void
  onToggleCollectionLevel: (level: Level) => void
  onToggleContent: (key: keyof ContentToggles) => void
  onToggleDocumentFocus: (focus: DocumentFocus) => void
  onToggleLanguageFocus: (focus: LanguageFocus) => void
  onWorkerErrorAction: (actionId: WorkerErrorActionId) => void
}

export function InspectorPanel({
  activeTemplateLabel,
  appBusy,
  cardOptions,
  cardTypes,
  contentOptions,
  documentFocusOptions,
  inspectorSheetOpen,
  languageFocusOptions,
  levels,
  readiness,
  request,
  requestEditedDuringRun,
  status,
  statusTone,
  templateId,
  templateOptions,
  workerBusy,
  workerErrorActions,
  workerProgress,
  onApplyCollectionPreset,
  onCloseSheet,
  onPatchRequest,
  onSelectCurrentLevel,
  onSelectPath,
  onSelectSourceMode,
  onSelectTemplate,
  onToggleCardType,
  onToggleCollectionLevel,
  onToggleContent,
  onToggleDocumentFocus,
  onToggleLanguageFocus,
  onWorkerErrorAction,
}: InspectorPanelProps) {
  return (
    <aside className={`control-column ${inspectorSheetOpen ? 'sheet-open' : ''}`} aria-label="素材和生成设置">
      <div className="compact-inspector-head">
        <div>
          <span>素材设置</span>
          <strong>生成前配置</strong>
        </div>
        <button type="button" className="icon-button" onClick={onCloseSheet} aria-label="关闭素材设置">
          <X size={18} />
        </button>
      </div>
      <ReadinessPanel items={readiness} />

      {workerProgress ? <WorkerProgressPanel progress={workerProgress} /> : null}

      <StatusPanel
        appBusy={appBusy}
        requestEditedDuringRun={requestEditedDuringRun}
        status={status}
        statusTone={statusTone}
        workerBusy={workerBusy}
        workerErrorActions={workerErrorActions}
        onWorkerErrorAction={onWorkerErrorAction}
      />

      <section className="setup-grid">
        <SourceSetupPanel
          request={request}
          onPatchRequest={onPatchRequest}
          onSelectPath={onSelectPath}
          onSelectSourceMode={onSelectSourceMode}
        />

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
            request={request}
            onApplyCollectionPreset={onApplyCollectionPreset}
            onPatchRequest={onPatchRequest}
            onSelectCurrentLevel={onSelectCurrentLevel}
            onToggleCollectionLevel={onToggleCollectionLevel}
            onToggleContent={onToggleContent}
            onToggleLanguageFocus={onToggleLanguageFocus}
          />
        )}
      </section>

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
    </aside>
  )
}
