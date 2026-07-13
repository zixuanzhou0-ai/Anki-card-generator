import type {
  ApiConfig,
  ApiTestResult,
  EnvRepairResult,
  GenerateRequest,
  Project,
  TtsConfig,
  TtsTestResult,
} from '../domain/types'
import { publicTemplateIdFor } from '../domain/templates'

type ProjectWithRuntimeConfig = Project & {
  api_config?: ApiConfig
  tts_config?: TtsConfig
}

const PUBLIC_VIDEO_SOURCE_ONLY_MESSAGE = '当前发布版只支持本地视频和视频链接。请选择视频素材。'

export function sourceUrlLooksPrivate(value: string) {
  try {
    const url = new URL(value)
    const host = url.hostname.toLowerCase().replace(/^\[|\]$/g, '')
    if (!host) return false
    if (host === 'localhost' || host.endsWith('.local')) return true
    if (host === '::1') return true
    const parts = host.split('.').map((part) => Number(part))
    if (parts.length !== 4 || parts.some((part) => !Number.isInteger(part) || part < 0 || part > 255)) return false
    const [first, second] = parts
    return (
      first === 10 ||
      first === 127 ||
      (first === 172 && second >= 16 && second <= 31) ||
      (first === 192 && second === 168) ||
      (first === 169 && second === 254) ||
      first === 0
    )
  } catch {
    return false
  }
}

export function stripApiConfigSecrets(api: ApiConfig): ApiConfig {
  return {
    ...api,
    api_key: '',
    tts_config: {
      ...api.tts_config,
      api_key: '',
    },
  }
}

export function stripTtsConfigSecret(ttsConfig: TtsConfig): TtsConfig {
  return {
    ...ttsConfig,
    api_key: '',
  }
}

export function stripProjectRuntimeSecrets(project: Project): Project {
  const source = project as ProjectWithRuntimeConfig
  const sanitized: ProjectWithRuntimeConfig = { ...source }
  if (source.api_config) {
    sanitized.api_config = stripApiConfigSecrets(source.api_config)
  }
  if (source.tts_config) {
    sanitized.tts_config = stripTtsConfigSecret(source.tts_config)
  }
  return sanitized
}

export function normalizeProjectTemplateForPublicSource(project: Project): Project {
  const template_id = publicTemplateIdFor(project.template_id, project.source_mode)
  return template_id === project.template_id ? project : { ...project, template_id }
}

export function cleanLocalPath(value: string) {
  return value.trim().replace(/^["'](.+)["']$/, '$1')
}

export function learningPointExtractionSourceError(
  request: Pick<GenerateRequest, 'source_mode' | 'source_url' | 'video_path'>,
): string | null {
  if (request.source_mode === 'document') {
    return PUBLIC_VIDEO_SOURCE_ONLY_MESSAGE
  }
  if (request.source_mode === 'url' && !request.source_url.trim()) {
    return '请先输入 YouTube / 视频 URL。'
  }
  if (request.source_mode === 'local' && !request.video_path) {
    return '请先选择视频文件。SRT 可以手动选择，也可以放在视频同目录自动匹配。'
  }
  return null
}

export function directGenerationSourceError(
  request: Pick<GenerateRequest, 'batch_enabled' | 'source_mode' | 'source_url' | 'document_path' | 'video_path'>,
  activeBatchItemCount: number,
): string | null {
  if (request.source_mode === 'document') {
    return PUBLIC_VIDEO_SOURCE_ONLY_MESSAGE
  }
  if (request.batch_enabled) {
    return activeBatchItemCount > 0
      ? null
      : '批量模式下还没有可生成的视频素材。请先选择视频文件夹或把视频链接加入批量列表。'
  }
  if (request.source_mode === 'url' && !request.source_url.trim()) {
    return '请先输入 YouTube / 视频 URL。'
  }
  if (request.source_mode === 'local' && !request.video_path) {
    return '请先选择视频文件。SRT 可以手动选择，也可以放在视频同目录自动匹配。'
  }
  return null
}

export function localPathAccessPromptForRequest(
  request: Pick<
    GenerateRequest,
    'source_mode' | 'local_path_access_confirmed' | 'video_path' | 'subtitle_path' | 'document_path'
  >,
): string | null {
  if (request.source_mode === 'url' || request.local_path_access_confirmed) {
    return null
  }

  const paths = [
    request.video_path ? `视频：${request.video_path}` : '',
    request.subtitle_path ? `字幕：${request.subtitle_path}` : '',
    request.document_path ? `文档：${request.document_path}` : '',
  ].filter(Boolean)

  if (!paths.length) {
    return null
  }

  return `本轮将读取以下本地文件路径：\n\n${paths.join('\n')}\n\n请确认这是你主动选择或认可的素材。`
}

export function workerFailureDetailsSummary(details: Record<string, unknown> | undefined) {
  if (!details) return ''
  const lines: string[] = []
  const blockedCards = Array.isArray(details.blocked_cards) ? details.blocked_cards : []
  if (blockedCards.length > 0) {
    const sample = blockedCards
      .slice(0, 4)
      .map((failure) => {
        const item = failure && typeof failure === 'object' ? (failure as Record<string, unknown>) : {}
        const title = String(item.title || item.answer_summary || item.card_id || '未知卡')
        const sourceTime = String(item.source_time || item.segment_id || '')
        const matchedText = String(item.matched_text || '')
        return `${sourceTime ? `${sourceTime} · ` : ''}${title}${matchedText ? ` · 命中「${matchedText.slice(0, 42)}」` : ''}`
      })
      .join('；')
    lines.push(`需修复卡：${sample}${blockedCards.length > 4 ? `；另 ${blockedCards.length - 4} 张` : ''}`)
  }
  const audioFailures = Array.isArray(details.audio_failures) ? details.audio_failures : []
  if (audioFailures.length > 0) {
    const sample = audioFailures
      .slice(0, 3)
      .map((failure) => {
        const item = failure && typeof failure === 'object' ? (failure as Record<string, unknown>) : {}
        const role = String(item.role || 'tts')
        const point = String(item.learning_point_id || item.card_id || item.segment_id || '未知卡')
        const expected = String(item.expected_text || '').slice(0, 80)
        return `${point} · ${role} · 期望「${expected}」`
      })
      .join('；')
    lines.push(`失败音频：${sample}${audioFailures.length > 3 ? `；另 ${audioFailures.length - 3} 条` : ''}`)
  }
  if (typeof details.audio_audit_path === 'string' && details.audio_audit_path) {
    lines.push(`audio_audit：${details.audio_audit_path}`)
  }
  return lines.join('\n')
}

export function titleFromPath(value: string) {
  const fileName = cleanLocalPath(value).split(/[\\/]/).pop() ?? ''
  return fileName.replace(/\.[^.]+$/, '')
}

export function pathLines(value: string) {
  return value
    .split(/[\r\n]+/u)
    .map((line) => cleanLocalPath(line))
    .filter(Boolean)
}

export function mergeRepairResults(left: EnvRepairResult | null, right: EnvRepairResult): EnvRepairResult {
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

export function modelApiTestTitle(result: ApiTestResult | null, testing: boolean) {
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

export function ttsApiTestTitle(result: TtsTestResult | null, testing: boolean, enabled: boolean) {
  if (testing) return '正在测试 TTS（最长 75 秒）'
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
