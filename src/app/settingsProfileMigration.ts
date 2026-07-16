import { createVerificationRecord, sanitizeCredentialRevision, type VerificationRecord } from './systemCapabilityState'

export type LegacyProfileVerification = {
  last_test_ok?: unknown
  updated_at?: unknown
  credential_revision?: unknown
}

export type LegacyProfileVerificationMigration = {
  credentialRevision: number
  verificationRecords: VerificationRecord[]
  migration: 'none' | 'stale_passed' | 'stale_failed'
}

type MigrationOptions = {
  now?: number
  credentialRevision?: number
}

function legacyCheckedAt(value: unknown, fallback: number) {
  if (typeof value !== 'string' && typeof value !== 'number') return fallback
  const parsed = typeof value === 'number' ? value : Date.parse(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

export function migrateLegacyProfileVerification(
  profile: LegacyProfileVerification,
  currentFingerprint: string,
  options: MigrationOptions = {},
): LegacyProfileVerificationMigration {
  const credentialRevision = sanitizeCredentialRevision(options.credentialRevision ?? profile.credential_revision)
  if (typeof profile.last_test_ok !== 'boolean') {
    return {
      credentialRevision,
      verificationRecords: [],
      migration: 'none',
    }
  }

  const now = Number.isFinite(options.now) ? Number(options.now) : Date.now()
  const verification = createVerificationRecord({
    ok: profile.last_test_ok,
    verificationFingerprint: `legacy:v1:${currentFingerprint}`,
    credentialRevision,
    checkedAt: legacyCheckedAt(profile.updated_at, now),
    errorCode: 'legacy_verification_requires_retest',
    retryable: true,
  })

  return {
    credentialRevision,
    verificationRecords: [verification],
    migration: profile.last_test_ok ? 'stale_passed' : 'stale_failed',
  }
}
