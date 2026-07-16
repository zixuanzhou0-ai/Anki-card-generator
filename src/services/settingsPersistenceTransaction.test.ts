import { describe, expect, it } from 'vitest'

import {
  persistSettingsTransaction,
  type SecretSnapshot,
  type SettingsPersistenceOperations,
  type SettingsPersistencePlan,
} from './settingsPersistenceTransaction'

type Profile = { id: string }

const plan: SettingsPersistencePlan<Profile, Profile> = {
  apiSecret: { key: 'api', value: 'api-new' },
  ttsSecret: { key: 'tts', value: 'tts-new' },
  apiProfiles: { previous: [{ id: 'api-old' }], next: [{ id: 'api-new' }] },
  ttsProfiles: { previous: [{ id: 'tts-old' }], next: [{ id: 'tts-new' }] },
}

function createState(options?: {
  failAt?: string
  rollbackFailAt?: string
  initialSecrets?: Record<string, string>
  originalError?: Error
}) {
  const events: string[] = []
  const secrets = new Map(Object.entries(options?.initialSecrets ?? {}))
  let apiProfiles: readonly Profile[] = plan.apiProfiles.previous
  let ttsProfiles: readonly Profile[] = plan.ttsProfiles.previous
  let originalFailureThrown = false
  const originalError = options?.originalError ?? new Error(`failed:${options?.failAt ?? 'unknown'}`)

  const mutateThenMaybeFail = (step: string) => {
    if (!originalFailureThrown && options?.failAt === step) {
      originalFailureThrown = true
      throw originalError
    }
    if (originalFailureThrown && options?.rollbackFailAt === step) {
      throw new Error(`rollback-failed:${step}`)
    }
  }
  const phase = () => (originalFailureThrown ? 'rollback:' : '')

  const operations: SettingsPersistenceOperations<Profile, Profile> = {
    async snapshotSecret(key): Promise<SecretSnapshot> {
      events.push(`snapshot:${key}`)
      return secrets.has(key) ? { exists: true, value: secrets.get(key) ?? '' } : { exists: false }
    },
    async writeSecret(key, value) {
      events.push(`${phase()}write-secret:${key}:${value}`)
      secrets.set(key, value)
      mutateThenMaybeFail(`write-secret:${key}`)
    },
    async deleteSecret(key) {
      events.push(`${phase()}delete-secret:${key}`)
      secrets.delete(key)
      mutateThenMaybeFail(`delete-secret:${key}`)
    },
    async writeApiProfiles(profiles) {
      events.push(`${phase()}write-api-profiles:${profiles[0]?.id ?? 'empty'}`)
      apiProfiles = [...profiles]
      mutateThenMaybeFail('write-api-profiles')
    },
    async writeTtsProfiles(profiles) {
      events.push(`${phase()}write-tts-profiles:${profiles[0]?.id ?? 'empty'}`)
      ttsProfiles = [...profiles]
      mutateThenMaybeFail('write-tts-profiles')
    },
  }

  return {
    events,
    secrets,
    operations,
    originalError,
    get apiProfiles() {
      return apiProfiles
    },
    get ttsProfiles() {
      return ttsProfiles
    },
  }
}

describe('persistSettingsTransaction', () => {
  it('snapshots both secrets before committing secrets and profile stores in order', async () => {
    const state = createState({ initialSecrets: { api: 'api-old', tts: 'tts-old' } })
    await persistSettingsTransaction(plan, state.operations)

    expect(state.events).toEqual([
      'snapshot:api',
      'snapshot:tts',
      'write-secret:api:api-new',
      'write-secret:tts:tts-new',
      'write-api-profiles:api-new',
      'write-tts-profiles:tts-new',
    ])
    expect(Object.fromEntries(state.secrets)).toEqual({ api: 'api-new', tts: 'tts-new' })
    expect(state.apiProfiles).toEqual([{ id: 'api-new' }])
    expect(state.ttsProfiles).toEqual([{ id: 'tts-new' }])
  })

  it.each(['write-secret:api', 'write-secret:tts', 'write-api-profiles', 'write-tts-profiles'])(
    'restores every attempted mutation when %s throws after writing',
    async (failAt) => {
      const state = createState({ failAt, initialSecrets: { api: 'api-old', tts: 'tts-old' } })

      await expect(persistSettingsTransaction(plan, state.operations)).rejects.toBe(state.originalError)
      expect(Object.fromEntries(state.secrets)).toEqual({ api: 'api-old', tts: 'tts-old' })
      expect(state.apiProfiles).toEqual([{ id: 'api-old' }])
      expect(state.ttsProfiles).toEqual([{ id: 'tts-old' }])
    },
  )

  it('deletes secrets that did not exist before a failed transaction', async () => {
    const state = createState({ failAt: 'write-tts-profiles' })
    await expect(persistSettingsTransaction(plan, state.operations)).rejects.toBe(state.originalError)
    expect(Object.fromEntries(state.secrets)).toEqual({})
    expect(state.events).toContain('rollback:delete-secret:api')
    expect(state.events).toContain('rollback:delete-secret:tts')
  })

  it('restores a deleted credential if profile persistence fails after deletion', async () => {
    const deletePlan: SettingsPersistencePlan<Profile, Profile> = {
      apiSecret: { key: 'api', delete: true },
      apiProfiles: plan.apiProfiles,
      ttsProfiles: plan.ttsProfiles,
    }
    const state = createState({
      failAt: 'write-api-profiles',
      initialSecrets: { api: 'api-old', tts: 'tts-old' },
    })

    await expect(persistSettingsTransaction(deletePlan, state.operations)).rejects.toBe(state.originalError)
    expect(state.secrets.get('api')).toBe('api-old')
    expect(state.secrets.get('tts')).toBe('tts-old')
    expect(state.events).toContain('delete-secret:api')
    expect(state.events).toContain('rollback:write-secret:api:api-old')
    expect(state.apiProfiles).toEqual([{ id: 'api-old' }])
  })

  it('continues compensation and preserves the original error if one rollback step fails', async () => {
    const originalError = new Error('original-write-failure')
    const state = createState({
      failAt: 'write-tts-profiles',
      rollbackFailAt: 'write-api-profiles',
      initialSecrets: { api: 'api-old', tts: 'tts-old' },
      originalError,
    })

    await expect(persistSettingsTransaction(plan, state.operations)).rejects.toBe(originalError)
    expect(state.secrets.get('api')).toBe('api-old')
    expect(state.secrets.get('tts')).toBe('tts-old')
    expect(state.events).toContain('rollback:write-secret:api:api-old')
  })
})
