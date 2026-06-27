import { useEffect, useMemo, useRef, useState } from 'react'
import type { MouseEvent } from 'react'
import { listen } from '@tauri-apps/api/event'
import { useReducedMotion } from 'motion/react'

import type {
  AnkiVerifyResult,
  ApiConfig,
  ApiPreset,
  ApiTestResult,
  Card,
  CardKind,
  ContentToggles,
  DocumentFocus,
  EnvRepairResult,
  EnvRepairTarget,
  EnvStatus,
  ExportResult,
  GenerateRequest,
  InspectorState,
  LanguageFocus,
  Level,
  Project,
  QualityFunnel,
  ResizeDirection,
  ResponsiveMode,
  SavedApiProfile,
  SavedTtsProfile,
  SegmentFilter,
  SettingsTab,
  SourceMode,
  TemplateId,
  TtsConfig,
  TtsPreset,
  TtsTestResult,
  WorkerFinishedEvent,
  WorkerOperation,
  WorkerProgress,
  WorkspaceStage,
} from '../domain/types'
import { createDemoProject } from '../domain/demoProject'
import { batchItemsForSource, buildBatchPackage, createLocalVideoBatchItems } from '../domain/batch'
import {
  advancedApiPresets,
  advancedTtsPresets,
  capabilityHelp,
  capabilityLabels,
  cardOptions,
  contentOptions,
  defaultCollectionLevels,
  documentFocusOptions,
  deepseekTextModels,
  featuredApiPresets,
  featuredTtsPresets,
  geminiVertexTextModels,
  languageFocusOptions,
  levelOrder,
  levels,
  MIMO_OPENAI_BASE_URL,
  MIMO_TOKEN_PLAN_SGP_BASE_URL,
  mimoTextModels,
  mimoTtsModels,
  mimoTtsVoices,
  qwenTextModels,
  qwenTtsModels,
  qwenTtsVoices,
  normalizeCollectionLevels,
  PROJECT_STORAGE_KEY,
  publicTemplateIdFor,
  REQUEST_STORAGE_KEY,
  selectionStrategyOptions,
  templateOptions,
} from '../domain/options'
import { materializeLearningPointInventory } from '../domain/inventoryDrafts'
import {
  applyUsableCardSelection,
  getExportSelectionStats,
  segmentMatchesFilter,
  isUsableCardForExport,
} from '../domain/quality'
import {
  ankiOpenImportRequestedStatusMessage,
  ankiOpenImportStartingStatusMessage,
  ankiVerifyStartingStatusMessage,
  ankiVerifyWorkerStartedMessage,
  buildAnkiVerifyPayload,
  exportResultForAnkiVerify,
  prepareAnkiVerifyStart,
} from './ankiVerifyState'
import {
  APKG_EXPORT_DIRECTORY_DIALOG_TITLE,
  buildProjectExportPayloadProject,
  defaultExportDirectoryForProject,
  defaultExportDirectoryForRequest,
  exportStartingStatusMessage,
  exportWorkerStartedProgressMessage,
  exportWorkerStartedStatusMessage,
  normalizeProjectForExportWorker,
  prepareProjectForExport,
  releaseApkgOutputGuardForProject,
  releaseTargetRequiresColdMediaCacheReadsDisabled,
  type ReleaseApkgTarget,
  videoExportTtsBlockReason,
} from './exportPreparation'
import {
  countSelectedCards,
  getQualityCounts,
  getQualityDiagnostics,
  getQualityFunnel,
  getSegmentReviewCounts,
} from '../domain/projectMetrics'
import type { WorkerErrorActionId } from '../domain/workerErrors'
import { getWorkerErrorActions } from '../domain/workerErrors'
import { buildReadinessItems, buildTtsReadinessDetail, isEnvironmentReadyForGeneration } from './readiness'
import { isSourceInputReady } from '../domain/sourceValidation'
import type { LearningPointExtractionResult } from '../domain/learningPoints'
import {
  defaultSelectedLearningPointIds,
  learningPointGenerationBatchSize,
  selectedLearningPoints,
} from '../domain/learningPoints'
import {
  isMimoApiConfig,
  isMimoTokenPlanBase,
  isMimoTokenPlanKey,
  normalizeApiConfigForRequest,
  resolveGenerateApiConfig,
  resolveTtsConfig,
  isQwenApiConfig,
  validateApiConfigForRequest,
  validateTtsConfigForRequest,
} from '../services/apiConfig'
import {
  apiAuthMode,
  apiConfigMatchesProfile,
  apiProfileIdFromConfig,
  buildSavedApiProfile,
  buildSavedTtsProfile,
  loadSavedApiProfiles,
  loadSavedTtsProfiles,
  profileSecretKey,
  saveSavedApiProfiles,
  saveSavedTtsProfiles,
  ttsAuthMode,
  ttsConfigMatchesProfile,
  ttsProfileIdFromConfig,
  upsertSavedApiProfile,
  upsertSavedTtsProfile,
} from '../services/settingsProfiles'
import { loadSavedRequest, projectMatchesRequest, stripRequestSecrets } from '../services/projectStorage'
import {
  cancelWorkerJob,
  checkBootstrapEnv,
  getWorkerJobStatus,
  loadSecret,
  readWorkerJobResult,
  recordRendererError,
  repairBootstrapEnv,
  runWorker,
  saveSecret,
  startWorkerJob,
} from '../services/tauriWorker'
import { isTauriRuntime } from '../services/runtime'
import {
  openAnkiImport as openAnkiImportFile,
  defaultExportDirectory,
  listDirectoryFiles,
  revealPath,
  selectDirectory,
  selectSingleFile,
  suggestSubtitlePath,
  toAssetUrl,
} from '../services/nativeShell'
import { redactSensitiveText } from '../services/redaction'
import {
  runWindowAction as runNativeWindowAction,
  startWindowDrag as startNativeWindowDrag,
  startWindowResize as startNativeWindowResize,
} from '../services/windowChrome'
import {
  buildDirectGenerationPayload,
  buildLearningPointExtractionPayload,
  buildLearningPointGenerationPayload,
} from './learningPointGenerationPayload'
import {
  generatedLearningPointIdsFromProject,
  generationBatchProgressSnapshot,
  mergeGeneratedBatchProject,
  retryLearningPointIdsAfterBatchFailure,
} from './generationBatch'
import type { GenerationBatchProgress, GenerationBatchRuntime } from './generationBatch'
import {
  fallbackWorkerOperationFromFinish,
  resolveWorkerFinishedResult,
  workerFinishInvalidatedByEditedRequest,
  workerFinishMatchesActiveJob,
} from './workerFinished'
import { requestPatchInvalidatesExportArtifacts, requestPatchInvalidatesLearningArtifacts } from './requestInvalidation'
import { clearStaleReviewWorkerError, workerFailureStatusMessage } from './exportFailureState'
import { compactExportResultForUi } from './exportResultState'
import { buildAppStatusTone } from './appStatusTone'
import { buildInspectorUiState } from './inspectorUiState'
import {
  cleanLocalPath,
  directGenerationSourceError,
  learningPointExtractionSourceError,
  localPathAccessPromptForRequest,
  mergeRepairResults,
  normalizeProjectTemplateForPublicSource,
  pathLines,
  stripProjectRuntimeSecrets,
  titleFromPath,
  workerFailureDetailsSummary,
} from './controllerHelpers'
import { buildGenerationQueueSummary } from './generationQueueSummary'
import { buildGenerationRunState } from './generationRunState'
import { buildReleaseEvidenceSummary } from './releaseEvidenceSummary'
import {
  buildReleaseObservedRawSnapshotHandoffArtifact,
  buildReleaseObservedSnapshotFromRawCapture,
  emptyReleaseEvidenceRawSnapshot,
  reduceReleaseEvidenceRawSnapshot,
  type BuildReleaseObservedSnapshotFromRawCaptureInput,
  type ReleaseEvidenceRawSnapshotEvent,
} from './releaseEvidenceObservedCapture'
import { buildSettingsProfileStatus } from './settingsProfileStatus'
import { buildApiTestStatus, buildEffectiveApiTestResult, buildTtsTestStatus } from './settingsTestStatus'

const INSPECTOR_COLLAPSE_MS = 130
type SourcePathKind = 'video' | 'subtitle' | 'video-folder'

type StartExportOptions = {
  projectOverride?: Project
  outputDir?: string
  auto?: boolean
}

function waitForNextPaint() {
  return new Promise<void>((resolve) => {
    if (typeof window === 'undefined' || typeof window.requestAnimationFrame !== 'function') {
      globalThis.setTimeout(resolve, 0)
      return
    }
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => resolve())
    })
  })
}

type ReleaseApkgBlockedGuard = Extract<ReturnType<typeof releaseApkgOutputGuardForProject>, { status: 'blocked' }>
type ReleaseExportExpectedTarget = Pick<ReleaseApkgTarget, 'caseId' | 'runSegment' | 'outputDir' | 'canonicalApkgPath'>

function releaseApkgTargetGuardFailureEvent(guard: ReleaseApkgBlockedGuard): WorkerFinishedEvent {
  return {
    job_id: `release-apkg-target-${Date.now()}`,
    command: 'export',
    ok: false,
    error: guard.statusMessage,
    error_code: 'RELEASE_APKG_TARGET_INVALID',
    stage: 'select_output_dir',
    retryable: true,
    details: {
      release_case_id: guard.releaseCaseId,
      selected_output_dir: guard.selectedOutputDir,
      expected_directory_pattern: guard.expectedDirectoryPattern,
      selected_release_case_id: guard.releaseTarget?.caseId ?? null,
      selected_canonical_apkg_path: guard.releaseTarget?.canonicalApkgPath ?? null,
    },
  }
}

function normalizedComparablePath(pathValue: string | null | undefined): string {
  return typeof pathValue === 'string'
    ? pathValue.trim().replace(/[/\\]+/g, '/').replace(/\/+$/, '').toLowerCase()
    : ''
}

function releaseApkgReturnedPathGuardFailureEvent({
  jobId,
  expected,
  actualApkgPath,
}: {
  jobId: string
  expected: ReleaseExportExpectedTarget
  actualApkgPath: string | null | undefined
}): WorkerFinishedEvent {
  return {
    job_id: jobId,
    command: 'export',
    ok: false,
    error:
      `导出已停止：worker 返回的 APKG 路径不是本次 release case 的 canonical 路径。` +
      ` expected=${expected.canonicalApkgPath} actual=${actualApkgPath || 'missing'}`,
    error_code: 'RELEASE_APKG_TARGET_INVALID',
    stage: 'export_result',
    retryable: true,
    details: {
      release_case_id: expected.caseId,
      release_run_segment: expected.runSegment,
      selected_output_dir: expected.outputDir,
      expected_canonical_apkg_path: expected.canonicalApkgPath,
      returned_apkg_path: actualApkgPath ?? null,
    },
  }
}

export function useAppController() {
  const initialRequest = useMemo(() => loadSavedRequest(), [])
  const [request, setRequest] = useState<GenerateRequest>(initialRequest)
  const [project, setProject] = useState<Project | null>(null)
  const [learningPointResult, setLearningPointResult] = useState<LearningPointExtractionResult | null>(null)
  const [selectedLearningPointIds, setSelectedLearningPointIds] = useState<Set<string>>(() => new Set())
  const [generationConfirmOpen, setGenerationConfirmOpen] = useState(false)
  const [generationQueueSelectedIds, setGenerationQueueSelectedIds] = useState<Set<string> | null>(null)
  const [envStatus, setEnvStatus] = useState<EnvStatus | null>(null)
  const [envRepairResult, setEnvRepairResult] = useState<EnvRepairResult | null>(null)
  const [envRepairing, setEnvRepairing] = useState(false)
  const [status, setStatus] = useState('准备生成 Anki 卡片。')
  const [busy, setBusy] = useState(false)
  const [workerOperation, setWorkerOperation] = useState<WorkerOperation>({ status: 'idle' })
  const [requestEditedDuringRun, setRequestEditedDuringRun] = useState(false)
  const [activeSegmentId, setActiveSegmentId] = useState<string | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [apiTesting, setApiTesting] = useState(false)
  const [apiTestResult, setApiTestResult] = useState<ApiTestResult | null>(null)
  const [ttsTesting, setTtsTesting] = useState(false)
  const [ttsTestResult, setTtsTestResult] = useState<TtsTestResult | null>(null)
  const [lastExport, setLastExport] = useState<ExportResult | null>(null)
  const lastExportFullRef = useRef<ExportResult | null>(null)
  const [lastWorkerError, setLastWorkerError] = useState<WorkerFinishedEvent | null>(null)
  const [ankiVerifying, setAnkiVerifying] = useState(false)
  const [ankiVerifyResult, setAnkiVerifyResult] = useState<AnkiVerifyResult | null>(null)
  const [previewRate, setPreviewRate] = useState(0.75)
  const [workerProgress, setWorkerProgress] = useState<WorkerProgress | null>(null)
  const [generationBatchProgress, setGenerationBatchProgress] = useState<GenerationBatchProgress | null>(null)
  const [cardGenerationCacheNamespace, setCardGenerationCacheNamespace] = useState<string | null>(null)
  const [showAdvancedApi, setShowAdvancedApi] = useState(false)
  const [showAdvancedTts, setShowAdvancedTts] = useState(false)
  const [showCapabilities, setShowCapabilities] = useState(false)
  const [settingsTab, setSettingsTab] = useState<SettingsTab>('api')
  const [savedApiProfiles, setSavedApiProfiles] = useState<SavedApiProfile[]>(() => loadSavedApiProfiles())
  const [savedTtsProfiles, setSavedTtsProfiles] = useState<SavedTtsProfile[]>(() => loadSavedTtsProfiles())
  const [apiProfileDirty, setApiProfileDirty] = useState(false)
  const [ttsProfileDirty, setTtsProfileDirty] = useState(false)
  const [segmentFilter, setSegmentFilter] = useState<SegmentFilter>('all')
  const [responsiveMode, setResponsiveMode] = useState<ResponsiveMode>('wide')
  const [inspectorState, setInspectorState] = useState<InspectorState>('open')
  const [activeWorkspaceStage, setActiveWorkspaceStage] = useState<WorkspaceStage>(project ? 'review' : 'source')
  const prefersReducedMotion = useReducedMotion()
  const previewPanelRef = useRef<HTMLElement | null>(null)
  const settingsDialogRef = useRef<HTMLElement | null>(null)
  const inspectorCollapseTimerRef = useRef<number | null>(null)
  const workerOperationRef = useRef<WorkerOperation>(workerOperation)
  const workerProgressRef = useRef<WorkerProgress | null>(workerProgress)
  const requestEditedDuringRunRef = useRef(requestEditedDuringRun)
  const learningPointResultRef = useRef<LearningPointExtractionResult | null>(learningPointResult)
  const lastLearningPointResultRef = useRef<LearningPointExtractionResult | null>(null)
  const generationRetryBaseProjectRef = useRef<Project | null>(null)
  const generationBatchRef = useRef<GenerationBatchRuntime | null>(null)
  const generationAutoExportOutputDirRef = useRef<string | null>(null)
  const releaseEvidenceRawSnapshotRef = useRef(emptyReleaseEvidenceRawSnapshot())
  const activeAnkiVerifyApkgPathRef = useRef<string | null>(null)
  const releaseExportTargetsByJobIdRef = useRef<Map<string, ReleaseExportExpectedTarget>>(new Map())
  const handledWorkerFinishIdsRef = useRef<Set<string>>(new Set())
  const processingWorkerFinishIdsRef = useRef<Set<string>>(new Set())
  const handleWorkerFinishedRef = useRef<(payload: WorkerFinishedEvent) => Promise<void>>(async () => {})

  const captureReleaseEvidenceRawSnapshot = (event: ReleaseEvidenceRawSnapshotEvent) => {
    releaseEvidenceRawSnapshotRef.current = reduceReleaseEvidenceRawSnapshot(
      releaseEvidenceRawSnapshotRef.current,
      event,
    )
  }

  const clearStaleReviewResults = () => {
    lastExportFullRef.current = null
    activeAnkiVerifyApkgPathRef.current = null
    captureReleaseEvidenceRawSnapshot({ type: 'invalidate', scope: 'export_and_verify' })
    setLastExport(null)
    setAnkiVerifyResult(null)
    setLastWorkerError(clearStaleReviewWorkerError)
  }

  const clearLearningArtifactsForRequestChange = () => {
    setProject(null)
    setLearningPointResult(null)
    setSelectedLearningPointIds(new Set())
    setActiveSegmentId(null)
    setWorkerProgress(null)
    setGenerationConfirmOpen(false)
    setGenerationQueueSelectedIds(null)
    setGenerationBatchRuntime(null)
    generationRetryBaseProjectRef.current = null
    generationAutoExportOutputDirRef.current = null
    releaseEvidenceRawSnapshotRef.current = emptyReleaseEvidenceRawSnapshot()
    activeAnkiVerifyApkgPathRef.current = null
    clearStaleReviewResults()
  }

  const selectedCardCount = useMemo(() => countSelectedCards(project), [project])
  const exportSelectionStats = useMemo(() => getExportSelectionStats(project), [project])
  const qualityCounts = useMemo(() => getQualityCounts(project), [project])
  const qualityDiagnostics = useMemo(
    () => getQualityDiagnostics(project, qualityCounts.recommended),
    [project, qualityCounts.recommended],
  )
  const qualityFunnel = useMemo<QualityFunnel>(
    () => getQualityFunnel(project, qualityCounts, qualityDiagnostics),
    [project, qualityCounts, qualityDiagnostics],
  )
  const segmentReviewCounts = useMemo(() => getSegmentReviewCounts(project), [project])

  const visibleSegments = useMemo(() => {
    return project?.segments.filter((segment) => segmentMatchesFilter(segment, segmentFilter)) ?? []
  }, [project, segmentFilter])

  const selectedLearningPointCount = useMemo(() => {
    if (!learningPointResult) return 0
    return selectedLearningPoints(learningPointResult.learning_points, selectedLearningPointIds).length
  }, [learningPointResult, selectedLearningPointIds])

  const activeGenerationQueueIds = generationQueueSelectedIds ?? selectedLearningPointIds
  const generationQueuePoints = useMemo(() => {
    if (!learningPointResult) return []
    return selectedLearningPoints(learningPointResult.learning_points, activeGenerationQueueIds)
  }, [activeGenerationQueueIds, learningPointResult])
  const generationQueueSummary = useMemo(
    () => buildGenerationQueueSummary({ generationQueuePoints, generationBatchProgress, request }),
    [generationQueuePoints, generationBatchProgress, request],
  )

  const activeTemplate = templateOptions.find((template) => template.id === request.template_id)
  const localVideoPath = cleanLocalPath(request.video_path)
  const localSubtitlePath = cleanLocalPath(request.subtitle_path)
  const sourceReady = isSourceInputReady(request)
  const tts = request.api_config.tts_config
  const ttsRequired = request.source_mode !== 'document'
  const activeApiProfileId = apiProfileIdFromConfig(request.api_config)
  const activeTtsProfileId = ttsProfileIdFromConfig(tts)
  const activeApiProfile = savedApiProfiles.find((profile) => profile.id === activeApiProfileId)
  const activeTtsProfile = savedTtsProfiles.find((profile) => profile.id === activeTtsProfileId)
  const activeApiKeySaved = Boolean(activeApiProfile?.has_api_key && apiAuthMode(request.api_config) === 'api_key')
  const activeTtsKeySaved = Boolean(activeTtsProfile?.has_api_key && ttsAuthMode(tts) === 'api_key')
  const loadApiConfigForWorker = async (apiConfig: ApiConfig = request.api_config): Promise<ApiConfig> => {
    const normalized = normalizeApiConfigForRequest(apiConfig)
    if (apiAuthMode(normalized) !== 'api_key' || normalized.api_key.trim()) {
      return normalized
    }
    const profileId = apiProfileIdFromConfig(normalized)
    const profile = savedApiProfiles.find((item) => item.id === profileId && apiConfigMatchesProfile(normalized, item))
    if (!profile?.has_api_key) return normalized
    const apiKey = await loadSecret(profileSecretKey('api', profile.id))
    return apiKey ? { ...normalized, api_key: apiKey } : normalized
  }
  const loadTtsConfigForWorker = async (
    ttsConfig: TtsConfig = request.api_config.tts_config,
    apiConfig: ApiConfig = request.api_config,
  ): Promise<{ apiConfig: ApiConfig; ttsConfig: TtsConfig }> => {
    const apiWithSecret = await loadApiConfigForWorker(apiConfig)
    const resolvedTts = resolveTtsConfig(ttsConfig, apiWithSecret)
    if (ttsAuthMode(resolvedTts) !== 'api_key' || resolvedTts.api_key.trim()) {
      return { apiConfig: apiWithSecret, ttsConfig: resolvedTts }
    }
    const profileId = ttsProfileIdFromConfig(resolvedTts)
    const profile = savedTtsProfiles.find((item) => item.id === profileId && ttsConfigMatchesProfile(resolvedTts, item))
    if (!profile?.has_api_key) return { apiConfig: apiWithSecret, ttsConfig: resolvedTts }
    const ttsKey = await loadSecret(profileSecretKey('tts', profile.id))
    return {
      apiConfig: apiWithSecret,
      ttsConfig: ttsKey ? { ...resolvedTts, api_key: ttsKey } : resolvedTts,
    }
  }
  const patchResolvedApiForState = (resolvedApi: ApiConfig, currentApi: ApiConfig) => {
    patchRequest({
      api_config: {
        ...resolvedApi,
        api_key: currentApi.api_key,
        tts_config: currentApi.tts_config,
      },
    })
  }
  const confirmLocalPathAccessForRequest = (generateRequest: GenerateRequest): boolean => {
    const prompt = localPathAccessPromptForRequest(generateRequest)
    if (!prompt) return true
    const ok = !isTauriRuntime() || window.confirm(prompt)
    if (!ok) {
      setStatus('已取消本地路径读取。请用文件选择器重新选择素材，或再次确认后生成。')
      return false
    }
    generateRequest.local_path_access_confirmed = true
    patchRequest({ local_path_access_confirmed: true })
    return true
  }
  const apiProfileSaved =
    Boolean(activeApiProfile && apiConfigMatchesProfile(request.api_config, activeApiProfile)) && !apiProfileDirty
  const ttsProfileSaved =
    Boolean(activeTtsProfile && ttsConfigMatchesProfile(tts, activeTtsProfile)) && !ttsProfileDirty
  const apiProfileDisplayStatus = buildSettingsProfileStatus({
    profile: activeApiProfile,
    profileSaved: apiProfileSaved,
    auth: apiAuthMode(request.api_config),
    notSavedLabel: '未保存到我的模型',
  })
  const ttsProfileDisplayStatus = buildSettingsProfileStatus({
    profile: activeTtsProfile,
    profileSaved: ttsProfileSaved,
    auth: ttsAuthMode(tts),
    notSavedLabel: '未保存到我的语音',
  })
  const effectiveApiTestResult: ApiTestResult | null = buildEffectiveApiTestResult({
    result: apiTestResult,
    savedProfileTestOk: apiProfileDisplayStatus.savedTestOk,
    activeProfile: activeApiProfile,
  })
  const apiReadyForGeneration = request.api_config.provider !== 'local' && Boolean(effectiveApiTestResult?.ok)
  const apiReady = apiReadyForGeneration
  const effectiveTtsTestResult: Pick<TtsTestResult, 'ok'> | null =
    ttsTestResult ?? (ttsProfileDisplayStatus.savedTestOk ? { ok: true } : null)
  const ttsReadyForGeneration = Boolean(effectiveTtsTestResult?.ok)
  const ttsDetail = buildTtsReadinessDetail({ ttsRequired, ttsTestResult: effectiveTtsTestResult })
  const envReady = isEnvironmentReadyForGeneration({
    desktopRuntime: isTauriRuntime(),
    envStatus,
    sourceMode: request.source_mode,
  })
  const currentSelectionCount = project
    ? selectedCardCount
    : learningPointResult
      ? selectedLearningPointCount
      : request.card_types.length
  const readiness = buildReadinessItems({
    sourceMode: request.source_mode,
    sourceReady,
    localVideoPath,
    localSubtitlePath,
    envReady,
    envStatusChecked: Boolean(envStatus),
    apiProvider: request.api_config.provider,
    apiReadyForGeneration: apiReady,
    hasApiTestResult: Boolean(effectiveApiTestResult),
    ttsRequired,
    ttsDetail,
    currentSelectionCount,
  })
  const apiTestStatus = buildApiTestStatus({
    result: effectiveApiTestResult,
    testing: apiTesting,
    apiConfig: request.api_config,
  })
  const apiTestTone = apiTestStatus.tone
  const apiTestTitle = apiTestStatus.title
  const apiTestMessage = apiTestStatus.message
  const apiTestMeta = apiTestStatus.meta
  const ttsTestStatus = buildTtsTestStatus({
    result: ttsTestResult,
    testing: ttsTesting,
    tts,
  })
  const ttsTestTone = ttsTestStatus.tone
  const ttsTestTitle = ttsTestStatus.title
  const ttsTestMessage = ttsTestStatus.message
  const ttsTestMeta = ttsTestStatus.meta
  const allApiPresets = [...featuredApiPresets, ...advancedApiPresets]
  const allTtsPresets = [...featuredTtsPresets, ...advancedTtsPresets]
  const apiProfileStatus = apiProfileDisplayStatus.label
  const ttsProfileStatus = ttsProfileDisplayStatus.label
  const workerBusy = workerOperation.status === 'running' || workerOperation.status === 'cancelling'
  const appBusy = busy || workerBusy
  const isCancelling = workerOperation.status === 'cancelling'
  const inspectorUiState = buildInspectorUiState({
    responsiveMode,
    inspectorState,
    prefersReducedMotion,
  })
  const inspectorSheetOpen = inspectorUiState.inspectorSheetOpen
  const inspectorActionLabel = inspectorUiState.inspectorActionLabel
  const motionDuration = inspectorUiState.motionDuration
  const statusTone = buildAppStatusTone({
    appBusy,
    hasWorkerProgress: Boolean(workerProgress),
    status,
  })
  const generationRunState = buildGenerationRunState({
    sourceReady,
    learningPointResult,
    generationConfirmOpen,
    workerOperation,
    project,
    lastExport,
    lastWorkerError,
    ankiVerifyResult,
  })
  const releaseEvidenceSummary = useMemo(
    () =>
      buildReleaseEvidenceSummary({
        learningPointResult,
        project,
        exportResult: lastExport,
        ankiVerifyResult,
      }),
    [ankiVerifyResult, lastExport, learningPointResult, project],
  )
  const workerErrorActions = useMemo(
    () => (lastWorkerError ? getWorkerErrorActions(lastWorkerError.error_code, lastWorkerError.fallbacks) : []),
    [lastWorkerError],
  )

  useEffect(() => {
    const current = workerOperationRef.current
    if (
      current.status === 'running' &&
      current.jobId &&
      workerOperation.jobId &&
      current.jobId !== workerOperation.jobId
    ) {
      return
    }
    workerOperationRef.current = workerOperation
  }, [workerOperation])

  useEffect(() => {
    requestEditedDuringRunRef.current = requestEditedDuringRun
  }, [requestEditedDuringRun])

  useEffect(() => {
    learningPointResultRef.current = learningPointResult
  }, [learningPointResult])

  useEffect(() => {
    workerProgressRef.current = workerProgress
  }, [workerProgress])

  useEffect(() => {
    return () => {
      if (inspectorCollapseTimerRef.current !== null) {
        window.clearTimeout(inspectorCollapseTimerRef.current)
      }
    }
  }, [])

  useEffect(() => {
    if (typeof window === 'undefined') return
    const syncResponsiveMode = () => {
      const width = window.innerWidth
      setResponsiveMode(width < 1240 ? 'compact' : width < 1320 ? 'medium' : 'wide')
    }
    syncResponsiveMode()
    window.addEventListener('resize', syncResponsiveMode)
    return () => window.removeEventListener('resize', syncResponsiveMode)
  }, [])

  useEffect(() => {
    if (responsiveMode === 'compact' && (inspectorState === 'open' || inspectorState === 'collapsing')) {
      if (inspectorCollapseTimerRef.current !== null) {
        window.clearTimeout(inspectorCollapseTimerRef.current)
        inspectorCollapseTimerRef.current = null
      }
      setInspectorState('collapsed')
    } else if (responsiveMode !== 'compact' && inspectorState === 'sheet') {
      setInspectorState('open')
    }
  }, [responsiveMode, inspectorState])

  useEffect(() => {
    window.localStorage.setItem(REQUEST_STORAGE_KEY, JSON.stringify(stripRequestSecrets(request)))
  }, [request])

  useEffect(() => {
    if (typeof window === 'undefined') return
    if (project) {
      window.localStorage.setItem(PROJECT_STORAGE_KEY, JSON.stringify(project))
    } else {
      window.localStorage.removeItem(PROJECT_STORAGE_KEY)
    }
  }, [project])

  useEffect(() => {
    if (!project || projectMatchesRequest(project, request)) return
    lastExportFullRef.current = null
    activeAnkiVerifyApkgPathRef.current = null
    captureReleaseEvidenceRawSnapshot({ type: 'invalidate', scope: 'project_export_verify' })
    setProject(null)
    setLastExport(null)
    setAnkiVerifyResult(null)
    setActiveSegmentId(null)
    setStatus('已清理与当前素材不匹配的旧项目结果，请用当前本地视频重新生成。')
  }, [project, request])

  useEffect(() => {
    if (!project) {
      setActiveSegmentId(null)
      return
    }
    const hasActiveSegment = visibleSegments.some((segment) => segment.id === activeSegmentId)
    if (!hasActiveSegment) {
      setActiveSegmentId(visibleSegments[0]?.id ?? null)
    }
  }, [project, activeSegmentId, visibleSegments])

  function applyGeneratedProject(result: Project, editedDuringRun: boolean, jobId?: string) {
    const safeProject = normalizeProjectTemplateForPublicSource(stripProjectRuntimeSecrets(result))
    const materialized = materializeLearningPointInventory(safeProject)
    const generatedSelection = applyUsableCardSelection(materialized.project)
    const projectToShow = generatedSelection.project
    lastExportFullRef.current = null
    activeAnkiVerifyApkgPathRef.current = null
    setLastExport(null)
    setAnkiVerifyResult(null)
    captureReleaseEvidenceRawSnapshot({
      type: 'project_result',
      project: projectToShow,
      learningPointResult: lastLearningPointResultRef.current,
      jobId,
    })
    setProject(projectToShow)
    setSegmentFilter('all')
    setActiveSegmentId(projectToShow.segments[0]?.id ?? null)
    const projectExportStats = getExportSelectionStats(projectToShow)
    const usableCount = projectExportStats.selectedExportableCards
    const repairRequiredCount = projectExportStats.repairRequiredCards
    const candidateOnlyCount = projectToShow.quality_funnel?.candidate_only_learning_point_count ?? 0
    const hiddenDuplicateCount = projectToShow.quality_funnel?.hidden_duplicate_learning_point_count ?? 0
    const hardBlockedCount = projectToShow.quality_funnel?.hard_blocked_learning_point_count ?? 0
    const autoAddedHint = materialized.added ? ` 已自动补成 ${materialized.added} 张草稿卡。` : ''
    const diagnosticCount = candidateOnlyCount + hiddenDuplicateCount + hardBlockedCount
    const inventoryHint = diagnosticCount > 0 ? ` 更多学习点 ${diagnosticCount} 个可在诊断中查看。` : ''
    const isDocument = projectToShow.source_mode === 'document'
    const isReading = isDocument && projectToShow.document_study_mode === 'language_reading'
    const shortHint =
      usableCount < 5
        ? isReading
          ? '可导出精读卡偏少，通常是语言点较弱、模型返回空或多数学习点被过滤；可以在“更多学习点”查看原因。'
          : isDocument
            ? '可导出知识卡偏少，通常是文档分段较少、模型返回空或多数学习点被过滤；可以在“更多学习点”查看原因。'
            : '可导出卡偏少，通常是字幕太短、重复太多、词伙评分不足或模型返回空；可以在“更多学习点”查看原因。'
        : ''
    const editedHint = editedDuringRun ? ' 生成期间你修改过设置；下一次生成会使用新配置。' : ''
    const generatedLabel = isReading ? '精读卡' : isDocument ? '知识卡' : '卡'
    const repairHint = repairRequiredCount > 0 ? ` 已隔离 ${repairRequiredCount} 张需修复草稿卡，默认不会导出。` : ''
    const generationDiagnostics = projectToShow.card_generation_diagnostics
    const generationMissingCount = generationDiagnostics?.missing_learning_point_count ?? 0
    const generationProcessedCount =
      generationDiagnostics?.processed_learning_point_count ?? generationDiagnostics?.selected_learning_point_count ?? 0
    const generationGeneratedCount =
      generationDiagnostics?.generated_card_count ??
      generationDiagnostics?.successful_learning_point_count ??
      usableCount
    const generationHint =
      generationProcessedCount > 0
        ? generationMissingCount > 0
          ? ` 处理 ${generationProcessedCount} 个学习点，生成 ${generationGeneratedCount} 张；${generationMissingCount} 个未生成，可在“高级诊断”查看原因。`
          : ` 处理 ${generationProcessedCount} 个学习点，生成 ${generationGeneratedCount} 张。`
        : ''
    setStatus(
      (projectToShow.warning ||
        (projectToShow.source_mode === 'url'
          ? `URL 导入成功，当前可导出 ${usableCount} 张${generatedLabel}。${generationHint}${repairHint}${inventoryHint}${autoAddedHint}${shortHint}`
          : projectToShow.source_mode === 'document'
            ? `文档导入成功，当前可导出 ${usableCount} 张${generatedLabel}。${generationHint}${repairHint}${inventoryHint}${autoAddedHint}${shortHint}`
            : `当前可导出 ${usableCount} 张${generatedLabel}。${generationHint}${repairHint}${inventoryHint}${autoAddedHint}${shortHint}`)) +
        editedHint,
    )
    return projectToShow
  }

  function applyLearningPointResult(result: LearningPointExtractionResult, jobId?: string) {
    lastLearningPointResultRef.current = result
    generationRetryBaseProjectRef.current = null
    activeAnkiVerifyApkgPathRef.current = null
    lastExportFullRef.current = null
    captureReleaseEvidenceRawSnapshot({ type: 'learning_point_result', result, jobId })
    setLearningPointResult(result)
    setProject(null)
    setLastExport(null)
    setAnkiVerifyResult(null)
    setActiveSegmentId(null)
    setSegmentFilter('all')
    setGenerationConfirmOpen(false)
    setGenerationQueueSelectedIds(null)
    setGenerationBatchRuntime(null)
    setSelectedLearningPointIds(
      defaultSelectedLearningPointIds(result.learning_points ?? [], {
        reviewDensity: request.review_density,
        maxSelected: null,
      }),
    )
    const summary = result.learning_point_summary
    setStatus(
      `已从字幕发现 ${summary.total} 个学习点：推荐 ${summary.recommended} 个，候选 ${summary.candidate_only} 个，重复 ${summary.hidden_duplicate} 个，硬阻断 ${summary.hard_blocked} 个。请先筛选学习点，再生成 Anki 卡。`,
    )
  }
  const applyLearningPointResultRef = useRef(applyLearningPointResult)
  useEffect(() => {
    applyLearningPointResultRef.current = applyLearningPointResult
  })

  function setGenerationBatchRuntime(runtime: GenerationBatchRuntime | null) {
    generationBatchRef.current = runtime
    setGenerationBatchProgress(runtime ? generationBatchProgressSnapshot(runtime) : null)
  }

  function recordGenerationCheckpoint(stage: string, details: Record<string, unknown> = {}) {
    void recordRendererError({
      kind: 'generation_checkpoint',
      stage,
      at: new Date().toISOString(),
      ...details,
    }).catch(() => {
      // Best-effort breadcrumb only.
    })
  }

  async function startNextLearningPointGenerationBatch(runtime: GenerationBatchRuntime) {
    const activeResult = learningPointResultRef.current
    if (!activeResult) throw new Error('学习点结果已经丢失，无法继续分批生成。')
    const batchStart = runtime.nextIndex
    const batchIds = runtime.queueIds.slice(batchStart, batchStart + runtime.batchSize)
    if (batchIds.length === 0) throw new Error('分批生成队列为空。')
    const nextRuntime: GenerationBatchRuntime = {
      ...runtime,
      active: true,
      activeBatchIds: batchIds,
      nextIndex: batchStart + batchIds.length,
    }
    setGenerationBatchRuntime(nextRuntime)
    const batchNumber = nextRuntime.completedBatches + 1
    setBusy(true)
    setWorkerProgress({
      command: 'generate_cards_from_learning_points',
      stage: 'batch_start',
      percent: Math.max(1, Math.round((nextRuntime.completedCount / Math.max(1, nextRuntime.queueIds.length)) * 100)),
      message: `正在生成第 ${batchNumber}/${nextRuntime.totalBatches} 批：${batchIds.length} 张。`,
    })
    setStatus(`正在生成卡片正文：第 ${batchNumber}/${nextRuntime.totalBatches} 批，当前 ${batchIds.length} 张。`)
    recordGenerationCheckpoint('before_payload_build', {
      project_id: nextRuntime.projectId,
      batch_number: batchNumber,
      total_batches: nextRuntime.totalBatches,
      batch_size: batchIds.length,
      total_count: nextRuntime.queueIds.length,
    })
    const payload = buildLearningPointGenerationPayload({
      learningPointResult: activeResult,
      request: nextRuntime.request,
      selectedLearningPointIds: new Set(batchIds),
      apiConfig: nextRuntime.apiConfig,
      projectId: nextRuntime.projectId,
    })
    if (cardGenerationCacheNamespace) {
      payload.disable_card_generation_cache_read = true
      payload.card_generation_cache_namespace = cardGenerationCacheNamespace
    }
    const payloadBytes = new TextEncoder().encode(JSON.stringify(payload)).length
    recordGenerationCheckpoint('payload_built', {
      project_id: nextRuntime.projectId,
      batch_number: batchNumber,
      selected_learning_point_count: payload.selected_learning_point_ids.length,
      learning_points_in_payload: payload.learning_points.length,
      source_sentences_in_payload: payload.source_sentences.length,
      payload_bytes: payloadBytes,
    })
    const job = await startWorkerJob('generate_cards_from_learning_points', payload)
    recordGenerationCheckpoint('job_started', {
      project_id: nextRuntime.projectId,
      job_id: job.job_id,
      batch_number: batchNumber,
      payload_bytes: payloadBytes,
    })
    const nextOperation: WorkerOperation = {
      status: 'running',
      command: 'generate_cards_from_learning_points',
      jobId: job.job_id,
    }
    workerOperationRef.current = nextOperation
    setWorkerOperation(nextOperation)
    setWorkerProgress({
      job_id: job.job_id,
      command: 'generate_cards_from_learning_points',
      stage: 'start',
      percent: Math.max(1, Math.round((nextRuntime.completedCount / Math.max(1, nextRuntime.queueIds.length)) * 100)),
      message: `卡片生成任务已在后台运行：第 ${batchNumber}/${nextRuntime.totalBatches} 批。`,
    })
  }

  function applyExportResult(result: ExportResult, jobId?: string) {
    lastExportFullRef.current = result
    activeAnkiVerifyApkgPathRef.current = null
    captureReleaseEvidenceRawSnapshot({ type: 'export_result', result, jobId })
    setLastExport(compactExportResultForUi(result))
    setAnkiVerifyResult(null)
    const mediaHint = result.media_summary
      ? `媒体约 ${result.media_summary.media_mb} MB，视频 ${result.media_summary.video_segments} 段，表达 TTS 文件 ${result.media_summary.phrase_tts_files} 个。`
      : ''
    setStatus(`导出完成：${result.cards} 张卡，${result.segments} 个片段。${mediaHint} ${result.apkg_path}`)
  }

  function applyVerifyResult(result: AnkiVerifyResult, jobId?: string) {
    captureReleaseEvidenceRawSnapshot({
      type: 'verify_result',
      result,
      verifiedExportApkgPath: activeAnkiVerifyApkgPathRef.current ?? lastExportFullRef.current?.apkg_path ?? null,
      jobId,
    })
    setAnkiVerifyResult(result)
    setStatus(result.message)
  }

  async function maybeStartAutoExport(generatedProject: Project) {
    const outputDir = generationAutoExportOutputDirRef.current
    if (!outputDir) return false
    generationAutoExportOutputDirRef.current = null
    await startExportForProject({
      projectOverride: generatedProject,
      outputDir,
      auto: true,
    })
    return true
  }

  async function handleWorkerFinished(payloadInput: WorkerFinishedEvent) {
    const active = workerOperationRef.current
    if (
      !workerFinishMatchesActiveJob(payloadInput, {
        refOperation: active,
        stateOperation: workerOperation,
        lastProgress: workerProgressRef.current,
      })
    ) {
      return
    }
    if (payloadInput.job_id !== active.jobId) {
      workerOperationRef.current =
        payloadInput.job_id === workerOperation.jobId
          ? workerOperation
          : fallbackWorkerOperationFromFinish(payloadInput)
    }
    if (handledWorkerFinishIdsRef.current.has(payloadInput.job_id)) return
    if (processingWorkerFinishIdsRef.current.has(payloadInput.job_id)) return
    processingWorkerFinishIdsRef.current.add(payloadInput.job_id)

    try {
      let payload: WorkerFinishedEvent = { ...payloadInput }
      if (payload.ok && typeof payload.result === 'undefined' && payload.result_ref) {
        try {
          payload = await resolveWorkerFinishedResult(payload, readWorkerJobResult)
        } catch (error) {
          const failedPayload: WorkerFinishedEvent = {
            ...payload,
            ok: false,
            error: `后台任务已完成，但结果读取失败：${redactSensitiveText(error)}`,
            retryable: true,
          }
          handledWorkerFinishIdsRef.current.add(payload.job_id)
          setBusy(false)
          setAnkiVerifying(false)
          setWorkerProgress(null)
          setWorkerOperation({ status: 'failed', command: payload.command, jobId: payload.job_id })
          setLastWorkerError(failedPayload)
          setStatus(failedPayload.error || '后台任务结果读取失败。')
          return
        }
      }

      handledWorkerFinishIdsRef.current.add(payload.job_id)
      setBusy(false)
      setAnkiVerifying(false)
      if (payload.cancelled) {
        if (payload.command === 'export') releaseExportTargetsByJobIdRef.current.delete(payload.job_id)
        if (payload.command === 'generate_cards_from_learning_points') {
          setGenerationBatchRuntime(null)
          generationAutoExportOutputDirRef.current = null
        }
        setWorkerProgress(null)
        setWorkerOperation({ status: 'idle' })
        setLastWorkerError(null)
        setStatus('任务已取消，可以继续调整后重新生成。')
        return
      }
      if (workerFinishInvalidatedByEditedRequest(payload, requestEditedDuringRunRef.current)) {
        if (payload.command === 'export') releaseExportTargetsByJobIdRef.current.delete(payload.job_id)
        if (
          payload.command === 'extract_learning_points' ||
          payload.command === 'generate' ||
          payload.command === 'generate_cards_from_learning_points'
        ) {
          setProject(null)
          setLearningPointResult(null)
          setSelectedLearningPointIds(new Set())
          setActiveSegmentId(null)
          setGenerationConfirmOpen(false)
          setGenerationQueueSelectedIds(null)
        }
        setGenerationBatchRuntime(null)
        generationRetryBaseProjectRef.current = null
        generationAutoExportOutputDirRef.current = null
        lastExportFullRef.current = null
        activeAnkiVerifyApkgPathRef.current = null
        captureReleaseEvidenceRawSnapshot({
          type: 'invalidate',
          scope: payload.command === 'export' || payload.command === 'verify_anki_import' ? 'export_and_verify' : 'all',
        })
        setLastExport(null)
        setAnkiVerifyResult(null)
        setWorkerProgress(null)
        setWorkerOperation({ status: 'idle' })
        setLastWorkerError(null)
        setRequestEditedDuringRun(false)
        setStatus('任务完成，但运行期间素材或设置已变化；已丢弃旧结果，请用当前配置重新开始。')
        return
      }
      if (!payload.ok) {
        if (payload.command === 'export') releaseExportTargetsByJobIdRef.current.delete(payload.job_id)
        let generationFailureRecoveryHint = ''
        if (payload.command === 'generate_cards_from_learning_points' && generationBatchRef.current?.active) {
          generationAutoExportOutputDirRef.current = null
          const batch = generationBatchRef.current
          generationRetryBaseProjectRef.current = batch.mergedProject
          const retryIds = retryLearningPointIdsAfterBatchFailure({
            queueIds: batch.queueIds,
            completedCount: batch.completedCount,
            activeBatchIds: batch.activeBatchIds,
          })
          setGenerationBatchRuntime({ ...batch, active: false })
          setGenerationConfirmOpen(true)
          setGenerationQueueSelectedIds(new Set(retryIds))
          setSelectedLearningPointIds(new Set(retryIds))
          generationFailureRecoveryHint = `已保留已完成的 ${batch.completedCount} 个学习点；可重试失败批和后续 ${retryIds.length} 个学习点。`
          recordGenerationCheckpoint('job_failed', {
            project_id: batch.projectId,
            completed_count: batch.completedCount,
            total_count: batch.queueIds.length,
            active_batch_size: batch.activeBatchIds.length,
            retry_count: retryIds.length,
            error_code: payload.error_code,
            stage: payload.stage,
          })
        }
        setWorkerOperation({ status: 'failed', command: payload.command, jobId: payload.job_id })
        setLastWorkerError(payload)
        setWorkerProgress(null)
        setStatus(
          workerFailureStatusMessage(payload, {
            redactedError: redactSensitiveText(payload.error || '任务失败。'),
            detailsSummary: workerFailureDetailsSummary(payload.details),
            generationFailureRecoveryHint,
          }),
        )
        return
      }
      if (typeof payload.result === 'undefined') {
        const failedPayload: WorkerFinishedEvent = {
          ...payload,
          ok: false,
          error: '后台任务已完成，但没有返回结果。请重试；如果再次出现，请保留日志定位 worker 输出。',
          retryable: true,
        }
        setWorkerProgress(null)
        setWorkerOperation({ status: 'failed', command: payload.command, jobId: payload.job_id })
        setLastWorkerError(failedPayload)
        setStatus(failedPayload.error || '后台任务没有返回结果。')
        return
      }
      setWorkerProgress({
        job_id: payload.job_id,
        command: payload.command,
        stage: 'done',
        percent: 100,
        message: '任务完成。',
      })
      if (payload.command === 'extract_learning_points') {
        applyLearningPointResultRef.current(payload.result as LearningPointExtractionResult, payload.job_id)
        setActiveWorkspaceStage('review')
      } else if (payload.command === 'generate_cards_from_learning_points') {
        const activeBatch = generationBatchRef.current
        if (activeBatch?.active) {
          const completedBatch: GenerationBatchRuntime = {
            ...activeBatch,
            completedBatches: activeBatch.completedBatches + 1,
            completedCount: activeBatch.completedCount + activeBatch.activeBatchIds.length,
          }
          const mergedProject = mergeGeneratedBatchProject(
            activeBatch.mergedProject,
            payload.result as Project,
            completedBatch,
          )
          const mergedDiagnostics = mergedProject.card_generation_diagnostics
          const nextBatch: GenerationBatchRuntime = {
            ...completedBatch,
            mergedProject,
            activeBatchIds: [],
            generatedCount:
              mergedDiagnostics?.generated_card_count ?? mergedDiagnostics?.successful_learning_point_count ?? 0,
            missingCount: mergedDiagnostics?.missing_learning_point_count ?? 0,
            exportableCount: mergedDiagnostics?.exportable_card_count ?? 0,
          }
          recordGenerationCheckpoint('job_finished', {
            project_id: nextBatch.projectId,
            job_id: payload.job_id,
            completed_batches: nextBatch.completedBatches,
            total_batches: nextBatch.totalBatches,
            completed_count: nextBatch.completedCount,
            generated_count: nextBatch.generatedCount,
            missing_count: nextBatch.missingCount,
            total_count: nextBatch.queueIds.length,
          })
          if (nextBatch.nextIndex < nextBatch.queueIds.length) {
            setGenerationBatchRuntime(nextBatch)
            setBusy(true)
            setWorkerOperation({ status: 'running', command: 'generate_cards_from_learning_points' })
            try {
              await startNextLearningPointGenerationBatch(nextBatch)
            } catch (error) {
              const failedPayload: WorkerFinishedEvent = {
                ...payload,
                ok: false,
                error: `下一批生成任务启动失败：${redactSensitiveText(error)}`,
                retryable: true,
              }
              setBusy(false)
              setGenerationBatchRuntime({ ...nextBatch, active: false })
              setWorkerOperation({
                status: 'failed',
                command: 'generate_cards_from_learning_points',
                jobId: payload.job_id,
              })
              setLastWorkerError(failedPayload)
              setStatus(failedPayload.error || '下一批生成任务启动失败。')
            }
            return
          }
          setGenerationBatchRuntime(null)
          generationRetryBaseProjectRef.current = null
          setLearningPointResult(null)
          setSelectedLearningPointIds(new Set())
          setGenerationConfirmOpen(false)
          setGenerationQueueSelectedIds(null)
          const projectToShow = applyGeneratedProject(mergedProject, requestEditedDuringRunRef.current, payload.job_id)
          setActiveWorkspaceStage('review')
          const missingCount =
            mergedDiagnostics?.missing_learning_point_count ??
            Math.max(0, nextBatch.completedCount - nextBatch.generatedCount)
          const generatedCards = mergedDiagnostics?.generated_card_count ?? nextBatch.generatedCount
          setStatus(
            missingCount > 0
              ? `处理 ${nextBatch.completedCount} 个学习点，生成 ${generatedCards} 张；${missingCount} 个未生成，点击查看原因。`
              : `处理 ${nextBatch.completedCount} 个学习点，生成 ${generatedCards} 张；全部生成成功。`,
          )
          if (await maybeStartAutoExport(projectToShow)) {
            setLastWorkerError(null)
            setRequestEditedDuringRun(false)
            return
          }
        } else {
          const generatedProject = payload.result as Project
          generationRetryBaseProjectRef.current = null
          setLearningPointResult(null)
          setSelectedLearningPointIds(new Set())
          setGenerationConfirmOpen(false)
          setGenerationQueueSelectedIds(null)
          const projectToShow = applyGeneratedProject(
            generatedProject,
            requestEditedDuringRunRef.current,
            payload.job_id,
          )
          setActiveWorkspaceStage('review')
          if (await maybeStartAutoExport(projectToShow)) {
            setLastWorkerError(null)
            setRequestEditedDuringRun(false)
            return
          }
        }
      } else if (payload.command === 'generate') {
        applyGeneratedProject(payload.result as Project, requestEditedDuringRunRef.current, payload.job_id)
        setActiveWorkspaceStage('review')
      } else if (payload.command === 'export') {
        const exportResult = payload.result as ExportResult
        const expectedReleaseTarget = releaseExportTargetsByJobIdRef.current.get(payload.job_id)
        releaseExportTargetsByJobIdRef.current.delete(payload.job_id)
        if (
          expectedReleaseTarget &&
          normalizedComparablePath(exportResult.apkg_path) !==
            normalizedComparablePath(expectedReleaseTarget.canonicalApkgPath)
        ) {
          const failedPayload = releaseApkgReturnedPathGuardFailureEvent({
            jobId: payload.job_id,
            expected: expectedReleaseTarget,
            actualApkgPath: exportResult.apkg_path,
          })
          lastExportFullRef.current = null
          activeAnkiVerifyApkgPathRef.current = null
          captureReleaseEvidenceRawSnapshot({ type: 'invalidate', scope: 'export_and_verify' })
          setLastExport(null)
          setAnkiVerifyResult(null)
          setWorkerProgress(null)
          setWorkerOperation({ status: 'failed', command: 'export', jobId: payload.job_id })
          setLastWorkerError(failedPayload)
          setStatus(failedPayload.error || '导出没有生成 canonical APKG。')
          return
        }
        applyExportResult(exportResult, payload.job_id)
        setActiveWorkspaceStage('review')
      } else if (payload.command === 'verify_anki_import') {
        applyVerifyResult(payload.result as AnkiVerifyResult, payload.job_id)
        setActiveWorkspaceStage('review')
      }
      setLastWorkerError(null)
      setWorkerOperation({ status: 'succeeded', command: payload.command, jobId: payload.job_id })
      setRequestEditedDuringRun(false)
    } finally {
      processingWorkerFinishIdsRef.current.delete(payloadInput.job_id)
    }
  }
  useEffect(() => {
    handleWorkerFinishedRef.current = handleWorkerFinished
  })

  useEffect(() => {
    if (!isTauriRuntime()) return
    let stopListening: (() => void) | undefined
    let stopFinishedListening: (() => void) | undefined
    listen<WorkerProgress>('worker-progress', (event) => {
      const active = workerOperationRef.current
      if (event.payload.job_id && event.payload.job_id !== active.jobId) return
      workerProgressRef.current = event.payload
      setWorkerProgress(event.payload)
      setStatus(event.payload.message)
    })
      .then((unlisten) => {
        stopListening = unlisten
      })
      .catch(() => {
        setWorkerProgress(null)
      })
    listen<WorkerFinishedEvent>('worker-finished', (event) => {
      void handleWorkerFinishedRef.current(event.payload)
    })
      .then((unlisten) => {
        stopFinishedListening = unlisten
      })
      .catch(() => {
        setStatus('后台任务监听失败，请重启软件后再试。')
      })
    return () => {
      stopListening?.()
      stopFinishedListening?.()
    }
  }, [])

  useEffect(() => {
    if (!isTauriRuntime()) return
    const resolvePollingJobId = () => {
      const active = workerOperationRef.current
      if (active.status === 'running' && active.jobId) return active.jobId
      if (workerOperation.status === 'running' && workerOperation.jobId) return workerOperation.jobId
      if (busy && workerProgressRef.current?.job_id) return workerProgressRef.current.job_id
      return null
    }
    const initialJobId = resolvePollingJobId()
    if (!initialJobId) return
    let cancelled = false
    let pollFailureCount = 0
    let pollFailureReported = false
    const pollFinishedJob = async () => {
      const jobId = resolvePollingJobId()
      if (!jobId || handledWorkerFinishIdsRef.current.has(jobId)) return
      try {
        const status = await getWorkerJobStatus(jobId)
        pollFailureCount = 0
        if (!cancelled && status?.job_id) {
          if (!workerOperationRef.current.jobId && status.job_id === jobId) {
            workerOperationRef.current = fallbackWorkerOperationFromFinish(status)
          }
          void handleWorkerFinishedRef.current(status)
        }
      } catch (error) {
        // Progress events are still the primary path; polling only recovers missed finish events.
        pollFailureCount += 1
        if (!cancelled && pollFailureCount >= 3 && !pollFailureReported) {
          pollFailureReported = true
          const message = `后台任务完成状态轮询失败：${redactSensitiveText(error)}`
          setStatus(`${message}。如果进度长时间不动，请取消后重试；诊断日志已保留。`)
          void recordRendererError({
            kind: 'worker_status_poll_failed',
            job_id: jobId,
            command: workerOperationRef.current.command ?? workerOperation.command,
            error: redactSensitiveText(error),
          })
        }
      }
    }
    void pollFinishedJob()
    const intervalId = window.setInterval(pollFinishedJob, 2000)
    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [busy, workerOperation.command, workerOperation.jobId, workerOperation.status, workerProgress?.job_id])

  useEffect(() => {
    if (!settingsOpen) return
    const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const focusTimer = window.setTimeout(() => {
      settingsDialogRef.current?.focus()
    }, 0)
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        setSettingsOpen(false)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => {
      window.clearTimeout(focusTimer)
      window.removeEventListener('keydown', handleKeyDown)
      previouslyFocused?.focus()
    }
  }, [settingsOpen])

  const runWindowAction = async (action: 'minimize' | 'toggleMaximize' | 'close') => {
    await runNativeWindowAction(action)
  }

  const startWindowDrag = async (event: MouseEvent<HTMLElement>) => {
    if (event.button !== 0) return
    const target = event.target as HTMLElement
    if (target.closest('button,input,select,textarea,a,label,summary,.topbar-actions,.window-controls')) return
    await startNativeWindowDrag(event)
  }

  const handleTopbarDoubleClick = async (event: MouseEvent<HTMLElement>) => {
    const target = event.target as HTMLElement
    if (target.closest('button,input,select,textarea,a,label,summary,.topbar-actions,.window-controls')) return
    await runWindowAction('toggleMaximize')
  }

  const startWindowResize = async (direction: ResizeDirection, event: MouseEvent<HTMLDivElement>) => {
    if (event.button !== 0) return
    event.stopPropagation()
    await startNativeWindowResize(direction, event)
  }

  const markRequestEditedIfRunning = () => {
    if (workerOperationRef.current.status === 'running') {
      setRequestEditedDuringRun(true)
    }
  }

  const toggleInspector = () => {
    if (inspectorCollapseTimerRef.current !== null) {
      window.clearTimeout(inspectorCollapseTimerRef.current)
      inspectorCollapseTimerRef.current = null
    }

    if (responsiveMode === 'compact') {
      setInspectorState((current) => (current === 'sheet' ? 'collapsed' : 'sheet'))
      return
    }

    if (prefersReducedMotion) {
      setInspectorState((current) => (current === 'collapsed' ? 'open' : 'collapsed'))
      return
    }

    if (inspectorState === 'open') {
      setInspectorState('collapsing')
      inspectorCollapseTimerRef.current = window.setTimeout(() => {
        setInspectorState('collapsed')
        inspectorCollapseTimerRef.current = null
      }, INSPECTOR_COLLAPSE_MS)
      return
    }

    setInspectorState('open')
  }

  const patchRequest = (patch: Partial<GenerateRequest>) => {
    const safePatch: Partial<GenerateRequest> =
      patch.source_mode === 'document'
        ? {
            ...patch,
            source_mode: 'local',
            document_path: '',
            card_types: patch.card_types?.filter((type) => type !== 'knowledge').length
              ? patch.card_types.filter((type) => type !== 'knowledge')
              : ['phrase'],
          }
        : patch
    markRequestEditedIfRunning()
    if (requestPatchInvalidatesLearningArtifacts(safePatch)) {
      clearLearningArtifactsForRequestChange()
    } else if (requestPatchInvalidatesExportArtifacts(safePatch)) {
      clearStaleReviewResults()
    }
    setRequest((current) => {
      const next = { ...current, ...safePatch }
      if (next.source_mode !== 'document') {
        next.skip_video_slicing = false
      }
      if (next.source_mode === 'url') {
        next.url_import_mode = 'video'
        next.url_auto_subtitle_fallback = false
      }
      return next
    })
  }

  const selectCurrentLevel = (level: Level) => {
    patchRequest({
      level_mode: 'manual',
      level,
      collection_levels: defaultCollectionLevels(level),
    })
  }

  const toggleCollectionLevel = (level: Level) => {
    markRequestEditedIfRunning()
    clearLearningArtifactsForRequestChange()
    setRequest((current) => {
      const selected = normalizeCollectionLevels(current.collection_levels, current.level)
      const next = selected.includes(level) ? selected.filter((item) => item !== level) : [...selected, level]
      return {
        ...current,
        collection_levels: normalizeCollectionLevels(next.length ? next : selected, current.level),
      }
    })
  }

  const applyCollectionPreset = (mode: 'current' | 'below' | 'around') => {
    markRequestEditedIfRunning()
    clearLearningArtifactsForRequestChange()
    setRequest((current) => {
      const index = Math.max(0, levelOrder.indexOf(current.level))
      const collectionLevels =
        mode === 'current'
          ? [current.level]
          : mode === 'below'
            ? levelOrder.slice(0, index + 1)
            : levelOrder.slice(Math.max(0, index - 1), Math.min(levelOrder.length, index + 2))
      return {
        ...current,
        collection_levels: collectionLevels,
      }
    })
  }

  const selectSourceMode = (mode: SourceMode) => {
    const publicMode: SourceMode = mode === 'document' ? 'local' : mode
    const nextCardTypes: CardKind[] = request.card_types.includes('knowledge')
      ? ['phrase']
      : request.card_types

    lastExportFullRef.current = null
    activeAnkiVerifyApkgPathRef.current = null
    releaseEvidenceRawSnapshotRef.current = emptyReleaseEvidenceRawSnapshot()
    setLastExport(null)
    setLastWorkerError(null)
    setAnkiVerifyResult(null)
    setProject(null)
    setActiveSegmentId(null)
    setWorkerProgress(null)
    const sourcePatch: Partial<GenerateRequest> = {
      source_mode: publicMode,
      card_types: nextCardTypes,
      document_path: '',
    }
    if (publicMode === 'local') {
      sourcePatch.source_url = ''
      sourcePatch.skip_video_slicing = false
      sourcePatch.allow_private_network_url = false
      sourcePatch.allow_ytdlp_remote_components = false
      sourcePatch.local_path_access_confirmed = false
    } else if (publicMode === 'url') {
      sourcePatch.video_path = ''
      sourcePatch.subtitle_path = ''
      sourcePatch.url_import_mode = 'video'
      sourcePatch.url_auto_subtitle_fallback = false
      sourcePatch.skip_video_slicing = false
      sourcePatch.allow_private_network_url = false
      sourcePatch.allow_ytdlp_remote_components = false
      sourcePatch.local_path_access_confirmed = false
    }
    patchRequest(sourcePatch)
    setStatus(
      mode === 'document'
        ? '文档资料制卡已从当前发布版隐藏。当前只保留本地视频和视频链接制卡。'
        : publicMode === 'url'
          ? '已切换到视频链接模式，请粘贴 YouTube 或视频 URL。'
          : '已切换到本地视频模式，请选择视频；SRT 可留空并自动匹配或提取内嵌字幕。',
    )
  }

  const patchApi = (patch: Partial<ApiConfig>) => {
    markRequestEditedIfRunning()
    clearStaleReviewResults()
    setRequest((current) => ({
      ...current,
      api_config: { ...current.api_config, ...patch },
    }))
    setApiProfileDirty(true)
    setApiTestResult(null)
  }

  const patchTts = (patch: Partial<TtsConfig>) => {
    markRequestEditedIfRunning()
    clearStaleReviewResults()
    setRequest((current) => ({
      ...current,
      api_config: {
        ...current.api_config,
        tts_config: { ...current.api_config.tts_config, ...patch },
      },
    }))
    setTtsProfileDirty(true)
    setTtsTestResult(null)
  }

  const saveCurrentApiProfile = async () => {
    const existing = savedApiProfiles.find((profile) => profile.id === activeApiProfileId)
    const profile = buildSavedApiProfile(request.api_config, allApiPresets, existing, apiTestResult?.ok)
    const shouldSaveKey = profile.auth === 'api_key' && request.api_config.api_key.trim()
    try {
      if (shouldSaveKey) {
        await saveSecret(profileSecretKey('api', profile.id), request.api_config.api_key.trim())
        profile.has_api_key = true
      }
      const next = upsertSavedApiProfile(savedApiProfiles, profile)
      saveSavedApiProfiles(next)
      setSavedApiProfiles(next)
      if (shouldSaveKey) {
        setRequest((current) => ({
          ...current,
          api_config: {
            ...current.api_config,
            api_key: '',
          },
        }))
      }
      setApiProfileDirty(false)
      setStatus(
        profile.auth === 'gcloud'
          ? `已保存模型方案：${profile.label}。它使用本机 gcloud OAuth，不需要 API Key。`
          : profile.has_api_key
            ? `已保存模型方案：${profile.label}，API Key 已单独保存到系统凭据。`
            : `已保存模型方案：${profile.label}。这个方案还没有保存 API Key。`,
      )
    } catch {
      setStatus('模型方案保存失败，请确认系统凭据可写。')
    }
  }

  const saveCurrentTtsProfile = async () => {
    const existing = savedTtsProfiles.find((profile) => profile.id === activeTtsProfileId)
    const profile = buildSavedTtsProfile(tts, allTtsPresets, existing, ttsTestResult?.ok)
    const shouldSaveKey = profile.auth === 'api_key' && tts.api_key.trim()
    try {
      if (shouldSaveKey) {
        await saveSecret(profileSecretKey('tts', profile.id), tts.api_key.trim())
        profile.has_api_key = true
      }
      const next = upsertSavedTtsProfile(savedTtsProfiles, profile)
      saveSavedTtsProfiles(next)
      setSavedTtsProfiles(next)
      if (shouldSaveKey) {
        setRequest((current) => ({
          ...current,
          api_config: {
            ...current.api_config,
            tts_config: {
              ...current.api_config.tts_config,
              api_key: '',
            },
          },
        }))
      }
      setTtsProfileDirty(false)
      setStatus(
        profile.auth === 'gcloud'
          ? `已保存语音方案：${profile.label}。它使用本机 gcloud OAuth，不需要 TTS API Key。`
          : profile.has_api_key
            ? `已保存语音方案：${profile.label}，TTS API Key 已单独保存到系统凭据。`
            : `已保存语音方案：${profile.label}。这个方案还没有保存 TTS API Key。`,
      )
    } catch {
      setStatus('语音方案保存失败，请确认系统凭据可写。')
    }
  }

  const applySavedApiProfile = async (profileId: string) => {
    const profile = savedApiProfiles.find((item) => item.id === profileId)
    if (!profile) return
    markRequestEditedIfRunning()
    clearStaleReviewResults()
    setRequest((current) => ({
      ...current,
      api_config: {
        ...current.api_config,
        provider: profile.provider,
        base_url: profile.base_url,
        model: profile.model,
        capabilities: profile.capabilities,
        api_key: '',
      },
    }))
    setApiProfileDirty(false)
    setApiTestResult(
      profile.last_test_ok === undefined
        ? null
        : {
            ok: profile.last_test_ok,
            provider: profile.provider,
            model: profile.model,
            message: profile.last_test_ok
              ? '已加载保存方案，建议按需重新测试连接。'
              : '已加载保存方案，建议重新测试连接。',
          },
    )
    setStatus(
      profile.auth === 'api_key' && !profile.has_api_key
        ? `已切换到模型方案：${profile.label}。这个方案没有保存 API Key。`
        : profile.auth === 'api_key'
          ? `已切换到模型方案：${profile.label}。Key 已保存，测试或生成前会短时读取。`
          : `已切换到模型方案：${profile.label}。`,
    )
  }

  const applySavedTtsProfile = async (profileId: string) => {
    const profile = savedTtsProfiles.find((item) => item.id === profileId)
    if (!profile) return
    patchTts({
      enabled: profile.enabled,
      provider: profile.provider,
      base_url: profile.base_url,
      model: profile.model,
      voice: profile.voice,
      language: profile.language,
      sample_rate: profile.sample_rate,
      bit_rate: profile.bit_rate,
      output_volume: profile.output_volume,
      api_key: '',
    })
    setTtsProfileDirty(false)
    setTtsTestResult(
      profile.last_test_ok === undefined
        ? null
        : {
            ok: profile.last_test_ok,
            provider: profile.provider,
            model: profile.model,
            voice: profile.voice,
            message: profile.last_test_ok
              ? '已加载保存语音方案，建议按需重新测试 TTS。'
              : '已加载保存语音方案，建议重新测试 TTS。',
          },
    )
    setStatus(
      profile.auth === 'api_key' && !profile.has_api_key
        ? `已切换到语音方案：${profile.label}。这个方案没有保存 TTS API Key。`
        : profile.auth === 'api_key'
          ? `已切换到语音方案：${profile.label}。Key 已保存，测试或导出前会短时读取。`
          : `已切换到语音方案：${profile.label}。`,
    )
  }

  const applyApiPreset = async (preset: ApiPreset) => {
    markRequestEditedIfRunning()
    clearStaleReviewResults()
    const nextConfig = {
      provider: preset.provider,
      base_url: preset.base_url,
      model: preset.model,
      capabilities: preset.capabilities,
    }
    const profileId = apiProfileIdFromConfig(nextConfig)
    const savedProfile = savedApiProfiles.find((profile) => profile.id === profileId)
    setRequest((current) => ({
      ...current,
      api_config: {
        ...current.api_config,
        ...nextConfig,
        api_key: '',
      },
    }))
    setApiTestResult(
      savedProfile?.last_test_ok === undefined
        ? null
        : {
            ok: savedProfile.last_test_ok,
            provider: savedProfile.provider,
            model: savedProfile.model,
            message: savedProfile.last_test_ok
              ? '已套用保存方案，配置未改变，无需重复测试。'
              : '已套用保存方案，建议重新测试连接。',
          },
    )
    setApiProfileDirty(!savedProfile)
    setStatus(
      savedProfile
        ? `已套用已保存的 ${preset.label} 方案。`
        : preset.provider === 'gemini-vertex' || preset.provider === 'local'
          ? `已套用 ${preset.label} 预设，建议保存为我的模型方案。`
          : `已套用 ${preset.label} 预设，请填写 API Key 后保存方案并测试连接。`,
    )
  }

  const rememberSavedApiTestResult = (api: ApiConfig, result: ApiTestResult) => {
    if (apiProfileDirty) return
    const profileId = apiProfileIdFromConfig(api)
    const existing = savedApiProfiles.find((profile) => profile.id === profileId)
    if (!existing || !apiConfigMatchesProfile(api, existing)) return
    const next = upsertSavedApiProfile(savedApiProfiles, {
      ...existing,
      updated_at: new Date().toISOString(),
      last_test_ok: result.ok,
    })
    saveSavedApiProfiles(next)
    setSavedApiProfiles(next)
  }

  const applyTtsPreset = async (preset: TtsPreset) => {
    const shouldReuseMainMimoKey =
      preset.provider === 'mimo' &&
      isMimoApiConfig(request.api_config) &&
      Boolean(request.api_config.api_key.trim() || activeApiProfile?.has_api_key)
    const shouldReuseMainQwenKey =
      preset.provider === 'qwen' &&
      isQwenApiConfig(request.api_config) &&
      Boolean(request.api_config.api_key.trim() || activeApiProfile?.has_api_key)
    const usesLocalVertexAuth = preset.provider === 'gemini-vertex'
    const nextConfig = {
      enabled: preset.provider !== 'disabled',
      provider: preset.provider,
      base_url: preset.base_url,
      model: preset.model,
      voice: preset.voice,
      language: request.api_config.tts_config.language,
      sample_rate: request.api_config.tts_config.sample_rate,
      bit_rate: request.api_config.tts_config.bit_rate,
      output_volume: request.api_config.tts_config.output_volume,
    }
    const profileId = ttsProfileIdFromConfig(nextConfig)
    const savedProfile = savedTtsProfiles.find((profile) => profile.id === profileId)
    patchTts({
      ...nextConfig,
      api_key:
        savedProfile?.has_api_key || shouldReuseMainMimoKey || shouldReuseMainQwenKey || usesLocalVertexAuth
          ? ''
          : request.api_config.tts_config.api_key,
    })
    setTtsProfileDirty(!savedProfile)
    setStatus(
      savedProfile
        ? `已套用已保存的 ${preset.label} 语音方案。`
        : preset.provider === 'disabled'
          ? '已关闭 TTS；视频卡导出前需要开启整句 TTS 和表达 TTS。'
          : usesLocalVertexAuth
            ? `已套用 ${preset.label}，会使用本机 gcloud / Vertex AI 授权；建议先测试 TTS。`
            : shouldReuseMainMimoKey || shouldReuseMainQwenKey
              ? `已套用 ${preset.label}，会复用上方同服务商 API Key；建议先测试 TTS。`
              : `已套用 ${preset.label}，请填写对应 API Key 后测试 TTS。`,
    )
  }

  const toggleContent = (key: keyof ContentToggles) => {
    markRequestEditedIfRunning()
    setRequest((current) => ({
      ...current,
      content_toggles: {
        ...current.content_toggles,
        [key]: !current.content_toggles[key],
      },
    }))
  }

  const toggleLanguageFocus = (focus: LanguageFocus) => {
    markRequestEditedIfRunning()
    setRequest((current) => {
      const exists = current.language_focus.includes(focus)
      const next = exists ? current.language_focus.filter((item) => item !== focus) : [...current.language_focus, focus]
      return { ...current, language_focus: next.length ? next : current.language_focus }
    })
  }

  const toggleDocumentFocus = (focus: DocumentFocus) => {
    markRequestEditedIfRunning()
    setRequest((current) => {
      const exists = current.document_focus.includes(focus)
      const next = exists ? current.document_focus.filter((item) => item !== focus) : [...current.document_focus, focus]
      return { ...current, document_focus: next.length ? next : current.document_focus }
    })
  }

  const toggleCardType = (type: CardKind) => {
    markRequestEditedIfRunning()
    setRequest((current) => {
      const exists = current.card_types.includes(type)
      const next = exists ? current.card_types.filter((item) => item !== type) : [...current.card_types, type]
      return { ...current, card_types: next.length ? next : current.card_types }
    })
  }

  const selectPath = async (kind: SourcePathKind) => {
    const applyBatchFolder = (directory: string, files: string[]) => {
      const createdItems = createLocalVideoBatchItems(files)
      if (!createdItems.length) {
        setStatus('这个文件夹里没有找到可批量制卡的视频文件。')
        return
      }
      const title = request.title.trim() || titleFromPath(directory) || '视频学习包'
      const existingOtherSources = (request.batch_items ?? []).filter((item) => item.source_mode !== 'local')
      const sameSourceItems = batchItemsForSource(request.batch_items ?? [], 'local')
      const seen = new Set<string>()
      const mergedSameSource = [...sameSourceItems, ...createdItems].filter((item) => {
        const key = item.video_path || item.document_path || item.source_url || item.id
        if (seen.has(key)) return false
        seen.add(key)
        return true
      })
      const batchPackage = buildBatchPackage({ title, source_mode: 'local', items: mergedSameSource })
      patchRequest({
        title,
        source_mode: 'local',
        batch_enabled: true,
        batch_items: [...existingOtherSources, ...batchPackage.items],
        local_path_access_confirmed: true,
        video_path: '',
        subtitle_path: '',
        document_path: '',
      })
      setStatus(`已从文件夹添加 ${createdItems.length} 个素材到“${title}”，将导出为嵌套子牌组。`)
    }

    if (!isTauriRuntime()) {
      const prompt =
        kind === 'video'
          ? '输入视频绝对路径'
          : kind === 'subtitle'
            ? '输入 SRT 绝对路径'
            : '每行输入一个视频或字幕绝对路径，用来模拟视频文件夹批量添加'
      const value = window.prompt(prompt)
      if (!value) return
      if (kind === 'video-folder') {
        applyBatchFolder(value, pathLines(value))
        return
      }
      patchRequest(kind === 'video' ? { video_path: value } : { subtitle_path: value })
      return
    }

    if (kind === 'video-folder') {
      const selectedDirectory = await selectDirectory()
      if (typeof selectedDirectory !== 'string') return
      try {
        const files = await listDirectoryFiles(selectedDirectory)
        applyBatchFolder(selectedDirectory, files)
      } catch (error) {
        setStatus(redactSensitiveText(error))
      }
      return
    }

    const selected = await selectSingleFile(
      kind === 'video'
        ? [{ name: 'Video', extensions: ['mp4', 'mkv', 'mov', 'avi', 'webm'] }]
        : [{ name: 'Subtitle', extensions: ['srt'] }],
    )

    if (typeof selected === 'string') {
      if (kind === 'video') {
        const patch: Partial<GenerateRequest> = { video_path: selected, local_path_access_confirmed: true }
        if (!request.title.trim()) {
          patch.title = titleFromPath(selected)
        }
        if (!request.subtitle_path.trim()) {
          try {
            const suggestedSubtitle = await suggestSubtitlePath(selected, request.language)
            if (suggestedSubtitle) {
              patch.subtitle_path = suggestedSubtitle
            }
          } catch {
            // A missing suggestion should not block selecting the video.
          }
        }
        patchRequest(patch)
      } else {
        patchRequest({ subtitle_path: selected, local_path_access_confirmed: true })
      }
    }
  }

  const checkEnv = async () => {
    setBusy(true)
    setWorkerProgress(null)
    setStatus('正在检查 Python、ffmpeg 和 genanki。')
    try {
      if (!isTauriRuntime()) {
        setEnvStatus({
          python: 'browser-preview',
          ffmpeg: false,
          genanki: false,
          anki_installed: false,
          anki_connect: false,
        })
        setStatus('当前是浏览器预览模式，真实导出请运行 Tauri 桌面端。')
      } else {
        try {
          const result = await runWorker<EnvStatus>('check_env', {})
          setEnvStatus(result)
          setStatus(result.ffmpeg && result.genanki ? '环境检查通过。' : '环境缺少依赖，请查看状态卡。')
        } catch (workerError) {
          const bootstrap = await checkBootstrapEnv()
          setEnvStatus(bootstrap)
          setStatus(`Python worker 暂时不可用，已切换到原生环境检查：${redactSensitiveText(workerError)}`)
        }
      }
    } catch (error) {
      setStatus(redactSensitiveText(error))
    } finally {
      setBusy(false)
    }
  }

  const repairEnv = async (target: EnvRepairTarget = 'auto') => {
    if (
      isTauriRuntime() &&
      !window.confirm(
        '环境修复可能会调用 winget、pip 或打开 Anki 插件安装流程，并修改本机运行环境。请确认这是你主动发起的操作。',
      )
    ) {
      setStatus('已取消环境修复。')
      return
    }
    setBusy(true)
    setEnvRepairing(true)
    setWorkerProgress(null)
    setEnvRepairResult(null)
    const label =
      target === 'all'
        ? '正在一键修复本机环境：推荐 Python 3.12、Python 依赖、FFmpeg、Deno/Node、Anki 与 AnkiConnect。'
        : target === 'python_runtime'
          ? '正在尝试安装推荐 Python 3.12 运行环境。'
          : target === 'ffmpeg'
            ? '正在尝试安装 FFmpeg。'
            : target === 'js_runtime'
              ? '正在尝试安装 Deno / Node challenge solver。'
              : target === 'anki'
                ? '正在尝试安装 Anki 桌面端。'
                : target === 'anki_connect'
                  ? '正在打开 Anki 并准备 AnkiConnect 安装步骤。'
                  : '正在修复 Python venv、genanki 和 yt-dlp。'
    setStatus(label)
    try {
      if (!isTauriRuntime()) {
        setEnvRepairResult({
          ok: false,
          target,
          summary: '浏览器预览模式不能修复本机环境，请运行 Tauri 桌面端。',
          actions: [
            {
              id: 'desktop',
              label: '桌面端',
              status: 'manual',
              detail: '当前不是桌面运行时。',
              next_step: '请打开 Anki 卡片生成器桌面端后再使用环境修复。',
            },
          ],
        })
        setStatus('浏览器预览模式不能修复本机环境。')
        return
      }
      let result: EnvRepairResult | null = null
      if (target === 'all' || target === 'python_runtime') {
        result = await repairBootstrapEnv(target === 'all' ? 'all' : 'python_runtime')
      }
      if (target !== 'python_runtime') {
        try {
          const workerResult = await runWorker<EnvRepairResult>('repair_env', { target })
          result = mergeRepairResults(result, workerResult)
        } catch (workerError) {
          if (!result) throw workerError
          result = mergeRepairResults(result, {
            ok: false,
            target,
            summary: 'Python worker 后续修复没有执行成功。',
            actions: [
              {
                id: 'worker_repair',
                label: '继续修复 worker 依赖',
                status: 'failed',
                detail: redactSensitiveText(workerError),
                next_step: '先完成 Python 运行环境修复，重启应用后再点击一键修复。',
              },
            ],
          })
        }
      }
      if (!result) {
        result = await runWorker<EnvRepairResult>('repair_env', { target })
      }
      setEnvRepairResult(result)
      let env: EnvStatus
      try {
        env = await runWorker<EnvStatus>('check_env', {})
      } catch {
        env = await checkBootstrapEnv()
      }
      setEnvStatus(env)
      const failed = result.actions.filter((action) => action.status === 'failed').length
      const manual = result.actions.filter((action) => action.status === 'manual').length
      setStatus(
        failed
          ? `环境修复有 ${failed} 项失败，已自动复检；请查看修复日志。`
          : manual
            ? `环境修复已执行，仍有 ${manual} 项需要手动处理；已自动复检。`
            : '环境修复完成，已自动重新检查环境。',
      )
    } catch (error) {
      setStatus(`环境修复失败：${redactSensitiveText(error)}`)
    } finally {
      setEnvRepairing(false)
      setBusy(false)
    }
  }

  const testApi = async () => {
    const normalizedApi = normalizeApiConfigForRequest(request.api_config)
    if (
      normalizedApi.base_url !== request.api_config.base_url ||
      normalizedApi.model !== request.api_config.model ||
      normalizedApi.provider !== request.api_config.provider
    ) {
      patchRequest({ api_config: { ...normalizedApi, api_key: request.api_config.api_key } })
      setStatus('已自动修正模型 API 配置，再开始测试连接。')
    }
    let api: ApiConfig
    try {
      api = await loadApiConfigForWorker(normalizedApi)
    } catch {
      setApiTestResult({
        ok: false,
        provider: normalizedApi.provider,
        model: normalizedApi.model,
        message: '系统凭据读取失败，请在设置页重新保存 API Key。',
        error_code: 'MODEL_AUTH_FAILED',
        stage: 'model_api',
        retryable: false,
      })
      setStatus('API 测试失败：系统凭据读取失败，请重新保存 API Key。')
      return
    }
    const failBeforeRequest = (message: string, errorCode: string = 'MODEL_AUTH_FAILED') => {
      const result: ApiTestResult = {
        ok: false,
        provider: api.provider,
        model: api.model,
        message,
        error_code: errorCode,
        stage: 'model_api',
        retryable: false,
      }
      setApiTestResult(result)
      rememberSavedApiTestResult(api, result)
      setStatus(`API 测试失败：${message}`)
    }

    const configError = validateApiConfigForRequest(api)
    if (configError) {
      const errorCode = !api.model.trim()
        ? 'MODEL_NOT_FOUND'
        : configError.includes('Base URL') || configError.includes('URL')
          ? 'MODEL_CONNECTION_FAILED'
          : 'MODEL_AUTH_FAILED'
      failBeforeRequest(configError, errorCode)
      return
    }

    setApiTesting(true)
    setApiTestResult(null)
    setWorkerProgress(null)
    setStatus('正在测试模型 API 连接。')
    try {
      if (!isTauriRuntime()) {
        const result = {
          ok: api.provider === 'local',
          provider: api.provider,
          model: api.model,
          message:
            api.provider === 'local'
              ? '预览模式可用，但不能用于正式抽取学习点或制卡。'
              : '浏览器预览模式不能真实测试 API，请运行桌面端。',
        }
        setApiTestResult(result)
        setStatus(result.message)
      } else {
        const result = await runWorker<ApiTestResult>('test_api', { api_config: api })
        setApiTestResult(result)
        rememberSavedApiTestResult(api, result)
        setStatus(result.ok ? `API 测试通过：${result.message}` : `API 测试失败：${result.message}`)
      }
    } catch (error) {
      const message = redactSensitiveText(error)
      const result: ApiTestResult = {
        ok: false,
        provider: api.provider,
        model: api.model,
        message,
        error_code: 'MODEL_CONNECTION_FAILED',
        stage: 'model_api',
        retryable: true,
      }
      setApiTestResult(result)
      rememberSavedApiTestResult(api, result)
      setStatus(`API 测试失败：${message}`)
    } finally {
      setApiTesting(false)
    }
  }

  const testTts = async () => {
    let resolvedTtsRuntime: { apiConfig: ApiConfig; ttsConfig: TtsConfig }
    try {
      resolvedTtsRuntime = await loadTtsConfigForWorker(request.api_config.tts_config, request.api_config)
    } catch {
      const fallbackTts = resolveTtsConfig(request.api_config.tts_config, request.api_config)
      setTtsTestResult({
        ok: false,
        provider: fallbackTts.provider,
        model: fallbackTts.model,
        voice: fallbackTts.voice,
        message: '系统凭据读取失败，请在设置页重新保存 TTS/API Key。',
        error_code: 'TTS_AUTH_FAILED',
        stage: 'tts',
        retryable: false,
      })
      setStatus('TTS 测试失败：系统凭据读取失败，请重新保存 TTS/API Key。')
      return
    }
    const apiConfigForTts = resolvedTtsRuntime.apiConfig
    const currentTts = resolvedTtsRuntime.ttsConfig
    const failBeforeRequest = (message: string, errorCode: string = 'TTS_AUTH_FAILED') => {
      setTtsTestResult({
        ok: false,
        provider: currentTts.provider,
        model: currentTts.model,
        voice: currentTts.voice,
        message,
        error_code: errorCode,
        stage: 'tts',
        retryable: false,
      })
      setStatus(`TTS 测试失败：${message}`)
    }

    if (!currentTts.enabled || currentTts.provider === 'disabled') {
      failBeforeRequest('TTS 当前是关闭状态。', 'TTS_NOT_FOUND')
      return
    }
    const ttsConfigError = validateTtsConfigForRequest(currentTts)
    if (ttsConfigError) {
      const errorCode =
        !currentTts.model.trim() || !currentTts.voice.trim()
          ? 'TTS_NOT_FOUND'
          : ttsConfigError.includes('Base URL') || ttsConfigError.includes('URL')
            ? 'TTS_CONNECTION_FAILED'
            : 'TTS_AUTH_FAILED'
      failBeforeRequest(ttsConfigError, errorCode)
      return
    }
    if (currentTts.provider === 'grok' && !currentTts.voice.trim()) {
      failBeforeRequest('Grok TTS 需要填写 voice_id，例如 eve、ara、leo、rex、sal。', 'TTS_NOT_FOUND')
      return
    }
    if (currentTts.provider === 'gemini' && !currentTts.model.trim()) {
      failBeforeRequest('Gemini TTS 需要填写 TTS 模型名。', 'TTS_NOT_FOUND')
      return
    }
    if (currentTts.provider === 'gemini-vertex' && !currentTts.model.trim()) {
      failBeforeRequest('Gemini Vertex TTS 需要填写 TTS 模型名。', 'TTS_NOT_FOUND')
      return
    }
    if (
      (currentTts.provider === 'openai-compatible' || currentTts.provider === 'mimo') &&
      (!currentTts.base_url.trim() || !currentTts.model.trim())
    ) {
      failBeforeRequest(
        currentTts.provider === 'mimo'
          ? 'MIMO TTS 需要 Base URL 和模型名。'
          : 'OpenAI-compatible Speech 需要 Base URL 和模型名。',
        'TTS_NOT_FOUND',
      )
      return
    }
    if (
      currentTts.provider === 'mimo' &&
      isMimoTokenPlanKey(currentTts.api_key) &&
      !isMimoTokenPlanBase(currentTts.base_url)
    ) {
      failBeforeRequest(
        `你填的是 tp- 开头的 Token Plan Key，TTS Base URL 必须用 ${MIMO_TOKEN_PLAN_SGP_BASE_URL}，不能用公共 ${MIMO_OPENAI_BASE_URL}。请点 “MIMO SGP TTS” 预设。`,
        'TTS_AUTH_FAILED',
      )
      return
    }

    setTtsTesting(true)
    setTtsTestResult(null)
    setWorkerProgress(null)
    setStatus('正在测试 TTS 语音接口。')
    try {
      if (!isTauriRuntime()) {
        const result: TtsTestResult = {
          ok: false,
          provider: currentTts.provider,
          model: currentTts.model,
          voice: currentTts.voice,
          message: '浏览器预览模式不能真实测试 TTS，请运行桌面端。',
        }
        setTtsTestResult(result)
        setStatus(result.message)
      } else {
        const result = await runWorker<TtsTestResult>('test_tts', {
          tts_config: currentTts,
          api_config: apiConfigForTts,
          language: request.language,
        })
        setTtsTestResult(result)
        setStatus(result.ok ? `TTS 测试通过：${result.message}` : `TTS 测试失败：${result.message}`)
      }
    } catch (error) {
      const message = redactSensitiveText(error)
      setTtsTestResult({
        ok: false,
        provider: currentTts.provider,
        model: currentTts.model,
        voice: currentTts.voice,
        message,
        error_code: 'TTS_CONNECTION_FAILED',
        stage: 'tts',
        retryable: true,
      })
      setStatus(`TTS 测试失败：${message}`)
    } finally {
      setTtsTesting(false)
    }
  }

  const extractLearningPoints = async (options: { bypassCache?: boolean } = {}) => {
    const bypassCache = Boolean(options.bypassCache)
    const generateRequest: GenerateRequest = {
      ...request,
      video_path: cleanLocalPath(request.video_path),
      subtitle_path: cleanLocalPath(request.subtitle_path),
      document_path: cleanLocalPath(request.document_path),
    }
    if (workerBusy) {
      setStatus('已有任务正在运行，请先取消或等待完成。')
      return
    }
    const sourceInputError = learningPointExtractionSourceError(generateRequest)
    if (sourceInputError) {
      setStatus(sourceInputError)
      return
    }
    if (!confirmLocalPathAccessForRequest(generateRequest)) return
    let apiConfigForWorker: ApiConfig
    try {
      apiConfigForWorker = await loadApiConfigForWorker(generateRequest.api_config)
    } catch {
      setStatus('模型 API 凭据读取失败，请在设置页重新保存 API Key。')
      return
    }
    const resolvedApi = resolveGenerateApiConfig(apiConfigForWorker, generateRequest.source_mode)
    if (isTauriRuntime()) {
      const openApiSettings = (message: string) => {
        setActiveWorkspaceStage('generate')
        setSettingsTab('api')
        setSettingsOpen(true)
        setStatus(message)
      }
      if (generateRequest.api_config.provider === 'local') {
        openApiSettings('AI 精筛学习点需要正式模型 API。请先在“模型 API”里选择服务商、保存配置并测试连接。')
        return
      }
      if (resolvedApi.error) {
        openApiSettings(`AI 精筛学习点前模型 API 配置未通过：${resolvedApi.error}`)
        return
      }
      if (resolvedApi.fallbackReason) {
        const fallbackIssue = resolvedApi.fallbackReason.replace(/[。.!！?？]+$/u, '')
        openApiSettings(`模型 API 未就绪：${fallbackIssue}。学习点抽取不会退回本地半成品，请先测试模型 API。`)
        return
      }
      if (!apiReadyForGeneration) {
        openApiSettings(
          '模型 API 尚未通过测试，不能进行 AI 学习点精筛。保存过且测试通过的模型方案无需重复测试；如果改过配置，请重新保存并测试。',
        )
        return
      }
      if (
        resolvedApi.api.base_url !== request.api_config.base_url ||
        resolvedApi.api.model !== request.api_config.model ||
        resolvedApi.api.provider !== request.api_config.provider
      ) {
        patchResolvedApiForState(resolvedApi.api, generateRequest.api_config)
      }
    }
    if (isTauriRuntime() && !envStatus) {
      setActiveWorkspaceStage('review')
      setSettingsOpen(false)
      setStatus('抽取学习点前需要先检查本地环境。请在左侧确认卡片点击“立即检查”，需要完整诊断时再查看详情。')
      return
    }
    if (!isTauriRuntime()) {
      const demoLearningPoints: LearningPointExtractionResult = {
        id: `lp_demo_${Date.now()}`,
        title: generateRequest.title || '浏览器演示字幕',
        source_mode: generateRequest.source_mode,
        video_path: '',
        subtitle_path: '',
        language: generateRequest.language,
        level_mode: generateRequest.level_mode,
        level: generateRequest.level,
        review_basis: 'ai_reviewed',
        ai_model_provider: 'browser-demo',
        ai_model_name: 'demo-ai-review',
        local_candidate_count: 1,
        ai_reviewed_source_count: 1,
        ai_reviewed_candidate_count: 1,
        ai_recommended_count: 1,
        ai_candidate_count: 0,
        ai_rejected_count: 0,
        source_sentences: [
          {
            id: 'src_demo_001',
            source_segment_id: 'src_demo_001',
            source_sentence: "I'm not really in the mood right now.",
            text: "I'm not really in the mood right now.",
            start: 1,
            end: 3,
            source_time: '00:00:01.000 - 00:00:03.000',
          },
        ],
        learning_points: [
          {
            id: 'lp_demo_mood',
            source_segment_id: 'src_demo_001',
            source_sentence: "I'm not really in the mood right now.",
            source_time: '00:00:01.000 - 00:00:03.000',
            start: 1,
            end: 3,
            exact_span: 'in the mood',
            answer_core: 'in the mood',
            normalized_answer: 'in the mood',
            type: 'phrase',
            candidate_kind: 'expression',
            phrase_type: 'collocation',
            level: 'B1',
            estimated_level: 'B1',
            level_reason: 'B1：高频自然口语词伙。',
            learning_action: '训练表达“有/没心情”。',
            learning_action_key: 'expression:in the mood',
            value_score: 4.4,
            level_fit_score: 5,
            final_score: 8.1,
            reason: '高频口语词伙，可迁移。',
            confidence: 'high',
            status: 'recommended',
            status_reason: '高价值、合法、不重复，默认推荐。',
            source: 'local_rule',
            review_source: 'ai',
            ai_decision: 'recommend',
            ai_value_score: 4.4,
            ai_reason: '浏览器演示精筛通过。',
            ai_batch_id: 'demo_ai_review_1',
            validation_issues: [],
            repair_history: [],
          },
        ],
        learning_point_summary: {
          total: 1,
          recommended: 1,
          candidate_only: 0,
          hidden_duplicate: 0,
          hard_blocked: 0,
          by_type: { phrase: 1 },
          by_level: { B1: 1 },
        },
      }
      applyLearningPointResult(demoLearningPoints)
      setActiveWorkspaceStage('review')
      setWorkerProgress({
        command: 'extract_learning_points',
        stage: 'done',
        percent: 100,
        message: '演示学习点抽取完成。',
      })
      setWorkerOperation({ status: 'succeeded', command: 'extract_learning_points' })
      setStatus('已生成浏览器演示学习点。真实字幕抽取请用 Tauri 桌面端。')
      return
    }

    setProject(null)
    setLearningPointResult(null)
    setSelectedLearningPointIds(new Set())
    setGenerationConfirmOpen(false)
    setGenerationQueueSelectedIds(null)
    setGenerationBatchRuntime(null)
    generationRetryBaseProjectRef.current = null
    lastExportFullRef.current = null
    activeAnkiVerifyApkgPathRef.current = null
    releaseEvidenceRawSnapshotRef.current = emptyReleaseEvidenceRawSnapshot()
    setLastExport(null)
    setAnkiVerifyResult(null)
    setActiveSegmentId(null)
    setActiveWorkspaceStage('review')
    setBusy(true)
    setLastWorkerError(null)
    setCardGenerationCacheNamespace(bypassCache ? `cold_${Date.now()}` : null)
    setRequestEditedDuringRun(false)
    setWorkerProgress({
      command: 'extract_learning_points',
      stage: 'start',
      percent: 1,
      message: '准备从字幕抽取学习点。',
    })
    setStatus(
      bypassCache
        ? '正在不使用缓存重新抽取学习点：本轮会重新调用模型精筛。'
        : '正在读取字幕并抽取词伙、口语、单词用法、语法和听力学习点；可能复用同素材缓存。',
    )
    try {
      const requestSnapshot = JSON.parse(
        JSON.stringify(
          buildLearningPointExtractionPayload({
            request: generateRequest,
            apiConfig: resolvedApi.api,
            reuseAiReviewCache: !bypassCache,
            disableAiReviewCacheRead: bypassCache,
          }),
        ),
      ) as GenerateRequest
      const job = await startWorkerJob('extract_learning_points', requestSnapshot)
      const nextOperation: WorkerOperation = {
        status: 'running',
        command: 'extract_learning_points',
        jobId: job.job_id,
      }
      workerOperationRef.current = nextOperation
      setWorkerOperation(nextOperation)
      setWorkerProgress({
        job_id: job.job_id,
        command: 'extract_learning_points',
        stage: 'start',
        percent: 1,
        message: '学习点抽取任务已在后台运行。',
      })
      setStatus(
        bypassCache
          ? '不使用缓存的学习点抽取任务已在后台运行。完成后可以按类型和级别筛选，再生成卡片。'
          : '学习点抽取任务已在后台运行。完成后你可以按类型和级别筛选，再生成卡片。',
      )
    } catch (error) {
      setBusy(false)
      setWorkerOperation({ status: 'failed', command: 'extract_learning_points' })
      setLastWorkerError(null)
      setStatus(redactSensitiveText(error))
    }
  }

  const generate = async () => {
    if (request.source_mode !== 'document' && !request.batch_enabled) {
      await extractLearningPoints()
      return
    }
    const generateRequest: GenerateRequest = {
      ...request,
      video_path: cleanLocalPath(request.video_path),
      subtitle_path: cleanLocalPath(request.subtitle_path),
      document_path: cleanLocalPath(request.document_path),
    }
    const activeBatchItems = batchItemsForSource(generateRequest.batch_items ?? [], generateRequest.source_mode)
    if (workerBusy) {
      setStatus('已有任务正在运行，请先取消或等待完成。')
      return
    }
    const sourceInputError = directGenerationSourceError(generateRequest, activeBatchItems.length)
    if (sourceInputError) {
      setStatus(sourceInputError)
      return
    }
    if (!confirmLocalPathAccessForRequest(generateRequest)) return
    let apiConfigForWorker: ApiConfig
    try {
      apiConfigForWorker = await loadApiConfigForWorker(generateRequest.api_config)
    } catch {
      setStatus('模型 API 凭据读取失败，请在设置页重新保存 API Key。')
      return
    }
    const resolvedApi = resolveGenerateApiConfig(apiConfigForWorker, generateRequest.source_mode)
    if (isTauriRuntime()) {
      const openPreflightSettings = (tab: SettingsTab, message: string) => {
        setActiveWorkspaceStage('generate')
        setSettingsTab(tab)
        setSettingsOpen(true)
        setStatus(message)
      }

      if (!envStatus) {
        setActiveWorkspaceStage('review')
        setSettingsOpen(false)
        setStatus('生成前需要先检查本地环境。请在左侧确认卡片点击“立即检查”，需要完整诊断时再查看详情。')
        return
      }
      if (!envReady) {
        setActiveWorkspaceStage('review')
        setSettingsOpen(false)
        setStatus('本地环境还没准备好，不能开始正式制卡。请在左侧确认卡片点击“一键修复”，或查看详情处理单项依赖。')
        return
      }
      if (generateRequest.api_config.provider === 'local') {
        openPreflightSettings(
          'api',
          '当前选择的是预览模式，不能作为正式制卡结果。请先在“模型 API”里选择服务商、保存配置并测试连接。',
        )
        return
      }
      if (resolvedApi.error) {
        openPreflightSettings('api', `生成前模型 API 配置未通过：${resolvedApi.error}`)
        return
      }
      if (resolvedApi.fallbackReason) {
        const fallbackIssue = resolvedApi.fallbackReason.replace(/[。.!！?？]+$/u, '')
        openPreflightSettings('api', `模型 API 未就绪：${fallbackIssue}。已禁止退回本地字幕草稿，请先测试模型 API。`)
        return
      }
      if (!apiReadyForGeneration) {
        openPreflightSettings(
          'api',
          '模型 API 尚未通过测试，不能开始正式制卡。保存过且测试通过的模型方案无需重复测试；如果改过配置，请重新保存并测试。',
        )
        return
      }

      if (
        resolvedApi.api.base_url !== request.api_config.base_url ||
        resolvedApi.api.model !== request.api_config.model ||
        resolvedApi.api.provider !== request.api_config.provider
      ) {
        patchResolvedApiForState(resolvedApi.api, generateRequest.api_config)
      }
    }
    lastExportFullRef.current = null
    activeAnkiVerifyApkgPathRef.current = null
    captureReleaseEvidenceRawSnapshot({ type: 'invalidate', scope: 'project_export_verify' })
    setLastExport(null)
    setAnkiVerifyResult(null)
    setActiveWorkspaceStage('review')
    setWorkerProgress({ command: 'generate', stage: 'start', percent: 1, message: '准备开始生成。' })
    setBusy(true)
    setLastWorkerError(null)
    setRequestEditedDuringRun(false)
    setStatus(
      generateRequest.batch_enabled
        ? `正在批量生成 ${activeBatchItems.length} 个子素材，并整理成嵌套 Anki 子牌组。`
        : generateRequest.source_mode === 'url'
          ? '正在下载 URL 视频和字幕，然后生成卡片。'
          : generateRequest.source_mode === 'document'
            ? '正在解析文档、总结知识点并生成卡片。'
            : generateRequest.subtitle_path
              ? '正在解析字幕、筛选片段并生成卡片。'
              : '正在自动匹配同目录字幕、筛选片段并生成卡片。',
    )
    try {
      const requestSnapshot = JSON.parse(
        JSON.stringify(
          buildDirectGenerationPayload({
            request: generateRequest,
            apiConfig: resolvedApi.api,
          }),
        ),
      ) as GenerateRequest
      if (!isTauriRuntime()) {
        const demo = createDemoProject(requestSnapshot)
        setProject(demo)
        setSegmentFilter('all')
        setActiveSegmentId(demo.segments[0]?.id ?? null)
        setStatus(
          generateRequest.source_mode === 'url'
            ? '已生成浏览器演示卡片。URL 下载需要在 Tauri 桌面端运行。'
            : generateRequest.source_mode === 'document'
              ? '已生成浏览器演示文档卡。真实文档解析和 apkg 导出请用 Tauri 桌面端。'
              : '已生成浏览器演示卡片。真实视频切片和 apkg 导出请用 Tauri 桌面端。',
        )
        setWorkerProgress({ command: 'generate', stage: 'done', percent: 100, message: '演示卡片生成完成。' })
        setWorkerOperation({ status: 'succeeded', command: 'generate' })
        setActiveWorkspaceStage('review')
        setBusy(false)
      } else {
        const job = await startWorkerJob('generate', requestSnapshot)
        const nextOperation: WorkerOperation = { status: 'running', command: 'generate', jobId: job.job_id }
        workerOperationRef.current = nextOperation
        setWorkerOperation(nextOperation)
        setWorkerProgress({
          job_id: job.job_id,
          command: 'generate',
          stage: 'start',
          percent: 1,
          message: '生成任务已在后台运行。你可以继续浏览、拖动窗口或打开设置。',
        })
        setStatus('生成任务已在后台运行。你可以继续浏览、拖动窗口或打开设置；再次生成和导出会暂时禁用。')
      }
    } catch (error) {
      setBusy(false)
      setWorkerOperation({ status: 'failed', command: 'generate' })
      setLastWorkerError(null)
      setStatus(redactSensitiveText(error))
    }
  }

  const extractLearningPointsWithoutCache = async () => {
    await extractLearningPoints({ bypassCache: true })
  }

  const cancelCurrentWorker = async () => {
    const jobId = workerOperation.jobId
    if (!jobId || !workerBusy) return
    setWorkerOperation((current) => ({ ...current, status: 'cancelling' }))
    setLastWorkerError(null)
    setStatus('正在取消当前任务，请稍等。')
    try {
      const result = await cancelWorkerJob(jobId)
      if (!result.cancelled) {
        setBusy(false)
        setWorkerOperation({ status: 'idle' })
        setWorkerProgress(null)
        setGenerationBatchRuntime(null)
        setStatus('当前任务已经结束。')
      }
    } catch (error) {
      setWorkerOperation((current) => ({ ...current, status: 'failed' }))
      setLastWorkerError(null)
      setStatus(redactSensitiveText(error))
    }
  }

  const openGenerationConfirmForLearningPoints = (ids: Set<string>) => {
    if (workerBusy) {
      setStatus('已有任务正在运行，请先取消或等待完成。')
      return
    }
    if (!learningPointResult) {
      setStatus('还没有学习点清单。请先从字幕抽取学习点。')
      return
    }
    const selectedPoints = selectedLearningPoints(learningPointResult.learning_points, ids)
    if (selectedPoints.length === 0) {
      setStatus('请先选择至少一个推荐或候选学习点。')
      return
    }
    setGenerationQueueSelectedIds(new Set(selectedPoints.map((point) => point.id)))
    setGenerationConfirmOpen(true)
    setActiveWorkspaceStage('review')
    setStatus(`请确认本轮 APKG 队列：${selectedPoints.length} 个学习点。确认后会自动生成卡片、音频、视频片段并打包。`)
  }

  const generateCardsFromLearningPoints = () => {
    generationRetryBaseProjectRef.current = null
    openGenerationConfirmForLearningPoints(selectedLearningPointIds)
  }

  const generateSingleLearningPoint = (pointId: string) => {
    if (!learningPointResult) {
      setStatus('还没有学习点清单。请先从字幕抽取学习点。')
      return
    }
    const selectedPoint = selectedLearningPoints(learningPointResult.learning_points, new Set([pointId]))[0]
    if (!selectedPoint) {
      setStatus('这条学习点当前不可制卡，请换一条推荐或候选学习点。')
      return
    }
    const single = new Set([selectedPoint.id])
    generationRetryBaseProjectRef.current = null
    setSelectedLearningPointIds(single)
    openGenerationConfirmForLearningPoints(single)
  }

  const closeGenerationConfirm = () => {
    setGenerationConfirmOpen(false)
    setGenerationQueueSelectedIds(null)
    generationAutoExportOutputDirRef.current = null
    setStatus('已关闭生成确认。本轮还没有调用模型。')
  }

  const removeGenerationQueueLearningPoint = (pointId: string) => {
    setGenerationQueueSelectedIds((current) => {
      const next = new Set(current ?? selectedLearningPointIds)
      next.delete(pointId)
      return next
    })
  }

  const retryMissingLearningPoints = () => {
    const source = lastLearningPointResultRef.current
    const currentProject = project
    const missingIds = [
      ...new Set(
        (currentProject?.card_generation_diagnostics?.items ?? [])
          .map((item) => item.learning_point_id)
          .filter((id): id is string => Boolean(id)),
      ),
    ]
    if (!source || !currentProject) {
      setStatus('缺少上一次学习点清单，无法只重试未生成项。请重新抽取后再生成。')
      return
    }
    if (!missingIds.length) {
      setStatus('当前没有可重试的未生成学习点。')
      return
    }
    generationRetryBaseProjectRef.current = currentProject
    const missingSelection = new Set(missingIds)
    lastExportFullRef.current = null
    activeAnkiVerifyApkgPathRef.current = null
    captureReleaseEvidenceRawSnapshot({ type: 'invalidate', scope: 'project_export_verify' })
    setLearningPointResult(source)
    setProject(null)
    setLastExport(null)
    setAnkiVerifyResult(null)
    setSelectedLearningPointIds(missingSelection)
    setGenerationQueueSelectedIds(missingSelection)
    setGenerationConfirmOpen(true)
    setActiveWorkspaceStage('review')
    setStatus(`已载入 ${missingIds.length} 个未生成学习点；确认后只重试这些项，已生成卡片会保留。`)
  }

  const confirmGenerateCardsFromLearningPoints = async () => {
    if (workerBusy) {
      setStatus('已有任务正在运行，请先取消或等待完成。')
      return
    }
    if (!learningPointResult) {
      setStatus('还没有学习点清单。请先从字幕抽取学习点。')
      return
    }
    const activeSelectedIds = generationQueueSelectedIds ?? selectedLearningPointIds
    const selectedPoints = selectedLearningPoints(learningPointResult.learning_points, activeSelectedIds)
    if (selectedPoints.length === 0) {
      setStatus('本轮生成队列为空。请至少保留一个推荐或候选学习点。')
      return
    }
    const generateRequest: GenerateRequest = {
      ...request,
      video_path: cleanLocalPath(request.video_path),
      subtitle_path: cleanLocalPath(request.subtitle_path),
      document_path: cleanLocalPath(request.document_path),
    }
    if (!confirmLocalPathAccessForRequest(generateRequest)) return
    let apiConfigForWorker: ApiConfig
    try {
      apiConfigForWorker = await loadApiConfigForWorker(generateRequest.api_config)
    } catch {
      setStatus('模型 API 凭据读取失败，请在设置页重新保存 API Key。')
      return
    }
    const resolvedApi = resolveGenerateApiConfig(apiConfigForWorker, generateRequest.source_mode)
    if (isTauriRuntime()) {
      const openPreflightSettings = (tab: SettingsTab, message: string) => {
        setActiveWorkspaceStage('generate')
        setSettingsTab(tab)
        setSettingsOpen(true)
        setStatus(message)
      }

      if (!envStatus) {
        setActiveWorkspaceStage('review')
        setSettingsOpen(false)
        setStatus('生成 APKG 前需要先检查本地环境。请在左侧确认卡片点击“立即检查”，需要完整诊断时再查看详情。')
        return
      }
      if (!envReady) {
        setActiveWorkspaceStage('review')
        setSettingsOpen(false)
        setStatus('本地环境还没准备好，不能生成 APKG。请在左侧确认卡片点击“一键修复”，或查看详情处理单项依赖。')
        return
      }
      if (generateRequest.api_config.provider === 'local') {
        openPreflightSettings(
          'api',
          '当前选择的是预览模式，不能作为正式卡片结果。请先在“模型 API”里选择服务商、保存配置并测试连接。',
        )
        return
      }
      if (resolvedApi.error) {
        openPreflightSettings('api', `生成 APKG 前模型 API 配置未通过：${resolvedApi.error}`)
        return
      }
      if (resolvedApi.fallbackReason) {
        const fallbackIssue = resolvedApi.fallbackReason.replace(/[。.!！?？]+$/u, '')
        openPreflightSettings('api', `模型 API 未就绪：${fallbackIssue}。已禁止退回本地字幕草稿，请先测试模型 API。`)
        return
      }
      if (!apiReadyForGeneration) {
        openPreflightSettings(
          'api',
          '模型 API 尚未通过测试，不能生成 APKG。保存过且测试通过的模型方案无需重复测试；如果改过配置，请重新保存并测试。',
        )
        return
      }
      const resolvedTtsForPreflight = resolveTtsConfig(generateRequest.api_config.tts_config, resolvedApi.api)
      if (ttsRequired && (!resolvedTtsForPreflight.enabled || resolvedTtsForPreflight.provider === 'disabled')) {
        openPreflightSettings(
          'tts',
          '视频卡导出需要整句 TTS 和表达 TTS。请在“语音/TTS”里启用并测试通过后再生成 APKG。',
        )
        return
      }
      if (ttsRequired && !ttsReadyForGeneration) {
        openPreflightSettings('tts', '视频卡导出需要先通过 TTS 测试，否则不会生成 APKG。请测试语音配置后再继续。')
        return
      }

      if (
        resolvedApi.api.base_url !== request.api_config.base_url ||
        resolvedApi.api.model !== request.api_config.model ||
        resolvedApi.api.provider !== request.api_config.provider
      ) {
        patchResolvedApiForState(resolvedApi.api, generateRequest.api_config)
      }
    }
    if (!isTauriRuntime()) {
      const demo = createDemoProject(request)
      setProject(demo)
      setLearningPointResult(null)
      setSelectedLearningPointIds(new Set())
      setGenerationConfirmOpen(false)
      setGenerationQueueSelectedIds(null)
      setSegmentFilter('all')
      setActiveSegmentId(demo.segments[0]?.id ?? null)
      setWorkerProgress({
        command: 'generate_cards_from_learning_points',
        stage: 'done',
        percent: 100,
        message: '演示卡片生成完成。',
      })
      setWorkerOperation({ status: 'succeeded', command: 'generate_cards_from_learning_points' })
      setStatus(
        `演示卡片生成完成。已把 ${selectedPoints.length} 个演示学习点生成浏览器演示卡片；真实 APKG 导出请用 Tauri 桌面端。`,
      )
      return
    }
    setGenerationConfirmOpen(false)
    setBusy(true)
    setLastWorkerError(null)
    setWorkerProgress({
      command: 'generate_cards_from_learning_points',
      stage: 'select_output_dir',
      percent: 0,
      message: '正在打开 APKG 保存目录选择器。',
    })
    setStatus('正在打开 APKG 保存目录选择器。选择后会自动生成卡片正文、TTS、视频片段并打包。')
    await waitForNextPaint()
    const defaultOutputDir = defaultExportDirectoryForRequest(request) ?? (await defaultExportDirectory())
    const selectedOutputDir = await selectDirectory({
      title: APKG_EXPORT_DIRECTORY_DIALOG_TITLE,
      defaultPath: defaultOutputDir,
    })
    if (typeof selectedOutputDir !== 'string') {
      generationAutoExportOutputDirRef.current = null
      setBusy(false)
      setWorkerProgress(null)
      setGenerationConfirmOpen(true)
      setStatus('已取消：未选择 APKG 保存目录，本轮还没有调用模型。')
      return
    }
    const releaseOutputGuard = releaseApkgOutputGuardForProject(learningPointResult, selectedOutputDir)
    if (releaseOutputGuard.status === 'blocked') {
      generationAutoExportOutputDirRef.current = null
      setBusy(false)
      setWorkerProgress(null)
      setWorkerOperation({ status: 'failed', command: 'export' })
      setLastWorkerError(releaseApkgTargetGuardFailureEvent(releaseOutputGuard))
      setGenerationConfirmOpen(true)
      setStatus(`已暂停生成：${releaseOutputGuard.statusMessage}`)
      return
    }
    generationAutoExportOutputDirRef.current = selectedOutputDir
    setGenerationConfirmOpen(false)
    const queueIds = selectedPoints.map((point) => point.id)
    const batchSize = learningPointGenerationBatchSize(queueIds.length)
    const totalBatches = Math.max(1, Math.ceil(queueIds.length / batchSize))
    const projectId = `project_${Date.now()}`
    const retryBaseProject = generationRetryBaseProjectRef.current
    const baseGeneratedLearningPointIds = retryBaseProject ? generatedLearningPointIdsFromProject(retryBaseProject) : []
    const runtime: GenerationBatchRuntime = {
      active: true,
      queueIds,
      activeBatchIds: [],
      batchSize,
      totalBatches,
      completedBatches: 0,
      completedCount: 0,
      generatedCount: 0,
      missingCount: 0,
      exportableCount: 0,
      nextIndex: 0,
      projectId,
      baseGeneratedLearningPointIds,
      mergedProject: retryBaseProject,
      request: generateRequest,
      apiConfig: resolvedApi.api,
    }
    setGenerationBatchRuntime(runtime)
    setBusy(true)
    setLastWorkerError(null)
    lastExportFullRef.current = null
    activeAnkiVerifyApkgPathRef.current = null
    captureReleaseEvidenceRawSnapshot({ type: 'invalidate', scope: 'export_and_verify' })
    setLastExport(null)
    setAnkiVerifyResult(null)
    setWorkerProgress({
      command: 'generate_cards_from_learning_points',
      stage: 'start',
      percent: 1,
      message:
        totalBatches > 1
          ? `准备分 ${totalBatches} 批生成正文，完成后自动打包 APKG。`
          : '准备生成正文，完成后自动打包 APKG。',
    })
    setStatus(
      totalBatches > 1
        ? `正在生成 APKG：先把 ${selectedPoints.length} 个学习点分 ${totalBatches} 批生成正文，再自动生成音频、切片并打包。`
        : `正在生成 APKG：先生成 ${selectedPoints.length} 张卡片正文，再自动生成音频、切片并打包。`,
    )
    try {
      await startNextLearningPointGenerationBatch(runtime)
      if (totalBatches <= 1) {
        setGenerationQueueSelectedIds(null)
      }
    } catch (error) {
      setBusy(false)
      setGenerationBatchRuntime(null)
      generationAutoExportOutputDirRef.current = null
      setWorkerOperation({ status: 'failed', command: 'generate_cards_from_learning_points' })
      setLastWorkerError(null)
      setGenerationConfirmOpen(true)
      setStatus(redactSensitiveText(error))
    }
  }

  async function startExportForProject(options: StartExportOptions = {}) {
    if (!options.auto && workerBusy) {
      setStatus('已有任务正在运行，请先取消或等待完成。')
      return false
    }
    const targetProject = options.projectOverride ?? project
    if (!targetProject) {
      setStatus('还没有可导出的卡片。')
      return false
    }
    clearStaleReviewResults()
    const exportPreparation = prepareProjectForExport(targetProject)
    const projectForExport = normalizeProjectForExportWorker(exportPreparation.project)
    captureReleaseEvidenceRawSnapshot({
      type: 'project_for_export',
      project: projectForExport,
      learningPointResult: lastLearningPointResultRef.current,
    })
    setProject(projectForExport)
    if (exportPreparation.status === 'blocked') {
      setLastWorkerError(null)
      setStatus(exportPreparation.statusMessage)
      setWorkerOperation({ status: 'failed', command: 'export' })
      return false
    }
    if (exportPreparation.statusMessage) {
      setStatus(exportPreparation.statusMessage)
    }
    if (!isTauriRuntime()) {
      setStatus('浏览器预览模式不能导出 apkg，请运行 npm run tauri:dev。')
      return false
    }
    let exportRuntimeConfig: { apiConfig: ApiConfig; ttsConfig: TtsConfig }
    try {
      exportRuntimeConfig = await loadTtsConfigForWorker(request.api_config.tts_config, request.api_config)
    } catch {
      setStatus('导出前读取 TTS/API 凭据失败，请在设置页重新保存 Key。')
      return false
    }
    const exportApiConfig = exportRuntimeConfig.apiConfig
    const resolvedExportTtsConfig = exportRuntimeConfig.ttsConfig
    const exportTtsConfigError = validateTtsConfigForRequest(resolvedExportTtsConfig)
    const exportTtsBlockReason = videoExportTtsBlockReason(
      projectForExport,
      resolvedExportTtsConfig,
      exportTtsConfigError,
    )
    if (exportTtsBlockReason) {
      setLastWorkerError(null)
      setWorkerOperation({ status: 'failed', command: 'export' })
      setStatus(exportTtsBlockReason)
      return false
    }
    const ttsConfigForExport = exportTtsConfigError
      ? { ...resolvedExportTtsConfig, enabled: false, provider: 'disabled' as const }
      : resolvedExportTtsConfig

    const defaultOutputDir =
      defaultExportDirectoryForProject(projectForExport) ??
      defaultExportDirectoryForRequest(request) ??
      (await defaultExportDirectory())
    const outputDir =
      options.outputDir ??
      (await selectDirectory({
        title: APKG_EXPORT_DIRECTORY_DIALOG_TITLE,
        defaultPath: defaultOutputDir,
      }))
    if (typeof outputDir !== 'string') {
      setLastWorkerError(null)
      setStatus('已取消导出：未选择 APKG 保存目录。')
      return false
    }
    const releaseOutputGuard = releaseApkgOutputGuardForProject(projectForExport, outputDir)
    if (releaseOutputGuard.status === 'blocked') {
      setLastWorkerError(releaseApkgTargetGuardFailureEvent(releaseOutputGuard))
      setWorkerOperation({ status: 'failed', command: 'export' })
      setStatus(releaseOutputGuard.statusMessage)
      return false
    }

    lastExportFullRef.current = null
    activeAnkiVerifyApkgPathRef.current = null
    captureReleaseEvidenceRawSnapshot({ type: 'invalidate', scope: 'export_and_verify' })
    setLastExport(null)
    setAnkiVerifyResult(null)
    setActiveWorkspaceStage('review')
    setBusy(true)
    setLastWorkerError(null)
    setWorkerProgress({ command: 'export', stage: 'start', percent: 1, message: '准备开始导出。' })
    setStatus(
      exportStartingStatusMessage({
        sourceMode: projectForExport.source_mode,
        auto: options.auto,
        ttsConfigError: exportTtsConfigError,
      }),
    )
    try {
      const canonicalApkgPath = releaseOutputGuard.canonicalApkgPath
      const exportPayload = {
        project: buildProjectExportPayloadProject({
          project: projectForExport,
          templateId: request.template_id,
          apiConfig: exportApiConfig,
          ttsConfig: ttsConfigForExport,
          disableMediaCacheRead: releaseTargetRequiresColdMediaCacheReadsDisabled(releaseOutputGuard.releaseTarget),
        }),
        output_dir: outputDir,
        ...(canonicalApkgPath ? { canonical_apkg_path: canonicalApkgPath } : {}),
      }
      const job = await startWorkerJob('export', exportPayload)
      if (releaseOutputGuard.releaseTarget) {
        releaseExportTargetsByJobIdRef.current.set(job.job_id, releaseOutputGuard.releaseTarget)
      }
      const nextOperation: WorkerOperation = { status: 'running', command: 'export', jobId: job.job_id }
      workerOperationRef.current = nextOperation
      setWorkerOperation(nextOperation)
      setWorkerProgress({
        job_id: job.job_id,
        command: 'export',
        stage: 'start',
        percent: 1,
        message: exportWorkerStartedProgressMessage(options.auto),
      })
      setStatus(exportWorkerStartedStatusMessage(options.auto))
      return true
    } catch (error) {
      setBusy(false)
      setWorkerOperation({ status: 'failed', command: 'export' })
      setLastWorkerError(null)
      setStatus(redactSensitiveText(error))
      return false
    }
  }

  const exportApkg = async () => {
    await startExportForProject()
  }

  const revealExport = async () => {
    if (!lastExport?.apkg_path) return
    try {
      await revealPath(lastExport.apkg_path)
    } catch (error) {
      setStatus(redactSensitiveText(error))
    }
  }

  const openAnkiImport = async () => {
    if (!lastExport?.apkg_path) return
    setStatus(ankiOpenImportStartingStatusMessage())
    try {
      await openAnkiImportFile(lastExport.apkg_path)
      setStatus(ankiOpenImportRequestedStatusMessage())
    } catch (error) {
      setStatus(redactSensitiveText(error))
    }
  }

  const verifyAnkiImport = async () => {
    const exportForVerify = exportResultForAnkiVerify(lastExportFullRef.current, lastExport)
    const preparation = prepareAnkiVerifyStart({
      workerBusy,
      exportResult: exportForVerify,
      tauriRuntime: isTauriRuntime(),
    })
    if (!preparation.ok) {
      if (preparation.statusMessage) setStatus(preparation.statusMessage)
      return
    }
    activeAnkiVerifyApkgPathRef.current = preparation.exportResult.apkg_path
    captureReleaseEvidenceRawSnapshot({ type: 'invalidate', scope: 'verify' })
    setAnkiVerifying(true)
    setActiveWorkspaceStage('review')
    setLastWorkerError(null)
    setAnkiVerifyResult(null)
    setStatus(ankiVerifyStartingStatusMessage())
    try {
      const job = await startWorkerJob('verify_anki_import', buildAnkiVerifyPayload(preparation.exportResult))
      const nextOperation: WorkerOperation = { status: 'running', command: 'verify_anki_import', jobId: job.job_id }
      workerOperationRef.current = nextOperation
      setWorkerOperation(nextOperation)
      setWorkerProgress({
        job_id: job.job_id,
        command: 'verify_anki_import',
        stage: 'start',
        percent: 1,
        message: ankiVerifyWorkerStartedMessage(),
      })
      setStatus(ankiVerifyWorkerStartedMessage())
    } catch (error) {
      activeAnkiVerifyApkgPathRef.current = null
      setAnkiVerifying(false)
      setWorkerOperation({ status: 'failed', command: 'verify_anki_import' })
      setLastWorkerError(null)
      setStatus(redactSensitiveText(error))
    }
  }

  const setCardsEnabled = (enabled: boolean, segmentId?: string) => {
    clearStaleReviewResults()
    setProject((current) => {
      if (!current) return current
      const segments = current.segments.map((segment) =>
        segmentId && segment.id !== segmentId
          ? segment
          : {
              ...segment,
              cards: segment.cards.map((card) => ({
                ...card,
                enabled: enabled ? isUsableCardForExport(segment, card) : false,
              })),
            },
      )
      const selected = segments.reduce(
        (total, segment) => total + segment.cards.filter((card) => card.enabled).length,
        0,
      )
      return {
        ...current,
        quality_funnel: current.quality_funnel
          ? {
              ...current.quality_funnel,
              selected_card_count: selected,
              selected_exportable_card_count: selected,
              selected_repair_required_card_count: 0,
            }
          : {
              selected_card_count: selected,
              selected_exportable_card_count: selected,
              selected_repair_required_card_count: 0,
            },
        segments,
      }
    })
  }

  const invertCardSelection = () => {
    clearStaleReviewResults()
    setProject((current) => {
      if (!current) return current
      let selected = 0
      const segments = current.segments.map((segment) => ({
        ...segment,
        cards: segment.cards.map((card) => {
          const enabled = !card.enabled && isUsableCardForExport(segment, card)
          if (enabled) selected += 1
          return { ...card, enabled }
        }),
      }))
      return {
        ...current,
        quality_funnel: current.quality_funnel
          ? {
              ...current.quality_funnel,
              selected_card_count: selected,
              selected_exportable_card_count: selected,
              selected_repair_required_card_count: 0,
            }
          : {
              selected_card_count: selected,
              selected_exportable_card_count: selected,
              selected_repair_required_card_count: 0,
            },
        segments,
      }
    })
    setStatus('已反选当前可导出的卡。')
  }

  const updateCard = (segmentId: string, cardId: string, patch: Partial<Card>) => {
    clearStaleReviewResults()
    setProject((current) => {
      if (!current) return current
      return {
        ...current,
        segments: current.segments.map((segment) =>
          segment.id === segmentId
            ? {
                ...segment,
                cards: segment.cards.map((card) => (card.id === cardId ? { ...card, ...patch } : card)),
              }
            : segment,
        ),
      }
    })
  }

  const selectTemplate = (templateId: TemplateId) => {
    const publicTemplateId = publicTemplateIdFor(templateId, request.source_mode)
    clearStaleReviewResults()
    patchRequest({ template_id: publicTemplateId })
    setProject((current) => (current ? { ...current, template_id: publicTemplateId } : current))
  }

  const handleWorkerErrorAction = (actionId: WorkerErrorActionId) => {
    if (actionId === 'open-api-settings') {
      setSettingsTab('api')
      setSettingsOpen(true)
      setLastWorkerError(null)
      setStatus('已打开模型 API 设置，请检查 Key、Base URL 和模型名。')
      return
    }
    if (actionId === 'open-tts-settings') {
      setSettingsTab('tts')
      setSettingsOpen(true)
      setLastWorkerError(null)
      setStatus('已打开 TTS 设置，请检查语音 Key、模型和声音。')
      return
    }
    if (actionId === 'open-env-settings') {
      setSettingsTab('env')
      setSettingsOpen(true)
      setLastWorkerError(null)
      setStatus('已打开本地环境设置，请检查 Python、FFmpeg、yt-dlp 和依赖状态。')
      return
    }
    if (actionId === 'use-subtitle-only') {
      setLastWorkerError(null)
      setStatus('当前发布版只保留视频制卡，不再提供缺视频恢复。请修复下载/FFmpeg 问题后重试，避免生成缺视频卡。')
      return
    }
    if (actionId === 'skip-video-slicing') {
      setLastWorkerError(null)
      setStatus('当前发布版不再允许缺视频导出视频卡。请检查 FFmpeg 或重新生成素材后重试。')
      return
    }
    if (actionId === 'allow-private-network-url') {
      patchRequest({ allow_private_network_url: true })
      setStatus('已允许本机/内网 URL。本次只应在你信任该链接时继续；请点击重试任务。')
      return
    }
    if (actionId === 'allow-ytdlp-remote-components') {
      patchRequest({ allow_ytdlp_remote_components: true })
      setStatus('已允许 yt-dlp remote components。本次只应在你信任该视频来源时继续；请点击重试任务。')
      return
    }
    if (actionId === 'retry') {
      const failedCommand = lastWorkerError?.command
      setLastWorkerError(null)
      setWorkerProgress(null)
      setWorkerOperation({ status: 'idle' })
      setBusy(false)
      setAnkiVerifying(false)
      if (failedCommand === 'extract_learning_points') {
        void extractLearningPoints()
      } else if (failedCommand === 'generate_cards_from_learning_points') {
        void confirmGenerateCardsFromLearningPoints()
      } else if (failedCommand === 'export') {
        void exportApkg()
      } else if (failedCommand === 'verify_anki_import') {
        void verifyAnkiImport()
      } else {
        void generate()
      }
      return
    }
  }

  const buildReleaseObservedTimingCacheSnapshot = (
    context: Omit<BuildReleaseObservedSnapshotFromRawCaptureInput, 'capture'>,
  ) =>
    buildReleaseObservedSnapshotFromRawCapture({
      ...context,
      capture: releaseEvidenceRawSnapshotRef.current,
    })

  const buildReleaseObservedRawSnapshotHandoff = (
    context: Omit<BuildReleaseObservedSnapshotFromRawCaptureInput, 'capture'>,
  ) =>
    buildReleaseObservedRawSnapshotHandoffArtifact({
      ...context,
      capture: releaseEvidenceRawSnapshotRef.current,
    })

  const activeSegment = project?.segments.find((segment) => segment.id === activeSegmentId)
  const activeSegmentVideoSrc = activeSegment && project?.video_path ? toAssetUrl(project.video_path) : ''

  return {
    activeWorkspaceStage,
    activeSegment,
    activeSegmentId,
    activeSegmentVideoSrc,
    activeTemplate,
    activeApiKeySaved,
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
    applyApiPreset,
    applyCollectionPreset,
    applyTtsPreset,
    cancelCurrentWorker,
    capabilityHelp,
    capabilityLabels,
    cardOptions,
    checkEnv,
    contentOptions,
    documentFocusOptions,
    deepseekTextModels,
    envStatus,
    envRepairing,
    envRepairResult,
    exportApkg,
    extractLearningPointsWithoutCache,
    featuredApiPresets,
    featuredTtsPresets,
    geminiVertexTextModels,
    generate,
    generationConfirmOpen,
    generationQueuePoints,
    generationQueueSummary,
    generationRunState,
    generateCardsFromLearningPoints,
    generateSingleLearningPoint,
    closeGenerationConfirm,
    confirmGenerateCardsFromLearningPoints,
    handleTopbarDoubleClick,
    handleWorkerErrorAction,
    inspectorActionLabel,
    inspectorSheetOpen,
    inspectorState,
    isCancelling,
    isDesktopRuntime: isTauriRuntime(),
    lastExport,
    lastWorkerError,
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
    buildReleaseObservedRawSnapshotHandoff,
    buildReleaseObservedTimingCacheSnapshot,
    releaseEvidenceSummary,
    request,
    requestEditedDuringRun,
    responsiveMode,
    revealExport,
    removeGenerationQueueLearningPoint,
    retryMissingLearningPoints,
    repairEnv,
    runWindowAction,
    activeApiProfileId,
    activeTtsProfileId,
    activeTtsKeySaved,
    apiProfileDirty,
    apiProfileStatus,
    applySavedApiProfile,
    applySavedTtsProfile,
    savedApiProfiles,
    savedTtsProfiles,
    saveCurrentApiProfile,
    saveCurrentTtsProfile,
    selectionStrategyOptions,
    segmentFilter,
    segmentReviewCounts,
    selectedCardCount,
    selectedExportableCardCount: exportSelectionStats.selectedExportableCards,
    exportableCardCount: exportSelectionStats.exportableCards,
    repairRequiredCardCount: exportSelectionStats.repairRequiredCards,
    selectedRepairRequiredCardCount: exportSelectionStats.selectedRepairRequiredCards,
    selectedLearningPointCount,
    selectedLearningPointIds,
    invertCardSelection,
    selectCurrentLevel,
    selectPath,
    selectSegment: setActiveSegmentId,
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
  }
}

export type AppController = ReturnType<typeof useAppController>
