import type { ApiConfig, TtsConfig } from '../domain/types'
import { MIMO_OPENAI_BASE_URL, MIMO_TOKEN_PLAN_SGP_BASE_URL } from '../domain/options'

export function normalizeMimoModelId(value: string) {
  const trimmed = value.trim()
  return trimmed.toLowerCase().startsWith('mimo-') ? trimmed.toLowerCase() : trimmed
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
  if (!api.api_key.trim()) return '还没有填写 API Key。'
  if (!api.model.trim()) return '还没有填写模型名。'
  return validateServiceBaseUrl(api.base_url, api.provider === 'mimo' ? 'MIMO Base URL' : '模型 Base URL')
}

export function validateTtsConfigForRequest(tts: TtsConfig): string | null {
  if (!tts.enabled || tts.provider === 'disabled') return null
  if (!tts.api_key.trim()) return '还没有填写 TTS API Key。'
  if (tts.provider !== 'grok' && !tts.model.trim()) return '还没有填写 TTS 模型。'
  if (!tts.voice.trim()) return '还没有填写 TTS voice。'
  if (tts.provider === 'gemini' && !tts.base_url.trim()) return null
  return validateServiceBaseUrl(tts.base_url, 'TTS Base URL')
}

export function resolveTtsConfig(tts: TtsConfig, api: ApiConfig): TtsConfig {
  if (tts.provider !== 'mimo') return tts

  const canReuseMainMimo = isMimoApiConfig(api) && api.api_key.trim()
  const mainApiKey = canReuseMainMimo ? api.api_key.trim() : ''
  const explicitTtsKey = tts.api_key.trim()
  const staleTokenPlanTtsKey =
    mainApiKey &&
    isMimoTokenPlanKey(mainApiKey) &&
    isMimoTokenPlanKey(explicitTtsKey) &&
    explicitTtsKey !== mainApiKey
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
  }
}
