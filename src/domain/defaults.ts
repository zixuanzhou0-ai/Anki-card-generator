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
import { DEEPSEEK_DEFAULT_MODEL, DEEPSEEK_OPENAI_BASE_URL } from './providers'
import { defaultSelectionStrategy } from './selectionStrategy'
import { defaultStudyDepth } from './studyDepth'

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
  url_auto_subtitle_fallback: true,
  skip_video_slicing: false,
  video_path: '',
  subtitle_path: '',
  document_path: '',
  language: 'English',
  level: 'B1',
  collection_levels: defaultCollectionLevels('B1'),
  template_id: 'immersive_v11',
  content_toggles: defaultToggles,
  language_focus: defaultLanguageFocus,
  document_focus: defaultDocumentFocus,
  document_study_mode: defaultDocumentStudyMode,
  document_answer_language: defaultDocumentAnswerLanguage,
  document_depth: defaultDocumentDepth,
  document_answer_length: defaultDocumentAnswerLength,
  study_depth: defaultStudyDepth,
  selection_strategy: defaultSelectionStrategy,
  card_types: ['listening', 'phrase', 'cloze'],
  max_segments: 0,
  api_config: {
    provider: 'openai-compatible',
    base_url: DEEPSEEK_OPENAI_BASE_URL,
    api_key: '',
    model: DEEPSEEK_DEFAULT_MODEL,
    capabilities: ['structured_json', 'long_context'],
    tts_config: {
      enabled: false,
      provider: 'grok',
      base_url: 'https://api.x.ai/v1',
      api_key: '',
      model: '',
      voice: 'eve',
      language: 'auto',
      sample_rate: 24000,
      bit_rate: 128000,
    },
  },
}

export const REQUEST_STORAGE_KEY = 'anki-card-generator.request.v1'
export const SECRET_PREFS_STORAGE_KEY = 'anki-card-generator.secret-prefs.v2'
