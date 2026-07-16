import type {
  ApiConfig,
  ApiPreset,
  HermesProxyStatus,
  SavedApiProfile,
  SavedProfileAuth,
  SavedTtsProfile,
  TtsConfig,
  TtsPreset,
} from '../domain/types'
import { migrateLegacyProfileVerification } from '../app/settingsProfileMigration'
import {
  advanceCredentialRevision,
  buildModelCapabilityStatus,
  buildTtsCapabilityStatus,
  createVerificationRecord,
  modelVerificationFingerprint,
  sanitizeCredentialRevision,
  ttsVerificationFingerprint,
  type CredentialSource,
  type ServiceCapabilityStatus,
  type VerificationRecord,
} from '../app/systemCapabilityState'
import { isHermesLocalApiConfig } from './apiConfig'

export const LEGACY_API_PROFILES_STORAGE_KEY = 'anki-card-generator.api-profiles.v1'
export const LEGACY_TTS_PROFILES_STORAGE_KEY = 'anki-card-generator.tts-profiles.v1'
export const API_PROFILES_STORAGE_KEY = 'anki-card-generator.api-profiles.v2'
export const TTS_PROFILES_STORAGE_KEY = 'anki-card-generator.tts-profiles.v2'

export type PersistedProfileVerification = {
  verification_schema_version: 1
  credential_revision: number
  verification_records: VerificationRecord[]
}

export type PersistedSavedApiProfile = SavedApiProfile & PersistedProfileVerification
export type PersistedSavedTtsProfile = SavedTtsProfile & PersistedProfileVerification

export type ProfileVerificationTarget = {
  verificationFingerprint: string
  credentialRevision: number
}

function hashProfileKey(value: string) {
  let hash = 2166136261
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return (hash >>> 0).toString(36)
}

function normalizeUrl(value: string) {
  return value.trim().replace(/\/+$/, '')
}

function sameStringList(left: string[], right: string[]) {
  const a = [...left].sort()
  const b = [...right].sort()
  return a.length === b.length && a.every((item, index) => item === b[index])
}

type StorageArrayRead = {
  found: boolean
  items: unknown[]
}

function readStorageArray(key: string): StorageArrayRead {
  if (typeof window === 'undefined') return { found: false, items: [] }
  try {
    const serialized = window.localStorage.getItem(key)
    if (serialized === null) return { found: false, items: [] }
    const parsed = JSON.parse(serialized)
    return { found: true, items: Array.isArray(parsed) ? parsed : [] }
  } catch {
    return { found: true, items: [] }
  }
}

function writeStorageArray<T>(key: string, value: readonly T[]) {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(key, JSON.stringify(value))
}

export function apiAuthMode(api: Pick<ApiConfig, 'base_url' | 'model' | 'provider'>): SavedProfileAuth {
  if (api.provider === 'local') return 'none'
  if (api.provider === 'gemini-vertex') return 'gcloud'
  if (isHermesLocalApiConfig(api)) return 'local_oauth'
  return 'api_key'
}

export function ttsAuthMode(tts: Pick<TtsConfig, 'enabled' | 'provider'>): SavedProfileAuth {
  if (!tts.enabled || tts.provider === 'disabled') return 'none'
  if (tts.provider === 'gemini-vertex') return 'gcloud'
  return 'api_key'
}

export function apiProfileIdFromConfig(api: Pick<ApiConfig, 'base_url' | 'model' | 'provider'>) {
  return `api_${hashProfileKey([api.provider, normalizeUrl(api.base_url), api.model.trim()].join('|'))}`
}

export function ttsProfileIdFromConfig(tts: Pick<TtsConfig, 'base_url' | 'model' | 'provider' | 'voice'>) {
  return `tts_${hashProfileKey([tts.provider, normalizeUrl(tts.base_url), tts.model.trim(), tts.voice.trim()].join('|'))}`
}

export function profileSecretKey(kind: 'api' | 'tts', profileId: string) {
  return `${kind === 'api' ? 'model_profile_key_' : 'tts_profile_key_'}${profileId.replace(/[^a-z0-9_]/gi, '_')}`
}
function isSavedProfileAuth(value: unknown): value is SavedProfileAuth {
  return value === 'api_key' || value === 'gcloud' || value === 'local_oauth' || value === 'none'
}

function credentialSourceForTtsAuth(auth: SavedProfileAuth): CredentialSource {
  if (auth === 'api_key') return 'tts_secret'
  return auth
}

function normalizeVerificationRecord(value: unknown): VerificationRecord | null {
  if (!value || typeof value !== 'object') return null
  const record = value as Record<string, unknown>
  if (record.status !== 'passed' && record.status !== 'failed') return null
  if (typeof record.verificationFingerprint !== 'string' || !record.verificationFingerprint) return null
  const checkedAt = Number(record.checkedAt)
  if (!Number.isFinite(checkedAt)) return null

  return {
    status: record.status,
    verificationFingerprint: record.verificationFingerprint,
    credentialRevision: sanitizeCredentialRevision(record.credentialRevision),
    checkedAt,
    ...(Number.isFinite(Number(record.latencyMs)) ? { latencyMs: Number(record.latencyMs) } : {}),
    ...(typeof record.errorCode === 'string' ? { errorCode: record.errorCode } : {}),
    ...(typeof record.retryable === 'boolean' ? { retryable: record.retryable } : {}),
  }
}

function normalizeProfileVerification(
  profile: SavedApiProfile | SavedTtsProfile,
  currentFingerprint: string,
): PersistedProfileVerification {
  const candidate = profile as (SavedApiProfile | SavedTtsProfile) & Partial<PersistedProfileVerification>
  if (Array.isArray(candidate.verification_records)) {
    return {
      verification_schema_version: 1,
      credential_revision: sanitizeCredentialRevision(candidate.credential_revision),
      verification_records: candidate.verification_records
        .map(normalizeVerificationRecord)
        .filter((record): record is VerificationRecord => Boolean(record))
        .slice(-32),
    }
  }

  const migrated = migrateLegacyProfileVerification(profile, currentFingerprint, {
    credentialRevision: candidate.credential_revision,
  })
  return {
    verification_schema_version: 1,
    credential_revision: migrated.credentialRevision,
    verification_records: migrated.verificationRecords,
  }
}

export function normalizeSavedApiProfile(value: unknown): PersistedSavedApiProfile | null {
  if (!value || typeof value !== 'object') return null
  const profile = value as SavedApiProfile
  if (
    typeof profile.id !== 'string' ||
    !profile.id ||
    typeof profile.provider !== 'string' ||
    !profile.provider ||
    typeof profile.base_url !== 'string' ||
    typeof profile.model !== 'string'
  ) {
    return null
  }

  const auth = isSavedProfileAuth(profile.auth) ? profile.auth : apiAuthMode(profile)
  const normalized: SavedApiProfile = {
    id: profile.id,
    label: typeof profile.label === 'string' && profile.label ? profile.label : profile.id,
    provider: profile.provider,
    base_url: profile.base_url,
    model: profile.model,
    capabilities: Array.isArray(profile.capabilities)
      ? profile.capabilities.filter((capability): capability is string => typeof capability === 'string')
      : [],
    auth,
    has_api_key: Boolean(profile.has_api_key),
    updated_at: typeof profile.updated_at === 'string' ? profile.updated_at : new Date(0).toISOString(),
    last_test_ok: undefined,
  }
  return {
    ...normalized,
    ...normalizeProfileVerification(profile, modelVerificationFingerprint(normalized, auth)),
  }
}

export function normalizeSavedTtsProfile(value: unknown): PersistedSavedTtsProfile | null {
  if (!value || typeof value !== 'object') return null
  const profile = value as SavedTtsProfile
  if (
    typeof profile.id !== 'string' ||
    !profile.id ||
    typeof profile.provider !== 'string' ||
    !profile.provider ||
    typeof profile.base_url !== 'string' ||
    typeof profile.model !== 'string' ||
    typeof profile.voice !== 'string' ||
    typeof profile.language !== 'string' ||
    !Number.isFinite(Number(profile.sample_rate)) ||
    !Number.isFinite(Number(profile.bit_rate))
  ) {
    return null
  }

  const auth = isSavedProfileAuth(profile.auth) ? profile.auth : ttsAuthMode(profile)
  const normalized: SavedTtsProfile = {
    id: profile.id,
    label: typeof profile.label === 'string' && profile.label ? profile.label : profile.id,
    enabled: Boolean(profile.enabled),
    provider: profile.provider,
    base_url: profile.base_url,
    model: profile.model,
    voice: profile.voice,
    language: profile.language,
    sample_rate: Number(profile.sample_rate),
    bit_rate: Number(profile.bit_rate),
    output_volume: profile.output_volume,
    auth,
    has_api_key: Boolean(profile.has_api_key),
    updated_at: typeof profile.updated_at === 'string' ? profile.updated_at : new Date(0).toISOString(),
    last_test_ok: undefined,
  }
  return {
    ...normalized,
    ...normalizeProfileVerification(profile, ttsVerificationFingerprint(normalized, credentialSourceForTtsAuth(auth))),
  }
}

function readPreferredStorage(currentKey: string, legacyKey: string) {
  const current = readStorageArray(currentKey)
  if (current.found) return { items: current.items, migratedFromLegacy: false }
  const legacy = readStorageArray(legacyKey)
  return { items: legacy.items, migratedFromLegacy: legacy.found }
}

export function loadSavedApiProfiles(): PersistedSavedApiProfile[] {
  const source = readPreferredStorage(API_PROFILES_STORAGE_KEY, LEGACY_API_PROFILES_STORAGE_KEY)
  const profiles = source.items
    .map(normalizeSavedApiProfile)
    .filter((profile): profile is PersistedSavedApiProfile => Boolean(profile))
  if (source.migratedFromLegacy) writeStorageArray(API_PROFILES_STORAGE_KEY, profiles)
  return profiles
}

export function loadSavedTtsProfiles(): PersistedSavedTtsProfile[] {
  const source = readPreferredStorage(TTS_PROFILES_STORAGE_KEY, LEGACY_TTS_PROFILES_STORAGE_KEY)
  const profiles = source.items
    .map(normalizeSavedTtsProfile)
    .filter((profile): profile is PersistedSavedTtsProfile => Boolean(profile))
  if (source.migratedFromLegacy) writeStorageArray(TTS_PROFILES_STORAGE_KEY, profiles)
  return profiles
}

export function saveSavedApiProfiles(profiles: readonly SavedApiProfile[]) {
  const normalized = profiles
    .map(normalizeSavedApiProfile)
    .filter((profile): profile is PersistedSavedApiProfile => Boolean(profile))
  writeStorageArray(API_PROFILES_STORAGE_KEY, normalized)
}

export function saveSavedTtsProfiles(profiles: readonly SavedTtsProfile[]) {
  const normalized = profiles
    .map(normalizeSavedTtsProfile)
    .filter((profile): profile is PersistedSavedTtsProfile => Boolean(profile))
  writeStorageArray(TTS_PROFILES_STORAGE_KEY, normalized)
}

export function upsertSavedApiProfile(
  profiles: readonly SavedApiProfile[],
  profile: SavedApiProfile,
): PersistedSavedApiProfile[] {
  const normalizedProfile = normalizeSavedApiProfile(profile)
  const normalizedExisting = profiles
    .map(normalizeSavedApiProfile)
    .filter((item): item is PersistedSavedApiProfile => Boolean(item))
  if (!normalizedProfile) return normalizedExisting.slice(0, 24)
  return [normalizedProfile, ...normalizedExisting.filter((item) => item.id !== normalizedProfile.id)].slice(0, 24)
}

export function upsertSavedTtsProfile(
  profiles: readonly SavedTtsProfile[],
  profile: SavedTtsProfile,
): PersistedSavedTtsProfile[] {
  const normalizedProfile = normalizeSavedTtsProfile(profile)
  const normalizedExisting = profiles
    .map(normalizeSavedTtsProfile)
    .filter((item): item is PersistedSavedTtsProfile => Boolean(item))
  if (!normalizedProfile) return normalizedExisting.slice(0, 24)
  return [normalizedProfile, ...normalizedExisting.filter((item) => item.id !== normalizedProfile.id)].slice(0, 24)
}

export function findApiPresetForConfig(presets: ApiPreset[], api: ApiConfig) {
  return presets.find(
    (preset) =>
      preset.provider === api.provider &&
      normalizeUrl(preset.base_url) === normalizeUrl(api.base_url) &&
      preset.model === api.model,
  )
}

export function findTtsPresetForConfig(presets: TtsPreset[], tts: TtsConfig) {
  return presets.find(
    (preset) =>
      preset.provider === tts.provider &&
      normalizeUrl(preset.base_url) === normalizeUrl(tts.base_url) &&
      preset.model === tts.model &&
      preset.voice === tts.voice,
  )
}

export function buildSavedApiProfile(
  api: ApiConfig,
  presets: ApiPreset[],
  existing?: SavedApiProfile,
  _lastTestOk?: boolean,
): PersistedSavedApiProfile {
  const preset = findApiPresetForConfig(presets, api)
  const auth = apiAuthMode(api)
  const label = existing?.label ?? preset?.label ?? `${api.provider} · ${api.model || '未命名模型'}`
  const profile = normalizeSavedApiProfile({
    ...existing,
    id: apiProfileIdFromConfig(api),
    label,
    provider: api.provider,
    base_url: api.base_url,
    model: api.model,
    capabilities: [...api.capabilities],
    auth,
    has_api_key: auth === 'api_key' ? Boolean(api.api_key.trim() || existing?.has_api_key) : false,
    updated_at: new Date().toISOString(),
    last_test_ok: _lastTestOk ?? existing?.last_test_ok,
  })
  if (!profile) throw new Error('Unable to build saved API profile')
  return profile
}

export function buildSavedTtsProfile(
  tts: TtsConfig,
  presets: TtsPreset[],
  existing?: SavedTtsProfile,
  _lastTestOk?: boolean,
): PersistedSavedTtsProfile {
  const preset = findTtsPresetForConfig(presets, tts)
  const auth = ttsAuthMode(tts)
  const label = existing?.label ?? preset?.label ?? `${tts.provider} · ${tts.model || tts.voice || '未命名语音'}`
  const profile = normalizeSavedTtsProfile({
    ...existing,
    id: ttsProfileIdFromConfig(tts),
    label,
    enabled: tts.enabled,
    provider: tts.provider,
    base_url: tts.base_url,
    model: tts.model,
    voice: tts.voice,
    language: tts.language,
    sample_rate: tts.sample_rate,
    bit_rate: tts.bit_rate,
    output_volume: tts.output_volume,
    auth,
    has_api_key: auth === 'api_key' ? Boolean(tts.api_key.trim() || existing?.has_api_key) : false,
    updated_at: new Date().toISOString(),
    last_test_ok: _lastTestOk ?? existing?.last_test_ok,
  })
  if (!profile) throw new Error('Unable to build saved TTS profile')
  return profile
}
export function apiConfigMatchesProfile(api: ApiConfig, profile: SavedApiProfile) {
  return (
    api.provider === profile.provider &&
    normalizeUrl(api.base_url) === normalizeUrl(profile.base_url) &&
    api.model === profile.model &&
    sameStringList(api.capabilities ?? [], profile.capabilities ?? [])
  )
}

export function ttsConfigMatchesProfile(tts: TtsConfig, profile: SavedTtsProfile) {
  return (
    tts.enabled === profile.enabled &&
    tts.provider === profile.provider &&
    normalizeUrl(tts.base_url) === normalizeUrl(profile.base_url) &&
    tts.model === profile.model &&
    tts.voice === profile.voice &&
    tts.language === profile.language &&
    tts.sample_rate === profile.sample_rate &&
    tts.bit_rate === profile.bit_rate &&
    (tts.output_volume ?? 0.65) === (profile.output_volume ?? 0.65)
  )
}
export function apiProfileVerificationTarget(
  api: ApiConfig,
  profile?: SavedApiProfile | null,
): ProfileVerificationTarget {
  const matchingProfile = profile && apiConfigMatchesProfile(api, profile) ? normalizeSavedApiProfile(profile) : null
  const auth = apiAuthMode(api)
  const credentialRevision = advanceCredentialRevision(
    matchingProfile?.credential_revision ?? 0,
    auth === 'api_key' && Boolean(api.api_key.trim()),
  )
  return {
    verificationFingerprint: modelVerificationFingerprint(api, auth),
    credentialRevision,
  }
}

export function ttsProfileVerificationTarget(
  tts: TtsConfig,
  profile?: SavedTtsProfile | null,
  options: {
    credentialSource?: CredentialSource
    credentialRevision?: number
    secretChanged?: boolean
  } = {},
): ProfileVerificationTarget {
  const matchingProfile = profile && ttsConfigMatchesProfile(tts, profile) ? normalizeSavedTtsProfile(profile) : null
  const credentialSource = options.credentialSource ?? credentialSourceForTtsAuth(ttsAuthMode(tts))
  const baseRevision = options.credentialRevision ?? matchingProfile?.credential_revision ?? 0
  const secretChanged = options.secretChanged ?? (credentialSource === 'tts_secret' && Boolean(tts.api_key.trim()))
  return {
    verificationFingerprint: ttsVerificationFingerprint(tts, credentialSource),
    credentialRevision: advanceCredentialRevision(baseRevision, secretChanged),
  }
}

export function advanceApiProfileCredentialRevision(
  profile: SavedApiProfile,
  changed = true,
): PersistedSavedApiProfile {
  const normalized = normalizeSavedApiProfile(profile)
  if (!normalized) throw new Error('Invalid saved API profile')
  return {
    ...normalized,
    credential_revision: advanceCredentialRevision(normalized.credential_revision, changed),
    last_test_ok: undefined,
  }
}

export function advanceTtsProfileCredentialRevision(
  profile: SavedTtsProfile,
  changed = true,
): PersistedSavedTtsProfile {
  const normalized = normalizeSavedTtsProfile(profile)
  if (!normalized) throw new Error('Invalid saved TTS profile')
  return {
    ...normalized,
    credential_revision: advanceCredentialRevision(normalized.credential_revision, changed),
    last_test_ok: undefined,
  }
}

/**
 * Removes only the credential binding from a saved profile. The profile itself
 * remains available, while every verification record is invalidated because
 * it was produced with a different credential revision.
 */
export function removeSavedApiProfileCredential(profile: SavedApiProfile): PersistedSavedApiProfile {
  const advanced = advanceApiProfileCredentialRevision(profile)
  return {
    ...advanced,
    has_api_key: false,
    verification_records: [],
    last_test_ok: undefined,
  }
}

export function removeSavedTtsProfileCredential(profile: SavedTtsProfile): PersistedSavedTtsProfile {
  const advanced = advanceTtsProfileCredentialRevision(profile)
  return {
    ...advanced,
    has_api_key: false,
    verification_records: [],
    last_test_ok: undefined,
  }
}
type ProfileTestEvidence = {
  ok: boolean
  error_code?: string
  retryable?: boolean
  latency_ms?: number
}

function appendVerificationRecord(
  profile: PersistedProfileVerification,
  evidence: ProfileTestEvidence,
  target: ProfileVerificationTarget,
  checkedAt = Date.now(),
) {
  const record = createVerificationRecord({
    ok: evidence.ok,
    verificationFingerprint: target.verificationFingerprint,
    credentialRevision: target.credentialRevision,
    checkedAt,
    latencyMs: evidence.latency_ms,
    errorCode: evidence.error_code,
    retryable: evidence.retryable,
  })
  return [...profile.verification_records, record].slice(-32)
}

export function recordApiProfileVerification(
  profile: SavedApiProfile,
  evidence: ProfileTestEvidence,
  target: ProfileVerificationTarget,
  checkedAt = Date.now(),
): PersistedSavedApiProfile {
  const normalized = normalizeSavedApiProfile(profile)
  if (!normalized) throw new Error('Invalid saved API profile')
  const expectedFingerprint = modelVerificationFingerprint(normalized, normalized.auth)
  if (
    target.verificationFingerprint !== expectedFingerprint ||
    sanitizeCredentialRevision(target.credentialRevision) !== normalized.credential_revision
  ) {
    return normalized
  }
  return {
    ...normalized,
    updated_at: new Date(checkedAt).toISOString(),
    last_test_ok: undefined,
    verification_records: appendVerificationRecord(normalized, evidence, target, checkedAt),
  }
}

export function recordTtsProfileVerification(
  profile: SavedTtsProfile,
  evidence: ProfileTestEvidence,
  target: ProfileVerificationTarget,
  checkedAt = Date.now(),
  credentialSource?: CredentialSource,
): PersistedSavedTtsProfile {
  const normalized = normalizeSavedTtsProfile(profile)
  if (!normalized) throw new Error('Invalid saved TTS profile')
  const expectedFingerprint = ttsVerificationFingerprint(
    normalized,
    credentialSource ?? credentialSourceForTtsAuth(normalized.auth),
  )
  if (
    target.verificationFingerprint !== expectedFingerprint ||
    sanitizeCredentialRevision(target.credentialRevision) !== normalized.credential_revision
  ) {
    return normalized
  }
  return {
    ...normalized,
    updated_at: new Date(checkedAt).toISOString(),
    last_test_ok: undefined,
    verification_records: appendVerificationRecord(normalized, evidence, target, checkedAt),
  }
}

export function resolveSavedApiProfileVerification(
  profile: SavedApiProfile,
  options: {
    secretExists?: boolean | null
    checking?: boolean
    hermesStatus?: HermesProxyStatus | null
    now?: number
  } = {},
): ServiceCapabilityStatus {
  const normalized = normalizeSavedApiProfile(profile)
  if (!normalized) throw new Error('Invalid saved API profile')
  return buildModelCapabilityStatus({
    config: normalized,
    authMode: normalized.auth,
    credentialRevision: normalized.credential_revision,
    secretExists: options.secretExists ?? (normalized.auth === 'api_key' ? normalized.has_api_key : null),
    verificationRecords: normalized.verification_records,
    hermesStatus: options.hermesStatus,
    checking: options.checking,
    now: options.now,
  })
}

export function resolveSavedTtsProfileVerification(
  profile: SavedTtsProfile,
  options: {
    credentialSource?: CredentialSource
    secretExists?: boolean | null
    checking?: boolean
    required?: boolean
    now?: number
  } = {},
): ServiceCapabilityStatus {
  const normalized = normalizeSavedTtsProfile(profile)
  if (!normalized) throw new Error('Invalid saved TTS profile')
  const credentialSource = options.credentialSource ?? credentialSourceForTtsAuth(normalized.auth)
  return buildTtsCapabilityStatus({
    config: normalized,
    credentialSource,
    credentialRevision: normalized.credential_revision,
    secretExists:
      options.secretExists ??
      (credentialSource === 'tts_secret' || credentialSource === 'model_secret' ? normalized.has_api_key : null),
    verificationRecords: normalized.verification_records,
    required: options.required ?? true,
    checking: options.checking,
    now: options.now,
  })
}
