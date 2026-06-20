import type { AnkiVerifyResult, ExportResult } from '../domain/types.ts'
import type { VideoReleaseCaseId, VideoReleaseCaseManifest } from '../domain/releaseEvidenceLayout.ts'
import {
  VIDEO_RELEASE_CASES,
  VIDEO_RELEASE_RUN_DIR_PREFIX,
  VIDEO_RELEASE_RUN_STAMP_PATTERN,
  evaluateVideoReleaseCaseCompletionEvidence,
} from '../domain/releaseEvidenceLayout.ts'

type AudioAuditPayload = {
  summary: Record<string, unknown>
  items: Record<string, unknown>[]
}

export type BuildReleaseAudioAuditArtifactInput = {
  caseId: VideoReleaseCaseId
  manifest: VideoReleaseCaseManifest
  audioAudit: unknown
  exportResult?: Pick<ExportResult, 'cards' | 'audio_audit_summary' | 'audio_audit_items'> | null
  ankiVerifyResult?: Pick<
    AnkiVerifyResult,
    'ok' | 'failed_checks' | 'card_count' | 'audio_audit_verify_path' | 'audio_audit_mismatches' | 'audio_audit_write_errors' | 'audio_audit_summary'
  > | null
}

export type ReleaseAudioAuditArtifactResult = {
  ok: boolean
  status: 'ready_for_write_plan' | 'blocked'
  matrixPassCreated: false
  failedChecks: string[]
  warnings: string[]
  artifactPath: string
  audioAudit: AudioAuditPayload | null
  notes: string
}

export type ReleaseAudioAuditArtifactWrite = {
  kind: 'audio_audit'
  relativePath: string
  absolutePath: string
  content: string
  writeMode: 'exclusive_create'
}

export type BuildReleaseAudioAuditArtifactWritePlanInput = BuildReleaseAudioAuditArtifactInput & {
  runDir: string
}

export type ReleaseAudioAuditArtifactWritePlan = {
  ok: boolean
  status: 'ready_to_write' | 'blocked'
  matrixPassCreated: false
  failedChecks: string[]
  warnings: string[]
  runDir: string
  caseDir: string
  artifactPath: string
  writes: ReleaseAudioAuditArtifactWrite[]
  notes: string
}

function objectRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {}
}

function arrayRecords(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object' && !Array.isArray(item))
    : []
}

function numberValue(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function hasNoFailures(value: unknown): boolean {
  return Array.isArray(value) && value.length === 0
}

function releaseCaseCardCountMatches(caseId: VideoReleaseCaseId, value: number | null): boolean {
  if (value === null) {
    return false
  }
  const releaseCase = VIDEO_RELEASE_CASES.find((item) => item.id === caseId)
  if (!releaseCase) {
    return false
  }
  return 'minimumGeneratedCards' in releaseCase ? value >= releaseCase.minimumGeneratedCards : value === releaseCase.targetCardCount
}

function audioAuditArtifactPath(caseId: VideoReleaseCaseId): string {
  return `cases/${caseId}/audio_audit.verify.json`
}

function normalizeRelativePath(value: string): string {
  return value.replace(/\\/g, '/').replace(/^\/+/, '').replace(/\/+/g, '/').replace(/\/$/, '')
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
  return value.startsWith(VIDEO_RELEASE_RUN_DIR_PREFIX) && VIDEO_RELEASE_RUN_STAMP_PATTERN.test(value.slice(VIDEO_RELEASE_RUN_DIR_PREFIX.length))
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

function validateAudioAuditRelativePath({
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
    failedChecks.push('audio_audit_artifact_path_unsafe')
  }
  if (normalized !== audioAuditArtifactPath(caseId)) {
    failedChecks.push('audio_audit_artifact_path_mismatch')
  }
}

function jsonContent(value: unknown): string {
  return `${JSON.stringify(value, null, 2)}\n`
}

function isAudioAuditPayload(value: unknown): value is AudioAuditPayload {
  const payload = objectRecord(value)
  return Object.keys(payload).length > 0 && Object.keys(objectRecord(payload.summary)).length > 0 && arrayRecords(payload.items).length > 0
}

function matrixPassFieldPresent(value: unknown): boolean {
  const payload = objectRecord(value)
  return Object.hasOwn(payload, 'matrix_pass_created') || Object.hasOwn(payload, 'matrixPassCreated')
}

function compareAuditSummaryCount(
  failedChecks: string[],
  prefix: string,
  caseId: VideoReleaseCaseId,
  summary: Record<string, unknown>,
) {
  const items = numberValue(summary.items)
  const expectedItems = numberValue(summary.expected_items)
  if (!releaseCaseCardCountMatches(caseId, items) || !releaseCaseCardCountMatches(caseId, expectedItems)) {
    failedChecks.push(`${prefix}_count_mismatch`)
  }
}

export function buildReleaseAudioAuditArtifact(input: BuildReleaseAudioAuditArtifactInput): ReleaseAudioAuditArtifactResult {
  const failedChecks: string[] = []
  const releaseCase = VIDEO_RELEASE_CASES.find((item) => item.id === input.caseId)
  if (!releaseCase) {
    failedChecks.push('release_case_unknown')
  }
  if (input.manifest.case_id !== input.caseId) {
    failedChecks.push('audio_audit_manifest_case_id_mismatch')
  }
  if (releaseCase && input.manifest.target_card_count !== releaseCase.targetCardCount) {
    failedChecks.push('audio_audit_manifest_target_card_count_mismatch')
  }
  if (!isAudioAuditPayload(input.audioAudit)) {
    failedChecks.push('audio_audit_payload_missing')
  }
  if (matrixPassFieldPresent(input.audioAudit)) {
    failedChecks.push('audio_audit_artifact_matrix_pass_field_present')
  }

  const auditPayload = isAudioAuditPayload(input.audioAudit)
    ? {
        summary: objectRecord(input.audioAudit.summary),
        items: arrayRecords(input.audioAudit.items),
      }
    : null

  if (auditPayload) {
    const completion = evaluateVideoReleaseCaseCompletionEvidence({
      caseId: input.caseId,
      manifest: input.manifest,
      audioAudit: auditPayload,
    })
    failedChecks.push(
      ...completion.failedChecks.filter((check) => check === 'audio_audit_missing' || check.startsWith('audio_audit_')),
    )
  }

  const exportSummary = objectRecord(input.exportResult?.audio_audit_summary)
  if (Object.keys(exportSummary).length > 0) {
    if (exportSummary.status !== 'passed') {
      failedChecks.push('audio_audit_export_summary_status_not_passed')
    }
    compareAuditSummaryCount(failedChecks, 'audio_audit_export_summary', input.caseId, exportSummary)
  }
  const exportItems = Array.isArray(input.exportResult?.audio_audit_items) ? input.exportResult.audio_audit_items.length : null
  if (exportItems !== null && !releaseCaseCardCountMatches(input.caseId, exportItems)) {
    failedChecks.push('audio_audit_export_items_count_mismatch')
  }
  const exportedCards = numberValue(input.exportResult?.cards)
  if (exportedCards !== null && !releaseCaseCardCountMatches(input.caseId, exportedCards)) {
    failedChecks.push('audio_audit_export_card_count_mismatch')
  }

  const ankiVerify = input.ankiVerifyResult
  if (ankiVerify) {
    if (ankiVerify.ok !== true) {
      failedChecks.push('audio_audit_anki_verify_not_ok')
    }
    if (!hasNoFailures(ankiVerify.failed_checks)) {
      failedChecks.push('audio_audit_anki_verify_failed_checks_present')
    }
    const verifiedCards = numberValue(ankiVerify.card_count)
    if (!releaseCaseCardCountMatches(input.caseId, verifiedCards)) {
      failedChecks.push('audio_audit_anki_verify_card_count_mismatch')
    }
    if (typeof ankiVerify.audio_audit_verify_path !== 'string' || !ankiVerify.audio_audit_verify_path.trim()) {
      failedChecks.push('audio_audit_anki_verify_path_missing')
    }
    if (!hasNoFailures(ankiVerify.audio_audit_mismatches)) {
      failedChecks.push('audio_audit_anki_verify_mismatches_present')
    }
    if (!hasNoFailures(ankiVerify.audio_audit_write_errors)) {
      failedChecks.push('audio_audit_anki_verify_write_errors_present')
    }
    const verifySummary = objectRecord(ankiVerify.audio_audit_summary)
    if (Object.keys(verifySummary).length === 0) {
      failedChecks.push('audio_audit_anki_verify_summary_missing')
    } else {
      if (verifySummary.status !== 'passed') {
        failedChecks.push('audio_audit_anki_verify_summary_status_not_passed')
      }
      compareAuditSummaryCount(failedChecks, 'audio_audit_anki_verify_summary', input.caseId, verifySummary)
    }
    if (auditPayload && verifySummary.verify_path && verifySummary.verify_path !== ankiVerify.audio_audit_verify_path) {
      failedChecks.push('audio_audit_anki_verify_summary_path_mismatch')
    }
  }

  const uniqueFailedChecks = [...new Set(failedChecks)]
  return {
    ok: uniqueFailedChecks.length === 0,
    status: uniqueFailedChecks.length === 0 ? 'ready_for_write_plan' : 'blocked',
    matrixPassCreated: false,
    failedChecks: uniqueFailedChecks,
    warnings: [],
    artifactPath: audioAuditArtifactPath(input.caseId),
    audioAudit: uniqueFailedChecks.length === 0 ? auditPayload : null,
    notes:
      'Pure audio audit artifact guard only. It can prepare future audio_audit.verify.json content, but it does not write files, update manifests, create APKG/Anki/Computer Use evidence, or claim a matrix pass.',
  }
}

export function buildReleaseAudioAuditArtifactWritePlan(
  input: BuildReleaseAudioAuditArtifactWritePlanInput,
): ReleaseAudioAuditArtifactWritePlan {
  const runDir = String(input.runDir ?? '').trim()
  const failedChecks: string[] = []
  validateRunDir(runDir, failedChecks)

  const artifact = buildReleaseAudioAuditArtifact(input)
  failedChecks.push(...artifact.failedChecks)
  validateAudioAuditRelativePath({
    relativePath: artifact.artifactPath,
    caseId: input.caseId,
    failedChecks,
  })

  const caseDir = runDir ? joinRunRelativePath(runDir, `cases/${input.caseId}`) : ''
  const audioAuditPath = runDir ? joinRunRelativePath(runDir, artifact.artifactPath) : ''
  if (caseDir && audioAuditPath && !pathIsInsideDirectory(audioAuditPath, caseDir)) {
    failedChecks.push('audio_audit_absolute_path_outside_case_dir')
  }

  const uniqueFailedChecks = [...new Set(failedChecks)]
  const writes: ReleaseAudioAuditArtifactWrite[] =
    uniqueFailedChecks.length === 0 && artifact.audioAudit
      ? [
          {
            kind: 'audio_audit',
            relativePath: artifact.artifactPath,
            absolutePath: audioAuditPath,
            content: jsonContent(artifact.audioAudit),
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
      'Pure write plan only. A caller may persist audio_audit.verify.json with exclusive-create semantics, but this plan does not write files, update manifests, create APKG/Anki/Computer Use evidence, or claim a matrix pass.',
  }
}
