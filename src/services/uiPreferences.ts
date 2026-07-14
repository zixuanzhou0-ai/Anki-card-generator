export type UiPreferencesV1 = {
  onboardingVersion: 1
  onboardingCompleted: boolean
  settingsMode: 'simple' | 'advanced'
}

export const UI_PREFERENCES_STORAGE_KEY = 'anki-card-generator.ui-preferences.v1'

export const defaultUiPreferences: UiPreferencesV1 = {
  onboardingVersion: 1,
  onboardingCompleted: false,
  settingsMode: 'simple',
}

export function parseUiPreferences(value: string | null): UiPreferencesV1 {
  if (!value) return defaultUiPreferences

  try {
    const parsed = JSON.parse(value) as Partial<UiPreferencesV1>
    if (parsed.onboardingVersion !== 1) return defaultUiPreferences
    return {
      onboardingVersion: 1,
      onboardingCompleted: parsed.onboardingCompleted === true,
      settingsMode: parsed.settingsMode === 'advanced' ? 'advanced' : 'simple',
    }
  } catch {
    return defaultUiPreferences
  }
}

export function loadUiPreferences(storage: Pick<Storage, 'getItem'> | null = null): UiPreferencesV1 {
  const target = storage ?? (typeof window !== 'undefined' ? window.localStorage : null)
  if (!target) return defaultUiPreferences

  try {
    return parseUiPreferences(target.getItem(UI_PREFERENCES_STORAGE_KEY))
  } catch {
    return defaultUiPreferences
  }
}

export function saveUiPreferences(
  preferences: UiPreferencesV1,
  storage: Pick<Storage, 'setItem'> | null = null,
): void {
  const target = storage ?? (typeof window !== 'undefined' ? window.localStorage : null)
  if (!target) return

  try {
    target.setItem(UI_PREFERENCES_STORAGE_KEY, JSON.stringify(preferences))
  } catch {
    // A blocked or full preference store must never block card generation.
  }
}