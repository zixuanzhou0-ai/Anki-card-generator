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
  REQUEST_STORAGE_KEY,
  selectionStrategyOptions,
  templateOptions,
} from '../domain/options'
import { materializeLearningPointInventory } from '../domain/inventoryDrafts'
import { applyUsableCardSelection, segmentMatchesFilter } from '../domain/quality'
import {
  countSelectedCards,
  getQualityCounts,
  getQualityDiagnostics,
  getQualityFunnel,
  getSegmentReviewCounts,
} from '../domain/projectMetrics'
import type { WorkerErrorActionId } from '../domain/workerErrors'
import { getWorkerErrorActions } from '../domain/workerErrors'
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
import {
  loadSavedProjectForRequest,
  loadSavedRequest,
  projectMatchesRequest,
  stripRequestSecrets,
} from '../services/projectStorage'
import {
  cancelWorkerJob,
  checkBootstrapEnv,
  loadSecret,
  repairBootstrapEnv,
  runWorker,
  saveSecret,
  startWorkerJob,
} from '../services/tauriWorker'
import { isTauriRuntime } from '../services/runtime'
import {
  openAnkiImport as openAnkiImportFile,
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

const INSPECTOR_COLLAPSE_MS = 130

function cleanLocalPath(value: string) {
  return value.trim().replace(/^["'](.+)["']$/, '$1')
}

function titleFromPath(value: string) {
  const fileName = cleanLocalPath(value).split(/[\\/]/).pop() ?? ''
  return fileName.replace(/\.[^.]+$/, '')
}

function mergeRepairResults(left: EnvRepairResult | null, right: EnvRepairResult): EnvRepairResult {
  if (!left) return right
  const failed = [...left.actions, ...right.actions].filter((action) => action.status === 'failed').length
  const manual = [...left.actions, ...right.actions].filter((action) => action.status === 'manual').length
  return {
    ok: left.ok && right.ok,
    target: left.target === right.target ? left.target : 'all',
    summary: `${left.summary}；${right.summary}；合计失败 ${failed} 个，需手动处理 ${manual} 个。`,
    actions: [...left.actions, ...right.actions],
  }
}

function touchesSourceMaterial(patch: Partial<GenerateRequest>) {
  return ['source_mode', 'source_url', 'video_path', 'subtitle_path', 'document_path'].some((key) =>
    Object.prototype.hasOwnProperty.call(patch, key),
  )
}

function modelApiTestTitle(result: ApiTestResult | null, testing: boolean) {
  if (testing) return '正在测试连接'
  if (!result) return '尚未测试'
  if (result.ok) return '连接成功'
  switch (result.error_code) {
    case 'MODEL_AUTH_FAILED':
      return '授权失败'
    case 'MODEL_TIMEOUT':
      return '请求超时'
    case 'MODEL_QUOTA_EXCEEDED':
      return '配额或限流'
    case 'MODEL_NOT_FOUND':
      return '模型或端点不存在'
    case 'MODEL_CONNECTION_FAILED':
      return '网络连接异常'
    case 'MODEL_JSON_INVALID':
      return '模型输出格式异常'
    default:
      return '测试失败'
  }
}

function ttsApiTestTitle(result: TtsTestResult | null, testing: boolean, enabled: boolean) {
  if (testing) return '正在测试 TTS'
  if (!result) return enabled ? 'TTS 已开启，尚未测试' : 'TTS 已关闭'
  if (result.ok) return 'TTS 连接成功'
  switch (result.error_code) {
    case 'TTS_AUTH_FAILED':
      return 'TTS 授权失败'
    case 'TTS_TIMEOUT':
      return 'TTS 请求超时'
    case 'TTS_QUOTA_EXCEEDED':
      return 'TTS 配额或限流'
    case 'TTS_NOT_FOUND':
      return 'TTS 模型或端点不存在'
    case 'TTS_CONNECTION_FAILED':
      return 'TTS 网络异常'
    default:
      return 'TTS 测试失败'
  }
}

export function useAppController() {
  const initialRequest = useMemo(() => loadSavedRequest(), [])
  const [request, setRequest] = useState<GenerateRequest>(initialRequest)
  const [project, setProject] = useState<Project | null>(() => {
    const savedProject = loadSavedProjectForRequest(initialRequest)
    return savedProject ? materializeLearningPointInventory(savedProject).project : savedProject
  })
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
  const [lastWorkerError, setLastWorkerError] = useState<WorkerFinishedEvent | null>(null)
  const [ankiVerifying, setAnkiVerifying] = useState(false)
  const [ankiVerifyResult, setAnkiVerifyResult] = useState<AnkiVerifyResult | null>(null)
  const [previewRate, setPreviewRate] = useState(0.75)
  const [workerProgress, setWorkerProgress] = useState<WorkerProgress | null>(null)
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
  const requestEditedDuringRunRef = useRef(requestEditedDuringRun)

  const selectedCardCount = useMemo(() => countSelectedCards(project), [project])
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

  const activeTemplate = templateOptions.find((template) => template.id === request.template_id)
  const localVideoPath = cleanLocalPath(request.video_path)
  const localSubtitlePath = cleanLocalPath(request.subtitle_path)
  const sourceReady =
    request.source_mode === 'url'
      ? Boolean(request.source_url.trim())
      : request.source_mode === 'document'
        ? Boolean(request.document_path?.trim())
        : Boolean(localVideoPath)
  const apiReady =
    request.source_mode === 'local' || request.api_config.provider === 'local' || Boolean(apiTestResult?.ok)
  const envReady =
    !isTauriRuntime() ||
    Boolean(
      envStatus?.genanki &&
      (request.source_mode === 'document' ||
        (request.source_mode === 'url' && request.url_import_mode === 'subtitles' && envStatus.yt_dlp) ||
        (envStatus.ffmpeg && (request.source_mode === 'local' || envStatus.yt_dlp))),
    )
  const currentSelectionCount = project ? selectedCardCount : request.card_types.length
  const readiness = [
    {
      id: 'source',
      label: request.source_mode === 'url' ? 'URL' : request.source_mode === 'document' ? '文档' : '素材',
      done: sourceReady,
      detail: sourceReady
        ? '已就绪'
        : request.source_mode === 'url'
          ? '待输入链接'
          : request.source_mode === 'document'
            ? '待选择 TXT/Markdown'
            : localVideoPath
              ? localSubtitlePath
                ? '视频和字幕已选择'
                : '已选视频，自动匹配字幕'
              : '待选择视频；SRT 可自动匹配',
    },
    {
      id: 'env',
      label: '环境',
      done: envReady,
      detail: envReady ? '可用' : envStatus ? '缺少依赖' : '未检查',
    },
    {
      id: 'api',
      label: 'API',
      done: apiReady,
      detail:
        request.api_config.provider === 'local'
          ? '本地草稿'
          : request.source_mode === 'local'
            ? '本地规则可生成'
            : apiTestResult?.ok
              ? '已通过'
              : apiTestResult
                ? '失败'
                : '未测试',
    },
    {
      id: 'cards',
      label: '卡片',
      done: currentSelectionCount > 0,
      detail: `${currentSelectionCount} 张`,
    },
  ]
  const apiTestTone = apiTesting ? 'testing' : apiTestResult ? (apiTestResult.ok ? 'ok' : 'warn') : 'idle'
  const apiTestTitle = modelApiTestTitle(apiTestResult, apiTesting)
  const apiTestMessage = apiTesting
    ? '正在向当前接口发送一条短测试消息，通常几秒内会返回。'
    : (apiTestResult?.message ?? '换 Provider、Base URL、模型名或 API Key 后，都建议点一次测试连接。')
  const apiTestMeta = apiTestResult
    ? `${apiTestResult.provider} · ${apiTestResult.model || '未填模型'}${
        apiTestResult.latency_ms ? ` · ${apiTestResult.latency_ms} ms` : ''
      }`
    : `${request.api_config.provider} · ${request.api_config.model || '未填模型'}`
  const tts = request.api_config.tts_config
  const ttsTestTone = ttsTesting ? 'testing' : ttsTestResult ? (ttsTestResult.ok ? 'ok' : 'warn') : 'idle'
  const ttsTestTitle = ttsApiTestTitle(ttsTestResult, ttsTesting, tts.enabled)
  const ttsTestMessage = ttsTesting
    ? '正在生成一小段测试音频，用来确认 Key、语音和接口可用。'
    : (ttsTestResult?.message ??
      (tts.enabled
        ? 'MIMO / Grok / Gemini / Vertex TTS / Speech API 都在这里单独测试，和上面的文本模型测试互不影响。'
        : '关闭时不会生成 AI 朗读，只会把视频原声音频放进卡片。'))
  const ttsTestMeta = ttsTestResult
    ? `${ttsTestResult.provider} · ${ttsTestResult.model || '无模型名'} · ${ttsTestResult.voice || '无 voice'}${
        ttsTestResult.latency_ms ? ` · ${ttsTestResult.latency_ms} ms` : ''
      }${ttsTestResult.bytes ? ` · ${ttsTestResult.bytes} bytes` : ''}`
    : `${tts.provider} · ${tts.model || '无模型名'} · ${tts.voice || '无 voice'}`
  const allApiPresets = [...featuredApiPresets, ...advancedApiPresets]
  const allTtsPresets = [...featuredTtsPresets, ...advancedTtsPresets]
  const activeApiProfileId = apiProfileIdFromConfig(request.api_config)
  const activeTtsProfileId = ttsProfileIdFromConfig(tts)
  const activeApiProfile = savedApiProfiles.find((profile) => profile.id === activeApiProfileId)
  const activeTtsProfile = savedTtsProfiles.find((profile) => profile.id === activeTtsProfileId)
  const apiProfileSaved =
    Boolean(activeApiProfile && apiConfigMatchesProfile(request.api_config, activeApiProfile)) && !apiProfileDirty
  const ttsProfileSaved =
    Boolean(activeTtsProfile && ttsConfigMatchesProfile(tts, activeTtsProfile)) && !ttsProfileDirty
  const apiProfileStatus = apiProfileSaved
    ? activeApiProfile?.has_api_key || apiAuthMode(request.api_config) !== 'api_key'
      ? `已保存 · ${activeApiProfile?.last_test_ok ? '测试通过' : '未测试'}`
      : '已保存配置 · 未保存 Key'
    : activeApiProfile
      ? '有未保存更改'
      : '未保存到我的模型'
  const ttsProfileStatus = ttsProfileSaved
    ? activeTtsProfile?.has_api_key || ttsAuthMode(tts) !== 'api_key'
      ? `已保存 · ${activeTtsProfile?.last_test_ok ? '测试通过' : '未测试'}`
      : '已保存配置 · 未保存 Key'
    : activeTtsProfile
      ? '有未保存更改'
      : '未保存到我的语音'
  const workerBusy = workerOperation.status === 'running' || workerOperation.status === 'cancelling'
  const appBusy = busy || workerBusy
  const isCancelling = workerOperation.status === 'cancelling'
  const inspectorSheetOpen = responsiveMode === 'compact' && inspectorState === 'sheet'
  const inspectorActionLabel =
    responsiveMode === 'compact'
      ? inspectorSheetOpen
        ? '关闭面板'
        : '素材面板'
      : inspectorState === 'collapsed'
        ? '打开面板'
        : '收起面板'
  const motionDuration = prefersReducedMotion ? 0 : 0.2
  const statusTone =
    appBusy || workerProgress
      ? 'active'
      : /失败|缺少|不能|请先|不存在|错误|没有/.test(status)
        ? 'warn'
        : /完成|通过|成功|可用|已打开|已切换|已套用|已保留/.test(status)
          ? 'ok'
          : 'idle'
  const workerErrorActions = useMemo(
    () => (lastWorkerError ? getWorkerErrorActions(lastWorkerError.error_code, lastWorkerError.fallbacks) : []),
    [lastWorkerError],
  )

  useEffect(() => {
    workerOperationRef.current = workerOperation
  }, [workerOperation])

  useEffect(() => {
    requestEditedDuringRunRef.current = requestEditedDuringRun
  }, [requestEditedDuringRun])

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
      setResponsiveMode(width < 1080 ? 'compact' : width < 1320 ? 'medium' : 'wide')
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
    if (!isTauriRuntime()) return
    let cancelled = false
    const restore = async () => {
      try {
        const modelKey =
          activeApiProfile?.has_api_key && activeApiProfile.auth === 'api_key'
            ? await loadSecret(profileSecretKey('api', activeApiProfile.id))
            : ''
        const ttsKey =
          activeTtsProfile?.has_api_key && activeTtsProfile.auth === 'api_key'
            ? await loadSecret(profileSecretKey('tts', activeTtsProfile.id))
            : ''
        if (cancelled) return
        setRequest((current) => ({
          ...current,
          api_config: {
            ...current.api_config,
            api_key: current.api_config.api_key || modelKey,
            tts_config: {
              ...current.api_config.tts_config,
              api_key: current.api_config.tts_config.api_key || ttsKey,
            },
          },
        }))
      } catch {
        setStatus('系统凭据读取失败，请在设置页重新填写 API Key。')
      }
    }
    restore()
    return () => {
      cancelled = true
    }
  }, [activeApiProfile, activeTtsProfile])

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

  function applyGeneratedProject(result: Project, editedDuringRun: boolean) {
    const materialized = materializeLearningPointInventory(result)
    const generatedSelection = applyUsableCardSelection(materialized.project)
    const projectToShow = generatedSelection.project
    setProject(projectToShow)
    setSegmentFilter('all')
    setActiveSegmentId(projectToShow.segments[0]?.id ?? null)
    const usableCount = generatedSelection.selected
    const candidateOnlyCount = projectToShow.quality_funnel?.candidate_only_learning_point_count ?? 0
    const hiddenDuplicateCount = projectToShow.quality_funnel?.hidden_duplicate_learning_point_count ?? 0
    const hardBlockedCount = projectToShow.quality_funnel?.hard_blocked_learning_point_count ?? 0
    const autoAddedHint = materialized.added ? ` 已自动补成 ${materialized.added} 张草稿卡。` : ''
    const diagnosticCount = candidateOnlyCount + hiddenDuplicateCount + hardBlockedCount
    const inventoryHint = `更多学习点 ${diagnosticCount} 个，硬阻断 ${hardBlockedCount} 个。${autoAddedHint}`
    const isDocument = projectToShow.source_mode === 'document'
    const isReading = isDocument && projectToShow.document_study_mode === 'language_reading'
    const shortHint =
      usableCount < 5
        ? isReading
          ? '可用精读卡偏少，通常是语言点较弱、模型返回空或多数学习点被过滤；可以在“更多学习点”查看原因。'
          : isDocument
            ? '可用知识卡偏少，通常是文档分段较少、模型返回空或多数学习点被过滤；可以在“更多学习点”查看原因。'
            : '可用卡偏少，通常是字幕太短、重复太多、词伙评分不足或模型返回空；可以在“更多学习点”查看原因。'
        : ''
    const editedHint = editedDuringRun ? ' 生成期间你修改过设置；下一次生成会使用新配置。' : ''
    setStatus(
      (projectToShow.warning ||
        (projectToShow.source_mode === 'url'
          ? `URL 导入成功，已生成 ${usableCount} 张可用卡，默认全选。${inventoryHint}${shortHint}`
          : projectToShow.source_mode === 'document'
            ? `文档导入成功，已生成 ${usableCount} 张${isReading ? '精读' : '知识'}可用卡，默认全选。${inventoryHint}${shortHint}`
            : `已生成 ${usableCount} 张可用卡，默认全选。${inventoryHint}${shortHint}`)) + editedHint,
    )
  }

  function applyExportResult(result: ExportResult) {
    setLastExport(result)
    setAnkiVerifyResult(null)
    const mediaHint = result.media_summary
      ? `媒体约 ${result.media_summary.media_mb} MB，视频 ${result.media_summary.video_segments} 段，表达 TTS ${result.media_summary.phrase_tts_files} 条。`
      : ''
    setStatus(`导出完成：${result.cards} 张卡，${result.segments} 个片段。${mediaHint} ${result.apkg_path}`)
  }

  function applyVerifyResult(result: AnkiVerifyResult) {
    setAnkiVerifyResult(result)
    setStatus(result.message)
  }

  useEffect(() => {
    if (!isTauriRuntime()) return
    let stopListening: (() => void) | undefined
    let stopFinishedListening: (() => void) | undefined
    listen<WorkerProgress>('worker-progress', (event) => {
      const active = workerOperationRef.current
      if (event.payload.job_id && event.payload.job_id !== active.jobId) return
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
      const active = workerOperationRef.current
      const payload = event.payload
      if (payload.job_id !== active.jobId) return
      setBusy(false)
      setAnkiVerifying(false)
      if (payload.cancelled) {
        setWorkerProgress(null)
        setWorkerOperation({ status: 'idle' })
        setLastWorkerError(null)
        setStatus('任务已取消，可以继续调整后重新生成。')
        return
      }
      if (!payload.ok) {
        setWorkerOperation({ status: 'failed', command: payload.command, jobId: payload.job_id })
        setLastWorkerError(payload)
        const safeError = redactSensitiveText(payload.error || '任务失败。')
        const structuredDetails = [
          payload.error_code ? `错误码：${payload.error_code}` : '',
          payload.stage ? `阶段：${payload.stage}` : '',
          payload.fallbacks?.length ? `可尝试：${payload.fallbacks.join(' / ')}` : '',
        ]
          .filter(Boolean)
          .join('；')
        setStatus(`${safeError}${structuredDetails ? `\n${structuredDetails}` : ''}`)
        return
      }
      setWorkerProgress({
        job_id: payload.job_id,
        command: payload.command,
        stage: 'done',
        percent: 100,
        message: '任务完成。',
      })
      if (payload.command === 'generate') {
        applyGeneratedProject(payload.result as Project, requestEditedDuringRunRef.current)
        setActiveWorkspaceStage('review')
      } else if (payload.command === 'export') {
        applyExportResult(payload.result as ExportResult)
        setActiveWorkspaceStage('review')
      } else if (payload.command === 'verify_anki_import') {
        applyVerifyResult(payload.result as AnkiVerifyResult)
        setActiveWorkspaceStage('review')
      }
      setLastWorkerError(null)
      setWorkerOperation({ status: 'succeeded', command: payload.command, jobId: payload.job_id })
      setRequestEditedDuringRun(false)
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
    markRequestEditedIfRunning()
    if (touchesSourceMaterial(patch)) {
      setProject(null)
      setLastExport(null)
      setAnkiVerifyResult(null)
      setActiveSegmentId(null)
    }
    setRequest((current) => ({ ...current, ...patch }))
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
    const nextCardTypes: CardKind[] =
      mode === 'document'
        ? ['knowledge']
        : request.card_types.includes('knowledge')
          ? ['listening', 'phrase', 'cloze']
          : request.card_types

    setLastExport(null)
    setLastWorkerError(null)
    setAnkiVerifyResult(null)
    setProject(null)
    setActiveSegmentId(null)
    setWorkerProgress(null)
    const sourcePatch: Partial<GenerateRequest> = { source_mode: mode, card_types: nextCardTypes }
    if (mode === 'local') {
      sourcePatch.source_url = ''
      sourcePatch.document_path = ''
    } else if (mode === 'url') {
      sourcePatch.video_path = ''
      sourcePatch.subtitle_path = ''
      sourcePatch.document_path = ''
    } else {
      sourcePatch.source_url = ''
      sourcePatch.video_path = ''
      sourcePatch.subtitle_path = ''
    }
    patchRequest(sourcePatch)
    setStatus(
      mode === 'url'
        ? '已切换到视频链接模式，请粘贴 YouTube 或视频 URL。'
        : mode === 'document'
          ? '已切换到文档资料模式，请选择 TXT、Markdown、DOCX、EPUB 或 PDF。'
          : '已切换到本地视频模式，请选择视频；SRT 可留空并自动匹配或提取内嵌字幕。',
    )
  }

  const patchApi = (patch: Partial<ApiConfig>) => {
    markRequestEditedIfRunning()
    setRequest((current) => ({
      ...current,
      api_config: { ...current.api_config, ...patch },
    }))
    setApiProfileDirty(true)
    setApiTestResult(null)
  }

  const patchTts = (patch: Partial<TtsConfig>) => {
    markRequestEditedIfRunning()
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
    let apiKey = ''
    try {
      if (profile.auth === 'api_key' && profile.has_api_key) {
        apiKey = await loadSecret(profileSecretKey('api', profile.id))
      }
    } catch {
      setStatus('模型方案的 API Key 读取失败，请重新保存这个方案。')
    }
    markRequestEditedIfRunning()
    setRequest((current) => ({
      ...current,
      api_config: {
        ...current.api_config,
        provider: profile.provider,
        base_url: profile.base_url,
        model: profile.model,
        capabilities: profile.capabilities,
        api_key: apiKey,
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
      profile.auth === 'api_key' && !apiKey
        ? `已切换到模型方案：${profile.label}。这个方案没有保存 API Key。`
        : `已切换到模型方案：${profile.label}。`,
    )
  }

  const applySavedTtsProfile = async (profileId: string) => {
    const profile = savedTtsProfiles.find((item) => item.id === profileId)
    if (!profile) return
    let apiKey = ''
    try {
      if (profile.auth === 'api_key' && profile.has_api_key) {
        apiKey = await loadSecret(profileSecretKey('tts', profile.id))
      }
    } catch {
      setStatus('语音方案的 TTS API Key 读取失败，请重新保存这个方案。')
    }
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
      api_key: apiKey,
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
      profile.auth === 'api_key' && !apiKey
        ? `已切换到语音方案：${profile.label}。这个方案没有保存 TTS API Key。`
        : `已切换到语音方案：${profile.label}。`,
    )
  }

  const applyApiPreset = async (preset: ApiPreset) => {
    markRequestEditedIfRunning()
    const nextConfig = {
      provider: preset.provider,
      base_url: preset.base_url,
      model: preset.model,
      capabilities: preset.capabilities,
    }
    const profileId = apiProfileIdFromConfig(nextConfig)
    const savedProfile = savedApiProfiles.find((profile) => profile.id === profileId)
    const apiKey =
      savedProfile?.auth === 'api_key' && savedProfile.has_api_key
        ? await loadSecret(profileSecretKey('api', savedProfile.id)).catch(() => '')
        : ''
    setRequest((current) => ({
      ...current,
      api_config: {
        ...current.api_config,
        ...nextConfig,
        api_key: apiKey,
      },
    }))
    setApiTestResult(null)
    setApiProfileDirty(!savedProfile)
    setStatus(
      savedProfile
        ? `已套用已保存的 ${preset.label} 方案。`
        : preset.provider === 'gemini-vertex' || preset.provider === 'local'
          ? `已套用 ${preset.label} 预设，建议保存为我的模型方案。`
          : `已套用 ${preset.label} 预设，请填写 API Key 后保存方案并测试连接。`,
    )
  }

  const applyTtsPreset = async (preset: TtsPreset) => {
    const shouldReuseMainMimoKey =
      preset.provider === 'mimo' && isMimoApiConfig(request.api_config) && request.api_config.api_key.trim()
    const shouldReuseMainQwenKey =
      preset.provider === 'qwen' && isQwenApiConfig(request.api_config) && request.api_config.api_key.trim()
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
    const savedKey =
      savedProfile?.auth === 'api_key' && savedProfile.has_api_key
        ? await loadSecret(profileSecretKey('tts', savedProfile.id)).catch(() => '')
        : ''
    patchTts({
      ...nextConfig,
      api_key:
        savedKey ||
        (shouldReuseMainMimoKey || shouldReuseMainQwenKey || usesLocalVertexAuth
          ? ''
          : request.api_config.tts_config.api_key),
    })
    setTtsProfileDirty(!savedProfile)
    setStatus(
      savedProfile
        ? `已套用已保存的 ${preset.label} 语音方案。`
        : preset.provider === 'disabled'
          ? '已关闭 TTS，导出时只使用视频原声音频。'
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

  const selectPath = async (kind: 'video' | 'subtitle' | 'document') => {
    if (!isTauriRuntime()) {
      const prompt =
        kind === 'video'
          ? '输入视频绝对路径'
          : kind === 'subtitle'
            ? '输入 SRT 绝对路径'
            : '输入 TXT / Markdown / DOCX / EPUB / PDF 绝对路径'
      const value = window.prompt(prompt)
      if (value) {
        patchRequest(
          kind === 'video'
            ? { video_path: value }
            : kind === 'subtitle'
              ? { subtitle_path: value }
              : { document_path: value },
        )
      }
      return
    }

    const selected = await selectSingleFile(
      kind === 'video'
        ? [{ name: 'Video', extensions: ['mp4', 'mkv', 'mov', 'avi', 'webm'] }]
        : kind === 'subtitle'
          ? [{ name: 'Subtitle', extensions: ['srt'] }]
          : [{ name: 'Document', extensions: ['txt', 'md', 'markdown', 'pdf', 'docx', 'epub'] }],
    )

    if (typeof selected === 'string') {
      if (kind === 'video') {
        const patch: Partial<GenerateRequest> = { video_path: selected }
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
        patchRequest(kind === 'subtitle' ? { subtitle_path: selected } : { document_path: selected })
      }
    }
  }

  const checkEnv = async () => {
    setBusy(true)
    setWorkerProgress(null)
    setStatus('正在检查 Python、ffmpeg 和 genanki。')
    try {
      if (!isTauriRuntime()) {
        setEnvStatus({ python: 'browser-preview', ffmpeg: false, genanki: false, anki_installed: false, anki_connect: false })
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
    const api = normalizeApiConfigForRequest(request.api_config)
    if (
      api.base_url !== request.api_config.base_url ||
      api.model !== request.api_config.model ||
      api.provider !== request.api_config.provider
    ) {
      patchRequest({ api_config: api })
      setStatus('已自动修正模型 API 配置，再开始测试连接。')
    }
    const failBeforeRequest = (message: string, errorCode: string = 'MODEL_AUTH_FAILED') => {
      setApiTestResult({
        ok: false,
        provider: api.provider,
        model: api.model,
        message,
        error_code: errorCode,
        stage: 'model_api',
        retryable: false,
      })
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
          message: api.provider === 'local' ? '本地草稿模式可用。' : '浏览器预览模式不能真实测试 API，请运行桌面端。',
        }
        setApiTestResult(result)
        setStatus(result.message)
      } else {
        const result = await runWorker<ApiTestResult>('test_api', { api_config: api })
        setApiTestResult(result)
        setStatus(result.ok ? `API 测试通过：${result.message}` : `API 测试失败：${result.message}`)
      }
    } catch (error) {
      const message = redactSensitiveText(error)
      setApiTestResult({
        ok: false,
        provider: api.provider,
        model: api.model,
        message,
        error_code: 'MODEL_CONNECTION_FAILED',
        stage: 'model_api',
        retryable: true,
      })
      setStatus(`API 测试失败：${message}`)
    } finally {
      setApiTesting(false)
    }
  }

  const testTts = async () => {
    const currentTts = resolveTtsConfig(request.api_config.tts_config, request.api_config)
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
          api_config: request.api_config,
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

  const generate = async () => {
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
    if (generateRequest.source_mode === 'url' && !generateRequest.source_url.trim()) {
      setStatus('请先输入 YouTube / 视频 URL。')
      return
    }
    if (generateRequest.source_mode === 'document' && !generateRequest.document_path.trim()) {
      setStatus('请先选择 TXT、Markdown、DOCX、EPUB 或 PDF 文档。')
      return
    }
    if (generateRequest.source_mode === 'local' && !generateRequest.video_path) {
      setStatus('请先选择视频文件。SRT 可以手动选择，也可以放在视频同目录自动匹配。')
      return
    }
    const resolvedApi = resolveGenerateApiConfig(generateRequest.api_config, generateRequest.source_mode)
    if (isTauriRuntime()) {
      if (resolvedApi.error) {
        setStatus(`生成前配置检查失败：${resolvedApi.error}`)
        return
      }
      if (
        !resolvedApi.fallbackReason &&
        (resolvedApi.api.base_url !== request.api_config.base_url ||
          resolvedApi.api.model !== request.api_config.model ||
          resolvedApi.api.provider !== request.api_config.provider)
      ) {
        patchRequest({ api_config: resolvedApi.api })
      }
    }
    setLastExport(null)
    setAnkiVerifyResult(null)
    setActiveWorkspaceStage('generate')
    setWorkerProgress({ command: 'generate', stage: 'start', percent: 1, message: '准备开始生成。' })
    setBusy(true)
    setRequestEditedDuringRun(false)
    setStatus(
      generateRequest.source_mode === 'url'
        ? generateRequest.url_import_mode === 'subtitles'
          ? '正在下载 URL 字幕并跳过视频切片，然后生成卡片草稿。'
          : '正在下载 URL 视频和字幕，然后生成卡片草稿。'
        : generateRequest.source_mode === 'document'
          ? '正在解析文档、总结知识点并生成卡片草稿。'
          : resolvedApi.fallbackReason
            ? `模型 API 未就绪（${resolvedApi.fallbackReason}），本次先用本地规则解析字幕并生成可用卡。`
            : generateRequest.subtitle_path
              ? '正在解析字幕、筛选片段并生成卡片草稿。'
              : '正在自动匹配同目录字幕、筛选片段并生成卡片草稿。',
    )
    try {
      const requestSnapshot = JSON.parse(
        JSON.stringify({
          ...generateRequest,
          source_url: generateRequest.source_mode === 'url' ? generateRequest.source_url : '',
          video_path: generateRequest.source_mode === 'local' ? generateRequest.video_path : '',
          subtitle_path: generateRequest.source_mode === 'local' ? generateRequest.subtitle_path : '',
          document_path: generateRequest.source_mode === 'document' ? generateRequest.document_path : '',
          api_config: resolvedApi.api,
        }),
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
        setWorkerOperation({ status: 'running', command: 'generate', jobId: job.job_id })
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
        setStatus('当前任务已经结束。')
      }
    } catch (error) {
      setWorkerOperation((current) => ({ ...current, status: 'failed' }))
      setLastWorkerError(null)
      setStatus(redactSensitiveText(error))
    }
  }

  const exportApkg = async () => {
    if (workerBusy) {
      setStatus('已有任务正在运行，请先取消或等待完成。')
      return
    }
    if (!project) {
      setStatus('还没有可导出的卡片。')
      return
    }
    let projectForExport = project
    const materializedForExport = materializeLearningPointInventory(projectForExport)
    if (materializedForExport.added > 0) {
      projectForExport = materializedForExport.project
      setProject(projectForExport)
      setStatus(`已自动把 ${materializedForExport.added} 个合法学习点补成草稿卡，继续准备导出。`)
    }
    if (selectedCardCount === 0) {
      const usableSelection = applyUsableCardSelection(projectForExport)
      if (usableSelection.selected === 0) {
        setStatus('当前没有启用的卡片，也没有可自动启用的可用卡。请手动检查生成结果或重新生成。')
        return
      }
      projectForExport = usableSelection.project
      setProject(projectForExport)
      setStatus(`已自动启用 ${usableSelection.selected} 张可用卡，继续导出。`)
    }
    if (!isTauriRuntime()) {
      setStatus('浏览器预览模式不能导出 apkg，请运行 npm run tauri:dev。')
      return
    }
    const resolvedExportTtsConfig = resolveTtsConfig(request.api_config.tts_config, request.api_config)
    const exportTtsConfigError = validateTtsConfigForRequest(resolvedExportTtsConfig)
    if (exportTtsConfigError) {
      setStatus(`导出前 TTS 配置检查失败：${exportTtsConfigError}`)
      return
    }

    const outputDir = await selectDirectory()
    if (typeof outputDir !== 'string') {
      return
    }

    setActiveWorkspaceStage('review')
    setBusy(true)
    setLastWorkerError(null)
    setWorkerProgress({ command: 'export', stage: 'start', percent: 1, message: '准备开始导出。' })
    setStatus(
      projectForExport.source_mode === 'document'
        ? '正在打包文档知识卡 apkg。'
        : projectForExport.skip_video_slicing
          ? '正在打包字幕-only 卡包，并按需生成 TTS。'
          : '正在切视频、生成音频并打包 apkg。',
    )
    try {
      const exportPayload = {
        project: {
          ...projectForExport,
          template_id: request.template_id,
          api_config: {
            ...request.api_config,
            tts_config: resolvedExportTtsConfig,
          },
        },
        output_dir: outputDir,
      }
      const job = await startWorkerJob('export', exportPayload)
      setWorkerOperation({ status: 'running', command: 'export', jobId: job.job_id })
      setWorkerProgress({
        job_id: job.job_id,
        command: 'export',
        stage: 'start',
        percent: 1,
        message: '导出任务已在后台运行。你可以继续浏览当前草稿。',
      })
      setStatus('导出任务已在后台运行。导出期间不能再次生成或导出。')
    } catch (error) {
      setBusy(false)
      setWorkerOperation({ status: 'failed', command: 'export' })
      setLastWorkerError(null)
      setStatus(redactSensitiveText(error))
    }
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
    try {
      await openAnkiImportFile(lastExport.apkg_path)
      setStatus('已打开 Anki 导入窗口。')
    } catch (error) {
      setStatus(redactSensitiveText(error))
    }
  }

  const verifyAnkiImport = async () => {
    if (workerBusy) {
      setStatus('已有任务正在运行，请先取消或等待完成。')
      return
    }
    if (!lastExport?.apkg_path) return
    if (!isTauriRuntime()) {
      setStatus('浏览器预览模式不能连接 AnkiConnect。')
      return
    }
    setAnkiVerifying(true)
    setActiveWorkspaceStage('review')
    setLastWorkerError(null)
    setAnkiVerifyResult(null)
    setStatus('正在通过 AnkiConnect 核验导入后的卡片和媒体。')
    try {
      const job = await startWorkerJob('verify_anki_import', {
        export_result: lastExport,
      })
      setWorkerOperation({ status: 'running', command: 'verify_anki_import', jobId: job.job_id })
      setWorkerProgress({
        job_id: job.job_id,
        command: 'verify_anki_import',
        stage: 'start',
        percent: 1,
        message: 'Anki 媒体核验已在后台运行。',
      })
      setStatus('Anki 媒体核验已在后台运行。')
    } catch (error) {
      setAnkiVerifying(false)
      setWorkerOperation({ status: 'failed', command: 'verify_anki_import' })
      setLastWorkerError(null)
      setStatus(redactSensitiveText(error))
    }
  }

  const setCardsEnabled = (enabled: boolean, segmentId?: string) => {
    setLastExport(null)
    setAnkiVerifyResult(null)
    setProject((current) => {
      if (!current) return current
      const segments = current.segments.map((segment) =>
        segmentId && segment.id !== segmentId
          ? segment
          : {
              ...segment,
              cards: segment.cards.map((card) => ({ ...card, enabled })),
            },
      )
      const selected = segments.reduce(
        (total, segment) => total + segment.cards.filter((card) => card.enabled).length,
        0,
      )
      return {
        ...current,
        quality_funnel: current.quality_funnel
          ? { ...current.quality_funnel, selected_card_count: selected }
          : { selected_card_count: selected },
        segments,
      }
    })
  }

  const invertCardSelection = () => {
    setLastExport(null)
    setAnkiVerifyResult(null)
    setProject((current) => {
      if (!current) return current
      let selected = 0
      const segments = current.segments.map((segment) => ({
        ...segment,
        cards: segment.cards.map((card) => {
          const enabled = !card.enabled
          if (enabled) selected += 1
          return { ...card, enabled }
        }),
      }))
      return {
        ...current,
        quality_funnel: current.quality_funnel
          ? { ...current.quality_funnel, selected_card_count: selected }
          : { selected_card_count: selected },
        segments,
      }
    })
    setStatus('已反选当前生成的可用卡。')
  }

  const updateCard = (segmentId: string, cardId: string, patch: Partial<Card>) => {
    setLastExport(null)
    setAnkiVerifyResult(null)
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
    setLastExport(null)
    setAnkiVerifyResult(null)
    patchRequest({ template_id: templateId })
    setProject((current) => (current ? { ...current, template_id: templateId } : current))
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
      if (request.source_mode === 'local') {
        patchRequest({
          source_mode: 'local',
          source_url: '',
          document_path: '',
          skip_video_slicing: true,
        })
        setLastWorkerError(null)
        setStatus('已切换到本地字幕-only：下次生成仍使用当前本地视频/SRT，不会跳到视频链接。')
        return
      }
      patchRequest(
        request.source_mode === 'url'
          ? {
              source_mode: 'url',
              video_path: '',
              subtitle_path: '',
              document_path: '',
              url_import_mode: 'subtitles',
              skip_video_slicing: true,
              url_auto_subtitle_fallback: true,
            }
          : {
              skip_video_slicing: true,
            },
      )
      setLastWorkerError(null)
      setStatus('已切换到字幕-only：下次生成会跳过视频下载和切片，只用字幕继续制卡。')
      return
    }
    if (actionId === 'skip-video-slicing') {
      patchRequest({
        skip_video_slicing: true,
        url_import_mode: request.source_mode === 'url' ? 'subtitles' : request.url_import_mode,
      })
      setLastWorkerError(null)
      setStatus('已开启跳过视频切片：下次导出会保留卡片内容，避开 FFmpeg 切片失败。')
      return
    }
    if (actionId === 'retry') {
      if (lastWorkerError?.command === 'export') {
        void exportApkg()
      } else if (lastWorkerError?.command === 'verify_anki_import') {
        void verifyAnkiImport()
      } else {
        void generate()
      }
    }
  }

  const activeSegment = project?.segments.find((segment) => segment.id === activeSegmentId)
  const activeSegmentVideoSrc = activeSegment && project?.video_path ? toAssetUrl(project.video_path) : ''

  return {
    activeWorkspaceStage,
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
    isDesktopRuntime: isTauriRuntime(),
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
    activeApiProfileId,
    activeTtsProfileId,
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
