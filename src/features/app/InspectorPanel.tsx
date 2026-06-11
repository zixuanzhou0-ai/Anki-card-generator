import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  CircleDot,
  ClipboardCheck,
  Download,
  FileVideo2,
  PlayCircle,
  SlidersHorizontal,
  X,
} from 'lucide-react'

import type {
  ContentToggles,
  DocumentFocus,
  EnvRepairTarget,
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
import { batchItemsForSource } from '../../domain/batch'
import { sourceRequirementMessage } from '../../domain/sourceValidation'
import { CardTemplatePanel } from '../generation/CardTemplatePanel'
import { ReadinessPanel } from '../generation/ReadinessPanel'
import type { ReadinessItem } from '../generation/ReadinessPanel'
import { StatusPanel } from '../generation/StatusPanel'
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
  contentOptions: ContentOption[]
  diagnosticCount: number
  documentFocusOptions: DocumentFocusOption[]
  generatedCardCount: number
  hasExportableCards: boolean
  hasLearningPointResult: boolean
  hasProject: boolean
  inspectorSheetOpen: boolean
  languageFocusOptions: LanguageFocusOption[]
  levels: LevelOption[]
  previewRate: number
  readiness: ReadinessItem[]
  request: GenerateRequest
  requestEditedDuringRun: boolean
  selectedCardCount: number
  selectedLearningPointCount: number
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
  onCheckEnv: () => void
  onExport: () => void
  onGenerate: () => void
  onOpenEnvSettings: () => void
  onPatchRequest: (patch: Partial<GenerateRequest>) => void
  onPreviewRateChange: (rate: number) => void
  onRepairEnv: (target: EnvRepairTarget) => void
  onSelectCurrentLevel: (level: Level) => void
  onSelectPath: (kind: 'video' | 'subtitle' | 'document' | 'video-folder' | 'document-folder') => void
  onSelectSourceMode: (mode: SourceMode) => void
  onSelectTemplate: (templateId: TemplateId) => void
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
  contentOptions,
  diagnosticCount,
  documentFocusOptions,
  generatedCardCount,
  hasExportableCards,
  hasLearningPointResult,
  hasProject,
  inspectorSheetOpen,
  languageFocusOptions,
  levels,
  previewRate,
  readiness,
  request,
  requestEditedDuringRun,
  selectedCardCount,
  selectedLearningPointCount,
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
  onCheckEnv,
  onExport,
  onGenerate,
  onOpenEnvSettings,
  onPatchRequest,
  onPreviewRateChange,
  onRepairEnv,
  onSelectCurrentLevel,
  onSelectPath,
  onSelectSourceMode,
  onSelectTemplate,
  onToggleCollectionLevel,
  onToggleContent,
  onToggleDocumentFocus,
  onToggleLanguageFocus,
  onWorkspaceStageChange,
  onWorkerErrorAction,
}: InspectorPanelProps) {
  const sourceReady = readiness.find((item) => item.id === 'source')?.done ?? false
  const extractionReadinessIds = new Set(['source', 'env', 'api'])
  const cardGenerationReadinessIds = new Set(['source', 'env', 'api'])
  const incompleteReadiness = readiness.filter((item) => {
    if (hasProject) return !item.done
    if (hasLearningPointResult) return cardGenerationReadinessIds.has(item.id) && !item.done
    return extractionReadinessIds.has(item.id) && !item.done
  })
  const envPreflight = incompleteReadiness.find((item) => item.id === 'env')
  const envUnchecked = envPreflight?.detail === '未检查'
  const showEnvRepair = Boolean(envPreflight && !envUnchecked)
  const activeBatchItems = request.batch_enabled ? batchItemsForSource(request.batch_items ?? [], request.source_mode) : []
  const batchSubdeckSummary = `${activeBatchItems.length} 个子牌组`
  const batchPackageTitle = request.title.trim() || '未命名学习包'
  const sourceLabel = request.batch_enabled
    ? '批量学习包'
    : request.source_mode === 'document'
      ? '文档资料'
      : request.source_mode === 'url'
        ? '视频链接'
        : '本地视频'
  const sourceStageSummary = request.batch_enabled
    ? activeBatchItems.length
      ? `${batchPackageTitle} · ${batchSubdeckSummary}`
      : '先添加批量素材'
    : sourceReady
      ? `${sourceLabel}已就绪`
      : `先选择${sourceLabel}`
  const levelSummary = request.level_mode === 'auto' ? '自动判断' : request.level
  const runningCommand = workerProgress?.command
  const workerStageLabel = runningCommand === 'extract_learning_points' ? '抽取中' : '生成中'
  const reviewStageLabel = workerBusy && !hasProject ? workerStageLabel : hasProject ? '审核导出' : hasLearningPointResult ? '生成卡片' : '确认抽取'
  const reviewStageSummary =
    workerBusy && !hasProject
      ? `${Math.round(workerProgress?.percent ?? 0)}% · 进度在右侧`
      : hasProject
        ? `将导出 ${selectedCardCount} 张`
        : hasLearningPointResult
          ? `已选 ${selectedLearningPointCount} 个学习点`
          : '确认后抽取学习点'
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
      summary: sourceStageSummary,
      icon: FileVideo2,
      complete: sourceReady,
    },
    {
      id: 'generate',
      label: '学习设置',
      summary: workerBusy && !hasProject ? '设置已锁定' : hasProject ? `已生成 · ${generatedCardCount} 张` : `${levelSummary} · ${activeTemplateLabel}`,
      icon: SlidersHorizontal,
      complete: activeWorkspaceStage === 'review' || hasProject || workerBusy,
    },
    {
      id: 'review',
      label: reviewStageLabel,
      summary: reviewStageSummary,
      icon: ClipboardCheck,
      complete: hasProject && selectedCardCount > 0,
    },
  ]
  const stageTitle = stageItems.find((item) => item.id === activeWorkspaceStage)?.label ?? '素材配置'
  const activeStageIndex = Math.max(0, stageItems.findIndex((item) => item.id === activeWorkspaceStage))
  const canEnterStage = (stage: WorkspaceStage) => {
    if (workerBusy) return stage === 'review'
    if (stage === 'source') return true
    if (stage === 'generate') return sourceReady || activeWorkspaceStage !== 'source' || hasProject
    if (stage === 'review') return hasProject || activeWorkspaceStage === 'generate' || activeWorkspaceStage === 'review' || workerBusy
    return false
  }
  const goToGenerateSettings = () => {
    if (!workerBusy && (sourceReady || activeWorkspaceStage !== 'source')) onWorkspaceStageChange('generate')
  }
  const goToConfirmGenerate = () => {
    if (!workerBusy) onWorkspaceStageChange('review')
  }
  const sourceActionLabel = sourceReady ? '下一步：学习设置' : '选择素材后继续'
  const sourceActionNote = sourceRequirementMessage(request)

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
        <ol className="workflow-stepper" aria-label="制卡步骤">
          {stageItems.map((item, index) => {
            const Icon = item.icon
            const selected = item.id === activeWorkspaceStage
            const available = canEnterStage(item.id)
            const locked = !available
            const past = index < activeStageIndex || item.complete
            return (
              <li
                key={item.id}
                className={`workflow-step ${selected ? 'selected' : ''} ${past ? 'complete' : ''} ${locked ? 'locked' : ''}`}
              >
                <button
                  type="button"
                  className="workflow-stage-button"
                  aria-current={selected ? 'step' : undefined}
                  aria-disabled={locked}
                  disabled={locked}
                  onClick={() => {
                    if (available) onWorkspaceStageChange(item.id)
                  }}
                >
                  <span className="workflow-stage-index">{index + 1}</span>
                  <Icon size={17} />
                  <span className="workflow-stage-copy">
                    <strong>{item.label}</strong>
                    <small>{locked ? (workerBusy ? '生成中已锁定' : '先完成上一步') : item.summary}</small>
                  </span>
                  {past ? (
                    <CheckCircle2 className="workflow-stage-check complete" size={17} aria-hidden="true" />
                  ) : selected ? (
                    <CircleDot className="workflow-stage-check current" size={17} aria-hidden="true" />
                  ) : null}
                </button>
              </li>
            )
          })}
        </ol>
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
              <button type="button" className="primary-button" onClick={goToGenerateSettings} disabled={!sourceReady}>
                <ArrowRight size={18} />
                {sourceActionLabel}
              </button>
              {!sourceReady ? <small className="workflow-action-note">{sourceActionNote}</small> : null}
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
              cardStyleId={request.card_style}
              documentStudyMode={request.document_study_mode}
              reviewDensity={request.review_density}
              sourceMode={request.source_mode}
              templateId={templateId}
              templateOptions={templateOptions}
              onSelectCardStyle={(styleId) => onPatchRequest({ card_style: styleId })}
              onSelectReviewDensity={(reviewDensity) => onPatchRequest({ review_density: reviewDensity })}
              onSelectTemplate={onSelectTemplate}
            />
            <div className="workflow-stage-actions split">
              <button type="button" className="ghost-button" onClick={() => onWorkspaceStageChange('source')}>
                <ArrowLeft size={18} />
                返回素材
              </button>
              <button type="button" className="primary-button" onClick={goToConfirmGenerate} disabled={appBusy}>
                <ArrowRight size={18} />
                下一步：确认抽取
              </button>
            </div>
          </>
        ) : null}

        {activeWorkspaceStage === 'review' ? (
          <>
            {!workerBusy ? (
              <StatusPanel
                appBusy={appBusy}
                requestEditedDuringRun={requestEditedDuringRun}
                status={status}
                statusTone={statusTone}
                workerBusy={workerBusy}
                workerErrorActions={workerErrorActions}
                onWorkerErrorAction={onWorkerErrorAction}
              />
            ) : null}
            <div className="panel workflow-review-card">
              <div className="workflow-review-title">
                <span>{reviewStageLabel}</span>
                <strong>
                  {workerBusy && !hasProject
                    ? runningCommand === 'extract_learning_points'
                      ? '正在从字幕抽取学习点'
                      : '正在把学习点生成完整卡片'
                    : hasProject
                      ? '检查卡片后导出 APKG'
                      : hasLearningPointResult
                        ? '选择学习点后生成完整卡片'
                        : '设置完成后先抽取学习点'}
                </strong>
              </div>
              {workerBusy && !hasProject ? (
                <div className="workflow-running-card" role="status">
                  <strong>{Math.round(workerProgress?.percent ?? 0)}%</strong>
                  <span>生成进度已移到右侧工作台。素材、学习设置和模板在本轮任务中已锁定。</span>
                  <small>需要中止时，使用顶部的取消按钮。</small>
                </div>
              ) : hasProject ? (
                <>
                  <div className="workflow-review-compact" aria-label="审核阶段摘要">
                    <strong>{selectedCardCount}</strong>
                    <span>张将导出</span>
                    <small>
                      {`已生成 ${generatedCardCount} 张`}
                      {diagnosticCount > 0 ? ` · 更多学习点 ${diagnosticCount}` : ''}
                    </small>
                  </div>
                  <div className="workflow-stage-actions split">
                    <button type="button" className="ghost-button" onClick={() => onWorkspaceStageChange('generate')}>
                      <SlidersHorizontal size={18} />
                      修改设置
                    </button>
                    <button type="button" className="primary-button" onClick={onExport} disabled={appBusy || !hasExportableCards}>
                      <Download size={18} />
                      导出已选
                    </button>
                  </div>
                </>
              ) : (
                <>
                  <div className="workflow-confirm-list" aria-label="生成前确认">
                    <span>
                      <strong>素材</strong>
                      <small>{sourceLabel}</small>
                      {request.batch_enabled ? <small>{batchPackageTitle}</small> : null}
                      {request.batch_enabled ? <small>{batchSubdeckSummary}</small> : null}
                    </span>
                    <span>
                      <strong>学习</strong>
                      <small>{levelSummary}</small>
                    </span>
                    <span>
                      <strong>{hasLearningPointResult ? '已选学习点' : '模板'}</strong>
                      <small>{hasLearningPointResult ? `${selectedLearningPointCount} 个` : activeTemplateLabel}</small>
                    </span>
                  </div>
                  {incompleteReadiness.length ? (
                    <div className="workflow-preflight-warning" role="status">
                      <strong>{hasLearningPointResult ? '生成完整卡片前还需要完成' : '抽取学习点前还需要完成'}</strong>
                      <small>{incompleteReadiness.map((item) => `${item.label}：${item.detail}`).join(' / ')}</small>
                      {envPreflight ? (
                        <div className="workflow-preflight-actions" aria-label="环境快捷处理">
                          {envUnchecked ? (
                            <button type="button" className="preflight-primary-action" onClick={onCheckEnv} disabled={appBusy}>
                              立即检查
                            </button>
                          ) : null}
                          {showEnvRepair ? (
                            <button type="button" className="preflight-primary-action" onClick={() => onRepairEnv('all')} disabled={appBusy}>
                              一键修复
                            </button>
                          ) : null}
                          <button type="button" className="preflight-secondary-action" onClick={onOpenEnvSettings} disabled={appBusy}>
                            查看详情
                          </button>
                        </div>
                      ) : null}
                    </div>
                  ) : (
                    <div className="workflow-preflight-ok" role="status">
                      <strong>{hasLearningPointResult ? '可以生成完整卡片' : '可以抽取学习点'}</strong>
                      <small>
                        {hasLearningPointResult
                          ? '环境和模型 API 已就绪。TTS 可在导出前继续测试或配置。'
                          : request.batch_enabled
                            ? `本轮会按 ${batchSubdeckSummary} 逐项制卡，最终导出一个保留层级的 APKG。`
                            : '本轮会先读取字幕，再调用模型 API 精筛词伙、口语、单词用法、语法和听力点。'}
                      </small>
                    </div>
                  )}
                  <div className="workflow-stage-actions split">
                    <button type="button" className="ghost-button" onClick={() => onWorkspaceStageChange('generate')}>
                      <ArrowLeft size={18} />
                      返回学习设置
                    </button>
                    <button
                      type="button"
                      className="primary-button"
                      onClick={onGenerate}
                      disabled={appBusy || !sourceReady || (hasLearningPointResult && selectedLearningPointCount === 0)}
                    >
                      <PlayCircle size={18} />
                      {hasLearningPointResult ? '生成选中卡片' : '开始抽取学习点'}
                    </button>
                  </div>
                </>
              )}
            </div>
          </>
        ) : null}
      </section>
    </aside>
  )
}
