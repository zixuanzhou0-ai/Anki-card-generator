import { useEffect, useMemo, useRef, useState } from 'react'
import type { MouseEvent } from 'react'
import { listen } from '@tauri-apps/api/event'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import {
  Boxes,
  CheckCircle2,
  CircleAlert,
  Download,
  FileText,
  Film,
  FolderOpen,
  KeyRound,
  Languages,
  Layers3,
  Link2,
  Loader2,
  MessageSquareText,
  Minus,
  PlugZap,
  Settings2,
  Square,
  Subtitles,
  Wand2,
  X,
} from 'lucide-react'

import type {
  AnkiVerifyResult,
  ApiConfig,
  ApiPreset,
  ApiTestResult,
  Card,
  CardKind,
  ContentToggles,
  EnvStatus,
  ExportResult,
  GenerateRequest,
  InspectorState,
  Level,
  Project,
  Provider,
  QualityFunnel,
  ResizeDirection,
  ResponsiveMode,
  SecretPrefs,
  SegmentFilter,
  SettingsTab,
  SourceMode,
  TemplateId,
  TtsConfig,
  TtsPreset,
  TtsProvider,
  TtsTestResult,
  WorkerFinishedEvent,
  WorkerOperation,
  WorkerProgress,
} from './domain/types'
import { createDemoProject } from './domain/demoProject'
import {
  advancedApiPresets,
  advancedTtsPresets,
  capabilityHelp,
  capabilityLabels,
  cardOptions,
  contentOptions,
  defaultCollectionLevels,
  featuredApiPresets,
  featuredTtsPresets,
  levelOrder,
  levels,
  MIMO_OPENAI_BASE_URL,
  MIMO_TOKEN_PLAN_SGP_BASE_URL,
  mimoTextModels,
  mimoTtsModels,
  mimoTtsVoices,
  normalizeCollectionLevels,
  PROJECT_STORAGE_KEY,
  REQUEST_STORAGE_KEY,
  SECRET_PREFS_STORAGE_KEY,
  templateOptions,
} from './domain/options'
import {
  applyCardSelection,
  badgeText,
  isRecommendedCardForExport,
  segmentMatchesFilter,
} from './domain/quality'
import {
  countSelectedCards,
  getQualityCounts,
  getQualityDiagnostics,
  getQualityFunnel,
  getSegmentReviewCounts,
} from './domain/projectMetrics'
import type { WorkerErrorActionId } from './domain/workerErrors'
import { getWorkerErrorActions } from './domain/workerErrors'
import { ReadinessPanel } from './features/generation/ReadinessPanel'
import { StatusPanel } from './features/generation/StatusPanel'
import { WorkerProgressPanel } from './features/generation/WorkerProgressPanel'
import { EmptyWorkbench } from './features/review/EmptyWorkbench'
import { ExportResultPanel } from './features/review/ExportResultPanel'
import { ReviewSummaryPanel } from './features/review/ReviewSummaryPanel'
import { SegmentDetail } from './features/review/SegmentDetail'
import { SegmentList } from './features/review/SegmentList'
import { ConnectionTestCard } from './features/settings/ConnectionTestCard'
import { EnvSettingsPanel } from './features/settings/EnvSettingsPanel'
import {
  isMimoApiConfig,
  isMimoTokenPlanBase,
  isMimoTokenPlanKey,
  resolveTtsConfig,
  validateApiConfigForRequest,
  validateTtsConfigForRequest,
} from './services/apiConfig'
import { loadSavedProject, loadSavedRequest, loadSecretPrefs, stripRequestSecrets } from './services/projectStorage'
import { cancelWorkerJob, deleteSecret, loadSecret, runWorker, saveSecret, startWorkerJob } from './services/tauriWorker'
import { isTauriRuntime } from './services/runtime'
import { openAnkiImport as openAnkiImportFile, revealPath, selectDirectory, selectSingleFile, toAssetUrl } from './services/nativeShell'
import { redactSensitiveText } from './services/redaction'
import {
  runWindowAction as runNativeWindowAction,
  startWindowDrag as startNativeWindowDrag,
  startWindowResize as startNativeWindowResize,
} from './services/windowChrome'
function App() {
  const [request, setRequest] = useState<GenerateRequest>(() => loadSavedRequest())
  const [project, setProject] = useState<Project | null>(() => loadSavedProject())
  const [envStatus, setEnvStatus] = useState<EnvStatus | null>(null)
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
  const [secretPrefs, setSecretPrefs] = useState<SecretPrefs>(() => loadSecretPrefs())
  const [segmentFilter, setSegmentFilter] = useState<SegmentFilter>('all')
  const [responsiveMode, setResponsiveMode] = useState<ResponsiveMode>('wide')
  const [inspectorState, setInspectorState] = useState<InspectorState>('open')
  const prefersReducedMotion = useReducedMotion()
  const previewPanelRef = useRef<HTMLElement | null>(null)
  const settingsDialogRef = useRef<HTMLElement | null>(null)
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
  const sourceReady =
    request.source_mode === 'url'
      ? Boolean(request.source_url.trim())
      : request.source_mode === 'document'
        ? Boolean(request.document_path?.trim())
        : Boolean(request.video_path && request.subtitle_path)
  const apiReady = request.api_config.provider === 'local' || Boolean(apiTestResult?.ok)
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
            : '待选择视频和字幕',
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
  const apiTestTitle = apiTesting
    ? '正在测试连接'
    : apiTestResult
      ? apiTestResult.ok
        ? '连接成功'
        : '连接失败'
      : '尚未测试'
  const apiTestMessage = apiTesting
    ? '正在向当前接口发送一条短测试消息，通常几秒内会返回。'
    : apiTestResult?.message ?? '换 Provider、Base URL、模型名或 API Key 后，都建议点一次测试连接。'
  const apiTestMeta = apiTestResult
    ? `${apiTestResult.provider} · ${apiTestResult.model || '未填模型'}${
        apiTestResult.latency_ms ? ` · ${apiTestResult.latency_ms} ms` : ''
      }`
    : `${request.api_config.provider} · ${request.api_config.model || '未填模型'}`
  const tts = request.api_config.tts_config
  const ttsTestTone = ttsTesting ? 'testing' : ttsTestResult ? (ttsTestResult.ok ? 'ok' : 'warn') : 'idle'
  const ttsTestTitle = ttsTesting
    ? '正在测试 TTS'
    : ttsTestResult
      ? ttsTestResult.ok
        ? 'TTS 连接成功'
        : 'TTS 连接失败'
      : tts.enabled
        ? 'TTS 已开启，尚未测试'
        : 'TTS 已关闭'
  const ttsTestMessage = ttsTesting
    ? '正在生成一小段测试音频，用来确认 Key、语音和接口可用。'
    : ttsTestResult?.message ??
      (tts.enabled
        ? 'MIMO / Grok / Gemini / Speech API 都在这里单独测试，和上面的文本模型测试互不影响。'
        : '关闭时不会生成 AI 朗读，只会把视频原声音频放进卡片。')
  const ttsTestMeta = ttsTestResult
    ? `${ttsTestResult.provider} · ${ttsTestResult.model || '无模型名'} · ${ttsTestResult.voice || '无 voice'}${
        ttsTestResult.latency_ms ? ` · ${ttsTestResult.latency_ms} ms` : ''
      }${ttsTestResult.bytes ? ` · ${ttsTestResult.bytes} bytes` : ''}`
    : `${tts.provider} · ${tts.model || '无模型名'} · ${tts.voice || '无 voice'}`
  const workerBusy = workerOperation.status === 'running' || workerOperation.status === 'cancelling'
  const appBusy = busy || workerBusy
  const isCancelling = workerOperation.status === 'cancelling'
  const inspectorSheetOpen = responsiveMode === 'compact' && inspectorState === 'sheet'
  const inspectorActionLabel =
    responsiveMode === 'compact'
      ? inspectorSheetOpen
        ? '关闭面板'
        : '素材面板'
      : inspectorState === 'open'
        ? '收起面板'
        : '打开面板'
  const motionDuration = prefersReducedMotion ? 0 : 0.2
  const statusTone = appBusy || workerProgress
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
    if (responsiveMode === 'compact' && inspectorState === 'open') {
      setInspectorState('collapsed')
    } else if (responsiveMode !== 'compact' && inspectorState === 'sheet') {
      setInspectorState('open')
    }
  }, [responsiveMode, inspectorState])

  useEffect(() => {
    window.localStorage.setItem(REQUEST_STORAGE_KEY, JSON.stringify(stripRequestSecrets(request)))
  }, [request])

  useEffect(() => {
    window.localStorage.setItem(SECRET_PREFS_STORAGE_KEY, JSON.stringify(secretPrefs))
  }, [secretPrefs])

  useEffect(() => {
    if (!isTauriRuntime()) return
    let cancelled = false
    const restore = async () => {
      try {
        const [modelKey, ttsKey] = await Promise.all([
          secretPrefs.rememberModelKey ? loadSecret('model_api_key') : Promise.resolve(''),
          secretPrefs.rememberTtsKey ? loadSecret('tts_api_key') : Promise.resolve(''),
        ])
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
  }, [secretPrefs.rememberModelKey, secretPrefs.rememberTtsKey])

  useEffect(() => {
    if (!isTauriRuntime()) return
    if (secretPrefs.rememberModelKey && request.api_config.api_key.trim()) {
      saveSecret('model_api_key', request.api_config.api_key.trim()).catch(() => {
        setStatus('模型 API Key 保存到系统凭据失败。')
      })
    }
  }, [secretPrefs.rememberModelKey, request.api_config.api_key])

  useEffect(() => {
    if (!isTauriRuntime()) return
    if (secretPrefs.rememberTtsKey && request.api_config.tts_config.api_key.trim()) {
      saveSecret('tts_api_key', request.api_config.tts_config.api_key.trim()).catch(() => {
        setStatus('TTS API Key 保存到系统凭据失败。')
      })
    }
  }, [secretPrefs.rememberTtsKey, request.api_config.tts_config.api_key])

  useEffect(() => {
    if (typeof window === 'undefined') return
    if (project) {
      window.localStorage.setItem(PROJECT_STORAGE_KEY, JSON.stringify(project))
    } else {
      window.localStorage.removeItem(PROJECT_STORAGE_KEY)
    }
  }, [project])

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
    setProject(result)
    setSegmentFilter('all')
    setActiveSegmentId(result.segments[0]?.id ?? null)
    const recommendedCount = result.segments.reduce(
      (total, segment) => total + segment.cards.filter((card) => isRecommendedCardForExport(segment, card)).length,
      0,
    )
    const shortHint =
      recommendedCount < 5
        ? '推荐卡偏少，通常是字幕太短、重复太多、词伙评分不足或模型返回空；可以在质量仪表盘查看原因。'
        : ''
    const editedHint = editedDuringRun ? ' 生成期间你修改过设置；下一次生成会使用新配置。' : ''
    setStatus(
      (result.warning ||
        (result.source_mode === 'url'
          ? `URL 导入成功，已生成 ${result.segments.length} 个片段组，推荐 ${recommendedCount} 张。${shortHint}`
          : result.source_mode === 'document'
            ? `文档导入成功，已生成 ${result.segments.length} 个知识点组。`
            : `已生成 ${result.segments.length} 个片段组，推荐 ${recommendedCount} 张。${shortHint}`)) + editedHint,
    )
  }

  function applyExportResult(result: ExportResult) {
    setLastExport(result)
    setAnkiVerifyResult(null)
    const mediaHint = result.media_summary
      ? `媒体约 ${result.media_summary.media_mb} MB，视频 ${result.media_summary.video_segments} 段，词伙 TTS ${result.media_summary.phrase_tts_files} 条。`
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
      setWorkerProgress({ job_id: payload.job_id, command: payload.command, stage: 'done', percent: 100, message: '任务完成。' })
      if (payload.command === 'generate') {
        applyGeneratedProject(payload.result as Project, requestEditedDuringRunRef.current)
      } else if (payload.command === 'export') {
        applyExportResult(payload.result as ExportResult)
      } else if (payload.command === 'verify_anki_import') {
        applyVerifyResult(payload.result as AnkiVerifyResult)
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
    setInspectorState((current) => {
      if (responsiveMode === 'compact') return current === 'sheet' ? 'collapsed' : 'sheet'
      return current === 'open' ? 'collapsed' : 'open'
    })
  }

  const patchRequest = (patch: Partial<GenerateRequest>) => {
    markRequestEditedIfRunning()
    setRequest((current) => ({ ...current, ...patch }))
  }

  const selectCurrentLevel = (level: Level) => {
    patchRequest({
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
    patchRequest({ source_mode: mode, card_types: nextCardTypes })
    setStatus(
      mode === 'url'
        ? '已切换到视频链接模式，请粘贴 YouTube 或视频 URL。'
        : mode === 'document'
          ? '已切换到文档资料模式，请选择 TXT、Markdown、DOCX、EPUB 或 PDF。'
          : '已切换到本地视频模式，请选择视频和 SRT 字幕。',
    )
  }

  const patchApi = (patch: Partial<ApiConfig>) => {
    markRequestEditedIfRunning()
    setRequest((current) => ({
      ...current,
      api_config: { ...current.api_config, ...patch },
    }))
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
    setTtsTestResult(null)
  }

  const toggleRememberSecret = (kind: 'model' | 'tts') => {
    const prefKey = kind === 'model' ? 'rememberModelKey' : 'rememberTtsKey'
    const secretKey = kind === 'model' ? 'model_api_key' : 'tts_api_key'
    setSecretPrefs((current) => {
      const enabled = !current[prefKey]
      if (!enabled) {
        deleteSecret(secretKey).catch(() => {
          setStatus('系统凭据删除失败，请稍后重试。')
        })
      }
      if (enabled) {
        const value = kind === 'model' ? request.api_config.api_key.trim() : request.api_config.tts_config.api_key.trim()
        if (value) {
          saveSecret(secretKey, value).catch(() => {
            setStatus('系统凭据保存失败，请确认当前桌面端有凭据访问权限。')
          })
        }
      }
      return { ...current, [prefKey]: enabled }
    })
  }

  const applyApiPreset = (preset: ApiPreset) => {
    markRequestEditedIfRunning()
    setRequest((current) => ({
      ...current,
      api_config: {
        ...current.api_config,
        provider: preset.provider,
        base_url: preset.base_url,
        model: preset.model,
        capabilities: preset.capabilities,
      },
    }))
    setApiTestResult(null)
    setStatus(`已套用 ${preset.label} 预设，请填写 API Key 后测试连接。`)
  }

  const applyTtsPreset = (preset: TtsPreset) => {
    const shouldReuseMainMimoKey = preset.provider === 'mimo' && isMimoApiConfig(request.api_config) && request.api_config.api_key.trim()
    patchTts({
      enabled: preset.provider !== 'disabled',
      provider: preset.provider,
      base_url: preset.base_url,
      model: preset.model,
      voice: preset.voice,
      api_key: shouldReuseMainMimoKey ? '' : request.api_config.tts_config.api_key,
    })
    setStatus(
      preset.provider === 'disabled'
        ? '已关闭 TTS，导出时只使用视频原声音频。'
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

  const toggleCardType = (type: CardKind) => {
    markRequestEditedIfRunning()
    setRequest((current) => {
      const exists = current.card_types.includes(type)
      const next = exists
        ? current.card_types.filter((item) => item !== type)
        : [...current.card_types, type]
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
      patchRequest(
        kind === 'video'
          ? { video_path: selected }
          : kind === 'subtitle'
            ? { subtitle_path: selected }
            : { document_path: selected },
      )
    }
  }

  const checkEnv = async () => {
    setBusy(true)
    setWorkerProgress(null)
    setStatus('正在检查 Python、ffmpeg 和 genanki。')
    try {
      if (!isTauriRuntime()) {
        setEnvStatus({ python: 'browser-preview', ffmpeg: false, genanki: false })
        setStatus('当前是浏览器预览模式，真实导出请运行 Tauri 桌面端。')
      } else {
        const result = await runWorker<EnvStatus>('check_env', {})
        setEnvStatus(result)
        setStatus(result.ffmpeg && result.genanki ? '环境检查通过。' : '环境缺少依赖，请查看状态卡。')
      }
    } catch (error) {
      setStatus(redactSensitiveText(error))
    } finally {
      setBusy(false)
    }
  }

  const testApi = async () => {
    const api = request.api_config
    const failBeforeRequest = (message: string) => {
      setApiTestResult({
        ok: false,
        provider: api.provider,
        model: api.model,
        message,
      })
      setStatus(`API 测试失败：${message}`)
    }

    const configError = validateApiConfigForRequest(api)
    if (configError) {
      failBeforeRequest(configError)
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
              ? '本地草稿模式可用。'
              : '浏览器预览模式不能真实测试 API，请运行桌面端。',
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
      })
      setStatus(`API 测试失败：${message}`)
    } finally {
      setApiTesting(false)
    }
  }

  const testTts = async () => {
    const currentTts = resolveTtsConfig(request.api_config.tts_config, request.api_config)
    const failBeforeRequest = (message: string) => {
      setTtsTestResult({
        ok: false,
        provider: currentTts.provider,
        model: currentTts.model,
        voice: currentTts.voice,
        message,
      })
      setStatus(`TTS 测试失败：${message}`)
    }

    if (!currentTts.enabled || currentTts.provider === 'disabled') {
      failBeforeRequest('TTS 当前是关闭状态。')
      return
    }
    const ttsConfigError = validateTtsConfigForRequest(currentTts)
    if (ttsConfigError) {
      failBeforeRequest(ttsConfigError)
      return
    }
    if (currentTts.provider === 'grok' && !currentTts.voice.trim()) {
      failBeforeRequest('Grok TTS 需要填写 voice_id，例如 eve、ara、leo、rex、sal。')
      return
    }
    if (currentTts.provider === 'gemini' && !currentTts.model.trim()) {
      failBeforeRequest('Gemini TTS 需要填写 TTS 模型名。')
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
      })
      setStatus(`TTS 测试失败：${message}`)
    } finally {
      setTtsTesting(false)
    }
  }

  const generate = async () => {
    if (workerBusy) {
      setStatus('已有任务正在运行，请先取消或等待完成。')
      return
    }
    if (request.source_mode === 'url' && !request.source_url.trim()) {
      setStatus('请先输入 YouTube / 视频 URL。')
      return
    }
    if (request.source_mode === 'document' && !request.document_path.trim()) {
      setStatus('请先选择 TXT、Markdown、DOCX、EPUB 或 PDF 文档。')
      return
    }
    if (request.source_mode === 'local' && (!request.video_path || !request.subtitle_path)) {
      setStatus('请先选择视频和 SRT 字幕。')
      return
    }
    if (isTauriRuntime()) {
      const apiConfigError = validateApiConfigForRequest(request.api_config)
      if (apiConfigError) {
        setStatus(`生成前配置检查失败：${apiConfigError}`)
        return
      }
      const ttsConfigError = validateTtsConfigForRequest(
        resolveTtsConfig(request.api_config.tts_config, request.api_config),
      )
      if (ttsConfigError) {
        setStatus(`生成前 TTS 配置检查失败：${ttsConfigError}`)
        return
      }
    }
    setLastExport(null)
    setAnkiVerifyResult(null)
    setWorkerProgress({ command: 'generate', stage: 'start', percent: 1, message: '准备开始生成。' })
    setBusy(true)
    setRequestEditedDuringRun(false)
    setStatus(
      request.source_mode === 'url'
        ? request.url_import_mode === 'subtitles'
          ? '正在下载 URL 字幕并跳过视频切片，然后生成卡片草稿。'
          : '正在下载 URL 视频和字幕，然后生成卡片草稿。'
        : request.source_mode === 'document'
          ? '正在解析文档、总结知识点并生成卡片草稿。'
          : '正在解析字幕、筛选片段并生成卡片草稿。',
    )
    try {
      const requestSnapshot = JSON.parse(JSON.stringify(request)) as GenerateRequest
      if (!isTauriRuntime()) {
        const demo = createDemoProject(requestSnapshot)
        setProject(demo)
        setSegmentFilter('all')
        setActiveSegmentId(demo.segments[0]?.id ?? null)
        setStatus(
          request.source_mode === 'url'
            ? '已生成浏览器演示卡片。URL 下载需要在 Tauri 桌面端运行。'
            : request.source_mode === 'document'
              ? '已生成浏览器演示文档卡。真实文档解析和 apkg 导出请用 Tauri 桌面端。'
              : '已生成浏览器演示卡片。真实视频切片和 apkg 导出请用 Tauri 桌面端。',
        )
        setWorkerProgress({ command: 'generate', stage: 'done', percent: 100, message: '演示卡片生成完成。' })
        setWorkerOperation({ status: 'succeeded', command: 'generate' })
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
    if (selectedCardCount === 0) {
      const recommendedSelection = applyCardSelection(project, 'recommended')
      if (recommendedSelection.selected === 0) {
        setStatus('当前没有启用的卡片，也没有可自动启用的推荐卡。请改用“推荐+待审”或手动勾选至少一张。')
        return
      }
      projectForExport = recommendedSelection.project
      setProject(projectForExport)
      setStatus(`已自动启用 ${recommendedSelection.selected} 张推荐卡，继续导出。`)
    }
    if (!isTauriRuntime()) {
      setStatus('浏览器预览模式不能导出 apkg，请运行 npm run tauri:dev。')
      return
    }
    const exportTtsConfigError = validateTtsConfigForRequest(
      resolveTtsConfig(request.api_config.tts_config, request.api_config),
    )
    if (exportTtsConfigError) {
      setStatus(`导出前 TTS 配置检查失败：${exportTtsConfigError}`)
      return
    }

    const outputDir = await selectDirectory()
    if (typeof outputDir !== 'string') {
      return
    }

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
        project: { ...projectForExport, template_id: request.template_id, api_config: request.api_config },
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
      return {
        ...current,
        segments: current.segments.map((segment) =>
          segmentId && segment.id !== segmentId
            ? segment
            : {
                ...segment,
                cards: segment.cards.map((card) => ({ ...card, enabled })),
              },
        ),
      }
    })
  }

  const selectCardsByQuality = (mode: 'recommended' | 'reviewable') => {
    setLastExport(null)
    setAnkiVerifyResult(null)
    if (!project) return
    const result = applyCardSelection(project, mode)
    setProject(result.project)
    setStatus(
      result.selected === 0
        ? mode === 'recommended'
          ? '当前没有推荐卡；可以切到“推荐+待审”，或查看质量漏斗了解为什么推荐数量少。'
          : '当前没有可导出的推荐或待审卡；请手动勾选，或降低筛选强度后重新生成。'
        : mode === 'recommended'
          ? `已只保留推荐卡：${result.selected} 张。待审和建议删除已关闭。`
          : `已保留推荐卡和待审卡：${result.selected} 张。建议删除已关闭。`,
    )
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
      patchRequest({
        source_mode: 'url',
        url_import_mode: 'subtitles',
        skip_video_slicing: true,
        url_auto_subtitle_fallback: true,
      })
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

  return (
    <div className="app-shell">
      <header
        className="topbar"
        onMouseDown={startWindowDrag}
        onDoubleClick={handleTopbarDoubleClick}
      >
        <div className="brand-lockup">
          <div className="app-mark" aria-hidden="true">
            <img src="/app-icon.png" alt="" />
          </div>
          <div>
            <p className="eyebrow">Anki Card Generator V1</p>
            <h1>Anki 卡片生成器</h1>
          </div>
        </div>
        <div className="window-drag-region" />
        <div className="topbar-actions">
          {project ? (
            <div className="mini-summary" aria-label="项目摘要">
              <span>{`${project.segments.length} 个片段`}</span>
              <span>{badgeText(selectedCardCount)}</span>
              <span>{`${qualityCounts.review} 张待审`}</span>
              <span>{activeTemplate?.label ?? '沉浸视频'}</span>
            </div>
          ) : null}
          <div className={`status-chip ${statusTone}`} title={status} role="status" aria-live="polite" aria-atomic="true">
            <CheckCircle2 size={16} />
            <span>{status}</span>
          </div>
          <button
            className="ghost-button inspector-toggle"
            type="button"
            onClick={toggleInspector}
            aria-pressed={inspectorState === 'open' || inspectorSheetOpen}
            aria-expanded={inspectorState === 'open' || inspectorSheetOpen}
          >
            <Layers3 size={18} />
            {inspectorActionLabel}
          </button>
          <button className="ghost-button" type="button" onClick={() => setSettingsOpen(true)}>
            <Settings2 size={18} />
            设置
          </button>
          {workerBusy ? (
            <button className="ghost-button cancel-button" type="button" onClick={cancelCurrentWorker} disabled={isCancelling}>
              {isCancelling ? <Loader2 className="spin" size={18} /> : <X size={18} />}
              {isCancelling ? '取消中' : '取消任务'}
            </button>
          ) : null}
          {project && selectedCardCount > 0 && !workerBusy ? (
            <button className="ghost-button command-export" type="button" onClick={exportApkg} disabled={appBusy}>
              <Download size={18} />
              导出
            </button>
          ) : null}
          <button className="primary-button" type="button" onClick={generate} disabled={appBusy}>
            {appBusy ? <Loader2 className="spin" size={18} /> : <Wand2 size={18} />}
            {project ? '重新生成' : '生成卡片'}
          </button>
        </div>
        <div className="window-controls" aria-label="窗口控制">
          <button type="button" onClick={() => runWindowAction('minimize')} aria-label="最小化">
            <Minus size={17} />
          </button>
          <button type="button" onClick={() => runWindowAction('toggleMaximize')} aria-label="最大化">
            <Square size={15} />
          </button>
          <button className="close-window" type="button" onClick={() => runWindowAction('close')} aria-label="关闭">
            <X size={18} />
          </button>
        </div>
      </header>

      <main className="workspace">
        <section
          className={`desktop-workspace inspector-${inspectorState}`}
          data-responsive-mode={responsiveMode}
        >
          {inspectorSheetOpen ? (
            <button
              className="inspector-backdrop"
              type="button"
              aria-label="关闭素材面板遮罩"
              onClick={() => setInspectorState('collapsed')}
            />
          ) : null}
          <aside className={`control-column ${inspectorSheetOpen ? 'sheet-open' : ''}`} aria-label="素材和生成设置">
          <div className="compact-inspector-head">
            <div>
              <span>素材设置</span>
              <strong>生成前配置</strong>
            </div>
            <button type="button" className="icon-button" onClick={() => setInspectorState('collapsed')} aria-label="关闭素材设置">
              <X size={18} />
            </button>
          </div>
          <ReadinessPanel items={readiness} />

          {workerProgress ? <WorkerProgressPanel progress={workerProgress} /> : null}

          <StatusPanel
            appBusy={appBusy}
            requestEditedDuringRun={requestEditedDuringRun}
            status={status}
            statusTone={statusTone}
            workerBusy={workerBusy}
            workerErrorActions={workerErrorActions}
            onWorkerErrorAction={handleWorkerErrorAction}
          />

          <section className="setup-grid">
            <div className="panel source-panel">
              <div className="panel-heading">
                <FolderOpen size={20} />
                <h3>素材</h3>
              </div>
              <div className="source-switch" aria-label="素材来源">
                <button
                  type="button"
                  className={request.source_mode === 'local' ? 'selected' : ''}
                  aria-pressed={request.source_mode === 'local'}
                  onClick={() => selectSourceMode('local')}
                >
                  <Film size={18} />
                  <span>本地视频</span>
                  <small>视频 + SRT</small>
                </button>
                <button
                  type="button"
                  className={request.source_mode === 'url' ? 'selected' : ''}
                  aria-pressed={request.source_mode === 'url'}
                  onClick={() => selectSourceMode('url')}
                >
                  <Link2 size={18} />
                  <span>视频链接</span>
                  <small>YouTube / URL</small>
                </button>
                <button
                  type="button"
                  className={request.source_mode === 'document' ? 'selected' : ''}
                  aria-pressed={request.source_mode === 'document'}
                  onClick={() => selectSourceMode('document')}
                >
                  <FileText size={18} />
                  <span>文档资料</span>
                  <small>PDF / Word / EPUB</small>
                </button>
              </div>
              <details className="compact-details source-input-details" open>
                <summary>
                  <span>输入内容</span>
                  <strong>
                    {request.source_mode === 'url'
                      ? '视频链接'
                      : request.source_mode === 'document'
                        ? '文档资料'
                        : '本地视频'}
                  </strong>
                </summary>
                <label className="field project-title-field">
                  <span>项目标题</span>
                  <input
                    value={request.title}
                    onChange={(event) => patchRequest({ title: event.target.value })}
                    placeholder="例如 Friends S01E01"
                  />
                </label>
                {request.source_mode === 'url' ? (
                  <label className="field">
                    <span>YouTube / 视频 URL</span>
                    <input
                      value={request.source_url}
                      onChange={(event) => patchRequest({ source_url: event.target.value })}
                      placeholder="https://www.youtube.com/watch?v=..."
                    />
                    <small>
                      失败时可切到字幕-only 或手动上传 SRT 继续制卡。
                    </small>
                  </label>
                ) : request.source_mode === 'document' ? (
                  <label className="field file-field">
                    <span>文档资料</span>
                    <div>
                      <input
                        value={request.document_path}
                        onChange={(event) => patchRequest({ document_path: event.target.value })}
                        placeholder="选择文档资料"
                      />
                      <button type="button" onClick={() => selectPath('document')} aria-label="选择文档资料">
                        <FileText size={18} />
                      </button>
                    </div>
                    <small>支持 TXT、Markdown、DOCX、EPUB、PDF。扫描版 PDF 需要后续 OCR。</small>
                  </label>
                ) : (
                  <>
                    <label className="field file-field">
                      <span>视频文件</span>
                      <div>
                        <input
                          value={request.video_path}
                          onChange={(event) => patchRequest({ video_path: event.target.value })}
                          placeholder="选择本地视频"
                        />
                        <button type="button" onClick={() => selectPath('video')} aria-label="选择视频文件">
                          <Film size={18} />
                        </button>
                      </div>
                    </label>
                    <label className="field file-field">
                      <span>SRT 字幕</span>
                      <div>
                        <input
                          value={request.subtitle_path}
                          onChange={(event) => patchRequest({ subtitle_path: event.target.value })}
                          placeholder="选择 SRT 字幕"
                        />
                        <button type="button" onClick={() => selectPath('subtitle')} aria-label="选择字幕文件">
                          <Subtitles size={18} />
                        </button>
                      </div>
                    </label>
                  </>
                )}
              </details>
              {request.source_mode === 'url' ? (
                <details className="compact-details inspector-fold url-options-details">
                  <summary>
                    <span>下载和 fallback</span>
                    <strong>{request.url_import_mode === 'subtitles' ? '字幕-only' : '视频+字幕'}</strong>
                  </summary>
                  <div className="url-fallback-options" aria-label="URL 导入 fallback">
                    <div className="segmented compact-segmented">
                      <button
                        type="button"
                        className={request.url_import_mode === 'video' ? 'selected' : ''}
                        onClick={() => patchRequest({ url_import_mode: 'video', skip_video_slicing: false })}
                      >
                        下载视频+字幕
                      </button>
                      <button
                        type="button"
                        className={request.url_import_mode === 'subtitles' ? 'selected' : ''}
                        onClick={() => patchRequest({ url_import_mode: 'subtitles', skip_video_slicing: true })}
                      >
                        只用字幕生成
                      </button>
                    </div>
                    <label className="toggle">
                      <input
                        type="checkbox"
                        checked={request.url_auto_subtitle_fallback}
                        onChange={() =>
                          patchRequest({ url_auto_subtitle_fallback: !request.url_auto_subtitle_fallback })
                        }
                      />
                      <span>视频下载失败时自动 fallback 到字幕-only</span>
                    </label>
                    <label className="toggle">
                      <input
                        type="checkbox"
                        checked={request.skip_video_slicing}
                        onChange={() => {
                          const next = !request.skip_video_slicing
                          patchRequest({
                            skip_video_slicing: next,
                            url_import_mode: next ? 'subtitles' : request.url_import_mode,
                          })
                        }}
                      />
                      <span>导出时跳过视频切片，只保留字幕和 TTS</span>
                    </label>
                  </div>
                </details>
              ) : null}
            </div>

            <div className="panel settings-panel">
              <div className="panel-heading">
                <Languages size={20} />
                <h3>学习设置</h3>
              </div>
              <div className="two-fields">
                <label className="field">
                  <span>学习语言</span>
                  <select
                    value={request.language}
                    onChange={(event) => patchRequest({ language: event.target.value })}
                  >
                    <option>English</option>
                    <option>Français</option>
                    <option>Español</option>
                    <option>日本語</option>
                  </select>
                </label>
                <label className="field">
                  <span>最大片段数</span>
                  <div className="segment-budget-input">
                    <input
                      type="number"
                      min={3}
                      max={120}
                      value={request.max_segments > 0 ? request.max_segments : ''}
                      placeholder="自动"
                      disabled={request.max_segments <= 0}
                      onChange={(event) => patchRequest({ max_segments: Number(event.target.value) })}
                    />
                    <button
                      type="button"
                      className={request.max_segments <= 0 ? 'selected' : ''}
                      onClick={() => patchRequest({ max_segments: request.max_segments <= 0 ? 35 : 0 })}
                    >
                      自动
                    </button>
                  </div>
                  <small>{request.max_segments <= 0 ? '根据视频长度、字幕密度和句子完整性自动计算。' : '手动限制最终进入制卡的片段数量。'}</small>
                </label>
              </div>
              <div className="settings-subheading level-subheading">
                <strong>当前水平</strong>
                <span>控制解释深度和质量门槛</span>
              </div>
              <div className="segmented level-segmented" aria-label="当前学习水平">
                {levels.map((level) => (
                  <button
                    type="button"
                    key={level.id}
                    className={request.level === level.id ? 'selected' : ''}
                    onClick={() => selectCurrentLevel(level.id)}
                  >
                    <strong>{level.id}</strong>
                    <span>{level.note}</span>
                  </button>
                ))}
              </div>
              <details className="compact-details inspector-fold level-range-panel" aria-label="收录难度范围">
                <summary>
                  <span>收录难度范围</span>
                  <strong>{normalizeCollectionLevels(request.collection_levels, request.level).join(' / ')}</strong>
                </summary>
                <div className="level-range-body">
                  <div className="range-actions" aria-label="收录范围快捷设置">
                    <button type="button" onClick={() => applyCollectionPreset('current')}>
                      只当前
                    </button>
                    <button type="button" onClick={() => applyCollectionPreset('below')}>
                      当前及以下
                    </button>
                    <button type="button" onClick={() => applyCollectionPreset('around')}>
                      上下一级
                    </button>
                  </div>
                  <div className="level-range-grid">
                    {levels.map((level) => {
                      const selected = normalizeCollectionLevels(request.collection_levels, request.level).includes(level.id)
                      return (
                        <button
                          type="button"
                          key={level.id}
                          className={selected ? 'selected' : ''}
                          onClick={() => toggleCollectionLevel(level.id)}
                          aria-pressed={selected}
                        >
                          <strong>{level.id}</strong>
                          <span>{level.note}</span>
                        </button>
                      )
                    })}
                  </div>
                </div>
              </details>
              <details className="compact-details content-preferences">
                <summary>
                  <span>内容偏好</span>
                  <strong>
                    {contentOptions.filter((item) => request.content_toggles[item.key]).length} 项已选
                  </strong>
                </summary>
                <div className="toggle-grid">
                  {contentOptions.map((item) => (
                    <label className="toggle" key={item.key}>
                      <input
                        type="checkbox"
                        checked={request.content_toggles[item.key]}
                        onChange={() => toggleContent(item.key)}
                      />
                      <span>{item.label}</span>
                    </label>
                  ))}
                </div>
              </details>
            </div>
          </section>

          <section className="panel generation-panel">
            <details className="compact-details preference-details">
              <summary>
                <span>卡片和模板</span>
                <strong>
                  {request.source_mode === 'document'
                    ? '知识点卡'
                    : `${request.card_types.length} 类 · ${activeTemplate?.label ?? '沉浸视频'}`}
                </strong>
              </summary>
              {request.source_mode === 'document' ? (
                <div className="doc-card-mode">
                  <FileText size={18} />
                  <div>
                    <strong>知识点卡</strong>
                    <span>正面是问题或概念提示，反面是结构化答案、解释、例子和为什么值得记。</span>
                  </div>
                </div>
              ) : (
                <div className="choice-row">
                  {cardOptions.map((item) => (
                    <button
                      type="button"
                      key={item.id}
                      className={`choice ${request.card_types.includes(item.id) ? 'selected' : ''}`}
                      onClick={() => toggleCardType(item.id)}
                    >
                      <strong>{item.label}</strong>
                      <span>{item.note}</span>
                    </button>
                  ))}
                </div>
              )}
              <div className="choice-row">
                {templateOptions.map((item) => (
                  <button
                    type="button"
                    key={item.id}
                    className={`choice template-choice ${request.template_id === item.id ? 'selected' : ''} ${
                      item.locked ? 'locked' : ''
                    }`}
                    onClick={() => {
                      if (!item.locked) selectTemplate(item.id)
                    }}
                    disabled={item.locked}
                  >
                    <strong>{item.label}</strong>
                    <span>{item.note}</span>
                  </button>
                ))}
              </div>
            </details>
          </section>
          </aside>

          <section
            className={`panel preview-panel template-${request.template_id}`}
            ref={previewPanelRef}
            tabIndex={-1}
            aria-labelledby="preview-title"
          >
            <div className="preview-header">
              <div className="panel-heading">
                <MessageSquareText size={20} />
                <div>
                  <h3 id="preview-title">{project ? 'AI 评审工作台' : '生成工作台'}</h3>
                  <p className="panel-subtitle">
                    {project ? '查看模型留下的表达、判断理由和可导出的卡片草稿。' : '先选择素材，再生成卡片；结果会在这里展开。'}
                  </p>
                </div>
              </div>
              {project ? (
                <div className="preview-actions">
                  <button className="ghost-button" type="button" onClick={() => setCardsEnabled(true)}>
                    全选
                  </button>
                  <button className="ghost-button" type="button" onClick={() => setCardsEnabled(false)}>
                    全不选
                  </button>
                  <button className="ghost-button" type="button" onClick={() => selectCardsByQuality('recommended')}>
                    只保留推荐
                  </button>
                  <button className="ghost-button" type="button" onClick={() => selectCardsByQuality('reviewable')}>
                    推荐+待审
                  </button>
                </div>
              ) : null}
            </div>

            {project ? (
              <ReviewSummaryPanel
                activeTemplateLabel={activeTemplate?.label ?? '沉浸视频'}
                language={request.language}
                level={request.level}
                project={project}
                qualityCounts={qualityCounts}
                qualityDiagnostics={qualityDiagnostics}
                qualityFunnel={qualityFunnel}
                selectedCardCount={selectedCardCount}
                segmentFilter={segmentFilter}
                segmentReviewCounts={segmentReviewCounts}
                onSegmentFilterChange={setSegmentFilter}
              />
            ) : null}

            {lastExport ? (
              <ExportResultPanel
                ankiVerifying={ankiVerifying}
                ankiVerifyResult={ankiVerifyResult}
                lastExport={lastExport}
                onOpenAnkiImport={openAnkiImport}
                onRevealExport={revealExport}
                onVerifyAnkiImport={verifyAnkiImport}
              />
            ) : null}

            {!project ? (
              <EmptyWorkbench
                appBusy={appBusy}
                level={request.level}
                maxSegments={request.max_segments}
                sourceMode={request.source_mode}
                templateLabel={activeTemplate?.label ?? '沉浸视频'}
                onGenerate={generate}
                onOpenSettings={() => setSettingsOpen(true)}
              />
            ) : (
              <div className="preview-layout">
                <SegmentList
                  activeSegmentId={activeSegmentId}
                  motionDuration={motionDuration}
                  prefersReducedMotion={Boolean(prefersReducedMotion)}
                  segments={visibleSegments}
                  onSelectSegment={setActiveSegmentId}
                />

                {activeSegment ? (
                  <SegmentDetail
                    motionDuration={motionDuration}
                    prefersReducedMotion={Boolean(prefersReducedMotion)}
                    previewRate={previewRate}
                    segment={activeSegment}
                    videoSrc={activeSegmentVideoSrc}
                    onPreviewRateChange={setPreviewRate}
                    onSetSegmentCardsEnabled={setCardsEnabled}
                    onUpdateCard={updateCard}
                  />
                ) : null}
              </div>
            )}
          </section>
        </section>
      </main>

      <AnimatePresence>
        {settingsOpen ? (
        <motion.div
          className="settings-overlay"
          role="presentation"
          onClick={() => setSettingsOpen(false)}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: motionDuration }}
        >
          <motion.section
            className="settings-dialog"
            ref={settingsDialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="settings-title"
            tabIndex={-1}
            onClick={(event) => event.stopPropagation()}
            initial={{ opacity: 0, x: prefersReducedMotion ? 0 : 28 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: prefersReducedMotion ? 0 : 24 }}
            transition={{ duration: motionDuration, ease: 'easeOut' }}
          >
            <div className="settings-dialog-header">
              <div>
                <p className="eyebrow">Settings</p>
                <h2 id="settings-title">设置</h2>
              </div>
              <button
                className="icon-button"
                type="button"
                onClick={() => setSettingsOpen(false)}
                aria-label="关闭设置"
              >
                <X size={18} />
              </button>
            </div>
            <div className="settings-tabs" role="tablist" aria-label="设置分类">
              <button
                type="button"
                role="tab"
                aria-selected={settingsTab === 'api'}
                className={settingsTab === 'api' ? 'selected' : ''}
                onClick={() => setSettingsTab('api')}
              >
                模型 API
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={settingsTab === 'tts'}
                className={settingsTab === 'tts' ? 'selected' : ''}
                onClick={() => setSettingsTab('tts')}
              >
                语音 TTS
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={settingsTab === 'env'}
                className={settingsTab === 'env' ? 'selected' : ''}
                onClick={() => setSettingsTab('env')}
              >
                本地环境
              </button>
            </div>

            <div className="settings-content">
              {settingsTab === 'env' ? (
                <EnvSettingsPanel appBusy={appBusy} envStatus={envStatus} onCheckEnv={checkEnv} />
              ) : null}

              {settingsTab === 'api' ? (
              <section className="settings-section settings-section-single">
                <div className="panel-heading">
                  <Boxes size={20} />
                  <h3>模型 API</h3>
                </div>
                <details className="settings-disclosure">
                  <summary>
                    <span>模型说明与隐私</span>
                    <strong>安全 / 费用 / MIMO Token Plan</strong>
                  </summary>
                  <div className="settings-callout">
                    <PlugZap size={18} />
                    <div>
                      <strong>你现在用 MIMO，可以直接选 MIMO V2.5 Pro。</strong>
                      <p>
                        Token Plan 用户优先选 MIMO Token Plan SGP。程序会按官方要求自动使用 api-key 请求头、
                        小写模型 ID 和更大的 max_completion_tokens；填好 Key 后先点“测试连接”。
                      </p>
                    </div>
                  </div>
                  <div className="settings-callout risk-callout">
                    <CircleAlert size={18} />
                    <div>
                      <strong>字幕、文档和卡片字段会发送给你选择的模型服务商。</strong>
                      <p>
                        API Key 只保留在当前会话，关闭或刷新后可能需要重新填写；不要把私人素材或不想上传的内容交给第三方模型。
                      </p>
                    </div>
                  </div>
                </details>

                <ConnectionTestCard
                  buttonLabel="测试连接"
                  disabled={apiTesting || appBusy}
                  message={apiTestMessage}
                  meta={apiTestMeta}
                  ok={apiTestResult?.ok}
                  statusLabel="连接状态"
                  testing={apiTesting}
                  testingLabel="测试中..."
                  title={apiTestTitle}
                  tone={apiTestTone}
                  onTest={testApi}
                />

                <div className="settings-subheading">
                  <strong>推荐配置</strong>
                  <span>普通用户只需要选一个服务商、填 Key、点测试。</span>
                </div>
                <div className="preset-grid compact-presets" aria-label="API 推荐预设">
                  {featuredApiPresets.map((preset) => {
                    const selected =
                      request.api_config.provider === preset.provider &&
                      request.api_config.base_url === preset.base_url &&
                      request.api_config.model === preset.model
                    return (
                      <button
                        type="button"
                        key={preset.id}
                        className={`preset-card ${selected ? 'selected' : ''}`}
                        onClick={() => applyApiPreset(preset)}
                      >
                        <strong>{preset.label}</strong>
                        <span>{preset.note}</span>
                        <small>{preset.key_hint}</small>
                      </button>
                    )
                  })}
                </div>

                <button
                  className="advanced-toggle"
                  type="button"
                  onClick={() => setShowAdvancedApi((value) => !value)}
                >
                  {showAdvancedApi ? '收起更多服务商' : '展开更多服务商'}
                </button>
                {showAdvancedApi ? (
                  <div className="preset-grid compact-presets secondary-presets" aria-label="更多 API 预设">
                    {advancedApiPresets.map((preset) => {
                      const selected =
                        request.api_config.provider === preset.provider &&
                        request.api_config.base_url === preset.base_url &&
                        request.api_config.model === preset.model
                      return (
                        <button
                          type="button"
                          key={preset.id}
                          className={`preset-card ${selected ? 'selected' : ''}`}
                          onClick={() => applyApiPreset(preset)}
                        >
                          <strong>{preset.label}</strong>
                          <span>{preset.note}</span>
                          <small>{preset.key_hint}</small>
                        </button>
                      )
                    })}
                  </div>
                ) : null}

                <div className="api-grid">
                  <label className="field">
                    <span>Provider</span>
                    <select
                      value={request.api_config.provider}
                      onChange={(event) => {
                        const provider = event.target.value as Provider
                        patchApi({
                          provider,
                          base_url:
                            provider === 'mimo'
                              ? request.api_config.base_url || MIMO_OPENAI_BASE_URL
                              : request.api_config.base_url,
                          model:
                            provider === 'mimo' && !request.api_config.model
                              ? 'mimo-v2.5-pro'
                              : request.api_config.model,
                          capabilities:
                            provider === 'mimo'
                              ? Array.from(new Set([...request.api_config.capabilities, 'structured_json', 'long_context']))
                              : request.api_config.capabilities,
                        })
                      }}
                    >
                      <option value="local">本地草稿</option>
                      <option value="mimo">MIMO / 小米</option>
                      <option value="openai-compatible">OpenAI-compatible</option>
                      <option value="claude">Claude 原生</option>
                      <option value="gemini">Gemini 原生</option>
                    </select>
                    <small>MIMO 已有独立选项；其他兼容 OpenAI API 的服务商选 OpenAI-compatible。</small>
                  </label>
                  <label className="field">
                    <span>Base URL</span>
                    <input
                      value={request.api_config.base_url}
                      onChange={(event) => patchApi({ base_url: event.target.value })}
                      placeholder={request.api_config.provider === 'mimo' ? MIMO_OPENAI_BASE_URL : 'https://api.deepseek.com/v1'}
                    />
                    <small>
                      {request.api_config.provider === 'mimo'
                        ? `默认 ${MIMO_OPENAI_BASE_URL}；Token Plan 可改成控制台专属端点。`
                        : request.api_config.provider === 'claude' && request.api_config.base_url
                          ? '当前使用 Anthropic-compatible 自定义端点；通常会自动请求 /v1/messages。'
                        : 'OpenAI-compatible 必填；Claude / Gemini 原生模式不用填。'}
                    </small>
                  </label>
                  <label className="field">
                    <span>Model</span>
                    <input
                      value={request.api_config.model}
                      onChange={(event) => patchApi({ model: event.target.value })}
                      list="mimo-text-models"
                      placeholder={request.api_config.provider === 'mimo' ? 'mimo-v2.5-pro' : 'deepseek-chat'}
                    />
                    <datalist id="mimo-text-models">
                      {mimoTextModels.map((model) => (
                        <option key={model.value} value={model.value}>
                          {model.label}
                        </option>
                      ))}
                    </datalist>
                    <small>
                      {request.api_config.provider === 'mimo'
                        ? '官方要求模型 ID 小写：mimo-v2.5-pro、mimo-v2.5、mimo-v2-pro、mimo-v2-omni。'
                        : '填模型 ID，不是产品名。比如 deepseek-chat、qwen-plus。'}
                    </small>
                  </label>
                  <label className="field">
                    <span>API Key</span>
                    <input
                      type="password"
                      value={request.api_config.api_key}
                      onChange={(event) => patchApi({ api_key: event.target.value })}
                      placeholder={request.api_config.provider === 'mimo' ? 'sk-... / tp-...' : 'sk-...'}
                    />
                    <small>只用于当前会话的字幕理解和卡片解释生成；不会写入本地缓存，也不会自动拿去做 TTS。</small>
                  </label>
                  <label className="toggle secret-toggle">
                    <input
                      type="checkbox"
                      checked={secretPrefs.rememberModelKey}
                      onChange={() => toggleRememberSecret('model')}
                    />
                    <span>记住本机模型 API Key（Windows Credential Manager）</span>
                  </label>
                </div>
                <button className="capability-heading collapsible-heading" type="button" onClick={() => setShowCapabilities((value) => !value)}>
                  <KeyRound size={18} />
                  <strong>模型能力标签</strong>
                  <span>{showCapabilities ? '收起' : '高级选项，默认不用改'}</span>
                </button>
                {showCapabilities ? (
                  <div className="capabilities capability-grid">
                    {capabilityLabels.map((capability) => {
                      const selected = request.api_config.capabilities.includes(capability)
                      return (
                        <button
                          type="button"
                          key={capability}
                          className={selected ? 'cap selected' : 'cap'}
                          onClick={() => {
                            const capabilities = selected
                              ? request.api_config.capabilities.filter((item) => item !== capability)
                              : [...request.api_config.capabilities, capability]
                            patchApi({ capabilities })
                          }}
                        >
                          <strong>{capability}</strong>
                          <span>{capabilityHelp[capability]}</span>
                        </button>
                      )
                    })}
                  </div>
                ) : null}
                <div className="settings-help-grid">
                  <div>
                    <CircleAlert size={18} />
                    <strong>测试通过代表什么？</strong>
                    <p>代表 Key、Base URL、模型名和基础文本生成接口可用，可以进入生成流程。</p>
                  </div>
                  <div>
                    <CircleAlert size={18} />
                    <strong>测试失败常见原因</strong>
                    <p>Key 填错、模型名不存在、Base URL 少了 /v1、余额不足、服务商网络不可达。</p>
                  </div>
                </div>
              </section>
              ) : null}

              {settingsTab === 'tts' ? (
              <section className="settings-section settings-section-single">
                <div className="panel-heading">
                  <PlugZap size={20} />
                  <h3>语音 TTS</h3>
                </div>
                <details className="settings-disclosure">
                  <summary>
                    <span>TTS 说明与费用</span>
                    <strong>语音模型 / 授权 / 费用</strong>
                  </summary>
                  <div className="settings-callout tts-callout">
                    <CircleAlert size={18} />
                    <div>
                      <strong>TTS 是独立配置，MIMO 语音模型也在这里选。</strong>
                      <p>
                        MIMO V2.5 TTS、VoiceDesign、VoiceClone 和 V2 TTS 都可以作为独立语音模型配置。
                        如果上方文本模型已经配置了 MIMO Key，TTS 会默认复用它；只有想单独换语音服务时才需要另填 TTS Key。
                      </p>
                    </div>
                  </div>
                  <div className="settings-callout risk-callout">
                    <CircleAlert size={18} />
                    <div>
                      <strong>TTS 会额外调用语音服务，并可能产生费用。</strong>
                      <p>
                        导出牌组如果包含视频片段、字幕或合成音频，默认仅供个人学习；分享前请确认素材和声音服务授权。
                      </p>
                    </div>
                  </div>
                </details>

                <ConnectionTestCard
                  buttonLabel="测试 TTS"
                  disabled={ttsTesting || appBusy}
                  message={ttsTestMessage}
                  meta={ttsTestMeta}
                  ok={ttsTestResult?.ok}
                  statusLabel="TTS 状态"
                  testing={ttsTesting}
                  testingLabel="测试中..."
                  title={ttsTestTitle}
                  tone={ttsTestTone}
                  onTest={testTts}
                />

                <div className="settings-subheading">
                  <strong>常用语音</strong>
                  <span>视频卡优先用原声；只在需要额外朗读时开启 TTS。</span>
                </div>
                <div className="preset-grid compact-presets tts-preset-grid" aria-label="TTS 推荐预设">
                  {featuredTtsPresets.map((preset) => {
                    const selected =
                      tts.provider === preset.provider &&
                      tts.base_url === preset.base_url &&
                      tts.model === preset.model &&
                      tts.voice === preset.voice &&
                      (preset.provider !== 'disabled' ? tts.enabled : !tts.enabled)
                    return (
                      <button
                        type="button"
                        key={preset.id}
                        className={`preset-card ${selected ? 'selected' : ''}`}
                        onClick={() => applyTtsPreset(preset)}
                      >
                        <strong>{preset.label}</strong>
                        <span>{preset.note}</span>
                        <small>{preset.key_hint}</small>
                      </button>
                    )
                  })}
                </div>
                <button
                  className="advanced-toggle"
                  type="button"
                  onClick={() => setShowAdvancedTts((value) => !value)}
                >
                  {showAdvancedTts ? '收起高级 TTS' : '高级 TTS 模型和参数'}
                </button>
                {showAdvancedTts ? (
                  <div className="preset-grid compact-presets secondary-presets" aria-label="更多 TTS 预设">
                    {advancedTtsPresets.map((preset) => {
                      const selected =
                        tts.provider === preset.provider &&
                        tts.base_url === preset.base_url &&
                        tts.model === preset.model &&
                        tts.voice === preset.voice &&
                        (preset.provider !== 'disabled' ? tts.enabled : !tts.enabled)
                      return (
                        <button
                          type="button"
                          key={preset.id}
                          className={`preset-card ${selected ? 'selected' : ''}`}
                          onClick={() => applyTtsPreset(preset)}
                        >
                          <strong>{preset.label}</strong>
                          <span>{preset.note}</span>
                          <small>{preset.key_hint}</small>
                        </button>
                      )
                    })}
                  </div>
                ) : null}

                <div className="tts-enable-row">
                  <label className="toggle">
                    <input
                      type="checkbox"
                      checked={tts.enabled}
                      onChange={() =>
                        patchTts({
                          enabled: !tts.enabled,
                          provider: !tts.enabled ? (tts.provider === 'disabled' ? 'mimo' : tts.provider) : 'disabled',
                          base_url:
                            !tts.enabled && tts.provider === 'disabled' ? MIMO_TOKEN_PLAN_SGP_BASE_URL : tts.base_url,
                          model: !tts.enabled && !tts.model ? 'mimo-v2.5-tts' : tts.model,
                          voice: !tts.enabled && !tts.voice ? 'Mia' : tts.voice,
                        })
                      }
                    />
                    <span>导出时生成整句和词伙 TTS</span>
                  </label>
                  <small>开启后会额外生成整句朗读，并给顶部重点词伙生成小喇叭音频。</small>
                </div>

                {tts.enabled ? (
                <div className="api-grid tts-api-grid">
                  <label className="field">
                    <span>语音服务</span>
                    <select
                      value={tts.provider}
                      onChange={(event) => {
                        const provider = event.target.value as TtsProvider
                        patchTts({
                          provider,
                          enabled: provider !== 'disabled',
                          base_url:
                            provider === 'mimo'
                              ? tts.base_url || MIMO_TOKEN_PLAN_SGP_BASE_URL
                              : provider === 'grok'
                              ? 'https://api.x.ai/v1'
                              : provider === 'openai-compatible'
                                ? tts.base_url || 'https://api.openai.com/v1'
                                : tts.base_url,
                          model: provider === 'mimo' && !tts.model ? 'mimo-v2.5-tts' : tts.model,
                          voice:
                            provider === 'mimo'
                              ? tts.voice || 'Mia'
                              : provider === 'grok'
                                ? tts.voice || 'eve'
                                : tts.voice,
                        })
                      }}
                    >
                      <option value="disabled">关闭 TTS</option>
                      <option value="mimo">MIMO / 小米 TTS</option>
                      <option value="grok">Grok / xAI TTS</option>
                      <option value="gemini">Gemini TTS</option>
                      <option value="openai-compatible">OpenAI-compatible Speech</option>
                    </select>
                    <small>这里选择语音服务商，不影响上面的文本模型 Provider。</small>
                  </label>
                  <label className="field">
                    <span>语音 Base URL</span>
                    <input
                      value={tts.base_url}
                      onChange={(event) => patchTts({ base_url: event.target.value })}
                      placeholder={tts.provider === 'mimo' ? MIMO_OPENAI_BASE_URL : 'https://api.x.ai/v1'}
                    />
                    <small>
                      {tts.provider === 'mimo'
                        ? `MIMO 默认 ${MIMO_OPENAI_BASE_URL}；你的 tp-... 套餐 Key 优先用 ${MIMO_TOKEN_PLAN_SGP_BASE_URL}。`
                        : 'Grok 默认 https://api.x.ai/v1；Gemini 可留空。'}
                    </small>
                  </label>
                  <label className="field">
                    <span>语音 API Key</span>
                    <input
                      type="password"
                      value={tts.api_key}
                      onChange={(event) => patchTts({ api_key: event.target.value })}
                      placeholder={tts.provider === 'mimo' ? 'sk-... / tp-...' : 'xai-... / AIza...'}
                    />
                    <small>MIMO TTS 可留空并复用上方 MIMO Key；填写后优先使用这里的 Key，且不会写入本地缓存。</small>
                  </label>
                  <label className="toggle secret-toggle">
                    <input
                      type="checkbox"
                      checked={secretPrefs.rememberTtsKey}
                      onChange={() => toggleRememberSecret('tts')}
                    />
                    <span>记住本机 TTS API Key（Windows Credential Manager）</span>
                  </label>
                  <label className="field">
                    <span>语音模型</span>
                    <input
                      value={tts.model}
                      onChange={(event) => patchTts({ model: event.target.value })}
                      placeholder={
                        tts.provider === 'mimo'
                          ? 'mimo-v2.5-tts'
                          : tts.provider === 'grok'
                          ? '留空即可，Grok TTS 不需要模型名'
                          : tts.provider === 'gemini'
                            ? 'gemini-2.5-flash-preview-tts'
                            : 'gpt-4o-mini-tts'
                      }
                      list="mimo-tts-models"
                    />
                    <datalist id="mimo-tts-models">
                      {mimoTtsModels.map((model) => (
                        <option key={model.value} value={model.value}>
                          {model.label}
                        </option>
                      ))}
                    </datalist>
                    <small>
                      {tts.provider === 'mimo'
                        ? '官方要求模型 ID 小写：mimo-v2.5-tts、voicedesign、voiceclone、mimo-v2-tts。'
                        : 'Grok TTS 当前不需要模型名，可留空；Gemini / Speech API 需要模型名。'}
                    </small>
                  </label>
                  <label className="field">
                    <span>声音 / voice_id</span>
                    <input
                      value={tts.voice}
                      onChange={(event) => patchTts({ voice: event.target.value })}
                      placeholder={
                        tts.provider === 'mimo'
                          ? 'Mia / Chloe / Milo / Dean / mimo_default'
                          : tts.provider === 'grok'
                            ? 'eve / ara / leo / rex / sal'
                            : 'Kore / alloy'
                      }
                      list={tts.provider === 'mimo' ? 'mimo-tts-voices' : undefined}
                    />
                    <datalist id="mimo-tts-voices">
                      {mimoTtsVoices.map((voice) => (
                        <option key={voice} value={voice} />
                      ))}
                    </datalist>
                    <small>
                      MIMO V2.5 内置声音可填 Mia、Chloe、Milo、Dean；VoiceDesign 模型这里填声音描述，
                      VoiceClone 模型这里填 data:audio/...;base64。
                    </small>
                  </label>
                  {showAdvancedTts ? (
                    <>
                      <label className="field">
                        <span>Language</span>
                        <input
                          value={tts.language}
                          onChange={(event) => patchTts({ language: event.target.value })}
                          placeholder="auto / en / zh / ja"
                        />
                        <small>MIMO / Grok 支持 auto 或 BCP-47 语言码；英语卡建议 auto 或 en。</small>
                      </label>
                      <label className="field">
                        <span>Sample Rate</span>
                        <input
                          type="number"
                          min={8000}
                          max={48000}
                          value={tts.sample_rate}
                          onChange={(event) => patchTts({ sample_rate: Number(event.target.value) })}
                        />
                        <small>MIMO / Grok 常用 24000；不确定就保持默认。</small>
                      </label>
                      <label className="field">
                        <span>Bit Rate</span>
                        <input
                          type="number"
                          min={32000}
                          max={192000}
                          step={32000}
                          value={tts.bit_rate}
                          onChange={(event) => patchTts({ bit_rate: Number(event.target.value) })}
                        />
                        <small>MP3 常用 128000，体积和质量比较均衡。</small>
                      </label>
                    </>
                  ) : null}
                </div>
                ) : (
                  <div className="tts-disabled-note">
                    <strong>TTS 当前关闭</strong>
                    <span>导出时只使用视频原声；需要顶部词伙小喇叭和 AI 朗读时，打开上面的开关或选择一个常用语音预设。</span>
                  </div>
                )}
              </section>
              ) : null}
            </div>
          </motion.section>
        </motion.div>
        ) : null}
      </AnimatePresence>

      {isTauriRuntime() ? (
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

export default App
