import type { LearningPointExtractionResult } from '../domain/learningPoints'
import { selectedLearningPoints } from '../domain/learningPoints'
import { stripStaleOrdinaryAsrGate } from '../domain/payloadSanitization'
import { publicTemplateIdFor } from '../domain/templates'
import type {
  ApiConfig,
  CardKind,
  CardStyleId,
  ContentToggles,
  GenerateRequest,
  LanguageFocus,
  Level,
  LevelMode,
  Project,
  ReviewDensity,
  SourceMode,
  StudyDepth,
  TemplateId,
  UrlImportMode,
} from '../domain/types'

export type LearningPointGenerationPayload = LearningPointExtractionResult & {
  project_id: string
  selected_learning_point_ids: string[]
  source_mode: SourceMode
  source_url: string
  url_import_mode: UrlImportMode | ''
  url_auto_subtitle_fallback: boolean
  allow_private_network_url: boolean
  allow_ytdlp_remote_components: boolean
  local_path_access_confirmed: boolean
  video_path: string
  subtitle_path: string
  document_path: string
  skip_video_slicing: boolean
  card_types: CardKind[]
  template_id: TemplateId
  card_style: CardStyleId
  review_density: ReviewDensity
  api_config: ApiConfig
  content_toggles: ContentToggles
  language_focus: LanguageFocus[]
  study_depth: StudyDepth
  level_mode: LevelMode
  level: Level
  disable_card_generation_cache_read?: boolean
  disable_card_generation_cache_write?: boolean
  card_generation_cache_namespace?: string
  existing_project?: Project
  existing_generated_ids?: string[]
}

export type LearningPointExtractionPayload = Omit<
  GenerateRequest,
  | 'source_mode'
  | 'source_url'
  | 'url_import_mode'
  | 'url_auto_subtitle_fallback'
  | 'video_path'
  | 'subtitle_path'
  | 'document_path'
  | 'skip_video_slicing'
  | 'reuse_ai_review_cache'
  | 'api_config'
> & {
  source_mode: SourceMode
  source_url: string
  url_import_mode: UrlImportMode | ''
  url_auto_subtitle_fallback: boolean
  allow_private_network_url: boolean
  allow_ytdlp_remote_components: boolean
  local_path_access_confirmed: boolean
  video_path: string
  subtitle_path: string
  document_path: string
  skip_video_slicing: boolean
  reuse_ai_review_cache: boolean
  disable_ai_review_cache_read: boolean
  disable_ai_review_cache_write: boolean
  api_config: ApiConfig
}

type BuildLearningPointGenerationPayloadInput = {
  learningPointResult: LearningPointExtractionResult
  request: GenerateRequest
  selectedLearningPointIds: Set<string>
  apiConfig: ApiConfig
  projectId: string
  existingProject?: Project | null
  existingGeneratedIds?: string[]
}

type BuildLearningPointExtractionPayloadInput = {
  request: GenerateRequest
  apiConfig: ApiConfig
  reuseAiReviewCache?: boolean
  disableAiReviewCacheRead?: boolean
  disableAiReviewCacheWrite?: boolean
}

type BuildDirectGenerationPayloadInput = {
  request: GenerateRequest
  apiConfig: ApiConfig
}

function stripRuntimeCachePolicyFromApiConfig(apiConfig: ApiConfig): ApiConfig {
  const sanitized = { ...(apiConfig as ApiConfig & Record<string, unknown>) }
  delete sanitized.disable_ai_review_cache
  delete sanitized.disable_ai_review_cache_read
  delete sanitized.disable_ai_review_cache_write
  delete sanitized.disable_card_generation_cache
  delete sanitized.disable_card_generation_cache_read
  delete sanitized.disable_card_generation_cache_write
  delete sanitized.card_generation_cache_namespace
  return sanitized as ApiConfig
}

function sanitizeApiConfigForOrdinaryPayload(apiConfig: ApiConfig): ApiConfig {
  return stripStaleOrdinaryAsrGate(
    stripRuntimeCachePolicyFromApiConfig(apiConfig) as ApiConfig & Record<string, unknown>,
  ) as ApiConfig
}

function sourceSkipVideoSlicing(request: GenerateRequest) {
  if (request.source_mode === 'document') return false
  return false
}

function publicTemplateForRequest(request: Pick<GenerateRequest, 'source_mode' | 'template_id'>): TemplateId {
  return publicTemplateIdFor(request.template_id, request.source_mode)
}

function normalizeExistingProjectForOrdinaryPayload(project: Project, fallbackSourceMode: SourceMode): Project {
  const stripped = stripStaleOrdinaryAsrGate(project as Project & Record<string, unknown>) as Project
  const sourceMode = stripped.source_mode ?? fallbackSourceMode
  if (sourceMode === 'document') {
    return stripped
  }
  return {
    ...stripped,
    source_mode: sourceMode,
    template_id: publicTemplateIdFor(stripped.template_id, sourceMode),
  }
}

function sourceSentencesForSelectedPoints(
  learningPointResult: LearningPointExtractionResult,
  selectedPoints: ReturnType<typeof selectedLearningPoints>,
) {
  const sourceIds = new Set(
    selectedPoints
      .map((point) => point.source_segment_id)
      .filter((id): id is string => Boolean(id)),
  )
  const sourceTexts = new Set(selectedPoints.map((point) => point.source_sentence).filter(Boolean))
  return (learningPointResult.source_sentences ?? []).filter((sentence) => {
    const id = sentence.id || sentence.source_segment_id
    return (id && sourceIds.has(id)) || (sentence.source_sentence && sourceTexts.has(sentence.source_sentence))
  })
}

export function buildLearningPointExtractionPayload({
  request,
  apiConfig,
  reuseAiReviewCache = true,
  disableAiReviewCacheRead = false,
  disableAiReviewCacheWrite = false,
}: BuildLearningPointExtractionPayloadInput): LearningPointExtractionPayload {
  const isUrl = request.source_mode === 'url'
  const isLocal = request.source_mode === 'local'
  const isDocument = request.source_mode === 'document'

  return stripStaleOrdinaryAsrGate({
    ...request,
    source_mode: request.source_mode,
    source_url: isUrl ? request.source_url : '',
    url_import_mode: isUrl ? 'video' : '',
    url_auto_subtitle_fallback: false,
    allow_private_network_url: isUrl ? Boolean(request.allow_private_network_url) : false,
    allow_ytdlp_remote_components: isUrl ? Boolean(request.allow_ytdlp_remote_components) : false,
    local_path_access_confirmed: isLocal || isDocument ? Boolean(request.local_path_access_confirmed) : false,
    video_path: isLocal ? request.video_path : '',
    subtitle_path: isLocal ? request.subtitle_path : '',
    document_path: isDocument ? request.document_path : '',
    skip_video_slicing: sourceSkipVideoSlicing(request),
    template_id: publicTemplateForRequest(request),
    reuse_ai_review_cache: reuseAiReviewCache,
    disable_ai_review_cache_read: disableAiReviewCacheRead,
    disable_ai_review_cache_write: disableAiReviewCacheWrite,
    api_config: sanitizeApiConfigForOrdinaryPayload(apiConfig),
  }) as LearningPointExtractionPayload
}

export function buildLearningPointGenerationPayload({
  learningPointResult,
  request,
  selectedLearningPointIds,
  apiConfig,
  projectId,
  existingProject,
  existingGeneratedIds,
}: BuildLearningPointGenerationPayloadInput): LearningPointGenerationPayload {
  const selectedPoints = selectedLearningPoints(learningPointResult.learning_points, selectedLearningPointIds)
  const selectedSourceSentences = sourceSentencesForSelectedPoints(learningPointResult, selectedPoints)
  const isUrl = request.source_mode === 'url'
  const isLocal = request.source_mode === 'local'
  const isDocument = request.source_mode === 'document'
  const sanitizedExistingProject = existingProject
    ? normalizeExistingProjectForOrdinaryPayload(existingProject, request.source_mode)
    : null

  return stripStaleOrdinaryAsrGate({
    ...learningPointResult,
    project_id: projectId,
    selected_learning_point_ids: selectedPoints.map((point) => point.id),
    learning_points: selectedPoints,
    source_sentences: selectedSourceSentences,
    source_mode: request.source_mode,
    source_url: isUrl ? request.source_url : '',
    url_import_mode: isUrl ? 'video' : '',
    url_auto_subtitle_fallback: false,
    allow_private_network_url: isUrl ? Boolean(request.allow_private_network_url) : false,
    allow_ytdlp_remote_components: isUrl ? Boolean(request.allow_ytdlp_remote_components) : false,
    local_path_access_confirmed: isLocal || isDocument ? Boolean(request.local_path_access_confirmed) : false,
    video_path: isLocal ? request.video_path : '',
    subtitle_path: isLocal ? request.subtitle_path : '',
    document_path: isDocument ? request.document_path : '',
    skip_video_slicing: sourceSkipVideoSlicing(request),
    card_types: request.card_types,
    template_id: publicTemplateForRequest(request),
    card_style: request.card_style,
    review_density: request.review_density,
    api_config: sanitizeApiConfigForOrdinaryPayload(apiConfig),
    content_toggles: request.content_toggles,
    language_focus: request.language_focus,
    study_depth: request.study_depth,
    level_mode: request.level_mode,
    level: request.level,
    ...(sanitizedExistingProject ? { existing_project: sanitizedExistingProject } : {}),
    ...(existingGeneratedIds?.length ? { existing_generated_ids: existingGeneratedIds } : {}),
  }) as LearningPointGenerationPayload
}

export function buildDirectGenerationPayload({
  request,
  apiConfig,
}: BuildDirectGenerationPayloadInput): GenerateRequest {
  const isUrl = request.source_mode === 'url'
  const isLocal = request.source_mode === 'local'
  const isDocument = request.source_mode === 'document'

  return stripStaleOrdinaryAsrGate({
    ...request,
    source_url: isUrl ? request.source_url : '',
    url_import_mode: isUrl ? 'video' : '',
    url_auto_subtitle_fallback: false,
    video_path: isLocal ? request.video_path : '',
    subtitle_path: isLocal ? request.subtitle_path : '',
    document_path: isDocument ? request.document_path : '',
    skip_video_slicing: false,
    allow_private_network_url: isUrl ? Boolean(request.allow_private_network_url) : false,
    allow_ytdlp_remote_components: isUrl ? Boolean(request.allow_ytdlp_remote_components) : false,
    local_path_access_confirmed: !isUrl ? Boolean(request.local_path_access_confirmed) : false,
    template_id: publicTemplateForRequest(request),
    api_config: sanitizeApiConfigForOrdinaryPayload(apiConfig),
  }) as GenerateRequest
}
