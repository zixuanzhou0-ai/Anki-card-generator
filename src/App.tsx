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
  EnvStatus,
  ExportResult,
  GenerateRequest,
  InspectorState,
  Level,
  Project,
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
import { InspectorPanel } from './features/app/InspectorPanel'
import { Topbar } from './features/app/Topbar'
import { ReviewWorkspace } from './features/review/ReviewWorkspace'
import { SettingsDialog } from './features/settings/SettingsDialog'
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
            onSelectSegment={setActiveSegmentId}
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
