import type { ApiConfig, GenerateRequest } from '../domain/types'

const SOURCE_CONTRACT_KEYS = [
  'source_mode',
  'source_url',
  'video_path',
  'subtitle_path',
  'document_path',
  'batch_enabled',
  'batch_items',
] satisfies Array<keyof GenerateRequest>

const LEARNING_CONTRACT_KEYS = [
  'language',
  'level_mode',
  'level',
  'collection_levels',
  'review_density',
  'card_style',
  'card_types',
  'content_toggles',
  'language_focus',
  'study_depth',
  'selection_strategy',
  'max_segments',
] satisfies Array<keyof GenerateRequest>

const EXPORT_RUNTIME_CONTRACT_KEYS = ['api_config', 'template_id'] satisfies Array<keyof GenerateRequest>

function hasOwnKey(patch: Partial<GenerateRequest>, key: keyof GenerateRequest) {
  return Object.prototype.hasOwnProperty.call(patch, key)
}

function normalizedModelConnection(config: ApiConfig) {
  return {
    provider: config.provider,
    baseUrl: config.base_url.trim().replace(/\/+$/u, '').toLowerCase(),
    model: config.model.trim(),
    capabilities: [...config.capabilities].sort(),
  }
}

export function modelApiConfigChangeInvalidatesLearningArtifacts(current: ApiConfig, next: ApiConfig) {
  return JSON.stringify(normalizedModelConnection(current)) !== JSON.stringify(normalizedModelConnection(next))
}

export function requestPatchTouchesSourceMaterial(patch: Partial<GenerateRequest>) {
  return SOURCE_CONTRACT_KEYS.some((key) => hasOwnKey(patch, key))
}

export function requestPatchInvalidatesLearningArtifacts(patch: Partial<GenerateRequest>) {
  return requestPatchTouchesSourceMaterial(patch) || LEARNING_CONTRACT_KEYS.some((key) => hasOwnKey(patch, key))
}

export function requestPatchInvalidatesExportArtifacts(patch: Partial<GenerateRequest>) {
  return (
    requestPatchInvalidatesLearningArtifacts(patch) || EXPORT_RUNTIME_CONTRACT_KEYS.some((key) => hasOwnKey(patch, key))
  )
}
