import { useEffect, useState } from 'react'
import { publicSourceModeFor } from '../domain/publicSource'
import { Topbar } from '../features/app/Topbar'
import { WorkflowRail } from '../features/app/WorkflowRail'
import { ReviewWorkspace } from '../features/review/ReviewWorkspace'
import { SettingsDialog } from '../features/settings/SettingsDialog'
import { OnboardingWizard } from '../features/onboarding/OnboardingWizard'
import { SourceWorkspace } from '../features/source/SourceWorkspace'
import { loadUiPreferences, saveUiPreferences } from '../services/uiPreferences'
import {
  selectProductStepForArtifact,
  type ArtifactStage,
  type ProductStep,
  type WorkflowActionId,
  type WorkflowIssue,
} from './workflowState'
import { resolutionForWorkflowIssue } from './workflowIssueResolution'
import type { AppController } from './useAppController'

type AppShellProps = {
  controller: AppController
}

export function existingArtifactDestination(artifactStage: ArtifactStage): ProductStep | null {
  const destination = selectProductStepForArtifact(artifactStage)
  return destination === 'source' ? null : destination
}

export function sourcePrimaryTarget(artifactStage: ArtifactStage): ProductStep | 'extract_learning_points' {
  return existingArtifactDestination(artifactStage) ?? 'extract_learning_points'
}

export function deliveryFooterSummary(
  artifactStage: ArtifactStage,
  exportableCardCount: number,
  operationMessage?: string,
): { title: string; detail: string } {
  if (artifactStage === 'anki_verified') {
    return {
      title: '已在 Anki 中核验',
      detail: '牌组、卡片和媒体已经通过本次核验。',
    }
  }
  if (artifactStage === 'apkg_ready') {
    return {
      title: 'APKG 已生成，尚未导入 Anki',
      detail: '文件已经安全保存；导入与核验仍需要你明确触发。',
    }
  }
  return {
    title: artifactStage === 'drafts_ready' ? `${exportableCardCount} 张可安全导出` : operationMessage || '等待安全产物',
    detail: '生成、导出、导入与核验严格区分，已完成结果不会被重复执行。',
  }
}

const WORKFLOW_SCROLL_CONTAINER_SELECTOR = '.source-workspace-content, .workflow-step-scroll'

function workflowScrollContainers(root: ParentNode = document): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(WORKFLOW_SCROLL_CONTAINER_SELECTOR))
}

export function resetWorkflowStepViewport(
  previousScrollContainers: readonly HTMLElement[] = [],
  root: ParentNode = document,
): void {
  const scrollContainers = new Set([...previousScrollContainers, ...workflowScrollContainers(root)])
  scrollContainers.forEach((container) => {
    // Direct assignment is always instant and must not inherit motion preferences.
    container.scrollTop = 0
  })
  root.querySelector<HTMLElement>('[data-workflow-page-title="true"]')?.focus({ preventScroll: true })
}

export function modalBackgroundAttributes(active: boolean): { 'aria-hidden'?: true; inert?: true } {
  return active ? { 'aria-hidden': true, inert: true } : {}
}

export function appModalActive(
  settingsOpen: boolean,
  onboardingVisible: boolean,
  generationConfirmOpen: boolean,
): boolean {
  return settingsOpen || onboardingVisible || generationConfirmOpen
}

declare global {
  interface Window {
    __ANKI_RELEASE_EVIDENCE__?: {
      buildRawObservedSnapshotHandoff: AppController['buildReleaseObservedRawSnapshotHandoff']
      buildTimingCacheSnapshot: AppController['buildReleaseObservedTimingCacheSnapshot']
    }
  }
}

export function AppShell({ controller }: AppShellProps) {
  const [uiPreferences, setUiPreferences] = useState(loadUiPreferences)
  const [onboardingOpen, setOnboardingOpen] = useState(false)
  const [onboardingRunId, setOnboardingRunId] = useState(0)
  const [settingsReturnToOnboarding, setSettingsReturnToOnboarding] = useState(false)
  const {
    activeWorkspaceStage,
    productStep,
    activeSegment,
    activeSegmentId,
    activeSegmentVideoSrc,
    activeSegmentVideoError,
    advancedApiPresets,
    advancedTtsPresets,
    ankiVerifying,
    ankiVerifyResult,
    apiTestMessage,
    apiTestMeta,
    apiTestTitle,
    apiTestTone,
    apiTesting,
    apiReadyForGeneration,
    hermesChecking,
    hermesStarting,
    hermesStatus,
    appBusy,
    applyApiPreset,
    applySavedApiProfile,
    applySavedTtsProfile,
    applyTtsPreset,
    cancelCurrentWorker,
    forceCancelCurrentWorker,
    forceCancelBusy,
    showForceCancel,
    capabilityHelp,
    capabilityLabels,
    checkEnv,
    deepseekTextModels,
    envRepairing,
    envRepairResult,
    envStatus,
    exportApkg,
    extractLearningPoints,
    extractLearningPointsWithoutCache,
    featuredApiPresets,
    featuredTtsPresets,
    geminiVertexTextModels,
    generationConfirmOpen,
    generationQueuePoints,
    generationQueueSummary,
    generateCardsFromLearningPoints,
    generateSingleLearningPoint,
    handleWorkerErrorAction,
    handleTopbarDoubleClick,
    inspectorActionLabel,
    inspectorSheetOpen,
    inspectorState,
    isDesktopRuntime,
    lastExport,
    lastWorkerError,
    learningPointResult,
    levels,
    MIMO_OPENAI_BASE_URL,
    MIMO_TOKEN_PLAN_SGP_BASE_URL,
    mimoTextModels,
    mimoTtsModels,
    mimoTtsVoices,
    qwenTextModels,
    qwenTtsModels,
    qwenTtsVoices,
    motionDuration,
    openAnkiImport,
    outputDirectory,
    changeOutputDirectory,
    closeGenerationConfirm,
    confirmGenerateCardsFromLearningPoints,
    patchApi,
    patchRequest,
    patchTts,
    prefersReducedMotion,
    previewPanelRef,
    previewRate,
    project,
    qualityCounts,
    qualityDiagnostics,
    qualityFunnel,
    workflowUiSnapshot,
    buildReleaseObservedRawSnapshotHandoff,
    buildReleaseObservedTimingCacheSnapshot,
    request,
    responsiveMode,
    revealExport,
    removeGenerationQueueLearningPoint,
    retryMissingLearningPoints,
    repairEnv,
    resumeRecoveredWorkflow,
    runWindowAction,
    savedApiProfiles,
    savedTtsProfiles,
    segmentFilter,
    segmentReviewCounts,
    selectedCardCount,
    selectedExportableCardCount,
    selectedLearningPointIds,
    invertCardSelection,
    selectCurrentLevel,
    selectPath,
    selectSegment,
    selectSourceMode,
    selectTemplate,
    setCardsEnabled,
    setActiveWorkspaceStage,
    setProductStep,
    setInspectorState,
    setPreviewRate,
    setSegmentFilter,
    setSelectedLearningPointIds,
    setSettingsOpen,
    setSettingsTab,
    setShowAdvancedTts,
    setShowCapabilities,
    settingsDialogRef,
    settingsOpen,
    settingsTab,
    settingsApiConfig,
    settingsTts,
    settingsActiveApiProfileId,
    settingsActiveTtsProfileId,
    settingsActiveApiKeySaved,
    settingsActiveTtsKeySaved,
    settingsApiProfileDirty,
    settingsTtsProfileDirty,
    settingsApiProfileStatus,
    settingsTtsProfileStatus,
    settingsApiTestOk,
    settingsTtsTestOk,
    settingsDraftDirty,
    settingsDraftMode,
    settingsSaving,
    beginSettingsDraftSession,
    setSettingsDraftDisplayMode,
    discardSettingsChanges,
    deleteSavedApiCredential,
    deleteSavedTtsCredential,
    endSettingsDraftSession,
    saveSettingsAndVerify,
    applySettingsDraftLater,
    abandonRecoveredWorkflow,
    showAdvancedTts,
    showCapabilities,
    startWindowDrag,
    startWindowResize,
    status,
    refreshHermesStatus,
    startHermesForSettings,
    testApi,
    testTts,
    toggleInspector,
    ttsReadyForGeneration,
    ttsRequired,
    ttsTesting,
    ttsTestMessage,
    ttsTestMeta,
    ttsTestTitle,
    ttsTestTone,
    updateCard,
    verifyAnkiImport,
    visibleSegments,
    workerBusy,
    workerErrorActions,
    workerProgress,
  } = controller

  useEffect(() => {
    if (settingsOpen) beginSettingsDraftSession(uiPreferences.settingsMode)
  }, [beginSettingsDraftSession, settingsOpen, uiPreferences.settingsMode])
  useEffect(() => {
    if (typeof window === 'undefined' || !isDesktopRuntime) {
      if (typeof window !== 'undefined') delete window.__ANKI_RELEASE_EVIDENCE__
      return
    }
    window.__ANKI_RELEASE_EVIDENCE__ = {
      buildRawObservedSnapshotHandoff: buildReleaseObservedRawSnapshotHandoff,
      buildTimingCacheSnapshot: buildReleaseObservedTimingCacheSnapshot,
    }
    return () => {
      if (
        window.__ANKI_RELEASE_EVIDENCE__?.buildRawObservedSnapshotHandoff === buildReleaseObservedRawSnapshotHandoff
      ) {
        delete window.__ANKI_RELEASE_EVIDENCE__
      }
    }
  }, [buildReleaseObservedRawSnapshotHandoff, buildReleaseObservedTimingCacheSnapshot, isDesktopRuntime])

  useEffect(() => {
    if (isDesktopRuntime && !uiPreferences.onboardingCompleted) {
      setOnboardingOpen(true)
    }
  }, [isDesktopRuntime, uiPreferences.onboardingCompleted])

  useEffect(() => {
    if (!inspectorSheetOpen || settingsOpen || generationConfirmOpen || onboardingOpen) return

    const closeInspectorOnEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      setInspectorState('collapsed')
      window.requestAnimationFrame(() => {
        document.querySelector<HTMLButtonElement>('[data-inspector-toggle="true"]')?.focus()
      })
    }

    window.addEventListener('keydown', closeInspectorOnEscape)
    return () => window.removeEventListener('keydown', closeInspectorOnEscape)
  }, [generationConfirmOpen, inspectorSheetOpen, onboardingOpen, setInspectorState, settingsOpen])

  const dismissOnboarding = () => {
    const nextPreferences = { ...uiPreferences, onboardingCompleted: true as const }
    setUiPreferences(nextPreferences)
    saveUiPreferences(nextPreferences)
    setOnboardingOpen(false)
  }

  const openOnboardingSettings = (tab: 'api' | 'tts') => {
    setSettingsTab(tab)
    setSettingsReturnToOnboarding(true)
    setOnboardingOpen(false)
    setSettingsOpen(true)
  }

  const closeSettings = () => {
    endSettingsDraftSession()
    setSettingsOpen(false)
    if (!settingsReturnToOnboarding) return
    setSettingsReturnToOnboarding(false)
    setOnboardingOpen(true)
  }

  const persistSettingsMode = () => {
    const nextPreferences = { ...uiPreferences, settingsMode: settingsDraftMode }
    setUiPreferences(nextPreferences)
    saveUiPreferences(nextPreferences)
  }

  const handleSaveSettings = async () => {
    if (!settingsDraftDirty && settingsDraftMode !== uiPreferences.settingsMode) {
      persistSettingsMode()
      return
    }
    if (await saveSettingsAndVerify()) persistSettingsMode()
  }

  const handleApplySettingsLater = async () => {
    if (!settingsDraftDirty) {
      persistSettingsMode()
      return
    }
    if (await applySettingsDraftLater()) persistSettingsMode()
  }

  const settingsDirty = settingsDraftDirty || settingsDraftMode !== uiPreferences.settingsMode

  const publicSourceMode = publicSourceModeFor(request.source_mode)
  const reviewTemplateLabel = request.review_density === 'fast' ? '快速复读' : '完整复读'
  const deliverySummary = deliveryFooterSummary(
    workflowUiSnapshot.artifactStage,
    selectedExportableCardCount,
    workflowUiSnapshot.operation?.message,
  )
  const navigateProductStep = (step: AppController['productStep']) => {
    const outgoingScrollContainers = workflowScrollContainers()
    setProductStep(step)
    setActiveWorkspaceStage(step === 'source' ? 'source' : 'review')
    if (inspectorSheetOpen) setInspectorState('collapsed')
    window.requestAnimationFrame(() => {
      resetWorkflowStepViewport(outgoingScrollContainers)
    })
  }

  const resolveWorkflowIssues = (issues: WorkflowIssue[]) => {
    const issue = issues[0]
    switch (resolutionForWorkflowIssue(issue)) {
      case 'check_environment':
        void checkEnv()
        return
      case 'repair_environment':
        void repairEnv('all')
        return
      case 'test_api':
        void testApi()
        return
      case 'open_api_settings':
        setSettingsTab('api')
        setSettingsOpen(true)
        return
      case 'test_tts':
        void testTts()
        return
      case 'open_tts_settings':
        setSettingsTab('tts')
        setSettingsOpen(true)
        return
      case 'navigate_source':
        navigateProductStep('source')
        return
      case 'navigate_select':
        navigateProductStep('select')
        return
      case 'none':
        return
    }
  }

  const runWorkflowAction = (action: WorkflowActionId) => {
    if (action === 'resume_task') {
      void resumeRecoveredWorkflow()
      return
    }
    if (action === 'analyze_source') {
      const target = sourcePrimaryTarget(workflowUiSnapshot.artifactStage)
      if (target === 'extract_learning_points') void extractLearningPoints()
      else navigateProductStep(target)
      return
    }
    if (action === 'generate_cards') {
      generateCardsFromLearningPoints()
      return
    }
    if (action === 'export_cards') {
      void exportApkg()
      return
    }
    if (action === 'import_and_verify') {
      void verifyAnkiImport()
      return
    }
    resolveWorkflowIssues(workflowUiSnapshot.primaryAction.blockers)
  }
  const onboardingVisible = isDesktopRuntime && onboardingOpen
  const modalActive = appModalActive(settingsOpen, onboardingVisible, generationConfirmOpen)

  return (
    <div className="app-shell">
      <Topbar
        inspectorActionLabel={inspectorActionLabel}
        inspectorActive={inspectorState === 'open' || inspectorState === 'collapsing' || inspectorSheetOpen}
        workflowUiSnapshot={workflowUiSnapshot}
        modalActive={modalActive}
        onCancelCurrentWorker={cancelCurrentWorker}
        onForceCancel={forceCancelCurrentWorker}
        forceCancelBusy={forceCancelBusy}
        showForceCancel={showForceCancel}
        onDoubleClick={handleTopbarDoubleClick}
        onMouseDown={startWindowDrag}
        onOpenSettings={() => setSettingsOpen(true)}
        onToggleInspector={toggleInspector}
        onWindowAction={runWindowAction}
      />

      <main className="workspace" {...modalBackgroundAttributes(modalActive)}>
        <section className={`desktop-workspace inspector-${inspectorState}`} data-responsive-mode={responsiveMode}>
          {inspectorSheetOpen ? (
            <button
              className="inspector-backdrop"
              type="button"
              aria-label="关闭流程面板遮罩"
              onClick={() => setInspectorState('collapsed')}
            />
          ) : null}
          <WorkflowRail
            snapshot={workflowUiSnapshot}
            request={request}
            learningPointCount={learningPointResult?.learning_points.length ?? 0}
            draftCardCount={qualityCounts.total}
            onStepChange={navigateProductStep}
          />

          {productStep === 'source' ? (
            <SourceWorkspace
              snapshot={workflowUiSnapshot}
              request={request}
              levels={levels}
              previewRate={previewRate}
              onPatchRequest={patchRequest}
              onPreviewRateChange={setPreviewRate}
              onSelectCurrentLevel={selectCurrentLevel}
              onSelectPath={selectPath}
              onSelectSourceMode={selectSourceMode}
              onSelectReviewDensity={(reviewDensity) => patchRequest({ review_density: reviewDensity })}
              onSelectTemplate={selectTemplate}
              onPrimaryAction={runWorkflowAction}
              onAbandonRecovery={() => {
                void abandonRecoveredWorkflow()
              }}
              onResolveBlockers={resolveWorkflowIssues}
              workerErrorActions={workerErrorActions}
              onWorkerErrorAction={handleWorkerErrorAction}
            />
          ) : (
            <section className="workflow-step-workspace" aria-labelledby="workflow-step-title">
              <header className="workflow-step-header">
                <span>第 {productStep === 'select' ? 2 : 3}/3 步</span>
                <h1 id="workflow-step-title" data-workflow-page-title="true" tabIndex={-1}>
                  {workflowUiSnapshot.heading}
                </h1>
                <p>{workflowUiSnapshot.description}</p>
              </header>
              <div className="workflow-step-scroll">
                {' '}
                <ReviewWorkspace
                  activeSegment={activeSegment}
                  activeSegmentId={activeSegmentId}
                  activeSegmentVideoSrc={activeSegmentVideoSrc}
                  activeSegmentVideoError={activeSegmentVideoError}
                  activeTemplateLabel={reviewTemplateLabel}
                  ankiVerifying={ankiVerifying}
                  ankiVerifyResult={ankiVerifyResult}
                  lastExport={lastExport}
                  lastWorkerError={lastWorkerError}
                  language={request.language}
                  level={request.level}
                  learningPointResult={learningPointResult}
                  motionDuration={motionDuration}
                  prefersReducedMotion={Boolean(prefersReducedMotion)}
                  previewPanelRef={previewPanelRef}
                  previewRate={previewRate}
                  preferLearningPointSelection={productStep === 'select'}
                  project={project}
                  qualityCounts={qualityCounts}
                  qualityDiagnostics={qualityDiagnostics}
                  qualityFunnel={qualityFunnel}
                  selectedCardCount={selectedCardCount}
                  selectedLearningPointIds={selectedLearningPointIds}
                  generationConfirmOpen={generationConfirmOpen}
                  generationQueuePoints={generationQueuePoints}
                  generationQueueSummary={generationQueueSummary}
                  segmentFilter={segmentFilter}
                  segmentReviewCounts={segmentReviewCounts}
                  sourceMode={publicSourceMode}
                  templateId={request.template_id}
                  visibleSegments={visibleSegments}
                  workerBusy={workerBusy}
                  workerProgress={workerProgress}
                  primaryAction={workflowUiSnapshot.primaryAction}
                  workerErrorActions={workerErrorActions}
                  workspaceStage={activeWorkspaceStage}
                  status={status}
                  onCloseGenerationConfirm={closeGenerationConfirm}
                  onConfirmGenerateCardsFromLearningPoints={confirmGenerateCardsFromLearningPoints}
                  onExport={exportApkg}
                  onExtractLearningPointsWithoutCache={extractLearningPointsWithoutCache}
                  onRevealExport={revealExport}
                  onSegmentFilterChange={setSegmentFilter}
                  onInvertCardSelection={invertCardSelection}
                  onOpenAnkiImport={openAnkiImport}
                  onResolveBlockers={resolveWorkflowIssues}
                  onRunWorkflowAction={runWorkflowAction}
                  onGenerateSingleLearningPoint={generateSingleLearningPoint}
                  onRemoveGenerationQueueLearningPoint={removeGenerationQueueLearningPoint}
                  onRetryMissingLearningPoints={retryMissingLearningPoints}
                  onSelectSegment={selectSegment}
                  onSetCardsEnabled={setCardsEnabled}
                  onSetSelectedLearningPointIds={setSelectedLearningPointIds}
                  onUpdateCard={updateCard}
                  onWorkerErrorAction={handleWorkerErrorAction}
                  onVerifyAnkiImport={verifyAnkiImport}
                  showExportPrimaryAction={false}
                />
              </div>
              {productStep === 'deliver' ? (
                <footer className="workflow-delivery-action-bar">
                  <div>
                    <strong>{deliverySummary.title}</strong>
                    <small>
                      {workflowUiSnapshot.primaryAction.blockers[0]?.detail ?? deliverySummary.detail}
                    </small>
                    <small className="workflow-output-directory" title={outputDirectory || '导出时选择保存目录'}>
                      {outputDirectory ? `保存到：${outputDirectory}` : '尚未选择保存目录；导出时再选择。'}
                    </small>
                  </div>
                  <button type="button" className="ghost-button" onClick={() => void changeOutputDirectory()}>
                    更改保存目录
                  </button>
                  {workflowUiSnapshot.primaryAction.action === 'resume_task' ? (
                    <button type="button" className="secondary-button" onClick={() => void abandonRecoveredWorkflow()}>
                      放弃恢复
                    </button>
                  ) : null}
                  <button
                    type="button"
                    className="primary-button"
                    data-variant="primary"
                    disabled={
                      workflowUiSnapshot.primaryAction.state === 'running' ||
                      workflowUiSnapshot.primaryAction.state === 'completed' ||
                      (workflowUiSnapshot.primaryAction.state === 'blocked' &&
                        !workflowUiSnapshot.primaryAction.blockers.some((issue) =>
                          ['environment', 'api', 'tts', 'selection_empty', 'learning_points_missing'].includes(
                            issue.id,
                          ),
                        ))
                    }
                    onClick={() => {
                      if (workflowUiSnapshot.primaryAction.state === 'blocked') {
                        resolveWorkflowIssues(workflowUiSnapshot.primaryAction.blockers)
                      } else {
                        runWorkflowAction(workflowUiSnapshot.primaryAction.action)
                      }
                    }}
                  >
                    {workflowUiSnapshot.primaryAction.primaryLabel}
                  </button>
                </footer>
              ) : null}
            </section>
          )}
        </section>
      </main>

      <OnboardingWizard
        key={onboardingRunId}
        apiReady={apiReadyForGeneration}
        envStatus={envStatus}
        open={onboardingVisible}
        ttsReady={ttsReadyForGeneration}
        ttsRequired={ttsRequired}
        onCheckEnv={checkEnv}
        onComplete={dismissOnboarding}
        onOpenApiSettings={() => openOnboardingSettings('api')}
        onOpenTtsSettings={() => openOnboardingSettings('tts')}
        onSkip={dismissOnboarding}
      />

      <SettingsDialog
        apiSettings={{
          advancedApiPresets,
          apiConfig: settingsApiConfig,
          apiTestMessage,
          apiTestMeta,
          apiTestOk: settingsApiTestOk,
          apiTestTitle,
          apiTestTone,
          apiTesting,
          apiKeySaved: settingsActiveApiKeySaved,
          activeApiProfileId: settingsActiveApiProfileId,
          apiProfileDirty: settingsApiProfileDirty,
          apiProfileStatus: settingsApiProfileStatus,
          appBusy,
          capabilityHelp,
          capabilityLabels,
          featuredApiPresets,
          hermesChecking,
          hermesStarting,
          hermesStatus,
          mimoOpenAiBaseUrl: MIMO_OPENAI_BASE_URL,
          mimoTextModels: [...mimoTextModels, ...qwenTextModels, ...deepseekTextModels, ...geminiVertexTextModels],
          savedApiProfiles,
          showCapabilities,
          onApplyApiPreset: applyApiPreset,
          onApplySavedApiProfile: applySavedApiProfile,
          onCheckHermes: refreshHermesStatus,
          onPatchApi: patchApi,
          onDeleteSavedCredential: () => {
            void deleteSavedApiCredential()
          },
          onSaveApiProfile: () => {
            void handleSaveSettings()
          },
          onSetShowCapabilities: setShowCapabilities,
          onStartHermes: startHermesForSettings,
          onTestApi: testApi,
        }}
        dialogRef={settingsDialogRef}
        envSettings={{
          appBusy,
          envRepairing,
          envRepairResult,
          envStatus,
          onCheckEnv: checkEnv,
          onRepairEnv: repairEnv,
        }}
        motionDuration={motionDuration}
        open={settingsOpen}
        prefersReducedMotion={Boolean(prefersReducedMotion)}
        settingsMode={settingsDraftMode}
        settingsTab={settingsTab}
        ttsSettings={{
          advancedTtsPresets,
          apiConfig: settingsApiConfig,
          appBusy,
          featuredTtsPresets,
          mimoOpenAiBaseUrl: MIMO_OPENAI_BASE_URL,
          mimoTokenPlanSgpBaseUrl: MIMO_TOKEN_PLAN_SGP_BASE_URL,
          mimoTtsModels,
          mimoTtsVoices,
          qwenTtsModels,
          qwenTtsVoices,
          activeTtsProfileId: settingsActiveTtsProfileId,
          savedTtsProfiles,
          showAdvancedTts,
          tts: settingsTts,
          ttsKeySaved: settingsActiveTtsKeySaved,
          ttsProfileDirty: settingsTtsProfileDirty,
          ttsProfileStatus: settingsTtsProfileStatus,
          ttsTestMessage,
          ttsTestMeta,
          ttsTestOk: settingsTtsTestOk,
          ttsTestTitle,
          ttsTestTone,
          ttsTesting,
          onApplySavedTtsProfile: applySavedTtsProfile,
          onApplyTtsPreset: applyTtsPreset,
          onPatchTts: patchTts,
          onDeleteSavedCredential: () => {
            void deleteSavedTtsCredential()
          },
          onSaveTtsProfile: () => {
            void handleSaveSettings()
          },
          onSetShowAdvancedTts: setShowAdvancedTts,
          onTestTts: testTts,
        }}
        dirty={settingsDirty}
        saving={settingsSaving}
        onApplyWithoutVerification={() => {
          void handleApplySettingsLater()
        }}
        onClose={closeSettings}
        onDiscardChanges={discardSettingsChanges}
        onSaveAndVerify={() => {
          void handleSaveSettings()
        }}
        onRerunOnboarding={() => {
          setSettingsReturnToOnboarding(false)
          endSettingsDraftSession()
          setSettingsOpen(false)
          setOnboardingRunId((current) => current + 1)
          setOnboardingOpen(true)
        }}
        onSettingsModeChange={setSettingsDraftDisplayMode}
        onSettingsTabChange={setSettingsTab}
      />

      {isDesktopRuntime ? (
        <div className="resize-handles" aria-hidden="true">
          <div className="resize-handle resize-n" onMouseDown={(event) => startWindowResize('North', event)} />
          <div className="resize-handle resize-e" onMouseDown={(event) => startWindowResize('East', event)} />
          <div className="resize-handle resize-s" onMouseDown={(event) => startWindowResize('South', event)} />
          <div className="resize-handle resize-w" onMouseDown={(event) => startWindowResize('West', event)} />
          <div className="resize-handle resize-ne" onMouseDown={(event) => startWindowResize('NorthEast', event)} />
          <div className="resize-handle resize-nw" onMouseDown={(event) => startWindowResize('NorthWest', event)} />
          <div className="resize-handle resize-se" onMouseDown={(event) => startWindowResize('SouthEast', event)} />
          <div className="resize-handle resize-sw" onMouseDown={(event) => startWindowResize('SouthWest', event)} />
        </div>
      ) : null}
    </div>
  )
}
