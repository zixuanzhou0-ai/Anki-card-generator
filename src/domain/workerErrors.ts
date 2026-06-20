import type { WorkerErrorCode } from './types'

export type WorkerErrorActionId =
  | 'open-api-settings'
  | 'open-tts-settings'
  | 'open-env-settings'
  | 'use-subtitle-only'
  | 'skip-video-slicing'
  | 'allow-private-network-url'
  | 'allow-ytdlp-remote-components'
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
    label: '缺视频恢复已停用',
    description: '当前发布版只保留视频制卡，请修复视频下载或切片问题后重试。',
  },
  'skip-video-slicing': {
    id: 'skip-video-slicing',
    label: '跳过切片已停用',
    description: '当前发布版的视频卡必须包含视频片段和原声。',
  },
  'allow-private-network-url': {
    id: 'allow-private-network-url',
    label: '允许本机/内网 URL 后重试',
    description: '仅当这个链接确实是你主动选择的本机或内网素材时使用。',
  },
  'allow-ytdlp-remote-components': {
    id: 'allow-ytdlp-remote-components',
    label: '允许远程组件后重试',
    description: '仅当你信任本次视频来源，并接受 yt-dlp 拉取远程组件时使用。',
  },
  retry: {
    id: 'retry',
    label: '重试任务',
    description: '使用当前配置重新执行刚才失败的任务。',
  },
}

const ERROR_ACTIONS: Partial<Record<WorkerErrorCode, WorkerErrorActionId[]>> = {
  ENV_PYTHON_MISSING: ['open-env-settings'],
  ENV_FFMPEG_MISSING: ['open-env-settings'],
  YOUTUBE_RATE_LIMIT: ['open-env-settings', 'retry'],
  YOUTUBE_N_CHALLENGE: ['open-env-settings', 'retry'],
  YOUTUBE_SUBTITLE_UNAVAILABLE: ['open-env-settings', 'retry'],
  LOCAL_SUBTITLE_MISSING: ['retry'],
  MODEL_AUTH_FAILED: ['open-api-settings'],
  MODEL_CONNECTION_FAILED: ['open-api-settings', 'retry'],
  MODEL_NOT_FOUND: ['open-api-settings'],
  MODEL_QUOTA_EXCEEDED: ['open-api-settings', 'retry'],
  MODEL_TIMEOUT: ['open-api-settings', 'retry'],
  MODEL_JSON_INVALID: ['open-api-settings', 'retry'],
  MODEL_REVIEW_BAD_JSON: ['open-api-settings', 'retry'],
  MODEL_REVIEW_FAILED: ['open-api-settings', 'retry'],
  TTS_AUTH_FAILED: ['open-tts-settings'],
  TTS_CONNECTION_FAILED: ['open-tts-settings', 'retry'],
  TTS_NOT_FOUND: ['open-tts-settings'],
  TTS_QUOTA_EXCEEDED: ['open-tts-settings', 'retry'],
  TTS_TIMEOUT: ['open-tts-settings', 'retry'],
  TTS_SEMANTIC_MISMATCH: ['retry'],
  TTS_SEMANTIC_UNVERIFIED: ['open-env-settings', 'open-tts-settings', 'retry'],
  UNSAFE_ASR_COMMAND: ['open-env-settings', 'open-tts-settings'],
  UNSAFE_VERIFY_OUTPUT_DIR: ['retry'],
  REMOTE_ANKI_CONNECT_BLOCKED: ['open-env-settings'],
  PRIVATE_NETWORK_URL_BLOCKED: ['allow-private-network-url', 'retry'],
  YTDLP_REMOTE_COMPONENTS_CONFIRMATION_REQUIRED: ['allow-ytdlp-remote-components', 'retry'],
  LOCAL_PATH_ACCESS_CONFIRMATION_REQUIRED: ['retry'],
  EXPORT_QUALITY_GATE_FAILED: ['retry'],
  MEDIA_SUBTITLE_ALIGNMENT_MISMATCH: ['retry'],
  FFMPEG_SLICE_FAILED: ['open-env-settings'],
  ANKI_EXPORT_FAILED: ['retry'],
  ANKI_VERIFY_FAILED: ['retry'],
  WORKER_CANCELLED: [],
  WORKER_TIMEOUT: ['retry'],
  UNKNOWN_WORKER_ERROR: ['retry'],
}

const FALLBACK_ACTIONS: Record<string, WorkerErrorActionId> = {
  skip_tts: 'open-tts-settings',
  allow_ytdlp_remote_components: 'allow-ytdlp-remote-components',
}

function uniqueActions(ids: WorkerErrorActionId[]): WorkerErrorAction[] {
  return [...new Set(ids)].map((id) => ACTIONS[id])
}

export function getWorkerErrorActions(errorCode?: string, fallbacks: string[] = []): WorkerErrorAction[] {
  const fromError = errorCode && errorCode in ERROR_ACTIONS ? (ERROR_ACTIONS[errorCode as WorkerErrorCode] ?? []) : []
  const fromFallbacks = fallbacks
    .map((fallback) => FALLBACK_ACTIONS[fallback])
    .filter((action): action is WorkerErrorActionId => Boolean(action))

  return uniqueActions([...fromError, ...fromFallbacks])
}
