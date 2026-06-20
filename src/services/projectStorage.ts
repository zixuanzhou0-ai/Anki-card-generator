import type {
  ApiConfig,
  GenerateRequest,
  Level,
  LevelMode,
  Project,
  SecretPrefs,
  SourceMode,
  TemplateId,
  TtsConfig,
  TtsProvider,
} from '../domain/types'
import { normalizeBatchItems } from '../domain/batch'
import {
  DEEPSEEK_DEFAULT_MODEL,
  DEEPSEEK_OPENAI_BASE_URL,
  defaultRequest,
  defaultCollectionLevels,
  documentReadingFocusOptions,
  normalizeDocumentAnswerLanguage,
  normalizeDocumentAnswerLength,
  normalizeDocumentDepth,
  normalizeCollectionLevels,
  normalizeCardStyleId,
  normalizeDocumentFocus,
  normalizeDocumentStudyMode,
  normalizeLanguageFocus,
  normalizeLearningLanguage,
  normalizeReviewDensity,
  normalizeSelectionStrategy,
  normalizeStudyDepth,
  publicTemplateIdFor,
  PROJECT_STORAGE_KEY,
  REQUEST_STORAGE_KEY,
  SECRET_PREFS_STORAGE_KEY,
} from '../domain/options'
import { stripStaleOrdinaryAsrGate } from '../domain/payloadSanitization'
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
  const sanitizedRequest = stripStaleOrdinaryAsrGate(request as GenerateRequest & Record<string, unknown>) as GenerateRequest
  const sanitizedApiConfig = stripStaleOrdinaryAsrGate(
    request.api_config as ApiConfig & Record<string, unknown>,
  ) as ApiConfig

  return {
    ...sanitizedRequest,
    api_config: {
      ...sanitizedApiConfig,
      api_key: '',
      tts_config: {
        ...sanitizedApiConfig.tts_config,
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

function normalizeMainFlowTemplateId(value: unknown, sourceMode: SourceMode | undefined): TemplateId {
  return publicTemplateIdFor(value, sourceMode)
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
    const savedSourceMode = (saved.source_mode ?? defaultRequest.source_mode) as SourceMode
    const sourceMode = savedSourceMode === 'document' ? 'local' : savedSourceMode
    const isDocumentSource = false
    const currentLevel = (saved.level ?? defaultRequest.level) as Level
    const documentStudyMode = normalizeDocumentStudyMode(saved.document_study_mode)
    return stripRequestSecrets(
      normalizeSavedApiConfig({
        ...defaultRequest,
        ...saved,
        source_mode: sourceMode,
        template_id: normalizeMainFlowTemplateId(saved.template_id, sourceMode),
        card_style: normalizeCardStyleId(saved.card_style),
        review_density: normalizeReviewDensity(saved.review_density),
        url_import_mode: sourceMode === 'url' ? 'video' : defaultRequest.url_import_mode,
        url_auto_subtitle_fallback: false,
        allow_private_network_url: false,
        allow_ytdlp_remote_components: false,
        local_path_access_confirmed: false,
        skip_video_slicing: false,
        batch_enabled: saved.batch_enabled ?? defaultRequest.batch_enabled,
        batch_items: normalizeBatchItems(saved.batch_items, sourceMode),
        document_path: isDocumentSource ? saved.document_path ?? '' : '',
        language: normalizeLearningLanguage(saved.language),
        level_mode: normalizeLevelMode(saved.level_mode),
        collection_levels: isDocumentSource
          ? normalizeCollectionLevels(saved.collection_levels, currentLevel)
          : defaultCollectionLevels(currentLevel),
        content_toggles: isDocumentSource
          ? {
              ...defaultRequest.content_toggles,
              ...(saved.content_toggles ?? {}),
            }
          : defaultRequest.content_toggles,
        language_focus: isDocumentSource
          ? documentStudyMode === 'language_reading'
            ? normalizeDocumentLanguageFocus(saved.language_focus)
            : normalizeLanguageFocus(saved.language_focus)
          : defaultRequest.language_focus,
        document_focus: normalizeDocumentFocus(saved.document_focus),
        document_study_mode: documentStudyMode,
        document_answer_language: normalizeDocumentAnswerLanguage(saved.document_answer_language),
        document_depth: normalizeDocumentDepth(saved.document_depth),
        document_answer_length: normalizeDocumentAnswerLength(saved.document_answer_length),
        study_depth: isDocumentSource ? normalizeStudyDepth(saved.study_depth) : defaultRequest.study_depth,
        selection_strategy: isDocumentSource
          ? normalizeSelectionStrategy(saved.selection_strategy)
          : defaultRequest.selection_strategy,
        reuse_ai_review_cache: isDocumentSource
          ? (saved.reuse_ai_review_cache ?? defaultRequest.reuse_ai_review_cache)
          : defaultRequest.reuse_ai_review_cache,
        max_segments: isDocumentSource ? (saved.max_segments ?? defaultRequest.max_segments) : defaultRequest.max_segments,
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
        card_types: isDocumentSource
          ? saved.card_types?.length
            ? saved.card_types
            : ['knowledge']
          : saved.card_types?.filter((type) => type !== 'knowledge').length
            ? saved.card_types.filter((type) => type !== 'knowledge')
            : defaultRequest.card_types,
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
    const sourceMode = (saved.source_mode ?? 'local') as SourceMode
    if (sourceMode === 'document') return null
    const project: Project = {
      ...saved,
      template_id: normalizeMainFlowTemplateId(saved.template_id, sourceMode),
      card_style: normalizeCardStyleId(saved.card_style),
      review_density: normalizeReviewDensity(saved.review_density),
      batch_enabled: saved.batch_enabled ?? false,
      batch_items: normalizeBatchItems(saved.batch_items, sourceMode),
      source_mode: sourceMode,
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
  if (request.source_mode === 'document' || projectSourceMode(project) === 'document') return false
  if (projectSourceMode(project) !== request.source_mode) return false

  if (request.batch_enabled) {
    if (!project.batch_enabled) return false
    const requestItems = normalizeBatchItems(request.batch_items, request.source_mode)
    const projectItems = normalizeBatchItems(project.batch_items, request.source_mode)
    if (!requestItems.length || requestItems.length !== projectItems.length) return false
    const sourceKey = (item: (typeof requestItems)[number]) =>
      normalizeMaterialUrl(item.source_url ?? '') || normalizeMaterialPath(item.video_path ?? '') || normalizeMaterialPath(item.document_path ?? '')
    const projectKeys = new Set(projectItems.map(sourceKey).filter(Boolean))
    return requestItems.every((item) => {
      const key = sourceKey(item)
      return Boolean(key && projectKeys.has(key))
    })
  }

  if (request.source_mode === 'url') {
    const requestUrl = normalizeMaterialUrl(request.source_url)
    const projectUrl = normalizeMaterialUrl(
      project.source_url || ('webpage_url' in sourceInfo ? sourceInfo.webpage_url : ''),
    )
    return Boolean(requestUrl && projectUrl && requestUrl === projectUrl)
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
