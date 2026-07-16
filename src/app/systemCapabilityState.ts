import type { ApiConfig, HermesProxyStatus, SavedProfileAuth, TtsConfig } from '../domain/types'
import { isHermesLocalApiConfig } from '../services/apiConfig'

export const DEFAULT_VERIFICATION_TTL_MS = 7 * 24 * 60 * 60 * 1_000

const MAX_FUTURE_CLOCK_SKEW_MS = 5 * 60 * 1_000

export type CapabilityState =
  | 'unknown'
  | 'checking'
  | 'ready'
  | 'stale'
  | 'action_required'
  | 'blocked'
  | 'disabled'
  | 'optional'

export type VerificationRecord = {
  status: 'passed' | 'failed'
  verificationFingerprint: string
  credentialRevision: number
  checkedAt: number
  latencyMs?: number
  errorCode?: string
  retryable?: boolean
}

export type CredentialSource = 'model_secret' | 'tts_secret' | 'gcloud' | 'local_oauth' | 'none'

export type CapabilityReason =
  | 'checking'
  | 'disabled'
  | 'secret_status_unknown'
  | 'secret_missing'
  | 'verification_missing'
  | 'verification_expired'
  | 'configuration_or_credential_changed'
  | 'verification_failed'
  | 'verified'
  | 'hermes_status_unknown'
  | 'hermes_missing'
  | 'hermes_stopped'
  | 'hermes_oauth_unready'
  | 'hermes_starting'
  | 'hermes_port_conflict'
  | 'hermes_error'

export type ServiceCapabilityStatus = {
  state: CapabilityState
  reason: CapabilityReason
  verificationFingerprint: string
  credentialRevision: number
  verification?: VerificationRecord
}

export type EnvironmentCapabilityStatus = ServiceCapabilityStatus

export type SystemCapabilitySnapshot = {
  model: ServiceCapabilityStatus
  tts: ServiceCapabilityStatus
  environment: EnvironmentCapabilityStatus
  anki: ServiceCapabilityStatus
}

type ModelFingerprintConfig = Pick<ApiConfig, 'provider' | 'base_url' | 'model'> & Partial<Pick<ApiConfig, 'api_key'>>

type TtsFingerprintConfig = Pick<
  TtsConfig,
  'enabled' | 'provider' | 'base_url' | 'model' | 'voice' | 'language' | 'sample_rate' | 'bit_rate'
> &
  Partial<Pick<TtsConfig, 'api_key'>>

type CreateVerificationRecordInput = {
  ok: boolean
  verificationFingerprint: string
  credentialRevision: number
  checkedAt?: number
  latencyMs?: number
  errorCode?: string
  retryable?: boolean
}

export type ResolveVerificationCapabilityInput = {
  verificationFingerprint: string
  credentialRevision: number
  verificationRecords: readonly VerificationRecord[]
  secretRequired: boolean
  secretExists?: boolean | null
  checking?: boolean
  enabled?: boolean
  optional?: boolean
  now?: number
  ttlMs?: number
}

export type BuildModelCapabilityStatusInput = {
  config: ModelFingerprintConfig
  authMode: SavedProfileAuth
  credentialRevision: number
  secretExists?: boolean | null
  verificationRecords: readonly VerificationRecord[]
  hermesStatus?: HermesProxyStatus | null
  checking?: boolean
  now?: number
  ttlMs?: number
}

export type BuildTtsCapabilityStatusInput = {
  config: TtsFingerprintConfig
  credentialSource: CredentialSource
  credentialRevision: number
  secretExists?: boolean | null
  verificationRecords: readonly VerificationRecord[]
  required: boolean
  checking?: boolean
  now?: number
  ttlMs?: number
}

function normalizeEndpoint(value: string) {
  const trimmed = value.trim()
  if (!trimmed) return ''

  try {
    const parsed = new URL(trimmed)
    parsed.username = ''
    parsed.password = ''
    parsed.search = ''
    parsed.hash = ''
    return parsed.toString().replace(/\/+$/, '')
  } catch {
    return trimmed
      .replace(/[?#].*$/, '')
      .replace(/\/\/[^/@]+@/, '//')
      .replace(/\/+$/, '')
  }
}

function hash32(value: string, seed: number) {
  let hash = seed >>> 0
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 16_777_619)
    hash ^= hash >>> 13
  }
  return (hash >>> 0).toString(36).padStart(7, '0')
}

function stableFingerprint(kind: 'model' | 'tts', fields: readonly unknown[]) {
  const serialized = JSON.stringify(fields)
  return `${kind}:v1:${hash32(serialized, 2_166_136_261)}${hash32(serialized, 2_654_435_769)}`
}

export function sanitizeCredentialRevision(value: unknown) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric) || numeric < 0) return 0
  return Math.floor(numeric)
}

export function advanceCredentialRevision(current: unknown, secretChanged = true) {
  const normalized = sanitizeCredentialRevision(current)
  return secretChanged ? normalized + 1 : normalized
}

export function modelVerificationFingerprint(config: ModelFingerprintConfig, authMode: SavedProfileAuth) {
  return stableFingerprint('model', [
    config.provider.trim().toLowerCase(),
    normalizeEndpoint(config.base_url),
    config.model.trim(),
    authMode,
  ])
}

export function ttsVerificationFingerprint(config: TtsFingerprintConfig, credentialSource: CredentialSource) {
  return stableFingerprint('tts', [
    config.enabled,
    config.provider.trim().toLowerCase(),
    normalizeEndpoint(config.base_url),
    config.model.trim(),
    config.voice.trim(),
    config.language.trim().toLowerCase(),
    config.sample_rate,
    config.bit_rate,
    credentialSource,
  ])
}

export function createVerificationRecord(input: CreateVerificationRecordInput): VerificationRecord {
  return {
    status: input.ok ? 'passed' : 'failed',
    verificationFingerprint: input.verificationFingerprint,
    credentialRevision: sanitizeCredentialRevision(input.credentialRevision),
    checkedAt: Number.isFinite(input.checkedAt) ? Number(input.checkedAt) : Date.now(),
    ...(input.latencyMs === undefined ? {} : { latencyMs: input.latencyMs }),
    ...(input.errorCode === undefined ? {} : { errorCode: input.errorCode }),
    ...(input.retryable === undefined ? {} : { retryable: input.retryable }),
  }
}

function latestCurrentVerification(
  records: readonly VerificationRecord[],
  verificationFingerprint: string,
  credentialRevision: number,
) {
  return records.reduce<VerificationRecord | undefined>((latest, record) => {
    if (
      record.verificationFingerprint !== verificationFingerprint ||
      sanitizeCredentialRevision(record.credentialRevision) !== credentialRevision
    ) {
      return latest
    }

    if (!latest || record.checkedAt > latest.checkedAt) return record
    if (record.checkedAt === latest.checkedAt && record.status === 'failed') return record
    return latest
  }, undefined)
}

function baseStatus(
  state: CapabilityState,
  reason: CapabilityReason,
  verificationFingerprint: string,
  credentialRevision: number,
  verification?: VerificationRecord,
): ServiceCapabilityStatus {
  return {
    state,
    reason,
    verificationFingerprint,
    credentialRevision,
    ...(verification ? { verification } : {}),
  }
}

export function resolveVerificationCapability(input: ResolveVerificationCapabilityInput): ServiceCapabilityStatus {
  const credentialRevision = sanitizeCredentialRevision(input.credentialRevision)
  const now = Number.isFinite(input.now) ? Number(input.now) : Date.now()
  const ttlMs = Number.isFinite(input.ttlMs) ? Math.max(0, Number(input.ttlMs)) : DEFAULT_VERIFICATION_TTL_MS
  const status = (state: CapabilityState, reason: CapabilityReason, verification?: VerificationRecord) =>
    baseStatus(state, reason, input.verificationFingerprint, credentialRevision, verification)

  if (input.enabled === false) return status('disabled', 'disabled')
  if (input.checking) return status('checking', 'checking')

  if (input.secretRequired) {
    if (input.secretExists === null || input.secretExists === undefined) {
      return status('unknown', 'secret_status_unknown')
    }
    if (!input.secretExists) return status('action_required', 'secret_missing')
  }

  const verification = latestCurrentVerification(
    input.verificationRecords,
    input.verificationFingerprint,
    credentialRevision,
  )
  if (verification?.status === 'failed') {
    return status('blocked', 'verification_failed', verification)
  }
  if (verification) {
    const timestampIsCredible =
      Number.isFinite(verification.checkedAt) && verification.checkedAt <= now + MAX_FUTURE_CLOCK_SKEW_MS
    const fresh = timestampIsCredible && now - verification.checkedAt <= ttlMs
    return fresh ? status('ready', 'verified', verification) : status('stale', 'verification_expired', verification)
  }

  if (input.verificationRecords.length > 0) {
    return status('stale', 'configuration_or_credential_changed')
  }
  if (input.optional) return status('optional', 'verification_missing')
  return status('unknown', 'verification_missing')
}

function hermesRuntimeStatus(
  state: CapabilityState,
  reason: CapabilityReason,
  fingerprint: string,
  credentialRevision: number,
) {
  return baseStatus(state, reason, fingerprint, credentialRevision)
}

export function buildModelCapabilityStatus(input: BuildModelCapabilityStatusInput): ServiceCapabilityStatus {
  const fingerprint = modelVerificationFingerprint(input.config, input.authMode)
  const credentialRevision = sanitizeCredentialRevision(input.credentialRevision)

  if (isHermesLocalApiConfig(input.config)) {
    if (input.checking) {
      return hermesRuntimeStatus('checking', 'checking', fingerprint, credentialRevision)
    }
    if (!input.hermesStatus) {
      return hermesRuntimeStatus('unknown', 'hermes_status_unknown', fingerprint, credentialRevision)
    }

    switch (input.hermesStatus.state) {
      case 'missing':
        return hermesRuntimeStatus('blocked', 'hermes_missing', fingerprint, credentialRevision)
      case 'stopped':
        return hermesRuntimeStatus('action_required', 'hermes_stopped', fingerprint, credentialRevision)
      case 'oauth_unready':
        return hermesRuntimeStatus('blocked', 'hermes_oauth_unready', fingerprint, credentialRevision)
      case 'starting':
        return hermesRuntimeStatus('checking', 'hermes_starting', fingerprint, credentialRevision)
      case 'port_conflict':
        return hermesRuntimeStatus('blocked', 'hermes_port_conflict', fingerprint, credentialRevision)
      case 'error':
        return hermesRuntimeStatus('blocked', 'hermes_error', fingerprint, credentialRevision)
      case 'ready':
        if (!input.hermesStatus.authenticated) {
          return hermesRuntimeStatus('blocked', 'hermes_oauth_unready', fingerprint, credentialRevision)
        }
        break
    }
  }

  return resolveVerificationCapability({
    verificationFingerprint: fingerprint,
    credentialRevision,
    verificationRecords: input.verificationRecords,
    secretRequired: input.authMode === 'api_key',
    secretExists: input.secretExists,
    checking: input.checking,
    now: input.now,
    ttlMs: input.ttlMs,
  })
}

export function buildTtsCapabilityStatus(input: BuildTtsCapabilityStatusInput): ServiceCapabilityStatus {
  const fingerprint = ttsVerificationFingerprint(input.config, input.credentialSource)
  return resolveVerificationCapability({
    verificationFingerprint: fingerprint,
    credentialRevision: input.credentialRevision,
    verificationRecords: input.verificationRecords,
    secretRequired: input.credentialSource === 'model_secret' || input.credentialSource === 'tts_secret',
    secretExists: input.secretExists,
    checking: input.checking,
    enabled: input.config.enabled && input.config.provider !== 'disabled',
    optional: !input.required,
    now: input.now,
    ttlMs: input.ttlMs,
  })
}
