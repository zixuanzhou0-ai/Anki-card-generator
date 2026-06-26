import { beforeEach, describe, expect, it } from 'vitest'

import {
  defaultDocumentAnswerLanguage,
  defaultDocumentAnswerLength,
  defaultDocumentDepth,
  defaultDocumentFocus,
  defaultDocumentStudyMode,
  defaultCollectionLevels,
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

  it('falls back from the experimental ciba template to immersive v11 in saved video requests', () => {
    window.localStorage.setItem(REQUEST_STORAGE_KEY, JSON.stringify({ template_id: 'ciba_tianxia_v1' }))

    expect(loadSavedRequest().template_id).toBe('immersive_v11')
  })

  it('strips stale ASR hard-gate fields from saved public video requests', () => {
    window.localStorage.setItem(
      REQUEST_STORAGE_KEY,
      JSON.stringify({
        source_mode: 'local',
        video_path: 'E:/media/source.mp4',
        subtitle_path: 'E:/media/source.srt',
        tts_semantic_verification: {
          enabled: true,
          require_pass_for_export: true,
          asr_provider: 'whisper-cli',
        },
        asr_provider: 'whisper-cli',
        require_pass_for_export: true,
        enable_asr_quality_gate: true,
        api_config: {
          ...defaultRequest.api_config,
          tts_semantic_verification: {
            enabled: true,
            require_pass_for_export: true,
            asr_provider: 'whisper-cli',
          },
          asr_provider: 'whisper-cli',
          require_pass_for_export: true,
          enable_asr_quality_gate: true,
        },
      }),
    )

    const request = loadSavedRequest() as typeof defaultRequest & Record<string, unknown>
    const apiConfig = request.api_config as typeof defaultRequest.api_config & Record<string, unknown>

    expect(request.tts_semantic_verification).toBeUndefined()
    expect(request.asr_provider).toBeUndefined()
    expect(request.require_pass_for_export).toBeUndefined()
    expect(request.enable_asr_quality_gate).toBeUndefined()
    expect(apiConfig.tts_semantic_verification).toBeUndefined()
    expect(apiConfig.asr_provider).toBeUndefined()
    expect(apiConfig.require_pass_for_export).toBeUndefined()
    expect(apiConfig.enable_asr_quality_gate).toBeUndefined()
    expect(JSON.stringify(request)).not.toContain('whisper-cli')
  })

  it('resets hidden video tuning settings to the internal smart defaults', () => {
    window.localStorage.setItem(
      REQUEST_STORAGE_KEY,
      JSON.stringify({
        source_mode: 'local',
        level: 'B2',
        collection_levels: ['C2'],
        content_toggles: { daily: false, slang: true },
        language_focus: ['grammar'],
        study_depth: 'standard',
        selection_strategy: 'curated',
        reuse_ai_review_cache: true,
        max_segments: 42,
      }),
    )

    const request = loadSavedRequest()
    expect(request.collection_levels).toEqual(defaultCollectionLevels('B2'))
    expect(request.content_toggles).toEqual(defaultRequest.content_toggles)
    expect(request.language_focus).toEqual(defaultRequest.language_focus)
    expect(request.study_depth).toBe(defaultRequest.study_depth)
    expect(request.selection_strategy).toBe(defaultRequest.selection_strategy)
    expect(request.reuse_ai_review_cache).toBe(false)
    expect(request.max_segments).toBe(0)
  })

  it('preserves fast review density in saved requests and defaults legacy values to full study', () => {
    window.localStorage.setItem(REQUEST_STORAGE_KEY, JSON.stringify({ review_density: 'fast' }))
    expect(loadSavedRequest().review_density).toBe('fast')

    window.localStorage.setItem(REQUEST_STORAGE_KEY, JSON.stringify({ review_density: 'noisy' }))
    expect(loadSavedRequest().review_density).toBe(defaultRequest.review_density)
    expect(defaultRequest.review_density).toBe('full')
  })

  it('preserves batch mode and normalizes batch items in saved requests', () => {
    window.localStorage.setItem(
      REQUEST_STORAGE_KEY,
      JSON.stringify({
        source_mode: 'local',
        batch_enabled: true,
        batch_items: [
          {
            id: 'ep1',
            source_mode: 'local',
            enabled: true,
            title: 'Pilot',
            subdeck_title: 'Pilot',
            video_path: 'D:/Shows/S01E01 Pilot.mp4',
            subtitle_path: 'D:/Shows/S01E01 Pilot.srt',
          },
          {
            id: 'bad',
            source_mode: 'document',
            enabled: true,
            title: '',
            subdeck_title: '',
          },
        ],
      }),
    )

    const saved = loadSavedRequest()
    expect(saved.batch_enabled).toBe(true)
    expect(saved.batch_items).toHaveLength(1)
    expect(saved.batch_items[0]).toMatchObject({
      source_mode: 'local',
      subdeck_title: 'Pilot',
      video_path: 'D:/Shows/S01E01 Pilot.mp4',
      subtitle_path: 'D:/Shows/S01E01 Pilot.srt',
    })
  })

  it('does not persist per-run network and local path security confirmations', () => {
    window.localStorage.setItem(
      REQUEST_STORAGE_KEY,
      JSON.stringify({
        source_mode: 'local',
        video_path: 'E:/media/source.mp4',
        subtitle_path: 'E:/media/source.srt',
        allow_private_network_url: true,
        allow_ytdlp_remote_components: true,
        local_path_access_confirmed: true,
      }),
    )

    const saved = loadSavedRequest()
    expect(saved.allow_private_network_url).toBe(false)
    expect(saved.allow_ytdlp_remote_components).toBe(false)
    expect(saved.local_path_access_confirmed).toBe(false)
  })

  it('falls back to immersive v11 for invalid saved template ids', () => {
    window.localStorage.setItem(REQUEST_STORAGE_KEY, JSON.stringify({ template_id: 'unknown-template' }))

    expect(loadSavedRequest().template_id).toBe('immersive_v11')
  })

  it('keeps legacy document study preferences but restores the public source mode to local video', () => {
    window.localStorage.setItem(
      REQUEST_STORAGE_KEY,
      JSON.stringify({
        source_mode: 'document',
        document_path: 'E:/Docs/source.pdf',
        card_types: ['knowledge'],
        document_study_mode: 'language_reading',
        document_answer_language: 'bilingual',
        document_depth: 'deep',
        document_answer_length: 'long',
      }),
    )

    const request = loadSavedRequest()
    expect(request.source_mode).toBe('local')
    expect(request.document_path).toBe('')
    expect(request.card_types).toEqual(defaultRequest.card_types)
    expect(request.document_study_mode).toBe('language_reading')
    expect(request.document_answer_language).toBe('bilingual')
    expect(request.document_depth).toBe('deep')
    expect(request.document_answer_length).toBe('long')
  })

  it('ignores legacy document language focus in the public video-only workspace', () => {
    window.localStorage.setItem(
      REQUEST_STORAGE_KEY,
      JSON.stringify({
        document_study_mode: 'language_reading',
        language_focus: ['phrases', 'listening', 'grammar'],
      }),
    )

    expect(loadSavedRequest().language_focus).toEqual(defaultRequest.language_focus)
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

  it('does not restore saved document projects into the public video-only workspace', () => {
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

    expect(loadSavedProject()).toBeNull()
  })

  it('falls back from the experimental ciba template to immersive v11 in saved video projects', () => {
    window.localStorage.setItem(
      PROJECT_STORAGE_KEY,
      JSON.stringify({
        ...defaultRequest,
        id: 'ciba-project',
        template_id: 'ciba_tianxia_v1',
        segments: [
          {
            id: 'seg_0001',
            start: 1,
            end: 2,
            source_time: '00:00:01.000 - 00:00:02.000',
            text: 'Can you run the register for a minute?',
            duration: 1,
            recommendation: 4,
            phrase: 'run the register',
            cards: [],
          },
        ],
        created_at: 1,
      }),
    )

    expect(loadSavedProject()?.template_id).toBe('immersive_v11')
  })

  it('preserves fast review density in saved projects', () => {
    window.localStorage.setItem(
      PROJECT_STORAGE_KEY,
      JSON.stringify({
        ...defaultRequest,
        id: 'fast-project',
        review_density: 'fast',
        segments: [
          {
            id: 'seg_0001',
            start: 1,
            end: 2,
            source_time: '00:00:01.000 - 00:00:02.000',
            text: "I'm not really in the mood right now.",
            duration: 1,
            recommendation: 4,
            phrase: 'in the mood',
            cards: [],
          },
        ],
        created_at: 1,
      }),
    )

    expect(loadSavedProject()?.review_density).toBe('fast')
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
          'C:\\Users\\Example\\AppData\\Local\\com.ankicard.generator\\projects\\url_cache\\old\\source.mp4',
        subtitle_path:
          'C:\\Users\\Example\\AppData\\Local\\com.ankicard.generator\\projects\\url_cache\\old\\source.en.srt',
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

  it('does not retain in-memory document batch projects in the public video workspace', () => {
    const project = {
      ...defaultRequest,
      id: 'batch-project',
      source_mode: 'document' as const,
      document_path: '',
      batch_enabled: true,
      batch_items: [
        {
          id: 'doc1',
          source_mode: 'document' as const,
          enabled: true,
          title: 'Retrieval',
          subdeck_title: 'Retrieval',
          document_path: 'E:\\Docs\\retrieval.md',
        },
        {
          id: 'doc2',
          source_mode: 'document' as const,
          enabled: true,
          title: 'Spacing',
          subdeck_title: 'Spacing',
          document_path: 'E:\\Docs\\spacing.md',
        },
      ],
      segments: [],
      created_at: 1,
    }
    const matchingRequest = {
      ...defaultRequest,
      source_mode: 'document' as const,
      document_path: '',
      batch_enabled: true,
      batch_items: project.batch_items,
    }
    const changedRequest = {
      ...matchingRequest,
      batch_items: [project.batch_items[0]],
    }

    expect(projectMatchesRequest(project, matchingRequest)).toBe(false)
    expect(projectMatchesRequest(project, changedRequest)).toBe(false)
  })

  it('matches public local and URL batch projects by their batch item sources', () => {
    const localItems = [
      {
        id: 'local1',
        source_mode: 'local' as const,
        enabled: true,
        title: 'Local 1',
        subdeck_title: 'Local 1',
        video_path: 'E:\\Videos\\one.mp4',
      },
      {
        id: 'local2',
        source_mode: 'local' as const,
        enabled: true,
        title: 'Local 2',
        subdeck_title: 'Local 2',
        video_path: 'E:\\Videos\\two.mp4',
      },
    ]
    const localProject = {
      ...defaultRequest,
      id: 'local-batch-project',
      source_mode: 'local' as const,
      batch_enabled: true,
      batch_items: localItems,
      segments: [],
      created_at: 1,
    }
    const localRequest = {
      ...defaultRequest,
      source_mode: 'local' as const,
      batch_enabled: true,
      batch_items: localItems,
    }

    expect(projectMatchesRequest(localProject, localRequest)).toBe(true)
    expect(projectMatchesRequest(localProject, { ...localRequest, batch_items: [localItems[0]] })).toBe(false)

    const urlItems = [
      {
        id: 'url1',
        source_mode: 'url' as const,
        enabled: true,
        title: 'URL 1',
        subdeck_title: 'URL 1',
        source_url: 'https://www.youtube.com/watch?v=one',
      },
      {
        id: 'url2',
        source_mode: 'url' as const,
        enabled: true,
        title: 'URL 2',
        subdeck_title: 'URL 2',
        source_url: 'https://www.youtube.com/watch?v=two',
      },
    ]
    const urlProject = {
      ...defaultRequest,
      id: 'url-batch-project',
      source_mode: 'url' as const,
      batch_enabled: true,
      batch_items: urlItems,
      segments: [],
      created_at: 1,
    }
    const urlRequest = {
      ...defaultRequest,
      source_mode: 'url' as const,
      batch_enabled: true,
      batch_items: urlItems,
    }

    expect(projectMatchesRequest(urlProject, urlRequest)).toBe(true)
    expect(projectMatchesRequest(urlProject, { ...urlRequest, batch_items: [urlItems[0]] })).toBe(false)
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
