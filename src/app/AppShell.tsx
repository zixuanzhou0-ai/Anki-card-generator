import { InspectorPanel } from '../features/app/InspectorPanel'
import { Topbar } from '../features/app/Topbar'
import { ReviewWorkspace } from '../features/review/ReviewWorkspace'
import { SettingsDialog } from '../features/settings/SettingsDialog'
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
    cardOptions,
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
    handleTopbarDoubleClick,
    handleWorkerErrorAction,
    inspectorActionLabel,
    inspectorSheetOpen,
    inspectorState,
    isCancelling,
    isDesktopRuntime,
    lastExport,
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
    toggleCardType,
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

  return (
    <div className="app-shell">
      <Topbar
        appBusy={appBusy}
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
        onGenerate={generate}
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
            cardOptions={cardOptions}
            cardTypes={request.card_types}
            contentOptions={contentOptions}
            diagnosticCount={
              (qualityFunnel.candidate_only_learning_point_count ?? 0) +
              (qualityFunnel.hidden_duplicate_learning_point_count ?? 0) +
              (qualityFunnel.hard_blocked_learning_point_count ?? 0)
            }
            documentFocusOptions={documentFocusOptions}
            generatedCardCount={qualityCounts.total}
            hasExportableCards={selectedCardCount > 0}
            hasProject={Boolean(project)}
            inspectorSheetOpen={inspectorSheetOpen}
            languageFocusOptions={languageFocusOptions}
            levels={levels}
            previewRate={previewRate}
            selectedCardCount={selectedCardCount}
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
            onCloseSheet={() => setInspectorState('collapsed')}
            onExport={exportApkg}
            onGenerate={generate}
            onPatchRequest={patchRequest}
            onPreviewRateChange={setPreviewRate}
            onSelectCurrentLevel={selectCurrentLevel}
            onSelectPath={selectPath}
            onSelectSourceMode={selectSourceMode}
            onSelectTemplate={selectTemplate}
            onToggleCardType={toggleCardType}
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
            onSelectSegment={selectSegment}
            onSetCardsEnabled={setCardsEnabled}
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
