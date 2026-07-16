import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
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
  HermesProxyStatus,
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
import { applyCardPatchWithReliabilityInvalidation } from '../domain/reliability'
import {
  ankiVerificationPassed,
  ankiOpenImportRequestedStatusMessage,
  ankiOpenImportStartingStatusMessage,
  ankiVerifyStartingStatusMessage,
  ankiVerifyWorkerStartedMessage,
  buildAnkiMediaPreparationPayload,
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
import { isEnvironmentReadyForGeneration } from './readiness'
import { isSourceInputReady } from '../domain/sourceValidation'
import type { LearningPointExtractionResult } from '../domain/learningPoints'
import {
  defaultSelectedLearningPointIds,
  learningPointGenerationBatchSize,
  selectedLearningPoints,
} from '../domain/learningPoints'
import {
  isHermesLocalApiConfig,
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
  advanceApiProfileCredentialRevision,
  advanceTtsProfileCredentialRevision,
  apiAuthMode,
  apiConfigMatchesProfile,
  apiProfileIdFromConfig,
  apiProfileVerificationTarget,
  buildSavedApiProfile,
  buildSavedTtsProfile,
  loadSavedApiProfiles,
  loadSavedTtsProfiles,
  profileSecretKey,
  recordApiProfileVerification,
  recordTtsProfileVerification,
  removeSavedApiProfileCredential,
  removeSavedTtsProfileCredential,
  resolveSavedApiProfileVerification,
  resolveSavedTtsProfileVerification,
  saveSavedApiProfiles,
  saveSavedTtsProfiles,
  ttsAuthMode,
  ttsConfigMatchesProfile,
  ttsProfileIdFromConfig,
  ttsProfileVerificationTarget,
  upsertSavedApiProfile,
  upsertSavedTtsProfile,
  type ProfileVerificationTarget,
} from '../services/settingsProfiles'
import { persistSettingsTransaction } from '../services/settingsPersistenceTransaction'
import {
  applySettingsWithoutVerification,
  beginSettingsVerification,
  cancelSettingsVerification,
  completeSettingsVerification,
  discardSettingsDraft as discardSettingsDraftState,
  isSettingsDraftDirty,
  openSettingsDraft,
  patchApiSettingsDraft,
  patchTtsSettingsDraft,
  selectApiProfileForDraft,
  selectTtsProfileForDraft,
  setSettingsDraftMode,
  settingsDraftFingerprint,
  type SettingsDraftState,
  type SettingsDraftValues,
  type SettingsMode,
  type SettingsVerificationTarget,
} from './settingsDraftState'
import {
  loadSavedProjectForRequest,
  loadSavedRequest,
  projectMatchesRequest,
  stripRequestSecrets,
} from '../services/projectStorage'
import {
  buildWorkflowFileEvidence,
  collectWorkflowSourceFileRefs,
  compareApkgFileEvidence,
  compareSourceFileEvidence,
  fingerprintWorkflowRequest,
  fingerprintWorkflowSource,
  clearWorkflowCheckpoint,
  loadWorkflowCheckpointCandidate,
  normalizeWorkflowCheckpoint,
  readWorkflowArtifact,
  remainingGenerationQueueIds,
  remainingGenerationQueueIdsAfterSuccessfulActiveBatch,
  saveWorkflowCheckpoint,
  writeWorkflowArtifact,
  type WorkflowCheckpointV1,
  type WorkflowFileEvidence,
  type WorkflowSourceFileEvidence,
  type WorkflowSourceFileRef,
} from '../services/workflowCheckpoint'
import {
  decideOutputDirectory,
  loadOutputDirectoryPreference,
  saveOutputDirectoryPreference,
} from '../services/outputDirectoryPreference'
import {
  acknowledgeWorkerTaskResult,
  cancelWorkerJob,
  checkBootstrapEnv,
  deleteSecret,
  forceCancelWorkerJob,
  getWorkerJobStatus,
  getWorkerTask,
  isWorkerJobCancelled,
  listRecoverableWorkerTasks,
  loadSecret,
  readWorkerJobResult,
  recordRendererError,
  repairBootstrapEnv,
  runWorkerJobAndWait,
  saveSecret,
  secretExists,
  startWorkerJob,
  type WorkerJobObservation,
} from '../services/tauriWorker'
import { acknowledgeAppliedWorkerResults } from './workerResultAcknowledgement'
import { isTauriRuntime } from '../services/runtime'
import {
  checkHermesProxy as checkHermesProxyRuntime,
  startHermesProxy as startHermesProxyRuntime,
} from '../services/hermes'
import {
  checkOutputDirectory,
  inspectRecoveryFile,
  ensureAnkiRunning,
  openAnkiImport as openAnkiImportFile,
  defaultExportDirectory,
  listDirectoryFiles,
  revealPath,
  selectDirectory,
  selectSingleFile,
  suggestSubtitlePath,
  preparePreviewAssetUrl,
} from '../services/nativeShell'
import { redactSensitiveText } from '../services/redaction'
import {
  allowNextNativeWindowClose,
  listenForNativeCloseRequest,
  revokeNativeWindowClosePermission,
} from '../services/nativeCloseEvents'
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
  retryCardGenerationCacheNamespace,
} from './generationBatch'
import type { GenerationBatchProgress, GenerationBatchRuntime } from './generationBatch'
import {
  fallbackWorkerOperationFromFinish,
  resolveWorkerFinishedResult,
  workerFinishInvalidatedByEditedRequest,
  workerFinishMatchesActiveJob,
} from './workerFinished'
import {
  modelApiConfigChangeInvalidatesLearningArtifacts,
  requestPatchInvalidatesExportArtifacts,
  requestPatchInvalidatesLearningArtifacts,
} from './requestInvalidation'
import { clearStaleReviewWorkerError, workerFailureStatusMessage } from './exportFailureState'
import { compactExportResultForUi } from './exportResultState'
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
import { buildReleaseEvidenceSummary } from './releaseEvidenceSummary'
import { getTaskActivityStatus, normalizeVisibleOverallPercent } from './workerTaskState'
import {
  getForceCancelAvailability,
  reduceObservedWorkerTaskState,
  type ObservedWorkerTaskState,
} from './observedWorkerTaskState'
import { buildWorkflowCapabilityIssues, workflowRequiresCapabilityChecks } from './workflowCapabilityIssues'
import {
  completedWorkerResultKind,
  recoveryEvidenceRetryDelayMs,
  selectBoundWorkerTask,
  shouldRetryCheckpointWithBackup,
} from './workflowTaskRecovery'
import type { EnvironmentCapabilityStatus, ServiceCapabilityStatus } from './systemCapabilityState'
import {
  buildWorkflowUiSnapshot,
  selectArtifactStage,
  selectProductStepForArtifact,
  type ProductStep,
  type UserNotice,
  type WorkflowActionId,
  type TaskSnapshot as WorkflowTaskSnapshot,
  type WorkflowIssue,
} from './workflowState'
import {
  buildReleaseObservedRawSnapshotHandoffArtifact,
  buildReleaseObservedSnapshotFromRawCapture,
  emptyReleaseEvidenceRawSnapshot,
  reduceReleaseEvidenceRawSnapshot,
  type BuildReleaseObservedSnapshotFromRawCaptureInput,
  type ReleaseEvidenceRawSnapshotEvent,
} from './releaseEvidenceObservedCapture'
import { buildSettingsProfileStatus } from './settingsProfileStatus'
import { safelyCloseWindow, type SafeWindowCloseFailureReason } from './safeWindowClose'
import { waitForWorkerTerminal } from './waitForWorkerTerminal'
import { buildApiTestStatus, buildEffectiveApiTestResult, buildTtsTestStatus } from './settingsTestStatus'

const INSPECTOR_COLLAPSE_MS = 130

function safeCloseFailureMessage(reason: SafeWindowCloseFailureReason, error?: unknown): string {
  if (reason === 'terminal_timeout')
    return '任务仍未安全停止，窗口会保持打开。请等待任务结束，或使用“强制结束任务”后再关闭。'
  if (reason === 'task_missing') return '无法确认后台任务是否已经停止，窗口会保持打开；请稍后重试关闭。'
  if (reason === 'task_read_failed') return `读取后台任务状态失败，窗口会保持打开：${redactSensitiveText(error)}`
  if (reason === 'checkpoint_failed') return `最新恢复点保存失败，窗口会保持打开：${redactSensitiveText(error)}`
  if (reason === 'cancel_failed') return `任务停止请求失败，窗口会保持打开：${redactSensitiveText(error)}`
  if (reason === 'close_failed') return `窗口关闭失败，应用仍保持打开：${redactSensitiveText(error)}`
  return '后台任务尚未确认安全停止，窗口会保持打开。'
}
function workflowActionFromWorkerCommand(command: WorkerOperation['command']): WorkflowActionId {
  if (command === 'extract_learning_points') return 'analyze_source'
  if (command === 'generate' || command === 'generate_cards_from_learning_points') return 'generate_cards'
  if (command === 'export') return 'export_cards'
  if (command === 'verify_anki_import') return 'import_and_verify'
  return 'resolve_blocker'
}
function isWorkflowResultCommand(
  command: WorkerOperation['command'],
): command is
  | 'extract_learning_points'
  | 'generate_cards_from_learning_points'
  | 'generate'
  | 'export'
  | 'verify_anki_import' {
  return (
    command === 'extract_learning_points' ||
    command === 'generate_cards_from_learning_points' ||
    command === 'generate' ||
    command === 'export' ||
    command === 'verify_anki_import'
  )
}
async function reusableOutputDirectory(directory?: string | null): Promise<string | null> {
  const preferredDirectory = directory ?? loadOutputDirectoryPreference()?.directory
  if (!preferredDirectory) return null
  try {
    const availability = await checkOutputDirectory(preferredDirectory)
    const decision = decideOutputDirectory({
      directory: preferredDirectory,
      availability,
    })
    return decision.action === 'reuse' ? decision.directory : null
  } catch {
    return null
  }
}

type SourcePathKind = 'video' | 'subtitle' | 'video-folder'

type StartExportOptions = {
  outputDir?: string
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
    ? pathValue
        .trim()
        .replace(/[/\\]+/g, '/')
        .replace(/\/+$/, '')
        .toLowerCase()
    : ''
}
type RecoveryEvidenceVerdict =
  | { status: 'valid' }
  | { status: 'changed'; message: string }
  | { status: 'unavailable'; message: string }

type ApkgRecoveryEvidenceVerdict =
  | { status: 'valid'; evidence: WorkflowFileEvidence; verificationValid: boolean }
  | { status: 'changed'; message: string }
  | { status: 'unavailable'; message: string }

function workflowSourceEvidenceKey(refs: WorkflowSourceFileRef[]): string {
  return JSON.stringify(refs)
}

function workflowApkgEvidenceKey(result: ExportResult): string {
  return [
    normalizedComparablePath(result.apkg_path),
    String(result.apkg_sha256 ?? '').toLowerCase(),
    String(result.apkg_size_bytes ?? ''),
    String(result.apkg_mtime_ms ?? ''),
  ].join('\u0000')
}

async function inspectWorkflowSourceEvidence(refs: WorkflowSourceFileRef[]): Promise<WorkflowSourceFileEvidence[]> {
  const inspections = new Map<string, Awaited<ReturnType<typeof inspectRecoveryFile>>>()
  const result: WorkflowSourceFileEvidence[] = []
  for (const ref of refs) {
    const pathKey = normalizedComparablePath(ref.path)
    let inspection = inspections.get(pathKey)
    if (!inspection) {
      inspection = await inspectRecoveryFile(ref.path, false)
      inspections.set(pathKey, inspection)
    }
    const built = buildWorkflowFileEvidence(ref.path, inspection)
    if (!built.ok) throw new Error('无法记录素材恢复证据：' + built.message)
    result.push({ ...built.evidence, ...ref })
  }
  return result
}

async function validateWorkflowSourceEvidence(
  request: GenerateRequest,
  expected: WorkflowSourceFileEvidence[] | undefined,
): Promise<RecoveryEvidenceVerdict> {
  const refs = collectWorkflowSourceFileRefs(request)
  if (refs.length === 0) return { status: 'valid' }
  if (!expected || expected.length !== refs.length) {
    return { status: 'changed', message: '本地素材清单与上次任务不一致。' }
  }
  const evidenceById = new Map(expected.map((item) => [item.id, item]))
  for (const ref of refs) {
    const evidence = evidenceById.get(ref.id)
    if (
      !evidence ||
      evidence.role !== ref.role ||
      evidence.batchItemId !== ref.batchItemId ||
      normalizedComparablePath(evidence.path) !== normalizedComparablePath(ref.path)
    ) {
      return { status: 'changed', message: '本地素材路径或角色与上次任务不一致。' }
    }
    let inspection: Awaited<ReturnType<typeof inspectRecoveryFile>>
    try {
      inspection = await inspectRecoveryFile(ref.path, false)
    } catch {
      return { status: 'unavailable', message: '暂时无法读取本地素材，尚未覆盖上次安全检查点。' }
    }
    if (!inspection.ok && inspection.error?.retryable) {
      return { status: 'unavailable', message: '暂时无法读取本地素材，尚未覆盖上次安全检查点。' }
    }
    const comparison = compareSourceFileEvidence(evidence, inspection)
    if (!comparison.matches) {
      return { status: 'changed', message: '本地素材已移动、缺失或内容发生变化。' }
    }
  }
  return { status: 'valid' }
}

async function inspectWorkflowApkgEvidence(result: ExportResult): Promise<WorkflowFileEvidence> {
  const inspection = await inspectRecoveryFile(result.apkg_path, true)
  const built = buildWorkflowFileEvidence(result.apkg_path, inspection, true)
  if (!built.ok) throw new Error('无法记录 APKG 恢复证据：' + built.message)
  const reportedHash = String(result.apkg_sha256 ?? '').toLowerCase()
  if (reportedHash && built.evidence.sha256 !== reportedHash) {
    throw new Error('APKG 已在导出后发生变化，未写入新的恢复检查点。')
  }
  return built.evidence
}

async function validateWorkflowApkgEvidence(
  checkpoint: WorkflowCheckpointV1,
  restoredExport: ExportResult,
  restoredVerification: AnkiVerifyResult | null,
): Promise<ApkgRecoveryEvidenceVerdict> {
  const expectedPath = checkpoint.apkgPath || restoredExport.apkg_path
  if (
    !expectedPath ||
    normalizedComparablePath(expectedPath) !== normalizedComparablePath(restoredExport.apkg_path) ||
    (checkpoint.apkgEvidence &&
      normalizedComparablePath(checkpoint.apkgEvidence.path) !== normalizedComparablePath(expectedPath))
  ) {
    return { status: 'changed', message: 'APKG 路径与上次导出结果不一致。' }
  }

  let inspection: Awaited<ReturnType<typeof inspectRecoveryFile>>
  try {
    inspection = await inspectRecoveryFile(expectedPath, true)
  } catch {
    return { status: 'unavailable', message: '暂时无法核验 APKG，尚未覆盖上次安全检查点。' }
  }
  if (!inspection.ok && inspection.error?.retryable) {
    return { status: 'unavailable', message: '暂时无法核验 APKG，尚未覆盖上次安全检查点。' }
  }
  const built = buildWorkflowFileEvidence(expectedPath, inspection, true)
  if (!built.ok) return { status: 'changed', message: 'APKG 已缺失或无法作为普通文件读取。' }

  const expectedEvidence = checkpoint.apkgEvidence ?? {
    ...built.evidence,
    sha256: checkpoint.apkgSha256,
  }
  const comparison = compareApkgFileEvidence(expectedEvidence, inspection)
  if (!comparison.matches) return { status: 'changed', message: 'APKG 的 SHA-256 已发生变化。' }

  const actualHash = built.evidence.sha256 ?? ''
  const requiredHashes = [checkpoint.apkgSha256, restoredExport.apkg_sha256]
    .filter((value): value is string => Boolean(value))
    .map((value) => value.toLowerCase())
  if (requiredHashes.some((value) => value !== actualHash)) {
    return { status: 'changed', message: 'APKG 与导出记录的 SHA-256 不一致。' }
  }
  const verificationHash = String(restoredVerification?.apkg_sha256 ?? '').toLowerCase()
  return {
    status: 'valid',
    evidence: built.evidence,
    verificationValid:
      !restoredVerification ||
      (normalizedComparablePath(restoredVerification.apkg_path || expectedPath) ===
        normalizedComparablePath(expectedPath) &&
        (!verificationHash || verificationHash === actualHash)),
  }
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

function savedProfileCredentialRevision(profile: SavedApiProfile | SavedTtsProfile | null | undefined) {
  const revision = Number((profile as { credential_revision?: number } | null | undefined)?.credential_revision)
  return Number.isFinite(revision) && revision >= 0 ? Math.floor(revision) : 0
}

function profileVerificationRecordsCleared<T extends SavedApiProfile | SavedTtsProfile>(profile: T, revision: number) {
  return {
    ...profile,
    verification_schema_version: 1 as const,
    credential_revision: revision,
    verification_records: [],
  }
}

export function useAppController() {
  const initialRequest = useMemo(() => loadSavedRequest(), [])
  const [request, setRequest] = useState<GenerateRequest>(initialRequest)
  const initialProject = useMemo(() => loadSavedProjectForRequest(initialRequest), [initialRequest])
  const [project, setProject] = useState<Project | null>(initialProject)
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
  const [cancelRequestedAt, setCancelRequestedAt] = useState<number | null>(null)
  const [showForceCancel, setShowForceCancel] = useState(false)
  const [forceCancelBusy, setForceCancelBusy] = useState(false)
  const [requestEditedDuringRun, setRequestEditedDuringRun] = useState(false)
  const [activeSegmentId, setActiveSegmentId] = useState<string | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [settingsDraftState, setSettingsDraftState] = useState<SettingsDraftState | null>(null)
  const [settingsSaving, setSettingsSaving] = useState(false)
  const [apiTesting, setApiTesting] = useState(false)
  const [apiTestResult, setApiTestResult] = useState<ApiTestResult | null>(null)
  const [hermesChecking, setHermesChecking] = useState(false)
  const [hermesStarting, setHermesStarting] = useState(false)
  const [hermesStatus, setHermesStatus] = useState<HermesProxyStatus | null>(null)
  const [ttsTesting, setTtsTesting] = useState(false)
  const [ttsTestResult, setTtsTestResult] = useState<TtsTestResult | null>(null)
  const [lastExport, setLastExport] = useState<ExportResult | null>(null)
  const [outputDirectory, setOutputDirectory] = useState('')
  const lastExportFullRef = useRef<ExportResult | null>(null)
  const [lastWorkerError, setLastWorkerError] = useState<WorkerFinishedEvent | null>(null)
  const [ankiVerifying, setAnkiVerifying] = useState(false)
  const [ankiVerifyResult, setAnkiVerifyResult] = useState<AnkiVerifyResult | null>(null)
  const [previewRate, setPreviewRate] = useState(0.75)
  const [previewVideoSrc, setPreviewVideoSrc] = useState('')
  const [previewVideoError, setPreviewVideoError] = useState('')
  const [workerProgress, setWorkerProgress] = useState<WorkerProgress | null>(null)
  const [generationBatchProgress, setGenerationBatchProgress] = useState<GenerationBatchProgress | null>(null)
  const [cardGenerationCacheNamespace, setCardGenerationCacheNamespace] = useState<string | null>(null)
  const [showAdvancedApi, setShowAdvancedApi] = useState(false)
  const [showAdvancedTts, setShowAdvancedTts] = useState(false)
  const [showCapabilities, setShowCapabilities] = useState(false)
  const [settingsTab, setSettingsTab] = useState<SettingsTab>('api')
  const [savedApiProfiles, setSavedApiProfiles] = useState<SavedApiProfile[]>(() => loadSavedApiProfiles())
  const [secretAvailability, setSecretAvailability] = useState<Record<string, boolean>>({})
  const [checkpointReady, setCheckpointReady] = useState(false)
  const [checkpointRetryRevision, setCheckpointRetryRevision] = useState(0)
  const [workerResultAckRevision, setWorkerResultAckRevision] = useState(0)
  const [recoveredWorkflowTask, setRecoveredWorkflowTask] = useState<WorkflowTaskSnapshot | null>(null)
  const [recoveredGenerationIds, setRecoveredGenerationIds] = useState<string[]>([])
  const [savedTtsProfiles, setSavedTtsProfiles] = useState<SavedTtsProfile[]>(() => loadSavedTtsProfiles())
  const [apiProfileDirty, setApiProfileDirty] = useState(false)
  const [ttsProfileDirty, setTtsProfileDirty] = useState(false)
  const apiTestBindingRef = useRef<ProfileVerificationTarget | null>(null)
  const ttsTestBindingRef = useRef<ProfileVerificationTarget | null>(null)
  const apiTestRunRef = useRef(0)
  const ttsTestRunRef = useRef(0)
  const [segmentFilter, setSegmentFilter] = useState<SegmentFilter>('all')
  const settingsDraftStateRef = useRef<SettingsDraftState | null>(null)
  const [responsiveMode, setResponsiveMode] = useState<ResponsiveMode>('wide')
  const [inspectorState, setInspectorState] = useState<InspectorState>('open')
  const [productStep, setProductStep] = useState<ProductStep>(initialProject ? 'deliver' : 'source')
  const [activeWorkspaceStage, setActiveWorkspaceStage] = useState<WorkspaceStage>(initialProject ? 'review' : 'source')
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
  const abandonedRecoveryTaskIdsRef = useRef(new Set<string>())
  const releaseEvidenceRawSnapshotRef = useRef(emptyReleaseEvidenceRawSnapshot())
  const checkpointArtifactCacheRef = useRef<{
    learningPointValue: LearningPointExtractionResult | null
    learningPointRef?: string
    projectValue: Project | null
    projectRef?: string
    exportValue: ExportResult | null
    exportRef?: string
    verifyValue: AnkiVerifyResult | null
    verifyRef?: string
  }>({
    learningPointValue: null,
    projectValue: null,
    exportValue: null,
    verifyValue: null,
  })
  const checkpointEvidenceCacheRef = useRef<{
    sourceKey: string
    sourceEvidence?: WorkflowSourceFileEvidence[]
    apkgKey: string
    apkgEvidence?: WorkflowFileEvidence
  }>({
    sourceKey: '',
    apkgKey: '',
  })
  const checkpointWriteChainRef = useRef<Promise<void>>(Promise.resolve())
  const checkpointPersistenceSuspendedRef = useRef(false)
  const persistWorkflowCheckpointRef = useRef<() => Promise<void>>(async () => undefined)
  const closeInFlightRef = useRef(false)
  const checkpointWriteRetryAttemptRef = useRef(0)
  const checkpointWriteRetryTimerRef = useRef<number | null>(null)
  const pendingWorkerResultAcknowledgementsRef = useRef<Set<string>>(new Set())
  const workerResultAckRetryAttemptRef = useRef(0)
  const workerResultAckRetryTimerRef = useRef<number | null>(null)
  const activeAnkiVerifyApkgPathRef = useRef<string | null>(null)
  const releaseExportTargetsByJobIdRef = useRef<Map<string, ReleaseExportExpectedTarget>>(new Map())
  const handledWorkerFinishIdsRef = useRef<Set<string>>(new Set())
  const processingWorkerFinishIdsRef = useRef<Set<string>>(new Set())
  const handleWorkerFinishedRef = useRef<(payload: WorkerFinishedEvent) => Promise<void>>(async () => {})
  const locallyObservedWorkerJobIdsRef = useRef<Set<string>>(new Set())
  const observedWorkerTaskStateRef = useRef<ObservedWorkerTaskState | null>(null)
  const replaceWorkerOperation = useCallback((next: WorkerOperation) => {
    workerOperationRef.current = next
    setWorkerOperation(next)
  }, [])
  const queueWorkerResultAcknowledgement = useCallback((jobId: string) => {
    if (!jobId || !isTauriRuntime() || pendingWorkerResultAcknowledgementsRef.current.has(jobId)) return
    pendingWorkerResultAcknowledgementsRef.current.add(jobId)
    setWorkerResultAckRevision((revision) => revision + 1)
  }, [])
  const replaceSettingsDraftState = useCallback((next: SettingsDraftState | null) => {
    settingsDraftStateRef.current = next
    setSettingsDraftState(next)
  }, [])
  const updateSettingsDraftState = useCallback(
    (updater: (current: SettingsDraftState) => SettingsDraftState) => {
      const current = settingsDraftStateRef.current
      if (!current) return null
      const next = updater(current)
      replaceSettingsDraftState(next)
      return next
    },
    [replaceSettingsDraftState],
  )

  const publishWorkerProgress = useCallback(
    (progress: WorkerProgress, state: 'running' | 'cancelling' | 'succeeded' = 'running'): WorkerProgress => {
      const previous = workerProgressRef.current
      const batch = generationBatchRef.current
      const batchedGeneration = progress.command === 'generate_cards_from_learning_points' && Boolean(batch)
      const sameJob = Boolean(progress.job_id && previous?.job_id === progress.job_id)
      const carryPrevious = sameJob || batchedGeneration
      const percent = normalizeVisibleOverallPercent({
        previousPercent: carryPrevious && !previous?.indeterminate ? previous?.percent : null,
        phasePercent: progress.indeterminate ? null : progress.percent,
        completedItems: batchedGeneration ? batch?.completedCount : undefined,
        totalItems: batchedGeneration ? batch?.queueIds.length : undefined,
        activeItems: batchedGeneration ? batch?.activeBatchIds.length : undefined,
        state,
      })
      const normalized: WorkerProgress = {
        ...progress,
        percent: percent ?? 0,
        indeterminate: percent === null,
      }
      workerProgressRef.current = normalized
      setWorkerProgress(normalized)
      return normalized
    },
    [],
  )

  const observeWorkerJob = useCallback(
    (observation: WorkerJobObservation) => {
      const previous = observedWorkerTaskStateRef.current
      if (
        observation.type === 'started' &&
        previous?.lifecycle === 'terminal' &&
        previous.operation.jobId !== observation.job.job_id
      ) {
        if (previous.operation.jobId) locallyObservedWorkerJobIdsRef.current.delete(previous.operation.jobId)
        observedWorkerTaskStateRef.current = null
      }
      if (observation.type === 'started') {
        locallyObservedWorkerJobIdsRef.current.add(observation.job.job_id)
      }
      const next = reduceObservedWorkerTaskState(observedWorkerTaskStateRef.current, observation)
      observedWorkerTaskStateRef.current = next
      workerOperationRef.current = next.operation
      setWorkerOperation(next.operation)
      publishWorkerProgress(
        next.progress,
        next.operation.status === 'succeeded'
          ? 'succeeded'
          : next.operation.status === 'cancelling'
            ? 'cancelling'
            : 'running',
      )
      setBusy(next.lifecycle !== 'terminal')
      if (next.lifecycle !== 'terminal' && next.progress.message) setStatus(next.progress.message)
    },
    [publishWorkerProgress],
  )

  const releaseObservedWorkerJob = useCallback(() => {
    const observed = observedWorkerTaskStateRef.current
    const jobId = observed?.operation.jobId
    if (jobId) locallyObservedWorkerJobIdsRef.current.delete(jobId)
    if (jobId && workerOperationRef.current.jobId === jobId) {
      const idleOperation: WorkerOperation = { status: 'idle' }
      workerOperationRef.current = idleOperation
      setWorkerOperation(idleOperation)
    }
    observedWorkerTaskStateRef.current = null
    workerProgressRef.current = null
    setWorkerProgress(null)
    setBusy(false)
  }, [])

  const refreshHermesStatus = useCallback(async () => {
    setHermesChecking(true)
    try {
      const next = await checkHermesProxyRuntime()
      setHermesStatus(next)
      return next
    } catch (error) {
      const next: HermesProxyStatus = {
        state: 'error',
        message: 'Hermes 状态检测失败：' + redactSensitiveText(error),
        base_url: 'http://127.0.0.1:8645/v1',
        model: 'grok-4.5',
        managed: false,
        authenticated: false,
      }
      setHermesStatus(next)
      return next
    } finally {
      setHermesChecking(false)
    }
  }, [])

  const startHermesForSettings = useCallback(async () => {
    setHermesStarting(true)
    try {
      const next = await startHermesProxyRuntime()
      setHermesStatus(next)
      setStatus(next.message)
      return next
    } catch (error) {
      const next: HermesProxyStatus = {
        state: 'error',
        message: 'Hermes 代理启动失败：' + redactSensitiveText(error),
        base_url: 'http://127.0.0.1:8645/v1',
        model: 'grok-4.5',
        managed: false,
        authenticated: false,
      }
      setHermesStatus(next)
      setStatus(next.message)
      return next
    } finally {
      setHermesStarting(false)
    }
  }, [])

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
    setProductStep('source')
    setLearningPointResult(null)
    setSelectedLearningPointIds(new Set())
    setActiveSegmentId(null)
    setWorkerProgress(null)
    setGenerationConfirmOpen(false)
    setGenerationQueueSelectedIds(null)
    setGenerationBatchRuntime(null)
    generationRetryBaseProjectRef.current = null
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
  const sourceReady = isSourceInputReady(request)
  const tts = request.api_config.tts_config
  const ttsRequired = request.source_mode !== 'document'
  const activeApiProfileId = apiProfileIdFromConfig(request.api_config)
  const activeTtsProfileId = ttsProfileIdFromConfig(tts)
  const activeApiProfile = savedApiProfiles.find((profile) => profile.id === activeApiProfileId)
  const activeTtsProfile = savedTtsProfiles.find((profile) => profile.id === activeTtsProfileId)
  const settingsApiConfig = settingsDraftState?.draft.apiConfig ?? request.api_config
  const settingsTts = settingsApiConfig.tts_config
  const settingsActiveApiProfileId = apiProfileIdFromConfig(settingsApiConfig)
  const settingsActiveTtsProfileId = ttsProfileIdFromConfig(settingsTts)
  const settingsActiveApiProfile = savedApiProfiles.find(
    (profile) => profile.id === settingsActiveApiProfileId && apiConfigMatchesProfile(settingsApiConfig, profile),
  )
  const settingsActiveTtsProfile = savedTtsProfiles.find(
    (profile) => profile.id === settingsActiveTtsProfileId && ttsConfigMatchesProfile(settingsTts, profile),
  )
  const settingsModelCredentialRevision =
    settingsDraftState?.draft.credentialRevisions.model ?? savedProfileCredentialRevision(settingsActiveApiProfile)
  const settingsTtsCredentialRevision =
    settingsDraftState?.draft.credentialRevisions.tts ?? savedProfileCredentialRevision(settingsActiveTtsProfile)
  const settingsApiProfileSaved = Boolean(
    settingsActiveApiProfile &&
    savedProfileCredentialRevision(settingsActiveApiProfile) === settingsModelCredentialRevision,
  )
  const settingsTtsProfileSaved = Boolean(
    settingsActiveTtsProfile &&
    savedProfileCredentialRevision(settingsActiveTtsProfile) === settingsTtsCredentialRevision,
  )
  const settingsDraftDirty = Boolean(settingsDraftState && isSettingsDraftDirty(settingsDraftState))
  const settingsDraftMode = settingsDraftState?.mode ?? 'simple'
  const requiredSecretKeys = useMemo(() => {
    const keys = new Set<string>()
    if (activeApiProfile && apiAuthMode(request.api_config) === 'api_key') {
      keys.add(profileSecretKey('api', activeApiProfile.id))
    }
    if (activeTtsProfile && ttsAuthMode(tts) === 'api_key') {
      keys.add(profileSecretKey('tts', activeTtsProfile.id))
    }
    if (settingsActiveApiProfile && apiAuthMode(settingsApiConfig) === 'api_key') {
      keys.add(profileSecretKey('api', settingsActiveApiProfile.id))
    }
    if (settingsActiveTtsProfile && ttsAuthMode(settingsTts) === 'api_key') {
      keys.add(profileSecretKey('tts', settingsActiveTtsProfile.id))
    }
    return [...keys].sort()
  }, [
    activeApiProfile,
    activeTtsProfile,
    request.api_config,
    settingsActiveApiProfile,
    settingsActiveTtsProfile,
    settingsApiConfig,
    settingsTts,
    tts,
  ])
  const requiredSecretKeysSignature = requiredSecretKeys.join('\u0000')
  const secretAvailabilityRefreshSignature = [
    savedProfileCredentialRevision(activeApiProfile),
    savedProfileCredentialRevision(activeTtsProfile),
    savedProfileCredentialRevision(settingsActiveApiProfile),
    savedProfileCredentialRevision(settingsActiveTtsProfile),
  ].join(':')
  useEffect(() => {
    if (!isTauriRuntime() || !requiredSecretKeysSignature) return
    let disposed = false
    const keys = requiredSecretKeysSignature.split('\u0000')
    void Promise.all(
      keys.map(async (key) => {
        try {
          return [key, await secretExists(key)] as const
        } catch {
          return [key, null] as const
        }
      }),
    ).then((entries) => {
      if (disposed) return
      setSecretAvailability((current) => {
        const next = { ...current }
        for (const [key, available] of entries) {
          if (available !== null) next[key] = available
        }
        return next
      })
    })
    return () => {
      disposed = true
    }
  }, [requiredSecretKeysSignature, secretAvailabilityRefreshSignature])
  const resolveSecretAvailability = (
    kind: 'api' | 'tts',
    profile: SavedApiProfile | SavedTtsProfile | undefined,
    auth: string,
    typedSecret: string,
  ): boolean | null => {
    if (auth !== 'api_key') return null
    if (typedSecret.trim()) return true
    if (!profile) return false
    const key = profileSecretKey(kind, profile.id)
    return Object.prototype.hasOwnProperty.call(secretAvailability, key) ? secretAvailability[key] : null
  }
  const activeApiSecretAvailability = resolveSecretAvailability(
    'api',
    activeApiProfile,
    apiAuthMode(request.api_config),
    request.api_config.api_key,
  )
  const activeTtsSecretAvailability = resolveSecretAvailability('tts', activeTtsProfile, ttsAuthMode(tts), tts.api_key)
  const settingsApiSecretAvailability = resolveSecretAvailability(
    'api',
    settingsActiveApiProfile,
    apiAuthMode(settingsApiConfig),
    settingsApiConfig.api_key,
  )
  const settingsTtsSecretAvailability = resolveSecretAvailability(
    'tts',
    settingsActiveTtsProfile,
    ttsAuthMode(settingsTts),
    settingsTts.api_key,
  )
  const persistedSecretExists = (
    kind: 'api' | 'tts',
    profile: SavedApiProfile | SavedTtsProfile | undefined,
    auth: string,
  ): boolean => {
    if (!profile || auth !== 'api_key') return false
    return secretAvailability[profileSecretKey(kind, profile.id)] === true
  }
  const activeApiKeySaved = persistedSecretExists('api', activeApiProfile, apiAuthMode(request.api_config))
  const activeTtsKeySaved = persistedSecretExists('tts', activeTtsProfile, ttsAuthMode(tts))
  const settingsActiveApiKeySaved = persistedSecretExists(
    'api',
    settingsActiveApiProfile,
    apiAuthMode(settingsApiConfig),
  )
  const settingsActiveTtsKeySaved = persistedSecretExists('tts', settingsActiveTtsProfile, ttsAuthMode(settingsTts))

  const beginSettingsDraftSession = useCallback(
    (mode: SettingsMode) => {
      if (settingsDraftStateRef.current) return
      const next = openSettingsDraft({
        committed: {
          apiConfig: request.api_config,
          activeApiProfile: activeApiProfile ?? null,
          activeTtsProfile: activeTtsProfile ?? null,
          credentialRevisions: {
            model: savedProfileCredentialRevision(activeApiProfile),
            tts: savedProfileCredentialRevision(activeTtsProfile),
          },
        },
        mode,
      })
      replaceSettingsDraftState(next)
      apiTestBindingRef.current = null
      ttsTestBindingRef.current = null
      setApiTestResult(null)
      setTtsTestResult(null)
    },
    [activeApiProfile, activeTtsProfile, replaceSettingsDraftState, request.api_config],
  )
  const setSettingsDraftDisplayMode = useCallback(
    (mode: SettingsMode) => updateSettingsDraftState((current) => setSettingsDraftMode(current, mode)),
    [updateSettingsDraftState],
  )
  const discardSettingsChanges = useCallback(() => {
    updateSettingsDraftState(discardSettingsDraftState)
    apiTestBindingRef.current = null
    ttsTestBindingRef.current = null
    setApiTestResult(null)
    setTtsTestResult(null)
  }, [updateSettingsDraftState])
  const endSettingsDraftSession = useCallback(() => {
    replaceSettingsDraftState(null)
    setSettingsSaving(false)
    apiTestBindingRef.current = null
    ttsTestBindingRef.current = null
    setApiTestResult(null)
    setTtsTestResult(null)
  }, [replaceSettingsDraftState])
  const settingsSavedApiVerification =
    settingsApiProfileSaved && settingsActiveApiProfile
      ? resolveSavedApiProfileVerification(settingsActiveApiProfile, {
          secretExists: settingsApiSecretAvailability,
          checking: settingsApiSecretAvailability === null && apiAuthMode(settingsApiConfig) === 'api_key',
          hermesStatus,
        })
      : null
  const settingsSavedTtsVerification =
    settingsTtsProfileSaved && settingsActiveTtsProfile
      ? resolveSavedTtsProfileVerification(settingsActiveTtsProfile, {
          secretExists: settingsTtsSecretAvailability,
          checking: settingsTtsSecretAvailability === null && ttsAuthMode(settingsTts) === 'api_key',
          required: ttsRequired,
        })
      : null
  const settingsModelVerificationStatus = settingsDraftState?.verification.model.status ?? 'idle'
  const settingsTtsVerificationStatus = settingsDraftState?.verification.tts.status ?? 'idle'
  const settingsEffectiveApiTestResult: ApiTestResult | null =
    (settingsModelVerificationStatus === 'passed' || settingsModelVerificationStatus === 'failed') && apiTestResult
      ? apiTestResult
      : settingsSavedApiVerification?.state === 'ready' && settingsActiveApiProfile
        ? {
            ok: true,
            provider: settingsActiveApiProfile.provider,
            model: settingsActiveApiProfile.model,
            message: '当前草稿与已验证的模型方案一致。',
          }
        : null
  const settingsEffectiveTtsTestResult: TtsTestResult | null =
    (settingsTtsVerificationStatus === 'passed' || settingsTtsVerificationStatus === 'failed') && ttsTestResult
      ? ttsTestResult
      : settingsSavedTtsVerification?.state === 'ready' && settingsActiveTtsProfile
        ? {
            ok: true,
            provider: settingsActiveTtsProfile.provider,
            model: settingsActiveTtsProfile.model,
            voice: settingsActiveTtsProfile.voice,
            message: '当前草稿与已验证的语音方案一致。',
          }
        : null
  const settingsApiProfileStatus =
    settingsModelVerificationStatus === 'failed'
      ? '草稿验证失败'
      : settingsModelVerificationStatus === 'passed'
        ? '草稿验证通过 · 等待保存'
        : !settingsApiProfileSaved
          ? settingsDraftDirty
            ? '草稿有未应用更改'
            : '未保存到我的模型'
          : settingsSavedApiVerification?.state === 'ready'
            ? '已保存 · 当前验证通过'
            : settingsSavedApiVerification?.state === 'blocked'
              ? '已保存 · 最近验证失败'
              : settingsSavedApiVerification?.state === 'checking'
                ? '已保存 · 正在验证'
                : '已保存 · 需要重新验证'
  const settingsTtsProfileStatus =
    settingsTtsVerificationStatus === 'failed'
      ? '草稿验证失败'
      : settingsTtsVerificationStatus === 'passed'
        ? '草稿验证通过 · 等待保存'
        : !settingsTtsProfileSaved
          ? settingsDraftDirty
            ? '草稿有未应用更改'
            : '未保存到我的语音'
          : settingsSavedTtsVerification?.state === 'ready'
            ? '已保存 · 当前验证通过'
            : settingsSavedTtsVerification?.state === 'blocked'
              ? '已保存 · 最近验证失败'
              : settingsSavedTtsVerification?.state === 'checking'
                ? '已保存 · 正在验证'
                : '已保存 · 需要重新验证'
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
  const savedApiVerification =
    apiProfileSaved && activeApiProfile
      ? resolveSavedApiProfileVerification(activeApiProfile, {
          secretExists: activeApiSecretAvailability,
          checking: activeApiSecretAvailability === null && apiAuthMode(request.api_config) === 'api_key',
          hermesStatus,
        })
      : null
  const savedTtsVerification =
    ttsProfileSaved && activeTtsProfile
      ? resolveSavedTtsProfileVerification(activeTtsProfile, {
          secretExists: activeTtsSecretAvailability,
          checking: activeTtsSecretAvailability === null && ttsAuthMode(tts) === 'api_key',
          required: ttsRequired,
        })
      : null
  const savedApiTestReady = savedApiVerification?.state === 'ready'
  const savedTtsTestReady = savedTtsVerification?.state === 'ready'
  const apiProfileDisplayStatus = buildSettingsProfileStatus({
    profile: activeApiProfile ? { ...activeApiProfile, last_test_ok: savedApiTestReady } : undefined,
    profileSaved: apiProfileSaved,
    auth: apiAuthMode(request.api_config),
    notSavedLabel: '未保存到我的模型',
  })
  const ttsProfileDisplayStatus = buildSettingsProfileStatus({
    profile: activeTtsProfile ? { ...activeTtsProfile, last_test_ok: savedTtsTestReady } : undefined,
    profileSaved: ttsProfileSaved,
    auth: ttsAuthMode(tts),
    notSavedLabel: '未保存到我的语音',
  })
  const effectiveApiTestResult: ApiTestResult | null = buildEffectiveApiTestResult({
    result: apiTestResult,
    savedProfileTestOk: savedApiTestReady,
    activeProfile: activeApiProfile,
  })
  const apiVerificationTarget = apiProfileVerificationTarget(request.api_config, activeApiProfile)
  const fallbackModelCapability: ServiceCapabilityStatus = {
    state:
      request.api_config.provider === 'local'
        ? 'disabled'
        : effectiveApiTestResult?.ok
          ? 'ready'
          : effectiveApiTestResult
            ? 'blocked'
            : 'unknown',
    reason:
      request.api_config.provider === 'local'
        ? 'disabled'
        : effectiveApiTestResult?.ok
          ? 'verified'
          : effectiveApiTestResult
            ? 'verification_failed'
            : 'verification_missing',
    verificationFingerprint: apiVerificationTarget.verificationFingerprint,
    credentialRevision: apiVerificationTarget.credentialRevision,
  }
  const modelCapability: ServiceCapabilityStatus = apiTesting
    ? {
        ...(savedApiVerification ?? fallbackModelCapability),
        state: 'checking',
        reason: 'checking',
      }
    : (savedApiVerification ?? fallbackModelCapability)
  const hermesRuntimeReady =
    !isHermesLocalApiConfig(request.api_config) || (hermesStatus?.state === 'ready' && hermesStatus.authenticated)
  const apiReadyForGeneration =
    request.api_config.provider !== 'local' && modelCapability.state === 'ready' && hermesRuntimeReady
  const effectiveTtsTestResult: TtsTestResult | null =
    ttsTestResult ??
    (savedTtsTestReady && activeTtsProfile
      ? {
          ok: true,
          provider: activeTtsProfile.provider,
          model: activeTtsProfile.model,
          voice: activeTtsProfile.voice,
          message: '已保存的语音方案在当前配置和凭据版本下验证通过。',
        }
      : null)
  const ttsVerificationTarget = ttsProfileVerificationTarget(tts, activeTtsProfile)
  const fallbackTtsCapability: ServiceCapabilityStatus = {
    state:
      !tts.enabled || tts.provider === 'disabled'
        ? 'disabled'
        : effectiveTtsTestResult?.ok
          ? 'ready'
          : effectiveTtsTestResult
            ? 'blocked'
            : 'unknown',
    reason:
      !tts.enabled || tts.provider === 'disabled'
        ? 'disabled'
        : effectiveTtsTestResult?.ok
          ? 'verified'
          : effectiveTtsTestResult
            ? 'verification_failed'
            : 'verification_missing',
    verificationFingerprint: ttsVerificationTarget.verificationFingerprint,
    credentialRevision: ttsVerificationTarget.credentialRevision,
  }
  const ttsCapability: ServiceCapabilityStatus = ttsTesting
    ? {
        ...(savedTtsVerification ?? fallbackTtsCapability),
        state: 'checking',
        reason: 'checking',
      }
    : (savedTtsVerification ?? fallbackTtsCapability)
  const ttsReadyForGeneration = ttsCapability.state === 'ready'
  const envReady = isEnvironmentReadyForGeneration({
    desktopRuntime: isTauriRuntime(),
    envStatus,
    sourceMode: request.source_mode,
  })
  const environmentChecking =
    envRepairing ||
    ((workerOperation.status === 'running' || workerOperation.status === 'cancelling') &&
      (workerOperation.command === 'check_env' || workerOperation.command === 'repair_env'))
  const environmentRepairFailed = Boolean(envRepairResult?.actions.some((action) => action.status === 'failed'))
  const environmentCapability: EnvironmentCapabilityStatus = {
    state: environmentChecking
      ? 'checking'
      : !envStatus
        ? 'unknown'
        : envReady
          ? 'ready'
          : environmentRepairFailed
            ? 'blocked'
            : 'action_required',
    reason: environmentChecking
      ? 'checking'
      : !envStatus
        ? 'verification_missing'
        : envReady
          ? 'verified'
          : 'verification_failed',
    verificationFingerprint: 'environment:v1:' + request.source_mode,
    credentialRevision: 0,
  }
  const apiTestStatus = buildApiTestStatus({
    result: settingsDraftState ? settingsEffectiveApiTestResult : effectiveApiTestResult,
    testing: apiTesting,
    apiConfig: settingsDraftState ? settingsApiConfig : request.api_config,
  })
  const apiTestTone = apiTestStatus.tone
  const apiTestTitle = apiTestStatus.title
  const apiTestMessage = apiTestStatus.message
  const apiTestMeta = apiTestStatus.meta
  const ttsTestStatus = buildTtsTestStatus({
    result: settingsDraftState ? settingsEffectiveTtsTestResult : effectiveTtsTestResult,
    testing: ttsTesting,
    tts: settingsDraftState ? settingsTts : tts,
  })
  const ttsTestTone = ttsTestStatus.tone
  const ttsTestTitle = ttsTestStatus.title
  const ttsTestMessage = ttsTestStatus.message
  const ttsTestMeta = ttsTestStatus.meta
  const allApiPresets = [...featuredApiPresets, ...advancedApiPresets]
  const allTtsPresets = [...featuredTtsPresets, ...advancedTtsPresets]
  const apiProfileStatus = !apiProfileSaved
    ? apiProfileDisplayStatus.label
    : savedApiVerification?.state === 'ready'
      ? '已保存 · 当前验证通过'
      : savedApiVerification?.state === 'blocked'
        ? '已保存 · 最近验证失败'
        : savedApiVerification?.state === 'checking'
          ? '已保存 · 正在验证'
          : '已保存 · 需要重新验证'
  const ttsProfileStatus = !ttsProfileSaved
    ? ttsProfileDisplayStatus.label
    : savedTtsVerification?.state === 'ready'
      ? '已保存 · 当前验证通过'
      : savedTtsVerification?.state === 'blocked'
        ? '已保存 · 最近验证失败'
        : savedTtsVerification?.state === 'checking'
          ? '已保存 · 正在验证'
          : '已保存 · 需要重新验证'
  const workerBusy = workerOperation.status === 'running' || workerOperation.status === 'cancelling'
  const appBusy = busy || workerBusy
  const isCancelling = workerOperation.status === 'cancelling'
  useEffect(() => {
    if (!isCancelling) {
      setCancelRequestedAt(null)
      setShowForceCancel(false)
      setForceCancelBusy(false)
      return
    }

    if (cancelRequestedAt === null) {
      setCancelRequestedAt(Date.now())
      setShowForceCancel(false)
      return
    }

    const updateAvailability = () => {
      const availability = getForceCancelAvailability('cancelling', cancelRequestedAt, Date.now())
      setShowForceCancel(availability.visible)
      return availability
    }
    const availability = updateAvailability()
    if (availability.visible || availability.remainingMs === null) return
    const timerId = window.setTimeout(updateAvailability, Math.max(1, availability.remainingMs))
    return () => window.clearTimeout(timerId)
  }, [cancelRequestedAt, isCancelling])
  const inspectorUiState = buildInspectorUiState({
    responsiveMode,
    inspectorState,
    prefersReducedMotion,
  })
  const inspectorSheetOpen = inspectorUiState.inspectorSheetOpen
  const inspectorActionLabel = inspectorUiState.inspectorActionLabel
  const motionDuration = inspectorUiState.motionDuration

  const workflowArtifacts = useMemo(
    () => ({
      sourceReady,
      learningPointCount: learningPointResult?.learning_points.length ?? 0,
      draftCardCount: qualityCounts.total,
      apkgReady: Boolean(lastExport?.apkg_path),
      ankiVerified: ankiVerificationPassed(ankiVerifyResult),
    }),
    [
      ankiVerifyResult,
      lastExport?.apkg_path,
      learningPointResult?.learning_points.length,
      qualityCounts.total,
      sourceReady,
    ],
  )
  const workflowArtifactStage = selectArtifactStage(workflowArtifacts)
  const workflowActionForPage: WorkflowActionId =
    productStep === 'source'
      ? 'analyze_source'
      : productStep === 'select'
        ? 'generate_cards'
        : workflowArtifactStage === 'apkg_ready' || workflowArtifactStage === 'anki_verified'
          ? 'import_and_verify'
          : workflowArtifactStage === 'drafts_ready'
            ? 'export_cards'
            : 'generate_cards'
  const capabilityChecksRequired = workflowRequiresCapabilityChecks(
    workflowActionForPage,
    workflowArtifactStage,
    selectedLearningPointCount,
  )
  const workflowIssues = useMemo<WorkflowIssue[]>(
    () =>
      capabilityChecksRequired
        ? buildWorkflowCapabilityIssues({
            action: workflowActionForPage,
            environment: {
              state: environmentCapability.state,
              reason: environmentCapability.reason,
              verificationFingerprint: environmentCapability.verificationFingerprint,
              credentialRevision: environmentCapability.credentialRevision,
            },
            model: {
              state: modelCapability.state,
              reason: modelCapability.reason,
              verificationFingerprint: modelCapability.verificationFingerprint,
              credentialRevision: modelCapability.credentialRevision,
            },
            tts: {
              state: ttsCapability.state,
              reason: ttsCapability.reason,
              verificationFingerprint: ttsCapability.verificationFingerprint,
              credentialRevision: ttsCapability.credentialRevision,
            },
            ttsRequired,
          })
        : [],
    [
      capabilityChecksRequired,
      environmentCapability.credentialRevision,
      environmentCapability.reason,
      environmentCapability.state,
      environmentCapability.verificationFingerprint,
      modelCapability.credentialRevision,
      modelCapability.reason,
      modelCapability.state,
      modelCapability.verificationFingerprint,
      ttsCapability.credentialRevision,
      ttsCapability.reason,
      ttsCapability.state,
      ttsCapability.verificationFingerprint,
      ttsRequired,
      workflowActionForPage,
    ],
  )
  const workflowOperationSnapshot = useMemo<WorkflowTaskSnapshot | null>(() => {
    if (!workerBusy || !workerOperation.command) return null
    const action = workflowActionFromWorkerCommand(workerOperation.command)
    const now = Date.now()
    const observed =
      observedWorkerTaskStateRef.current?.operation.jobId === workerOperation.jobId
        ? observedWorkerTaskStateRef.current
        : null
    const updatedAt = observed?.lastProgressAt ?? now
    const elapsedMs = Math.max(0, workerProgress?.elapsed_ms ?? 0)
    const rawPercent = observed
      ? observed.overallPercent
      : Number.isFinite(workerProgress?.percent)
        ? (workerProgress?.percent ?? 0)
        : null
    const overallPercent = rawPercent === null ? null : Math.max(0, Math.min(99, rawPercent))
    const remainingItems = generationBatchProgress
      ? Math.max(0, generationBatchProgress.queueIds.length - generationBatchProgress.completedCount)
      : undefined
    return {
      schemaVersion: 1,
      id: workerOperation.jobId ?? workerOperation.command,
      action,
      state: workerOperation.status === 'cancelling' ? 'cancelling' : 'running',
      startedAt: now - elapsedMs,
      updatedAt,
      cancellable: true,
      phaseLabel: workerProgress?.stage_label ?? workerProgress?.stage,
      message: workerProgress?.message,
      overallPercent,
      remainingItems,
    }
  }, [
    generationBatchProgress,
    workerBusy,
    workerOperation.command,
    workerOperation.jobId,
    workerOperation.status,
    workerProgress,
  ])
  const workflowNotice = useMemo<UserNotice | null>(() => {
    if (!lastWorkerError) return null
    return {
      id: lastWorkerError.job_id || 'worker-failure',
      tone: 'error',
      title: '任务没有完成',
      detail: redactSensitiveText(lastWorkerError.error || lastWorkerError.error_code || '请查看失败原因后重试。'),
      occurredAt: Date.now(),
      relatedAction: workflowActionForPage,
      retryable: lastWorkerError.retryable !== false,
    }
  }, [lastWorkerError, workflowActionForPage])
  const workflowUiSnapshot = useMemo(
    () =>
      buildWorkflowUiSnapshot({
        step: productStep,
        artifacts: workflowArtifacts,
        selectedLearningPointCount,
        exportableCardCount: exportSelectionStats.selectedExportableCards,
        repairRequiredCardCount: exportSelectionStats.repairRequiredCards,
        operation: workflowOperationSnapshot ?? recoveredWorkflowTask,
        issues: workflowIssues,
        notice: workflowNotice,
      }),
    [
      exportSelectionStats.repairRequiredCards,
      exportSelectionStats.selectedExportableCards,
      recoveredWorkflowTask,
      productStep,
      selectedLearningPointCount,
      workflowArtifacts,
      workflowIssues,
      workflowNotice,
      workflowOperationSnapshot,
    ],
  )
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
  const hermesApiConfigured = isHermesLocalApiConfig(request.api_config)

  useEffect(() => {
    if (settingsOpen && settingsTab === 'api' && hermesApiConfigured) {
      void refreshHermesStatus()
    }
  }, [hermesApiConfigured, refreshHermesStatus, settingsOpen, settingsTab])

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
    if (!workerBusy) return
    setRecoveredWorkflowTask(null)
  }, [workerBusy])

  useEffect(() => {
    if (!isTauriRuntime()) {
      setCheckpointReady(true)
      return
    }
    let cancelled = false
    let retryTimer: number | null = null
    let retryAttempt = 0
    let restoreInFlight = false
    const readOptionalArtifact = async <T>(reference: string | undefined): Promise<T | null> => {
      if (!reference) return null
      return readWorkflowArtifact<T>(reference)
    }
    const scheduleEvidenceRetry = (message: string, publishStatus = true) => {
      if (cancelled) return
      if (retryTimer !== null) window.clearTimeout(retryTimer)
      const delayMs = recoveryEvidenceRetryDelayMs(retryAttempt)
      retryAttempt += 1
      if (publishStatus) setStatus(`${message} 将在 ${String(Math.ceil(delayMs / 1_000))} 秒后自动重试。`)
      retryTimer = window.setTimeout(() => {
        retryTimer = null
        void restoreCheckpoint()
      }, delayMs)
    }
    const restoreCheckpoint = async () => {
      if (restoreInFlight || cancelled) return
      restoreInFlight = true
      let taskEvidenceWarning = ''
      let taskEvidenceRetryScheduled = false
      try {
        const [checkpointResult, tasksResult] = await Promise.allSettled([
          loadWorkflowCheckpointCandidate('primary'),
          listRecoverableWorkerTasks(),
        ])
        if (cancelled) return
        if (tasksResult.status === 'rejected') {
          taskEvidenceWarning = '暂时无法读取后台任务状态；安全检查点仍已独立恢复，后台任务状态会自动重试。'
          taskEvidenceRetryScheduled = true
          scheduleEvidenceRetry('暂时无法读取后台任务状态，现有任务和检查点不会被误判或覆盖。', false)
        }
        const taskEvidence = tasksResult.status === 'fulfilled' ? tasksResult.value : { tasks: [], errors: [] }
        if (taskEvidence.errors.length > 0) {
          taskEvidenceWarning = `已跳过 ${String(taskEvidence.errors.length)} 个损坏或过期的旧任务记录；其他有效任务和安全检查点仍可恢复。`
        }
        const recoverableTasks = taskEvidence.tasks.filter((task) => !abandonedRecoveryTaskIdsRef.current.has(task.id))
        if (checkpointResult.status === 'rejected') {
          scheduleEvidenceRetry('暂时无法读取上次安全检查点，现有检查点不会被覆盖。')
          return
        }
        let checkpointCandidate: 'primary' | 'backup' = 'primary'
        let primaryRecoveryFailure: unknown = null
        let checkpoint = checkpointResult.value
        if (!checkpoint) {
          checkpoint = await loadWorkflowCheckpointCandidate('backup')
          if (checkpoint) checkpointCandidate = 'backup'
        }
        if (!checkpoint) {
          const missingCheckpointNotice = recoverableTasks.some((task) =>
            ['queued', 'running', 'cancelling', 'interrupted'].includes(task.state),
          )
            ? '发现中断的后台任务，但缺少可验证的安全输入；已停止自动继续，请重新选择素材。'
            : ''
          const recoveryStatus = [missingCheckpointNotice, taskEvidenceWarning].filter(Boolean).join(' ')
          if (recoveryStatus) setStatus(recoveryStatus)
          const rememberedOutputDirectory = await reusableOutputDirectory()
          if (cancelled) return
          if (rememberedOutputDirectory) setOutputDirectory(rememberedOutputDirectory)
          setCheckpointReady(true)
          return
        }
        for (;;) {
          try {
            const boundTaskSelection = selectBoundWorkerTask(recoverableTasks, {
              checkpointTaskId: checkpoint.task?.id,
              requestFingerprint: checkpoint.requestFingerprint,
            })
            if (checkpoint.requestFingerprint !== fingerprintWorkflowRequest(checkpoint.request)) {
              throw new Error('检查点数据已经变化，已停止自动恢复。')
            }
            if (
              checkpoint.sourceFingerprint &&
              checkpoint.sourceFingerprint !== fingerprintWorkflowSource(checkpoint.request)
            ) {
              throw new Error('检查点数据已经变化，已停止自动恢复。')
            }

            const sourceRefs = collectWorkflowSourceFileRefs(checkpoint.request)
            const sourceVerdict = await validateWorkflowSourceEvidence(checkpoint.request, checkpoint.sourceEvidence)
            if (cancelled) return
            if (sourceVerdict.status === 'unavailable') {
              scheduleEvidenceRetry(sourceVerdict.message)
              return
            }
            if (sourceVerdict.status === 'changed') {
              if (shouldRetryCheckpointWithBackup(checkpointCandidate, sourceVerdict.status)) {
                throw new Error(sourceVerdict.message)
              }
              checkpointArtifactCacheRef.current = {
                learningPointValue: null,
                projectValue: null,
                exportValue: null,
                verifyValue: null,
              }
              checkpointEvidenceCacheRef.current = {
                sourceKey: workflowSourceEvidenceKey(sourceRefs),
                apkgKey: '',
              }
              setRequest(checkpoint.request)
              setLearningPointResult(null)
              learningPointResultRef.current = null
              lastLearningPointResultRef.current = null
              setProject(null)
              lastExportFullRef.current = null
              setLastExport(null)
              setAnkiVerifyResult(null)
              setSelectedLearningPointIds(new Set())
              setGenerationQueueSelectedIds(null)
              setRecoveredWorkflowTask(null)
              setRecoveredGenerationIds([])
              setProductStep('source')
              setActiveWorkspaceStage('source')
              setStatus(
                [
                  sourceVerdict.message + ' 已保留设置，但学习点、卡片、APKG 和核验结果已安全失效。',
                  taskEvidenceWarning,
                ]
                  .filter(Boolean)
                  .join(' '),
              )
              if (!taskEvidenceRetryScheduled) retryAttempt = 0
              setCheckpointReady(true)
              return
            }

            const [restoredLearningPoints, restoredProject, rawRestoredExport, rawRestoredVerification] =
              await Promise.all([
                readOptionalArtifact<LearningPointExtractionResult>(checkpoint.learningPointResultRef),
                readOptionalArtifact<Project>(checkpoint.projectRef),
                readOptionalArtifact<ExportResult>(checkpoint.exportResultRef),
                readOptionalArtifact<AnkiVerifyResult>(checkpoint.ankiVerificationRef),
              ])
            if (cancelled) return

            let restoredExport = rawRestoredExport
            let restoredVerification = rawRestoredVerification
            let restoredApkgEvidence: WorkflowFileEvidence | undefined
            let recoveryNotice = checkpointCandidate === 'backup' ? '主检查点无法安全恢复，已改用备份检查点。' : ''
            if (restoredExport) {
              const apkgVerdict = await validateWorkflowApkgEvidence(checkpoint, restoredExport, restoredVerification)
              if (cancelled) return
              if (apkgVerdict.status === 'unavailable') {
                scheduleEvidenceRetry(apkgVerdict.message)
                return
              } else if (apkgVerdict.status === 'changed') {
                if (shouldRetryCheckpointWithBackup(checkpointCandidate, apkgVerdict.status)) {
                  throw new Error(apkgVerdict.message)
                }
                restoredExport = null
                restoredVerification = null
                recoveryNotice = apkgVerdict.message + ' 已保留卡片草稿，可直接重新导出，无需重新调用模型或 TTS。'
              } else {
                restoredApkgEvidence = apkgVerdict.evidence
                if (!apkgVerdict.verificationValid) {
                  restoredVerification = null
                  recoveryNotice = 'Anki 核验记录与当前 APKG 不一致，已保留 APKG 并等待重新核验。'
                }
              }
            } else {
              restoredVerification = null
            }

            const restoredArtifactStage = selectArtifactStage({
              sourceReady: isSourceInputReady(checkpoint.request),
              learningPointCount: restoredLearningPoints?.learning_points.length ?? 0,
              draftCardCount: getQualityCounts(restoredProject).total,
              apkgReady: Boolean(restoredExport?.apkg_path),
              ankiVerified: ankiVerificationPassed(restoredVerification),
            })
            const restoredProductStep = selectProductStepForArtifact(restoredArtifactStage)
            const restoredOutputDirectory = await reusableOutputDirectory(checkpoint.outputDirectory)
            if (cancelled) return
            if (checkpoint.outputDirectory && !restoredOutputDirectory) {
              recoveryNotice = [recoveryNotice, '上次保存目录已不存在或不可写，导出时会请你重新选择。']
                .filter(Boolean)
                .join(' ')
            }

            checkpointArtifactCacheRef.current = {
              learningPointValue: restoredLearningPoints,
              learningPointRef: restoredLearningPoints ? checkpoint.learningPointResultRef : undefined,
              projectValue: restoredProject,
              projectRef: restoredProject ? checkpoint.projectRef : undefined,
              exportValue: restoredExport,
              exportRef: restoredExport ? checkpoint.exportResultRef : undefined,
              verifyValue: restoredVerification,
              verifyRef: restoredVerification ? checkpoint.ankiVerificationRef : undefined,
            }
            checkpointEvidenceCacheRef.current = {
              sourceKey: workflowSourceEvidenceKey(sourceRefs),
              sourceEvidence: sourceRefs.length > 0 ? checkpoint.sourceEvidence : undefined,
              apkgKey: restoredExport ? workflowApkgEvidenceKey(restoredExport) : '',
              apkgEvidence: restoredApkgEvidence,
            }
            setRequest(checkpoint.request)
            setLearningPointResult(restoredLearningPoints)
            learningPointResultRef.current = restoredLearningPoints
            lastLearningPointResultRef.current = restoredLearningPoints
            setProject(restoredProject)
            lastExportFullRef.current = restoredExport
            setLastExport(restoredExport ? compactExportResultForUi(restoredExport) : null)
            setAnkiVerifyResult(restoredVerification)
            setProductStep(restoredProductStep)
            if (restoredOutputDirectory) {
              saveOutputDirectoryPreference(restoredOutputDirectory)
              setOutputDirectory(restoredOutputDirectory)
            }
            setActiveWorkspaceStage(restoredProductStep === 'source' ? 'source' : 'review')
            if (restoredLearningPoints) {
              const restoredSelection = checkpoint.generationQueue?.selectedIds
              setSelectedLearningPointIds(
                restoredSelection?.length
                  ? new Set(restoredSelection)
                  : defaultSelectedLearningPointIds(restoredLearningPoints.learning_points ?? [], {
                      reviewDensity: checkpoint.request.review_density,
                      maxSelected: null,
                    }),
              )
            } else {
              setSelectedLearningPointIds(new Set())
            }

            let completedPendingHandled = false
            const completedPendingTask =
              boundTaskSelection?.kind === 'completedPendingConsumption' ? boundTaskSelection.task : null
            if (completedPendingTask) {
              completedPendingHandled = true
              setRecoveredWorkflowTask(null)
              setRecoveredGenerationIds([])
              if (!isWorkflowResultCommand(completedPendingTask.command)) {
                setStatus('上次辅助任务已经完成，但它不属于可恢复的制卡产物；为避免误操作，应用没有自动重跑。')
              } else {
                try {
                  const completedResult = await readWorkerJobResult<unknown>(completedPendingTask.id)
                  if (cancelled) return
                  if (
                    completedWorkerResultKind(completedPendingTask.command, completedResult) === 'ankiMediaPreparation'
                  ) {
                    setStatus('Anki 媒体预置已完成；APKG 已保留。为避免重复导入，请点击“导入 Anki 并核验”继续。')
                  } else {
                    let remainingAfterCompletedBatch: string[] = []
                    let completedBatchMergedProject: Project | null = null
                    if (completedPendingTask.command === 'generate_cards_from_learning_points') {
                      const queue = checkpoint.generationQueue
                      const activeBatchIds = [...new Set(queue?.activeBatchIds.filter(Boolean) ?? [])]
                      if (!restoredLearningPoints || !queue || activeBatchIds.length === 0) {
                        throw new Error('完成的分批任务缺少可验证的活动批次，已停止自动合并。')
                      }
                      const knownLearningPointIds = new Set(
                        (restoredLearningPoints.learning_points ?? []).map((point) => point.id),
                      )
                      if (
                        activeBatchIds.some((id) => !queue.selectedIds.includes(id) || !knownLearningPointIds.has(id))
                      ) {
                        throw new Error('完成批次与恢复的学习点清单不一致，已停止自动合并。')
                      }
                      if (
                        !completedResult ||
                        typeof completedResult !== 'object' ||
                        !Array.isArray((completedResult as Project).segments)
                      ) {
                        throw new Error('完成批次的持久结果不是有效卡片项目，已停止自动合并。')
                      }
                      const baseGeneratedIds = [
                        ...new Set([
                          ...queue.completedIds,
                          ...(restoredProject ? generatedLearningPointIdsFromProject(restoredProject) : []),
                        ]),
                      ]
                      const recoveryBatchRuntime: GenerationBatchRuntime = {
                        active: true,
                        queueIds: activeBatchIds,
                        activeBatchIds,
                        batchSize: activeBatchIds.length,
                        totalBatches: 1,
                        completedBatches: 0,
                        completedCount: 0,
                        generatedCount: 0,
                        missingCount: 0,
                        exportableCount: 0,
                        nextIndex: activeBatchIds.length,
                        projectId:
                          restoredProject?.id ||
                          String((completedResult as Project).id || '') ||
                          `recovered_${completedPendingTask.id}`,
                        baseGeneratedLearningPointIds: baseGeneratedIds,
                        mergedProject: restoredProject,
                        request: checkpoint.request,
                        apiConfig: checkpoint.request.api_config,
                      }
                      const completedRuntime = {
                        ...recoveryBatchRuntime,
                        completedBatches: 1,
                        completedCount: activeBatchIds.length,
                      }
                      completedBatchMergedProject = mergeGeneratedBatchProject(
                        restoredProject,
                        completedResult as Project,
                        completedRuntime,
                      )
                      remainingAfterCompletedBatch = remainingGenerationQueueIdsAfterSuccessfulActiveBatch(queue)
                      setGenerationBatchRuntime(recoveryBatchRuntime)
                    }
                    if (completedPendingTask.command === 'verify_anki_import') {
                      activeAnkiVerifyApkgPathRef.current = restoredExport?.apkg_path ?? checkpoint.apkgPath ?? null
                    }
                    const finished: WorkerFinishedEvent = {
                      job_id: completedPendingTask.id,
                      command: completedPendingTask.command,
                      ok: true,
                      result: completedResult,
                      result_ref: completedPendingTask.resultRef,
                      finished_at_ms: completedPendingTask.updatedAt,
                    }
                    const recoveredOperation = fallbackWorkerOperationFromFinish(finished)
                    workerOperationRef.current = recoveredOperation
                    setWorkerOperation(recoveredOperation)
                    await handleWorkerFinishedRef.current(finished)
                    if (cancelled) return
                    if (
                      completedPendingTask.command === 'generate_cards_from_learning_points' &&
                      remainingAfterCompletedBatch.length > 0
                    ) {
                      generationRetryBaseProjectRef.current = completedBatchMergedProject
                      const remainingSet = new Set(remainingAfterCompletedBatch)
                      setRecoveredGenerationIds(remainingAfterCompletedBatch)
                      setSelectedLearningPointIds(remainingSet)
                      setGenerationQueueSelectedIds(remainingSet)
                      setRecoveredWorkflowTask({
                        schemaVersion: 1,
                        id: completedPendingTask.id,
                        action: 'generate_cards',
                        state: 'interrupted',
                        startedAt: completedPendingTask.startedAt,
                        updatedAt: completedPendingTask.updatedAt,
                        cancellable: true,
                        phaseLabel: '等待继续生成',
                        message: `已接收完成批次，剩余 ${remainingAfterCompletedBatch.length} 张。`,
                        overallPercent: completedPendingTask.progress.overallPercent,
                        remainingItems: remainingAfterCompletedBatch.length,
                      })
                      setStatus(
                        `已安全接收上次完成的批次；还剩 ${remainingAfterCompletedBatch.length} 张。点击继续时不会重复调用已完成批次。`,
                      )
                    }
                  }
                } catch (error) {
                  setGenerationBatchRuntime(null)
                  setStatus(
                    '上次任务已经完成，但持久结果无法安全读取或验证：' +
                      redactSensitiveText(error) +
                      ' 应用没有自动重跑，以免重复生成或重复导入。',
                  )
                }
              }
            }

            const checkpointTaskId = checkpoint.task?.id
            const checkpointTaskObserved = Boolean(
              checkpointTaskId && recoverableTasks.some((task) => task.id === checkpointTaskId),
            )
            const recoveryTask = completedPendingHandled
              ? undefined
              : boundTaskSelection?.kind === 'recoverableInterrupted'
                ? boundTaskSelection.task
                : !checkpointTaskObserved
                  ? checkpoint.task
                  : undefined
            if (
              recoveryTask &&
              (recoveryTask.state === 'queued' ||
                recoveryTask.state === 'running' ||
                recoveryTask.state === 'cancelling' ||
                recoveryTask.state === 'interrupted')
            ) {
              const remainingIds = remainingGenerationQueueIds(checkpoint.generationQueue)
              const remainingItems = remainingIds.length
              if (recoveryTask.command === 'generate_cards_from_learning_points') {
                generationRetryBaseProjectRef.current = restoredProject
                setRecoveredGenerationIds(remainingIds)
                setSelectedLearningPointIds(new Set(remainingIds))
                setGenerationQueueSelectedIds(new Set(remainingIds))
              }
              setRecoveredWorkflowTask({
                schemaVersion: 1,
                id: recoveryTask.id,
                action: workflowActionFromWorkerCommand(recoveryTask.command),
                state: 'interrupted',
                startedAt: recoveryTask.startedAt,
                updatedAt: recoveryTask.updatedAt,
                cancellable: true,
                phaseLabel: recoveryTask.progress.phaseLabel,
                message: recoveryTask.progress.message,
                overallPercent: recoveryTask.progress.overallPercent,
                remainingItems: remainingItems || undefined,
              })
              setStatus(
                remainingItems > 0
                  ? '上次任务意外中断，已保留安全结果；剩余 ' + String(remainingItems) + ' 张。'
                  : '上次任务意外中断，已保留最后的安全结果。',
              )
            } else if (completedPendingHandled) {
              // The durable result handler already published the precise state. Do not
              // replace it with the older artifact summary from the checkpoint.
            } else if (recoveryNotice) {
              setStatus(recoveryNotice)
            } else if (ankiVerificationPassed(restoredVerification)) {
              setStatus('已恢复上次经过 Anki 核验的结果。')
            } else if (restoredExport) {
              setStatus('已恢复上次生成的 APKG，尚未完成 Anki 核验。')
            } else if (restoredProject) {
              setStatus('已恢复上次生成的卡片草稿。')
            } else if (restoredLearningPoints) {
              setStatus('已恢复上次分析出的学习点。')
            }
            if (taskEvidenceWarning) {
              setStatus((current) => [current, taskEvidenceWarning].filter(Boolean).join(' '))
            }
            if (!taskEvidenceRetryScheduled) retryAttempt = 0
            setCheckpointReady(true)
            return
          } catch (candidateError) {
            if (checkpointCandidate === 'primary') {
              primaryRecoveryFailure = candidateError
              const backupCheckpoint = await loadWorkflowCheckpointCandidate('backup')
              if (cancelled) return
              if (backupCheckpoint) {
                checkpoint = backupCheckpoint
                checkpointCandidate = 'backup'
                continue
              }
            }
            if (checkpointCandidate === 'backup' && primaryRecoveryFailure) {
              throw new Error(
                '主检查点无法验证：' +
                  redactSensitiveText(primaryRecoveryFailure) +
                  '；备份检查点也无法验证：' +
                  redactSensitiveText(candidateError),
                { cause: candidateError },
              )
            }
            throw candidateError
          }
        }
      } catch (error) {
        if (!cancelled) {
          setStatus(['无法恢复上次任务：' + redactSensitiveText(error), taskEvidenceWarning].filter(Boolean).join(' '))
          setCheckpointReady(true)
        }
      } finally {
        restoreInFlight = false
      }
    }
    void restoreCheckpoint()
    return () => {
      cancelled = true
      if (retryTimer !== null) window.clearTimeout(retryTimer)
    }
  }, [])
  const persistWorkflowCheckpoint = useCallback(async () => {
    if (!checkpointReady || checkpointPersistenceSuspendedRef.current || !isTauriRuntime()) return
    const cache = checkpointArtifactCacheRef.current
    if (cache.learningPointValue !== learningPointResult) {
      cache.learningPointRef = learningPointResult
        ? ((await writeWorkflowArtifact('learning-points', learningPointResult)) ?? undefined)
        : undefined
      cache.learningPointValue = learningPointResult
    }
    const checkpointProject = project ?? generationBatchRef.current?.mergedProject ?? null
    if (cache.projectValue !== checkpointProject) {
      cache.projectRef = checkpointProject
        ? ((await writeWorkflowArtifact('project', checkpointProject)) ?? undefined)
        : undefined
      cache.projectValue = checkpointProject
    }
    const fullExport = lastExportFullRef.current ?? lastExport
    if (cache.exportValue !== fullExport) {
      cache.exportRef = fullExport
        ? ((await writeWorkflowArtifact('export-result', fullExport)) ?? undefined)
        : undefined
      cache.exportValue = fullExport
    }
    if (cache.verifyValue !== ankiVerifyResult) {
      cache.verifyRef = ankiVerifyResult
        ? ((await writeWorkflowArtifact('anki-verification', ankiVerifyResult)) ?? undefined)
        : undefined
      cache.verifyValue = ankiVerifyResult
    }

    const evidenceCache = checkpointEvidenceCacheRef.current
    const sourceRefs = sourceReady ? collectWorkflowSourceFileRefs(request) : []
    const sourceKey = workflowSourceEvidenceKey(sourceRefs)
    if (evidenceCache.sourceKey !== sourceKey) {
      const sourceEvidence = sourceRefs.length > 0 ? await inspectWorkflowSourceEvidence(sourceRefs) : undefined
      evidenceCache.sourceKey = sourceKey
      evidenceCache.sourceEvidence = sourceEvidence
    }

    const apkgKey = fullExport ? workflowApkgEvidenceKey(fullExport) : ''
    if (evidenceCache.apkgKey !== apkgKey) {
      evidenceCache.apkgEvidence = fullExport ? await inspectWorkflowApkgEvidence(fullExport) : undefined
      evidenceCache.apkgKey = apkgKey
    }

    const requestFingerprint = fingerprintWorkflowRequest(request)
    const activeOperation = workerOperationRef.current
    const activeProgress = workerProgressRef.current
    const operationIsActive =
      (activeOperation.status === 'running' || activeOperation.status === 'cancelling') &&
      !abandonedRecoveryTaskIdsRef.current.has(activeOperation.jobId ?? '')
    const runningTask =
      operationIsActive && activeOperation.command
        ? {
            schemaVersion: 1 as const,
            id: activeOperation.jobId ?? activeOperation.command,
            command: activeOperation.command,
            state: activeOperation.status === 'cancelling' ? ('cancelling' as const) : ('running' as const),
            startedAt: Date.now() - Math.max(0, activeProgress?.elapsed_ms ?? 0),
            updatedAt: Date.now(),
            progress: {
              phase: activeProgress?.stage ?? 'starting',
              phaseLabel: activeProgress?.stage_label ?? activeProgress?.stage ?? '正在准备',
              phasePercent: Number.isFinite(activeProgress?.percent) ? (activeProgress?.percent ?? 0) : null,
              overallPercent: Number.isFinite(activeProgress?.percent)
                ? Math.max(0, Math.min(99, activeProgress?.percent ?? 0))
                : null,
              completedItems: generationBatchProgress?.completedCount,
              totalItems: generationBatchProgress?.queueIds.length,
              completedBatches: generationBatchProgress?.completedBatches,
              totalBatches: generationBatchProgress?.totalBatches,
              message: activeProgress?.message ?? '任务正在运行。',
              lastProgressAt: activeProgress?.last_progress_at_ms ?? Date.now(),
            },
            cancellable: true,
            inputFingerprint: requestFingerprint,
          }
        : undefined

    const selectedIds = [...selectedLearningPointIds]
    const completedIds = generationBatchProgress
      ? generationBatchProgress.queueIds.slice(0, generationBatchProgress.completedCount)
      : []
    await saveWorkflowCheckpoint(
      normalizeWorkflowCheckpoint({
        request,
        sourceFingerprint: sourceReady ? fingerprintWorkflowSource(request) : undefined,
        sourceEvidence: evidenceCache.sourceEvidence,
        productStep,
        artifactStage: workflowArtifactStage,
        learningPointResultRef: cache.learningPointRef,
        projectRef: cache.projectRef,
        generationQueue:
          selectedIds.length > 0 || generationBatchProgress
            ? {
                selectedIds: generationBatchProgress?.queueIds ?? selectedIds,
                completedIds,
                activeBatchIds: generationBatchProgress?.activeBatchIds ?? [],
              }
            : undefined,
        outputDirectory: outputDirectory || undefined,
        exportResultRef: cache.exportRef,
        apkgPath: fullExport?.apkg_path,
        apkgSha256: fullExport?.apkg_sha256,
        apkgEvidence: evidenceCache.apkgEvidence,
        ankiVerificationRef: cache.verifyRef,
        task: runningTask,
      }),
    )
  }, [
    ankiVerifyResult,
    checkpointReady,
    generationBatchProgress,
    lastExport,
    learningPointResult,
    outputDirectory,
    productStep,
    project,
    request,
    selectedLearningPointIds,
    sourceReady,
    workflowArtifactStage,
  ])

  persistWorkflowCheckpointRef.current = persistWorkflowCheckpoint

  const flushWorkflowCheckpoint = useCallback(() => {
    const write = checkpointWriteChainRef.current
      .catch(() => undefined)
      .then(() => persistWorkflowCheckpointRef.current())
    checkpointWriteChainRef.current = write
    return write
  }, [])

  useEffect(() => {
    if (!checkpointReady || checkpointPersistenceSuspendedRef.current || !isTauriRuntime()) return
    if (pendingWorkerResultAcknowledgementsRef.current.size === 0) return
    let disposed = false

    const scheduleRetry = () => {
      if (disposed || workerResultAckRetryTimerRef.current !== null) return
      const delayMs = recoveryEvidenceRetryDelayMs(workerResultAckRetryAttemptRef.current)
      workerResultAckRetryAttemptRef.current += 1
      workerResultAckRetryTimerRef.current = window.setTimeout(() => {
        workerResultAckRetryTimerRef.current = null
        setWorkerResultAckRevision((revision) => revision + 1)
      }, delayMs)
    }

    void acknowledgeAppliedWorkerResults({
      jobIds: pendingWorkerResultAcknowledgementsRef.current,
      persistCheckpoint: flushWorkflowCheckpoint,
      acknowledge: acknowledgeWorkerTaskResult,
    })
      .then((outcome) => {
        if (disposed) return
        for (const jobId of outcome.consumedIds) {
          pendingWorkerResultAcknowledgementsRef.current.delete(jobId)
        }
        for (const rejected of outcome.rejected) {
          pendingWorkerResultAcknowledgementsRef.current.delete(rejected.jobId)
          void recordRendererError({
            kind: 'worker_result_acknowledgement_rejected',
            job_id: rejected.jobId,
            state: rejected.state,
          }).catch(() => undefined)
        }
        if (outcome.retryIds.length > 0) {
          void recordRendererError({
            kind: 'worker_result_acknowledgement_deferred',
            pending_count: outcome.retryIds.length,
          }).catch(() => undefined)
          scheduleRetry()
        } else {
          workerResultAckRetryAttemptRef.current = 0
        }
      })
      .catch((error) => {
        if (disposed) return
        void recordRendererError({
          kind: 'worker_result_acknowledgement_checkpoint_failed',
          error: redactSensitiveText(error),
        }).catch(() => undefined)
        scheduleRetry()
      })

    return () => {
      disposed = true
      if (workerResultAckRetryTimerRef.current !== null) {
        window.clearTimeout(workerResultAckRetryTimerRef.current)
        workerResultAckRetryTimerRef.current = null
      }
    }
  }, [checkpointReady, flushWorkflowCheckpoint, workerResultAckRevision])

  useEffect(() => {
    if (!checkpointReady || checkpointPersistenceSuspendedRef.current || !isTauriRuntime()) return
    let disposed = false
    const timer = window.setTimeout(() => {
      void flushWorkflowCheckpoint()
        .then(() => {
          if (disposed) return
          checkpointWriteRetryAttemptRef.current = 0
          if (checkpointWriteRetryTimerRef.current !== null) {
            window.clearTimeout(checkpointWriteRetryTimerRef.current)
            checkpointWriteRetryTimerRef.current = null
          }
        })
        .catch((error) => {
          void recordRendererError({
            kind: 'workflow_checkpoint_write_failed',
            error: redactSensitiveText(error),
          }).catch(() => undefined)
          if (disposed) return
          const delayMs = recoveryEvidenceRetryDelayMs(checkpointWriteRetryAttemptRef.current)
          checkpointWriteRetryAttemptRef.current += 1
          if (checkpointWriteRetryTimerRef.current !== null) {
            window.clearTimeout(checkpointWriteRetryTimerRef.current)
          }
          checkpointWriteRetryTimerRef.current = window.setTimeout(() => {
            checkpointWriteRetryTimerRef.current = null
            setCheckpointRetryRevision((revision) => revision + 1)
          }, delayMs)
        })
    }, 400)
    return () => {
      disposed = true
      window.clearTimeout(timer)
      if (checkpointWriteRetryTimerRef.current !== null) {
        window.clearTimeout(checkpointWriteRetryTimerRef.current)
        checkpointWriteRetryTimerRef.current = null
      }
    }
  }, [checkpointReady, checkpointRetryRevision, flushWorkflowCheckpoint, persistWorkflowCheckpoint])
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
      setResponsiveMode(width < 1240 ? 'compact' : width < 1440 ? 'medium' : 'wide')
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

  const previewVideoPath = project?.video_path?.trim() ?? ''

  useEffect(() => {
    let cancelled = false
    setPreviewVideoSrc('')
    setPreviewVideoError('')
    if (!previewVideoPath)
      return () => {
        cancelled = true
      }

    void preparePreviewAssetUrl(previewVideoPath)
      .then((url) => {
        if (!cancelled) setPreviewVideoSrc(url)
      })
      .catch((error: unknown) => {
        if (cancelled) return
        const message = error instanceof Error ? error.message : String(error)
        setPreviewVideoError(`视频预览不可用：${message}`)
        void recordRendererError({
          source: 'preview_asset',
          message,
          video_path: previewVideoPath,
        }).catch(() => undefined)
      })

    return () => {
      cancelled = true
    }
  }, [previewVideoPath])
  useEffect(() => {
    if (!project || projectMatchesRequest(project, request)) return
    lastExportFullRef.current = null
    setProductStep('source')
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
    setProductStep('deliver')
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
    setProductStep('select')
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
    publishWorkerProgress({
      command: 'generate_cards_from_learning_points',
      stage: 'batch_start',
      percent: 1,
      message:
        '正在生成第 ' +
        String(batchNumber) +
        '/' +
        String(nextRuntime.totalBatches) +
        ' 批：' +
        String(batchIds.length) +
        ' 张。',
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
    const job = await startWorkerJob(
      'generate_cards_from_learning_points',
      payload,
      fingerprintWorkflowRequest(nextRuntime.request),
    )
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
    publishWorkerProgress({
      job_id: job.job_id,
      command: 'generate_cards_from_learning_points',
      stage: 'start',
      percent: 1,
      message: '卡片生成任务已在后台运行：第 ' + String(batchNumber) + '/' + String(nextRuntime.totalBatches) + ' 批。',
    })
  }

  function applyExportResult(result: ExportResult, jobId?: string) {
    setProductStep('deliver')
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
    setProductStep('deliver')
    captureReleaseEvidenceRawSnapshot({
      type: 'verify_result',
      result,
      verifiedExportApkgPath: activeAnkiVerifyApkgPathRef.current ?? lastExportFullRef.current?.apkg_path ?? null,
      jobId,
    })
    setAnkiVerifyResult(result)
    setStatus(result.message)
  }

  async function handleWorkerFinished(payloadInput: WorkerFinishedEvent) {
    if (locallyObservedWorkerJobIdsRef.current.has(payloadInput.job_id)) return
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
          replaceWorkerOperation({ status: 'failed', command: payload.command, jobId: payload.job_id })
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
        let cancellationMessage = '任务已取消，可以继续调整后重新运行。'
        if (payload.command === 'generate_cards_from_learning_points' && generationBatchRef.current) {
          const batch = generationBatchRef.current
          const retryIds = retryLearningPointIdsAfterBatchFailure({
            queueIds: batch.queueIds,
            completedCount: batch.completedCount,
            activeBatchIds: batch.activeBatchIds,
          })
          generationRetryBaseProjectRef.current = batch.mergedProject
          if (batch.mergedProject?.segments.length) {
            setProject(batch.mergedProject)
            setActiveSegmentId(batch.mergedProject.segments[0]?.id ?? null)
          }
          setGenerationBatchRuntime({ ...batch, active: false })
          setGenerationQueueSelectedIds(new Set(retryIds))
          setSelectedLearningPointIds(new Set(retryIds))
          setGenerationConfirmOpen(retryIds.length > 0)
          cancellationMessage =
            retryIds.length > 0
              ? `任务已取消；已保留完成的 ${batch.completedCount} 个学习点，剩余 ${retryIds.length} 个可以继续生成。`
              : `任务已取消；已保留完成的 ${batch.completedCount} 个学习点。`
        }
        setWorkerProgress(null)
        replaceWorkerOperation({ status: 'idle', command: payload.command, jobId: payload.job_id })
        setLastWorkerError(null)
        setStatus(cancellationMessage)
        return
      }
      if (workerFinishInvalidatedByEditedRequest(payload, requestEditedDuringRunRef.current)) {
        if (payload.command === 'export') releaseExportTargetsByJobIdRef.current.delete(payload.job_id)
        setWorkerProgress(null)
        replaceWorkerOperation({ status: 'idle', command: payload.command, jobId: payload.job_id })
        setLastWorkerError(null)
        setRequestEditedDuringRun(false)
        setStatus('旧任务已完成，但输入指纹已经变化；旧结果已隔离，当前工作区和已有产物保持不变。')
        return
      }
      if (!payload.ok) {
        if (payload.command === 'export') releaseExportTargetsByJobIdRef.current.delete(payload.job_id)
        let generationFailureRecoveryHint = ''
        if (payload.command === 'generate_cards_from_learning_points' && generationBatchRef.current?.active) {
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
        replaceWorkerOperation({ status: 'failed', command: payload.command, jobId: payload.job_id })
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
        replaceWorkerOperation({ status: 'failed', command: payload.command, jobId: payload.job_id })
        setLastWorkerError(failedPayload)
        setStatus(failedPayload.error || '后台任务没有返回结果。')
        return
      }
      if (payload.command !== 'generate_cards_from_learning_points') {
        publishWorkerProgress(
          {
            job_id: payload.job_id,
            command: payload.command,
            stage: 'done',
            percent: 100,
            message: '任务完成。',
          },
          'succeeded',
        )
      }
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
            publishWorkerProgress({
              job_id: payload.job_id,
              command: payload.command,
              stage: 'batch_complete',
              percent: 0,
              message:
                '已完成第 ' +
                String(nextBatch.completedBatches) +
                '/' +
                String(nextBatch.totalBatches) +
                ' 批，正在准备下一批。',
            })
            setBusy(true)
            replaceWorkerOperation({ status: 'running', command: 'generate_cards_from_learning_points' })
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
              replaceWorkerOperation({
                status: 'failed',
                command: 'generate_cards_from_learning_points',
                jobId: payload.job_id,
              })
              setLastWorkerError(failedPayload)
              setStatus(failedPayload.error || '下一批生成任务启动失败。')
            }
            queueWorkerResultAcknowledgement(payload.job_id)
            return
          }
          publishWorkerProgress(
            {
              job_id: payload.job_id,
              command: payload.command,
              stage: 'done',
              percent: 100,
              message: '全部卡片批次生成完成。',
            },
            'succeeded',
          )
          setGenerationBatchRuntime(null)
          generationRetryBaseProjectRef.current = null
          setGenerationConfirmOpen(false)
          setGenerationQueueSelectedIds(null)
          applyGeneratedProject(mergedProject, requestEditedDuringRunRef.current, payload.job_id)
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
        } else {
          const generatedProject = payload.result as Project
          publishWorkerProgress(
            {
              job_id: payload.job_id,
              command: payload.command,
              stage: 'done',
              percent: 100,
              message: '卡片生成完成。',
            },
            'succeeded',
          )
          generationRetryBaseProjectRef.current = null
          setGenerationConfirmOpen(false)
          setGenerationQueueSelectedIds(null)
          applyGeneratedProject(generatedProject, requestEditedDuringRunRef.current, payload.job_id)
          setActiveWorkspaceStage('review')
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
          replaceWorkerOperation({ status: 'failed', command: 'export', jobId: payload.job_id })
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
      replaceWorkerOperation({ status: 'succeeded', command: payload.command, jobId: payload.job_id })
      setRequestEditedDuringRun(false)
      queueWorkerResultAcknowledgement(payload.job_id)
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
      const normalized = publishWorkerProgress(
        {
          ...event.payload,
          last_progress_at_ms: event.payload.last_progress_at_ms ?? Date.now(),
        },
        'running',
      )
      setStatus(normalized.message)
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
  }, [publishWorkerProgress])

  useEffect(() => {
    if (!isTauriRuntime()) return
    const resolvePollingJobId = () => {
      const active = workerOperationRef.current
      if ((active.status === 'running' || active.status === 'cancelling') && active.jobId) return active.jobId
      if ((workerOperation.status === 'running' || workerOperation.status === 'cancelling') && workerOperation.jobId) {
        return workerOperation.jobId
      }
      if (busy && workerProgressRef.current?.job_id) return workerProgressRef.current.job_id
      return null
    }
    const initialJobId = resolvePollingJobId()
    if (!initialJobId) return
    let cancelled = false
    let pollFailureCount = 0
    let pollFailureReported = false
    const pollWorkerTask = async () => {
      const jobId = resolvePollingJobId()
      if (!jobId || handledWorkerFinishIdsRef.current.has(jobId)) return
      try {
        const task = await getWorkerTask(jobId)
        pollFailureCount = 0
        if (cancelled) return

        if (task && (task.state === 'running' || task.state === 'cancelling')) {
          const operation: WorkerOperation = {
            status: task.state,
            command: task.command,
            jobId: task.id,
          }
          workerOperationRef.current = operation
          setWorkerOperation(operation)
          const progress: WorkerProgress = {
            job_id: task.id,
            command: task.command,
            stage: task.progress.phase,
            stage_label: task.progress.phaseLabel,
            percent:
              task.command === 'generate_cards_from_learning_points'
                ? (task.progress.phasePercent ?? task.progress.overallPercent ?? 0)
                : (task.progress.overallPercent ?? task.progress.phasePercent ?? 0),
            message: task.progress.message,
            completed_batches: task.progress.completedBatches,
            total_batches: task.progress.totalBatches,
            elapsed_ms: Math.max(0, Date.now() - task.startedAt),
            last_progress_at_ms: task.progress.lastProgressAt,
          }
          publishWorkerProgress(progress, task.state)
          const activity = getTaskActivityStatus(task)
          setStatus(activity.message ?? task.progress.message)
          return
        }

        if (task && ['succeeded', 'failed', 'cancelled', 'interrupted'].includes(task.state)) {
          let finished = await getWorkerJobStatus(jobId)
          if (!finished) {
            if (task.state === 'succeeded') {
              const result = await readWorkerJobResult<unknown>(jobId)
              finished = {
                job_id: task.id,
                command: task.command,
                ok: true,
                result,
                result_ref: task.resultRef,
                finished_at_ms: task.updatedAt,
              }
            } else {
              finished = {
                job_id: task.id,
                command: task.command,
                ok: false,
                error: task.error?.message ?? (task.state === 'cancelled' ? '任务已取消。' : '后台任务意外中断。'),
                error_code:
                  task.error?.code ?? (task.state === 'cancelled' ? 'WORKER_CANCELLED' : 'UNKNOWN_WORKER_ERROR'),
                retryable: task.error?.retryable ?? task.state !== 'cancelled',
                cancelled: task.state === 'cancelled',
                finished_at_ms: task.updatedAt,
              }
            }
          }
          if (!workerOperationRef.current.jobId && finished.job_id === jobId) {
            workerOperationRef.current = fallbackWorkerOperationFromFinish(finished)
          }
          void handleWorkerFinishedRef.current(finished)
          return
        }

        const legacyFinished = await getWorkerJobStatus(jobId)
        if (legacyFinished?.job_id) {
          if (!workerOperationRef.current.jobId && legacyFinished.job_id === jobId) {
            workerOperationRef.current = fallbackWorkerOperationFromFinish(legacyFinished)
          }
          void handleWorkerFinishedRef.current(legacyFinished)
        }
      } catch (error) {
        pollFailureCount += 1
        if (!cancelled && pollFailureCount >= 3 && !pollFailureReported) {
          pollFailureReported = true
          const message = `后台任务状态轮询失败：${redactSensitiveText(error)}`
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
    void pollWorkerTask()
    const intervalId = window.setInterval(pollWorkerTask, 2000)
    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [
    busy,
    publishWorkerProgress,
    workerOperation.command,
    workerOperation.jobId,
    workerOperation.status,
    workerProgress?.job_id,
  ])

  const performSafeWindowClose = useCallback(async () => {
    if (closeInFlightRef.current) return
    const active = workerOperationRef.current
    const operationActive = active.status === 'running' || active.status === 'cancelling'
    if (operationActive && !active.jobId) {
      setStatus('后台任务仍在启动，暂时无法确认安全停止；请稍后再关闭。')
      return
    }
    if (active.jobId && operationActive) {
      const shouldStopAndClose = window.confirm(
        '当前任务仍在运行。选择“确定”会安全停止任务、保存恢复点后关闭；选择“取消”会继续等待。',
      )
      if (!shouldStopAndClose) return
    }

    closeInFlightRef.current = true
    const jobId = operationActive ? active.jobId : null
    if (jobId) {
      const cancellingOperation: WorkerOperation = { ...active, status: 'cancelling', jobId }
      workerOperationRef.current = cancellingOperation
      setWorkerOperation(cancellingOperation)
      setBusy(true)
      setStatus('正在安全停止任务并保存恢复点…')
    } else {
      setStatus('正在保存最新恢复点…')
    }

    let closeSucceeded = false
    try {
      const result = await safelyCloseWindow({
        jobId,
        requestCancel: async (id) => {
          await cancelWorkerJob(id)
        },
        waitForTerminal: async (id) => {
          const terminal = await waitForWorkerTerminal(id, { readTask: getWorkerTask })
          if (terminal.kind === 'terminal') {
            const finished = await getWorkerJobStatus(id).catch(() => null)
            if (finished && !locallyObservedWorkerJobIdsRef.current.has(id)) {
              await handleWorkerFinishedRef.current(finished)
              await new Promise<void>((resolve) => globalThis.setTimeout(resolve, 0))
            }
            const terminalOperation: WorkerOperation = {
              status:
                terminal.task.state === 'succeeded'
                  ? 'succeeded'
                  : terminal.task.state === 'cancelled'
                    ? 'idle'
                    : 'failed',
              command: terminal.task.command,
              jobId: id,
            }
            workerOperationRef.current = terminalOperation
            setWorkerOperation(terminalOperation)
            setBusy(false)
          }
          return terminal
        },
        flushCheckpoint: flushWorkflowCheckpoint,
        closeWindow: async () => {
          await allowNextNativeWindowClose()
          try {
            await runNativeWindowAction('close')
          } catch (error) {
            await revokeNativeWindowClosePermission().catch(() => undefined)
            throw error
          }
        },
      })
      closeSucceeded = result.closed
      if (!result.closed) {
        setStatus(safeCloseFailureMessage(result.reason, result.error))
      }
    } finally {
      if (!closeSucceeded) closeInFlightRef.current = false
    }
  }, [flushWorkflowCheckpoint])

  const runWindowAction = async (action: 'minimize' | 'toggleMaximize' | 'close') => {
    if (action === 'close') {
      await performSafeWindowClose()
      return
    }
    await runNativeWindowAction(action)
  }

  useEffect(() => {
    if (!isTauriRuntime()) return
    let stopListening: (() => void) | undefined
    let disposed = false
    void listenForNativeCloseRequest(performSafeWindowClose)
      .then((unlisten) => {
        if (disposed) unlisten()
        else stopListening = unlisten
      })
      .catch((error) => {
        setStatus('系统关闭事件监听失败：' + redactSensitiveText(error))
      })
    return () => {
      disposed = true
      stopListening?.()
    }
  }, [performSafeWindowClose])
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

  const blockRequestMutationWhileWorkerActive = (): boolean => {
    const active = workerOperationRef.current
    if (active.status !== 'running' && active.status !== 'cancelling') return false
    setStatus('当前任务仍在运行或取消中。请先取消并等待任务到达终态，再修改素材或生成设置。')
    return true
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
    if (blockRequestMutationWhileWorkerActive()) return
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
    const modelConnectionChanged = Boolean(
      safePatch.api_config &&
      modelApiConfigChangeInvalidatesLearningArtifacts(request.api_config, safePatch.api_config),
    )
    if (modelConnectionChanged || requestPatchInvalidatesLearningArtifacts(safePatch)) {
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
    if (blockRequestMutationWhileWorkerActive()) return
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
    if (blockRequestMutationWhileWorkerActive()) return
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
    if (blockRequestMutationWhileWorkerActive()) return
    const publicMode: SourceMode = mode === 'document' ? 'local' : mode
    const nextCardTypes: CardKind[] = request.card_types.includes('knowledge') ? ['phrase'] : request.card_types

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
    const draft = settingsDraftStateRef.current
    if (draft) {
      updateSettingsDraftState((current) => patchApiSettingsDraft(current, patch))
      apiTestBindingRef.current = null
      setApiTestResult(null)
      return
    }
    if (blockRequestMutationWhileWorkerActive()) return
    apiTestBindingRef.current = null
    const nextApiConfig = { ...request.api_config, ...patch }
    if (modelApiConfigChangeInvalidatesLearningArtifacts(request.api_config, nextApiConfig)) {
      clearLearningArtifactsForRequestChange()
    } else {
      clearStaleReviewResults()
    }
    setRequest((current) => ({
      ...current,
      api_config: { ...current.api_config, ...patch },
    }))
    setApiProfileDirty(true)
    setApiTestResult(null)
  }

  const patchTts = (patch: Partial<TtsConfig>) => {
    const draft = settingsDraftStateRef.current
    if (draft) {
      updateSettingsDraftState((current) => patchTtsSettingsDraft(current, patch))
      ttsTestBindingRef.current = null
      setTtsTestResult(null)
      return
    }
    if (blockRequestMutationWhileWorkerActive()) return
    ttsTestBindingRef.current = null
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
    if (blockRequestMutationWhileWorkerActive()) return
    const existing = savedApiProfiles.find((profile) => profile.id === activeApiProfileId)
    let profile = buildSavedApiProfile(request.api_config, allApiPresets, existing)
    const shouldSaveKey = profile.auth === 'api_key' && Boolean(request.api_config.api_key.trim())
    try {
      if (shouldSaveKey) {
        await saveSecret(profileSecretKey('api', profile.id), request.api_config.api_key.trim())
        profile = {
          ...advanceApiProfileCredentialRevision(profile),
          has_api_key: true,
        }
      }
      const binding = apiTestBindingRef.current
      if (apiTestResult && binding && (apiProfileDirty || shouldSaveKey)) {
        profile = recordApiProfileVerification(profile, apiTestResult, binding)
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
        profile.auth === 'local_oauth'
          ? '已保存模型方案：' + profile.label + '。它使用 Hermes 本机 OAuth，不保存 xAI Token。'
          : profile.auth === 'gcloud'
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
    if (blockRequestMutationWhileWorkerActive()) return
    const existing = savedTtsProfiles.find((profile) => profile.id === activeTtsProfileId)
    let profile = buildSavedTtsProfile(tts, allTtsPresets, existing)
    const shouldSaveKey = profile.auth === 'api_key' && Boolean(tts.api_key.trim())
    try {
      if (shouldSaveKey) {
        await saveSecret(profileSecretKey('tts', profile.id), tts.api_key.trim())
        profile = {
          ...advanceTtsProfileCredentialRevision(profile),
          has_api_key: true,
        }
      }
      const binding = ttsTestBindingRef.current
      if (ttsTestResult && binding && (ttsProfileDirty || shouldSaveKey)) {
        profile = recordTtsProfileVerification(profile, ttsTestResult, binding)
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
  const syncDeletedCredentialToSettingsDraft = (kind: 'api' | 'tts', profile: SavedApiProfile | SavedTtsProfile) => {
    updateSettingsDraftState((current) => {
      const revision = savedProfileCredentialRevision(profile)
      const syncValues = (values: SettingsDraftValues): SettingsDraftValues => {
        if (kind === 'api') {
          if (values.activeApiProfile?.id !== profile.id) return values
          return {
            ...values,
            apiConfig: { ...values.apiConfig, api_key: '' },
            activeApiProfile: profile as SavedApiProfile,
            credentialRevisions: { ...values.credentialRevisions, model: revision },
          }
        }
        if (values.activeTtsProfile?.id !== profile.id) return values
        return {
          ...values,
          apiConfig: {
            ...values.apiConfig,
            tts_config: { ...values.apiConfig.tts_config, api_key: '' },
          },
          activeTtsProfile: profile as SavedTtsProfile,
          credentialRevisions: { ...values.credentialRevisions, tts: revision },
        }
      }
      const committed = syncValues(current.committed)
      const draft = syncValues(current.draft)
      const stale = applySettingsWithoutVerification({ ...current, committed, draft, pendingSave: null })
      const target = kind === 'api' ? 'model' : 'tts'
      return {
        ...current,
        committed,
        draft,
        verification: { ...current.verification, [target]: stale.verification[target] },
        pendingSave: null,
      }
    })
  }

  const deleteSavedApiCredential = async () => {
    if (blockRequestMutationWhileWorkerActive()) return false
    const profile = settingsActiveApiProfile
    if (!profile || !settingsActiveApiKeySaved) return false
    if (!window.confirm(`删除“${profile.label}”保存在本机系统凭据中的 API Key？模型方案会继续保留。`)) {
      return false
    }
    const key = profileSecretKey('api', profile.id)
    const cleared = removeSavedApiProfileCredential(profile)
    const next = upsertSavedApiProfile(savedApiProfiles, cleared)
    try {
      await persistSettingsTransaction(
        {
          apiSecret: { key, delete: true },
          apiProfiles: { previous: savedApiProfiles, next },
          ttsProfiles: { previous: savedTtsProfiles, next: savedTtsProfiles },
        },
        {
          snapshotSecret: async (secretKey) => {
            if (!(await secretExists(secretKey))) return { exists: false }
            return { exists: true, value: await loadSecret(secretKey) }
          },
          writeSecret: saveSecret,
          deleteSecret,
          writeApiProfiles: saveSavedApiProfiles,
          writeTtsProfiles: saveSavedTtsProfiles,
        },
      )
      setSavedApiProfiles(next)
      setSecretAvailability((current) => ({ ...current, [key]: false }))
      setRequest((current) =>
        apiProfileIdFromConfig(current.api_config) === profile.id
          ? { ...current, api_config: { ...current.api_config, api_key: '' } }
          : current,
      )
      apiTestBindingRef.current = null
      setApiTestResult(null)
      setApiProfileDirty(false)
      syncDeletedCredentialToSettingsDraft('api', cleared)
      setStatus('已删除当前模型的系统凭据；模型方案仍保留，需要重新授权并验证。')
      return true
    } catch (error) {
      setStatus('删除模型 API Key 失败：' + redactSensitiveText(error))
      return false
    }
  }

  const deleteSavedTtsCredential = async () => {
    if (blockRequestMutationWhileWorkerActive()) return false
    const profile = settingsActiveTtsProfile
    if (!profile || !settingsActiveTtsKeySaved) return false
    if (!window.confirm(`删除“${profile.label}”保存在本机系统凭据中的 TTS API Key？语音方案会继续保留。`)) {
      return false
    }
    const key = profileSecretKey('tts', profile.id)
    const cleared = removeSavedTtsProfileCredential(profile)
    const next = upsertSavedTtsProfile(savedTtsProfiles, cleared)
    try {
      await persistSettingsTransaction(
        {
          ttsSecret: { key, delete: true },
          apiProfiles: { previous: savedApiProfiles, next: savedApiProfiles },
          ttsProfiles: { previous: savedTtsProfiles, next },
        },
        {
          snapshotSecret: async (secretKey) => {
            if (!(await secretExists(secretKey))) return { exists: false }
            return { exists: true, value: await loadSecret(secretKey) }
          },
          writeSecret: saveSecret,
          deleteSecret,
          writeApiProfiles: saveSavedApiProfiles,
          writeTtsProfiles: saveSavedTtsProfiles,
        },
      )
      setSavedTtsProfiles(next)
      setSecretAvailability((current) => ({ ...current, [key]: false }))
      setRequest((current) =>
        ttsProfileIdFromConfig(current.api_config.tts_config) === profile.id
          ? {
              ...current,
              api_config: {
                ...current.api_config,
                tts_config: { ...current.api_config.tts_config, api_key: '' },
              },
            }
          : current,
      )
      ttsTestBindingRef.current = null
      setTtsTestResult(null)
      setTtsProfileDirty(false)
      syncDeletedCredentialToSettingsDraft('tts', cleared)
      setStatus('已删除当前语音方案的系统凭据；语音方案仍保留，需要重新授权并验证。')
      return true
    } catch (error) {
      setStatus('删除 TTS API Key 失败：' + redactSensitiveText(error))
      return false
    }
  }
  const persistSettingsDraftValues = async (
    values: SettingsDraftValues,
    options: {
      clearVerification: boolean
      apiResult?: ApiTestResult | null
      apiTarget?: ProfileVerificationTarget | null
      ttsResult?: TtsTestResult | null
      ttsTarget?: ProfileVerificationTarget | null
    },
  ) => {
    const apiProfileId = apiProfileIdFromConfig(values.apiConfig)
    const existingApiProfile = savedApiProfiles.find((profile) => profile.id === apiProfileId)
    let apiProfile = buildSavedApiProfile(values.apiConfig, allApiPresets, existingApiProfile)
    const shouldSaveApiKey = apiProfile.auth === 'api_key' && Boolean(values.apiConfig.api_key.trim())
    apiProfile = {
      ...apiProfile,
      verification_schema_version: 1,
      credential_revision: values.credentialRevisions.model,
      has_api_key: shouldSaveApiKey || apiProfile.has_api_key,
    }
    if (options.clearVerification) {
      apiProfile = profileVerificationRecordsCleared(apiProfile, values.credentialRevisions.model)
    } else if (options.apiResult && options.apiTarget) {
      apiProfile = recordApiProfileVerification(apiProfile, options.apiResult, options.apiTarget)
    }

    const ttsConfig = values.apiConfig.tts_config
    const ttsProfileId = ttsProfileIdFromConfig(ttsConfig)
    const existingTtsProfile = savedTtsProfiles.find((profile) => profile.id === ttsProfileId)
    let ttsProfile = buildSavedTtsProfile(ttsConfig, allTtsPresets, existingTtsProfile)
    const shouldSaveTtsKey = ttsProfile.auth === 'api_key' && Boolean(ttsConfig.api_key.trim())
    ttsProfile = {
      ...ttsProfile,
      verification_schema_version: 1,
      credential_revision: values.credentialRevisions.tts,
      has_api_key: shouldSaveTtsKey || ttsProfile.has_api_key,
    }
    if (options.clearVerification) {
      ttsProfile = profileVerificationRecordsCleared(ttsProfile, values.credentialRevisions.tts)
    } else if (options.ttsResult && options.ttsTarget) {
      ttsProfile = recordTtsProfileVerification(ttsProfile, options.ttsResult, options.ttsTarget)
    }

    const nextApiProfiles = upsertSavedApiProfile(savedApiProfiles, apiProfile)
    const nextTtsProfiles = upsertSavedTtsProfile(savedTtsProfiles, ttsProfile)
    await persistSettingsTransaction(
      {
        apiSecret: shouldSaveApiKey
          ? {
              key: profileSecretKey('api', apiProfile.id),
              value: values.apiConfig.api_key.trim(),
            }
          : undefined,
        ttsSecret: shouldSaveTtsKey
          ? {
              key: profileSecretKey('tts', ttsProfile.id),
              value: ttsConfig.api_key.trim(),
            }
          : undefined,
        apiProfiles: { previous: savedApiProfiles, next: nextApiProfiles },
        ttsProfiles: { previous: savedTtsProfiles, next: nextTtsProfiles },
      },
      {
        snapshotSecret: async (key) => {
          if (!(await secretExists(key))) return { exists: false }
          return { exists: true, value: await loadSecret(key) }
        },
        writeSecret: saveSecret,
        deleteSecret,
        writeApiProfiles: saveSavedApiProfiles,
        writeTtsProfiles: saveSavedTtsProfiles,
      },
    )

    const committedApiConfig: ApiConfig = {
      ...values.apiConfig,
      api_key: '',
      capabilities: [...values.apiConfig.capabilities],
      tts_config: { ...values.apiConfig.tts_config, api_key: '' },
    }
    return {
      apiConfig: committedApiConfig,
      apiProfile,
      ttsProfile,
      nextApiProfiles,
      nextTtsProfiles,
    }
  }

  const commitPersistedSettingsDraft = (
    previous: SettingsDraftState,
    persisted: Awaited<ReturnType<typeof persistSettingsDraftValues>>,
    verification: 'verified' | 'stale',
  ) => {
    const committedValues: SettingsDraftValues = {
      apiConfig: persisted.apiConfig,
      activeApiProfile: persisted.apiProfile,
      activeTtsProfile: persisted.ttsProfile,
      credentialRevisions: { ...previous.draft.credentialRevisions },
    }
    if (modelApiConfigChangeInvalidatesLearningArtifacts(request.api_config, persisted.apiConfig)) {
      clearLearningArtifactsForRequestChange()
    } else {
      clearStaleReviewResults()
    }
    setRequest((current) => ({ ...current, api_config: persisted.apiConfig }))
    setSavedApiProfiles(persisted.nextApiProfiles)
    setSavedTtsProfiles(persisted.nextTtsProfiles)
    setApiProfileDirty(false)
    setTtsProfileDirty(false)
    apiTestBindingRef.current = null
    ttsTestBindingRef.current = null
    setApiTestResult(null)
    setTtsTestResult(null)

    const clean = openSettingsDraft({ committed: committedValues, mode: previous.mode })
    if (verification === 'verified') {
      replaceSettingsDraftState(clean)
      return
    }
    const stale = applySettingsWithoutVerification(previous)
    replaceSettingsDraftState({
      ...clean,
      verification: stale.verification,
    })
  }

  const saveSettingsAndVerify = async () => {
    if (blockRequestMutationWhileWorkerActive()) return false
    let original = settingsDraftStateRef.current
    if (!original || settingsSaving) return false
    const normalizedApi = normalizeApiConfigForRequest(original.draft.apiConfig)
    if (
      normalizedApi.provider !== original.draft.apiConfig.provider ||
      normalizedApi.base_url !== original.draft.apiConfig.base_url ||
      normalizedApi.model !== original.draft.apiConfig.model
    ) {
      original =
        updateSettingsDraftState((current) =>
          patchApiSettingsDraft(current, {
            provider: normalizedApi.provider,
            base_url: normalizedApi.base_url,
            model: normalizedApi.model,
            capabilities: normalizedApi.capabilities,
          }),
        ) ?? original
    }
    const targets: SettingsVerificationTarget[] = ['model']
    if (original.draft.apiConfig.tts_config.enabled && original.draft.apiConfig.tts_config.provider !== 'disabled') {
      targets.push('tts')
    }
    const runId = `settings-save-${Date.now()}`
    const started =
      updateSettingsDraftState((current) =>
        beginSettingsVerification(current, {
          targets,
          intent: 'save_and_verify',
          runId,
        }),
      ) ?? original
    const startedFingerprint = settingsDraftFingerprint(started.draft)
    setSettingsSaving(true)
    const cancelUnfinishedSettingsVerification = () => {
      updateSettingsDraftState((current) =>
        targets.reduce((next, target) => cancelSettingsVerification(next, { target, runId }), current),
      )
    }
    try {
      const apiResult = await testApi()
      if (!apiResult) {
        cancelUnfinishedSettingsVerification()
        return false
      }
      const apiTarget = apiTestBindingRef.current
      const ttsResult = targets.includes('tts') ? await testTts() : null
      if (targets.includes('tts') && !ttsResult) {
        cancelUnfinishedSettingsVerification()
        return false
      }
      const ttsTarget = targets.includes('tts') ? ttsTestBindingRef.current : null
      const completed = settingsDraftStateRef.current
      const stillMatches =
        completed && settingsDraftFingerprint(completed.draft) === startedFingerprint && !completed.pendingSave
      const allPassed =
        Boolean(stillMatches) &&
        targets.every((target) => completed?.verification[target].status === 'passed') &&
        Boolean(apiResult?.ok) &&
        (!targets.includes('tts') || Boolean(ttsResult?.ok))
      if (!completed || !allPassed || !apiTarget) {
        setStatus('设置没有应用：请先修复失败项，并重新执行“保存并验证”。')
        return false
      }

      const persisted = await persistSettingsDraftValues(completed.draft, {
        clearVerification: false,
        apiResult,
        apiTarget,
        ttsResult,
        ttsTarget,
      })
      commitPersistedSettingsDraft(completed, persisted, 'verified')
      setStatus('模型与语音设置已验证并应用。')
      return true
    } catch (error) {
      const current = settingsDraftStateRef.current
      if (current) {
        replaceSettingsDraftState({ ...current, committed: original.committed, pendingSave: null })
      }
      setStatus(`设置保存失败：${redactSensitiveText(error)}`)
      return false
    } finally {
      setSettingsSaving(false)
    }
  }

  const applySettingsDraftLater = async () => {
    if (blockRequestMutationWhileWorkerActive()) return false
    const current = settingsDraftStateRef.current
    if (!current || settingsSaving) return false
    setSettingsSaving(true)
    try {
      const persisted = await persistSettingsDraftValues(current.draft, { clearVerification: true })
      commitPersistedSettingsDraft(current, persisted, 'stale')
      setStatus('设置已应用，但模型和 TTS 需要在下次使用前重新验证。')
      return true
    } catch (error) {
      setStatus(`设置应用失败：${redactSensitiveText(error)}`)
      return false
    } finally {
      setSettingsSaving(false)
    }
  }

  const applySavedApiProfile = async (profileId: string) => {
    const profile = savedApiProfiles.find((item) => item.id === profileId)
    if (!profile) return
    if (settingsDraftStateRef.current) {
      updateSettingsDraftState((current) => {
        const selected = patchApiSettingsDraft(selectApiProfileForDraft(current, profile), { api_key: '' })
        return {
          ...selected,
          draft: {
            ...selected.draft,
            credentialRevisions: {
              ...selected.draft.credentialRevisions,
              model: savedProfileCredentialRevision(profile),
            },
          },
        }
      })
      apiTestBindingRef.current = null
      setApiTestResult(null)
      setStatus(`已加载模型方案：${profile.label}。更改尚未应用。`)
      return
    }
    if (blockRequestMutationWhileWorkerActive()) return
    apiTestBindingRef.current = null
    const nextApiConfig = {
      ...request.api_config,
      provider: profile.provider,
      base_url: profile.base_url,
      model: profile.model,
      capabilities: [...profile.capabilities],
    }
    if (modelApiConfigChangeInvalidatesLearningArtifacts(request.api_config, nextApiConfig)) {
      clearLearningArtifactsForRequestChange()
    } else {
      clearStaleReviewResults()
    }
    setRequest((current) => ({
      ...current,
      api_config: {
        ...current.api_config,
        provider: profile.provider,
        base_url: profile.base_url,
        model: profile.model,
        capabilities: [...profile.capabilities],
        api_key: '',
      },
    }))
    setApiProfileDirty(false)
    setApiTestResult(null)
    setStatus(
      profile.auth === 'local_oauth'
        ? '已切换到模型方案：' + profile.label + '。测试或生成时会按需启动 Hermes 本机代理。'
        : profile.auth === 'api_key' && !profile.has_api_key
          ? `已切换到模型方案：${profile.label}。这个方案没有保存 API Key。`
          : profile.auth === 'api_key'
            ? `已切换到模型方案：${profile.label}。Key 已保存，测试或生成前会短时读取。`
            : `已切换到模型方案：${profile.label}。`,
    )
  }

  const applySavedTtsProfile = async (profileId: string) => {
    const profile = savedTtsProfiles.find((item) => item.id === profileId)
    if (!profile) return
    if (settingsDraftStateRef.current) {
      updateSettingsDraftState((current) => {
        const selected = patchTtsSettingsDraft(selectTtsProfileForDraft(current, profile), { api_key: '' })
        return {
          ...selected,
          draft: {
            ...selected.draft,
            credentialRevisions: {
              ...selected.draft.credentialRevisions,
              tts: savedProfileCredentialRevision(profile),
            },
          },
        }
      })
      ttsTestBindingRef.current = null
      setTtsTestResult(null)
      setStatus(`已加载语音方案：${profile.label}。更改尚未应用。`)
      return
    }
    if (blockRequestMutationWhileWorkerActive()) return
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
    setTtsTestResult(null)
    setStatus(
      profile.auth === 'api_key' && !profile.has_api_key
        ? `已切换到语音方案：${profile.label}。这个方案没有保存 TTS API Key。`
        : profile.auth === 'api_key'
          ? `已切换到语音方案：${profile.label}。Key 已保存，测试或导出前会短时读取。`
          : `已切换到语音方案：${profile.label}。`,
    )
  }
  const applyApiPreset = async (preset: ApiPreset) => {
    const nextConfig = {
      provider: preset.provider,
      base_url: preset.base_url,
      model: preset.model,
      capabilities: preset.capabilities,
    }
    const profileId = apiProfileIdFromConfig(nextConfig)
    const savedProfile = savedApiProfiles.find((profile) => profile.id === profileId)
    const draft = settingsDraftStateRef.current
    if (draft) {
      updateSettingsDraftState((current) => {
        if (savedProfile) {
          const selected = patchApiSettingsDraft(selectApiProfileForDraft(current, savedProfile), { api_key: '' })
          return {
            ...selected,
            draft: {
              ...selected.draft,
              credentialRevisions: {
                ...selected.draft.credentialRevisions,
                model: savedProfileCredentialRevision(savedProfile),
              },
            },
          }
        }
        return patchApiSettingsDraft(current, { ...nextConfig, api_key: '' })
      })
      apiTestBindingRef.current = null
      setApiTestResult(null)
      if (isHermesLocalApiConfig({ ...draft.draft.apiConfig, ...nextConfig })) {
        await refreshHermesStatus()
      }
      setStatus(`已加载 ${preset.label} 预设。更改尚未应用。`)
      return
    }

    if (blockRequestMutationWhileWorkerActive()) return
    apiTestBindingRef.current = null
    const nextApiConfig = { ...request.api_config, ...nextConfig }
    if (modelApiConfigChangeInvalidatesLearningArtifacts(request.api_config, nextApiConfig)) {
      clearLearningArtifactsForRequestChange()
    } else {
      clearStaleReviewResults()
    }
    setRequest((current) => ({
      ...current,
      api_config: {
        ...current.api_config,
        ...nextConfig,
        api_key: '',
      },
    }))
    setApiTestResult(null)
    setApiProfileDirty(!savedProfile)
    if (isHermesLocalApiConfig({ ...request.api_config, ...nextConfig })) {
      await refreshHermesStatus()
    }
    setStatus(
      savedProfile
        ? `已套用已保存的 ${preset.label} 方案。`
        : preset.id === 'hermes-grok-45'
          ? '已套用 ' + preset.label + ' 预设；测试连接时会按需启动本机代理。'
          : preset.provider === 'gemini-vertex' || preset.provider === 'local'
            ? `已套用 ${preset.label} 预设，建议保存为我的模型方案。`
            : `已套用 ${preset.label} 预设，请填写 API Key 后保存方案并测试连接。`,
    )
  }

  const rememberSavedApiTestResult = (api: ApiConfig, result: ApiTestResult, target: ProfileVerificationTarget) => {
    const profileId = apiProfileIdFromConfig(api)
    const existing = savedApiProfiles.find((profile) => profile.id === profileId)
    if (!existing || !apiConfigMatchesProfile(api, existing)) return
    const recorded = recordApiProfileVerification(existing, result, target)
    const next = upsertSavedApiProfile(savedApiProfiles, recorded)
    saveSavedApiProfiles(next)
    setSavedApiProfiles(next)
  }

  const rememberSavedTtsTestResult = (
    testedTts: TtsConfig,
    result: TtsTestResult,
    target: ProfileVerificationTarget,
  ) => {
    const profileId = ttsProfileIdFromConfig(testedTts)
    const existing = savedTtsProfiles.find((profile) => profile.id === profileId)
    if (!existing || !ttsConfigMatchesProfile(testedTts, existing)) return
    const recorded = recordTtsProfileVerification(existing, result, target)
    const next = upsertSavedTtsProfile(savedTtsProfiles, recorded)
    saveSavedTtsProfiles(next)
    setSavedTtsProfiles(next)
  }
  const applyTtsPreset = async (preset: TtsPreset) => {
    const draft = settingsDraftStateRef.current
    if (!draft && blockRequestMutationWhileWorkerActive()) return
    const baseApiConfig = draft?.draft.apiConfig ?? request.api_config
    const baseApiProfileId = apiProfileIdFromConfig(baseApiConfig)
    const baseApiProfile = savedApiProfiles.find((profile) => profile.id === baseApiProfileId)
    const shouldReuseMainMimoKey =
      preset.provider === 'mimo' &&
      isMimoApiConfig(baseApiConfig) &&
      Boolean(baseApiConfig.api_key.trim() || baseApiProfile?.has_api_key)
    const shouldReuseMainQwenKey =
      preset.provider === 'qwen' &&
      isQwenApiConfig(baseApiConfig) &&
      Boolean(baseApiConfig.api_key.trim() || baseApiProfile?.has_api_key)
    const usesLocalVertexAuth = preset.provider === 'gemini-vertex'
    const nextConfig = {
      enabled: preset.provider !== 'disabled',
      provider: preset.provider,
      base_url: preset.base_url,
      model: preset.model,
      voice: preset.voice,
      language: baseApiConfig.tts_config.language,
      sample_rate: baseApiConfig.tts_config.sample_rate,
      bit_rate: baseApiConfig.tts_config.bit_rate,
      output_volume: baseApiConfig.tts_config.output_volume,
    }
    const profileId = ttsProfileIdFromConfig(nextConfig)
    const savedProfile = savedTtsProfiles.find((profile) => profile.id === profileId)

    if (draft && savedProfile) {
      updateSettingsDraftState((current) => {
        const selected = patchTtsSettingsDraft(selectTtsProfileForDraft(current, savedProfile), { api_key: '' })
        return {
          ...selected,
          draft: {
            ...selected.draft,
            credentialRevisions: {
              ...selected.draft.credentialRevisions,
              tts: savedProfileCredentialRevision(savedProfile),
            },
          },
        }
      })
      ttsTestBindingRef.current = null
      setTtsTestResult(null)
    } else {
      patchTts({
        ...nextConfig,
        api_key:
          savedProfile?.has_api_key || shouldReuseMainMimoKey || shouldReuseMainQwenKey || usesLocalVertexAuth
            ? ''
            : baseApiConfig.tts_config.api_key,
      })
    }
    if (!draft) setTtsProfileDirty(!savedProfile)
    setStatus(
      draft
        ? `已加载 ${preset.label} 语音预设。更改尚未应用。`
        : savedProfile
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
    if (blockRequestMutationWhileWorkerActive()) return
    clearLearningArtifactsForRequestChange()
    setRequest((current) => ({
      ...current,
      content_toggles: {
        ...current.content_toggles,
        [key]: !current.content_toggles[key],
      },
    }))
  }

  const toggleLanguageFocus = (focus: LanguageFocus) => {
    if (blockRequestMutationWhileWorkerActive()) return
    clearLearningArtifactsForRequestChange()
    setRequest((current) => {
      const exists = current.language_focus.includes(focus)
      const next = exists ? current.language_focus.filter((item) => item !== focus) : [...current.language_focus, focus]
      return { ...current, language_focus: next.length ? next : current.language_focus }
    })
  }

  const toggleDocumentFocus = (focus: DocumentFocus) => {
    if (blockRequestMutationWhileWorkerActive()) return
    clearLearningArtifactsForRequestChange()
    setRequest((current) => {
      const exists = current.document_focus.includes(focus)
      const next = exists ? current.document_focus.filter((item) => item !== focus) : [...current.document_focus, focus]
      return { ...current, document_focus: next.length ? next : current.document_focus }
    })
  }

  const toggleCardType = (type: CardKind) => {
    if (blockRequestMutationWhileWorkerActive()) return
    clearLearningArtifactsForRequestChange()
    setRequest((current) => {
      const exists = current.card_types.includes(type)
      const next = exists ? current.card_types.filter((item) => item !== type) : [...current.card_types, type]
      return { ...current, card_types: next.length ? next : current.card_types }
    })
  }

  const selectPath = async (kind: SourcePathKind) => {
    if (blockRequestMutationWhileWorkerActive()) return
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

  const checkEnv = useCallback(async () => {
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
          const result = await runWorkerJobAndWait<EnvStatus>('check_env', {}, observeWorkerJob)
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
      releaseObservedWorkerJob()
    }
  }, [observeWorkerJob, releaseObservedWorkerJob])

  useEffect(() => {
    if (!isTauriRuntime()) return
    void checkEnv()
  }, [checkEnv])

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
          const workerResult = await runWorkerJobAndWait<EnvRepairResult>('repair_env', { target }, observeWorkerJob)
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
        result = await runWorkerJobAndWait<EnvRepairResult>('repair_env', { target }, observeWorkerJob)
      }
      setEnvRepairResult(result)
      let env: EnvStatus
      try {
        env = await runWorkerJobAndWait<EnvStatus>('check_env', {}, observeWorkerJob)
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
      releaseObservedWorkerJob()
    }
  }

  const testApi = async (): Promise<ApiTestResult | null> => {
    let draft = settingsDraftStateRef.current
    let candidateApi = draft?.draft.apiConfig ?? request.api_config
    let normalizedApi = normalizeApiConfigForRequest(candidateApi)
    if (
      normalizedApi.base_url !== candidateApi.base_url ||
      normalizedApi.model !== candidateApi.model ||
      normalizedApi.provider !== candidateApi.provider
    ) {
      if (draft) {
        const normalizedDraft = updateSettingsDraftState((current) =>
          patchApiSettingsDraft(current, {
            provider: normalizedApi.provider,
            base_url: normalizedApi.base_url,
            model: normalizedApi.model,
            capabilities: normalizedApi.capabilities,
          }),
        )
        draft = normalizedDraft ?? draft
        candidateApi = draft.draft.apiConfig
        normalizedApi = normalizeApiConfigForRequest(candidateApi)
      } else {
        patchRequest({ api_config: { ...normalizedApi, api_key: candidateApi.api_key } })
      }
      setStatus('已自动修正模型 API 配置，再开始测试连接。')
    }

    let settingsAttempt: {
      runId: string
      fingerprint: string
      credentialRevision: number
    } | null = null
    if (draft) {
      const pendingRunId =
        draft.pendingSave?.targets.includes('model') && draft.verification.model.status === 'testing'
          ? draft.pendingSave.runId
          : null
      const runId = pendingRunId ?? `settings-model-${Date.now()}-${apiTestRunRef.current + 1}`
      if (!pendingRunId) {
        const started = updateSettingsDraftState((current) =>
          beginSettingsVerification(current, {
            targets: ['model'],
            intent: 'test',
            runId,
          }),
        )
        draft = started ?? draft
      }
      const attempt = draft.verification.model
      settingsAttempt = {
        runId,
        fingerprint: attempt.fingerprint,
        credentialRevision: attempt.credentialRevision,
      }
    }

    const profileId = apiProfileIdFromConfig(normalizedApi)
    const savedProfile = savedApiProfiles.find(
      (profile) => profile.id === profileId && apiConfigMatchesProfile(normalizedApi, profile),
    )
    const baseTarget = apiProfileVerificationTarget(normalizedApi, savedProfile)
    const testTarget: ProfileVerificationTarget = draft
      ? {
          ...baseTarget,
          credentialRevision: draft.draft.credentialRevisions.model,
        }
      : baseTarget
    apiTestBindingRef.current = testTarget
    const testRun = apiTestRunRef.current + 1
    apiTestRunRef.current = testRun
    const acceptApiTestResult = (result: ApiTestResult, persist = !draft) => {
      const activeBinding = apiTestBindingRef.current
      if (
        !activeBinding ||
        activeBinding.verificationFingerprint !== testTarget.verificationFingerprint ||
        apiTestRunRef.current !== testRun ||
        activeBinding.credentialRevision !== testTarget.credentialRevision
      ) {
        setApiTestResult(null)
        setStatus('模型测试已经返回，但设置在测试期间发生了变化；旧结果未应用，请重新验证当前配置。')
        return false
      }

      if (settingsAttempt) {
        const completed = updateSettingsDraftState((current) =>
          completeSettingsVerification(current, {
            target: 'model',
            runId: settingsAttempt.runId,
            verificationFingerprint: settingsAttempt.fingerprint,
            credentialRevision: settingsAttempt.credentialRevision,
            ok: result.ok,
            errorCode: result.error_code,
          }),
        )
        const expectedStatus = result.ok ? 'passed' : 'failed'
        if (completed?.verification.model.status !== expectedStatus) {
          setApiTestResult(null)
          setStatus('模型测试已经返回，但草稿已变化；旧结果未应用，请重新验证当前配置。')
          return false
        }
      }

      setApiTestResult(result)
      if (persist) rememberSavedApiTestResult(normalizedApi, result, testTarget)
      return true
    }

    if (isHermesLocalApiConfig(normalizedApi)) {
      const proxy = await startHermesForSettings()
      if (proxy.state !== 'ready') {
        const result: ApiTestResult = {
          ok: false,
          provider: normalizedApi.provider,
          model: normalizedApi.model,
          message: proxy.message,
          error_code: proxy.state === 'oauth_unready' ? 'MODEL_AUTH_FAILED' : 'MODEL_CONNECTION_FAILED',
          stage: 'hermes_proxy',
          retryable: proxy.state === 'stopped' || proxy.state === 'error',
        }
        if (acceptApiTestResult(result)) setStatus('API 测试失败：' + proxy.message)
        return result
      }
    }

    let api: ApiConfig
    try {
      api = await loadApiConfigForWorker(normalizedApi)
    } catch {
      const result: ApiTestResult = {
        ok: false,
        provider: normalizedApi.provider,
        model: normalizedApi.model,
        message: '系统凭据读取失败，请在设置页重新保存 API Key。',
        error_code: 'MODEL_AUTH_FAILED',
        stage: 'model_api',
        retryable: false,
      }
      if (acceptApiTestResult(result)) {
        setStatus('API 测试失败：系统凭据读取失败，请重新保存 API Key。')
      }
      return result
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
      if (acceptApiTestResult(result)) setStatus(`API 测试失败：${message}`)
      return result
    }

    const configError = validateApiConfigForRequest(api)
    if (configError) {
      const errorCode = !api.model.trim()
        ? 'MODEL_NOT_FOUND'
        : configError.includes('Base URL') || configError.includes('URL')
          ? 'MODEL_CONNECTION_FAILED'
          : 'MODEL_AUTH_FAILED'
      return failBeforeRequest(configError, errorCode)
    }

    setApiTesting(true)
    setBusy(true)
    setApiTestResult(null)
    setWorkerProgress(null)
    setStatus('正在测试模型 API 连接。')
    try {
      if (!isTauriRuntime()) {
        const result: ApiTestResult = {
          ok: api.provider === 'local',
          provider: api.provider,
          model: api.model,
          message:
            api.provider === 'local'
              ? '预览模式可用，但不能用于正式抽取学习点或制卡。'
              : '浏览器预览模式不能真实测试 API，请运行桌面端。',
        }
        if (acceptApiTestResult(result, false)) setStatus(result.message)
        return result
      }

      const result = await runWorkerJobAndWait<ApiTestResult>('test_api', { api_config: api }, observeWorkerJob)
      if (acceptApiTestResult(result)) {
        setStatus(result.ok ? `API 测试通过：${result.message}` : `API 测试失败：${result.message}`)
      }
      return result
    } catch (error) {
      if (isWorkerJobCancelled(error)) {
        if (settingsAttempt) {
          updateSettingsDraftState((current) =>
            cancelSettingsVerification(current, {
              target: 'model',
              runId: settingsAttempt.runId,
            }),
          )
        }
        apiTestBindingRef.current = null
        setApiTestResult(null)
        setStatus('模型连接测试已取消；原有验证记录未改变。')
        return null
      }
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
      if (acceptApiTestResult(result)) setStatus(`API 测试失败：${message}`)
      return result
    } finally {
      setApiTesting(false)
      releaseObservedWorkerJob()
    }
  }
  const testTts = async (): Promise<TtsTestResult | null> => {
    const draft = settingsDraftStateRef.current
    const candidateApi = draft?.draft.apiConfig ?? request.api_config
    const testedTtsForPersistence = resolveTtsConfig(candidateApi.tts_config, candidateApi)

    let settingsAttempt: {
      runId: string
      fingerprint: string
      credentialRevision: number
    } | null = null
    if (draft) {
      const pendingRunId =
        draft.pendingSave?.targets.includes('tts') && draft.verification.tts.status === 'testing'
          ? draft.pendingSave.runId
          : null
      const runId = pendingRunId ?? `settings-tts-${Date.now()}-${ttsTestRunRef.current + 1}`
      let started = draft
      if (!pendingRunId) {
        started =
          updateSettingsDraftState((current) =>
            beginSettingsVerification(current, {
              targets: ['tts'],
              intent: 'test',
              runId,
            }),
          ) ?? draft
      }
      const attempt = started.verification.tts
      settingsAttempt = {
        runId,
        fingerprint: attempt.fingerprint,
        credentialRevision: attempt.credentialRevision,
      }
    }

    const profileId = ttsProfileIdFromConfig(testedTtsForPersistence)
    const savedProfile = savedTtsProfiles.find(
      (profile) => profile.id === profileId && ttsConfigMatchesProfile(testedTtsForPersistence, profile),
    )
    const baseTarget = ttsProfileVerificationTarget(testedTtsForPersistence, savedProfile)
    const testTarget: ProfileVerificationTarget = draft
      ? {
          ...baseTarget,
          credentialRevision: draft.draft.credentialRevisions.tts,
        }
      : baseTarget
    ttsTestBindingRef.current = testTarget
    const testRun = ttsTestRunRef.current + 1
    ttsTestRunRef.current = testRun
    const acceptTtsTestResult = (result: TtsTestResult, persist = !draft) => {
      const activeBinding = ttsTestBindingRef.current
      if (
        !activeBinding ||
        ttsTestRunRef.current !== testRun ||
        activeBinding.verificationFingerprint !== testTarget.verificationFingerprint ||
        activeBinding.credentialRevision !== testTarget.credentialRevision
      ) {
        setTtsTestResult(null)
        setStatus('TTS 测试已经返回，但设置在测试期间发生了变化；旧结果未应用，请重新验证当前配置。')
        return false
      }

      if (settingsAttempt) {
        const completed = updateSettingsDraftState((current) =>
          completeSettingsVerification(current, {
            target: 'tts',
            runId: settingsAttempt.runId,
            verificationFingerprint: settingsAttempt.fingerprint,
            credentialRevision: settingsAttempt.credentialRevision,
            ok: result.ok,
            errorCode: result.error_code,
          }),
        )
        const expectedStatus = result.ok ? 'passed' : 'failed'
        if (completed?.verification.tts.status !== expectedStatus) {
          setTtsTestResult(null)
          setStatus('TTS 测试已经返回，但草稿已变化；旧结果未应用，请重新验证当前配置。')
          return false
        }
      }

      setTtsTestResult(result)
      if (persist) rememberSavedTtsTestResult(testedTtsForPersistence, result, testTarget)
      return true
    }

    let resolvedTtsRuntime: { apiConfig: ApiConfig; ttsConfig: TtsConfig }
    try {
      resolvedTtsRuntime = await loadTtsConfigForWorker(candidateApi.tts_config, candidateApi)
    } catch {
      const result: TtsTestResult = {
        ok: false,
        provider: testedTtsForPersistence.provider,
        model: testedTtsForPersistence.model,
        voice: testedTtsForPersistence.voice,
        message: '系统凭据读取失败，请在设置页重新保存 TTS/API Key。',
        error_code: 'TTS_AUTH_FAILED',
        stage: 'tts',
        retryable: false,
      }
      if (acceptTtsTestResult(result)) {
        setStatus('TTS 测试失败：系统凭据读取失败，请重新保存 TTS/API Key。')
      }
      return result
    }

    const activeBinding = ttsTestBindingRef.current
    if (
      ttsTestRunRef.current !== testRun ||
      !activeBinding ||
      activeBinding.verificationFingerprint !== testTarget.verificationFingerprint ||
      activeBinding.credentialRevision !== testTarget.credentialRevision
    ) {
      setTtsTestResult(null)
      setStatus('TTS 设置在读取凭据期间发生了变化；旧测试已停止，请重新验证当前配置。')
      return null
    }

    const apiConfigForTts = resolvedTtsRuntime.apiConfig
    const currentTts = resolvedTtsRuntime.ttsConfig
    const failBeforeRequest = (message: string, errorCode: string = 'TTS_AUTH_FAILED') => {
      const result: TtsTestResult = {
        ok: false,
        provider: currentTts.provider,
        model: currentTts.model,
        voice: currentTts.voice,
        message,
        error_code: errorCode,
        stage: 'tts',
        retryable: false,
      }
      if (acceptTtsTestResult(result)) setStatus(`TTS 测试失败：${message}`)
      return result
    }

    if (!currentTts.enabled || currentTts.provider === 'disabled') {
      return failBeforeRequest('TTS 当前是关闭状态。', 'TTS_NOT_FOUND')
    }
    const ttsConfigError = validateTtsConfigForRequest(currentTts)
    if (ttsConfigError) {
      const errorCode =
        !currentTts.model.trim() || !currentTts.voice.trim()
          ? 'TTS_NOT_FOUND'
          : ttsConfigError.includes('Base URL') || ttsConfigError.includes('URL')
            ? 'TTS_CONNECTION_FAILED'
            : 'TTS_AUTH_FAILED'
      return failBeforeRequest(ttsConfigError, errorCode)
    }
    if (currentTts.provider === 'grok' && !currentTts.voice.trim()) {
      return failBeforeRequest('Grok TTS 需要填写 voice_id，例如 eve、ara、leo、rex、sal。', 'TTS_NOT_FOUND')
    }
    if (currentTts.provider === 'gemini' && !currentTts.model.trim()) {
      return failBeforeRequest('Gemini TTS 需要填写 TTS 模型名。', 'TTS_NOT_FOUND')
    }
    if (currentTts.provider === 'gemini-vertex' && !currentTts.model.trim()) {
      return failBeforeRequest('Gemini Vertex TTS 需要填写 TTS 模型名。', 'TTS_NOT_FOUND')
    }
    if (
      (currentTts.provider === 'openai-compatible' || currentTts.provider === 'mimo') &&
      (!currentTts.base_url.trim() || !currentTts.model.trim())
    ) {
      return failBeforeRequest(
        currentTts.provider === 'mimo'
          ? 'MIMO TTS 需要 Base URL 和模型名。'
          : 'OpenAI-compatible Speech 需要 Base URL 和模型名。',
        'TTS_NOT_FOUND',
      )
    }
    if (
      currentTts.provider === 'mimo' &&
      isMimoTokenPlanKey(currentTts.api_key) &&
      !isMimoTokenPlanBase(currentTts.base_url)
    ) {
      return failBeforeRequest(
        `你填的是 tp- 开头的 Token Plan Key，TTS Base URL 必须用 ${MIMO_TOKEN_PLAN_SGP_BASE_URL}，不能用公共 ${MIMO_OPENAI_BASE_URL}。请点 “MIMO SGP TTS” 预设。`,
        'TTS_AUTH_FAILED',
      )
    }

    setTtsTesting(true)
    setBusy(true)
    setTtsTestResult(null)
    setWorkerProgress(null)
    setStatus('正在测试 TTS 语音接口（最长等待 75 秒，应用不会被卡死）。')
    try {
      if (!isTauriRuntime()) {
        const result: TtsTestResult = {
          ok: false,
          provider: currentTts.provider,
          model: currentTts.model,
          voice: currentTts.voice,
          message: '浏览器预览模式不能真实测试 TTS，请运行桌面端。',
        }
        if (acceptTtsTestResult(result, false)) setStatus(result.message)
        return result
      }

      const result = await runWorkerJobAndWait<TtsTestResult>(
        'test_tts',
        {
          tts_config: currentTts,
          api_config: apiConfigForTts,
          language: candidateApi.tts_config.language,
        },
        observeWorkerJob,
      )
      if (acceptTtsTestResult(result)) {
        setStatus(result.ok ? `TTS 测试通过：${result.message}` : `TTS 测试失败：${result.message}`)
      }
      return result
    } catch (error) {
      if (isWorkerJobCancelled(error)) {
        if (settingsAttempt) {
          updateSettingsDraftState((current) =>
            cancelSettingsVerification(current, {
              target: 'tts',
              runId: settingsAttempt.runId,
            }),
          )
        }
        ttsTestBindingRef.current = null
        setTtsTestResult(null)
        setStatus('TTS 语音测试已取消；原有验证记录未改变。')
        return null
      }
      const message = redactSensitiveText(error)
      const result: TtsTestResult = {
        ok: false,
        provider: currentTts.provider,
        model: currentTts.model,
        voice: currentTts.voice,
        message,
        error_code: 'TTS_CONNECTION_FAILED',
        stage: 'tts',
        retryable: true,
      }
      if (acceptTtsTestResult(result)) setStatus(`TTS 测试失败：${message}`)
      return result
    } finally {
      setTtsTesting(false)
      releaseObservedWorkerJob()
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
      const blockApiPreflight = (message: string) => {
        setSettingsTab('api')
        setSettingsOpen(false)
        setStatus(message)
      }
      if (generateRequest.api_config.provider === 'local') {
        blockApiPreflight('AI 精筛学习点需要正式模型 API。请先在“模型 API”里选择服务商、保存配置并测试连接。')
        return
      }
      if (resolvedApi.error) {
        blockApiPreflight(`AI 精筛学习点前模型 API 配置未通过：${resolvedApi.error}`)
        return
      }
      if (resolvedApi.fallbackReason) {
        const fallbackIssue = resolvedApi.fallbackReason.replace(/[。.!！?？]+$/u, '')
        blockApiPreflight(`模型 API 未就绪：${fallbackIssue}。学习点抽取不会退回本地半成品，请先测试模型 API。`)
        return
      }
      if (!apiReadyForGeneration) {
        blockApiPreflight(
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
      replaceWorkerOperation({ status: 'succeeded', command: 'extract_learning_points' })
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
      const job = await startWorkerJob(
        'extract_learning_points',
        requestSnapshot,
        fingerprintWorkflowRequest(generateRequest),
      )
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
      replaceWorkerOperation({ status: 'failed', command: 'extract_learning_points' })
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
      const blockPreflight = (tab: SettingsTab, message: string) => {
        setSettingsTab(tab)
        setSettingsOpen(false)
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
        blockPreflight(
          'api',
          '当前选择的是预览模式，不能作为正式制卡结果。请先在“模型 API”里选择服务商、保存配置并测试连接。',
        )
        return
      }
      if (resolvedApi.error) {
        blockPreflight('api', `生成前模型 API 配置未通过：${resolvedApi.error}`)
        return
      }
      if (resolvedApi.fallbackReason) {
        const fallbackIssue = resolvedApi.fallbackReason.replace(/[。.!！?？]+$/u, '')
        blockPreflight('api', `模型 API 未就绪：${fallbackIssue}。已禁止退回本地字幕草稿，请先测试模型 API。`)
        return
      }
      if (!apiReadyForGeneration) {
        blockPreflight(
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
        replaceWorkerOperation({ status: 'succeeded', command: 'generate' })
        setActiveWorkspaceStage('review')
        setBusy(false)
      } else {
        const job = await startWorkerJob('generate', requestSnapshot, fingerprintWorkflowRequest(generateRequest))
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
      replaceWorkerOperation({ status: 'failed', command: 'generate' })
      setLastWorkerError(null)
      setStatus(redactSensitiveText(error))
    }
  }

  const extractLearningPointsWithoutCache = async () => {
    await extractLearningPoints({ bypassCache: true })
  }

  const reconcileTerminalWorker = async (jobId: string): Promise<boolean> => {
    const task = await getWorkerTask(jobId)
    if (!task || task.state === 'queued' || task.state === 'running' || task.state === 'cancelling') return false
    if (locallyObservedWorkerJobIdsRef.current.has(jobId)) {
      setStatus('后台任务已经结束，正在整理最终状态。')
      return true
    }

    let finished = await getWorkerJobStatus(jobId)
    if (!finished) {
      if (task.state === 'succeeded') {
        try {
          const result = await readWorkerJobResult<unknown>(jobId)
          finished = {
            job_id: task.id,
            command: task.command,
            ok: true,
            result,
            result_ref: task.resultRef,
            finished_at_ms: task.updatedAt,
          }
        } catch (error) {
          finished = {
            job_id: task.id,
            command: task.command,
            ok: false,
            error: `后台任务已结束，但结果读取失败：${redactSensitiveText(error)}`,
            error_code: 'WORKER_RESULT_READ_FAILED',
            retryable: true,
            finished_at_ms: task.updatedAt,
          }
        }
      } else {
        finished = {
          job_id: task.id,
          command: task.command,
          ok: false,
          error: task.error?.message ?? (task.state === 'cancelled' ? '任务已取消。' : '后台任务意外中断。'),
          error_code: task.error?.code ?? (task.state === 'cancelled' ? 'WORKER_CANCELLED' : 'UNKNOWN_WORKER_ERROR'),
          retryable: task.error?.retryable ?? task.state !== 'cancelled',
          cancelled: task.state === 'cancelled',
          finished_at_ms: task.updatedAt,
        }
      }
    }
    await handleWorkerFinishedRef.current(finished)
    return true
  }

  const cancelCurrentWorker = async () => {
    const current = workerOperationRef.current
    const jobId = current.jobId
    if (!jobId || (current.status !== 'running' && current.status !== 'cancelling')) return
    setCancelRequestedAt(Date.now())
    setShowForceCancel(false)
    setForceCancelBusy(false)
    const cancellingOperation: WorkerOperation = { ...current, status: 'cancelling', jobId }
    replaceWorkerOperation(cancellingOperation)
    setBusy(true)
    setLastWorkerError(null)
    setStatus('正在取消当前任务，请稍等。')
    try {
      const result = await cancelWorkerJob(jobId)
      if (!result.cancelled) {
        const reconciled = await reconcileTerminalWorker(jobId)
        if (!reconciled) {
          setStatus('取消请求没有得到终态确认；应用会继续等待并保留“取消中”，不会清空当前批次。')
        }
      }
    } catch (error) {
      let reconciled = false
      try {
        reconciled = await reconcileTerminalWorker(jobId)
      } catch {
        // Keep the cancellating state when neither the request nor task read can prove a terminal state.
      }
      if (!reconciled) {
        replaceWorkerOperation(cancellingOperation)
        setBusy(true)
        setStatus(`取消请求失败且尚未确认任务终态：${redactSensitiveText(error)}。应用会继续等待。`)
      }
    }
  }

  const forceCancelCurrentWorker = async () => {
    const current = workerOperationRef.current
    const jobId = current.jobId
    if (!jobId || current.status !== 'cancelling' || !showForceCancel || forceCancelBusy) return
    setForceCancelBusy(true)
    setStatus('正在强制结束没有及时响应的后台任务，并保留最后一个安全阶段。')
    try {
      const result = await forceCancelWorkerJob(jobId)
      const reconciled = await reconcileTerminalWorker(jobId)
      if (!reconciled) {
        replaceWorkerOperation({ ...current, status: 'cancelling', jobId })
        setBusy(true)
        setStatus(
          !result.found || result.state === 'not_found'
            ? '后端没有找到活动进程，但也没有可验证的终态；窗口和当前批次会保持不变，请稍后重试。'
            : '强制结束请求已发送，但终态尚未持久化；应用会继续等待。',
        )
      }
    } catch (error) {
      let reconciled = false
      try {
        reconciled = await reconcileTerminalWorker(jobId)
      } catch {
        // A read failure is not proof that the worker stopped.
      }
      if (!reconciled) {
        replaceWorkerOperation({ ...current, status: 'cancelling', jobId })
        setBusy(true)
        setStatus('强制结束任务失败且尚未确认终态：' + redactSensitiveText(error))
      }
    } finally {
      setForceCancelBusy(false)
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
    const queueIds = new Set(selectedPoints.map((point) => point.id))
    const queueSummary = buildGenerationQueueSummary({
      generationQueuePoints: selectedPoints,
      generationBatchProgress: null,
      request,
    })
    const requiresSecurityReview = queueSummary.securityWarnings.some(
      (warning) => warning.includes('本机/内网 URL') || warning.includes('remote components'),
    )
    setGenerationQueueSelectedIds(queueIds)
    setActiveWorkspaceStage('review')
    if (!queueSummary.highRisk && !requiresSecurityReview) {
      setGenerationConfirmOpen(false)
      setStatus('正在开始生成选中的 ' + String(selectedPoints.length) + ' 张卡片。')
      void confirmGenerateCardsFromLearningPoints(queueIds)
      return
    }
    setGenerationConfirmOpen(true)
    setStatus(
      queueSummary.highRisk
        ? '本次将生成 ' + String(selectedPoints.length) + ' 张卡片，请确认批次数和媒体任务。'
        : '本次包含需要明确授权的网络访问，请确认后继续。',
    )
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
    // A retry must never reuse a cached fallback or structurally incomplete model response.
    // A fresh namespace also keeps the successful prior cards available only through the
    // explicit base project merge, where the reliability gate can account for them.
    setCardGenerationCacheNamespace(retryCardGenerationCacheNamespace())
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

  const confirmGenerateCardsFromLearningPoints = async (selectedIdsOverride?: unknown) => {
    if (workerBusy) {
      setStatus('已有任务正在运行，请先取消或等待完成。')
      return
    }
    if (!learningPointResult) {
      setStatus('还没有学习点清单。请先从字幕抽取学习点。')
      return
    }
    const activeSelectedIds =
      selectedIdsOverride instanceof Set
        ? (selectedIdsOverride as Set<string>)
        : (generationQueueSelectedIds ?? selectedLearningPointIds)
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
      const blockPreflight = (tab: SettingsTab, message: string) => {
        setSettingsTab(tab)
        setSettingsOpen(false)
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
        blockPreflight(
          'api',
          '当前选择的是预览模式，不能作为正式卡片结果。请先在“模型 API”里选择服务商、保存配置并测试连接。',
        )
        return
      }
      if (resolvedApi.error) {
        blockPreflight('api', `生成 APKG 前模型 API 配置未通过：${resolvedApi.error}`)
        return
      }
      if (resolvedApi.fallbackReason) {
        const fallbackIssue = resolvedApi.fallbackReason.replace(/[。.!！?？]+$/u, '')
        blockPreflight('api', `模型 API 未就绪：${fallbackIssue}。已禁止退回本地字幕草稿，请先测试模型 API。`)
        return
      }
      if (!apiReadyForGeneration) {
        blockPreflight(
          'api',
          '模型 API 尚未通过测试，不能生成 APKG。保存过且测试通过的模型方案无需重复测试；如果改过配置，请重新保存并测试。',
        )
        return
      }
      const resolvedTtsForPreflight = resolveTtsConfig(generateRequest.api_config.tts_config, resolvedApi.api)
      if (ttsRequired && (!resolvedTtsForPreflight.enabled || resolvedTtsForPreflight.provider === 'disabled')) {
        blockPreflight('tts', '视频卡导出需要整句 TTS 和表达 TTS。请在“语音/TTS”里启用并测试通过后再生成 APKG。')
        return
      }
      if (ttsRequired && !ttsReadyForGeneration) {
        blockPreflight('tts', '视频卡导出需要先通过 TTS 测试，否则不会生成 APKG。请测试语音配置后再继续。')
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
      setProductStep('deliver')
      const demo = createDemoProject(request)
      setProject(demo)
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
      replaceWorkerOperation({ status: 'succeeded', command: 'generate_cards_from_learning_points' })
      setStatus(
        `演示卡片生成完成。已把 ${selectedPoints.length} 个演示学习点生成浏览器演示卡片；真实 APKG 导出请用 Tauri 桌面端。`,
      )
      return
    }
    setGenerationConfirmOpen(false)
    setProductStep('deliver')
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
      message: totalBatches > 1 ? `准备分 ${totalBatches} 批生成卡片草稿。` : '准备生成卡片草稿。',
    })
    setStatus(
      totalBatches > 1
        ? `正在生成卡片草稿：将 ${selectedPoints.length} 个学习点分 ${totalBatches} 批处理。完成审核后再由你明确导出 APKG。`
        : `正在生成 ${selectedPoints.length} 张卡片草稿。完成审核后再由你明确导出 APKG。`,
    )
    try {
      await startNextLearningPointGenerationBatch(runtime)
      if (totalBatches <= 1) {
        setGenerationQueueSelectedIds(null)
      }
    } catch (error) {
      setBusy(false)
      setGenerationBatchRuntime(null)
      replaceWorkerOperation({ status: 'failed', command: 'generate_cards_from_learning_points' })
      setLastWorkerError(null)
      setGenerationConfirmOpen(true)
      setStatus(redactSensitiveText(error))
    }
  }

  const changeOutputDirectory = async () => {
    if (workerBusy) {
      setStatus('任务运行期间不能更改保存目录。请先取消或等待当前任务完成。')
      return false
    }
    if (!isTauriRuntime()) {
      setStatus('浏览器预览模式不能选择 APKG 保存目录，请运行桌面端。')
      return false
    }
    const defaultPath =
      outputDirectory ||
      (project ? defaultExportDirectoryForProject(project) : null) ||
      defaultExportDirectoryForRequest(request) ||
      (await defaultExportDirectory())
    const selected = await selectDirectory({
      title: APKG_EXPORT_DIRECTORY_DIALOG_TITLE,
      defaultPath,
    })
    if (typeof selected !== 'string') {
      setStatus('已保留原保存目录。')
      return false
    }
    try {
      const availability = await checkOutputDirectory(selected)
      if (availability !== 'writable') {
        setStatus('这个目录不存在或不可写，请选择其他文件夹。')
        return false
      }
    } catch (error) {
      setStatus('无法验证这个目录是否可写：' + redactSensitiveText(error))
      return false
    }
    saveOutputDirectoryPreference(selected)
    setOutputDirectory(selected)
    setStatus('APKG 将保存到：' + selected)
    return true
  }
  async function startExportForProject(options: StartExportOptions = {}) {
    if (workerBusy) {
      setStatus('已有任务正在运行，请先取消或等待完成。')
      return false
    }
    const targetProject = project
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
      replaceWorkerOperation({ status: 'failed', command: 'export' })
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
      replaceWorkerOperation({ status: 'failed', command: 'export' })
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
    const preferredOutputDir = options.outputDir ? null : await reusableOutputDirectory(outputDirectory)
    const outputDirCandidate =
      options.outputDir ??
      preferredOutputDir ??
      (await selectDirectory({
        title: APKG_EXPORT_DIRECTORY_DIALOG_TITLE,
        defaultPath: defaultOutputDir,
      }))
    if (typeof outputDirCandidate !== 'string') {
      setLastWorkerError(null)
      setStatus('已取消导出：未选择 APKG 保存目录。')
      return false
    }
    const outputDir = await reusableOutputDirectory(outputDirCandidate)
    if (!outputDir) {
      setLastWorkerError(null)
      setStatus('无法使用这个保存目录：目录不存在或不可写，请重新选择。')
      return false
    }
    const releaseOutputGuard = releaseApkgOutputGuardForProject(projectForExport, outputDir)
    if (releaseOutputGuard.status === 'blocked') {
      setLastWorkerError(releaseApkgTargetGuardFailureEvent(releaseOutputGuard))
      replaceWorkerOperation({ status: 'failed', command: 'export' })
      setStatus(releaseOutputGuard.statusMessage)
      return false
    }

    saveOutputDirectoryPreference(outputDir)
    setOutputDirectory(outputDir)
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
        auto: false,
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
      const job = await startWorkerJob('export', exportPayload, fingerprintWorkflowRequest(request))
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
        message: exportWorkerStartedProgressMessage(false),
      })
      setStatus(exportWorkerStartedStatusMessage(false))
      return true
    } catch (error) {
      setBusy(false)
      replaceWorkerOperation({ status: 'failed', command: 'export' })
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
    const exportForImport = exportResultForAnkiVerify(lastExportFullRef.current, lastExport)
    const preparation = prepareAnkiVerifyStart({
      workerBusy,
      exportResult: exportForImport,
      tauriRuntime: isTauriRuntime(),
    })
    if (!preparation.ok) {
      if (preparation.statusMessage) setStatus(preparation.statusMessage)
      return
    }
    setStatus(ankiOpenImportStartingStatusMessage())
    setAnkiVerifying(true)
    setBusy(true)
    try {
      await ensureAnkiRunning()
      const prepared = await runWorkerJobAndWait<{
        ok: boolean
        message?: string
        media_recovery_failures?: Array<{ file?: string; error?: string }>
      }>(
        'verify_anki_import',
        buildAnkiMediaPreparationPayload(preparation.exportResult),
        observeWorkerJob,
        fingerprintWorkflowRequest(request),
      )
      if (!prepared.ok) {
        throw new Error(prepared.message || 'Anki 媒体安全预置失败。')
      }
      await openAnkiImportFile(preparation.exportResult.apkg_path)
      setStatus(ankiOpenImportRequestedStatusMessage())
    } catch (error) {
      setStatus(`无法安全打开 Anki 导入：${redactSensitiveText(error)}。请确认 Anki 已打开且 AnkiConnect 可用后重试。`)
    } finally {
      setAnkiVerifying(false)
      releaseObservedWorkerJob()
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
      await ensureAnkiRunning()
      const job = await startWorkerJob(
        'verify_anki_import',
        buildAnkiVerifyPayload(preparation.exportResult),
        fingerprintWorkflowRequest(request),
      )
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
      replaceWorkerOperation({ status: 'failed', command: 'verify_anki_import' })
      setLastWorkerError(null)
      setStatus(redactSensitiveText(error))
    }
  }

  const abandonRecoveredWorkflow = async () => {
    const recovered = recoveredWorkflowTask
    if (!recovered) return false
    if (!isTauriRuntime()) {
      setRecoveredWorkflowTask(null)
      setRecoveredGenerationIds([])
      setGenerationQueueSelectedIds(null)
      setStatus('已放弃上次中断任务；当前素材和已有结果仍保留。')
      return true
    }

    abandonedRecoveryTaskIdsRef.current.add(recovered.id)
    checkpointPersistenceSuspendedRef.current = true
    setRecoveredWorkflowTask(null)
    setRecoveredGenerationIds([])
    setGenerationQueueSelectedIds(null)
    setGenerationBatchRuntime(null)
    generationRetryBaseProjectRef.current = null
    if (workerOperationRef.current.jobId === recovered.id) {
      replaceWorkerOperation({ status: 'idle' })
      setWorkerProgress(null)
      setBusy(false)
    }
    try {
      await checkpointWriteChainRef.current.catch(() => undefined)
      await clearWorkflowCheckpoint()
      setStatus('已放弃上次中断任务。当前素材、卡片草稿和 APKG 均已保留，不会删除用户文件。')
      return true
    } catch (error) {
      setStatus('无法清除恢复记录：' + redactSensitiveText(error))
      return false
    } finally {
      checkpointPersistenceSuspendedRef.current = false
      setCheckpointRetryRevision((revision) => revision + 1)
    }
  }
  const resumeRecoveredWorkflow = async () => {
    const recovered = recoveredWorkflowTask
    if (!recovered) return

    if (recovered.action === 'generate_cards') {
      if (recoveredGenerationIds.length === 0) {
        setRecoveredWorkflowTask(null)
        setStatus('无法继续生成：恢复检查点没有经过验证的剩余学习点。应用不会默认重跑整项任务。')
        return
      }
      if (!learningPointResult) {
        setStatus('无法继续生成：恢复检查点缺少学习点清单，请重新分析素材。')
        return
      }
      const remainingIds = new Set(recoveredGenerationIds)
      generationRetryBaseProjectRef.current = project
      setRecoveredWorkflowTask(null)
      setRecoveredGenerationIds([])
      setSelectedLearningPointIds(remainingIds)
      setGenerationQueueSelectedIds(remainingIds)
      setProject(null)
      setProductStep('deliver')
      setStatus(`正在从安全检查点继续生成剩余 ${remainingIds.size} 张；已完成批次不会重复调用模型。`)
      await confirmGenerateCardsFromLearningPoints(remainingIds)
      return
    }

    setRecoveredWorkflowTask(null)
    setRecoveredGenerationIds([])
    if (recovered.action === 'analyze_source') {
      setProductStep('source')
      await extractLearningPoints()
      return
    }
    if (recovered.action === 'export_cards') {
      setProductStep('deliver')
      await exportApkg()
      return
    }
    if (recovered.action === 'import_and_verify') {
      setProductStep('deliver')
      await verifyAnkiImport()
      return
    }
    setStatus('无法继续：该中断任务不属于受支持的制卡恢复动作。应用没有自动重跑。')
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
      return applyCardPatchWithReliabilityInvalidation(current, segmentId, cardId, patch)
    })
  }

  const selectTemplate = (templateId: TemplateId) => {
    if (blockRequestMutationWhileWorkerActive()) return
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
      replaceWorkerOperation({ status: 'idle' })
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
  const activeSegmentVideoSrc = activeSegment ? previewVideoSrc : ''
  const activeSegmentVideoError = activeSegment ? previewVideoError : ''

  return {
    activeWorkspaceStage,
    productStep,
    activeSegment,
    activeSegmentId,
    activeSegmentVideoSrc,
    activeSegmentVideoError,
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
    apiReadyForGeneration,
    hermesChecking,
    hermesStarting,
    hermesStatus,
    appBusy,
    applyApiPreset,
    applyCollectionPreset,
    applyTtsPreset,
    cancelCurrentWorker,
    forceCancelCurrentWorker,
    forceCancelBusy,
    showForceCancel,
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
    outputDirectory,
    changeOutputDirectory,
    extractLearningPoints,
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
    workflowUiSnapshot,
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
    resumeRecoveredWorkflow,
    abandonRecoveredWorkflow,
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
    deleteSavedApiCredential,
    saveCurrentTtsProfile,
    deleteSavedTtsCredential,
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
    setProductStep,
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
    settingsApiConfig,
    settingsTts,
    settingsActiveApiProfileId,
    settingsActiveTtsProfileId,
    settingsActiveApiKeySaved,
    settingsActiveTtsKeySaved,
    settingsApiProfileDirty: !settingsApiProfileSaved,
    settingsTtsProfileDirty: !settingsTtsProfileSaved,
    settingsApiProfileStatus,
    settingsTtsProfileStatus,
    settingsApiTestOk: settingsEffectiveApiTestResult?.ok,
    settingsTtsTestOk: settingsEffectiveTtsTestResult?.ok,
    settingsDraftDirty,
    settingsDraftMode,
    settingsSaving,
    beginSettingsDraftSession,
    setSettingsDraftDisplayMode,
    discardSettingsChanges,
    endSettingsDraftSession,
    saveSettingsAndVerify,
    applySettingsDraftLater,
    showAdvancedApi,
    showAdvancedTts,
    showCapabilities,
    startWindowDrag,
    startWindowResize,
    status,
    templateOptions,
    startHermesForSettings,
    refreshHermesStatus,
    testApi,
    testTts,
    toggleCardType,
    toggleCollectionLevel,
    toggleContent,
    toggleDocumentFocus,
    toggleLanguageFocus,
    toggleInspector,
    tts,
    ttsReadyForGeneration,
    ttsRequired,
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
