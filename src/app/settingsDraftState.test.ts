import { describe, expect, it } from 'vitest'
import type { ApiConfig, SavedApiProfile, SavedTtsProfile } from '../domain/types'
import {
  applySettingsWithoutVerification,
  beginSettingsVerification,
  cancelSettingsVerification,
  completeSettingsVerification,
  discardSettingsDraft,
  isSettingsDraftDirty,
  openSettingsDraft,
  patchApiSettingsDraft,
  patchTtsSettingsDraft,
  requestSettingsClose,
  selectApiProfileForDraft,
  selectTtsProfileForDraft,
  setSettingsDraftMode,
  settingsDraftFingerprint,
  settingsVerificationFingerprint,
  type SettingsDraftState,
  type SettingsDraftValues,
  type SettingsVerificationTarget,
} from './settingsDraftState'

const MODEL_SECRET = 'model-secret-that-must-not-leak'
const TTS_SECRET = 'tts-secret-that-must-not-leak'

const apiConfig: ApiConfig = {
  provider: 'openai-compatible',
  base_url: 'https://api.example.com/v1/',
  api_key: MODEL_SECRET,
  model: 'example-model',
  capabilities: ['structured_json'],
  tts_config: {
    enabled: true,
    provider: 'gemini',
    base_url: 'https://generativelanguage.googleapis.com/',
    api_key: TTS_SECRET,
    model: 'gemini-2.5-flash-preview-tts',
    voice: 'Kore',
    language: 'en-US',
    sample_rate: 24_000,
    bit_rate: 128_000,
    output_volume: 0.65,
  },
}

function values(): SettingsDraftValues {
  return {
    apiConfig: {
      ...apiConfig,
      capabilities: [...apiConfig.capabilities],
      tts_config: { ...apiConfig.tts_config },
    },
    activeApiProfile: null,
    activeTtsProfile: null,
    credentialRevisions: { model: 2, tts: 4 },
  }
}

function state() {
  return openSettingsDraft({ committed: values() })
}

function completeCurrent(current: SettingsDraftState, target: SettingsVerificationTarget, runId: string, ok = true) {
  const attempt = current.verification[target]
  return completeSettingsVerification(current, {
    target,
    runId,
    verificationFingerprint: attempt.fingerprint,
    credentialRevision: attempt.credentialRevision,
    ok,
    checkedAt: Date.UTC(2026, 6, 15, 12),
  })
}

describe('settings transaction draft', () => {
  it('opens with an isolated committed-to-draft copy and patches only the draft', () => {
    const committed = values()
    const opened = openSettingsDraft({ committed })
    const patched = patchApiSettingsDraft(opened, {
      model: 'new-model',
      capabilities: ['structured_json', 'long_context'],
    })

    expect(patched.draft.apiConfig.model).toBe('new-model')
    expect(patched.committed.apiConfig.model).toBe('example-model')
    expect(committed.apiConfig.model).toBe('example-model')
    expect(patched.draft.apiConfig.capabilities).toEqual(['structured_json', 'long_context'])
    expect(patched.committed.apiConfig.capabilities).toEqual(['structured_json'])
    expect(patched.draft.apiConfig).not.toBe(patched.committed.apiConfig)
    expect(isSettingsDraftDirty(patched)).toBe(true)
  })

  it('binds tests without placing model or TTS secrets in fingerprints', () => {
    const original = values()
    const keysChangedWithoutRevision = values()
    keysChangedWithoutRevision.apiConfig.api_key = 'another-model-secret'
    keysChangedWithoutRevision.apiConfig.tts_config.api_key = 'another-tts-secret'

    expect(settingsVerificationFingerprint(original, 'model')).toBe(
      settingsVerificationFingerprint(keysChangedWithoutRevision, 'model'),
    )
    expect(settingsVerificationFingerprint(original, 'tts')).toBe(
      settingsVerificationFingerprint(keysChangedWithoutRevision, 'tts'),
    )
    expect(settingsDraftFingerprint(original)).toBe(settingsDraftFingerprint(keysChangedWithoutRevision))

    for (const fingerprint of [
      settingsVerificationFingerprint(original, 'model'),
      settingsVerificationFingerprint(original, 'tts'),
      settingsDraftFingerprint(original),
    ]) {
      expect(fingerprint).not.toContain(MODEL_SECRET)
      expect(fingerprint).not.toContain(TTS_SECRET)
    }

    const secretPatched = patchApiSettingsDraft(state(), { api_key: 'replacement-secret' })
    expect(secretPatched.draft.credentialRevisions.model).toBe(3)
    expect(settingsDraftFingerprint(secretPatched.draft)).not.toBe(settingsDraftFingerprint(values()))
  })

  it('marks an in-flight result stale when its draft changes and never commits the old result', () => {
    const dirty = patchApiSettingsDraft(state(), { model: 'candidate-model' })
    const testing = beginSettingsVerification(dirty, {
      targets: ['model'],
      intent: 'save_and_verify',
      runId: 'model-run-1',
    })
    const oldAttempt = testing.verification.model
    const changed = patchApiSettingsDraft(testing, { capabilities: ['structured_json', 'long_context'] })

    expect(changed.verification.model).toMatchObject({
      status: 'stale',
      staleReason: 'draft_changed_during_test',
    })
    expect(changed.pendingSave).toBeNull()

    const lateResult = completeSettingsVerification(changed, {
      target: 'model',
      runId: 'model-run-1',
      verificationFingerprint: oldAttempt.fingerprint,
      credentialRevision: oldAttempt.credentialRevision,
      ok: true,
    })
    expect(lateResult.verification.model.status).toBe('stale')
    expect(lateResult.committed.apiConfig.model).toBe('example-model')
    expect(isSettingsDraftDirty(lateResult)).toBe(true)
  })

  it('commits save-and-verify only after every bound target succeeds', () => {
    const withModel = patchApiSettingsDraft(state(), { model: 'verified-model' })
    const dirty = patchTtsSettingsDraft(withModel, { voice: 'Puck' })
    const testing = beginSettingsVerification(dirty, {
      targets: ['model', 'tts'],
      intent: 'save_and_verify',
      runId: 'save-run-1',
    })

    const afterModel = completeCurrent(testing, 'model', 'save-run-1')
    expect(afterModel.committed.apiConfig.model).toBe('example-model')
    expect(afterModel.pendingSave).not.toBeNull()

    const afterTts = completeCurrent(afterModel, 'tts', 'save-run-1')
    expect(afterTts.committed.apiConfig.model).toBe('verified-model')
    expect(afterTts.committed.apiConfig.tts_config.voice).toBe('Puck')
    expect(afterTts.verification.model.status).toBe('passed')
    expect(afterTts.verification.tts.status).toBe('passed')
    expect(afterTts.pendingSave).toBeNull()
    expect(isSettingsDraftDirty(afterTts)).toBe(false)
  })

  it('keeps the committed configuration unchanged when save-and-verify fails', () => {
    const dirty = patchApiSettingsDraft(state(), { model: 'broken-model' })
    const testing = beginSettingsVerification(dirty, {
      targets: ['model'],
      intent: 'save_and_verify',
      runId: 'failed-save',
    })
    const failed = completeCurrent(testing, 'model', 'failed-save', false)

    expect(failed.verification.model.status).toBe('failed')
    expect(failed.committed.apiConfig.model).toBe('example-model')
    expect(failed.draft.apiConfig.model).toBe('broken-model')
    expect(failed.pendingSave).toBeNull()
    expect(isSettingsDraftDirty(failed)).toBe(true)
  })

  it('cancels only the exact in-flight verification without committing or recording a failure', () => {
    const dirty = patchTtsSettingsDraft(patchApiSettingsDraft(state(), { model: 'cancelled-model' }), {
      voice: 'Puck',
    })
    const testing = beginSettingsVerification(dirty, {
      targets: ['model', 'tts'],
      intent: 'save_and_verify',
      runId: 'cancelled-save',
    })

    const cancelled = cancelSettingsVerification(testing, {
      target: 'model',
      runId: 'cancelled-save',
    })

    expect(cancelled.verification.model).toEqual({
      status: 'idle',
      fingerprint: settingsVerificationFingerprint(cancelled.draft, 'model'),
      credentialRevision: cancelled.draft.credentialRevisions.model,
    })
    expect(cancelled.verification.tts).toEqual(testing.verification.tts)
    expect(cancelled.pendingSave).toBeNull()
    expect(cancelled.committed).toEqual(testing.committed)
    expect(cancelled.committed.apiConfig.model).toBe('example-model')
    expect(cancelled.draft.apiConfig.model).toBe('cancelled-model')
    expect(isSettingsDraftDirty(cancelled)).toBe(true)
  })

  it('ignores cancellation from a stale run or a target that is not testing', () => {
    const testing = beginSettingsVerification(state(), {
      targets: ['model'],
      intent: 'test',
      runId: 'current-run',
    })

    expect(
      cancelSettingsVerification(testing, {
        target: 'model',
        runId: 'stale-run',
      }),
    ).toBe(testing)
    expect(
      cancelSettingsVerification(testing, {
        target: 'tts',
        runId: 'current-run',
      }),
    ).toBe(testing)
  })

  it('rejects a result whose fingerprint does not match the started test', () => {
    const dirty = patchApiSettingsDraft(state(), { model: 'candidate-model' })
    const testing = beginSettingsVerification(dirty, {
      targets: ['model'],
      intent: 'save_and_verify',
      runId: 'mismatched-result',
    })
    const mismatched = completeSettingsVerification(testing, {
      target: 'model',
      runId: 'mismatched-result',
      verificationFingerprint: 'settings-model:v1:not-the-started-draft',
      credentialRevision: testing.verification.model.credentialRevision,
      ok: true,
    })

    expect(mismatched.verification.model).toMatchObject({ status: 'stale', staleReason: 'result_mismatch' })
    expect(mismatched.committed.apiConfig.model).toBe('example-model')
    expect(mismatched.pendingSave).toBeNull()
  })

  it('applies a draft for later verification while marking both capabilities stale', () => {
    const dirty = patchTtsSettingsDraft(patchApiSettingsDraft(state(), { model: 'later-model' }), {
      voice: 'Charon',
    })
    const applied = applySettingsWithoutVerification(dirty)

    expect(applied.committed.apiConfig.model).toBe('later-model')
    expect(applied.committed.apiConfig.tts_config.voice).toBe('Charon')
    expect(applied.verification.model).toMatchObject({
      status: 'stale',
      staleReason: 'applied_without_verification',
    })
    expect(applied.verification.tts.status).toBe('stale')
    expect(isSettingsDraftDirty(applied)).toBe(false)
  })

  it('requires confirmation before closing a dirty draft and can discard it', () => {
    const dirty = patchApiSettingsDraft(state(), { base_url: 'https://next.example.com/v1' })

    expect(requestSettingsClose(dirty)).toBe('confirm_discard')
    const discarded = discardSettingsDraft(dirty)
    expect(discarded.draft.apiConfig.base_url).toBe('https://api.example.com/v1/')
    expect(isSettingsDraftDirty(discarded)).toBe(false)
    expect(requestSettingsClose(discarded)).toBe('close')
  })

  it('switches simple and advanced modes without clearing or applying draft fields', () => {
    const dirty = patchTtsSettingsDraft(patchApiSettingsDraft(state(), { base_url: 'https://custom.test/v1' }), {
      voice: 'Aoede',
      sample_rate: 48_000,
    })
    const advanced = setSettingsDraftMode(dirty, 'advanced')
    const simpleAgain = setSettingsDraftMode(advanced, 'simple')

    expect(advanced.draft.apiConfig.base_url).toBe('https://custom.test/v1')
    expect(simpleAgain.draft.apiConfig.tts_config).toMatchObject({ voice: 'Aoede', sample_rate: 48_000 })
    expect(simpleAgain.committed.apiConfig.base_url).toBe('https://api.example.com/v1/')
    expect(isSettingsDraftDirty(simpleAgain)).toBe(true)
  })

  it('loads saved profiles into the draft without copying or erasing secret values', () => {
    const apiProfile: SavedApiProfile = {
      id: 'api_profile',
      label: 'Saved model',
      provider: 'openai-compatible',
      base_url: 'https://saved.example.com/v1',
      model: 'saved-model',
      capabilities: ['structured_json', 'long_context'],
      auth: 'api_key',
      has_api_key: true,
      updated_at: '2026-07-15T00:00:00.000Z',
      last_test_ok: true,
    }
    const ttsProfile: SavedTtsProfile = {
      id: 'tts_profile',
      label: 'Saved TTS',
      enabled: true,
      provider: 'gemini',
      base_url: 'https://tts.example.com/v1',
      model: 'saved-tts',
      voice: 'Puck',
      language: 'en-US',
      sample_rate: 24_000,
      bit_rate: 128_000,
      auth: 'api_key',
      has_api_key: true,
      updated_at: '2026-07-15T00:00:00.000Z',
      last_test_ok: true,
    }

    const selected = selectTtsProfileForDraft(selectApiProfileForDraft(state(), apiProfile), ttsProfile)
    expect(selected.draft.apiConfig).toMatchObject({
      base_url: 'https://saved.example.com/v1',
      model: 'saved-model',
      api_key: MODEL_SECRET,
    })
    expect(selected.draft.apiConfig.tts_config).toMatchObject({
      base_url: 'https://tts.example.com/v1',
      model: 'saved-tts',
      voice: 'Puck',
      api_key: TTS_SECRET,
    })
    expect(selected.draft.activeApiProfile).toEqual(apiProfile)
    expect(selected.draft.activeApiProfile).not.toBe(apiProfile)
    expect(selected.committed.activeApiProfile).toBeNull()
  })

  it('invalidates only the capability whose draft changed during parallel tests', () => {
    const testing = beginSettingsVerification(state(), {
      targets: ['model', 'tts'],
      intent: 'test',
      runId: 'parallel-test',
    })
    const changed = patchTtsSettingsDraft(testing, { voice: 'Puck' })

    expect(changed.verification.model.status).toBe('testing')
    expect(changed.verification.tts).toMatchObject({
      status: 'stale',
      staleReason: 'draft_changed_during_test',
    })
  })
})
