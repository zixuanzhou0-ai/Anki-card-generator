import type { ContentToggles, GenerateRequest } from './types'
import { contentOptions } from './cards'
import { defaultDocumentFocus } from './documentFocus'
import {
  defaultDocumentAnswerLanguage,
  defaultDocumentAnswerLength,
  defaultDocumentDepth,
  defaultDocumentStudyMode,
} from './documentStudy'
import { defaultCollectionLevels } from './levels'
import { defaultLanguageFocus } from './learningFocus'
import { GEMINI_VERTEX_DEFAULT_MODEL, GEMINI_VERTEX_GLOBAL_BASE_URL } from './providers'
import {
  GEMINI_VERTEX_TTS_DEFAULT_MODEL,
  GEMINI_VERTEX_TTS_DEFAULT_VOICE,
  GEMINI_VERTEX_TTS_GLOBAL_BASE_URL,
} from './ttsProviders'
import { defaultReviewDensity } from './reviewDensity'
import { defaultSelectionStrategy } from './selectionStrategy'
import { defaultStudyDepth } from './studyDepth'
import { defaultCardStyle } from './templates'

export const PROJECT_STORAGE_KEY = 'anki-card-generator:last-project'
export const defaultToggles = contentOptions.reduce((result, item) => {
  result[item.key] = item.defaultOn
  return result
}, {} as ContentToggles)

export const defaultRequest: GenerateRequest = {
  title: '',
  source_mode: 'local',
  source_url: '',
  url_import_mode: 'video',
  url_auto_subtitle_fallback: false,
  allow_private_network_url: false,
  allow_ytdlp_remote_components: false,
  local_path_access_confirmed: false,
  skip_video_slicing: false,
  batch_enabled: false,
  batch_items: [],
  video_path: '',
  subtitle_path: '',
  document_path: '',
  language: 'en',
  level_mode: 'auto',
  level: 'B1',
  collection_levels: defaultCollectionLevels('B1'),
  template_id: 'immersive_v11',
  card_style: defaultCardStyle,
  review_density: defaultReviewDensity,
  content_toggles: defaultToggles,
  language_focus: defaultLanguageFocus,
  document_focus: defaultDocumentFocus,
  document_study_mode: defaultDocumentStudyMode,
  document_answer_language: defaultDocumentAnswerLanguage,
  document_depth: defaultDocumentDepth,
  document_answer_length: defaultDocumentAnswerLength,
  study_depth: defaultStudyDepth,
  selection_strategy: defaultSelectionStrategy,
  reuse_ai_review_cache: false,
  card_types: ['phrase'],
  max_segments: 0,
  api_config: {
    provider: 'gemini-vertex',
    base_url: GEMINI_VERTEX_GLOBAL_BASE_URL,
    api_key: '',
    model: GEMINI_VERTEX_DEFAULT_MODEL,
    capabilities: ['structured_json', 'long_context', 'cheap_batch'],
    tts_config: {
      enabled: true,
      provider: 'gemini-vertex',
      base_url: GEMINI_VERTEX_TTS_GLOBAL_BASE_URL,
      api_key: '',
      model: GEMINI_VERTEX_TTS_DEFAULT_MODEL,
      voice: GEMINI_VERTEX_TTS_DEFAULT_VOICE,
      language: 'auto',
      sample_rate: 24000,
      bit_rate: 128000,
      output_volume: 0.65,
    },
  },
}

export const REQUEST_STORAGE_KEY = 'anki-card-generator.request.v1'
export const SECRET_PREFS_STORAGE_KEY = 'anki-card-generator.secret-prefs.v2'
