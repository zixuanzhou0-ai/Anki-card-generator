import { InspectorPanel } from '../features/app/InspectorPanel'
import { Topbar } from '../features/app/Topbar'
import { ReviewWorkspace } from '../features/review/ReviewWorkspace'
import { SettingsDialog } from '../features/settings/SettingsDialog'
import { defaultSelectedLearningPointIds } from '../domain/learningPoints'
import type { AppController } from './useAppController'

type AppShellProps = {
  controller: AppController
}

export function AppShell({ controller }: AppShellProps) {
  const {
    activeWorkspaceStage,
    activeSegment,
    activeSegmentId,
    activeSegmentVideoSrc,
    activeTemplate,
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
    apiProfileDirty,
    apiProfileStatus,
    appBusy,
    applyApiPreset,
    applyCollectionPreset,
    applySavedApiProfile,
    applySavedTtsProfile,
    applyTtsPreset,
    cancelCurrentWorker,
    capabilityHelp,
    capabilityLabels,
    checkEnv,
    contentOptions,
    deepseekTextModels,
    documentFocusOptions,
    envRepairing,
    envRepairResult,
    envStatus,
    exportApkg,
    featuredApiPresets,
    featuredTtsPresets,
    geminiVertexTextModels,
    generate,
    generateCardsFromLearningPoints,
    handleTopbarDoubleClick,
    handleWorkerErrorAction,
    inspectorActionLabel,
    inspectorSheetOpen,
    inspectorState,
    isCancelling,
    isDesktopRuntime,
    lastExport,
    learningPointResult,
    languageFocusOptions,
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
    request,
    requestEditedDuringRun,
    responsiveMode,
    revealExport,
    repairEnv,
    runWindowAction,
    savedApiProfiles,
    savedTtsProfiles,
    saveCurrentApiProfile,
    saveCurrentTtsProfile,
    selectionStrategyOptions,
    segmentFilter,
    segmentReviewCounts,
    selectedCardCount,
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
    setShowAdvancedApi,
    setShowAdvancedTts,
    setShowCapabilities,
    settingsDialogRef,
    settingsOpen,
    settingsTab,
    showAdvancedApi,
    showAdvancedTts,
    showCapabilities,
    startWindowDrag,
    startWindowResize,
    status,
    statusTone,
    templateOptions,
    testApi,
    testTts,
    toggleCollectionLevel,
    toggleContent,
    toggleDocumentFocus,
    toggleLanguageFocus,
    toggleInspector,
    tts,
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
  const hasLearningPointResult = Boolean(learningPointResult && !project)
  const sourceReady = readiness.find((item) => item.id === 'source')?.done ?? false
  const topbarGenerateDisabled =
    workerBusy ||
    (!project && !hasLearningPointResult && !sourceReady) ||
    (hasLearningPointResult && selectedLearningPointCount === 0)
  const primaryGenerateAction = hasLearningPointResult ? generateCardsFromLearningPoints : generate
  const primaryGenerateLabel =
    request.source_mode === 'document'
      ? project
        ? '重新生成'
        : '生成卡片'
      : project
        ? '重新抽取'
        : hasLearningPointResult
          ? '生成选中卡片'
          : '抽取学习点'

  return (
    <div className="app-shell">
      <Topbar
        appBusy={appBusy}
        generateDisabled={topbarGenerateDisabled}
        hasExportableCards={selectedCardCount > 0}
        hasProject={Boolean(project)}
        inspectorActionLabel={inspectorActionLabel}
        inspectorActive={inspectorState === 'open' || inspectorState === 'collapsing' || inspectorSheetOpen}
        isCancelling={isCancelling}
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
            activeTemplateLabel={activeTemplate?.label ?? '沉浸视频'}
            appBusy={appBusy}
            contentOptions={contentOptions}
            diagnosticCount={
              (qualityFunnel.candidate_only_learning_point_count ?? 0) +
              (qualityFunnel.hidden_duplicate_learning_point_count ?? 0) +
              (qualityFunnel.hard_blocked_learning_point_count ?? 0)
            }
            documentFocusOptions={documentFocusOptions}
            generatedCardCount={qualityCounts.total}
            hasExportableCards={selectedCardCount > 0}
            hasLearningPointResult={hasLearningPointResult}
            hasProject={Boolean(project)}
            inspectorSheetOpen={inspectorSheetOpen}
            languageFocusOptions={languageFocusOptions}
            levels={levels}
            previewRate={previewRate}
            selectedCardCount={selectedCardCount}
            selectedLearningPointCount={selectedLearningPointCount}
            readiness={readiness}
            request={request}
            requestEditedDuringRun={requestEditedDuringRun}
            status={status}
            statusTone={statusTone}
            templateId={request.template_id}
            templateOptions={templateOptions}
            selectionStrategyOptions={selectionStrategyOptions}
            workerBusy={workerBusy}
            workerErrorActions={workerErrorActions}
            workerProgress={workerProgress}
            onApplyCollectionPreset={applyCollectionPreset}
            onCheckEnv={checkEnv}
            onCloseSheet={() => setInspectorState('collapsed')}
            onExport={exportApkg}
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
            onToggleCollectionLevel={toggleCollectionLevel}
            onToggleContent={toggleContent}
            onToggleDocumentFocus={toggleDocumentFocus}
            onToggleLanguageFocus={toggleLanguageFocus}
            onWorkspaceStageChange={setActiveWorkspaceStage}
            onWorkerErrorAction={handleWorkerErrorAction}
          />

          <ReviewWorkspace
            activeSegment={activeSegment}
            activeSegmentId={activeSegmentId}
            activeSegmentVideoSrc={activeSegmentVideoSrc}
            activeTemplateLabel={activeTemplate?.label ?? '沉浸视频'}
            ankiVerifying={ankiVerifying}
            ankiVerifyResult={ankiVerifyResult}
            lastExport={lastExport}
            language={request.language}
            level={request.level}
            learningPointResult={learningPointResult}
            maxSegments={request.max_segments}
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
            segmentFilter={segmentFilter}
            segmentReviewCounts={segmentReviewCounts}
            sourceMode={request.source_mode}
            templateId={request.template_id}
            visibleSegments={visibleSegments}
            workerBusy={workerBusy}
            workerProgress={workerProgress}
            status={status}
            onOpenAnkiImport={openAnkiImport}
            onRevealExport={revealExport}
            onSegmentFilterChange={setSegmentFilter}
            onInvertCardSelection={invertCardSelection}
            onGenerateCardsFromLearningPoints={generateCardsFromLearningPoints}
            onSelectSegment={selectSegment}
            onSetCardsEnabled={setCardsEnabled}
            onSetSelectedLearningPointIds={setSelectedLearningPointIds}
            onSelectDefaultLearningPoints={() =>
              setSelectedLearningPointIds(
                defaultSelectedLearningPointIds(learningPointResult?.learning_points ?? [], { reviewDensity: request.review_density }),
              )
            }
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
          showAdvancedApi,
          showCapabilities,
          onApplyApiPreset: applyApiPreset,
          onApplySavedApiProfile: applySavedApiProfile,
          onPatchApi: patchApi,
          onSaveApiProfile: saveCurrentApiProfile,
          onSetShowAdvancedApi: setShowAdvancedApi,
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
