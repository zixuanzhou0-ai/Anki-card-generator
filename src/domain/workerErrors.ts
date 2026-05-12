import type { WorkerErrorCode } from './types'

export type WorkerErrorActionId =
  | 'open-api-settings'
  | 'open-tts-settings'
  | 'open-env-settings'
  | 'use-subtitle-only'
  | 'skip-video-slicing'
  | 'retry'

export type WorkerErrorAction = {
  id: WorkerErrorActionId
  label: string
  description: string
}

const ACTIONS: Record<WorkerErrorActionId, WorkerErrorAction> = {
  'open-api-settings': {
    id: 'open-api-settings',
    label: '检查模型设置',
    description: '打开模型 API 设置，检查 Key、Base URL 和模型名。',
  },
  'open-tts-settings': {
    id: 'open-tts-settings',
    label: '检查 TTS 设置',
    description: '打开语音设置，检查 TTS Key、模型和声音。',
  },
  'open-env-settings': {
    id: 'open-env-settings',
    label: '检查本地环境',
    description: '打开环境页，查看 Python、FFmpeg、yt-dlp 和依赖状态。',
  },
  'use-subtitle-only': {
    id: 'use-subtitle-only',
    label: '改用字幕-only',
    description: '跳过视频下载和切片，只用字幕继续生成卡片。',
  },
  'skip-video-slicing': {
    id: 'skip-video-slicing',
    label: '跳过视频切片',
    description: '保留卡片内容，导出时不再切视频片段。',
  },
  retry: {
    id: 'retry',
    label: '重试任务',
    description: '使用当前配置重新执行刚才失败的任务。',
  },
}

const ERROR_ACTIONS: Partial<Record<WorkerErrorCode, WorkerErrorActionId[]>> = {
  ENV_PYTHON_MISSING: ['open-env-settings'],
  ENV_FFMPEG_MISSING: ['open-env-settings', 'skip-video-slicing'],
  YOUTUBE_RATE_LIMIT: ['use-subtitle-only', 'retry'],
  YOUTUBE_N_CHALLENGE: ['use-subtitle-only', 'open-env-settings', 'retry'],
  YOUTUBE_SUBTITLE_UNAVAILABLE: ['use-subtitle-only'],
  MODEL_AUTH_FAILED: ['open-api-settings'],
  MODEL_TIMEOUT: ['open-api-settings', 'retry'],
  MODEL_JSON_INVALID: ['open-api-settings', 'retry'],
  TTS_AUTH_FAILED: ['open-tts-settings'],
  TTS_TIMEOUT: ['open-tts-settings', 'retry'],
  FFMPEG_SLICE_FAILED: ['skip-video-slicing', 'open-env-settings'],
  ANKI_EXPORT_FAILED: ['retry'],
  ANKI_VERIFY_FAILED: ['retry'],
  WORKER_CANCELLED: [],
  WORKER_TIMEOUT: ['retry'],
}

const FALLBACK_ACTIONS: Record<string, WorkerErrorActionId> = {
  subtitle_only: 'use-subtitle-only',
  local_srt: 'use-subtitle-only',
  skip_video_slicing: 'skip-video-slicing',
  skip_tts: 'open-tts-settings',
}

function uniqueActions(ids: WorkerErrorActionId[]): WorkerErrorAction[] {
  return [...new Set(ids)].map((id) => ACTIONS[id])
}

export function getWorkerErrorActions(errorCode?: string, fallbacks: string[] = []): WorkerErrorAction[] {
  const fromError = errorCode && errorCode in ERROR_ACTIONS ? ERROR_ACTIONS[errorCode as WorkerErrorCode] ?? [] : []
  const fromFallbacks = fallbacks
    .map((fallback) => FALLBACK_ACTIONS[fallback])
    .filter((action): action is WorkerErrorActionId => Boolean(action))

  return uniqueActions([...fromError, ...fromFallbacks])
}

