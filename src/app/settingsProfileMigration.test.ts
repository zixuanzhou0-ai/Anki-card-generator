import { describe, expect, it } from 'vitest'
import { resolveVerificationCapability } from './systemCapabilityState'
import { migrateLegacyProfileVerification } from './settingsProfileMigration'

const NOW = Date.UTC(2026, 6, 15, 12)

describe('legacy settings verification migration', () => {
  it.each([true, false])('migrates last_test_ok=%s as stale evidence', (lastTestOk) => {
    const currentFingerprint = 'model:v1:current'
    const migrated = migrateLegacyProfileVerification(
      {
        last_test_ok: lastTestOk,
        updated_at: '2026-07-14T12:00:00.000Z',
      },
      currentFingerprint,
      { now: NOW, credentialRevision: 2 },
    )

    expect(migrated).toMatchObject({
      credentialRevision: 2,
      migration: lastTestOk ? 'stale_passed' : 'stale_failed',
    })
    expect(migrated.verificationRecords).toHaveLength(1)
    expect(migrated.verificationRecords[0]).toMatchObject({
      status: lastTestOk ? 'passed' : 'failed',
      credentialRevision: 2,
      checkedAt: Date.parse('2026-07-14T12:00:00.000Z'),
      errorCode: 'legacy_verification_requires_retest',
      retryable: true,
    })
    expect(migrated.verificationRecords[0].verificationFingerprint).not.toBe(currentFingerprint)

    expect(
      resolveVerificationCapability({
        verificationFingerprint: currentFingerprint,
        credentialRevision: 2,
        verificationRecords: migrated.verificationRecords,
        secretRequired: false,
        now: NOW,
      }),
    ).toMatchObject({ state: 'stale', reason: 'configuration_or_credential_changed' })
  })

  it('does not invent evidence when the legacy flag is absent', () => {
    expect(migrateLegacyProfileVerification({}, 'model:v1:current', { now: NOW })).toEqual({
      credentialRevision: 0,
      verificationRecords: [],
      migration: 'none',
    })
  })

  it('sanitizes invalid revisions and timestamps', () => {
    const migrated = migrateLegacyProfileVerification(
      { last_test_ok: true, updated_at: 'invalid' },
      'model:v1:current',
      { now: NOW, credentialRevision: -10 },
    )

    expect(migrated.credentialRevision).toBe(0)
    expect(migrated.verificationRecords[0].checkedAt).toBe(NOW)
  })
})
