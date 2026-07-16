import { describe, expect, it } from 'vitest'
import type { ApiConfig, HermesProxyStatus, TtsConfig } from '../domain/types'
import {
  DEFAULT_VERIFICATION_TTL_MS,
  advanceCredentialRevision,
  buildModelCapabilityStatus,
  buildTtsCapabilityStatus,
  createVerificationRecord,
  modelVerificationFingerprint,
  resolveVerificationCapability,
  ttsVerificationFingerprint,
} from './systemCapabilityState'

const NOW = Date.UTC(2026, 6, 15, 12)

const ttsConfig: TtsConfig = {
  enabled: true,
  provider: 'gemini',
  base_url: 'https://generativelanguage.googleapis.com/',
  api_key: 'tts-super-secret',
  model: 'gemini-2.5-flash-preview-tts',
  voice: 'Kore',
  language: 'en-US',
  sample_rate: 24_000,
  bit_rate: 128_000,
}

const apiConfig: ApiConfig = {
  provider: 'openai-compatible',
  base_url: 'https://api.example.com/v1/',
  api_key: 'model-super-secret',
  model: 'example-model',
  capabilities: ['structured_json'],
  tts_config: ttsConfig,
}

const hermesConfig: ApiConfig = {
  ...apiConfig,
  base_url: 'http://127.0.0.1:8645/v1',
  model: 'grok-4.5',
}

function hermesStatus(overrides: Partial<HermesProxyStatus> = {}): HermesProxyStatus {
  return {
    state: 'ready',
    message: 'ready',
    base_url: 'http://127.0.0.1:8645/v1',
    model: 'grok-4.5',
    managed: true,
    authenticated: true,
    ...overrides,
  }
}

describe('verification fingerprints', () => {
  it('normalizes the model endpoint and never serializes an API key', () => {
    const first = modelVerificationFingerprint(apiConfig, 'api_key')
    const second = modelVerificationFingerprint(
      { ...apiConfig, base_url: '  https://api.example.com/v1', api_key: 'a-different-secret' },
      'api_key',
    )

    expect(first).toBe(second)
    expect(first).not.toContain(apiConfig.api_key)
    expect(first).not.toContain('a-different-secret')
  })

  it('changes the model fingerprint when a verified connection field changes', () => {
    const fingerprint = modelVerificationFingerprint(apiConfig, 'api_key')

    expect(modelVerificationFingerprint({ ...apiConfig, model: 'another-model' }, 'api_key')).not.toBe(fingerprint)
    expect(modelVerificationFingerprint(apiConfig, 'gcloud')).not.toBe(fingerprint)
  })

  it('includes TTS output and credential-source settings without serializing a key', () => {
    const fingerprint = ttsVerificationFingerprint(ttsConfig, 'tts_secret')

    expect(ttsVerificationFingerprint({ ...ttsConfig, api_key: 'another-secret' }, 'tts_secret')).toBe(fingerprint)
    expect(ttsVerificationFingerprint({ ...ttsConfig, voice: 'Puck' }, 'tts_secret')).not.toBe(fingerprint)
    expect(ttsVerificationFingerprint({ ...ttsConfig, sample_rate: 48_000 }, 'tts_secret')).not.toBe(fingerprint)
    expect(ttsVerificationFingerprint(ttsConfig, 'model_secret')).not.toBe(fingerprint)
    expect(fingerprint).not.toContain(ttsConfig.api_key)
  })
})

describe('credential revisions', () => {
  it('increments only when the native secret changed', () => {
    expect(advanceCredentialRevision(4, true)).toBe(5)
    expect(advanceCredentialRevision(4, false)).toBe(4)
    expect(advanceCredentialRevision(Number.NaN, true)).toBe(1)
  })
})

describe('verification evidence resolution', () => {
  const fingerprint = modelVerificationFingerprint(apiConfig, 'api_key')

  it('accepts a matching successful verification for seven days', () => {
    const verification = createVerificationRecord({
      ok: true,
      verificationFingerprint: fingerprint,
      credentialRevision: 3,
      checkedAt: NOW - DEFAULT_VERIFICATION_TTL_MS,
      latencyMs: 120,
    })

    expect(
      resolveVerificationCapability({
        verificationFingerprint: fingerprint,
        credentialRevision: 3,
        verificationRecords: [verification],
        secretRequired: true,
        secretExists: true,
        now: NOW,
      }),
    ).toMatchObject({ state: 'ready', reason: 'verified', verification })
  })

  it('marks successful evidence stale after the TTL', () => {
    const verification = createVerificationRecord({
      ok: true,
      verificationFingerprint: fingerprint,
      credentialRevision: 3,
      checkedAt: NOW - DEFAULT_VERIFICATION_TTL_MS - 1,
    })

    expect(
      resolveVerificationCapability({
        verificationFingerprint: fingerprint,
        credentialRevision: 3,
        verificationRecords: [verification],
        secretRequired: true,
        secretExists: true,
        now: NOW,
      }),
    ).toMatchObject({ state: 'stale', reason: 'verification_expired' })
  })

  it('lets the latest explicit failure override an older success', () => {
    const passed = createVerificationRecord({
      ok: true,
      verificationFingerprint: fingerprint,
      credentialRevision: 3,
      checkedAt: NOW - 2_000,
    })
    const failed = createVerificationRecord({
      ok: false,
      verificationFingerprint: fingerprint,
      credentialRevision: 3,
      checkedAt: NOW - 1_000,
      errorCode: 'unauthorized',
    })

    expect(
      resolveVerificationCapability({
        verificationFingerprint: fingerprint,
        credentialRevision: 3,
        verificationRecords: [passed, failed],
        secretRequired: true,
        secretExists: true,
        now: NOW,
      }),
    ).toMatchObject({ state: 'blocked', reason: 'verification_failed', verification: failed })
  })

  it('prefers a failure when records share the same timestamp', () => {
    const records = [
      createVerificationRecord({
        ok: false,
        verificationFingerprint: fingerprint,
        credentialRevision: 3,
        checkedAt: NOW,
      }),
      createVerificationRecord({
        ok: true,
        verificationFingerprint: fingerprint,
        credentialRevision: 3,
        checkedAt: NOW,
      }),
    ]

    expect(
      resolveVerificationCapability({
        verificationFingerprint: fingerprint,
        credentialRevision: 3,
        verificationRecords: records,
        secretRequired: true,
        secretExists: true,
        now: NOW,
      }),
    ).toMatchObject({ state: 'blocked', reason: 'verification_failed' })
  })

  it('does not trust evidence from another config or credential revision', () => {
    const verification = createVerificationRecord({
      ok: true,
      verificationFingerprint: fingerprint,
      credentialRevision: 2,
      checkedAt: NOW,
    })

    expect(
      resolveVerificationCapability({
        verificationFingerprint: fingerprint,
        credentialRevision: 3,
        verificationRecords: [verification],
        secretRequired: true,
        secretExists: true,
        now: NOW,
      }),
    ).toMatchObject({ state: 'stale', reason: 'configuration_or_credential_changed' })
  })

  it('requires native secret existence instead of trusting profile metadata', () => {
    const verification = createVerificationRecord({
      ok: true,
      verificationFingerprint: fingerprint,
      credentialRevision: 3,
      checkedAt: NOW,
    })

    expect(
      resolveVerificationCapability({
        verificationFingerprint: fingerprint,
        credentialRevision: 3,
        verificationRecords: [verification],
        secretRequired: true,
        secretExists: false,
        now: NOW,
      }),
    ).toMatchObject({ state: 'action_required', reason: 'secret_missing' })

    expect(
      resolveVerificationCapability({
        verificationFingerprint: fingerprint,
        credentialRevision: 3,
        verificationRecords: [verification],
        secretRequired: true,
        secretExists: null,
        now: NOW,
      }),
    ).toMatchObject({ state: 'unknown', reason: 'secret_status_unknown' })
  })
})

describe('model capability', () => {
  const fingerprint = modelVerificationFingerprint(hermesConfig, 'local_oauth')
  const passed = createVerificationRecord({
    ok: true,
    verificationFingerprint: fingerprint,
    credentialRevision: 0,
    checkedAt: NOW,
  })

  it('does not let historical success hide a stopped Hermes proxy', () => {
    expect(
      buildModelCapabilityStatus({
        config: hermesConfig,
        authMode: 'local_oauth',
        credentialRevision: 0,
        secretExists: null,
        verificationRecords: [passed],
        hermesStatus: hermesStatus({ state: 'stopped', authenticated: false }),
        now: NOW,
      }),
    ).toMatchObject({ state: 'action_required', reason: 'hermes_stopped' })
  })

  it('blocks OAuth-unready Hermes even when an old test passed', () => {
    expect(
      buildModelCapabilityStatus({
        config: hermesConfig,
        authMode: 'local_oauth',
        credentialRevision: 0,
        secretExists: null,
        verificationRecords: [passed],
        hermesStatus: hermesStatus({ state: 'oauth_unready', authenticated: false }),
        now: NOW,
      }),
    ).toMatchObject({ state: 'blocked', reason: 'hermes_oauth_unready' })
  })

  it('requires both a live authenticated proxy and matching verification', () => {
    expect(
      buildModelCapabilityStatus({
        config: hermesConfig,
        authMode: 'local_oauth',
        credentialRevision: 0,
        secretExists: null,
        verificationRecords: [passed],
        hermesStatus: hermesStatus(),
        now: NOW,
      }),
    ).toMatchObject({ state: 'ready', reason: 'verified' })

    expect(
      buildModelCapabilityStatus({
        config: hermesConfig,
        authMode: 'local_oauth',
        credentialRevision: 0,
        secretExists: null,
        verificationRecords: [passed],
        hermesStatus: hermesStatus({ authenticated: false }),
        now: NOW,
      }),
    ).toMatchObject({ state: 'blocked', reason: 'hermes_oauth_unready' })
  })
})

describe('TTS capability', () => {
  it('reports a disabled TTS service explicitly', () => {
    expect(
      buildTtsCapabilityStatus({
        config: { ...ttsConfig, enabled: false, provider: 'disabled' },
        credentialSource: 'none',
        credentialRevision: 0,
        secretExists: null,
        verificationRecords: [],
        required: true,
        now: NOW,
      }),
    ).toMatchObject({ state: 'disabled', reason: 'disabled' })
  })

  it('reports an unverified non-required service as optional', () => {
    expect(
      buildTtsCapabilityStatus({
        config: ttsConfig,
        credentialSource: 'tts_secret',
        credentialRevision: 1,
        secretExists: true,
        verificationRecords: [],
        required: false,
        now: NOW,
      }),
    ).toMatchObject({ state: 'optional', reason: 'verification_missing' })
  })
})
