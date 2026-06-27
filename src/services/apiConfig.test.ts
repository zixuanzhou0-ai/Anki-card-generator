import { describe, expect, it } from 'vitest'
import {
  normalizeTtsOutputVolume,
  normalizeApiConfigForRequest,
  resolveGenerateApiConfig,
  resolveTtsConfig,
  validateApiConfigForRequest,
  validateServiceBaseUrl,
  validateTtsConfigForRequest,
} from './apiConfig'

describe('validateServiceBaseUrl', () => {
  it('accepts https provider URLs', () => {
    expect(validateServiceBaseUrl('https://api.example.com/v1')).toBeNull()
  })

  it('accepts local http provider URLs for development', () => {
    expect(validateServiceBaseUrl('http://localhost:11434/v1')).toBeNull()
    expect(validateServiceBaseUrl('http://127.0.0.1:8000/v1')).toBeNull()
  })

  it('rejects non-http schemes and remote plaintext http', () => {
    expect(validateServiceBaseUrl('javascript:alert(1)')).toContain('只允许')
    expect(validateServiceBaseUrl('file:///C:/secret')).toContain('只允许')
    expect(validateServiceBaseUrl('http://api.example.com/v1')).toContain('只允许')
  })

  it('keeps Grok TTS model optional while validating key, voice, and URL', () => {
    expect(
      validateTtsConfigForRequest({
        enabled: true,
        provider: 'grok',
        base_url: 'https://api.x.ai/v1',
        api_key: 'xai-test',
        model: '',
        voice: 'Eve',
        language: 'auto',
        sample_rate: 24000,
        bit_rate: 128000,
      }),
    ).toBeNull()
  })

  it('routes MIMO Token Plan keys to the token-plan endpoint before requests', () => {
    const normalized = normalizeApiConfigForRequest({
      provider: 'mimo',
      base_url: 'https://api.xiaomimimo.com/v1',
      api_key: 'tp-test-token-plan-key',
      model: 'MiMo-V2.5-Pro',
      capabilities: ['structured_json'],
      tts_config: {
        enabled: false,
        provider: 'disabled',
        base_url: '',
        api_key: '',
        model: '',
        voice: '',
        language: 'auto',
        sample_rate: 24000,
        bit_rate: 128000,
      },
    })

    expect(normalized.base_url).toBe('https://token-plan-sgp.xiaomimimo.com/v1')
    expect(normalized.model).toBe('mimo-v2.5-pro')
  })

  it('fills empty OpenAI-compatible config with DeepSeek V4 Pro defaults before requests', () => {
    const normalized = normalizeApiConfigForRequest({
      provider: 'openai-compatible',
      base_url: '',
      api_key: 'sk-deepseek',
      model: '',
      capabilities: ['structured_json'],
      tts_config: {
        enabled: false,
        provider: 'disabled',
        base_url: '',
        api_key: '',
        model: '',
        voice: '',
        language: 'auto',
        sample_rate: 24000,
        bit_rate: 128000,
      },
    })

    expect(normalized.base_url).toBe('https://api.deepseek.com')
    expect(normalized.model).toBe('deepseek-v4-pro')
  })

  it('migrates legacy DeepSeek model names to DeepSeek V4 Pro', () => {
    const normalized = normalizeApiConfigForRequest({
      provider: 'openai-compatible',
      base_url: 'https://api.deepseek.com/v1',
      api_key: 'sk-deepseek',
      model: 'deepseek-chat',
      capabilities: ['structured_json'],
      tts_config: {
        enabled: false,
        provider: 'disabled',
        base_url: '',
        api_key: '',
        model: '',
        voice: '',
        language: 'auto',
        sample_rate: 24000,
        bit_rate: 128000,
      },
    })

    expect(normalized.base_url).toBe('https://api.deepseek.com')
    expect(normalized.model).toBe('deepseek-v4-pro')
  })

  it('allows Gemini Vertex requests to use local gcloud auth without an API key', () => {
    const normalized = normalizeApiConfigForRequest({
      provider: 'gemini-vertex',
      base_url: '',
      api_key: '',
      model: '',
      capabilities: ['structured_json'],
      tts_config: {
        enabled: false,
        provider: 'disabled',
        base_url: '',
        api_key: '',
        model: '',
        voice: '',
        language: 'auto',
        sample_rate: 24000,
        bit_rate: 128000,
      },
    })

    expect(normalized.base_url).toBe('https://aiplatform.googleapis.com')
    expect(normalized.model).toBe('gemini-3.5-flash')
    expect(validateApiConfigForRequest(normalized)).toBeNull()
  })

  it('normalizes TTS output volume with backward-compatible defaults', () => {
    expect(normalizeTtsOutputVolume(undefined)).toBe(0.65)
    expect(normalizeTtsOutputVolume(0.2)).toBe(0.4)
    expect(normalizeTtsOutputVolume(2)).toBe(1)
    expect(normalizeTtsOutputVolume(0.8)).toBe(0.8)
  })

  it('maps unavailable Gemini Vertex stable aliases to the working preview model', () => {
    const normalized = normalizeApiConfigForRequest({
      provider: 'gemini-vertex',
      base_url: 'https://aiplatform.googleapis.com',
      api_key: '',
      model: 'gemini-3.1-pro',
      capabilities: [],
      tts_config: {
        enabled: false,
        provider: 'disabled',
        base_url: '',
        api_key: '',
        model: '',
        voice: '',
        language: 'auto',
        sample_rate: 24000,
        bit_rate: 128000,
      },
    })

    expect(normalized.model).toBe('gemini-3.1-pro-preview')
    expect(validateApiConfigForRequest(normalized)).toBeNull()
  })

  it('normalizes Gemini Vertex 3.5 aliases to the official Flash model id', () => {
    const normalized = normalizeApiConfigForRequest({
      provider: 'gemini-vertex',
      base_url: 'https://aiplatform.googleapis.com',
      api_key: '',
      model: 'gemini-3.5',
      capabilities: [],
      tts_config: {
        enabled: false,
        provider: 'disabled',
        base_url: '',
        api_key: '',
        model: '',
        voice: '',
        language: 'auto',
        sample_rate: 24000,
        bit_rate: 128000,
      },
    })

    expect(normalized.model).toBe('gemini-3.5-flash')
    expect(validateApiConfigForRequest(normalized)).toBeNull()
  })

  it('rejects DashScope-shaped keys on MIMO Token Plan endpoints before a network request', () => {
    const apiMessage = validateApiConfigForRequest({
      provider: 'mimo',
      base_url: 'https://token-plan-sgp.xiaomimimo.com/v1',
      api_key: 'sk-dashscope',
      model: 'mimo-v2.5-pro',
      capabilities: ['structured_json'],
      tts_config: {
        enabled: false,
        provider: 'disabled',
        base_url: '',
        api_key: '',
        model: '',
        voice: '',
        language: 'auto',
        sample_rate: 24000,
        bit_rate: 128000,
      },
    })

    expect(apiMessage).toContain('tp-')
    expect(apiMessage).toContain('Qwen/DashScope')

    const ttsMessage = validateTtsConfigForRequest({
      enabled: true,
      provider: 'mimo',
      base_url: 'https://token-plan-sgp.xiaomimimo.com/v1',
      api_key: 'sk-dashscope',
      model: 'mimo-v2.5-tts',
      voice: 'Mia',
      language: 'auto',
      sample_rate: 24000,
      bit_rate: 128000,
    })

    expect(ttsMessage).toContain('tp-')
    expect(ttsMessage).toContain('Qwen3 TTS')
  })

  it('lets Qwen TTS reuse the main DashScope key', () => {
    const resolved = resolveTtsConfig(
      {
        enabled: true,
        provider: 'qwen',
        base_url: '',
        api_key: '',
        model: '',
        voice: '',
        language: 'auto',
        sample_rate: 24000,
        bit_rate: 128000,
      },
      {
        provider: 'openai-compatible',
        base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        api_key: 'sk-dashscope',
        model: 'qwen3.7-max',
        capabilities: ['structured_json'],
        tts_config: {
          enabled: false,
          provider: 'disabled',
          base_url: '',
          api_key: '',
          model: '',
          voice: '',
          language: 'auto',
          sample_rate: 24000,
          bit_rate: 128000,
        },
      },
    )

    expect(resolved.api_key).toBe('sk-dashscope')
    expect(resolved.base_url).toBe('https://dashscope.aliyuncs.com/api/v1')
    expect(resolved.model).toBe('qwen3-tts-flash')
    expect(resolved.voice).toBe('Jennifer')
    expect(resolved.output_volume).toBe(0.65)
  })

  it('allows Gemini Vertex TTS to use local gcloud auth without an API key', () => {
    const resolved = resolveTtsConfig(
      {
        enabled: true,
        provider: 'gemini-vertex',
        base_url: '',
        api_key: 'stale-key-should-not-be-used',
        model: '',
        voice: '',
        language: '',
        sample_rate: 24000,
        bit_rate: 128000,
      },
      {
        provider: 'gemini-vertex',
        base_url: 'https://aiplatform.googleapis.com',
        api_key: '',
        model: 'gemini-3.1-pro-preview',
        capabilities: ['structured_json'],
        tts_config: {
          enabled: false,
          provider: 'disabled',
          base_url: '',
          api_key: '',
          model: '',
          voice: '',
          language: 'auto',
          sample_rate: 24000,
          bit_rate: 128000,
        },
      },
    )

    expect(resolved.api_key).toBe('')
    expect(resolved.base_url).toBe('https://aiplatform.googleapis.com')
    expect(resolved.model).toBe('gemini-3.1-flash-tts-preview')
    expect(resolved.voice).toBe('Kore')
    expect(resolved.language).toBe('auto')
    expect(validateTtsConfigForRequest(resolved)).toBeNull()
  })

  it('allows local video generation to fall back when model API is not configured', () => {
    const resolved = resolveGenerateApiConfig(
      {
        provider: 'openai-compatible',
        base_url: 'https://api.deepseek.com/v1',
        api_key: '',
        model: 'deepseek-chat',
        capabilities: ['structured_json'],
        tts_config: {
          enabled: false,
          provider: 'disabled',
          base_url: '',
          api_key: '',
          model: '',
          voice: '',
          language: 'auto',
          sample_rate: 24000,
          bit_rate: 128000,
        },
      },
      'local',
    )

    expect(resolved.error).toBeUndefined()
    expect(resolved.fallbackReason).toContain('API Key')
    expect(resolved.api.provider).toBe('local')
    expect(resolved.api.model).toBe('local-fallback')
  })

  it('still blocks URL generation when model API is not configured', () => {
    const resolved = resolveGenerateApiConfig(
      {
        provider: 'openai-compatible',
        base_url: 'https://api.deepseek.com/v1',
        api_key: '',
        model: 'deepseek-chat',
        capabilities: ['structured_json'],
        tts_config: {
          enabled: false,
          provider: 'disabled',
          base_url: '',
          api_key: '',
          model: '',
          voice: '',
          language: 'auto',
          sample_rate: 24000,
          bit_rate: 128000,
        },
      },
      'url',
    )

    expect(resolved.error).toContain('API Key')
    expect(resolved.api.provider).toBe('openai-compatible')
  })
})
