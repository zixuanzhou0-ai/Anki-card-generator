import { describe, expect, it } from 'vitest'

import type { ApiConfig, ApiPreset } from '../domain/types'
import { apiAuthMode, buildSavedApiProfile } from './settingsProfiles'

const hermesApi: ApiConfig = {
  provider: 'openai-compatible',
  base_url: 'http://127.0.0.1:8645/v1',
  api_key: '',
  model: 'grok-4.5',
  capabilities: ['structured_json', 'long_context'],
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
}

const hermesPreset: ApiPreset = {
  id: 'hermes-grok-45',
  label: 'Hermes · Grok 4.5（本机 OAuth）',
  provider: 'openai-compatible',
  base_url: 'http://127.0.0.1:8645/v1',
  model: 'grok-4.5',
  capabilities: ['structured_json', 'long_context'],
  note: '本机 OAuth',
  key_hint: '不需要 API Key',
}

describe('Hermes settings profile', () => {
  it('uses local OAuth and never claims an API key was saved', () => {
    expect(apiAuthMode(hermesApi)).toBe('local_oauth')
    expect(buildSavedApiProfile(hermesApi, [hermesPreset])).toMatchObject({
      label: hermesPreset.label,
      auth: 'local_oauth',
      has_api_key: false,
    })
  })
})