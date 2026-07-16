export type SecretSnapshot =
  | { exists: false }
  | {
      exists: true
      value: string
    }

export type SecretWrite =
  | {
      key: string
      value: string
    }
  | {
      key: string
      delete: true
    }

export type ProfileStoreWrite<T> = {
  previous: readonly T[]
  next: readonly T[]
}

export type SettingsPersistencePlan<ApiProfile, TtsProfile> = {
  apiSecret?: SecretWrite
  ttsSecret?: SecretWrite
  apiProfiles: ProfileStoreWrite<ApiProfile>
  ttsProfiles: ProfileStoreWrite<TtsProfile>
}

export type SettingsPersistenceOperations<ApiProfile, TtsProfile> = {
  snapshotSecret: (key: string) => Promise<SecretSnapshot>
  writeSecret: (key: string, value: string) => void | Promise<void>
  deleteSecret: (key: string) => void | Promise<void>
  writeApiProfiles: (profiles: readonly ApiProfile[]) => void | Promise<void>
  writeTtsProfiles: (profiles: readonly TtsProfile[]) => void | Promise<void>
}

type Rollback = () => void | Promise<void>

async function restoreSecret<ApiProfile, TtsProfile>(
  write: SecretWrite,
  snapshot: SecretSnapshot,
  operations: SettingsPersistenceOperations<ApiProfile, TtsProfile>,
) {
  if (snapshot.exists) {
    await operations.writeSecret(write.key, snapshot.value)
    return
  }
  await operations.deleteSecret(write.key)
}

/**
 * Commits secrets and profile metadata as one compensating transaction.
 *
 * The OS secret store and browser preference store do not share a database
 * transaction, so every secret is snapshotted before the first mutation. A
 * compensation is registered before each write, which also covers adapters
 * that throw after partially persisting. Rollback errors never hide the
 * original persistence failure.
 */
export async function persistSettingsTransaction<ApiProfile, TtsProfile>(
  plan: SettingsPersistencePlan<ApiProfile, TtsProfile>,
  operations: SettingsPersistenceOperations<ApiProfile, TtsProfile>,
): Promise<void> {
  const secretSnapshots = new Map<string, SecretSnapshot>()
  for (const write of [plan.apiSecret, plan.ttsSecret]) {
    if (!write || secretSnapshots.has(write.key)) continue
    secretSnapshots.set(write.key, await operations.snapshotSecret(write.key))
  }

  const rollbacks: Rollback[] = []
  try {
    for (const write of [plan.apiSecret, plan.ttsSecret]) {
      if (!write) continue
      const snapshot = secretSnapshots.get(write.key)
      if (!snapshot) throw new Error('Missing secret snapshot before settings persistence.')
      rollbacks.push(() => restoreSecret(write, snapshot, operations))
      if ('delete' in write) {
        await operations.deleteSecret(write.key)
      } else {
        await operations.writeSecret(write.key, write.value)
      }
    }

    rollbacks.push(() => operations.writeApiProfiles(plan.apiProfiles.previous))
    await operations.writeApiProfiles(plan.apiProfiles.next)

    rollbacks.push(() => operations.writeTtsProfiles(plan.ttsProfiles.previous))
    await operations.writeTtsProfiles(plan.ttsProfiles.next)
  } catch (originalError) {
    for (let index = rollbacks.length - 1; index >= 0; index -= 1) {
      try {
        await rollbacks[index]()
      } catch {
        // Keep compensating earlier steps and surface the original failure.
      }
    }
    throw originalError
  }
}
