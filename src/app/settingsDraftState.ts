import type { ApiConfig, SavedApiProfile, SavedProfileAuth, SavedTtsProfile, TtsConfig } from '../domain/types'
import {
  apiAuthMode,
  apiConfigMatchesProfile,
  ttsAuthMode,
  ttsConfigMatchesProfile,
} from '../services/settingsProfiles'
import {
  advanceCredentialRevision,
  modelVerificationFingerprint,
  sanitizeCredentialRevision,
  ttsVerificationFingerprint,
  type CredentialSource,
} from './systemCapabilityState'

export type SettingsMode = 'simple' | 'advanced'
export type SettingsVerificationTarget = 'model' | 'tts'
export type SettingsVerificationStatus = 'idle' | 'testing' | 'passed' | 'failed' | 'stale'

export type SettingsCredentialRevisions = {
  model: number
  tts: number
}

export type SettingsDraftValues = {
  apiConfig: ApiConfig
  activeApiProfile: SavedApiProfile | null
  activeTtsProfile: SavedTtsProfile | null
  credentialRevisions: SettingsCredentialRevisions
}

export type SettingsVerificationState = {
  status: SettingsVerificationStatus
  fingerprint: string
  credentialRevision: number
  runId?: string
  checkedAt?: number
  errorCode?: string
  staleReason?: 'draft_changed' | 'draft_changed_during_test' | 'result_mismatch' | 'applied_without_verification'
}

export type PendingSettingsSave = {
  runId: string
  targets: SettingsVerificationTarget[]
  draftFingerprint: string
}

export type SettingsDraftState = {
  committed: SettingsDraftValues
  draft: SettingsDraftValues
  mode: SettingsMode
  verification: Record<SettingsVerificationTarget, SettingsVerificationState>
  pendingSave: PendingSettingsSave | null
}

type OpenSettingsDraftInput = {
  committed: SettingsDraftValues
  mode?: SettingsMode
}

type BeginSettingsVerificationInput = {
  targets: readonly SettingsVerificationTarget[]
  intent: 'test' | 'save_and_verify'
  runId: string
}

type CompleteSettingsVerificationInput = {
  target: SettingsVerificationTarget
  runId: string
  verificationFingerprint: string
  credentialRevision: number
  ok: boolean
  checkedAt?: number
  errorCode?: string
}

function cloneApiProfile(profile: SavedApiProfile | null): SavedApiProfile | null {
  return profile ? { ...profile, capabilities: [...profile.capabilities] } : null
}

function cloneTtsProfile(profile: SavedTtsProfile | null): SavedTtsProfile | null {
  return profile ? { ...profile } : null
}

function cloneApiConfig(config: ApiConfig): ApiConfig {
  return {
    ...config,
    capabilities: [...config.capabilities],
    tts_config: { ...config.tts_config },
  }
}

function cloneSettingsValues(values: SettingsDraftValues): SettingsDraftValues {
  return {
    apiConfig: cloneApiConfig(values.apiConfig),
    activeApiProfile: cloneApiProfile(values.activeApiProfile),
    activeTtsProfile: cloneTtsProfile(values.activeTtsProfile),
    credentialRevisions: {
      model: sanitizeCredentialRevision(values.credentialRevisions.model),
      tts: sanitizeCredentialRevision(values.credentialRevisions.tts),
    },
  }
}

function currentApiAuthMode(values: SettingsDraftValues): SavedProfileAuth {
  if (values.activeApiProfile && apiConfigMatchesProfile(values.apiConfig, values.activeApiProfile)) {
    return values.activeApiProfile.auth
  }
  return apiAuthMode(values.apiConfig)
}

function ttsCredentialSource(values: SettingsDraftValues): CredentialSource {
  const tts = values.apiConfig.tts_config
  const auth =
    values.activeTtsProfile && ttsConfigMatchesProfile(tts, values.activeTtsProfile)
      ? values.activeTtsProfile.auth
      : ttsAuthMode(tts)

  if (auth === 'api_key') return 'tts_secret'
  return auth
}

function hash32(value: string) {
  let hash = 2_166_136_261
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 16_777_619)
  }
  return (hash >>> 0).toString(36).padStart(7, '0')
}

/**
 * Fingerprint used to bind an asynchronous settings test to the exact draft it
 * started from. Secret values are intentionally omitted; credential revisions
 * bind secret changes without exposing the secret itself.
 */
export function settingsVerificationFingerprint(values: SettingsDraftValues, target: SettingsVerificationTarget) {
  const api = values.apiConfig
  if (target === 'model') {
    const connectionFingerprint = modelVerificationFingerprint(api, currentApiAuthMode(values))
    return `settings-model:v1:${hash32(
      JSON.stringify([
        connectionFingerprint,
        [...api.capabilities].sort(),
        api.tts_provider ?? '',
        api.tts_model ?? '',
      ]),
    )}`
  }

  const tts = api.tts_config
  const connectionFingerprint = ttsVerificationFingerprint(tts, ttsCredentialSource(values))
  return `settings-tts:v1:${hash32(JSON.stringify([connectionFingerprint, tts.output_volume ?? 0.65]))}`
}

function verificationIdentity(values: SettingsDraftValues, target: SettingsVerificationTarget) {
  return {
    fingerprint: settingsVerificationFingerprint(values, target),
    credentialRevision: sanitizeCredentialRevision(values.credentialRevisions[target]),
  }
}

export function settingsDraftFingerprint(values: SettingsDraftValues) {
  const model = verificationIdentity(values, 'model')
  const tts = verificationIdentity(values, 'tts')
  return [
    'settings-draft:v1',
    model.fingerprint,
    model.credentialRevision,
    tts.fingerprint,
    tts.credentialRevision,
  ].join(':')
}

function idleVerification(values: SettingsDraftValues, target: SettingsVerificationTarget): SettingsVerificationState {
  return {
    status: 'idle',
    ...verificationIdentity(values, target),
  }
}

export function openSettingsDraft({ committed, mode = 'simple' }: OpenSettingsDraftInput): SettingsDraftState {
  const committedCopy = cloneSettingsValues(committed)
  const draft = cloneSettingsValues(committed)
  return {
    committed: committedCopy,
    draft,
    mode,
    verification: {
      model: idleVerification(draft, 'model'),
      tts: idleVerification(draft, 'tts'),
    },
    pendingSave: null,
  }
}

function valuesEqual(left: SettingsDraftValues, right: SettingsDraftValues) {
  return JSON.stringify(left) === JSON.stringify(right)
}

export function isSettingsDraftDirty(state: SettingsDraftState) {
  return !valuesEqual(state.committed, state.draft)
}

function reconcileVerification(
  previousValues: SettingsDraftValues,
  nextValues: SettingsDraftValues,
  target: SettingsVerificationTarget,
  current: SettingsVerificationState,
): SettingsVerificationState {
  const previousIdentity = verificationIdentity(previousValues, target)
  const nextIdentity = verificationIdentity(nextValues, target)
  const changed =
    previousIdentity.fingerprint !== nextIdentity.fingerprint ||
    previousIdentity.credentialRevision !== nextIdentity.credentialRevision

  if (!changed) return current
  if (current.status === 'idle') return { status: 'idle', ...nextIdentity }
  return {
    ...current,
    status: 'stale',
    staleReason: current.status === 'testing' ? 'draft_changed_during_test' : 'draft_changed',
  }
}

function updateDraft(state: SettingsDraftState, draft: SettingsDraftValues): SettingsDraftState {
  const nextDraft = cloneSettingsValues(draft)
  const draftChanged = !valuesEqual(state.draft, nextDraft)
  if (!draftChanged) return state

  return {
    ...state,
    draft: nextDraft,
    verification: {
      model: reconcileVerification(state.draft, nextDraft, 'model', state.verification.model),
      tts: reconcileVerification(state.draft, nextDraft, 'tts', state.verification.tts),
    },
    pendingSave: null,
  }
}

function hasOwn(value: object, key: PropertyKey) {
  return Object.prototype.hasOwnProperty.call(value, key)
}

export function patchApiSettingsDraft(state: SettingsDraftState, patch: Partial<ApiConfig>): SettingsDraftState {
  const previous = state.draft.apiConfig
  const nextTts = patch.tts_config ? { ...patch.tts_config } : { ...previous.tts_config }
  const secretChanged = hasOwn(patch, 'api_key') && patch.api_key !== previous.api_key
  const ttsSecretChanged = Boolean(patch.tts_config && patch.tts_config.api_key !== previous.tts_config.api_key)
  return updateDraft(state, {
    ...state.draft,
    apiConfig: {
      ...previous,
      ...patch,
      capabilities: patch.capabilities ? [...patch.capabilities] : [...previous.capabilities],
      tts_config: nextTts,
    },
    credentialRevisions: {
      model: advanceCredentialRevision(state.draft.credentialRevisions.model, secretChanged),
      tts: advanceCredentialRevision(state.draft.credentialRevisions.tts, ttsSecretChanged),
    },
  })
}

export function patchTtsSettingsDraft(state: SettingsDraftState, patch: Partial<TtsConfig>): SettingsDraftState {
  const previous = state.draft.apiConfig.tts_config
  const secretChanged = hasOwn(patch, 'api_key') && patch.api_key !== previous.api_key
  return updateDraft(state, {
    ...state.draft,
    apiConfig: {
      ...state.draft.apiConfig,
      capabilities: [...state.draft.apiConfig.capabilities],
      tts_config: { ...previous, ...patch },
    },
    credentialRevisions: {
      ...state.draft.credentialRevisions,
      tts: advanceCredentialRevision(state.draft.credentialRevisions.tts, secretChanged),
    },
  })
}

export function selectApiProfileForDraft(state: SettingsDraftState, profile: SavedApiProfile): SettingsDraftState {
  return updateDraft(state, {
    ...state.draft,
    apiConfig: {
      ...state.draft.apiConfig,
      provider: profile.provider,
      base_url: profile.base_url,
      model: profile.model,
      capabilities: [...profile.capabilities],
      tts_config: { ...state.draft.apiConfig.tts_config },
    },
    activeApiProfile: cloneApiProfile(profile),
  })
}

export function selectTtsProfileForDraft(state: SettingsDraftState, profile: SavedTtsProfile): SettingsDraftState {
  return updateDraft(state, {
    ...state.draft,
    apiConfig: {
      ...state.draft.apiConfig,
      capabilities: [...state.draft.apiConfig.capabilities],
      tts_config: {
        ...state.draft.apiConfig.tts_config,
        enabled: profile.enabled,
        provider: profile.provider,
        base_url: profile.base_url,
        model: profile.model,
        voice: profile.voice,
        language: profile.language,
        sample_rate: profile.sample_rate,
        bit_rate: profile.bit_rate,
        output_volume: profile.output_volume,
      },
    },
    activeTtsProfile: cloneTtsProfile(profile),
  })
}

export function setSettingsDraftMode(state: SettingsDraftState, mode: SettingsMode): SettingsDraftState {
  if (state.mode === mode) return state
  return { ...state, mode }
}

function uniqueTargets(targets: readonly SettingsVerificationTarget[]) {
  return [...new Set(targets)]
}

export function beginSettingsVerification(
  state: SettingsDraftState,
  input: BeginSettingsVerificationInput,
): SettingsDraftState {
  const targets = uniqueTargets(input.targets)
  if (targets.length === 0) return state

  const verification = { ...state.verification }
  for (const target of targets) {
    verification[target] = {
      status: 'testing',
      ...verificationIdentity(state.draft, target),
      runId: input.runId,
    }
  }

  return {
    ...state,
    verification,
    pendingSave:
      input.intent === 'save_and_verify'
        ? {
            runId: input.runId,
            targets,
            draftFingerprint: settingsDraftFingerprint(state.draft),
          }
        : null,
  }
}

function finalizePendingSave(state: SettingsDraftState): SettingsDraftState {
  const pending = state.pendingSave
  if (!pending) return state

  const targetStates = pending.targets.map((target) => state.verification[target])
  if (targetStates.some((verification) => verification.status === 'testing')) return state

  const canCommit =
    targetStates.every((verification) => verification.status === 'passed') &&
    settingsDraftFingerprint(state.draft) === pending.draftFingerprint

  return {
    ...state,
    ...(canCommit ? { committed: cloneSettingsValues(state.draft) } : {}),
    pendingSave: null,
  }
}

export function cancelSettingsVerification(
  state: SettingsDraftState,
  input: { target: SettingsVerificationTarget; runId: string },
): SettingsDraftState {
  const current = state.verification[input.target]
  if (current.status !== 'testing' || current.runId !== input.runId) return state

  return {
    ...state,
    verification: {
      ...state.verification,
      [input.target]: idleVerification(state.draft, input.target),
    },
    pendingSave: state.pendingSave?.runId === input.runId ? null : state.pendingSave,
  }
}

export function completeSettingsVerification(
  state: SettingsDraftState,
  input: CompleteSettingsVerificationInput,
): SettingsDraftState {
  const current = state.verification[input.target]
  if (current.status !== 'testing' || current.runId !== input.runId) return state

  const currentIdentity = verificationIdentity(state.draft, input.target)
  const resultMatches =
    input.verificationFingerprint === current.fingerprint &&
    input.verificationFingerprint === currentIdentity.fingerprint &&
    sanitizeCredentialRevision(input.credentialRevision) === current.credentialRevision &&
    current.credentialRevision === currentIdentity.credentialRevision

  const nextVerification: SettingsVerificationState = resultMatches
    ? {
        status: input.ok ? 'passed' : 'failed',
        fingerprint: input.verificationFingerprint,
        credentialRevision: current.credentialRevision,
        runId: input.runId,
        checkedAt: Number.isFinite(input.checkedAt) ? Number(input.checkedAt) : Date.now(),
        ...(input.errorCode ? { errorCode: input.errorCode } : {}),
      }
    : {
        ...current,
        status: 'stale',
        staleReason: 'result_mismatch',
      }

  return finalizePendingSave({
    ...state,
    verification: {
      ...state.verification,
      [input.target]: nextVerification,
    },
  })
}

export function applySettingsWithoutVerification(state: SettingsDraftState): SettingsDraftState {
  const draft = cloneSettingsValues(state.draft)
  return {
    ...state,
    committed: cloneSettingsValues(draft),
    draft,
    verification: {
      model: {
        status: 'stale',
        ...verificationIdentity(draft, 'model'),
        staleReason: 'applied_without_verification',
      },
      tts: {
        status: 'stale',
        ...verificationIdentity(draft, 'tts'),
        staleReason: 'applied_without_verification',
      },
    },
    pendingSave: null,
  }
}

export type SettingsCloseDisposition = 'close' | 'confirm_discard'

export function requestSettingsClose(state: SettingsDraftState): SettingsCloseDisposition {
  return isSettingsDraftDirty(state) ? 'confirm_discard' : 'close'
}

export function discardSettingsDraft(state: SettingsDraftState): SettingsDraftState {
  const draft = cloneSettingsValues(state.committed)
  return {
    ...state,
    draft,
    verification: {
      model: idleVerification(draft, 'model'),
      tts: idleVerification(draft, 'tts'),
    },
    pendingSave: null,
  }
}
