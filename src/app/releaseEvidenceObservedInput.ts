import type { AnkiVerifyResult, ExportResult, Project } from '../domain/types.ts'
import type {
  VideoReleaseCaseCacheTimingPlan,
  VideoReleaseCaseId,
  VideoReleaseCaseManifest,
} from '../domain/releaseEvidenceLayout.ts'
import type { LearningPointExtractionResult } from '../domain/learningPoints.ts'
import {
  buildReleaseTimingCacheArtifacts,
  type BuildReleaseTimingCacheArtifactsInput,
} from './releaseEvidenceArtifacts.ts'

export type BuildReleaseObservedTimingCacheInputSnapshotInput = {
  caseId: VideoReleaseCaseId
  manifest: VideoReleaseCaseManifest
  learningPointResult: unknown
  project: unknown
  exportResult: unknown
  ankiVerifyResult: unknown
  verifiedExportApkgPath?: string | null
  coldCacheReadsDisabled?: boolean
  sourceCacheProbeStatus?: string | null
  existingUrlCacheDirs?: string[]
}

export type BuildReleaseObservedTimingCacheInputSnapshotFromJsonInput = {
  caseId: VideoReleaseCaseId
  manifest: VideoReleaseCaseManifest
  rawObserved: unknown
}

export type ReleaseObservedTimingCacheInputSnapshot = {
  ok: boolean
  status: 'ready_for_write_plan' | 'blocked'
  matrixPassCreated: false
  failedChecks: string[]
  warnings: string[]
  artifactPaths: VideoReleaseCaseCacheTimingPlan['artifact_paths']
  observedInput: BuildReleaseTimingCacheArtifactsInput | null
  notes: string
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function hasRecordField(value: Record<string, unknown>, key: string) {
  return isRecord(value[key])
}

function hasFiniteNumberField(value: Record<string, unknown>, key: string) {
  return typeof value[key] === 'number' && Number.isFinite(value[key])
}

function hasPositiveNumberField(value: Record<string, unknown>, key: string) {
  return typeof value[key] === 'number' && Number.isFinite(value[key]) && value[key] > 0
}

function hasSha256Field(value: Record<string, unknown>, key: string) {
  return typeof value[key] === 'string' && /^[a-f0-9]{64}$/i.test(value[key])
}

function sourceFingerprintFrom(value: unknown) {
  if (!isRecord(value)) return ''
  const direct = stringValue(value.source_fingerprint)
  if (direct) return direct
  const sourceIdentity = value.source_identity
  if (!isRecord(sourceIdentity)) return ''
  return stringValue(sourceIdentity.source_fingerprint)
}

function unique(values: string[]) {
  return [...new Set(values)]
}

function looksLikeReleaseEvidenceSummary(value: Record<string, unknown>) {
  return (
    Array.isArray(value.stageTimings) &&
    hasRecordField(value, 'phaseTotalsMs') &&
    hasRecordField(value, 'cache') &&
    hasRecordField(value, 'counts') &&
    hasRecordField(value, 'ready')
  )
}

function looksLikeWorkerProgress(value: Record<string, unknown>) {
  return (
    typeof value.command === 'string' &&
    typeof value.stage === 'string' &&
    hasFiniteNumberField(value, 'percent') &&
    typeof value.message === 'string'
  )
}

function looksLikeRustResultSummary(value: Record<string, unknown>) {
  return (
    typeof value.command === 'string' &&
    ['learning_point_summary', 'media_summary', 'quality_funnel', 'cards', 'segments', 'apkg_path'].some((key) =>
      Object.hasOwn(value, key),
    )
  )
}

function looksLikeWorkerFinishedEnvelope(value: Record<string, unknown>) {
  return (
    typeof value.command === 'string' && (Object.hasOwn(value, 'result_summary') || Object.hasOwn(value, 'result_ref'))
  )
}

function looksLikeGenerationBatchFragment(value: Record<string, unknown>) {
  return (
    Array.isArray(value.queueIds) &&
    Array.isArray(value.activeBatchIds) &&
    hasFiniteNumberField(value, 'totalBatches') &&
    hasFiniteNumberField(value, 'completedBatches')
  )
}

function lossyShapeChecks(value: unknown) {
  if (!isRecord(value)) return []
  const failedChecks: string[] = []
  if (looksLikeReleaseEvidenceSummary(value)) {
    failedChecks.push('observed_release_evidence_summary_not_raw')
  }
  if (looksLikeWorkerProgress(value)) {
    failedChecks.push('observed_worker_progress_not_raw')
  }
  if (looksLikeRustResultSummary(value) || looksLikeWorkerFinishedEnvelope(value)) {
    failedChecks.push('observed_worker_result_summary_not_raw')
  }
  if (looksLikeGenerationBatchFragment(value)) {
    failedChecks.push('observed_generation_batch_fragment_not_raw')
  }
  return failedChecks
}

function rawLearningPointChecks(value: unknown) {
  if (!isRecord(value)) return ['observed_learning_point_result_missing']
  if (!hasRecordField(value, 'quality_funnel') && !hasRecordField(value, 'timing_ms')) {
    return ['observed_learning_point_result_not_raw']
  }
  return []
}

function rawProjectChecks(value: unknown) {
  if (!isRecord(value)) return ['observed_project_missing']
  const failedChecks: string[] = []
  if (!hasRecordField(value, 'quality_funnel')) {
    failedChecks.push('observed_project_not_raw')
    return failedChecks
  }
  const qualityFunnel = value.quality_funnel
  if (!isRecord(qualityFunnel)) {
    return ['observed_project_not_raw']
  }
  const reconciliationStatus =
    typeof qualityFunnel.generation_reconciliation_status === 'string'
      ? qualityFunnel.generation_reconciliation_status
      : ''
  if (reconciliationStatus && reconciliationStatus !== 'ok') {
    failedChecks.push('observed_generation_reconciliation_not_ok')
  }
  const missingCount =
    typeof qualityFunnel.generation_missing_count === 'number' ? qualityFunnel.generation_missing_count : 0
  if (missingCount > 0) {
    failedChecks.push('observed_generation_missing_count_nonzero')
  }
  const completedBatches =
    typeof qualityFunnel.generation_batch_completed === 'number' ? qualityFunnel.generation_batch_completed : null
  const totalBatches =
    typeof qualityFunnel.generation_batch_count === 'number' ? qualityFunnel.generation_batch_count : null
  if (totalBatches !== null && totalBatches > 1) {
    if (completedBatches === null || completedBatches < totalBatches) {
      failedChecks.push('observed_generation_batch_incomplete')
    }
    const timingBatchCount =
      typeof qualityFunnel.generation_timing_aggregate_batch_count === 'number'
        ? qualityFunnel.generation_timing_aggregate_batch_count
        : null
    const cacheBatchCount =
      typeof qualityFunnel.card_generation_cache_aggregate_batch_count === 'number'
        ? qualityFunnel.card_generation_cache_aggregate_batch_count
        : null
    if (qualityFunnel.generation_timing_aggregate_complete !== true || timingBatchCount !== totalBatches) {
      failedChecks.push('observed_generation_timing_aggregate_missing')
    }
    if (qualityFunnel.card_generation_cache_aggregate_complete !== true || cacheBatchCount !== totalBatches) {
      failedChecks.push('observed_card_generation_cache_aggregate_missing')
    }
    if (qualityFunnel.card_generation_cache_policy_consistent === false) {
      failedChecks.push('observed_card_generation_cache_policy_inconsistent')
    }
    if (qualityFunnel.card_generation_cache_namespace_consistent === false) {
      failedChecks.push('observed_card_generation_cache_namespace_inconsistent')
    }
    if (
      qualityFunnel.generation_timing_aggregate_complete !== true ||
      timingBatchCount !== totalBatches ||
      qualityFunnel.card_generation_cache_aggregate_complete !== true ||
      cacheBatchCount !== totalBatches ||
      qualityFunnel.card_generation_cache_policy_consistent === false ||
      qualityFunnel.card_generation_cache_namespace_consistent === false
    ) {
      failedChecks.push('observed_generation_batch_aggregate_missing')
    }
  }
  if (completedBatches !== null && totalBatches !== null && completedBatches < totalBatches) {
    failedChecks.push('observed_generation_batch_incomplete')
  }
  return failedChecks
}

function rawExportChecks(value: unknown) {
  if (!isRecord(value)) return ['observed_export_result_missing']
  const failedChecks: string[] = []
  if (typeof value.apkg_path !== 'string' || !value.apkg_path.trim())
    failedChecks.push('observed_export_apkg_path_missing')
  if (!hasSha256Field(value, 'apkg_sha256')) failedChecks.push('observed_export_apkg_sha256_missing')
  if (!hasPositiveNumberField(value, 'apkg_size_bytes')) failedChecks.push('observed_export_apkg_size_bytes_missing')
  if (!hasPositiveNumberField(value, 'apkg_mtime_ms')) failedChecks.push('observed_export_apkg_mtime_ms_missing')
  if (!hasFiniteNumberField(value, 'cards')) failedChecks.push('observed_export_cards_missing')
  if (!hasRecordField(value, 'timing_ms')) failedChecks.push('observed_export_timing_missing')
  if (!hasRecordField(value, 'media_summary')) failedChecks.push('observed_export_media_summary_missing')
  if (!hasRecordField(value, 'media_manifest')) failedChecks.push('observed_export_full_media_manifest_missing')
  if (!Array.isArray(value.media_ledger)) failedChecks.push('observed_export_full_media_ledger_missing')
  if (!Array.isArray(value.card_media_ledger)) failedChecks.push('observed_export_full_card_media_ledger_missing')
  if (!Array.isArray(value.audio_audit_items)) failedChecks.push('observed_export_full_audio_audit_items_missing')
  return failedChecks
}

function rawAnkiVerifyChecks(value: unknown, verifiedExportApkgPath: unknown) {
  if (!isRecord(value)) return ['observed_anki_verify_result_missing']
  const failedChecks: string[] = []
  if (value.ok !== true) failedChecks.push('observed_anki_verify_not_ok')
  if (!Array.isArray(value.failed_checks) || value.failed_checks.length > 0) {
    failedChecks.push('observed_anki_verify_failed_checks_present')
  }
  if (!hasFiniteNumberField(value, 'card_count')) failedChecks.push('observed_anki_verify_card_count_missing')
  if (!hasRecordField(value, 'timing_ms')) failedChecks.push('observed_anki_verify_timing_missing')
  if (!hasSha256Field(value, 'apkg_sha256')) failedChecks.push('observed_anki_verify_apkg_sha256_missing')
  if (!hasPositiveNumberField(value, 'apkg_size_bytes'))
    failedChecks.push('observed_anki_verify_apkg_size_bytes_missing')
  if (!hasPositiveNumberField(value, 'apkg_mtime_ms')) failedChecks.push('observed_anki_verify_apkg_mtime_ms_missing')
  if (typeof verifiedExportApkgPath !== 'string' || !verifiedExportApkgPath.trim()) {
    failedChecks.push('observed_verified_export_apkg_path_missing')
  }
  return failedChecks
}

function staleVerifyChecks(exportResult: unknown, ankiVerifyResult: unknown, verifiedExportApkgPath: unknown) {
  if (!isRecord(exportResult) || !isRecord(ankiVerifyResult)) return []
  const failedChecks: string[] = []
  const exportedCards = typeof exportResult.cards === 'number' ? exportResult.cards : null
  const verifiedCards = typeof ankiVerifyResult.card_count === 'number' ? ankiVerifyResult.card_count : null
  const expectedCards = typeof ankiVerifyResult.expected_cards === 'number' ? ankiVerifyResult.expected_cards : null
  if (exportedCards !== null && verifiedCards !== null && exportedCards !== verifiedCards) {
    failedChecks.push('observed_verify_card_count_mismatch')
  }
  if (exportedCards !== null && expectedCards !== null && exportedCards !== expectedCards) {
    failedChecks.push('observed_verify_expected_cards_mismatch')
  }
  const exportDeck = typeof exportResult.deck_name === 'string' ? exportResult.deck_name.trim() : ''
  const verifyDeck = typeof ankiVerifyResult.deck_name === 'string' ? ankiVerifyResult.deck_name.trim() : ''
  if (exportDeck && verifyDeck && exportDeck !== verifyDeck) {
    failedChecks.push('observed_verify_deck_name_mismatch')
  }
  const exportApkgPath = typeof exportResult.apkg_path === 'string' ? exportResult.apkg_path.trim() : ''
  const verifiedApkgPath = typeof verifiedExportApkgPath === 'string' ? verifiedExportApkgPath.trim() : ''
  if (exportApkgPath && verifiedApkgPath && exportApkgPath !== verifiedApkgPath) {
    failedChecks.push('observed_verify_apkg_path_mismatch')
  }
  const exportApkgSha = typeof exportResult.apkg_sha256 === 'string' ? exportResult.apkg_sha256.trim() : ''
  const verifyApkgSha = typeof ankiVerifyResult.apkg_sha256 === 'string' ? ankiVerifyResult.apkg_sha256.trim() : ''
  if (exportApkgSha && verifyApkgSha && exportApkgSha !== verifyApkgSha) {
    failedChecks.push('observed_verify_apkg_sha256_mismatch')
  }
  const exportApkgSize = typeof exportResult.apkg_size_bytes === 'number' ? exportResult.apkg_size_bytes : null
  const verifyApkgSize = typeof ankiVerifyResult.apkg_size_bytes === 'number' ? ankiVerifyResult.apkg_size_bytes : null
  if (exportApkgSize !== null && verifyApkgSize !== null && exportApkgSize !== verifyApkgSize) {
    failedChecks.push('observed_verify_apkg_size_bytes_mismatch')
  }
  const exportApkgMtime = typeof exportResult.apkg_mtime_ms === 'number' ? exportResult.apkg_mtime_ms : null
  const verifyApkgMtime = typeof ankiVerifyResult.apkg_mtime_ms === 'number' ? ankiVerifyResult.apkg_mtime_ms : null
  if (exportApkgMtime !== null && verifyApkgMtime !== null && exportApkgMtime !== verifyApkgMtime) {
    failedChecks.push('observed_verify_apkg_mtime_ms_mismatch')
  }
  const exportSourceFingerprint = sourceFingerprintFrom(exportResult)
  const verifySourceFingerprint = sourceFingerprintFrom(ankiVerifyResult)
  if (exportSourceFingerprint && !verifySourceFingerprint) {
    failedChecks.push('observed_verify_source_fingerprint_missing')
  } else if (
    exportSourceFingerprint &&
    verifySourceFingerprint &&
    exportSourceFingerprint !== verifySourceFingerprint
  ) {
    failedChecks.push('observed_verify_source_fingerprint_mismatch')
  }
  return failedChecks
}

function fallbackArtifactPaths(caseId: VideoReleaseCaseId): VideoReleaseCaseCacheTimingPlan['artifact_paths'] {
  return {
    timing: `cases/${caseId}/timing.json`,
    cache_summary: `cases/${caseId}/cache_summary.json`,
  }
}

export function buildReleaseObservedTimingCacheInputSnapshot(
  input: BuildReleaseObservedTimingCacheInputSnapshotInput,
): ReleaseObservedTimingCacheInputSnapshot {
  const failedChecks = unique([
    ...lossyShapeChecks(input.learningPointResult),
    ...lossyShapeChecks(input.project),
    ...lossyShapeChecks(input.exportResult),
    ...lossyShapeChecks(input.ankiVerifyResult),
    ...rawLearningPointChecks(input.learningPointResult),
    ...rawProjectChecks(input.project),
    ...rawExportChecks(input.exportResult),
    ...rawAnkiVerifyChecks(input.ankiVerifyResult, input.verifiedExportApkgPath),
    ...staleVerifyChecks(input.exportResult, input.ankiVerifyResult, input.verifiedExportApkgPath),
  ])

  const observedInput: BuildReleaseTimingCacheArtifactsInput = {
    caseId: input.caseId,
    manifest: input.manifest,
    learningPointResult: isRecord(input.learningPointResult)
      ? (input.learningPointResult as Pick<LearningPointExtractionResult, 'quality_funnel' | 'timing_ms'>)
      : null,
    project: isRecord(input.project) ? (input.project as Pick<Project, 'quality_funnel'>) : null,
    exportResult: isRecord(input.exportResult)
      ? (input.exportResult as Pick<
          ExportResult,
          | 'apkg_path'
          | 'apkg_relative_path'
          | 'apkg_sha256'
          | 'apkg_size_bytes'
          | 'apkg_mtime_ms'
          | 'cards'
          | 'media_summary'
          | 'timing_ms'
        >)
      : null,
    ankiVerifyResult: isRecord(input.ankiVerifyResult)
      ? (input.ankiVerifyResult as Pick<AnkiVerifyResult, 'card_count' | 'timing_ms'>)
      : null,
    coldCacheReadsDisabled: input.coldCacheReadsDisabled,
    sourceCacheProbeStatus: input.sourceCacheProbeStatus,
    existingUrlCacheDirs: input.existingUrlCacheDirs,
  }

  let artifactPaths = fallbackArtifactPaths(input.caseId)
  let warnings: string[] = []
  if (failedChecks.length === 0) {
    const artifacts = buildReleaseTimingCacheArtifacts(observedInput)
    artifactPaths = artifacts.artifactPaths
    warnings = artifacts.warnings
    failedChecks.push(...artifacts.failedChecks)
  }

  const uniqueFailedChecks = unique(failedChecks)
  return {
    ok: uniqueFailedChecks.length === 0,
    status: uniqueFailedChecks.length === 0 ? 'ready_for_write_plan' : 'blocked',
    matrixPassCreated: false,
    failedChecks: uniqueFailedChecks,
    warnings,
    artifactPaths,
    observedInput: uniqueFailedChecks.length === 0 ? observedInput : null,
    notes:
      'Pure raw-observed input snapshot only. It accepts raw extraction/generation/export/Anki verify objects for the timing/cache write plan, rejects lossy UI or worker summaries, and does not write files, update manifests, create APKG/Anki/Computer Use evidence, or claim a matrix pass.',
  }
}

function firstValue(...values: unknown[]) {
  return values.find((value) => typeof value !== 'undefined')
}

function stringValue(value: unknown) {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

function stringArrayValue(value: unknown) {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
}

function looksLikeWriterHandoffEnvelope(value: Record<string, unknown>) {
  return (
    value.schema_kind === 'release_timing_cache_writer_handoff_audit' ||
    value.artifact_kind === 'timing_cache_writer_handoff' ||
    value.handoff_kind === 'timing_cache_writer_dry_run_handoff' ||
    value.evidence_role === 'non_final_writer_handoff' ||
    value.matrix_eligibility === 'never' ||
    Object.hasOwn(value, 'raw_observed_json')
  )
}

function writerHandoffEnvelopeFailedChecks(value: Record<string, unknown>, caseId: VideoReleaseCaseId) {
  const failedChecks: string[] = []
  if (value.matrix_pass_created !== false) {
    failedChecks.push('observed_handoff_matrix_pass_created_not_false')
  }
  if (value.matrix_pass_verified !== false && Object.hasOwn(value, 'matrix_pass_verified')) {
    failedChecks.push('observed_handoff_matrix_pass_verified_not_false')
  }
  if (value.write_requested !== false) {
    failedChecks.push('observed_handoff_write_requested_not_false')
  }
  if (Array.isArray(value.written_files) && value.written_files.length > 0) {
    failedChecks.push('observed_handoff_final_written_files_present')
  }
  if (value.release_case_evidence !== false && Object.hasOwn(value, 'release_case_evidence')) {
    failedChecks.push('observed_handoff_release_case_evidence_not_false')
  }
  if (value.matrix_eligibility !== 'never' && Object.hasOwn(value, 'matrix_eligibility')) {
    failedChecks.push('observed_handoff_matrix_eligibility_not_never')
  }
  const envelopeCaseId = stringValue(firstValue(value.caseId, value.case_id))
  if (envelopeCaseId && envelopeCaseId !== caseId) {
    failedChecks.push('observed_handoff_case_id_mismatch')
  }
  if (!isRecord(value.raw_observed_json)) {
    failedChecks.push('observed_handoff_raw_observed_json_missing')
  }
  return failedChecks
}

export function buildReleaseObservedTimingCacheInputSnapshotFromJson({
  caseId,
  manifest,
  rawObserved,
}: BuildReleaseObservedTimingCacheInputSnapshotFromJsonInput): ReleaseObservedTimingCacheInputSnapshot {
  const rootObserved = isRecord(rawObserved) ? rawObserved : {}
  const isHandoffEnvelope = looksLikeWriterHandoffEnvelope(rootObserved)
  const handoffFailedChecks = isHandoffEnvelope ? writerHandoffEnvelopeFailedChecks(rootObserved, caseId) : []
  const observed =
    isHandoffEnvelope && isRecord(rootObserved.raw_observed_json) ? rootObserved.raw_observed_json : rootObserved
  const observedCaseId = stringValue(firstValue(observed.caseId, observed.case_id))
  const snapshot = buildReleaseObservedTimingCacheInputSnapshot({
    caseId,
    manifest,
    learningPointResult: firstValue(observed.learningPointResult, observed.learning_point_result),
    project: observed.project,
    exportResult: firstValue(observed.exportResult, observed.export_result),
    ankiVerifyResult: firstValue(observed.ankiVerifyResult, observed.anki_verify_result),
    verifiedExportApkgPath: stringValue(
      firstValue(observed.verifiedExportApkgPath, observed.verified_export_apkg_path),
    ),
    coldCacheReadsDisabled:
      typeof firstValue(observed.coldCacheReadsDisabled, observed.cold_cache_reads_disabled) === 'boolean'
        ? (firstValue(observed.coldCacheReadsDisabled, observed.cold_cache_reads_disabled) as boolean)
        : undefined,
    sourceCacheProbeStatus: stringValue(
      firstValue(observed.sourceCacheProbeStatus, observed.source_cache_probe_status),
    ),
    existingUrlCacheDirs: stringArrayValue(firstValue(observed.existingUrlCacheDirs, observed.existing_url_cache_dirs)),
  })
  if (observedCaseId && observedCaseId !== caseId) {
    const failedChecks = unique([...snapshot.failedChecks, 'observed_case_id_mismatch'])
    return {
      ...snapshot,
      ok: false,
      status: 'blocked',
      failedChecks,
      observedInput: null,
    }
  }
  if (handoffFailedChecks.length > 0) {
    const failedChecks = unique([...snapshot.failedChecks, ...handoffFailedChecks])
    return {
      ...snapshot,
      ok: false,
      status: 'blocked',
      failedChecks,
      observedInput: null,
    }
  }
  return snapshot
}
