import type { EnvStatus, SourceMode, TtsTestResult } from '../domain/types'
import type { ReadinessItem } from '../features/generation/ReadinessPanel'

const PUBLIC_VIDEO_SOURCE_ONLY_MESSAGE = '当前发布版只支持本地视频和视频链接。请选择视频素材。'

type BuildReadinessItemsInput = {
  sourceMode: SourceMode
  sourceReady: boolean
  localVideoPath: string
  localSubtitlePath: string
  envReady: boolean
  envStatusChecked: boolean
  apiProvider: string
  apiReadyForGeneration: boolean
  hasApiTestResult: boolean
  ttsRequired: boolean
  ttsReadyForGeneration: boolean
  ttsDetail: string
  currentSelectionCount: number
}

export function buildTtsReadinessDetail({
  ttsRequired,
  ttsTestResult,
}: {
  ttsRequired: boolean
  ttsTestResult: Pick<TtsTestResult, 'ok'> | null
}): string {
  if (!ttsRequired) {
    return '已关闭'
  }
  if (ttsTestResult?.ok) {
    return '导出可用'
  }
  if (ttsTestResult) {
    return '需修复后导出'
  }
  return '必须先测试'
}

export function isEnvironmentReadyForGeneration({
  desktopRuntime,
  envStatus,
  sourceMode,
}: {
  desktopRuntime: boolean
  envStatus: EnvStatus | null
  sourceMode: SourceMode
}): boolean {
  if (!desktopRuntime) {
    return true
  }

  return Boolean(
    envStatus?.genanki &&
      envStatus.ffmpeg &&
      (sourceMode === 'local' || (sourceMode === 'url' && envStatus.yt_dlp)),
  )
}

export function buildReadinessItems({
  sourceMode,
  sourceReady,
  localVideoPath,
  localSubtitlePath,
  envReady,
  envStatusChecked,
  apiProvider,
  apiReadyForGeneration,
  hasApiTestResult,
  ttsRequired,
  ttsReadyForGeneration,
  ttsDetail,
  currentSelectionCount,
}: BuildReadinessItemsInput): ReadinessItem[] {
  const sourceLabel = sourceMode === 'url' ? 'URL' : '素材'
  const sourceDetail =
    sourceMode === 'url'
      ? sourceReady
        ? '已就绪'
        : '待输入链接'
      : sourceMode === 'document'
        ? PUBLIC_VIDEO_SOURCE_ONLY_MESSAGE
        : localVideoPath
          ? localSubtitlePath
            ? '视频和字幕已选择'
            : '已选视频，自动匹配字幕'
          : '待选择视频；SRT 可自动匹配'

  const items: ReadinessItem[] = [
    {
      id: 'source',
      label: sourceLabel,
      done: sourceReady,
      detail: sourceDetail,
    },
    {
      id: 'env',
      label: '环境',
      done: envReady,
      detail: envReady ? '可用' : envStatusChecked ? '缺少依赖' : '未检查',
    },
    {
      id: 'api',
      label: 'API',
      done: apiReadyForGeneration,
      detail:
        apiProvider === 'local'
          ? '请选择正式模型'
          : apiReadyForGeneration
            ? '已通过'
            : hasApiTestResult
              ? '失败'
              : '未测试',
    },
  ]

  if (sourceMode !== 'document') {
    items.push({
      id: 'tts',
      label: ttsRequired ? 'TTS 必需' : 'TTS 增强',
      done: !ttsRequired || ttsReadyForGeneration,
      detail: ttsRequired ? ttsDetail : '已关闭',
    })
  }

  items.push({
    id: 'cards',
    label: '卡片',
    done: currentSelectionCount > 0,
    detail: `${currentSelectionCount} 张`,
  })

  return items
}
export type WorkflowStageId = 'setup' | 'extract' | 'generate' | 'export' | 'verify'

export type ReadinessState = 'unknown' | 'checking' | 'ready' | 'blocked' | 'optional'

export type ReadinessBlockerAction =
  | 'select_source'
  | 'check_environment'
  | 'repair_environment'
  | 'test_api'
  | 'test_tts'
  | 'select_learning_points'
  | 'repair_cards'
  | 'open_anki'

export type ReadinessBlocker = {
  id: 'source' | 'environment' | 'api' | 'tts' | 'selection' | 'cards' | 'anki'
  stage: WorkflowStageId
  state: ReadinessState
  title: string
  detail: string
  action: ReadinessBlockerAction
}

export type WorkflowReadinessSnapshot = {
  stage: WorkflowStageId
  canProceed: boolean
  blockers: ReadinessBlocker[]
  warnings: ReadinessBlocker[]
  primaryActionLabel: string
}

export type BuildWorkflowReadinessInput = {
  sourceReady: boolean
  environmentReady: boolean
  environmentChecked: boolean
  apiProvider: string
  apiReady: boolean
  apiTested: boolean
  ttsRequired: boolean
  ttsReady: boolean
  ttsTested: boolean
  selectedLearningPointCount: number
  hasLearningPoints: boolean
  hasProject: boolean
  exportableCardCount: number
  repairRequiredCardCount: number
  hasExport: boolean
  ankiVerified: boolean
}

function getWorkflowStage(input: BuildWorkflowReadinessInput): WorkflowStageId {
  if (input.hasExport) return 'verify'
  if (input.hasProject) return 'export'
  if (input.hasLearningPoints) return 'generate'
  if (!input.sourceReady || !input.environmentChecked || !input.apiTested) return 'setup'
  return 'extract'
}

export function buildWorkflowReadiness(
  input: BuildWorkflowReadinessInput,
): WorkflowReadinessSnapshot {
  const stage = getWorkflowStage(input)
  const blockers: ReadinessBlocker[] = []
  const warnings: ReadinessBlocker[] = []

  if (stage === 'setup' || stage === 'extract' || stage === 'generate') {
    if (!input.sourceReady) {
      blockers.push({
        id: 'source',
        stage,
        state: 'blocked',
        title: '选择学习素材',
        detail: '请选择本地视频或填写可访问的视频链接。',
        action: 'select_source',
      })
    }

    if (!input.environmentReady) {
      blockers.push({
        id: 'environment',
        stage,
        state: input.environmentChecked ? 'blocked' : 'unknown',
        title: input.environmentChecked ? '修复本地环境' : '检查本地环境',
        detail: input.environmentChecked
          ? '生成依赖尚未全部可用，请先完成修复。'
          : '本地生成环境尚未检查，不能假定为已就绪。',
        action: input.environmentChecked ? 'repair_environment' : 'check_environment',
      })
    }

    if (!input.apiReady) {
      blockers.push({
        id: 'api',
        stage,
        state: input.apiTested ? 'blocked' : 'unknown',
        title: input.apiProvider === 'local' ? '选择并测试模型' : '测试模型连接',
        detail:
          input.apiProvider === 'local'
            ? '请选择 Hermes Grok 4.5、OpenAI 或自定义模型并完成测试。'
            : input.apiTested
              ? '最近一次模型测试未通过，请检查授权和连接参数。'
              : '模型连接尚未测试，抽取前必须验证。',
        action: 'test_api',
      })
    }
  }

  if ((stage === 'setup' || stage === 'extract') && input.ttsRequired && !input.ttsReady) {
    warnings.push({
      id: 'tts',
      stage,
      state: input.ttsTested ? 'blocked' : 'unknown',
      title: input.ttsTested ? 'TTS 需要修复' : 'TTS 尚未测试',
      detail: '抽取可以继续，但生成视频卡前必须完成 TTS 测试。',
      action: 'test_tts',
    })
  }

  if (stage === 'generate') {
    if (input.ttsRequired && !input.ttsReady) {
      blockers.push({
        id: 'tts',
        stage,
        state: input.ttsTested ? 'blocked' : 'unknown',
        title: input.ttsTested ? '修复 TTS' : '测试 TTS',
        detail: input.ttsTested
          ? '最近一次 TTS 测试未通过，不能生成缺少语音的半成品卡片。'
          : 'TTS 已启用但尚未测试，不能显示为完全就绪。',
        action: 'test_tts',
      })
    }

    if (input.selectedLearningPointCount < 1) {
      blockers.push({
        id: 'selection',
        stage,
        state: 'blocked',
        title: '选择学习点',
        detail: '至少选择一个可制卡的学习点。',
        action: 'select_learning_points',
      })
    }
  }

  if (stage === 'export') {
    if (input.exportableCardCount < 1) {
      blockers.push({
        id: 'cards',
        stage,
        state: 'blocked',
        title: '修复卡片',
        detail: '当前没有可安全导出的卡片，请先修复失败项。',
        action: 'repair_cards',
      })
    }

    if (input.repairRequiredCardCount > 0) {
      warnings.push({
        id: 'cards',
        stage,
        state: 'blocked',
        title: '部分卡片需要修复',
        detail:
          String(input.repairRequiredCardCount) +
          ' 张卡片不会混入本次导出；可用卡片仍可继续。',
        action: 'repair_cards',
      })
    }
  }

  if (stage === 'verify' && !input.ankiVerified) {
    blockers.push({
      id: 'anki',
      stage,
      state: 'blocked',
      title: '在 Anki 中核验',
      detail: 'APKG 已生成，但尚未在真实 Anki 中完成导入与复习核验。',
      action: 'open_anki',
    })
  }

  const primaryActionLabel =
    blockers.length > 0
      ? stage === 'verify'
        ? '打开 Anki 核验'
        : '完成 ' + String(blockers.length) + ' 项准备'
      : stage === 'setup' || stage === 'extract'
        ? '开始抽取学习点'
        : stage === 'generate'
          ? '生成选中的 ' + String(input.selectedLearningPointCount) + ' 张'
          : stage === 'export'
            ? '导出可用的 ' + String(input.exportableCardCount) + ' 张'
            : '已在 Anki 中核验'

  return {
    stage,
    canProceed: blockers.length === 0,
    blockers,
    warnings,
    primaryActionLabel,
  }
}
