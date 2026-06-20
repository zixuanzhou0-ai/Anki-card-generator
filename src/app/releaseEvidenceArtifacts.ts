import type {
  VideoReleaseCaseCacheTimingPlan,
  VideoReleaseCaseId,
  VideoReleaseCaseManifest,
} from '../domain/releaseEvidenceLayout.ts'
import {
  VIDEO_RELEASE_CASES,
  VIDEO_RELEASE_RUN_DIR_PREFIX,
  VIDEO_RELEASE_RUN_STAMP_PATTERN,
  buildVideoReleaseCaseCacheTimingPlan,
} from '../domain/releaseEvidenceLayout.ts'
import type { LearningPointExtractionResult } from '../domain/learningPoints.ts'
import type { AnkiVerifyResult, ExportResult, Project } from '../domain/types.ts'

type TimingStageKey =
  | 'source_prepare_ms'
  | 'learning_point_extract_ms'
  | 'ai_review_ms'
  | 'card_body_ms'
  | 'tts_ms'
  | 'media_slice_ms'
  | 'apkg_pack_ms'
  | 'anki_verify_ms'

type TimingBottleneckStage =
  | 'source_prepare'
  | 'learning_point_extract'
  | 'ai_review'
  | 'card_body'
  | 'tts'
  | 'media_slice'
  | 'apkg_pack'
  | 'anki_verify'

type CacheGroupArtifact = {
  hits: number
  misses: number
  total: number
}

type CacheGroupWithFlagsArtifact = CacheGroupArtifact & {
  read_enabled: boolean
  write_enabled: boolean
}

export type ReleaseTimingArtifact = {
  schema_version: 1
  case_id: VideoReleaseCaseId
  source_fingerprint: string
  apkg_relative_path: string
  apkg_sha256: string
  apkg_size_bytes: number
  apkg_mtime_ms: number
  declared_cache_state: VideoReleaseCaseCacheTimingPlan['declared_cache_state']
  observed_cache_state: VideoReleaseCaseCacheTimingPlan['declared_cache_state']
  source_prepare_ms: number
  learning_point_extract_ms: number
  ai_review_ms: number
  card_body_ms: number
  tts_ms: number
  media_slice_ms: number
  apkg_pack_ms: number
  anki_verify_ms: number
  total_ms: number
  timing_card_count: number
  per_card_ms: number
  stage_per_card_ms: {
    card_body: number
    tts: number
    media_slice: number
    apkg_pack: number
    anki_verify: number
    total: number
  }
  bottleneck_stage: TimingBottleneckStage
  bottleneck_ms: number
}

export type ReleaseCacheSummaryArtifact = {
  schema_version: 1
  case_id: VideoReleaseCaseId
  source_fingerprint: string
  apkg_relative_path: string
  apkg_sha256: string
  apkg_size_bytes: number
  apkg_mtime_ms: number
  declared_cache_state: VideoReleaseCaseCacheTimingPlan['declared_cache_state']
  observed_cache_state: VideoReleaseCaseCacheTimingPlan['declared_cache_state']
  source_cache_probe_status: string
  existing_url_cache_dirs: string[]
  cold_cache_reads_disabled: boolean | null
  cold_claim_scope: VideoReleaseCaseCacheTimingPlan['cold_claim_scope']
  ai_review_cache: CacheGroupWithFlagsArtifact
  card_generation_cache: CacheGroupWithFlagsArtifact
  tts_cache: CacheGroupArtifact
  media_cache: CacheGroupArtifact
}

export type ReleaseDeckMetadataArtifact = {
  schema_version: 1
  case_id: VideoReleaseCaseId
  source_kind: VideoReleaseCaseManifest['source_kind']
  mode: VideoReleaseCaseManifest['mode']
  cache_state: VideoReleaseCaseManifest['cache_state']
  source_fingerprint: string
  apkg_relative_path: string
  apkg_sha256: string
  apkg_size_bytes: number
  apkg_mtime_ms: number
  deck_name: string
  deck_kind: string
  model_name: string
  template_name: string
  template_version: string
  anki_tag: string
  card_count: number
  exported_count: number
}

type ReleaseArtifactIdentityInput = {
  caseId: VideoReleaseCaseId
  manifest: VideoReleaseCaseManifest
  exportResult: Pick<
    ExportResult,
    'apkg_path' | 'apkg_relative_path' | 'apkg_sha256' | 'apkg_size_bytes' | 'apkg_mtime_ms'
  > | null
}

export type BuildReleaseTimingCacheArtifactsInput = {
  caseId: VideoReleaseCaseId
  manifest: VideoReleaseCaseManifest
  learningPointResult: Pick<LearningPointExtractionResult, 'quality_funnel' | 'timing_ms'> | null
  project: Pick<Project, 'quality_funnel'> | null
  exportResult: Pick<
    ExportResult,
    | 'apkg_path'
    | 'apkg_relative_path'
    | 'apkg_sha256'
    | 'apkg_size_bytes'
    | 'apkg_mtime_ms'
    | 'cards'
    | 'media_summary'
    | 'timing_ms'
  > | null
  ankiVerifyResult: Pick<AnkiVerifyResult, 'card_count' | 'timing_ms'> | null
  coldCacheReadsDisabled?: boolean
  sourceCacheProbeStatus?: string | null
  existingUrlCacheDirs?: string[]
}

export type BuildReleaseDeckMetadataArtifactInput = ReleaseArtifactIdentityInput & {
  exportResult: Pick<
    ExportResult,
    | 'apkg_path'
    | 'apkg_relative_path'
    | 'apkg_sha256'
    | 'apkg_size_bytes'
    | 'apkg_mtime_ms'
    | 'cards'
    | 'deck_name'
    | 'deck_kind'
    | 'model_name'
    | 'template_name'
    | 'template_version'
    | 'anki_tag'
  > | null
  ankiVerifyResult?: Pick<AnkiVerifyResult, 'deck_name' | 'card_count' | 'model_names'> | null
}

export type ReleaseTimingCacheArtifacts = {
  ok: boolean
  failedChecks: string[]
  warnings: string[]
  artifactPaths: VideoReleaseCaseCacheTimingPlan['artifact_paths']
  timing: ReleaseTimingArtifact | null
  cacheSummary: ReleaseCacheSummaryArtifact | null
}

export type ReleaseTimingCacheArtifactWrite = {
  kind: 'timing' | 'cache_summary'
  relativePath: string
  absolutePath: string
  content: string
  writeMode: 'exclusive_create'
}

export type BuildReleaseTimingCacheArtifactWritePlanInput = BuildReleaseTimingCacheArtifactsInput & {
  runDir: string
}

export type ReleaseTimingCacheArtifactWritePlan = {
  ok: boolean
  status: 'ready_to_write' | 'blocked'
  matrixPassCreated: false
  failedChecks: string[]
  warnings: string[]
  runDir: string
  caseDir: string
  artifactPaths: VideoReleaseCaseCacheTimingPlan['artifact_paths']
  writes: ReleaseTimingCacheArtifactWrite[]
  notes: string
}

export type ReleaseDeckMetadataArtifactResult = {
  ok: boolean
  status: 'ready_for_write_plan' | 'blocked'
  matrixPassCreated: false
  failedChecks: string[]
  warnings: string[]
  artifactPath: string
  deckMetadata: ReleaseDeckMetadataArtifact | null
  notes: string
}

export type ReleaseDeckMetadataArtifactWrite = {
  kind: 'deck_metadata'
  relativePath: string
  absolutePath: string
  content: string
  writeMode: 'exclusive_create'
}

export type BuildReleaseDeckMetadataArtifactWritePlanInput = BuildReleaseDeckMetadataArtifactInput & {
  runDir: string
}

export type ReleaseDeckMetadataArtifactWritePlan = {
  ok: boolean
  status: 'ready_to_write' | 'blocked'
  matrixPassCreated: false
  failedChecks: string[]
  warnings: string[]
  runDir: string
  caseDir: string
  artifactPath: string
  writes: ReleaseDeckMetadataArtifactWrite[]
  notes: string
}

const TIMING_STAGE_FIELDS: Array<{ key: TimingStageKey; bottleneck: TimingBottleneckStage }> = [
  { key: 'source_prepare_ms', bottleneck: 'source_prepare' },
  { key: 'learning_point_extract_ms', bottleneck: 'learning_point_extract' },
  { key: 'ai_review_ms', bottleneck: 'ai_review' },
  { key: 'card_body_ms', bottleneck: 'card_body' },
  { key: 'tts_ms', bottleneck: 'tts' },
  { key: 'media_slice_ms', bottleneck: 'media_slice' },
  { key: 'apkg_pack_ms', bottleneck: 'apkg_pack' },
  { key: 'anki_verify_ms', bottleneck: 'anki_verify' },
]

function objectRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {}
}

function finiteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? Math.round(value) : null
}

function positiveNumber(value: unknown): number | null {
  const numeric = finiteNumber(value)
  return numeric !== null && numeric > 0 ? numeric : null
}

function nonnegativeNumber(value: unknown): number | null {
  const numeric = finiteNumber(value)
  return numeric !== null && numeric >= 0 ? numeric : null
}

function booleanValue(value: unknown): boolean | null {
  return typeof value === 'boolean' ? value : null
}

function firstNumber(...values: unknown[]): number | null {
  for (const value of values) {
    const numeric = finiteNumber(value)
    if (numeric !== null) {
      return numeric
    }
  }
  return null
}

function firstPositiveNumber(...values: unknown[]): number | null {
  for (const value of values) {
    const numeric = positiveNumber(value)
    if (numeric !== null) {
      return numeric
    }
  }
  return null
}

function firstBoolean(...values: unknown[]): boolean | null {
  for (const value of values) {
    const boolean = booleanValue(value)
    if (boolean !== null) {
      return boolean
    }
  }
  return null
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function isSha256Hex(value: string): boolean {
  return /^[a-f0-9]{64}$/i.test(value)
}

function positiveFiniteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? Math.round(value) : null
}

function normalizeRelativePath(value: string): string {
  return value.replace(/\\/g, '/').replace(/^\/+/, '').replace(/\/+/g, '/')
}

function apkgRelativePathForCase(input: ReleaseArtifactIdentityInput): string {
  const explicit = stringValue(input.exportResult?.apkg_relative_path)
  if (explicit) {
    return normalizeRelativePath(explicit)
  }
  const apkgPath = stringValue(input.exportResult?.apkg_path)
  if (!apkgPath) {
    return ''
  }
  const normalized = normalizeRelativePath(apkgPath)
  const marker = `cases/${input.caseId}/apkg/`
  const markerIndex = normalized.toLowerCase().indexOf(marker.toLowerCase())
  return markerIndex >= 0 ? normalized.slice(markerIndex) : normalized
}

function expectedApkgRelativePathForCase(caseId: VideoReleaseCaseId): string {
  return `cases/${caseId}/apkg/${caseId}.apkg`
}

function buildArtifactIdentity(input: ReleaseArtifactIdentityInput, failedChecks: string[]) {
  const sourceFingerprint = stringValue(input.manifest.source_candidate?.source_fingerprint)
  const apkgRelativePath = apkgRelativePathForCase(input)
  const expectedApkgRelativePath = expectedApkgRelativePathForCase(input.caseId)
  const apkgSha256 = stringValue(input.exportResult?.apkg_sha256).toLowerCase()
  const apkgSizeBytes = positiveFiniteNumber(input.exportResult?.apkg_size_bytes)
  const apkgMtimeMs = positiveFiniteNumber(input.exportResult?.apkg_mtime_ms)
  if (!sourceFingerprint) {
    failedChecks.push('release_identity_source_fingerprint_missing')
  }
  if (!apkgRelativePath || !apkgRelativePath.toLowerCase().startsWith(`cases/${input.caseId}/apkg/`)) {
    failedChecks.push('release_identity_apkg_relative_path_missing')
  } else if (apkgRelativePath.toLowerCase() !== expectedApkgRelativePath.toLowerCase()) {
    failedChecks.push('release_identity_apkg_relative_path_not_canonical')
  }
  if (!isSha256Hex(apkgSha256)) {
    failedChecks.push('release_identity_apkg_sha256_missing')
  }
  if (apkgSizeBytes === null) {
    failedChecks.push('release_identity_apkg_size_bytes_missing')
  }
  if (apkgMtimeMs === null) {
    failedChecks.push('release_identity_apkg_mtime_ms_missing')
  }
  return {
    sourceFingerprint,
    apkgRelativePath,
    apkgSha256,
    apkgSizeBytes,
    apkgMtimeMs,
  }
}

function releaseCaseExpectedCardCount(caseId: VideoReleaseCaseId): number | null {
  const releaseCase = VIDEO_RELEASE_CASES.find((item) => item.id === caseId)
  if (!releaseCase) {
    return null
  }
  return 'minimumGeneratedCards' in releaseCase ? releaseCase.minimumGeneratedCards : releaseCase.targetCardCount
}

function releaseCaseCardCountMatches(caseId: VideoReleaseCaseId, value: number): boolean {
  const releaseCase = VIDEO_RELEASE_CASES.find((item) => item.id === caseId)
  if (!releaseCase) {
    return false
  }
  return 'minimumGeneratedCards' in releaseCase ? value >= releaseCase.minimumGeneratedCards : value === releaseCase.targetCardCount
}

function templateLabelForMode(mode: VideoReleaseCaseManifest['mode']): string {
  return mode === 'quick' ? '沉浸复读 V11 · 快速复读' : '沉浸复读 V11'
}

function buildDeckModelName(input: BuildReleaseDeckMetadataArtifactInput): {
  modelName: string
  templateName: string
  templateVersion: string
  ankiTag: string
} {
  const explicitModel = stringValue(input.exportResult?.model_name)
  const explicitTemplate = stringValue(input.exportResult?.template_name)
  const templateVersion = stringValue(input.exportResult?.template_version)
  const templateName = explicitTemplate || templateLabelForMode(input.manifest.mode)
  const modelName = explicitModel || (templateVersion ? `Anki Card Generator ${templateVersion} - ${templateName}` : '')
  const ankiTag = stringValue(input.exportResult?.anki_tag) || (templateVersion ? `anki_card_generator_${templateVersion.toLowerCase()}` : '')
  return {
    modelName,
    templateName,
    templateVersion,
    ankiTag,
  }
}

function verifiedModelNames(input: BuildReleaseDeckMetadataArtifactInput): string[] {
  return Array.isArray(input.ankiVerifyResult?.model_names)
    ? input.ankiVerifyResult.model_names.filter((value): value is string => typeof value === 'string')
    : []
}

function deckMetadataArtifactPath(caseId: VideoReleaseCaseId): string {
  return `cases/${caseId}/deck_metadata.json`
}

function requirePositiveStage(failedChecks: string[], key: TimingStageKey, ...values: unknown[]): number | null {
  for (const value of values) {
    const numeric = positiveNumber(value)
    if (numeric !== null) {
      return numeric
    }
  }
  failedChecks.push(`timing_${key}_missing`)
  return null
}

function requireNonnegativeStage(failedChecks: string[], key: TimingStageKey, ...values: unknown[]): number | null {
  for (const value of values) {
    const numeric = nonnegativeNumber(value)
    if (numeric !== null) {
      return numeric
    }
  }
  failedChecks.push(`timing_${key}_missing`)
  return null
}

function requireNonnegativeCount(failedChecks: string[], check: string, value: unknown): number | null {
  const numeric = nonnegativeNumber(value)
  if (numeric === null) {
    failedChecks.push(check)
    return null
  }
  return numeric
}

function timingRecordFrom(value: unknown): Record<string, unknown> {
  return objectRecord(value)
}

function cacheGroupFromCounts(
  failedChecks: string[],
  prefix: string,
  hitsValue: unknown,
  missesValue: unknown,
  options: { totalValue?: unknown; deriveTotal?: boolean } = {},
): CacheGroupArtifact | null {
  const hits = requireNonnegativeCount(failedChecks, `${prefix}_hits_missing`, hitsValue)
  const misses = requireNonnegativeCount(failedChecks, `${prefix}_misses_missing`, missesValue)
  const total = options.deriveTotal
    ? hits !== null && misses !== null
      ? hits + misses
      : null
    : requireNonnegativeCount(failedChecks, `${prefix}_total_missing`, options.totalValue)
  if (hits === null || misses === null || total === null) {
    return null
  }
  if (hits + misses !== total) {
    failedChecks.push(`${prefix}_total_mismatch`)
    return null
  }
  return { hits, misses, total }
}

function cacheGroupWithFlags(
  failedChecks: string[],
  prefix: string,
  readEnabled: boolean | null,
  writeEnabled: boolean | null,
  counts: CacheGroupArtifact | null,
): CacheGroupWithFlagsArtifact | null {
  if (readEnabled === null) {
    failedChecks.push(`${prefix}_read_flag_missing`)
  }
  if (writeEnabled === null) {
    failedChecks.push(`${prefix}_write_flag_missing`)
  }
  if (readEnabled === null || writeEnabled === null || !counts) {
    return null
  }
  return {
    ...counts,
    read_enabled: readEnabled,
    write_enabled: writeEnabled,
  }
}

function cacheGroupFullyHit(counts: CacheGroupArtifact | null): boolean {
  return Boolean(counts && counts.total > 0 && counts.misses === 0 && counts.hits === counts.total)
}

function buildTimingArtifact(
  input: BuildReleaseTimingCacheArtifactsInput,
  plan: VideoReleaseCaseCacheTimingPlan,
  failedChecks: string[],
  identity: ReturnType<typeof buildArtifactIdentity>,
): ReleaseTimingArtifact | null {
  const extractionFunnel = objectRecord(input.learningPointResult?.quality_funnel)
  const projectFunnel = objectRecord(input.project?.quality_funnel)
  const extractionTiming = timingRecordFrom(
    input.learningPointResult?.timing_ms ?? extractionFunnel.learning_point_timing_ms,
  )
  const generationTiming = timingRecordFrom(projectFunnel.generation_timing_ms)
  const exportTiming = timingRecordFrom(input.exportResult?.timing_ms)
  const verifyTiming = timingRecordFrom(input.ankiVerifyResult?.timing_ms)
  const timingCardCount = positiveNumber(input.ankiVerifyResult?.card_count)

  if (timingCardCount === null) {
    failedChecks.push('timing_card_count_missing')
  } else if (timingCardCount !== plan.target_card_count) {
    failedChecks.push('timing_card_count_mismatch')
  }

  const stages = {
    source_prepare_ms: requirePositiveStage(
      failedChecks,
      'source_prepare_ms',
      extractionTiming.source_prepare_ms,
      generationTiming.source_prepare_ms,
    ),
    learning_point_extract_ms: requirePositiveStage(
      failedChecks,
      'learning_point_extract_ms',
      extractionTiming.learning_point_extract_ms,
    ),
    ai_review_ms: requirePositiveStage(failedChecks, 'ai_review_ms', extractionTiming.ai_review_ms),
    card_body_ms: requireNonnegativeStage(failedChecks, 'card_body_ms', generationTiming.card_body_ms),
    tts_ms: requirePositiveStage(failedChecks, 'tts_ms', exportTiming.tts_ms),
    media_slice_ms: requirePositiveStage(failedChecks, 'media_slice_ms', exportTiming.media_slice_ms),
    apkg_pack_ms: requirePositiveStage(failedChecks, 'apkg_pack_ms', exportTiming.apkg_pack_ms),
    anki_verify_ms: requirePositiveStage(failedChecks, 'anki_verify_ms', verifyTiming.anki_verify_ms),
  }

  if (
    Object.values(stages).some((value) => value === null) ||
    timingCardCount === null ||
    timingCardCount !== plan.target_card_count ||
    !identity.sourceFingerprint ||
    !identity.apkgRelativePath ||
    !isSha256Hex(identity.apkgSha256) ||
    identity.apkgSizeBytes === null ||
    identity.apkgMtimeMs === null
  ) {
    return null
  }

  const resolvedStages = stages as Record<TimingStageKey, number>
  const totalMs = TIMING_STAGE_FIELDS.reduce((sum, stage) => sum + resolvedStages[stage.key], 0)
  const perCardMs = Math.round(totalMs / timingCardCount)
  const bottleneck = TIMING_STAGE_FIELDS.reduce(
    (current, stage) => {
      const ms = resolvedStages[stage.key]
      return ms > current.ms ? { stage: stage.bottleneck, ms } : current
    },
    { stage: 'source_prepare' as TimingBottleneckStage, ms: resolvedStages.source_prepare_ms },
  )

  return {
    schema_version: 1,
    case_id: input.caseId,
    source_fingerprint: identity.sourceFingerprint,
    apkg_relative_path: identity.apkgRelativePath,
    apkg_sha256: identity.apkgSha256,
    apkg_size_bytes: identity.apkgSizeBytes,
    apkg_mtime_ms: identity.apkgMtimeMs,
    declared_cache_state: plan.declared_cache_state,
    observed_cache_state: plan.declared_cache_state,
    ...resolvedStages,
    total_ms: totalMs,
    timing_card_count: timingCardCount,
    per_card_ms: perCardMs,
    stage_per_card_ms: {
      card_body: Math.round(resolvedStages.card_body_ms / timingCardCount),
      tts: Math.round(resolvedStages.tts_ms / timingCardCount),
      media_slice: Math.round(resolvedStages.media_slice_ms / timingCardCount),
      apkg_pack: Math.round(resolvedStages.apkg_pack_ms / timingCardCount),
      anki_verify: Math.round(resolvedStages.anki_verify_ms / timingCardCount),
      total: perCardMs,
    },
    bottleneck_stage: bottleneck.stage,
    bottleneck_ms: bottleneck.ms,
  }
}

function buildCacheSummaryArtifact(
  input: BuildReleaseTimingCacheArtifactsInput,
  plan: VideoReleaseCaseCacheTimingPlan,
  failedChecks: string[],
  identity: ReturnType<typeof buildArtifactIdentity>,
): ReleaseCacheSummaryArtifact | null {
  const extractionFunnel = objectRecord(input.learningPointResult?.quality_funnel)
  const projectFunnel = objectRecord(input.project?.quality_funnel)
  const mediaSummary = objectRecord(input.exportResult?.media_summary)
  const sourceCacheProbeStatus = String(plan.source_cache_probe_status ?? '').trim()
  if (!sourceCacheProbeStatus) {
    failedChecks.push('cache_summary_source_cache_probe_status_missing')
  }

  const aiCounts = cacheGroupFromCounts(
    failedChecks,
    'ai_review_cache',
    firstNumber(extractionFunnel.ai_review_cache_hits, projectFunnel.ai_review_cache_hits),
    firstNumber(extractionFunnel.ai_review_cache_misses, projectFunnel.ai_review_cache_misses),
    { deriveTotal: true },
  )
  const cardCounts = cacheGroupFromCounts(
    failedChecks,
    'card_generation_cache',
    projectFunnel.card_generation_cache_hits,
    projectFunnel.card_generation_cache_misses,
    { deriveTotal: true },
  )
  const ttsCounts = cacheGroupFromCounts(
    failedChecks,
    'tts_cache',
    mediaSummary.tts_cache_hits,
    mediaSummary.tts_cache_misses,
    { totalValue: mediaSummary.tts_cache_total },
  )
  const mediaCounts = cacheGroupFromCounts(
    failedChecks,
    'media_cache',
    mediaSummary.media_cache_hits,
    mediaSummary.media_cache_misses,
    { totalValue: mediaSummary.media_cache_total },
  )
  const aiCache = cacheGroupWithFlags(
    failedChecks,
    'ai_review_cache',
    firstBoolean(extractionFunnel.ai_review_cache_read_enabled, projectFunnel.ai_review_cache_read_enabled),
    firstBoolean(extractionFunnel.ai_review_cache_write_enabled, projectFunnel.ai_review_cache_write_enabled),
    aiCounts,
  )
  const cardCache = cacheGroupWithFlags(
    failedChecks,
    'card_generation_cache',
    firstBoolean(projectFunnel.card_generation_cache_read_enabled),
    firstBoolean(projectFunnel.card_generation_cache_write_enabled),
    cardCounts,
  )

  if (plan.declared_cache_state === 'cold') {
    if (plan.cold_cache_reads_disabled !== true) {
      failedChecks.push('cache_summary_cold_reads_not_disabled')
    }
    if (aiCache && aiCache.read_enabled !== false) {
      failedChecks.push('cache_summary_cold_ai_review_read_enabled')
    }
    if (cardCache && cardCache.read_enabled !== false) {
      failedChecks.push('cache_summary_cold_card_generation_read_enabled')
    }
    if ((aiCounts && aiCounts.hits !== 0) || (cardCounts && cardCounts.hits !== 0)) {
      failedChecks.push('cache_summary_cold_ai_card_hits_nonzero')
    }
    if (cardCounts && cardCounts.misses < plan.target_card_count) {
      failedChecks.push('cache_summary_cold_card_generation_misses_below_expected')
    }
    if ((ttsCounts && ttsCounts.hits !== 0) || (mediaCounts && mediaCounts.hits !== 0)) {
      failedChecks.push('cache_summary_cold_tts_media_hits_nonzero')
    }
  }

  if (plan.declared_cache_state === 'hot') {
    if (aiCache && aiCache.read_enabled !== true) {
      failedChecks.push('cache_summary_hot_ai_review_read_not_enabled')
    }
    if (cardCache && cardCache.read_enabled !== true) {
      failedChecks.push('cache_summary_hot_card_generation_read_not_enabled')
    }
    if (cardCounts && cardCounts.hits < plan.target_card_count) {
      failedChecks.push('cache_summary_hot_card_generation_hits_below_expected')
    }
    if (cardCounts && cardCounts.misses !== 0) {
      failedChecks.push('cache_summary_hot_card_generation_misses_nonzero')
    }
    if (ttsCounts && !cacheGroupFullyHit(ttsCounts)) {
      failedChecks.push('cache_summary_hot_tts_hits_below_expected')
    }
    if (mediaCounts && mediaCounts.hits < plan.target_card_count) {
      failedChecks.push('cache_summary_hot_media_hits_below_expected')
    }
  }

  if (
    !sourceCacheProbeStatus ||
    !aiCache ||
    !cardCache ||
    !ttsCounts ||
    !mediaCounts ||
    !identity.sourceFingerprint ||
    !identity.apkgRelativePath ||
    !isSha256Hex(identity.apkgSha256) ||
    identity.apkgSizeBytes === null ||
    identity.apkgMtimeMs === null
  ) {
    return null
  }

  return {
    schema_version: 1,
    case_id: input.caseId,
    source_fingerprint: identity.sourceFingerprint,
    apkg_relative_path: identity.apkgRelativePath,
    apkg_sha256: identity.apkgSha256,
    apkg_size_bytes: identity.apkgSizeBytes,
    apkg_mtime_ms: identity.apkgMtimeMs,
    declared_cache_state: plan.declared_cache_state,
    observed_cache_state: plan.declared_cache_state,
    source_cache_probe_status: sourceCacheProbeStatus,
    existing_url_cache_dirs: [...plan.existing_url_cache_dirs],
    cold_cache_reads_disabled: plan.cold_cache_reads_disabled,
    cold_claim_scope: plan.cold_claim_scope,
    ai_review_cache: aiCache,
    card_generation_cache: cardCache,
    tts_cache: ttsCounts,
    media_cache: mediaCounts,
  }
}

function pathSegments(value: string): string[] {
  return value.split(/[\\/]+/).filter(Boolean)
}

function pathHasTraversal(value: string): boolean {
  return pathSegments(value).some((segment) => segment === '..')
}

function pathLooksAbsolute(value: string): boolean {
  return /^[A-Za-z]:[\\/]/.test(value) || value.startsWith('\\\\') || value.startsWith('/')
}

function runDirNameFromPath(value: string): string {
  return pathSegments(value).at(-1) ?? ''
}

function isReleaseRunDirName(value: string): boolean {
  if (!value.startsWith(VIDEO_RELEASE_RUN_DIR_PREFIX)) {
    return false
  }
  return VIDEO_RELEASE_RUN_STAMP_PATTERN.test(value.slice(VIDEO_RELEASE_RUN_DIR_PREFIX.length))
}

function joinRunRelativePath(runDir: string, relativePath: string): string {
  const separator = runDir.includes('\\') ? '\\' : '/'
  const cleanRunDir = runDir.replace(/[\\/]+$/, '')
  return [cleanRunDir, ...normalizeRelativePath(relativePath).split('/')].join(separator)
}

function comparePath(value: string): string {
  return value.replace(/\\/g, '/').replace(/\/+/g, '/').replace(/\/$/, '').toLowerCase()
}

function pathIsInsideDirectory(pathValue: string, directory: string): boolean {
  return comparePath(pathValue).startsWith(`${comparePath(directory)}/`)
}

function validateRunDir(runDir: string, failedChecks: string[]) {
  if (!runDir) {
    failedChecks.push('run_dir_missing')
    return
  }
  if (!pathLooksAbsolute(runDir)) {
    failedChecks.push('run_dir_not_absolute')
  }
  if (pathHasTraversal(runDir)) {
    failedChecks.push('run_dir_path_unsafe')
  }
  if (!isReleaseRunDirName(runDirNameFromPath(runDir))) {
    failedChecks.push('run_dir_not_release_hardening_dir')
  }
}

function validateArtifactRelativePath({
  kind,
  relativePath,
  caseId,
  expectedFile,
  failedChecks,
}: {
  kind: ReleaseTimingCacheArtifactWrite['kind']
  relativePath: string
  caseId: VideoReleaseCaseId
  expectedFile: string
  failedChecks: string[]
}) {
  const normalized = normalizeRelativePath(relativePath)
  if (pathLooksAbsolute(relativePath) || pathHasTraversal(relativePath)) {
    failedChecks.push(`${kind}_artifact_path_unsafe`)
  }
  if (normalized !== `cases/${caseId}/${expectedFile}`) {
    failedChecks.push(`${kind}_artifact_path_mismatch`)
  }
}

function jsonContent(value: unknown): string {
  return `${JSON.stringify(value, null, 2)}\n`
}

export function buildReleaseTimingCacheArtifacts(
  input: BuildReleaseTimingCacheArtifactsInput,
): ReleaseTimingCacheArtifacts {
  const plan = buildVideoReleaseCaseCacheTimingPlan({
    caseId: input.caseId,
    manifest: input.manifest,
    coldCacheReadsDisabled: input.coldCacheReadsDisabled,
    sourceCacheProbeStatus: input.sourceCacheProbeStatus,
    existingUrlCacheDirs: input.existingUrlCacheDirs,
  })
  const failedChecks: string[] = []
  const identity = buildArtifactIdentity(input, failedChecks)
  const timing = buildTimingArtifact(input, plan, failedChecks, identity)
  const cacheSummary = buildCacheSummaryArtifact(input, plan, failedChecks, identity)
  const uniqueFailedChecks = [...new Set(failedChecks)]

  return {
    ok: uniqueFailedChecks.length === 0,
    failedChecks: uniqueFailedChecks,
    warnings: [],
    artifactPaths: plan.artifact_paths,
    timing: uniqueFailedChecks.length === 0 ? timing : null,
    cacheSummary: uniqueFailedChecks.length === 0 ? cacheSummary : null,
  }
}

export function buildReleaseDeckMetadataArtifact(
  input: BuildReleaseDeckMetadataArtifactInput,
): ReleaseDeckMetadataArtifactResult {
  const failedChecks: string[] = []
  const releaseCase = VIDEO_RELEASE_CASES.find((item) => item.id === input.caseId)
  if (!releaseCase) {
    failedChecks.push('release_case_unknown')
  }
  if (input.manifest.case_id !== input.caseId) {
    failedChecks.push('deck_metadata_manifest_case_id_mismatch')
  }
  if (releaseCase && input.manifest.target_card_count !== releaseCase.targetCardCount) {
    failedChecks.push('deck_metadata_manifest_target_card_count_mismatch')
  }

  const identity = buildArtifactIdentity(input, failedChecks)
  const deckName = stringValue(input.exportResult?.deck_name)
  const deckKind = stringValue(input.exportResult?.deck_kind)
  const exportedCount = positiveFiniteNumber(input.exportResult?.cards)
  const verifiedCardCount = positiveFiniteNumber(input.ankiVerifyResult?.card_count)
  const expectedCardCount = releaseCaseExpectedCardCount(input.caseId)
  const { modelName, templateName, templateVersion, ankiTag } = buildDeckModelName(input)

  if (!deckName) {
    failedChecks.push('deck_metadata_deck_name_missing')
  }
  if (!deckKind) {
    failedChecks.push('deck_metadata_deck_kind_missing')
  }
  if (!modelName) {
    failedChecks.push('deck_metadata_model_name_missing')
  }
  if (!templateName) {
    failedChecks.push('deck_metadata_template_name_missing')
  }
  if (!templateVersion) {
    failedChecks.push('deck_metadata_template_version_missing')
  }
  if (!ankiTag) {
    failedChecks.push('deck_metadata_anki_tag_missing')
  }
  if (exportedCount === null) {
    failedChecks.push('deck_metadata_exported_count_missing')
  } else if (!releaseCaseCardCountMatches(input.caseId, exportedCount)) {
    failedChecks.push('deck_metadata_card_count_mismatch')
  }
  if (verifiedCardCount !== null && exportedCount !== null && verifiedCardCount !== exportedCount) {
    failedChecks.push('deck_metadata_anki_verify_card_count_mismatch')
  }
  const verifiedDeckName = stringValue(input.ankiVerifyResult?.deck_name)
  if (verifiedDeckName && deckName && verifiedDeckName !== deckName) {
    failedChecks.push('deck_metadata_anki_verify_deck_name_mismatch')
  }
  const modelNames = verifiedModelNames(input)
  if (modelNames.length > 0 && modelName && !modelNames.includes(modelName)) {
    failedChecks.push('deck_metadata_model_name_not_verified')
  }

  const uniqueFailedChecks = [...new Set(failedChecks)]
  const deckMetadata: ReleaseDeckMetadataArtifact | null =
    uniqueFailedChecks.length === 0 &&
    exportedCount !== null &&
    expectedCardCount !== null &&
    identity.sourceFingerprint &&
    identity.apkgRelativePath &&
    isSha256Hex(identity.apkgSha256) &&
    identity.apkgSizeBytes !== null &&
    identity.apkgMtimeMs !== null &&
    deckName &&
    deckKind &&
    modelName &&
    templateName &&
    templateVersion &&
    ankiTag
      ? {
          schema_version: 1,
          case_id: input.caseId,
          source_kind: input.manifest.source_kind,
          mode: input.manifest.mode,
          cache_state: input.manifest.cache_state,
          source_fingerprint: identity.sourceFingerprint,
          apkg_relative_path: identity.apkgRelativePath,
          apkg_sha256: identity.apkgSha256,
          apkg_size_bytes: identity.apkgSizeBytes,
          apkg_mtime_ms: identity.apkgMtimeMs,
          deck_name: deckName,
          deck_kind: deckKind,
          model_name: modelName,
          template_name: templateName,
          template_version: templateVersion,
          anki_tag: ankiTag,
          card_count: exportedCount,
          exported_count: exportedCount,
        }
      : null

  return {
    ok: uniqueFailedChecks.length === 0,
    status: uniqueFailedChecks.length === 0 ? 'ready_for_write_plan' : 'blocked',
    matrixPassCreated: false,
    failedChecks: uniqueFailedChecks,
    warnings: [],
    artifactPath: deckMetadataArtifactPath(input.caseId),
    deckMetadata,
    notes:
      'Pure deck metadata artifact only. It can prepare future deck_metadata.json content, but it does not write files, update manifests, create APKG/Anki/Computer Use evidence, or claim a matrix pass.',
  }
}

function validateDeckMetadataRelativePath({
  relativePath,
  caseId,
  failedChecks,
}: {
  relativePath: string
  caseId: VideoReleaseCaseId
  failedChecks: string[]
}) {
  const normalized = normalizeRelativePath(relativePath)
  if (pathLooksAbsolute(relativePath) || pathHasTraversal(relativePath)) {
    failedChecks.push('deck_metadata_artifact_path_unsafe')
  }
  if (normalized !== deckMetadataArtifactPath(caseId)) {
    failedChecks.push('deck_metadata_artifact_path_mismatch')
  }
}

export function buildReleaseDeckMetadataArtifactWritePlan(
  input: BuildReleaseDeckMetadataArtifactWritePlanInput,
): ReleaseDeckMetadataArtifactWritePlan {
  const runDir = String(input.runDir ?? '').trim()
  const failedChecks: string[] = []
  validateRunDir(runDir, failedChecks)

  const artifact = buildReleaseDeckMetadataArtifact(input)
  failedChecks.push(...artifact.failedChecks)
  validateDeckMetadataRelativePath({
    relativePath: artifact.artifactPath,
    caseId: input.caseId,
    failedChecks,
  })

  const caseDir = runDir ? joinRunRelativePath(runDir, `cases/${input.caseId}`) : ''
  const deckMetadataPath = runDir ? joinRunRelativePath(runDir, artifact.artifactPath) : ''
  if (caseDir && deckMetadataPath && !pathIsInsideDirectory(deckMetadataPath, caseDir)) {
    failedChecks.push('deck_metadata_absolute_path_outside_case_dir')
  }

  const uniqueFailedChecks = [...new Set(failedChecks)]
  const writes: ReleaseDeckMetadataArtifactWrite[] =
    uniqueFailedChecks.length === 0 && artifact.deckMetadata
      ? [
          {
            kind: 'deck_metadata',
            relativePath: artifact.artifactPath,
            absolutePath: deckMetadataPath,
            content: jsonContent(artifact.deckMetadata),
            writeMode: 'exclusive_create',
          },
        ]
      : []

  return {
    ok: uniqueFailedChecks.length === 0,
    status: uniqueFailedChecks.length === 0 ? 'ready_to_write' : 'blocked',
    matrixPassCreated: false,
    failedChecks: uniqueFailedChecks,
    warnings: artifact.warnings,
    runDir,
    caseDir,
    artifactPath: artifact.artifactPath,
    writes,
    notes:
      'Pure write plan only. A caller may persist deck_metadata.json with exclusive-create semantics, but this plan does not write files, update manifests, create APKG/Anki/Computer Use evidence, or claim a matrix pass.',
  }
}

export function buildReleaseTimingCacheArtifactWritePlan(
  input: BuildReleaseTimingCacheArtifactWritePlanInput,
): ReleaseTimingCacheArtifactWritePlan {
  const runDir = String(input.runDir ?? '').trim()
  const failedChecks: string[] = []
  validateRunDir(runDir, failedChecks)

  const releaseCase = VIDEO_RELEASE_CASES.find((item) => item.id === input.caseId)
  if (!releaseCase) {
    failedChecks.push('release_case_unknown')
  } else {
    if (input.manifest.case_id !== input.caseId) {
      failedChecks.push('write_plan_case_manifest_id_mismatch')
    }
    if (input.manifest.target_card_count !== releaseCase.targetCardCount) {
      failedChecks.push('write_plan_case_manifest_target_card_count_mismatch')
    }
    if (input.manifest.required_preview_cards !== releaseCase.requiredPreviewCards) {
      failedChecks.push('write_plan_case_manifest_required_preview_cards_mismatch')
    }

    const projectFunnel = objectRecord(input.project?.quality_funnel)
    const projectCardCount = firstPositiveNumber(
      projectFunnel.card_count,
      projectFunnel.selected_exportable_card_count,
      projectFunnel.exportable_card_count,
    )
    if (projectCardCount === null) {
      failedChecks.push('write_plan_project_card_count_missing')
    } else if (projectCardCount !== releaseCase.targetCardCount) {
      failedChecks.push('write_plan_project_card_count_mismatch')
    }

    const exportCardCount = positiveNumber(input.exportResult?.cards)
    if (exportCardCount === null) {
      failedChecks.push('write_plan_export_card_count_missing')
    } else if (exportCardCount !== releaseCase.targetCardCount) {
      failedChecks.push('write_plan_export_card_count_mismatch')
    }
  }

  let artifacts: ReleaseTimingCacheArtifacts
  try {
    artifacts = buildReleaseTimingCacheArtifacts(input)
  } catch {
    artifacts = {
      ok: false,
      failedChecks: ['release_case_unknown'],
      warnings: [],
      artifactPaths: {
        timing: `cases/${input.caseId}/timing.json`,
        cache_summary: `cases/${input.caseId}/cache_summary.json`,
      },
      timing: null,
      cacheSummary: null,
    }
  }
  failedChecks.push(...artifacts.failedChecks)

  validateArtifactRelativePath({
    kind: 'timing',
    relativePath: artifacts.artifactPaths.timing,
    caseId: input.caseId,
    expectedFile: 'timing.json',
    failedChecks,
  })
  validateArtifactRelativePath({
    kind: 'cache_summary',
    relativePath: artifacts.artifactPaths.cache_summary,
    caseId: input.caseId,
    expectedFile: 'cache_summary.json',
    failedChecks,
  })

  const caseDir = runDir ? joinRunRelativePath(runDir, `cases/${input.caseId}`) : ''
  const timingPath = runDir ? joinRunRelativePath(runDir, artifacts.artifactPaths.timing) : ''
  const cacheSummaryPath = runDir ? joinRunRelativePath(runDir, artifacts.artifactPaths.cache_summary) : ''
  if (caseDir && timingPath && !pathIsInsideDirectory(timingPath, caseDir)) {
    failedChecks.push('timing_absolute_path_outside_case_dir')
  }
  if (caseDir && cacheSummaryPath && !pathIsInsideDirectory(cacheSummaryPath, caseDir)) {
    failedChecks.push('cache_summary_absolute_path_outside_case_dir')
  }

  const uniqueFailedChecks = [...new Set(failedChecks)]
  const writes: ReleaseTimingCacheArtifactWrite[] =
    uniqueFailedChecks.length === 0 && artifacts.timing && artifacts.cacheSummary
      ? [
          {
            kind: 'timing',
            relativePath: artifacts.artifactPaths.timing,
            absolutePath: timingPath,
            content: jsonContent(artifacts.timing),
            writeMode: 'exclusive_create',
          },
          {
            kind: 'cache_summary',
            relativePath: artifacts.artifactPaths.cache_summary,
            absolutePath: cacheSummaryPath,
            content: jsonContent(artifacts.cacheSummary),
            writeMode: 'exclusive_create',
          },
        ]
      : []

  return {
    ok: uniqueFailedChecks.length === 0,
    status: uniqueFailedChecks.length === 0 ? 'ready_to_write' : 'blocked',
    matrixPassCreated: false,
    failedChecks: uniqueFailedChecks,
    warnings: artifacts.warnings,
    runDir,
    caseDir,
    artifactPaths: artifacts.artifactPaths,
    writes,
    notes:
      'Pure write plan only. A caller may persist these timing/cache artifacts with exclusive-create semantics, but this plan does not write files, update manifests, create APKG/Anki/Computer Use evidence, or claim a matrix pass.',
  }
}
