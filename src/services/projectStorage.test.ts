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
import {
  loadSavedProject,
  loadSavedProjectForRequest,
  loadSavedRequest,
  loadSecretPrefs,
  projectMatchesRequest,
} from './projectStorage'

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

  it('normalizes legacy display language values to stable codes', () => {
    window.localStorage.setItem(REQUEST_STORAGE_KEY, JSON.stringify({ language: 'Français' }))

    expect(loadSavedRequest().language).toBe('fr')
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

  it('migrates legacy empty model config to filled DeepSeek V4 Pro settings', () => {
    window.localStorage.setItem(
      REQUEST_STORAGE_KEY,
      JSON.stringify({
        api_config: {
          provider: 'local',
          base_url: '',
          api_key: 'should-be-stripped',
          model: '',
          capabilities: [],
          tts_config: defaultRequest.api_config.tts_config,
        },
      }),
    )

    const request = loadSavedRequest()
    expect(request.api_config.provider).toBe('openai-compatible')
    expect(request.api_config.base_url).toBe('https://api.deepseek.com')
    expect(request.api_config.model).toBe('deepseek-v4-pro')
    expect(request.api_config.capabilities).toEqual(['structured_json', 'long_context'])
    expect(request.api_config.api_key).toBe('')
  })

  it('migrates old DeepSeek chat settings to official V4 Pro settings', () => {
    window.localStorage.setItem(
      REQUEST_STORAGE_KEY,
      JSON.stringify({
        api_config: {
          provider: 'openai-compatible',
          base_url: 'https://api.deepseek.com/v1',
          api_key: '',
          model: 'deepseek-chat',
          capabilities: ['structured_json'],
          tts_config: defaultRequest.api_config.tts_config,
        },
      }),
    )

    const request = loadSavedRequest()
    expect(request.api_config.base_url).toBe('https://api.deepseek.com')
    expect(request.api_config.model).toBe('deepseek-v4-pro')
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
    expect(project?.language).toBe('en')
    expect(project?.language_focus).toEqual(['phrases'])
    expect(project?.source_info).toMatchObject({ document_study_mode: 'language_reading' })
  })

  it('drops a saved URL project when the current request is local video', () => {
    window.localStorage.setItem(
      PROJECT_STORAGE_KEY,
      JSON.stringify({
        ...defaultRequest,
        id: 'old-url-project',
        source_mode: 'url',
        source_url: 'https://www.youtube.com/watch?v=old',
        source_info: { webpage_url: 'https://www.youtube.com/watch?v=old' },
        video_path:
          'C:\\Users\\Administrator\\AppData\\Local\\com.ankicard.generator\\projects\\url_cache\\old\\source.mp4',
        subtitle_path:
          'C:\\Users\\Administrator\\AppData\\Local\\com.ankicard.generator\\projects\\url_cache\\old\\source.en.srt',
        segments: [
          {
            id: 'seg_0001',
            start: 1,
            end: 2,
            source_time: '00:00:01.000 - 00:00:02.000',
            text: 'old URL card',
            duration: 1,
            recommendation: 4,
            phrase: 'old URL card',
            cards: [],
          },
        ],
        created_at: 1,
      }),
    )

    expect(
      loadSavedProjectForRequest({
        ...defaultRequest,
        source_mode: 'local',
        video_path: 'E:\\Videos\\episode.mp4',
        subtitle_path: 'E:\\Videos\\episode.srt',
      }),
    ).toBeNull()
  })

  it('keeps a saved local project only for the same local video', () => {
    const project = {
      ...defaultRequest,
      id: 'local-project',
      source_mode: 'local' as const,
      source_info: {
        video_path: 'E:\\Videos\\episode.mp4',
        subtitle_path: 'E:\\Videos\\episode.srt',
      },
      video_path: 'E:\\Videos\\episode.mp4',
      subtitle_path: 'E:\\Videos\\episode.srt',
      segments: [
        {
          id: 'seg_0001',
          start: 1,
          end: 2,
          source_time: '00:00:01.000 - 00:00:02.000',
          text: 'same local card',
          duration: 1,
          recommendation: 4,
          phrase: 'same local card',
          cards: [],
        },
      ],
      created_at: 1,
    }
    window.localStorage.setItem(PROJECT_STORAGE_KEY, JSON.stringify(project))

    const matchingRequest = {
      ...defaultRequest,
      source_mode: 'local' as const,
      video_path: 'E:\\Videos\\episode.mp4',
      subtitle_path: '',
    }
    const otherRequest = {
      ...matchingRequest,
      video_path: 'E:\\Videos\\other.mp4',
    }

    expect(loadSavedProjectForRequest(matchingRequest)?.id).toBe('local-project')
    expect(projectMatchesRequest(project, matchingRequest)).toBe(true)
    expect(projectMatchesRequest(project, otherRequest)).toBe(false)
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
