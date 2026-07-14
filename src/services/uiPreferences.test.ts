import { describe, expect, it, vi } from 'vitest'

import {
  UI_PREFERENCES_STORAGE_KEY,
  defaultUiPreferences,
  loadUiPreferences,
  parseUiPreferences,
  saveUiPreferences,
} from './uiPreferences'

describe('uiPreferences', () => {
  it('returns a safe first-run default for missing, corrupt, or future data', () => {
    expect(parseUiPreferences(null)).toEqual(defaultUiPreferences)
    expect(parseUiPreferences('{broken')).toEqual(defaultUiPreferences)
    expect(parseUiPreferences('{"onboardingVersion":2,"onboardingCompleted":true}')).toEqual(defaultUiPreferences)
  })

  it('migrates optional fields without ever containing credentials', () => {
    expect(parseUiPreferences('{"onboardingVersion":1,"onboardingCompleted":true}')).toEqual({
      onboardingVersion: 1,
      onboardingCompleted: true,
      settingsMode: 'simple',
    })
    expect(Object.keys(defaultUiPreferences)).toEqual([
      'onboardingVersion',
      'onboardingCompleted',
      'settingsMode',
    ])
  })

  it('loads and saves through an isolated non-secret storage key', () => {
    const getItem = vi.fn(() => '{"onboardingVersion":1,"onboardingCompleted":true,"settingsMode":"advanced"}')
    expect(loadUiPreferences({ getItem }).settingsMode).toBe('advanced')
    expect(getItem).toHaveBeenCalledWith(UI_PREFERENCES_STORAGE_KEY)

    const setItem = vi.fn()
    saveUiPreferences({ ...defaultUiPreferences, onboardingCompleted: true }, { setItem })
    expect(setItem).toHaveBeenCalledWith(
      UI_PREFERENCES_STORAGE_KEY,
      '{"onboardingVersion":1,"onboardingCompleted":true,"settingsMode":"simple"}',
    )
  })
})