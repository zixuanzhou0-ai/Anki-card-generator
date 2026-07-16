import { describe, expect, it, vi } from 'vitest'

import {
  OUTPUT_DIRECTORY_PREFERENCE_STORAGE_KEY,
  clearOutputDirectoryPreference,
  decideOutputDirectory,
  loadOutputDirectoryPreference,
  parseOutputDirectoryPreference,
  saveOutputDirectoryPreference,
} from './outputDirectoryPreference'

describe('outputDirectoryPreference', () => {
  it('stores only the version, normalized directory, and timestamp', () => {
    const setItem = vi.fn()

    expect(saveOutputDirectoryPreference('  E:\\Anki Exports  ', { setItem }, 42)).toEqual({
      schemaVersion: 1,
      directory: 'E:\\Anki Exports',
      updatedAt: 42,
    })
    expect(setItem).toHaveBeenCalledWith(
      OUTPUT_DIRECTORY_PREFERENCE_STORAGE_KEY,
      '{"schemaVersion":1,"directory":"E:\\\\Anki Exports","updatedAt":42}',
    )

    const serialized = setItem.mock.calls[0]?.[1] as string
    expect(serialized).not.toMatch(/api[_-]?key|token|cookie|oauth|password|secret/i)
  })

  it('drops unknown credential-like fields while parsing stored data', () => {
    const parsed = parseOutputDirectoryPreference(
      JSON.stringify({
        schemaVersion: 1,
        directory: 'D:\\Cards',
        updatedAt: 99,
        api_key: 'must-not-survive',
        oauthToken: 'must-not-survive',
      }),
    )

    expect(parsed).toEqual({ schemaVersion: 1, directory: 'D:\\Cards', updatedAt: 99 })
    expect(Object.keys(parsed ?? {})).toEqual(['schemaVersion', 'directory', 'updatedAt'])
  })

  it('rejects missing, corrupt, future, or unsafe directory data', () => {
    expect(parseOutputDirectoryPreference(null)).toBeNull()
    expect(parseOutputDirectoryPreference('{broken')).toBeNull()
    expect(parseOutputDirectoryPreference('{"schemaVersion":2,"directory":"D:\\\\Cards"}')).toBeNull()
    expect(parseOutputDirectoryPreference('{"schemaVersion":1,"directory":"  "}')).toBeNull()
    expect(parseOutputDirectoryPreference('{"schemaVersion":1,"directory":"D:\\\\Cards\\nother"}')).toBeNull()
  })

  it('loads and clears through the isolated preference key without propagating storage failures', () => {
    const getItem = vi.fn(() => '{"schemaVersion":1,"directory":"E:\\\\Exports","updatedAt":7}')
    expect(loadOutputDirectoryPreference({ getItem })?.directory).toBe('E:\\Exports')
    expect(getItem).toHaveBeenCalledWith(OUTPUT_DIRECTORY_PREFERENCE_STORAGE_KEY)

    const removeItem = vi.fn()
    clearOutputDirectoryPreference({ removeItem })
    expect(removeItem).toHaveBeenCalledWith(OUTPUT_DIRECTORY_PREFERENCE_STORAGE_KEY)

    expect(
      loadOutputDirectoryPreference({
        getItem: () => {
          throw new Error('blocked')
        },
      }),
    ).toBeNull()
    expect(() =>
      saveOutputDirectoryPreference('E:\\Exports', {
        setItem: () => {
          throw new Error('full')
        },
      }),
    ).not.toThrow()
  })

  it('reuses a writable remembered directory without reopening the picker', () => {
    expect(decideOutputDirectory({ directory: 'E:\\Exports', availability: 'writable' })).toEqual({
      action: 'reuse',
      directory: 'E:\\Exports',
      reason: 'preferred_directory_writable',
    })
  })

  it.each([
    ['missing', 'preferred_directory_missing'],
    ['not_writable', 'preferred_directory_not_writable'],
  ] as const)('opens the picker only when the remembered directory is %s', (availability, reason) => {
    expect(decideOutputDirectory({ directory: 'E:\\Exports', availability })).toEqual({
      action: 'pick',
      previousDirectory: 'E:\\Exports',
      reason,
    })
  })

  it('opens the picker for a first export and distinguishes an explicit change request', () => {
    expect(decideOutputDirectory({ directory: null })).toEqual({
      action: 'pick',
      reason: 'no_preference',
    })
    expect(decideOutputDirectory({ directory: 'E:\\Exports', availability: 'writable' }, 'change')).toEqual({
      action: 'change',
      previousDirectory: 'E:\\Exports',
      reason: 'user_requested_change',
    })
  })
})
