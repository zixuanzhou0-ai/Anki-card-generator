import type { ApiConfig, TtsConfig } from '../domain/types'
import {
  DEEPSEEK_DEFAULT_MODEL,
  DEEPSEEK_OPENAI_BASE_URL,
  GEMINI_VERTEX_DEFAULT_MODEL,
  GEMINI_VERTEX_FLASH_MODEL,
  GEMINI_VERTEX_GLOBAL_BASE_URL,
  GEMINI_VERTEX_UNAVAILABLE_MODEL_ALIASES,
  GEMINI_VERTEX_TTS_DEFAULT_MODEL,
  GEMINI_VERTEX_TTS_DEFAULT_VOICE,
  GEMINI_VERTEX_TTS_GLOBAL_BASE_URL,
  MIMO_OPENAI_BASE_URL,
  MIMO_TOKEN_PLAN_SGP_BASE_URL,
  QWEN_DASHSCOPE_CN_TTS_BASE_URL,
  QWEN_TTS_DEFAULT_MODEL,
  QWEN_TTS_DEFAULT_VOICE,
} from '../domain/options'
import type { SourceMode } from '../domain/types'

export function normalizeMimoModelId(value: string) {
  const trimmed = value.trim()
  return trimmed.toLowerCase().startsWith('mimo-') ? trimmed.toLowerCase() : trimmed
}

export function normalizeDeepSeekModelId(value: string) {
  const normalized = value.trim().toLowerCase().replace(/\s+/g, '-')
  if (!normalized) return DEEPSEEK_DEFAULT_MODEL
  if (
    normalized === 'deepseek-v4' ||
    normalized === 'deepseek-v4-pro' ||
    normalized === 'deepseek-v4pro' ||
    normalized === 'deepseek-v-4-pro'
  ) {
    return DEEPSEEK_DEFAULT_MODEL
  }
  if (
    normalized === 'deepseek-v4-flash' ||
    normalized === 'deepseek-v4flash' ||
    normalized === 'deepseek-v-4-flash'
  ) {
    return 'deepseek-v4-flash'
  }
  if (normalized === 'deepseek-chat' || normalized === 'deepseek-reasoner') {
    return DEEPSEEK_DEFAULT_MODEL
  }
  return value.trim()
}

export function normalizeGeminiVertexModelId(value: string) {
  const normalized = value.trim().toLowerCase()
  if (!normalized) return GEMINI_VERTEX_DEFAULT_MODEL
  if (GEMINI_VERTEX_UNAVAILABLE_MODEL_ALIASES.has(normalized)) return GEMINI_VERTEX_DEFAULT_MODEL
  if (normalized === 'gemini-3.5' || normalized === 'gemini-3.5-flash-latest') return GEMINI_VERTEX_FLASH_MODEL
  return value.trim()
}

export function isMimoTokenPlanKey(value: string) {
  return value.trim().toLowerCase().startsWith('tp-')
}

export function isMimoTokenPlanBase(value: string) {
  return value.trim().toLowerCase().includes('token-plan-')
}

export function isMimoApiConfig(api: ApiConfig) {
  return api.provider === 'mimo' || api.base_url.toLowerCase().includes('xiaomimimo.com')
}

export function isQwenApiConfig(api: ApiConfig) {
  const baseUrl = api.base_url.toLowerCase()
  return api.provider === 'openai-compatible' && (baseUrl.includes('dashscope') || baseUrl.includes('qwencloud'))
}

export function isDeepSeekApiConfig(api: ApiConfig) {
  const baseUrl = api.base_url.toLowerCase()
  const model = api.model.trim().toLowerCase()
  return api.provider === 'openai-compatible' && (baseUrl.includes('deepseek.com') || model.startsWith('deepseek-'))
}

export function validateServiceBaseUrl(value: string, label = 'Base URL'): string | null {
  const trimmed = value.trim()
  if (!trimmed) return `${label} 不能为空。`

  let parsed: URL
  try {
    parsed = new URL(trimmed)
  } catch {
    return `${label} 不是有效 URL。`
  }

  if (parsed.protocol === 'https:') return null
  if (parsed.protocol === 'http:') {
    const host = parsed.hostname.toLowerCase()
    if (host === 'localhost' || host === '127.0.0.1' || host === '::1') return null
  }
  return `${label} 只允许 https，或本机 http://localhost / 127.0.0.1。`
}

export function validateApiConfigForRequest(api: ApiConfig): string | null {
  if (api.provider === 'local') return null
  if (api.provider !== 'gemini-vertex' && !api.api_key.trim()) return '还没有填写 API Key。'
  if (!api.model.trim()) return '还没有填写模型名。'
  if (api.provider === 'gemini-vertex') {
    return api.base_url.trim() ? validateServiceBaseUrl(api.base_url, 'Vertex AI Base URL') : null
  }
  if (api.provider === 'gemini') return null
  if (api.provider === 'claude' && !api.base_url.trim()) return null
  if (isMimoApiConfig(api) && isMimoTokenPlanBase(api.base_url) && !isMimoTokenPlanKey(api.api_key)) {
    return 'MIMO Token Plan Base URL 需要 tp- 开头的 Token Plan Key。当前 Key 更像 DashScope / OpenAI-compatible Key，请切换到 Qwen/DashScope 预设，或改用匹配的 MIMO Key。'
  }
  return validateServiceBaseUrl(api.base_url, api.provider === 'mimo' ? 'MIMO Base URL' : '模型 Base URL')
}

export function localFallbackApiConfig(api: ApiConfig): ApiConfig {
  return {
    ...api,
    provider: 'local',
    base_url: '',
    api_key: '',
    model: 'local-fallback',
    capabilities: ['structured_json'],
  }
}

export function resolveGenerateApiConfig(api: ApiConfig, sourceMode: SourceMode) {
  const normalized = normalizeApiConfigForRequest(api)
  const error = validateApiConfigForRequest(normalized)
  if (!error) {
    return { api: normalized, fallbackReason: '' }
  }
  if (sourceMode === 'local') {
    return {
      api: localFallbackApiConfig(normalized),
      fallbackReason: error,
    }
  }
  return { api: normalized, error }
}

export function normalizeApiConfigForRequest(api: ApiConfig): ApiConfig {
  if (api.provider === 'claude' || api.provider === 'gemini' || api.provider === 'local') return api

  if (api.provider === 'gemini-vertex') {
    return {
      ...api,
      base_url: api.base_url.trim() || GEMINI_VERTEX_GLOBAL_BASE_URL,
      model: normalizeGeminiVertexModelId(api.model),
      capabilities: Array.from(new Set([...(api.capabilities ?? []), 'structured_json', 'long_context'])),
    }
  }

  if (isDeepSeekApiConfig(api) || (api.provider === 'openai-compatible' && !api.base_url.trim() && !api.model.trim())) {
    return {
      ...api,
      base_url: api.base_url.toLowerCase().includes('deepseek.com')
        ? DEEPSEEK_OPENAI_BASE_URL
        : api.base_url.trim() || DEEPSEEK_OPENAI_BASE_URL,
      model: normalizeDeepSeekModelId(api.model),
    }
  }

  if (isMimoApiConfig(api)) {
    const apiKey = api.api_key.trim()
    let baseUrl = api.base_url.trim()
    if (!baseUrl) {
      baseUrl = isMimoTokenPlanKey(apiKey) ? MIMO_TOKEN_PLAN_SGP_BASE_URL : MIMO_OPENAI_BASE_URL
    }
    if (isMimoTokenPlanKey(apiKey) && !isMimoTokenPlanBase(baseUrl)) {
      baseUrl = MIMO_TOKEN_PLAN_SGP_BASE_URL
    }

    return {
      ...api,
      base_url: baseUrl,
      model: normalizeMimoModelId(api.model || 'mimo-v2.5-pro'),
    }
  }

  return api
}

export function validateTtsConfigForRequest(tts: TtsConfig): string | null {
  if (!tts.enabled || tts.provider === 'disabled') return null
  if (tts.provider !== 'gemini-vertex' && !tts.api_key.trim()) return '还没有填写 TTS API Key。'
  if (tts.provider !== 'grok' && !tts.model.trim()) return '还没有填写 TTS 模型。'
  if (!tts.voice.trim()) return '还没有填写 TTS voice。'
  if (tts.provider === 'gemini-vertex') {
    return tts.base_url.trim() ? validateServiceBaseUrl(tts.base_url, 'Vertex TTS Base URL') : null
  }
  if (tts.provider === 'gemini' && !tts.base_url.trim()) return null
  if (tts.provider === 'mimo' && isMimoTokenPlanBase(tts.base_url) && !isMimoTokenPlanKey(tts.api_key)) {
    return 'MIMO Token Plan TTS Base URL 需要 tp- 开头的 Token Plan Key。当前 Key 更像 DashScope / OpenAI-compatible Key，请切换到 Qwen3 TTS 预设，或改用匹配的 MIMO TTS Key。'
  }
  return validateServiceBaseUrl(tts.base_url, 'TTS Base URL')
}

export function normalizeTtsOutputVolume(value: unknown): number {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return 0.65
  return Math.min(1, Math.max(0.4, numeric))
}

export function resolveTtsConfig(tts: TtsConfig, api: ApiConfig): TtsConfig {
  const output_volume = normalizeTtsOutputVolume(tts.output_volume)

  if (tts.provider === 'gemini-vertex') {
    return {
      ...tts,
      api_key: '',
      base_url: tts.base_url.trim() || GEMINI_VERTEX_TTS_GLOBAL_BASE_URL,
      model: tts.model.trim() || GEMINI_VERTEX_TTS_DEFAULT_MODEL,
      voice: tts.voice.trim() || GEMINI_VERTEX_TTS_DEFAULT_VOICE,
      language: tts.language.trim() || 'auto',
      output_volume,
    }
  }

  if (tts.provider === 'qwen') {
    const canReuseMainQwen = isQwenApiConfig(api) && api.api_key.trim()
    return {
      ...tts,
      api_key: tts.api_key.trim() || (canReuseMainQwen ? api.api_key.trim() : ''),
      base_url: tts.base_url.trim() || QWEN_DASHSCOPE_CN_TTS_BASE_URL,
      model: tts.model || QWEN_TTS_DEFAULT_MODEL,
      voice: tts.voice || QWEN_TTS_DEFAULT_VOICE,
      output_volume,
    }
  }

  if (tts.provider !== 'mimo') return { ...tts, output_volume }

  const canReuseMainMimo = isMimoApiConfig(api) && api.api_key.trim()
  const mainApiKey = canReuseMainMimo ? api.api_key.trim() : ''
  const explicitTtsKey = tts.api_key.trim()
  const staleTokenPlanTtsKey =
    mainApiKey && isMimoTokenPlanKey(mainApiKey) && isMimoTokenPlanKey(explicitTtsKey) && explicitTtsKey !== mainApiKey
  const apiKey = staleTokenPlanTtsKey ? mainApiKey : explicitTtsKey || mainApiKey
  let baseUrl = tts.base_url.trim()

  if (!baseUrl && canReuseMainMimo) {
    baseUrl = api.base_url.trim()
  }
  if (!baseUrl) {
    baseUrl = isMimoTokenPlanKey(apiKey) ? MIMO_TOKEN_PLAN_SGP_BASE_URL : MIMO_OPENAI_BASE_URL
  }
  if (isMimoTokenPlanKey(apiKey) && !isMimoTokenPlanBase(baseUrl)) {
    baseUrl = MIMO_TOKEN_PLAN_SGP_BASE_URL
  }

  return {
    ...tts,
    api_key: apiKey,
    base_url: baseUrl,
    model: normalizeMimoModelId(tts.model || 'mimo-v2.5-tts'),
    voice: tts.voice || 'Mia',
    output_volume,
  }
}
