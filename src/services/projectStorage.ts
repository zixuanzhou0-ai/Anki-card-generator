import type { ApiConfig, GenerateRequest, Level, Project, SecretPrefs, TtsConfig, TtsProvider, UrlImportMode } from '../domain/types'
import {
  defaultRequest,
  documentReadingFocusOptions,
  normalizeDocumentAnswerLanguage,
  normalizeDocumentAnswerLength,
  normalizeDocumentDepth,
  normalizeCollectionLevels,
  normalizeDocumentFocus,
  normalizeDocumentStudyMode,
  normalizeLanguageFocus,
  normalizeStudyDepth,
  PROJECT_STORAGE_KEY,
  REQUEST_STORAGE_KEY,
  SECRET_PREFS_STORAGE_KEY,
} from '../domain/options'
import { normalizeMimoModelId } from './apiConfig'
import { isTauriRuntime } from './runtime'

export function normalizeSavedMimoConfig(saved: GenerateRequest): GenerateRequest {
  const apiBase = saved.api_config.base_url.toLowerCase()
  const isMimoText = saved.api_config.provider === 'mimo' || apiBase.includes('xiaomimimo.com')
  const ttsBase = saved.api_config.tts_config.base_url.toLowerCase()
  const isMimoTts = saved.api_config.tts_config.provider === 'mimo' || ttsBase.includes('xiaomimimo.com')

  return {
    ...saved,
    api_config: {
      ...saved.api_config,
      model: isMimoText ? normalizeMimoModelId(saved.api_config.model) : saved.api_config.model,
      tts_config: {
        ...saved.api_config.tts_config,
        model: isMimoTts ? normalizeMimoModelId(saved.api_config.tts_config.model) : saved.api_config.tts_config.model,
      },
    },
  }
}

export function stripRequestSecrets(request: GenerateRequest): GenerateRequest {
  return {
    ...request,
    api_config: {
      ...request.api_config,
      api_key: '',
      tts_config: {
        ...request.api_config.tts_config,
        api_key: '',
      },
    },
  }
}

function normalizeDocumentLanguageFocus(value: unknown) {
  const focus = normalizeLanguageFocus(value).filter((item) => documentReadingFocusOptions.includes(item))
  return focus.length ? focus : (['phrases'] as typeof focus)
}

export function loadSavedRequest(): GenerateRequest {
  if (typeof window === 'undefined') return defaultRequest
  try {
    const raw = window.localStorage.getItem(REQUEST_STORAGE_KEY)
    if (!raw) return defaultRequest
    const saved = JSON.parse(raw) as Partial<GenerateRequest>
    const savedApi = (saved.api_config ?? {}) as Partial<ApiConfig>
    const savedTts = (savedApi.tts_config ?? {}) as Partial<TtsConfig>
    const legacyTtsProvider = savedApi.tts_provider?.trim()
    const legacyTtsModel = savedApi.tts_model?.trim()
    const documentStudyMode = normalizeDocumentStudyMode(saved.document_study_mode)
    return stripRequestSecrets(normalizeSavedMimoConfig({
      ...defaultRequest,
      ...saved,
      template_id: 'immersive_v11',
      url_import_mode: (saved.url_import_mode ?? defaultRequest.url_import_mode) as UrlImportMode,
      url_auto_subtitle_fallback: saved.url_auto_subtitle_fallback ?? defaultRequest.url_auto_subtitle_fallback,
      skip_video_slicing: saved.skip_video_slicing ?? defaultRequest.skip_video_slicing,
      collection_levels: normalizeCollectionLevels(saved.collection_levels, (saved.level ?? defaultRequest.level) as Level),
      content_toggles: {
        ...defaultRequest.content_toggles,
        ...(saved.content_toggles ?? {}),
      },
      language_focus:
        documentStudyMode === 'language_reading'
          ? normalizeDocumentLanguageFocus(saved.language_focus)
          : normalizeLanguageFocus(saved.language_focus),
      document_focus: normalizeDocumentFocus(saved.document_focus),
      document_study_mode: documentStudyMode,
      document_answer_language: normalizeDocumentAnswerLanguage(saved.document_answer_language),
      document_depth: normalizeDocumentDepth(saved.document_depth),
      document_answer_length: normalizeDocumentAnswerLength(saved.document_answer_length),
      study_depth: normalizeStudyDepth(saved.study_depth),
      api_config: {
        ...defaultRequest.api_config,
        ...savedApi,
        tts_config: {
          ...defaultRequest.api_config.tts_config,
          ...savedTts,
          provider: (savedTts.provider ?? legacyTtsProvider ?? defaultRequest.api_config.tts_config.provider) as TtsProvider,
          voice: savedTts.voice ?? legacyTtsModel ?? defaultRequest.api_config.tts_config.voice,
          enabled: savedTts.enabled ?? Boolean(legacyTtsProvider),
        },
      },
      card_types: saved.card_types?.length ? saved.card_types : defaultRequest.card_types,
    }))
  } catch {
    return defaultRequest
  }
}

export function loadSavedProject(): Project | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(PROJECT_STORAGE_KEY)
    if (!raw) return null
    const saved = JSON.parse(raw) as Project
    if (!saved || !Array.isArray(saved.segments) || saved.segments.length === 0) return null
    const documentStudyMode = normalizeDocumentStudyMode(saved.document_study_mode)
    return {
      ...saved,
      template_id: 'immersive_v11',
      source_mode: saved.source_mode ?? 'local',
      language_focus:
        documentStudyMode === 'language_reading'
          ? normalizeDocumentLanguageFocus(saved.language_focus)
          : normalizeLanguageFocus(saved.language_focus),
      document_focus: normalizeDocumentFocus(saved.document_focus),
      document_study_mode: documentStudyMode,
      document_answer_language: normalizeDocumentAnswerLanguage(saved.document_answer_language),
      document_depth: normalizeDocumentDepth(saved.document_depth),
      document_answer_length: normalizeDocumentAnswerLength(saved.document_answer_length),
      study_depth: normalizeStudyDepth(saved.study_depth),
      material_context: saved.material_context ?? null,
      segments: saved.segments.map((segment) => ({
        ...segment,
        cards: Array.isArray(segment.cards) ? segment.cards : [],
      })),
    }
  } catch {
    return null
  }
}

export function loadSecretPrefs(): SecretPrefs {
  const defaults = defaultSecretPrefs()
  if (typeof window === 'undefined') return defaults
  try {
    const raw = window.localStorage.getItem(SECRET_PREFS_STORAGE_KEY)
    if (!raw) return defaults
    const parsed = JSON.parse(raw) as Partial<SecretPrefs>
    return {
      rememberModelKey: Boolean(parsed.rememberModelKey),
      rememberTtsKey: Boolean(parsed.rememberTtsKey),
    }
  } catch {
    return defaults
  }
}

function defaultSecretPrefs(): SecretPrefs {
  return isTauriRuntime()
    ? { rememberModelKey: true, rememberTtsKey: true }
    : { rememberModelKey: false, rememberTtsKey: false }
}
