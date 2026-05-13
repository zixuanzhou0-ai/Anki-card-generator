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
    activeSegment,
    activeSegmentId,
    activeSegmentVideoSrc,
    activeTemplate,
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
    appBusy,
    badgeText,
    applyApiPreset,
    applyCollectionPreset,
    applyTtsPreset,
    cancelCurrentWorker,
    capabilityHelp,
    capabilityLabels,
    cardOptions,
    checkEnv,
    contentOptions,
    envStatus,
    exportApkg,
    featuredApiPresets,
    featuredTtsPresets,
    generate,
    handleTopbarDoubleClick,
    handleWorkerErrorAction,
    inspectorActionLabel,
    inspectorSheetOpen,
    inspectorState,
    isCancelling,
    isDesktopRuntime,
    lastExport,
    levels,
    MIMO_OPENAI_BASE_URL,
    MIMO_TOKEN_PLAN_SGP_BASE_URL,
    mimoTextModels,
    mimoTtsModels,
    mimoTtsVoices,
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
    runWindowAction,
    secretPrefs,
    segmentFilter,
    segmentReviewCounts,
    selectedCardCount,
    selectCardsByQuality,
    selectCurrentLevel,
    selectPath,
    selectSegment,
    selectSourceMode,
    selectTemplate,
    setCardsEnabled,
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
    toggleInspector,
    toggleRememberSecret,
    tts,
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
        inspectorActive={inspectorState === 'open' || inspectorSheetOpen}
        isCancelling={isCancelling}
        projectSummary={
          project
            ? {
                reviewCount: qualityCounts.review,
                selectedCardLabel: badgeText(selectedCardCount),
                segmentCount: project.segments.length,
                templateLabel: activeTemplate?.label ?? '沉浸视频',
              }
            : undefined
        }
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
            activeTemplateLabel={activeTemplate?.label ?? '沉浸视频'}
            appBusy={appBusy}
            cardOptions={cardOptions}
            cardTypes={request.card_types}
            contentOptions={contentOptions}
            inspectorSheetOpen={inspectorSheetOpen}
            levels={levels}
            readiness={readiness}
            request={request}
            requestEditedDuringRun={requestEditedDuringRun}
            status={status}
            statusTone={statusTone}
            templateId={request.template_id}
            templateOptions={templateOptions}
            workerBusy={workerBusy}
            workerErrorActions={workerErrorActions}
            workerProgress={workerProgress}
            onApplyCollectionPreset={applyCollectionPreset}
            onCloseSheet={() => setInspectorState('collapsed')}
            onPatchRequest={patchRequest}
            onSelectCurrentLevel={selectCurrentLevel}
            onSelectPath={selectPath}
            onSelectSourceMode={selectSourceMode}
            onSelectTemplate={selectTemplate}
            onToggleCardType={toggleCardType}
            onToggleCollectionLevel={toggleCollectionLevel}
            onToggleContent={toggleContent}
            onWorkerErrorAction={handleWorkerErrorAction}
          />

          <ReviewWorkspace
            activeSegment={activeSegment}
            activeSegmentId={activeSegmentId}
            activeSegmentVideoSrc={activeSegmentVideoSrc}
            activeTemplateLabel={activeTemplate?.label ?? '沉浸视频'}
            ankiVerifying={ankiVerifying}
            ankiVerifyResult={ankiVerifyResult}
            appBusy={appBusy}
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
            onGenerate={generate}
            onOpenAnkiImport={openAnkiImport}
            onOpenSettings={() => setSettingsOpen(true)}
            onPreviewRateChange={setPreviewRate}
            onRevealExport={revealExport}
            onSegmentFilterChange={setSegmentFilter}
            onSelectCardsByQuality={selectCardsByQuality}
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
          appBusy,
          capabilityHelp,
          capabilityLabels,
          featuredApiPresets,
          mimoOpenAiBaseUrl: MIMO_OPENAI_BASE_URL,
          mimoTextModels,
          secretPrefs,
          showAdvancedApi,
          showCapabilities,
          onApplyApiPreset: applyApiPreset,
          onPatchApi: patchApi,
          onSetShowAdvancedApi: setShowAdvancedApi,
          onSetShowCapabilities: setShowCapabilities,
          onTestApi: testApi,
          onToggleRememberModelKey: () => toggleRememberSecret('model'),
        }}
        dialogRef={settingsDialogRef}
        envSettings={{ appBusy, envStatus, onCheckEnv: checkEnv }}
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
          secretPrefs,
          showAdvancedTts,
          tts,
          ttsTestMessage,
          ttsTestMeta,
          ttsTestOk: ttsTestResult?.ok,
          ttsTestTitle,
          ttsTestTone,
          ttsTesting,
          onApplyTtsPreset: applyTtsPreset,
          onPatchTts: patchTts,
          onSetShowAdvancedTts: setShowAdvancedTts,
          onTestTts: testTts,
          onToggleRememberTtsKey: () => toggleRememberSecret('tts'),
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
