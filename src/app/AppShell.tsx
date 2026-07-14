import { useEffect, useState } from 'react'
import { InspectorPanel } from '../features/app/InspectorPanel'
import { publicSourceModeFor } from '../domain/publicSource'
import { Topbar } from '../features/app/Topbar'
import { ReviewWorkspace } from '../features/review/ReviewWorkspace'
import { SettingsDialog } from '../features/settings/SettingsDialog'
import { OnboardingWizard } from '../features/onboarding/OnboardingWizard'
import { loadUiPreferences, saveUiPreferences } from '../services/uiPreferences'
import type { AppController } from './useAppController'

type AppShellProps = {
  controller: AppController
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
    activeSegment,
    activeSegmentId,
    activeSegmentVideoSrc,
    activeSegmentVideoError,
    activeApiProfileId,
    activeTtsProfileId,
    advancedApiPresets,
    advancedTtsPresets,
    ankiVerifying,
    ankiVerifyResult,
    apiTestMessage,
    apiTestMeta,
    apiTestResult,
    apiTestTitle,
    apiTestTone,
    apiTesting,
    apiReadyForGeneration,
    hermesChecking,
    hermesStarting,
    hermesStatus,
    activeApiKeySaved,
    apiProfileDirty,
    apiProfileStatus,
    appBusy,
    applyApiPreset,
    applySavedApiProfile,
    applySavedTtsProfile,
    applyTtsPreset,
    cancelCurrentWorker,
    capabilityHelp,
    capabilityLabels,
    checkEnv,
    deepseekTextModels,
    envRepairing,
    envRepairResult,
    envStatus,
    exportApkg,
    extractLearningPointsWithoutCache,
    featuredApiPresets,
    featuredTtsPresets,
    geminiVertexTextModels,
    generate,
    generationConfirmOpen,
    generationQueuePoints,
    generationQueueSummary,
    generateCardsFromLearningPoints,
    generateSingleLearningPoint,
    handleTopbarDoubleClick,
    handleWorkerErrorAction,
    inspectorActionLabel,
    inspectorSheetOpen,
    inspectorState,
    isCancelling,
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
    closeGenerationConfirm,
    confirmGenerateCardsFromLearningPoints,
    openAnkiImport,
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
    readiness,
    workflowReadiness,
    buildReleaseObservedRawSnapshotHandoff,
    buildReleaseObservedTimingCacheSnapshot,
    request,
    requestEditedDuringRun,
    responsiveMode,
    revealExport,
    removeGenerationQueueLearningPoint,
    retryMissingLearningPoints,
    repairEnv,
    runWindowAction,
    savedApiProfiles,
    savedTtsProfiles,
    saveCurrentApiProfile,
    saveCurrentTtsProfile,
    segmentFilter,
    segmentReviewCounts,
    selectedCardCount,
    selectedExportableCardCount,
    exportableCardCount,
    repairRequiredCardCount,
    selectedRepairRequiredCardCount,
    selectedLearningPointCount,
    selectedLearningPointIds,
    invertCardSelection,
    selectCurrentLevel,
    selectPath,
    selectSegment,
    selectSourceMode,
    selectTemplate,
    setCardsEnabled,
    setActiveWorkspaceStage,
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
    showAdvancedTts,
    showCapabilities,
    startWindowDrag,
    startWindowResize,
    status,
    statusTone,
    refreshHermesStatus,
    startHermesForSettings,
    testApi,
    testTts,
    toggleInspector,
    tts,
    ttsReadyForGeneration,
    ttsRequired,
    activeTtsKeySaved,
    ttsProfileDirty,
    ttsProfileStatus,
    ttsTesting,
    ttsTestMessage,
    ttsTestMeta,
    ttsTestResult,
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
    setSettingsOpen(false)
    if (!settingsReturnToOnboarding) return
    setSettingsReturnToOnboarding(false)
    setOnboardingOpen(true)
  }

  const hasLearningPointResult = Boolean(learningPointResult && !project)
  const publicSourceMode = publicSourceModeFor(request.source_mode)
  const primaryGenerateAction = hasLearningPointResult ? generateCardsFromLearningPoints : generate
  const reviewTemplateLabel = request.review_density === 'fast' ? '快速复读' : '完整复读'

  return (
    <div className="app-shell">
      <Topbar
        inspectorActionLabel={inspectorActionLabel}
        inspectorActive={inspectorState === 'open' || inspectorState === 'collapsing' || inspectorSheetOpen}
        isCancelling={isCancelling}
        status={status}
        statusTone={statusTone}
        workerBusy={workerBusy}
        workflowReadiness={workflowReadiness}
        onCancelCurrentWorker={cancelCurrentWorker}
        onDoubleClick={handleTopbarDoubleClick}
        onMouseDown={startWindowDrag}
        onOpenSettings={() => setSettingsOpen(true)}
        onToggleInspector={toggleInspector}
        onWindowAction={runWindowAction}
      />

      <main className="workspace">
        <section className={`desktop-workspace inspector-${inspectorState}`} data-responsive-mode={responsiveMode}>
          {inspectorSheetOpen ? (
            <button
              className="inspector-backdrop"
              type="button"
              aria-label="关闭素材面板遮罩"
              onClick={() => setInspectorState('collapsed')}
            />
          ) : null}
          <InspectorPanel
            activeWorkspaceStage={activeWorkspaceStage}
            appBusy={appBusy}
            diagnosticCount={
              (qualityFunnel.candidate_only_learning_point_count ?? 0) +
              (qualityFunnel.hidden_duplicate_learning_point_count ?? 0) +
              (qualityFunnel.hard_blocked_learning_point_count ?? 0)
            }
            generatedCardCount={qualityCounts.total}
            hasExportableCards={selectedExportableCardCount > 0}
            hasLearningPointResult={hasLearningPointResult}
            hasProject={Boolean(project)}
            inspectorSheetOpen={inspectorSheetOpen}
            levels={levels}
            previewRate={previewRate}
            selectedCardCount={selectedCardCount}
            selectedExportableCardCount={selectedExportableCardCount}
            exportableCardCount={exportableCardCount}
            repairRequiredCardCount={repairRequiredCardCount}
            selectedRepairRequiredCardCount={selectedRepairRequiredCardCount}
            selectedLearningPointCount={selectedLearningPointCount}
            readiness={readiness}
            workflowReadiness={workflowReadiness}
            request={request}
            requestEditedDuringRun={requestEditedDuringRun}
            status={status}
            statusTone={statusTone}
            workerBusy={workerBusy}
            workerErrorActions={workerErrorActions}
            workerProgress={workerProgress}
            onCloseSheet={() => setInspectorState('collapsed')}
            onExport={exportApkg}
            onExtractLearningPointsWithoutCache={extractLearningPointsWithoutCache}
            onGenerate={primaryGenerateAction}
            onPatchRequest={patchRequest}
            onPreviewRateChange={setPreviewRate}
            onResolveReadiness={(action) => {
              if (action === 'select_source') {
                setActiveWorkspaceStage('source')
                return
              }
              if (action === 'check_environment') {
                checkEnv()
                return
              }
              if (action === 'repair_environment') {
                repairEnv('all')
                return
              }
              if (action === 'test_api') {
                setSettingsTab('api')
                setSettingsOpen(true)
                return
              }
              if (action === 'test_tts') {
                setSettingsTab('tts')
                setSettingsOpen(true)
                return
              }
              if (action === 'select_learning_points' || action === 'repair_cards') {
                setActiveWorkspaceStage('review')
                return
              }
              if (action === 'open_anki') {
                openAnkiImport()
              }
            }}
            onSelectCurrentLevel={selectCurrentLevel}
            onSelectPath={selectPath}
            onSelectSourceMode={selectSourceMode}
            onSelectTemplate={selectTemplate}
            onWorkspaceStageChange={setActiveWorkspaceStage}
            onWorkerErrorAction={handleWorkerErrorAction}
          />

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
            workflowReadiness={workflowReadiness}
            workspaceStage={activeWorkspaceStage}
            status={status}
            onCloseGenerationConfirm={closeGenerationConfirm}
            onConfirmGenerateCardsFromLearningPoints={confirmGenerateCardsFromLearningPoints}
            onExport={exportApkg}
            onExtractLearningPointsWithoutCache={extractLearningPointsWithoutCache}
            onOpenAnkiImport={openAnkiImport}
            onRevealExport={revealExport}
            onSegmentFilterChange={setSegmentFilter}
            onInvertCardSelection={invertCardSelection}
            onGenerateCardsFromLearningPoints={generateCardsFromLearningPoints}
            onGenerateSingleLearningPoint={generateSingleLearningPoint}
            onRemoveGenerationQueueLearningPoint={removeGenerationQueueLearningPoint}
            onRetryMissingLearningPoints={retryMissingLearningPoints}
            onSelectSegment={selectSegment}
            onSetCardsEnabled={setCardsEnabled}
            onSetSelectedLearningPointIds={setSelectedLearningPointIds}
            onUpdateCard={updateCard}
            onVerifyAnkiImport={verifyAnkiImport}
          />
        </section>
      </main>

      <OnboardingWizard
        key={onboardingRunId}
        apiReady={apiReadyForGeneration}
        envStatus={envStatus}
        open={isDesktopRuntime && onboardingOpen}
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
          apiConfig: request.api_config,
          apiTestMessage,
          apiTestMeta,
          apiTestOk: apiTestResult?.ok,
          apiTestTitle,
          apiTestTone,
          apiTesting,
          apiKeySaved: activeApiKeySaved,
          activeApiProfileId,
          apiProfileDirty,
          apiProfileStatus,
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
          onSaveApiProfile: saveCurrentApiProfile,
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
        settingsMode={uiPreferences.settingsMode}
        settingsTab={settingsTab}
        ttsSettings={{
          advancedTtsPresets,
          apiConfig: request.api_config,
          appBusy,
          featuredTtsPresets,
          mimoOpenAiBaseUrl: MIMO_OPENAI_BASE_URL,
          mimoTokenPlanSgpBaseUrl: MIMO_TOKEN_PLAN_SGP_BASE_URL,
          mimoTtsModels,
          mimoTtsVoices,
          qwenTtsModels,
          qwenTtsVoices,
          activeTtsProfileId,
          savedTtsProfiles,
          showAdvancedTts,
          tts,
          ttsKeySaved: activeTtsKeySaved,
          ttsProfileDirty,
          ttsProfileStatus,
          ttsTestMessage,
          ttsTestMeta,
          ttsTestOk: ttsTestResult?.ok,
          ttsTestTitle,
          ttsTestTone,
          ttsTesting,
          onApplySavedTtsProfile: applySavedTtsProfile,
          onApplyTtsPreset: applyTtsPreset,
          onPatchTts: patchTts,
          onSaveTtsProfile: saveCurrentTtsProfile,
          onSetShowAdvancedTts: setShowAdvancedTts,
          onTestTts: testTts,
        }}
        onClose={closeSettings}
        onRerunOnboarding={() => {
          setSettingsReturnToOnboarding(false)
          setSettingsOpen(false)
          setOnboardingRunId((current) => current + 1)
          setOnboardingOpen(true)
        }}
        onSettingsModeChange={(settingsMode) => {
          const nextPreferences = { ...uiPreferences, settingsMode }
          setUiPreferences(nextPreferences)
          saveUiPreferences(nextPreferences)
        }}
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
