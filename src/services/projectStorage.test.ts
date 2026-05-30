import { beforeEach, describe, expect, it } from 'vitest'

import {
  defaultDocumentAnswerLanguage,
  defaultDocumentAnswerLength,
  defaultDocumentDepth,
  defaultDocumentFocus,
  defaultDocumentStudyMode,
  defaultRequest,
  PROJECT_STORAGE_KEY,
  REQUEST_STORAGE_KEY,
  SECRET_PREFS_STORAGE_KEY,
} from '../domain/options'
import { loadSavedProject, loadSavedRequest, loadSecretPrefs } from './projectStorage'

describe('projectStorage document focus migration', () => {
  beforeEach(() => {
    window.localStorage.clear()
    delete (window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__
  })

  it('restores default document focus for legacy saved requests', () => {
    window.localStorage.setItem(REQUEST_STORAGE_KEY, JSON.stringify({ title: 'legacy document config' }))

    expect(loadSavedRequest().document_focus).toEqual(defaultDocumentFocus)
    expect(loadSavedRequest().document_study_mode).toBe(defaultDocumentStudyMode)
    expect(loadSavedRequest().document_answer_language).toBe(defaultDocumentAnswerLanguage)
    expect(loadSavedRequest().document_depth).toBe(defaultDocumentDepth)
    expect(loadSavedRequest().document_answer_length).toBe(defaultDocumentAnswerLength)
  })

  it('normalizes saved document focus values', () => {
    window.localStorage.setItem(
      REQUEST_STORAGE_KEY,
      JSON.stringify({ document_focus: ['examples', 'invalid', 'terms', 'examples'] }),
    )

    expect(loadSavedRequest().document_focus).toEqual(['examples', 'terms'])
  })

  it('normalizes saved document study path settings', () => {
    window.localStorage.setItem(
      REQUEST_STORAGE_KEY,
      JSON.stringify({
        document_study_mode: 'language_reading',
        document_answer_language: 'bilingual',
        document_depth: 'deep',
        document_answer_length: 'long',
      }),
    )

    const request = loadSavedRequest()
    expect(request.document_study_mode).toBe('language_reading')
    expect(request.document_answer_language).toBe('bilingual')
    expect(request.document_depth).toBe('deep')
    expect(request.document_answer_length).toBe('long')
  })

  it('removes hidden listening focus from saved language reading requests', () => {
    window.localStorage.setItem(
      REQUEST_STORAGE_KEY,
      JSON.stringify({
        document_study_mode: 'language_reading',
        language_focus: ['phrases', 'listening', 'grammar'],
      }),
    )

    expect(loadSavedRequest().language_focus).toEqual(['phrases', 'grammar'])
  })

  it('preserves document source info and cleans reading focus on saved projects', () => {
    window.localStorage.setItem(
      PROJECT_STORAGE_KEY,
      JSON.stringify({
        ...defaultRequest,
        id: 'doc-project',
        source_mode: 'document',
        source_info: {
          title: 'Doc',
          document_path: 'doc.md',
          document_study_mode: 'language_reading',
        },
        document_study_mode: 'language_reading',
        language_focus: ['phrases', 'listening'],
        segments: [
          {
            id: 'doc_0001',
            start: 0,
            end: 0,
            source_time: '文档精读点 1',
            text: 'What does it mean?',
            duration: 0,
            recommendation: 4,
            phrase: 'it turns out',
            cards: [],
          },
        ],
        created_at: 1,
      }),
    )

    const project = loadSavedProject()
    expect(project?.language_focus).toEqual(['phrases'])
    expect(project?.source_info).toMatchObject({ document_study_mode: 'language_reading' })
  })

  it('keeps secret persistence opt-in for browser previews', () => {
    expect(loadSecretPrefs()).toEqual({ rememberModelKey: false, rememberTtsKey: false })
  })

  it('defaults desktop secret persistence to Windows credentials', () => {
    ;(window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ = {}

    expect(loadSecretPrefs()).toEqual({ rememberModelKey: true, rememberTtsKey: true })
  })

  it('ignores the legacy v1 secret preference key on desktop', () => {
    ;(window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ = {}
    window.localStorage.setItem(
      'anki-card-generator.secret-prefs.v1',
      JSON.stringify({ rememberModelKey: false, rememberTtsKey: false }),
    )

    expect(loadSecretPrefs()).toEqual({ rememberModelKey: true, rememberTtsKey: true })
  })

  it('preserves an explicit v2 desktop opt-out', () => {
    ;(window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ = {}
    window.localStorage.setItem(
      SECRET_PREFS_STORAGE_KEY,
      JSON.stringify({ rememberModelKey: false, rememberTtsKey: false }),
    )

    expect(loadSecretPrefs()).toEqual({ rememberModelKey: false, rememberTtsKey: false })
  })
})
