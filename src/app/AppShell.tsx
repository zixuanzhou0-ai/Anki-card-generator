import { useEffect } from 'react'
import { InspectorPanel } from '../features/app/InspectorPanel'
import { publicSourceModeFor } from '../domain/publicSource'
import { Topbar } from '../features/app/Topbar'
import { ReviewWorkspace } from '../features/review/ReviewWorkspace'
import { SettingsDialog } from '../features/settings/SettingsDialog'
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
  const {
    activeWorkspaceStage,
    activeSegment,
    activeSegmentId,
    activeSegmentVideoSrc,
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
    testApi,
    testTts,
    toggleInspector,
    tts,
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
        window.__ANKI_RELEASE_EVIDENCE__?.buildRawObservedSnapshotHandoff ===
        buildReleaseObservedRawSnapshotHandoff
      ) {
        delete window.__ANKI_RELEASE_EVIDENCE__
      }
    }
  }, [buildReleaseObservedRawSnapshotHandoff, buildReleaseObservedTimingCacheSnapshot, isDesktopRuntime])

  const hasLearningPointResult = Boolean(learningPointResult && !project)
  const sourceReady = readiness.find((item) => item.id === 'source')?.done ?? false
  const publicSourceMode = publicSourceModeFor(request.source_mode)
  const topbarGenerateDisabled =
    workerBusy ||
    (!project && !hasLearningPointResult && !sourceReady) ||
    (hasLearningPointResult && selectedLearningPointCount === 0)
  const primaryGenerateAction = hasLearningPointResult ? generateCardsFromLearningPoints : generate
  const primaryGenerateLabel =
    project
      ? '重新抽取（可能复用缓存）'
      : hasLearningPointResult
        ? generationConfirmOpen
          ? `确认区已打开 · ${generationQueueSummary.count || selectedLearningPointCount} 张`
          : `生成 APKG · ${selectedLearningPointCount} 张`
        : '抽取学习点'
  const reviewTemplateLabel = request.review_density === 'fast' ? '快速复读' : '完整复读'

  return (
    <div className="app-shell">
      <Topbar
        appBusy={appBusy}
        generateDisabled={topbarGenerateDisabled}
        hasExportableCards={selectedExportableCardCount > 0}
        hasProject={Boolean(project)}
        inspectorActionLabel={inspectorActionLabel}
        inspectorActive={inspectorState === 'open' || inspectorState === 'collapsing' || inspectorSheetOpen}
        isCancelling={isCancelling}
        showGenerateButton={!hasLearningPointResult}
        status={status}
        statusTone={statusTone}
        workerBusy={workerBusy}
        onCancelCurrentWorker={cancelCurrentWorker}
        onDoubleClick={handleTopbarDoubleClick}
        onExport={exportApkg}
        generateLabel={primaryGenerateLabel}
        onGenerate={primaryGenerateAction}
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
            request={request}
            requestEditedDuringRun={requestEditedDuringRun}
            status={status}
            statusTone={statusTone}
            workerBusy={workerBusy}
            workerErrorActions={workerErrorActions}
            workerProgress={workerProgress}
            onCheckEnv={checkEnv}
            onCloseSheet={() => setInspectorState('collapsed')}
            onExport={exportApkg}
            onExtractLearningPointsWithoutCache={extractLearningPointsWithoutCache}
            onGenerate={primaryGenerateAction}
            onOpenEnvSettings={() => {
              setSettingsTab('env')
              setSettingsOpen(true)
            }}
            onPatchRequest={patchRequest}
            onPreviewRateChange={setPreviewRate}
            onRepairEnv={repairEnv}
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
          mimoOpenAiBaseUrl: MIMO_OPENAI_BASE_URL,
          mimoTextModels: [...mimoTextModels, ...qwenTextModels, ...deepseekTextModels, ...geminiVertexTextModels],
          savedApiProfiles,
          showCapabilities,
          onApplyApiPreset: applyApiPreset,
          onApplySavedApiProfile: applySavedApiProfile,
          onPatchApi: patchApi,
          onSaveApiProfile: saveCurrentApiProfile,
          onSetShowCapabilities: setShowCapabilities,
          onTestApi: testApi,
        }}
        dialogRef={settingsDialogRef}
        envSettings={{ appBusy, envRepairing, envRepairResult, envStatus, onCheckEnv: checkEnv, onRepairEnv: repairEnv }}
        motionDuration={motionDuration}
        open={settingsOpen}
        prefersReducedMotion={Boolean(prefersReducedMotion)}
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
        onClose={() => setSettingsOpen(false)}
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
