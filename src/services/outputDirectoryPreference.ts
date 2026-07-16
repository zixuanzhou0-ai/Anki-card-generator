export const OUTPUT_DIRECTORY_PREFERENCE_STORAGE_KEY = 'anki-card-generator.output-directory-preference.v1'

export type OutputDirectoryPreferenceV1 = {
  schemaVersion: 1
  directory: string
  updatedAt: number
}

export type OutputDirectoryAvailability = 'writable' | 'missing' | 'not_writable'

export type OutputDirectorySelectionState =
  | { directory: null; availability?: never }
  | { directory: string; availability: OutputDirectoryAvailability }

export type OutputDirectoryDecision =
  | {
      action: 'reuse'
      directory: string
      reason: 'preferred_directory_writable'
    }
  | {
      action: 'pick'
      previousDirectory?: string
      reason: 'no_preference' | 'preferred_directory_missing' | 'preferred_directory_not_writable'
    }
  | {
      action: 'change'
      previousDirectory?: string
      reason: 'user_requested_change'
    }

function normalizeDirectory(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const directory = value.trim()
  if (!directory || directory.includes('\0') || directory.includes('\n') || directory.includes('\r')) {
    return null
  }
  return directory
}

export function parseOutputDirectoryPreference(value: string | null): OutputDirectoryPreferenceV1 | null {
  if (!value) return null

  try {
    const parsed = JSON.parse(value) as Partial<OutputDirectoryPreferenceV1>
    const directory = normalizeDirectory(parsed.directory)
    if (parsed.schemaVersion !== 1 || !directory) return null

    return {
      schemaVersion: 1,
      directory,
      updatedAt: Number.isFinite(parsed.updatedAt) && (parsed.updatedAt ?? 0) >= 0 ? parsed.updatedAt! : 0,
    }
  } catch {
    return null
  }
}

export function loadOutputDirectoryPreference(
  storage: Pick<Storage, 'getItem'> | null = null,
): OutputDirectoryPreferenceV1 | null {
  const target = storage ?? (typeof window !== 'undefined' ? window.localStorage : null)
  if (!target) return null

  try {
    return parseOutputDirectoryPreference(target.getItem(OUTPUT_DIRECTORY_PREFERENCE_STORAGE_KEY))
  } catch {
    return null
  }
}

export function saveOutputDirectoryPreference(
  directory: string,
  storage: Pick<Storage, 'setItem'> | null = null,
  updatedAt = Date.now(),
): OutputDirectoryPreferenceV1 | null {
  const normalizedDirectory = normalizeDirectory(directory)
  if (!normalizedDirectory) return null

  const preference: OutputDirectoryPreferenceV1 = {
    schemaVersion: 1,
    directory: normalizedDirectory,
    updatedAt: Number.isFinite(updatedAt) && updatedAt >= 0 ? updatedAt : 0,
  }
  const target = storage ?? (typeof window !== 'undefined' ? window.localStorage : null)
  if (!target) return preference

  try {
    target.setItem(OUTPUT_DIRECTORY_PREFERENCE_STORAGE_KEY, JSON.stringify(preference))
  } catch {
    // A blocked or full preference store must never block APKG export.
  }
  return preference
}

export function clearOutputDirectoryPreference(storage: Pick<Storage, 'removeItem'> | null = null): void {
  const target = storage ?? (typeof window !== 'undefined' ? window.localStorage : null)
  if (!target) return

  try {
    target.removeItem(OUTPUT_DIRECTORY_PREFERENCE_STORAGE_KEY)
  } catch {
    // Preference cleanup is best-effort and must never block APKG export.
  }
}

export function decideOutputDirectory(
  state: OutputDirectorySelectionState,
  intent: 'continue' | 'change' = 'continue',
): OutputDirectoryDecision {
  if (intent === 'change') {
    return {
      action: 'change',
      ...(state.directory ? { previousDirectory: state.directory } : {}),
      reason: 'user_requested_change',
    }
  }

  if (!state.directory) {
    return { action: 'pick', reason: 'no_preference' }
  }

  if (state.availability === 'writable') {
    return {
      action: 'reuse',
      directory: state.directory,
      reason: 'preferred_directory_writable',
    }
  }

  return {
    action: 'pick',
    previousDirectory: state.directory,
    reason: state.availability === 'missing' ? 'preferred_directory_missing' : 'preferred_directory_not_writable',
  }
}
