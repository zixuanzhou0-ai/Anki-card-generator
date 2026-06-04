import type {
  ApiConfig,
  GenerateRequest,
  Level,
  LevelMode,
  Project,
  SecretPrefs,
  TtsConfig,
  TtsProvider,
  UrlImportMode,
} from '../domain/types'
import {
  DEEPSEEK_DEFAULT_MODEL,
  DEEPSEEK_OPENAI_BASE_URL,
  defaultRequest,
  documentReadingFocusOptions,
  normalizeDocumentAnswerLanguage,
  normalizeDocumentAnswerLength,
  normalizeDocumentDepth,
  normalizeCollectionLevels,
  normalizeDocumentFocus,
  normalizeDocumentStudyMode,
  normalizeLanguageFocus,
  normalizeLearningLanguage,
  normalizeSelectionStrategy,
  normalizeStudyDepth,
  PROJECT_STORAGE_KEY,
  REQUEST_STORAGE_KEY,
  SECRET_PREFS_STORAGE_KEY,
} from '../domain/options'
import { normalizeDeepSeekModelId, normalizeMimoModelId } from './apiConfig'
import { isTauriRuntime } from './runtime'

export function normalizeSavedApiConfig(saved: GenerateRequest): GenerateRequest {
  const apiBase = saved.api_config.base_url.toLowerCase()
  const apiModel = saved.api_config.model.trim().toLowerCase()
  const isMimoText = saved.api_config.provider === 'mimo' || apiBase.includes('xiaomimimo.com')
  const isDeepSeekText =
    saved.api_config.provider === 'local' ||
    apiBase.includes('deepseek.com') ||
    apiModel.startsWith('deepseek-') ||
    (saved.api_config.provider === 'openai-compatible' &&
      (!saved.api_config.base_url.trim() || !saved.api_config.model.trim()))
  const ttsBase = saved.api_config.tts_config.base_url.toLowerCase()
  const isMimoTts = saved.api_config.tts_config.provider === 'mimo' || ttsBase.includes('xiaomimimo.com')
  const deepSeekModel = normalizeDeepSeekModelId(saved.api_config.model)

  return {
    ...saved,
    api_config: {
      ...saved.api_config,
      provider: isDeepSeekText ? 'openai-compatible' : saved.api_config.provider,
      base_url: isDeepSeekText ? DEEPSEEK_OPENAI_BASE_URL : saved.api_config.base_url,
      model: isDeepSeekText
        ? deepSeekModel.toLowerCase().startsWith('deepseek-')
          ? deepSeekModel
          : DEEPSEEK_DEFAULT_MODEL
        : isMimoText
          ? normalizeMimoModelId(saved.api_config.model)
          : saved.api_config.model,
      capabilities: isDeepSeekText
        ? Array.from(new Set([...(saved.api_config.capabilities ?? []), 'structured_json', 'long_context']))
        : saved.api_config.capabilities,
      tts_config: {
        ...saved.api_config.tts_config,
        model: isMimoTts ? normalizeMimoModelId(saved.api_config.tts_config.model) : saved.api_config.tts_config.model,
      },
    },
  }
}

export const normalizeSavedMimoConfig = normalizeSavedApiConfig

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

function normalizeLevelMode(value: unknown): LevelMode {
  return value === 'manual' ? 'manual' : 'auto'
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
    return stripRequestSecrets(
      normalizeSavedApiConfig({
        ...defaultRequest,
        ...saved,
        template_id: 'immersive_v11',
        url_import_mode: (saved.url_import_mode ?? defaultRequest.url_import_mode) as UrlImportMode,
        url_auto_subtitle_fallback: saved.url_auto_subtitle_fallback ?? defaultRequest.url_auto_subtitle_fallback,
        skip_video_slicing: saved.skip_video_slicing ?? defaultRequest.skip_video_slicing,
        language: normalizeLearningLanguage(saved.language),
        level_mode: normalizeLevelMode(saved.level_mode),
        collection_levels: normalizeCollectionLevels(
          saved.collection_levels,
          (saved.level ?? defaultRequest.level) as Level,
        ),
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
        selection_strategy: normalizeSelectionStrategy(saved.selection_strategy),
        api_config: {
          ...defaultRequest.api_config,
          ...savedApi,
          tts_config: {
            ...defaultRequest.api_config.tts_config,
            ...savedTts,
            provider: (savedTts.provider ??
              legacyTtsProvider ??
              defaultRequest.api_config.tts_config.provider) as TtsProvider,
            voice: savedTts.voice ?? legacyTtsModel ?? defaultRequest.api_config.tts_config.voice,
            enabled: savedTts.enabled ?? Boolean(legacyTtsProvider),
          },
        },
        card_types: saved.card_types?.length ? saved.card_types : defaultRequest.card_types,
      }),
    )
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
    const project: Project = {
      ...saved,
      template_id: 'immersive_v11',
      source_mode: saved.source_mode ?? 'local',
      language: normalizeLearningLanguage(saved.language),
      level_mode: normalizeLevelMode(saved.level_mode),
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
      selection_strategy: normalizeSelectionStrategy(saved.selection_strategy),
      material_context: saved.material_context ?? null,
      segments: saved.segments.map((segment) => ({
        ...segment,
        cards: Array.isArray(segment.cards) ? segment.cards : [],
      })),
    }
    return project
  } catch {
    return null
  }
}

function normalizeMaterialPath(value: unknown) {
  return String(value ?? '')
    .trim()
    .replace(/^["']|["']$/g, '')
    .replace(/\//g, '\\')
    .toLocaleLowerCase()
}

function normalizeMaterialUrl(value: unknown) {
  return String(value ?? '').trim()
}

function projectSourceMode(project: Project) {
  if (project.source_mode) return project.source_mode
  if (project.source_url) return 'url'
  if (project.document_path) return 'document'
  return 'local'
}

export function projectMatchesRequest(project: Project, request: GenerateRequest) {
  const sourceInfo = project.source_info ?? {}
  if (projectSourceMode(project) !== request.source_mode) return false

  if (request.source_mode === 'url') {
    const requestUrl = normalizeMaterialUrl(request.source_url)
    const projectUrl = normalizeMaterialUrl(
      project.source_url || ('webpage_url' in sourceInfo ? sourceInfo.webpage_url : ''),
    )
    return Boolean(requestUrl && projectUrl && requestUrl === projectUrl)
  }

  if (request.source_mode === 'document') {
    const requestDocumentPath = normalizeMaterialPath(request.document_path)
    const projectDocumentPath = normalizeMaterialPath(
      project.document_path || ('document_path' in sourceInfo ? sourceInfo.document_path : ''),
    )
    return Boolean(requestDocumentPath && projectDocumentPath && requestDocumentPath === projectDocumentPath)
  }

  const requestVideoPath = normalizeMaterialPath(request.video_path)
  const projectVideoPath = normalizeMaterialPath(
    project.video_path || ('video_path' in sourceInfo ? sourceInfo.video_path : ''),
  )
  if (!requestVideoPath || !projectVideoPath || requestVideoPath !== projectVideoPath) return false

  const requestSubtitlePath = normalizeMaterialPath(request.subtitle_path)
  const projectSubtitlePath = normalizeMaterialPath(
    project.subtitle_path || ('subtitle_path' in sourceInfo ? sourceInfo.subtitle_path : ''),
  )
  if (requestSubtitlePath && projectSubtitlePath && requestSubtitlePath !== projectSubtitlePath) return false

  return true
}

export function loadSavedProjectForRequest(request: GenerateRequest): Project | null {
  const project = loadSavedProject()
  return project && projectMatchesRequest(project, request) ? project : null
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
