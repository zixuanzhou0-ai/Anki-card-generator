import type { LearningPointExtractionResult } from '../domain/learningPoints.ts'
import type { VideoReleaseCaseId, VideoReleaseCaseManifest } from '../domain/releaseEvidenceLayout.ts'
import type { AnkiVerifyResult, ExportResult, Project } from '../domain/types.ts'
import {
  buildReleaseTimingCacheArtifactWritePlan,
  type ReleaseTimingCacheArtifactWrite,
  type ReleaseTimingCacheArtifactWritePlan,
} from './releaseEvidenceArtifacts.ts'
import {
  buildReleaseObservedTimingCacheInputSnapshot,
  type ReleaseObservedTimingCacheInputSnapshot,
} from './releaseEvidenceObservedInput.ts'

export type ReleaseEvidenceRawSnapshotJobIds = {
  extraction?: string
  generation?: string
  export?: string
  ankiVerify?: string
}

export type ReleaseEvidenceRawSnapshot = {
  learningPointResult: LearningPointExtractionResult | null
  project: Project | null
  exportResult: ExportResult | null
  ankiVerifyResult: AnkiVerifyResult | null
  verifiedExportApkgPath: string | null
  jobIds: ReleaseEvidenceRawSnapshotJobIds
}

export type ReleaseEvidenceRawSnapshotEvent =
  | { type: 'learning_point_result'; result: LearningPointExtractionResult; jobId?: string }
  | {
      type: 'project_result' | 'project_for_export'
      project: Project
      learningPointResult?: LearningPointExtractionResult | null
      jobId?: string
    }
  | { type: 'export_result'; result: ExportResult; jobId?: string }
  | { type: 'verify_result'; result: AnkiVerifyResult; verifiedExportApkgPath: string | null; jobId?: string }
  | { type: 'invalidate'; scope: 'all' | 'project_export_verify' | 'export_and_verify' | 'verify' }

export type BuildReleaseObservedSnapshotFromRawCaptureInput = {
  capture: ReleaseEvidenceRawSnapshot
  caseId: VideoReleaseCaseId
  manifest: VideoReleaseCaseManifest
  coldCacheReadsDisabled?: boolean
  sourceCacheProbeStatus?: string | null
  existingUrlCacheDirs?: string[]
}

export type BuildReleaseObservedSnapshotFromAppStateInput = Omit<
  BuildReleaseObservedSnapshotFromRawCaptureInput,
  'capture'
> & {
  learningPointResult: LearningPointExtractionResult | null
  lastLearningPointResult?: LearningPointExtractionResult | null
  project: Project | null
  lastExport: ExportResult | null
  lastExportFull: ExportResult | null
  ankiVerifyResult: AnkiVerifyResult | null
  verifiedExportApkgPath?: string | null
}

export type ReleaseObservedAppSnapshot = ReleaseObservedTimingCacheInputSnapshot & {
  rawObservedJson: Record<string, unknown> | null
}

export type BuildReleaseObservedTimingCacheWritePlanFromRawCaptureInput =
  BuildReleaseObservedSnapshotFromRawCaptureInput & {
    runDir: string
  }

export type BuildReleaseObservedTimingCacheWritePlanFromAppStateInput =
  BuildReleaseObservedSnapshotFromAppStateInput & {
    runDir: string
  }

export type ReleaseObservedTimingCacheWritePlanSnapshot = {
  ok: boolean
  status: 'ready_to_write' | 'blocked'
  matrixPassCreated: false
  failedChecks: string[]
  warnings: string[]
  rawObservedJson: Record<string, unknown> | null
  observedSnapshot: ReleaseObservedAppSnapshot
  writePlan: ReleaseTimingCacheArtifactWritePlan | null
  notes: string
}

export type ReleaseObservedTimingCacheWriterDryRunEvidence = {
  schema_version: 1
  status: 'ready_to_write' | 'blocked'
  matrix_pass_created: false
  write_requested: false
  written_files: []
  raw_observed_json: Record<string, unknown> | null
  planned_writes: Array<{
    kind: ReleaseTimingCacheArtifactWrite['kind']
    relative_path: string
    absolute_path: string
    write_mode: ReleaseTimingCacheArtifactWrite['writeMode']
    bytes: number
  }>
  writer: {
    ok: boolean
    failed_checks: string[]
    warnings: string[]
  }
  notes: string
}

export type ReleaseObservedTimingCacheWriterHandoffArtifact = ReleaseObservedTimingCacheWriterDryRunEvidence & {
  schema_kind: 'release_timing_cache_writer_handoff_audit'
  artifact_kind: 'timing_cache_writer_handoff'
  handoff_kind: 'timing_cache_writer_dry_run_handoff'
  evidence_role: 'non_final_writer_handoff'
  artifact_scope: 'timing_cache_writer_only'
  matrix_eligibility: 'never'
  release_case_evidence: false
  matrix_pass_verified: false
  promotion_policy: 'never_satisfies_release_verify_case'
  final_artifacts_written: false
  final_artifacts: {
    timing_json_written: false
    cache_summary_json_written: false
    manifests_updated: false
    matrix_summary_updated: false
    apkg_created: false
    anki_verified: false
    computer_use_actions_created: false
    screenshots_created: false
  }
  handoff_written_files: []
}

export type ReleaseObservedRawSnapshotHandoffArtifact = {
  schema_version: 1
  schema_kind: 'release_raw_observed_snapshot_handoff_audit'
  artifact_kind: 'raw_observed_snapshot_handoff'
  handoff_kind: 'raw_observed_snapshot_non_final_handoff'
  evidence_role: 'non_final_raw_observed_handoff'
  artifact_scope: 'raw_observed_input_only'
  matrix_eligibility: 'never'
  release_case_evidence: false
  matrix_pass_created: false
  matrix_pass_verified: false
  write_requested: false
  written_files: []
  final_artifacts_written: false
  final_artifacts: {
    timing_json_written: false
    cache_summary_json_written: false
    manifests_updated: false
    matrix_summary_updated: false
    apkg_created: false
    anki_verified: false
    computer_use_actions_created: false
    screenshots_created: false
  }
  case_id: VideoReleaseCaseId
  status: 'ready_for_downstream_validation' | 'captured_with_blockers'
  failed_checks: string[]
  warnings: string[]
  raw_observed_json: Record<string, unknown>
  capture_state: {
    ok: boolean
    failed_checks: string[]
    warnings: string[]
    present: {
      learning_point_result: boolean
      project: boolean
      export_result: boolean
      anki_verify_result: boolean
      verified_export_apkg_path: boolean
    }
    job_ids: ReleaseEvidenceRawSnapshotJobIds
  }
  notes: string
}

export function emptyReleaseEvidenceRawSnapshot(): ReleaseEvidenceRawSnapshot {
  return {
    learningPointResult: null,
    project: null,
    exportResult: null,
    ankiVerifyResult: null,
    verifiedExportApkgPath: null,
    jobIds: {},
  }
}

function unique(values: string[]) {
  return [...new Set(values)]
}

function compactExportMatchesFull(compact: ExportResult, full: ExportResult): boolean {
  const optionalIdentityMatches =
    (!compact.apkg_sha256 || !full.apkg_sha256 || compact.apkg_sha256 === full.apkg_sha256) &&
    (!compact.apkg_size_bytes || !full.apkg_size_bytes || compact.apkg_size_bytes === full.apkg_size_bytes) &&
    (!compact.apkg_mtime_ms || !full.apkg_mtime_ms || compact.apkg_mtime_ms === full.apkg_mtime_ms)
  return (
    compact.apkg_path === full.apkg_path &&
    compact.cards === full.cards &&
    compact.deck_name === full.deck_name &&
    compact.media_dir === full.media_dir &&
    optionalIdentityMatches
  )
}

function withAppFailedChecks(
  snapshot: ReleaseObservedTimingCacheInputSnapshot,
  failedChecks: string[],
  rawObservedJson: Record<string, unknown>,
): ReleaseObservedAppSnapshot {
  const uniqueFailedChecks = unique([...failedChecks, ...snapshot.failedChecks])
  return {
    ...snapshot,
    ok: uniqueFailedChecks.length === 0,
    status: uniqueFailedChecks.length === 0 ? 'ready_for_write_plan' : 'blocked',
    failedChecks: uniqueFailedChecks,
    observedInput: uniqueFailedChecks.length === 0 ? snapshot.observedInput : null,
    rawObservedJson: uniqueFailedChecks.length === 0 ? rawObservedJson : null,
  }
}

function buildWritePlanSnapshotFromObservedSnapshot(
  snapshot: ReleaseObservedAppSnapshot,
  runDir: string,
): ReleaseObservedTimingCacheWritePlanSnapshot {
  const writePlan = snapshot.observedInput
    ? buildReleaseTimingCacheArtifactWritePlan({
        ...snapshot.observedInput,
        runDir,
      })
    : null
  const failedChecks = unique(
    [
      ...snapshot.failedChecks,
      ...(snapshot.observedInput ? [] : ['observed_snapshot_blocked']),
      ...(writePlan?.failedChecks ?? []),
      writePlan && writePlan.matrixPassCreated !== false ? 'write_plan_matrix_pass_created_not_false' : '',
    ].filter(Boolean),
  )
  const warnings = unique([...snapshot.warnings, ...(writePlan?.warnings ?? [])])
  const ok = failedChecks.length === 0 && writePlan?.ok === true

  return {
    ok,
    status: ok ? 'ready_to_write' : 'blocked',
    matrixPassCreated: false,
    failedChecks,
    warnings,
    rawObservedJson: snapshot.rawObservedJson,
    observedSnapshot: snapshot,
    writePlan,
    notes:
      'Pure app-observed timing/cache write-plan snapshot only. It may return exclusive-create timing/cache payloads for a caller to persist, but it does not write files, update manifests, create APKG/Anki/Computer Use evidence, or claim a matrix pass.',
  }
}

function utf8ByteLength(value: string): number {
  return new TextEncoder().encode(value).length
}

function summarizePlannedWrite(
  write: ReleaseTimingCacheArtifactWrite,
): ReleaseObservedTimingCacheWriterDryRunEvidence['planned_writes'][number] {
  return {
    kind: write.kind,
    relative_path: write.relativePath,
    absolute_path: write.absolutePath,
    write_mode: write.writeMode,
    bytes: utf8ByteLength(write.content),
  }
}

export function buildReleaseObservedTimingCacheWriterDryRunEvidence(
  snapshot: ReleaseObservedTimingCacheWritePlanSnapshot,
): ReleaseObservedTimingCacheWriterDryRunEvidence {
  return {
    schema_version: 1,
    status: snapshot.status,
    matrix_pass_created: false,
    write_requested: false,
    written_files: [],
    raw_observed_json: snapshot.rawObservedJson,
    planned_writes: snapshot.writePlan?.writes.map(summarizePlannedWrite) ?? [],
    writer: {
      ok: snapshot.ok,
      failed_checks: snapshot.failedChecks,
      warnings: snapshot.warnings,
    },
    notes:
      'Dry-run writer handoff only. Planned writes are summaries without file content; no timing/cache files, manifests, APKG, Anki, Computer Use, observations, screenshots, or matrix proof were written.',
  }
}

export function buildReleaseObservedTimingCacheWriterHandoffArtifact(
  snapshot: ReleaseObservedTimingCacheWritePlanSnapshot,
): ReleaseObservedTimingCacheWriterHandoffArtifact {
  return {
    ...buildReleaseObservedTimingCacheWriterDryRunEvidence(snapshot),
    schema_kind: 'release_timing_cache_writer_handoff_audit',
    artifact_kind: 'timing_cache_writer_handoff',
    handoff_kind: 'timing_cache_writer_dry_run_handoff',
    evidence_role: 'non_final_writer_handoff',
    artifact_scope: 'timing_cache_writer_only',
    matrix_eligibility: 'never',
    release_case_evidence: false,
    matrix_pass_verified: false,
    promotion_policy: 'never_satisfies_release_verify_case',
    final_artifacts_written: false,
    final_artifacts: {
      timing_json_written: false,
      cache_summary_json_written: false,
      manifests_updated: false,
      matrix_summary_updated: false,
      apkg_created: false,
      anki_verified: false,
      computer_use_actions_created: false,
      screenshots_created: false,
    },
    handoff_written_files: [],
    notes:
      'Non-final timing/cache writer handoff audit only. It preserves raw observed JSON and planned write summaries for a future writer, but it is not release case evidence and never satisfies release verification by itself.',
  }
}

export function buildReleaseObservedRawJsonFromRawCapture(
  input: BuildReleaseObservedSnapshotFromRawCaptureInput,
): Record<string, unknown> {
  return rawObservedJsonFromSnapshot(input)
}

export function buildReleaseObservedRawSnapshotHandoffArtifact(
  input: BuildReleaseObservedSnapshotFromRawCaptureInput,
): ReleaseObservedRawSnapshotHandoffArtifact {
  const rawObservedJson = buildReleaseObservedRawJsonFromRawCapture(input)
  const observedSnapshot = buildReleaseObservedSnapshotFromRawCapture(input)

  return {
    schema_version: 1,
    schema_kind: 'release_raw_observed_snapshot_handoff_audit',
    artifact_kind: 'raw_observed_snapshot_handoff',
    handoff_kind: 'raw_observed_snapshot_non_final_handoff',
    evidence_role: 'non_final_raw_observed_handoff',
    artifact_scope: 'raw_observed_input_only',
    matrix_eligibility: 'never',
    release_case_evidence: false,
    matrix_pass_created: false,
    matrix_pass_verified: false,
    write_requested: false,
    written_files: [],
    final_artifacts_written: false,
    final_artifacts: {
      timing_json_written: false,
      cache_summary_json_written: false,
      manifests_updated: false,
      matrix_summary_updated: false,
      apkg_created: false,
      anki_verified: false,
      computer_use_actions_created: false,
      screenshots_created: false,
    },
    case_id: input.caseId,
    status: observedSnapshot.ok ? 'ready_for_downstream_validation' : 'captured_with_blockers',
    failed_checks: observedSnapshot.failedChecks,
    warnings: observedSnapshot.warnings,
    raw_observed_json: rawObservedJson,
    capture_state: {
      ok: observedSnapshot.ok,
      failed_checks: observedSnapshot.failedChecks,
      warnings: observedSnapshot.warnings,
      present: {
        learning_point_result: Boolean(input.capture.learningPointResult),
        project: Boolean(input.capture.project),
        export_result: Boolean(input.capture.exportResult),
        anki_verify_result: Boolean(input.capture.ankiVerifyResult),
        verified_export_apkg_path: Boolean(input.capture.verifiedExportApkgPath),
      },
      job_ids: input.capture.jobIds,
    },
    notes:
      'Non-final raw observed snapshot handoff only. It preserves hydrated app-side extraction, project, export, and Anki verify JSON for future release automation, but it writes no files, updates no manifests, creates no APKG/Anki/Computer Use/screenshot evidence, and never satisfies release verification by itself.',
  }
}

function rawObservedJsonFromSnapshot({
  caseId,
  capture,
  coldCacheReadsDisabled,
  sourceCacheProbeStatus,
  existingUrlCacheDirs,
}: {
  caseId: VideoReleaseCaseId
  capture: ReleaseEvidenceRawSnapshot
  coldCacheReadsDisabled?: boolean
  sourceCacheProbeStatus?: string | null
  existingUrlCacheDirs?: string[]
}): Record<string, unknown> {
  return {
    case_id: caseId,
    learning_point_result: capture.learningPointResult,
    project: capture.project,
    export_result: capture.exportResult,
    anki_verify_result: capture.ankiVerifyResult,
    verified_export_apkg_path: capture.verifiedExportApkgPath,
    cold_cache_reads_disabled: coldCacheReadsDisabled,
    source_cache_probe_status: sourceCacheProbeStatus,
    existing_url_cache_dirs: existingUrlCacheDirs ?? [],
    job_ids: capture.jobIds,
  }
}

export function reduceReleaseEvidenceRawSnapshot(
  current: ReleaseEvidenceRawSnapshot,
  event: ReleaseEvidenceRawSnapshotEvent,
): ReleaseEvidenceRawSnapshot {
  if (event.type === 'invalidate') {
    if (event.scope === 'all') return emptyReleaseEvidenceRawSnapshot()
    if (event.scope === 'project_export_verify') {
      return {
        ...current,
        project: null,
        exportResult: null,
        ankiVerifyResult: null,
        verifiedExportApkgPath: null,
        jobIds: { extraction: current.jobIds.extraction },
      }
    }
    if (event.scope === 'export_and_verify') {
      return {
        ...current,
        exportResult: null,
        ankiVerifyResult: null,
        verifiedExportApkgPath: null,
        jobIds: {
          extraction: current.jobIds.extraction,
          generation: current.jobIds.generation,
        },
      }
    }
    return {
      ...current,
      ankiVerifyResult: null,
      verifiedExportApkgPath: null,
      jobIds: {
        extraction: current.jobIds.extraction,
        generation: current.jobIds.generation,
        export: current.jobIds.export,
      },
    }
  }

  if (event.type === 'learning_point_result') {
    return {
      ...emptyReleaseEvidenceRawSnapshot(),
      learningPointResult: event.result,
      jobIds: { extraction: event.jobId },
    }
  }

  if (event.type === 'project_result' || event.type === 'project_for_export') {
    return {
      ...current,
      learningPointResult: event.learningPointResult ?? current.learningPointResult,
      project: event.project,
      exportResult: null,
      ankiVerifyResult: null,
      verifiedExportApkgPath: null,
      jobIds: {
        extraction: current.jobIds.extraction,
        generation: event.jobId ?? current.jobIds.generation,
      },
    }
  }

  if (event.type === 'export_result') {
    return {
      ...current,
      exportResult: event.result,
      ankiVerifyResult: null,
      verifiedExportApkgPath: null,
      jobIds: {
        extraction: current.jobIds.extraction,
        generation: current.jobIds.generation,
        export: event.jobId,
      },
    }
  }

  if (event.type === 'verify_result') {
    return {
      ...current,
      ankiVerifyResult: event.result,
      verifiedExportApkgPath: event.verifiedExportApkgPath,
      jobIds: {
        ...current.jobIds,
        ankiVerify: event.jobId,
      },
    }
  }

  return current
}

export function buildReleaseObservedSnapshotFromRawCapture({
  capture,
  caseId,
  manifest,
  coldCacheReadsDisabled,
  sourceCacheProbeStatus,
  existingUrlCacheDirs,
}: BuildReleaseObservedSnapshotFromRawCaptureInput): ReleaseObservedAppSnapshot {
  const rawObservedJson = rawObservedJsonFromSnapshot({
    caseId,
    capture,
    coldCacheReadsDisabled,
    sourceCacheProbeStatus,
    existingUrlCacheDirs,
  })
  const snapshot = buildReleaseObservedTimingCacheInputSnapshot({
    caseId,
    manifest,
    learningPointResult: capture.learningPointResult,
    project: capture.project,
    exportResult: capture.exportResult,
    ankiVerifyResult: capture.ankiVerifyResult,
    verifiedExportApkgPath: capture.verifiedExportApkgPath,
    coldCacheReadsDisabled,
    sourceCacheProbeStatus,
    existingUrlCacheDirs,
  })
  return withAppFailedChecks(snapshot, [], rawObservedJson)
}

export function buildReleaseObservedTimingCacheWritePlanFromRawCapture({
  runDir,
  ...snapshotInput
}: BuildReleaseObservedTimingCacheWritePlanFromRawCaptureInput): ReleaseObservedTimingCacheWritePlanSnapshot {
  return buildWritePlanSnapshotFromObservedSnapshot(buildReleaseObservedSnapshotFromRawCapture(snapshotInput), runDir)
}

export function buildReleaseObservedSnapshotFromAppState({
  caseId,
  manifest,
  learningPointResult,
  lastLearningPointResult,
  project,
  lastExport,
  lastExportFull,
  ankiVerifyResult,
  verifiedExportApkgPath,
  coldCacheReadsDisabled,
  sourceCacheProbeStatus,
  existingUrlCacheDirs,
}: BuildReleaseObservedSnapshotFromAppStateInput): ReleaseObservedAppSnapshot {
  const failedChecks: string[] = []
  const rawLearningPointResult = learningPointResult ?? lastLearningPointResult ?? null
  const rawExportResult = lastExport ? (lastExportFull ?? lastExport) : null
  const rawVerifiedExportApkgPath = lastExport ? (verifiedExportApkgPath ?? lastExportFull?.apkg_path ?? null) : null

  if (lastExport && !lastExportFull) {
    failedChecks.push('app_snapshot_full_export_result_missing')
  }
  if (!lastExport && lastExportFull) {
    failedChecks.push('app_snapshot_compact_export_result_missing')
  }
  if (!lastExport && ankiVerifyResult) {
    failedChecks.push('app_snapshot_verify_result_without_current_export')
  }
  if (lastExport && lastExportFull && !compactExportMatchesFull(lastExport, lastExportFull)) {
    failedChecks.push('app_snapshot_export_ref_mismatch')
  }

  const capture: ReleaseEvidenceRawSnapshot = {
    learningPointResult: rawLearningPointResult,
    project,
    exportResult: rawExportResult,
    ankiVerifyResult,
    verifiedExportApkgPath: rawVerifiedExportApkgPath,
    jobIds: {},
  }
  const rawObservedJson = rawObservedJsonFromSnapshot({
    caseId,
    capture,
    coldCacheReadsDisabled,
    sourceCacheProbeStatus,
    existingUrlCacheDirs,
  })
  const snapshot = buildReleaseObservedTimingCacheInputSnapshot({
    caseId,
    manifest,
    learningPointResult: capture.learningPointResult,
    project: capture.project,
    exportResult: capture.exportResult,
    ankiVerifyResult: capture.ankiVerifyResult,
    verifiedExportApkgPath: capture.verifiedExportApkgPath,
    coldCacheReadsDisabled,
    sourceCacheProbeStatus,
    existingUrlCacheDirs,
  })
  return withAppFailedChecks(snapshot, failedChecks, rawObservedJson)
}

export function buildReleaseObservedTimingCacheWritePlanFromAppState({
  runDir,
  ...snapshotInput
}: BuildReleaseObservedTimingCacheWritePlanFromAppStateInput): ReleaseObservedTimingCacheWritePlanSnapshot {
  return buildWritePlanSnapshotFromObservedSnapshot(buildReleaseObservedSnapshotFromAppState(snapshotInput), runDir)
}
