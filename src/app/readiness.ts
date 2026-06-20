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
  return '可稍后测试'
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
      label: 'TTS 增强',
      done: true,
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
