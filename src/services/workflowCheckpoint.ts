import { invoke } from '@tauri-apps/api/core'

import type { ArtifactStage, ProductStep } from '../app/workflowState'
import type { TaskSnapshot } from '../app/workerTaskState'
import type { GenerateRequest } from '../domain/types'
import { stripRequestSecrets } from './projectStorage'
import type { RecoveryFileInspection } from './nativeShell'
import { isTauriRuntime } from './runtime'

export type WorkflowArtifactKind =
  | 'learning-points'
  | 'project'
  | 'generation-queue'
  | 'export-result'
  | 'anki-verification'

export type GenerationQueueCheckpoint = {
  selectedIds: string[]
  completedIds: string[]
  activeBatchIds: string[]
}
export type WorkflowFileEvidence = {
  path: string
  size: number
  modifiedAtMs: number
  sha256?: string
}
export type WorkflowSourceEvidenceRole = 'video' | 'subtitle' | 'document'

export type WorkflowSourceFileRef = {
  id: string
  role: WorkflowSourceEvidenceRole
  path: string
  batchItemId?: string
}

export type WorkflowSourceFileEvidence = WorkflowFileEvidence & WorkflowSourceFileRef

export type WorkflowFileEvidenceIssueCode =
  | 'INVALID_PATH'
  | 'INSPECTION_FAILED'
  | 'FILE_MISSING'
  | 'NOT_REGULAR_FILE'
  | 'INVALID_METADATA'
  | 'SHA256_MISSING'
  | 'SHA256_INVALID'
  | 'SOURCE_CHANGED'
  | 'APKG_CHANGED'

export type WorkflowFileEvidenceBuildResult =
  | { ok: true; evidence: WorkflowFileEvidence }
  | { ok: false; code: WorkflowFileEvidenceIssueCode; message: string }

export type WorkflowFileEvidenceComparison =
  | { matches: true }
  | { matches: false; code: WorkflowFileEvidenceIssueCode; message: string }

export function remainingGenerationQueueIds(queue: GenerationQueueCheckpoint | undefined): string[] {
  if (!queue) return []
  const completed = new Set(queue.completedIds)
  const active = new Set(queue.activeBatchIds)
  return queue.selectedIds.filter((id) => active.has(id) || !completed.has(id))
}
export function remainingGenerationQueueIdsAfterSuccessfulActiveBatch(
  queue: GenerationQueueCheckpoint | undefined,
): string[] {
  if (!queue) return []
  const completed = new Set([...queue.completedIds, ...queue.activeBatchIds])
  return queue.selectedIds.filter((id) => !completed.has(id))
}
export type WorkflowCheckpointV1 = {
  schemaVersion: 1
  request: GenerateRequest
  requestFingerprint: string
  sourceFingerprint?: string
  sourceEvidence?: WorkflowSourceFileEvidence[]
  productStep: ProductStep
  artifactStage: ArtifactStage
  learningPointResultRef?: string
  projectRef?: string
  generationQueue?: GenerationQueueCheckpoint
  outputDirectory?: string
  exportResultRef?: string
  apkgPath?: string
  apkgSha256?: string
  apkgEvidence?: WorkflowFileEvidence
  ankiVerificationRef?: string
  task?: TaskSnapshot
  updatedAt: number
}

const FORBIDDEN_CHECKPOINT_KEYS = new Set([
  'api_key',
  'password',
  'cookie',
  'authorization',
  'access_token',
  'refresh_token',
  'oauth_token',
])

function normalizeForStableJson(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(normalizeForStableJson)
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, child]) => [key, normalizeForStableJson(child)]),
    )
  }
  return value
}

export function stableWorkflowJson(value: unknown): string {
  return JSON.stringify(normalizeForStableJson(value))
}

function fnv1a(value: string): string {
  let hash = 0x811c9dc5
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 0x01000193)
  }
  return (hash >>> 0).toString(16).padStart(8, '0')
}

export function fingerprintWorkflowRequest(request: GenerateRequest): string {
  const sanitized = stripRequestSecrets(request)
  return 'request-v1-' + fnv1a(stableWorkflowJson(sanitized))
}

function cleanWorkflowLocalPath(value: unknown): string {
  return String(value ?? '')
    .trim()
    .replace(/^(["'])(.+)\1$/u, '$2')
}

export function collectWorkflowSourceFileRefs(
  request: Pick<
    GenerateRequest,
    'source_mode' | 'video_path' | 'subtitle_path' | 'document_path' | 'batch_enabled' | 'batch_items'
  >,
): WorkflowSourceFileRef[] {
  const refs: WorkflowSourceFileRef[] = []
  const add = (id: string, role: WorkflowSourceEvidenceRole, value: unknown, batchItemId?: string) => {
    const path = cleanWorkflowLocalPath(value)
    if (!path) return
    refs.push({ id, role, path, ...(batchItemId ? { batchItemId } : {}) })
  }

  if (request.batch_enabled) {
    for (const item of request.batch_items ?? []) {
      if (item.enabled === false) continue
      if (item.source_mode === 'local') {
        add('batch:' + item.id + ':video', 'video', item.video_path, item.id)
        add('batch:' + item.id + ':subtitle', 'subtitle', item.subtitle_path, item.id)
      } else if (item.source_mode === 'document') {
        add('batch:' + item.id + ':document', 'document', item.document_path, item.id)
      }
    }
  } else if (request.source_mode === 'local') {
    add('single:video', 'video', request.video_path)
    add('single:subtitle', 'subtitle', request.subtitle_path)
  } else if (request.source_mode === 'document') {
    add('single:document', 'document', request.document_path)
  }

  return refs.sort((left, right) => left.id.localeCompare(right.id))
}

export function fingerprintWorkflowSource(
  request: Pick<
    GenerateRequest,
    'source_mode' | 'source_url' | 'video_path' | 'subtitle_path' | 'document_path' | 'batch_enabled' | 'batch_items'
  >,
): string {
  const files = collectWorkflowSourceFileRefs(request)
  const remoteSources = request.batch_enabled
    ? (request.batch_items ?? [])
        .filter((item) => item.enabled !== false)
        .map((item) => ({
          id: item.id,
          sourceMode: item.source_mode,
          sourceUrl: item.source_mode === 'url' ? String(item.source_url ?? '').trim() : '',
        }))
        .sort((left, right) => left.id.localeCompare(right.id))
    : [
        {
          id: 'single',
          sourceMode: request.source_mode,
          sourceUrl: request.source_mode === 'url' ? request.source_url.trim() : '',
        },
      ]

  return (
    'source-v2-' +
    fnv1a(
      stableWorkflowJson({
        sourceMode: request.source_mode,
        batchEnabled: request.batch_enabled,
        files,
        remoteSources,
      }),
    )
  )
}

const MAX_TEXT_LENGTH = 32_768
const MAX_ID_LENGTH = 512
const MAX_LIST_LENGTH = 10_000
const ARTIFACT_REFERENCE_PATTERN = /^[A-Za-z0-9._-]+\.json$/u
const RESERVED_WINDOWS_STEM_PATTERN = /^(?:con|prn|aux|nul|clock\$|com[1-9]|lpt[1-9])$/iu
const PRODUCT_STEPS = ['source', 'select', 'deliver'] as const
const ARTIFACT_STAGES = [
  'empty',
  'source_ready',
  'learning_points_ready',
  'drafts_ready',
  'apkg_ready',
  'anki_verified',
] as const
const SOURCE_MODES = ['local', 'url', 'document'] as const
const URL_IMPORT_MODES = ['video', 'subtitles'] as const
const LANGUAGES = ['en', 'fr', 'es', 'ja', 'ru'] as const
const LEVEL_MODES = ['auto', 'manual'] as const
const LEVELS = ['A1', 'A2', 'B1', 'B2', 'C1', 'C2'] as const
const TEMPLATE_IDS = ['immersive_v11', 'ciba_tianxia_v1', 'immersive', 'dictionary', 'minimal'] as const
const CARD_STYLE_IDS = ['warm_paper', 'minimal_white', 'dark_immersive'] as const
const REVIEW_DENSITIES = ['full', 'fast'] as const
const LANGUAGE_FOCUS_VALUES = ['phrases', 'vocabulary', 'grammar', 'listening'] as const
const DOCUMENT_FOCUS_VALUES = ['concepts', 'arguments', 'terms', 'examples'] as const
const DOCUMENT_STUDY_MODES = ['knowledge', 'language_reading'] as const
const DOCUMENT_ANSWER_LANGUAGES = [
  'zh',
  'en',
  'bilingual',
  'ja',
  'ko',
  'es',
  'fr',
  'de',
  'ru',
  'pt',
  'it',
  'ar',
] as const
const DOCUMENT_DEPTHS = ['quick', 'standard', 'deep'] as const
const DOCUMENT_ANSWER_LENGTHS = ['short', 'medium', 'long'] as const
const STUDY_DEPTHS = ['standard', 'deep'] as const
const SELECTION_STRATEGIES = ['catch_all', 'curated', 'exhaustive'] as const
const CARD_KINDS = ['listening', 'phrase', 'cloze', 'knowledge'] as const
const API_PROVIDERS = ['local', 'mimo', 'openai-compatible', 'claude', 'gemini', 'gemini-vertex'] as const
const TTS_PROVIDERS = ['disabled', 'mimo', 'qwen', 'grok', 'gemini', 'gemini-vertex', 'openai-compatible'] as const
const BATCH_STATUSES = ['pending', 'ready', 'failed', 'skipped', 'generated', 'exported'] as const
const WORKER_COMMANDS = [
  'check_env',
  'repair_env',
  'test_api',
  'test_tts',
  'extract_learning_points',
  'generate_cards_from_learning_points',
  'generate',
  'export',
  'verify_anki_import',
] as const
const OPERATION_STATES = [
  'idle',
  'queued',
  'running',
  'cancelling',
  'succeeded',
  'failed',
  'cancelled',
  'interrupted',
] as const

type UnknownRecord = Record<string, unknown>

function isPlainRecord(value: unknown): value is UnknownRecord {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const prototype = Object.getPrototypeOf(value)
  return prototype === Object.prototype || prototype === null
}

function isBoundedString(value: unknown, maximum = MAX_TEXT_LENGTH): value is string {
  return (
    typeof value === 'string' &&
    value.length <= maximum &&
    !Array.from(value).some((character) => character.charCodeAt(0) <= 31)
  )
}

function isNonEmptyString(value: unknown, maximum = MAX_ID_LENGTH): value is string {
  return isBoundedString(value, maximum) && value.trim().length > 0
}

function isOptionalString(value: unknown, maximum = MAX_TEXT_LENGTH): value is string | undefined {
  return value === undefined || isBoundedString(value, maximum)
}

function isOptionalBoolean(value: unknown): value is boolean | undefined {
  return value === undefined || typeof value === 'boolean'
}

function isSafeIntegerInRange(value: unknown, minimum = 0, maximum = Number.MAX_SAFE_INTEGER): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= minimum && value <= maximum
}

function isFiniteNumberInRange(value: unknown, minimum: number, maximum: number): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= minimum && value <= maximum
}

function isEnumValue<const T extends readonly string[]>(value: unknown, allowed: T): value is T[number] {
  return typeof value === 'string' && (allowed as readonly string[]).includes(value)
}

function isUniqueStringList(
  value: unknown,
  options: { maximum?: number; allowEmpty?: boolean; allowed?: readonly string[] } = {},
): value is string[] {
  if (!Array.isArray(value) || value.length > (options.maximum ?? MAX_LIST_LENGTH)) return false
  if (options.allowEmpty === false && value.length === 0) return false
  const seen = new Set<string>()
  for (const item of value) {
    if (!isNonEmptyString(item)) return false
    if (options.allowed && !options.allowed.includes(item)) return false
    if (seen.has(item)) return false
    seen.add(item)
  }
  return true
}

function isContentToggles(value: unknown): boolean {
  if (!isPlainRecord(value)) return false
  return ['daily', 'slang', 'sarcasm', 'business', 'culture', 'profanity', 'romance', 'rare'].every(
    (key) => typeof value[key] === 'boolean',
  )
}

function isBatchSourceItem(value: unknown): boolean {
  if (!isPlainRecord(value)) return false
  return (
    isNonEmptyString(value.id) &&
    isBoundedString(value.title) &&
    isBoundedString(value.subdeck_title) &&
    isEnumValue(value.source_mode, SOURCE_MODES) &&
    typeof value.enabled === 'boolean' &&
    (value.index === undefined || isSafeIntegerInRange(value.index, 0, MAX_LIST_LENGTH)) &&
    isOptionalString(value.deck_name) &&
    (value.status === undefined || isEnumValue(value.status, BATCH_STATUSES)) &&
    isOptionalString(value.source_url) &&
    isOptionalString(value.video_path) &&
    isOptionalString(value.subtitle_path) &&
    isOptionalString(value.document_path) &&
    isOptionalString(value.warning)
  )
}

function isBatchSourceItemList(value: unknown): boolean {
  if (!Array.isArray(value) || value.length > MAX_LIST_LENGTH) return false
  const ids = new Set<string>()
  return value.every((item) => {
    if (!isBatchSourceItem(item)) return false
    const id = (item as UnknownRecord).id as string
    if (ids.has(id)) return false
    ids.add(id)
    return true
  })
}

function isTtsConfig(value: unknown): boolean {
  if (!isPlainRecord(value)) return false
  return (
    typeof value.enabled === 'boolean' &&
    isEnumValue(value.provider, TTS_PROVIDERS) &&
    isBoundedString(value.base_url) &&
    isBoundedString(value.api_key) &&
    isBoundedString(value.model) &&
    isBoundedString(value.voice) &&
    isNonEmptyString(value.language) &&
    isSafeIntegerInRange(value.sample_rate, 1, 1_000_000) &&
    isSafeIntegerInRange(value.bit_rate, 1, 10_000_000) &&
    (value.output_volume === undefined || isFiniteNumberInRange(value.output_volume, 0, 10))
  )
}

function isApiConfig(value: unknown): boolean {
  if (!isPlainRecord(value)) return false
  return (
    isEnumValue(value.provider, API_PROVIDERS) &&
    isBoundedString(value.base_url) &&
    isBoundedString(value.api_key) &&
    isBoundedString(value.model) &&
    isUniqueStringList(value.capabilities, { maximum: 100 }) &&
    isOptionalString(value.tts_provider) &&
    isOptionalString(value.tts_model) &&
    isTtsConfig(value.tts_config)
  )
}

export function isWorkflowGenerateRequest(value: unknown): value is GenerateRequest {
  if (!isPlainRecord(value)) return false
  return (
    isBoundedString(value.title) &&
    isEnumValue(value.source_mode, SOURCE_MODES) &&
    isBoundedString(value.source_url) &&
    isEnumValue(value.url_import_mode, URL_IMPORT_MODES) &&
    typeof value.url_auto_subtitle_fallback === 'boolean' &&
    isOptionalBoolean(value.allow_private_network_url) &&
    isOptionalBoolean(value.allow_ytdlp_remote_components) &&
    isOptionalBoolean(value.local_path_access_confirmed) &&
    typeof value.skip_video_slicing === 'boolean' &&
    typeof value.batch_enabled === 'boolean' &&
    isBatchSourceItemList(value.batch_items) &&
    isBoundedString(value.video_path) &&
    isBoundedString(value.subtitle_path) &&
    isBoundedString(value.document_path) &&
    isEnumValue(value.language, LANGUAGES) &&
    isEnumValue(value.level_mode, LEVEL_MODES) &&
    isEnumValue(value.level, LEVELS) &&
    isUniqueStringList(value.collection_levels, { maximum: LEVELS.length, allowed: LEVELS }) &&
    isEnumValue(value.template_id, TEMPLATE_IDS) &&
    isEnumValue(value.card_style, CARD_STYLE_IDS) &&
    isEnumValue(value.review_density, REVIEW_DENSITIES) &&
    isContentToggles(value.content_toggles) &&
    isUniqueStringList(value.language_focus, {
      maximum: LANGUAGE_FOCUS_VALUES.length,
      allowed: LANGUAGE_FOCUS_VALUES,
    }) &&
    isUniqueStringList(value.document_focus, {
      maximum: DOCUMENT_FOCUS_VALUES.length,
      allowed: DOCUMENT_FOCUS_VALUES,
    }) &&
    isEnumValue(value.document_study_mode, DOCUMENT_STUDY_MODES) &&
    isEnumValue(value.document_answer_language, DOCUMENT_ANSWER_LANGUAGES) &&
    isEnumValue(value.document_depth, DOCUMENT_DEPTHS) &&
    isEnumValue(value.document_answer_length, DOCUMENT_ANSWER_LENGTHS) &&
    isEnumValue(value.study_depth, STUDY_DEPTHS) &&
    isEnumValue(value.selection_strategy, SELECTION_STRATEGIES) &&
    typeof value.reuse_ai_review_cache === 'boolean' &&
    isUniqueStringList(value.card_types, { maximum: CARD_KINDS.length, allowed: CARD_KINDS }) &&
    isSafeIntegerInRange(value.max_segments, 0, 1_000_000) &&
    isApiConfig(value.api_config)
  )
}

function isWorkflowPath(value: unknown, requiredExtension?: string): value is string {
  if (!isNonEmptyString(value, MAX_TEXT_LENGTH)) return false
  const normalized = value.trim()
  const absolute = /^[A-Za-z]:[\\/]/u.test(normalized) || /^\\\\/u.test(normalized) || normalized.startsWith('/')
  return absolute && (!requiredExtension || normalized.toLowerCase().endsWith(requiredExtension))
}

function comparableWorkflowPath(value: string): string {
  return value
    .trim()
    .replace(/[/\\]+/gu, '/')
    .replace(/\/+$/gu, '')
    .toLowerCase()
}

export function isWorkflowArtifactReference(value: unknown): value is string {
  if (!isNonEmptyString(value, 160) || !ARTIFACT_REFERENCE_PATTERN.test(value)) return false
  const stem = value.slice(0, -'.json'.length)
  const firstStem = stem.split('.')[0] ?? ''
  return !stem.startsWith('.') && !RESERVED_WINDOWS_STEM_PATTERN.test(firstStem)
}

function isGenerationQueueCheckpoint(value: unknown): value is GenerationQueueCheckpoint {
  if (!isPlainRecord(value)) return false
  if (
    !isUniqueStringList(value.selectedIds, { allowEmpty: false }) ||
    !isUniqueStringList(value.completedIds) ||
    !isUniqueStringList(value.activeBatchIds)
  ) {
    return false
  }
  const selected = new Set(value.selectedIds)
  return value.completedIds.every((id) => selected.has(id)) && value.activeBatchIds.every((id) => selected.has(id))
}

function isNullablePercent(value: unknown): boolean {
  return value === null || isFiniteNumberInRange(value, 0, 100)
}

function isOptionalCount(value: unknown): boolean {
  return value === undefined || isSafeIntegerInRange(value)
}

function isTaskSnapshot(value: unknown): value is TaskSnapshot {
  if (!isPlainRecord(value) || !isPlainRecord(value.progress)) return false
  const progress = value.progress
  const error = value.error
  return (
    value.schemaVersion === 1 &&
    isNonEmptyString(value.id) &&
    isEnumValue(value.command, WORKER_COMMANDS) &&
    isEnumValue(value.state, OPERATION_STATES) &&
    isSafeIntegerInRange(value.startedAt) &&
    isSafeIntegerInRange(value.updatedAt) &&
    value.updatedAt >= value.startedAt &&
    isNonEmptyString(progress.phase) &&
    isNonEmptyString(progress.phaseLabel) &&
    isNullablePercent(progress.phasePercent) &&
    isNullablePercent(progress.overallPercent) &&
    isOptionalCount(progress.completedItems) &&
    isOptionalCount(progress.totalItems) &&
    isOptionalCount(progress.completedBatches) &&
    isOptionalCount(progress.totalBatches) &&
    isBoundedString(progress.message) &&
    isSafeIntegerInRange(progress.lastProgressAt) &&
    typeof value.cancellable === 'boolean' &&
    isNonEmptyString(value.inputFingerprint) &&
    (value.resultRef === undefined || isNonEmptyString(value.resultRef)) &&
    (error === undefined ||
      (isPlainRecord(error) &&
        isNonEmptyString(error.code) &&
        isBoundedString(error.message) &&
        typeof error.retryable === 'boolean' &&
        isOptionalString(error.phase) &&
        isOptionalString(error.detail)))
  )
}

const SHA256_PATTERN = /^[a-f0-9]{64}$/i

function isSafeFileNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
}

function isValidSha256(value: unknown): value is string {
  return typeof value === 'string' && SHA256_PATTERN.test(value)
}

export function isWorkflowFileEvidence(value: unknown, requireSha256 = false): value is WorkflowFileEvidence {
  if (!isPlainRecord(value)) return false
  const evidence = value as Partial<WorkflowFileEvidence>
  if (!isWorkflowPath(evidence.path) || !isSafeFileNumber(evidence.size) || !isSafeFileNumber(evidence.modifiedAtMs)) {
    return false
  }
  if (requireSha256) return isValidSha256(evidence.sha256)
  return evidence.sha256 === undefined || isValidSha256(evidence.sha256)
}

export function isWorkflowSourceEvidenceList(value: unknown): value is WorkflowSourceFileEvidence[] {
  if (!Array.isArray(value) || value.length === 0 || value.length > 1_000) return false
  const ids = new Set<string>()
  return value.every((item) => {
    if (!isWorkflowFileEvidence(item)) return false
    const sourceItem = item as WorkflowSourceFileEvidence
    if (!isNonEmptyString(sourceItem.id)) return false
    if (!['video', 'subtitle', 'document'].includes(String(sourceItem.role))) return false
    if (sourceItem.batchItemId !== undefined && !isNonEmptyString(sourceItem.batchItemId)) {
      return false
    }
    if (ids.has(sourceItem.id)) return false
    ids.add(sourceItem.id)
    return true
  })
}

function evidenceBuildFailure(code: WorkflowFileEvidenceIssueCode, message: string): WorkflowFileEvidenceBuildResult {
  return { ok: false, code, message }
}

export function buildWorkflowFileEvidence(
  path: string,
  inspection: RecoveryFileInspection,
  requireSha256 = false,
): WorkflowFileEvidenceBuildResult {
  if (typeof path !== 'string' || !path.trim()) {
    return evidenceBuildFailure('INVALID_PATH', 'A non-empty file path is required.')
  }

  if (!inspection.ok) {
    if (inspection.error?.code === 'INVALID_PATH' || inspection.error?.code === 'UNSAFE_PATH') {
      return evidenceBuildFailure('INVALID_PATH', inspection.error.message)
    }
    if (inspection.error?.code === 'NOT_REGULAR_FILE' || inspection.error?.code === 'UNSAFE_FILE_TYPE') {
      return evidenceBuildFailure('NOT_REGULAR_FILE', inspection.error.message)
    }
    return evidenceBuildFailure('INSPECTION_FAILED', inspection.error?.message ?? 'The file could not be inspected.')
  }
  if (inspection.error) {
    return evidenceBuildFailure('INSPECTION_FAILED', inspection.error.message)
  }
  if (!inspection.exists) {
    return evidenceBuildFailure('FILE_MISSING', 'The file no longer exists.')
  }
  if (!inspection.isFile) {
    return evidenceBuildFailure('NOT_REGULAR_FILE', 'Recovery evidence must be a regular file.')
  }
  if (!isSafeFileNumber(inspection.size) || !isSafeFileNumber(inspection.modifiedAtMs)) {
    return evidenceBuildFailure('INVALID_METADATA', 'The file size or modification time is invalid.')
  }

  if (requireSha256 && !inspection.sha256) {
    return evidenceBuildFailure('SHA256_MISSING', 'SHA-256 evidence is required for an APKG file.')
  }
  if (inspection.sha256 != null && !isValidSha256(inspection.sha256)) {
    return evidenceBuildFailure('SHA256_INVALID', 'The SHA-256 evidence is invalid.')
  }

  return {
    ok: true,
    evidence: {
      path,
      size: inspection.size,
      modifiedAtMs: inspection.modifiedAtMs,
      ...(inspection.sha256 ? { sha256: inspection.sha256.toLowerCase() } : {}),
    },
  }
}

function comparisonFromBuildFailure(
  result: Exclude<WorkflowFileEvidenceBuildResult, { ok: true }>,
): WorkflowFileEvidenceComparison {
  return { matches: false, code: result.code, message: result.message }
}

export function compareSourceFileEvidence(
  expected: WorkflowFileEvidence,
  inspection: RecoveryFileInspection,
): WorkflowFileEvidenceComparison {
  if (!isWorkflowFileEvidence(expected)) {
    return { matches: false, code: 'INVALID_METADATA', message: 'The saved source evidence is invalid.' }
  }
  const current = buildWorkflowFileEvidence(expected.path, inspection)
  if (!current.ok) return comparisonFromBuildFailure(current)

  if (current.evidence.size !== expected.size || current.evidence.modifiedAtMs !== expected.modifiedAtMs) {
    return {
      matches: false,
      code: 'SOURCE_CHANGED',
      message: 'The source file size or modification time has changed.',
    }
  }
  return { matches: true }
}

export function compareApkgFileEvidence(
  expected: WorkflowFileEvidence,
  inspection: RecoveryFileInspection,
): WorkflowFileEvidenceComparison {
  if (!expected.sha256) {
    return { matches: false, code: 'SHA256_MISSING', message: 'The saved APKG evidence has no SHA-256.' }
  }
  if (!isValidSha256(expected.sha256)) {
    return { matches: false, code: 'SHA256_INVALID', message: 'The saved APKG evidence is invalid.' }
  }
  if (!isWorkflowFileEvidence(expected, true)) {
    return { matches: false, code: 'INVALID_METADATA', message: 'The saved APKG file metadata is invalid.' }
  }
  const current = buildWorkflowFileEvidence(expected.path, inspection, true)
  if (!current.ok) return comparisonFromBuildFailure(current)

  if (current.evidence.sha256 !== expected.sha256.toLowerCase()) {
    return { matches: false, code: 'APKG_CHANGED', message: 'The APKG SHA-256 has changed.' }
  }
  return { matches: true }
}
export function checkpointContainsSecret(value: unknown): boolean {
  if (Array.isArray(value)) return value.some(checkpointContainsSecret)
  if (!value || typeof value !== 'object') return false

  return Object.entries(value as Record<string, unknown>).some(([key, child]) => {
    const normalized = key.toLowerCase()
    const forbidden =
      FORBIDDEN_CHECKPOINT_KEYS.has(normalized) || normalized.endsWith('_token') || normalized.endsWith('_secret')
    const hasValue =
      child !== null &&
      child !== undefined &&
      (typeof child !== 'string' || child.trim().length > 0) &&
      (!Array.isArray(child) || child.length > 0)
    return (forbidden && hasValue) || checkpointContainsSecret(child)
  })
}

export function normalizeWorkflowCheckpoint(
  checkpoint: Omit<WorkflowCheckpointV1, 'schemaVersion' | 'request' | 'requestFingerprint' | 'updatedAt'> & {
    request: GenerateRequest
    updatedAt?: number
  },
): WorkflowCheckpointV1 {
  const request = stripRequestSecrets(checkpoint.request)
  const normalized: WorkflowCheckpointV1 = {
    ...checkpoint,
    schemaVersion: 1,
    request,
    requestFingerprint: fingerprintWorkflowRequest(request),
    updatedAt: checkpoint.updatedAt ?? Date.now(),
  }
  if (normalized.sourceEvidence !== undefined && !isWorkflowSourceEvidenceList(normalized.sourceEvidence)) {
    throw new Error('Invalid source file evidence.')
  }
  if (normalized.apkgEvidence !== undefined && !isWorkflowFileEvidence(normalized.apkgEvidence, true)) {
    throw new Error('Invalid APKG file evidence or missing SHA-256.')
  }
  if (checkpointContainsSecret(normalized)) {
    throw new Error('工作流检查点不能包含密钥或令牌。')
  }
  if (!parseWorkflowCheckpoint(normalized)) {
    throw new Error('Invalid workflow checkpoint schema.')
  }
  return normalized
}

export function parseWorkflowCheckpoint(value: unknown): WorkflowCheckpointV1 | null {
  if (!isPlainRecord(value) || checkpointContainsSecret(value)) return null
  const checkpoint = value
  if (
    checkpoint.schemaVersion !== 1 ||
    !isWorkflowGenerateRequest(checkpoint.request) ||
    !isEnumValue(checkpoint.productStep, PRODUCT_STEPS) ||
    !isEnumValue(checkpoint.artifactStage, ARTIFACT_STAGES) ||
    !isSafeIntegerInRange(checkpoint.updatedAt) ||
    !isNonEmptyString(checkpoint.requestFingerprint)
  ) {
    return null
  }

  const request = checkpoint.request
  const requestFingerprint = checkpoint.requestFingerprint
  if (requestFingerprint !== fingerprintWorkflowRequest(request)) return null

  if (
    checkpoint.sourceFingerprint !== undefined &&
    (!isNonEmptyString(checkpoint.sourceFingerprint) ||
      checkpoint.sourceFingerprint !== fingerprintWorkflowSource(request))
  ) {
    return null
  }

  if (checkpoint.generationQueue !== undefined && !isGenerationQueueCheckpoint(checkpoint.generationQueue)) {
    return null
  }

  const artifactReferences = [
    checkpoint.learningPointResultRef,
    checkpoint.projectRef,
    checkpoint.exportResultRef,
    checkpoint.ankiVerificationRef,
  ]
  if (artifactReferences.some((reference) => reference !== undefined && !isWorkflowArtifactReference(reference))) {
    return null
  }

  if (
    (checkpoint.outputDirectory !== undefined && !isWorkflowPath(checkpoint.outputDirectory)) ||
    (checkpoint.apkgPath !== undefined && !isWorkflowPath(checkpoint.apkgPath, '.apkg')) ||
    (checkpoint.apkgSha256 !== undefined && !isValidSha256(checkpoint.apkgSha256))
  ) {
    return null
  }

  if (checkpoint.sourceEvidence !== undefined) {
    if (!isWorkflowSourceEvidenceList(checkpoint.sourceEvidence)) return null
    const refs = collectWorkflowSourceFileRefs(request)
    if (refs.length !== checkpoint.sourceEvidence.length) return null
    const evidenceById = new Map(checkpoint.sourceEvidence.map((item) => [item.id, item]))
    for (const ref of refs) {
      const evidence = evidenceById.get(ref.id)
      if (
        !evidence ||
        evidence.role !== ref.role ||
        evidence.batchItemId !== ref.batchItemId ||
        comparableWorkflowPath(evidence.path) !== comparableWorkflowPath(ref.path)
      ) {
        return null
      }
    }
  }

  if (checkpoint.apkgEvidence !== undefined) {
    if (
      !isWorkflowFileEvidence(checkpoint.apkgEvidence, true) ||
      !isWorkflowPath(checkpoint.apkgEvidence.path, '.apkg')
    ) {
      return null
    }
    if (
      checkpoint.apkgPath !== undefined &&
      comparableWorkflowPath(checkpoint.apkgPath) !== comparableWorkflowPath(checkpoint.apkgEvidence.path)
    ) {
      return null
    }
    if (
      checkpoint.apkgSha256 !== undefined &&
      checkpoint.apkgSha256.toLowerCase() !== checkpoint.apkgEvidence.sha256?.toLowerCase()
    ) {
      return null
    }
  }

  if (
    checkpoint.task !== undefined &&
    (!isTaskSnapshot(checkpoint.task) || checkpoint.task.inputFingerprint !== requestFingerprint)
  ) {
    return null
  }

  return checkpoint as WorkflowCheckpointV1
}

export async function saveWorkflowCheckpoint(checkpoint: WorkflowCheckpointV1): Promise<void> {
  if (!isTauriRuntime()) return
  if (checkpointContainsSecret(checkpoint)) throw new Error('工作流检查点不能包含密钥或令牌。')
  if (checkpoint.sourceEvidence !== undefined && !isWorkflowSourceEvidenceList(checkpoint.sourceEvidence)) {
    throw new Error('Invalid source file evidence.')
  }
  if (checkpoint.apkgEvidence !== undefined && !isWorkflowFileEvidence(checkpoint.apkgEvidence, true)) {
    throw new Error('Invalid APKG file evidence or missing SHA-256.')
  }
  if (!parseWorkflowCheckpoint(checkpoint)) {
    throw new Error('Invalid workflow checkpoint schema.')
  }
  await invoke('save_workflow_checkpoint', { checkpoint })
}

export type WorkflowCheckpointCandidate = 'primary' | 'backup'

export async function loadWorkflowCheckpointCandidate(
  candidate: WorkflowCheckpointCandidate,
): Promise<WorkflowCheckpointV1 | null> {
  if (!isTauriRuntime()) return null
  const command = candidate === 'backup' ? 'load_workflow_checkpoint_backup' : 'load_workflow_checkpoint'
  const value = await invoke<unknown | null>(command)
  return parseWorkflowCheckpoint(value)
}

export async function loadWorkflowCheckpoint(): Promise<WorkflowCheckpointV1 | null> {
  if (!isTauriRuntime()) return null
  const primary = await invoke<unknown | null>('load_workflow_checkpoint')
  const parsedPrimary = parseWorkflowCheckpoint(primary)
  if (parsedPrimary || primary === null) return parsedPrimary

  return loadWorkflowCheckpointCandidate('backup')
}

export async function clearWorkflowCheckpoint(): Promise<void> {
  if (!isTauriRuntime()) return
  await invoke('clear_workflow_checkpoint')
}

export async function writeWorkflowArtifact<T>(kind: WorkflowArtifactKind, payload: T): Promise<string | null> {
  if (!isTauriRuntime()) return null
  if (checkpointContainsSecret(payload)) throw new Error('工作流恢复产物不能包含密钥或令牌。')
  return invoke<string>('write_workflow_artifact', { kind, payload })
}

export async function readWorkflowArtifact<T>(reference: string): Promise<T> {
  return invoke<T>('read_workflow_artifact', { reference })
}
