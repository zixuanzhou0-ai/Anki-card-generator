import { beforeEach, describe, expect, it } from 'vitest'

import type { ApiConfig, ApiPreset } from '../domain/types'
import {
  API_PROFILES_STORAGE_KEY,
  LEGACY_API_PROFILES_STORAGE_KEY,
  advanceApiProfileCredentialRevision,
  apiAuthMode,
  apiProfileVerificationTarget,
  buildSavedApiProfile,
  buildSavedTtsProfile,
  loadSavedApiProfiles,
  recordApiProfileVerification,
  recordTtsProfileVerification,
  removeSavedApiProfileCredential,
  removeSavedTtsProfileCredential,
  resolveSavedApiProfileVerification,
  resolveSavedTtsProfileVerification,
  saveSavedApiProfiles,
  ttsProfileVerificationTarget,
} from './settingsProfiles'

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

const NOW = Date.UTC(2026, 6, 15, 12)

const remoteApi: ApiConfig = {
  ...hermesApi,
  base_url: 'https://api.example.com/v1',
  api_key: 'model-secret',
  model: 'example-model',
}

describe('persisted settings verification evidence', () => {
  beforeEach(() => {
    window.localStorage.clear()
  })

  it('migrates a legacy last_test_ok=true flag as stale evidence instead of ready', () => {
    const built = buildSavedApiProfile(remoteApi, [])
    const legacy: Record<string, unknown> = { ...built, last_test_ok: true }
    legacy.api_key = 'legacy-profile-secret'
    legacy.oauth_token = 'legacy-oauth-token'
    delete legacy.verification_schema_version
    delete legacy.credential_revision
    delete legacy.verification_records
    window.localStorage.setItem(LEGACY_API_PROFILES_STORAGE_KEY, JSON.stringify([legacy]))

    const [loaded] = loadSavedApiProfiles()
    expect(loaded.last_test_ok).toBeUndefined()
    expect(loaded.verification_records).toHaveLength(1)
    expect(loaded.verification_records[0].verificationFingerprint).toContain('legacy:v1:')
    expect(
      resolveSavedApiProfileVerification(loaded, {
        secretExists: true,
        now: NOW,
      }),
    ).toMatchObject({ state: 'stale', reason: 'configuration_or_credential_changed' })

    const migratedStorage = window.localStorage.getItem(API_PROFILES_STORAGE_KEY)
    expect(migratedStorage).toBeTruthy()
    expect(migratedStorage).not.toContain('model-secret')
    expect(migratedStorage).not.toContain('legacy-profile-secret')
    expect(migratedStorage).not.toContain('legacy-oauth-token')
  })

  it('accepts only a result bound to the profile fingerprint and credential revision', () => {
    const storedConfig = { ...remoteApi, api_key: '' }
    const profile = buildSavedApiProfile(remoteApi, [])
    const target = apiProfileVerificationTarget(storedConfig, profile)
    const verified = recordApiProfileVerification(profile, { ok: true, latency_ms: 80 }, target, NOW)

    expect(
      resolveSavedApiProfileVerification(verified, {
        secretExists: true,
        now: NOW,
      }),
    ).toMatchObject({ state: 'ready', reason: 'verified' })

    const mismatched = recordApiProfileVerification(
      verified,
      { ok: true },
      { ...target, verificationFingerprint: 'model:v1:another-config' },
      NOW + 1,
    )
    expect(mismatched.verification_records).toEqual(verified.verification_records)
  })

  it('lets the latest persisted failure override an older success', () => {
    const storedConfig = { ...remoteApi, api_key: '' }
    const profile = buildSavedApiProfile(remoteApi, [])
    const target = apiProfileVerificationTarget(storedConfig, profile)
    const passed = recordApiProfileVerification(profile, { ok: true }, target, NOW - 2_000)
    const failed = recordApiProfileVerification(
      passed,
      { ok: false, error_code: 'MODEL_AUTH_FAILED', retryable: false },
      target,
      NOW - 1_000,
    )
    saveSavedApiProfiles([failed])
    const [reloaded] = loadSavedApiProfiles()

    expect(
      resolveSavedApiProfileVerification(reloaded, {
        secretExists: true,
        now: NOW,
      }),
    ).toMatchObject({
      state: 'blocked',
      reason: 'verification_failed',
      verification: { status: 'failed', errorCode: 'MODEL_AUTH_FAILED' },
    })
  })

  it('invalidates prior evidence when the stored credential revision advances', () => {
    const storedConfig = { ...remoteApi, api_key: '' }
    const profile = buildSavedApiProfile(remoteApi, [])
    const target = apiProfileVerificationTarget(storedConfig, profile)
    const passed = recordApiProfileVerification(profile, { ok: true }, target, NOW)
    const replacedSecret = advanceApiProfileCredentialRevision(passed)

    expect(replacedSecret.credential_revision).toBe(passed.credential_revision + 1)
    expect(
      resolveSavedApiProfileVerification(replacedSecret, {
        secretExists: true,
        now: NOW,
      }),
    ).toMatchObject({ state: 'stale', reason: 'configuration_or_credential_changed' })
  })

  it('removes an API credential without deleting its profile and invalidates old verification', () => {
    const storedConfig = { ...remoteApi, api_key: '' }
    const profile = buildSavedApiProfile(remoteApi, [])
    const target = apiProfileVerificationTarget(storedConfig, profile)
    const verified = recordApiProfileVerification(profile, { ok: true }, target, NOW)
    const removed = removeSavedApiProfileCredential(verified)

    expect(removed).toMatchObject({
      id: verified.id,
      label: verified.label,
      has_api_key: false,
      credential_revision: verified.credential_revision + 1,
      verification_records: [],
    })
    expect(resolveSavedApiProfileVerification(removed, { secretExists: false, now: NOW })).toMatchObject({
      state: 'action_required',
      reason: 'secret_missing',
    })
  })

  it('removes a TTS credential without deleting its profile and invalidates old verification', () => {
    const ttsWithSecret = {
      ...remoteApi.tts_config,
      enabled: true,
      provider: 'gemini' as const,
      base_url: 'https://tts.example.com/v1',
      api_key: 'tts-secret',
      model: 'tts-model',
      voice: 'Kore',
    }
    const profile = buildSavedTtsProfile(ttsWithSecret, [])
    const storedTts = { ...ttsWithSecret, api_key: '' }
    const target = ttsProfileVerificationTarget(storedTts, profile)
    const verified = recordTtsProfileVerification(profile, { ok: true }, target, NOW)
    const removed = removeSavedTtsProfileCredential(verified)

    expect(removed).toMatchObject({
      id: verified.id,
      label: verified.label,
      has_api_key: false,
      credential_revision: verified.credential_revision + 1,
      verification_records: [],
    })
    expect(resolveSavedTtsProfileVerification(removed, { secretExists: false, now: NOW })).toMatchObject({
      state: 'action_required',
      reason: 'secret_missing',
    })
  })
  it('persists and resolves TTS evidence with the same binding rules', () => {
    const ttsWithSecret = {
      ...remoteApi.tts_config,
      enabled: true,
      provider: 'gemini' as const,
      base_url: 'https://tts.example.com/v1',
      api_key: 'tts-secret',
      model: 'tts-model',
      voice: 'Kore',
    }
    const profile = buildSavedTtsProfile(ttsWithSecret, [])
    const storedTts = { ...ttsWithSecret, api_key: '' }
    const target = ttsProfileVerificationTarget(storedTts, profile)
    const verified = recordTtsProfileVerification(profile, { ok: true }, target, NOW)

    expect(
      resolveSavedTtsProfileVerification(verified, {
        secretExists: true,
        now: NOW,
      }),
    ).toMatchObject({ state: 'ready', reason: 'verified' })
    expect(ttsProfileVerificationTarget({ ...storedTts, voice: 'Puck' }, profile).verificationFingerprint).not.toBe(
      target.verificationFingerprint,
    )
  })
})
