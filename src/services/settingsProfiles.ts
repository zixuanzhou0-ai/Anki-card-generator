import type {
  ApiConfig,
  ApiPreset,
  SavedApiProfile,
  SavedProfileAuth,
  SavedTtsProfile,
  TtsConfig,
  TtsPreset,
} from '../domain/types'
import { isHermesLocalApiConfig } from './apiConfig'

export const API_PROFILES_STORAGE_KEY = 'anki-card-generator.api-profiles.v1'
export const TTS_PROFILES_STORAGE_KEY = 'anki-card-generator.tts-profiles.v1'

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

function readStorageArray<T>(key: string): T[] {
  if (typeof window === 'undefined') return []
  try {
    const parsed = JSON.parse(window.localStorage.getItem(key) ?? '[]')
    return Array.isArray(parsed) ? (parsed as T[]) : []
  } catch {
    return []
  }
}

function writeStorageArray<T>(key: string, value: T[]) {
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

export function loadSavedApiProfiles() {
  return readStorageArray<SavedApiProfile>(API_PROFILES_STORAGE_KEY).filter((profile) => profile.id && profile.provider)
}

export function loadSavedTtsProfiles() {
  return readStorageArray<SavedTtsProfile>(TTS_PROFILES_STORAGE_KEY).filter((profile) => profile.id && profile.provider)
}

export function saveSavedApiProfiles(profiles: SavedApiProfile[]) {
  writeStorageArray(API_PROFILES_STORAGE_KEY, profiles)
}

export function saveSavedTtsProfiles(profiles: SavedTtsProfile[]) {
  writeStorageArray(TTS_PROFILES_STORAGE_KEY, profiles)
}

export function upsertSavedApiProfile(profiles: SavedApiProfile[], profile: SavedApiProfile) {
  const next = [profile, ...profiles.filter((item) => item.id !== profile.id)]
  return next.slice(0, 24)
}

export function upsertSavedTtsProfile(profiles: SavedTtsProfile[], profile: SavedTtsProfile) {
  const next = [profile, ...profiles.filter((item) => item.id !== profile.id)]
  return next.slice(0, 24)
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
  lastTestOk?: boolean,
): SavedApiProfile {
  const preset = findApiPresetForConfig(presets, api)
  const auth = apiAuthMode(api)
  const label = existing?.label ?? preset?.label ?? `${api.provider} · ${api.model || '未命名模型'}`
  return {
    id: apiProfileIdFromConfig(api),
    label,
    provider: api.provider,
    base_url: api.base_url,
    model: api.model,
    capabilities: api.capabilities,
    auth,
    has_api_key: auth === 'api_key' ? Boolean(api.api_key.trim() || existing?.has_api_key) : false,
    updated_at: new Date().toISOString(),
    last_test_ok: lastTestOk ?? existing?.last_test_ok,
  }
}

export function buildSavedTtsProfile(
  tts: TtsConfig,
  presets: TtsPreset[],
  existing?: SavedTtsProfile,
  lastTestOk?: boolean,
): SavedTtsProfile {
  const preset = findTtsPresetForConfig(presets, tts)
  const auth = ttsAuthMode(tts)
  const label = existing?.label ?? preset?.label ?? `${tts.provider} · ${tts.model || tts.voice || '未命名语音'}`
  return {
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
    last_test_ok: lastTestOk ?? existing?.last_test_ok,
  }
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
