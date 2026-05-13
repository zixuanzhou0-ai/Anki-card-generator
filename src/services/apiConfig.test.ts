import { describe, expect, it } from 'vitest'
import {
  normalizeApiConfigForRequest,
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
})
