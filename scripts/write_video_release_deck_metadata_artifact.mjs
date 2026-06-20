import { createHash } from 'node:crypto'
import { constants as fsConstants } from 'node:fs'
import { access, readdir, readFile, stat, writeFile } from 'node:fs/promises'
import path from 'node:path'

import { buildReleaseDeckMetadataArtifactWritePlan } from '../src/app/releaseEvidenceArtifacts.ts'
import {
  VIDEO_RELEASE_CASES,
  VIDEO_RELEASE_RUN_DIR_PREFIX,
  VIDEO_RELEASE_RUN_STAMP_PATTERN,
} from '../src/domain/releaseEvidenceLayout.ts'
import {
  buildWriterInputSourceFilePreflight,
  readJsonWithSourceFile,
} from './release_input_source_files.mjs'

const WRITE_ARTIFACTS = {
  deck_metadata: 'deck_metadata.json',
}

function usage() {
  return [
    'Usage:',
    '  node scripts/write_video_release_deck_metadata_artifact.mjs --run-dir PATH --case CASE_ID --observed PATH [--dry-run|--write]',
    '',
    'Writes only cases/<case_id>/deck_metadata.json when --write is provided.',
    'Default mode is dry-run. Existing files are never overwritten.',
  ].join('\n')
}

function parseArgs(argv) {
  const args = {
    runDir: null,
    resolvedRunDir: null,
    caseId: null,
    observedPath: null,
    write: false,
    dryRunExplicit: false,
    overwrite: false,
  }

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index]
    if (arg === '--help' || arg === '-h') {
      console.log(usage())
      process.exit(0)
    }
    if (arg === '--write') {
      args.write = true
      continue
    }
    if (arg === '--dry-run') {
      args.dryRunExplicit = true
      continue
    }
    if (arg === '--overwrite') {
      args.overwrite = true
      continue
    }
    if (['--run-dir', '--case', '--observed'].includes(arg)) {
      const value = argv[index + 1]
      if (!value) {
        throw new Error(`${arg} requires a value`)
      }
      if (arg === '--run-dir') {
        args.runDir = value
        args.resolvedRunDir = path.resolve(value)
      } else if (arg === '--case') {
        args.caseId = value
      } else if (arg === '--observed') {
        args.observedPath = path.resolve(value)
      }
      index += 1
      continue
    }
    throw new Error(`Unknown argument: ${arg}`)
  }

  if (!args.runDir) {
    throw new Error('--run-dir is required')
  }
  if (!args.caseId) {
    throw new Error('--case is required')
  }
  if (!args.observedPath) {
    throw new Error('--observed is required')
  }
  if (!VIDEO_RELEASE_CASES.some((releaseCase) => releaseCase.id === args.caseId)) {
    throw new Error(`Unknown release matrix case: ${args.caseId}`)
  }

  return args
}

function isRecord(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function unique(values) {
  return [...new Set(values)]
}

function firstValue(...values) {
  return values.find((value) => typeof value !== 'undefined')
}

function stringValue(value) {
  return typeof value === 'string' && value.trim() ? value.trim() : ''
}

function stringArrayValue(value) {
  return Array.isArray(value) ? value.filter((item) => typeof item === 'string' && item.trim()) : []
}

function finitePositiveNumber(value) {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? Math.round(value) : null
}

function hasPositiveNumberField(value, key) {
  return finitePositiveNumber(value[key]) !== null
}

function hasSha256Field(value, key) {
  return typeof value[key] === 'string' && /^[a-f0-9]{64}$/i.test(value[key])
}

function sha256Value(value) {
  return typeof value === 'string' && /^[a-f0-9]{64}$/i.test(value.trim()) ? value.trim().toLowerCase() : ''
}

function pathSegments(value) {
  return String(value ?? '')
    .split(/[\\/]+/)
    .filter(Boolean)
}

function normalizeForCompare(filePath) {
  return path.resolve(filePath).replace(/\\/g, '/').replace(/\/$/, '').toLowerCase()
}

function normalizeRelativePath(value) {
  return String(value ?? '')
    .replace(/\\/g, '/')
    .replace(/^\/+/, '')
    .replace(/\/+/g, '/')
    .replace(/\/$/, '')
}

function pathIsInside(childPath, parentPath) {
  const relativePath = path.relative(path.resolve(parentPath), path.resolve(childPath))
  return Boolean(relativePath) && !relativePath.startsWith('..') && !path.isAbsolute(relativePath)
}

function resolveReportedPath(value, runDir) {
  const reported = stringValue(value)
  if (!reported) return ''
  if (path.isAbsolute(reported)) {
    return path.resolve(reported)
  }
  const normalized = normalizeRelativePath(reported)
  if (normalized.toLowerCase().startsWith('cases/')) {
    return path.join(path.resolve(runDir), ...normalized.split('/'))
  }
  return path.resolve(reported)
}

function validateRunDirInput(runDir) {
  const failedChecks = []
  if (!runDir) {
    failedChecks.push('run_dir_missing')
    return failedChecks
  }
  if (!path.isAbsolute(runDir)) {
    failedChecks.push('run_dir_not_absolute')
  }
  if (pathSegments(runDir).some((segment) => segment === '..')) {
    failedChecks.push('run_dir_path_unsafe')
  }
  const runDirName = pathSegments(runDir).at(-1) ?? ''
  if (
    !runDirName.startsWith(VIDEO_RELEASE_RUN_DIR_PREFIX) ||
    !VIDEO_RELEASE_RUN_STAMP_PATTERN.test(runDirName.slice(VIDEO_RELEASE_RUN_DIR_PREFIX.length))
  ) {
    failedChecks.push('run_dir_not_release_hardening_dir')
  }
  return failedChecks
}

async function readJsonDetailed(filePath, missingCheck, invalidCheck) {
  try {
    const content = await readFile(filePath, 'utf8')
    return {
      value: JSON.parse(content.replace(/^\uFEFF/, '')),
      failedChecks: [],
      error: null,
    }
  } catch (error) {
    return {
      value: null,
      failedChecks: [error?.code === 'ENOENT' ? missingCheck : invalidCheck],
      error: error instanceof Error ? error.message : String(error),
    }
  }
}

function summarizeWrite(write) {
  return {
    kind: write.kind,
    relative_path: write.relativePath,
    absolute_path: write.absolutePath,
    write_mode: write.writeMode,
    bytes: Buffer.byteLength(write.content, 'utf8'),
  }
}

async function initializedDirectoryChecks({ runDir, caseDir }) {
  const failedChecks = []
  for (const [name, directoryPath] of [
    ['run_dir', runDir],
    ['case_dir', caseDir],
  ]) {
    try {
      const directoryStat = await stat(directoryPath)
      if (!directoryStat.isDirectory()) {
        failedChecks.push(`${name}_not_directory`)
      }
    } catch (error) {
      failedChecks.push(error?.code === 'ENOENT' ? `${name}_not_found` : `${name}_access_error`)
    }
  }
  if (!pathIsInside(caseDir, runDir)) {
    failedChecks.push('case_dir_outside_run_dir')
  }
  return failedChecks
}

async function existingWriteChecks(writes) {
  const failedChecks = []
  const errors = {}
  for (const write of writes) {
    try {
      await access(write.absolutePath, fsConstants.F_OK)
      failedChecks.push(`${write.kind}_artifact_already_exists`)
    } catch (error) {
      if (error?.code !== 'ENOENT') {
        failedChecks.push(`${write.kind}_artifact_access_error`)
        errors[write.kind] = error instanceof Error ? error.message : String(error)
      }
    }
  }
  return { failedChecks, errors }
}

function looksLikeReleaseEvidenceSummary(value) {
  return (
    Array.isArray(value.stageTimings) &&
    isRecord(value.phaseTotalsMs) &&
    isRecord(value.cache) &&
    isRecord(value.counts) &&
    isRecord(value.ready)
  )
}

function looksLikeWorkerProgress(value) {
  return (
    typeof value.command === 'string' &&
    typeof value.stage === 'string' &&
    typeof value.percent === 'number' &&
    Number.isFinite(value.percent) &&
    typeof value.message === 'string'
  )
}

function looksLikeRustResultSummary(value) {
  return (
    typeof value.command === 'string' &&
    ['learning_point_summary', 'media_summary', 'quality_funnel', 'cards', 'segments', 'apkg_path'].some((key) =>
      Object.hasOwn(value, key),
    )
  )
}

function looksLikeWorkerFinishedEnvelope(value) {
  return typeof value.command === 'string' && (Object.hasOwn(value, 'result_summary') || Object.hasOwn(value, 'result_ref'))
}

function looksLikeGenerationBatchFragment(value) {
  return (
    Array.isArray(value.queueIds) &&
    Array.isArray(value.activeBatchIds) &&
    typeof value.totalBatches === 'number' &&
    typeof value.completedBatches === 'number'
  )
}

function looksLikeWriterHandoffEnvelope(value) {
  return (
    value.schema_kind === 'release_timing_cache_writer_handoff_audit' ||
    value.artifact_kind === 'timing_cache_writer_handoff' ||
    value.handoff_kind === 'timing_cache_writer_dry_run_handoff' ||
    value.evidence_role === 'non_final_writer_handoff' ||
    value.matrix_eligibility === 'never' ||
    Object.hasOwn(value, 'raw_observed_json')
  )
}

function lossyShapeChecks(value) {
  if (!isRecord(value)) return []
  const failedChecks = []
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
  if (looksLikeWriterHandoffEnvelope(value)) {
    failedChecks.push('observed_writer_handoff_not_raw')
  }
  return failedChecks
}

function rawDeckExportChecks(value) {
  if (!isRecord(value)) return ['observed_export_result_missing']
  const failedChecks = []
  if (!stringValue(value.apkg_path)) failedChecks.push('observed_export_apkg_path_missing')
  if (!hasSha256Field(value, 'apkg_sha256')) failedChecks.push('observed_export_apkg_sha256_missing')
  if (!hasPositiveNumberField(value, 'apkg_size_bytes')) failedChecks.push('observed_export_apkg_size_bytes_missing')
  if (!hasPositiveNumberField(value, 'apkg_mtime_ms')) failedChecks.push('observed_export_apkg_mtime_ms_missing')
  if (!hasPositiveNumberField(value, 'cards')) failedChecks.push('observed_export_cards_missing')
  if (!stringValue(value.deck_name)) failedChecks.push('observed_export_deck_name_missing')
  if (!stringValue(value.deck_kind)) failedChecks.push('observed_export_deck_kind_missing')
  if (!stringValue(value.template_version)) failedChecks.push('observed_export_template_version_missing')
  return failedChecks
}

function rawAnkiVerifyChecks(value, verifiedExportApkgPath) {
  if (!isRecord(value)) return ['observed_anki_verify_result_missing']
  const failedChecks = []
  if (value.ok !== true) failedChecks.push('observed_anki_verify_not_ok')
  if (!Array.isArray(value.failed_checks) || value.failed_checks.length > 0) {
    failedChecks.push('observed_anki_verify_failed_checks_present')
  }
  if (!hasPositiveNumberField(value, 'card_count')) failedChecks.push('observed_anki_verify_card_count_missing')
  if (!stringValue(value.deck_name)) failedChecks.push('observed_anki_verify_deck_name_missing')
  if (!hasSha256Field(value, 'apkg_sha256')) failedChecks.push('observed_anki_verify_apkg_sha256_missing')
  if (!hasPositiveNumberField(value, 'apkg_size_bytes')) {
    failedChecks.push('observed_anki_verify_apkg_size_bytes_missing')
  }
  if (!hasPositiveNumberField(value, 'apkg_mtime_ms')) failedChecks.push('observed_anki_verify_apkg_mtime_ms_missing')
  if (!stringValue(verifiedExportApkgPath)) {
    failedChecks.push('observed_verified_export_apkg_path_missing')
  }
  return failedChecks
}

function staleVerifyChecks(exportResult, ankiVerifyResult, verifiedExportApkgPath, runDir) {
  if (!isRecord(exportResult) || !isRecord(ankiVerifyResult)) return []
  const failedChecks = []
  const exportedCards = finitePositiveNumber(exportResult.cards)
  const verifiedCards = finitePositiveNumber(ankiVerifyResult.card_count)
  const expectedCards = finitePositiveNumber(ankiVerifyResult.expected_cards)
  if (exportedCards !== null && verifiedCards !== null && exportedCards !== verifiedCards) {
    failedChecks.push('observed_verify_card_count_mismatch')
  }
  if (exportedCards !== null && expectedCards !== null && exportedCards !== expectedCards) {
    failedChecks.push('observed_verify_expected_cards_mismatch')
  }

  const exportDeck = stringValue(exportResult.deck_name)
  const verifyDeck = stringValue(ankiVerifyResult.deck_name)
  if (exportDeck && verifyDeck && exportDeck !== verifyDeck) {
    failedChecks.push('observed_verify_deck_name_mismatch')
  }

  const exportApkgPath = resolveReportedPath(exportResult.apkg_path, runDir)
  const verifiedApkgPath = resolveReportedPath(verifiedExportApkgPath, runDir)
  const verifyResultApkgPath = resolveReportedPath(ankiVerifyResult.apkg_path, runDir)
  if (exportApkgPath && verifiedApkgPath && normalizeForCompare(exportApkgPath) !== normalizeForCompare(verifiedApkgPath)) {
    failedChecks.push('observed_verify_apkg_path_mismatch')
  }
  if (exportApkgPath && verifyResultApkgPath && normalizeForCompare(exportApkgPath) !== normalizeForCompare(verifyResultApkgPath)) {
    failedChecks.push('observed_verify_result_apkg_path_mismatch')
  }

  const exportApkgSha = sha256Value(exportResult.apkg_sha256)
  const verifyApkgSha = sha256Value(ankiVerifyResult.apkg_sha256)
  if (exportApkgSha && verifyApkgSha && exportApkgSha !== verifyApkgSha) {
    failedChecks.push('observed_verify_apkg_sha256_mismatch')
  }
  const exportApkgSize = finitePositiveNumber(exportResult.apkg_size_bytes)
  const verifyApkgSize = finitePositiveNumber(ankiVerifyResult.apkg_size_bytes)
  if (exportApkgSize !== null && verifyApkgSize !== null && exportApkgSize !== verifyApkgSize) {
    failedChecks.push('observed_verify_apkg_size_bytes_mismatch')
  }
  const exportApkgMtime = finitePositiveNumber(exportResult.apkg_mtime_ms)
  const verifyApkgMtime = finitePositiveNumber(ankiVerifyResult.apkg_mtime_ms)
  if (exportApkgMtime !== null && verifyApkgMtime !== null && exportApkgMtime !== verifyApkgMtime) {
    failedChecks.push('observed_verify_apkg_mtime_ms_mismatch')
  }
  return failedChecks
}

function buildObservedDeckMetadataInputFromJson({ caseId, manifest, rawObserved, runDir }) {
  const rootObserved = isRecord(rawObserved) ? rawObserved : {}
  const failedChecks = []
  if (!isRecord(rawObserved)) {
    failedChecks.push('observed_not_object')
  }
  failedChecks.push(...lossyShapeChecks(rootObserved))

  const observedCaseId = stringValue(firstValue(rootObserved.caseId, rootObserved.case_id))
  if (observedCaseId && observedCaseId !== caseId) {
    failedChecks.push('observed_case_id_mismatch')
  }

  const exportResult = firstValue(rootObserved.exportResult, rootObserved.export_result)
  const ankiVerifyResult = firstValue(rootObserved.ankiVerifyResult, rootObserved.anki_verify_result)
  const verifiedExportApkgPath = stringValue(
    firstValue(
      rootObserved.verifiedExportApkgPath,
      rootObserved.verified_export_apkg_path,
      isRecord(ankiVerifyResult) ? ankiVerifyResult.apkg_path : undefined,
    ),
  )

  failedChecks.push(...lossyShapeChecks(exportResult))
  failedChecks.push(...lossyShapeChecks(ankiVerifyResult))
  failedChecks.push(...rawDeckExportChecks(exportResult))
  failedChecks.push(...rawAnkiVerifyChecks(ankiVerifyResult, verifiedExportApkgPath))
  failedChecks.push(...staleVerifyChecks(exportResult, ankiVerifyResult, verifiedExportApkgPath, runDir))

  const uniqueFailedChecks = unique(failedChecks)
  return {
    ok: uniqueFailedChecks.length === 0,
    status: uniqueFailedChecks.length === 0 ? 'ready_for_write_plan' : 'blocked',
    matrixPassCreated: false,
    failedChecks: uniqueFailedChecks,
    warnings: [],
    observedInput:
      uniqueFailedChecks.length === 0 && isRecord(exportResult) && isRecord(ankiVerifyResult)
        ? {
            caseId,
            manifest,
            exportResult,
            ankiVerifyResult: {
              ...ankiVerifyResult,
              model_names: stringArrayValue(ankiVerifyResult.model_names),
            },
          }
        : null,
    verifiedExportApkgPath,
    notes:
      'Pure raw-observed deck metadata input snapshot only. It accepts raw export and Anki verify objects, rejects lossy summaries, and does not write files, update manifests, create APKG/Anki/Computer Use evidence, or claim a matrix pass.',
  }
}

async function canonicalApkgEvidence({ runDir, caseId }) {
  const apkgDir = path.join(path.resolve(runDir), 'cases', caseId, 'apkg')
  let entries
  try {
    entries = await readdir(apkgDir, { withFileTypes: true })
  } catch (error) {
    return {
      evidence: null,
      failedChecks: [error?.code === 'ENOENT' ? 'deck_metadata_apkg_dir_missing' : 'deck_metadata_apkg_dir_access_error'],
      errors: {
        apkg_dir: error instanceof Error ? error.message : String(error),
      },
    }
  }

  const apkgEntries = entries.filter((entry) => entry.isFile() && entry.name.toLowerCase().endsWith('.apkg'))
  if (apkgEntries.length === 0) {
    return { evidence: null, failedChecks: ['deck_metadata_apkg_missing'], errors: {} }
  }
  if (apkgEntries.length > 1) {
    return { evidence: null, failedChecks: ['deck_metadata_apkg_multiple'], errors: {} }
  }
  if (apkgEntries[0].name.toLowerCase() !== `${caseId.toLowerCase()}.apkg`) {
    return {
      evidence: null,
      failedChecks: ['deck_metadata_apkg_canonical_filename_mismatch'],
      errors: {
        apkg: `Expected ${caseId}.apkg, found ${apkgEntries[0].name}`,
      },
    }
  }

  const absolutePath = path.join(apkgDir, apkgEntries[0].name)
  try {
    const fileStat = await stat(absolutePath)
    if (!fileStat.isFile()) {
      return { evidence: null, failedChecks: ['deck_metadata_apkg_not_file'], errors: {} }
    }
    if (!pathIsInside(absolutePath, apkgDir)) {
      return { evidence: null, failedChecks: ['deck_metadata_apkg_outside_case_dir'], errors: {} }
    }
    const content = await readFile(absolutePath)
    return {
      evidence: {
        absolutePath,
        relativePath: normalizeRelativePath(path.relative(path.resolve(runDir), absolutePath)),
        sha256: createHash('sha256').update(content).digest('hex'),
        sizeBytes: fileStat.size,
        mtimeMs: Math.round(fileStat.mtimeMs),
      },
      failedChecks: [],
      errors: {},
    }
  } catch (error) {
    return {
      evidence: null,
      failedChecks: ['deck_metadata_apkg_read_error'],
      errors: {
        apkg: error instanceof Error ? error.message : String(error),
      },
    }
  }
}

function compareRelativePath(value, expected, check) {
  const reported = stringValue(value)
  if (!reported) return []
  return normalizeRelativePath(reported).toLowerCase() === expected.toLowerCase() ? [] : [check]
}

function compareReportedPathToCanonical(value, runDir, expectedAbsolutePath, check) {
  const reported = resolveReportedPath(value, runDir)
  if (!reported) return []
  return normalizeForCompare(reported) === normalizeForCompare(expectedAbsolutePath) ? [] : [check]
}

function compareSha(value, expected, check) {
  const reported = sha256Value(value)
  if (!reported) return []
  return reported === expected ? [] : [check]
}

function comparePositiveNumber(value, expected, check, tolerance = 0) {
  const reported = finitePositiveNumber(value)
  if (reported === null) return []
  return Math.abs(reported - expected) <= tolerance ? [] : [check]
}

function canonicalApkgIdentityChecks({ observedInput, verifiedExportApkgPath, apkgEvidence, runDir }) {
  if (!observedInput || !apkgEvidence) return []
  const { exportResult, ankiVerifyResult } = observedInput
  return unique([
    ...compareReportedPathToCanonical(exportResult.apkg_path, runDir, apkgEvidence.absolutePath, 'observed_export_apkg_path_not_canonical'),
    ...compareRelativePath(
      exportResult.apkg_relative_path,
      apkgEvidence.relativePath,
      'observed_export_apkg_relative_path_not_canonical',
    ),
    ...compareSha(exportResult.apkg_sha256, apkgEvidence.sha256, 'observed_export_apkg_sha256_not_canonical'),
    ...comparePositiveNumber(exportResult.apkg_size_bytes, apkgEvidence.sizeBytes, 'observed_export_apkg_size_bytes_not_canonical'),
    ...comparePositiveNumber(exportResult.apkg_mtime_ms, apkgEvidence.mtimeMs, 'observed_export_apkg_mtime_ms_not_canonical', 1),
    ...compareReportedPathToCanonical(
      verifiedExportApkgPath,
      runDir,
      apkgEvidence.absolutePath,
      'observed_verified_export_apkg_path_not_canonical',
    ),
    ...compareReportedPathToCanonical(
      ankiVerifyResult.apkg_path,
      runDir,
      apkgEvidence.absolutePath,
      'observed_anki_verify_apkg_path_not_canonical',
    ),
    ...compareRelativePath(
      ankiVerifyResult.apkg_relative_path,
      apkgEvidence.relativePath,
      'observed_anki_verify_apkg_relative_path_not_canonical',
    ),
    ...compareSha(ankiVerifyResult.apkg_sha256, apkgEvidence.sha256, 'observed_anki_verify_apkg_sha256_not_canonical'),
    ...comparePositiveNumber(
      ankiVerifyResult.apkg_size_bytes,
      apkgEvidence.sizeBytes,
      'observed_anki_verify_apkg_size_bytes_not_canonical',
    ),
    ...comparePositiveNumber(
      ankiVerifyResult.apkg_mtime_ms,
      apkgEvidence.mtimeMs,
      'observed_anki_verify_apkg_mtime_ms_not_canonical',
      1,
    ),
  ])
}

function validateCanonicalWritePaths({ writes, runDir, caseId, apkgEvidence }) {
  const failedChecks = []
  const caseDir = path.join(path.resolve(runDir), 'cases', caseId)
  const expectedPath = path.join(caseDir, WRITE_ARTIFACTS.deck_metadata)

  for (const write of writes) {
    if (write.kind !== 'deck_metadata') {
      failedChecks.push('write_artifact_kind_unknown')
      continue
    }
    if (write.writeMode !== 'exclusive_create') {
      failedChecks.push('deck_metadata_write_mode_not_exclusive_create')
    }
    if (normalizeForCompare(write.absolutePath) !== normalizeForCompare(expectedPath)) {
      failedChecks.push('deck_metadata_absolute_path_not_canonical')
    }
    if (!pathIsInside(write.absolutePath, caseDir)) {
      failedChecks.push('deck_metadata_absolute_path_outside_case_dir')
    }
    try {
      const parsed = JSON.parse(write.content)
      if (isRecord(parsed) && Object.hasOwn(parsed, 'matrix_pass_created')) {
        failedChecks.push('deck_metadata_artifact_matrix_pass_field_present')
      }
      if (!isRecord(parsed)) {
        failedChecks.push('deck_metadata_artifact_content_not_object')
      } else {
        if (parsed.case_id !== caseId) failedChecks.push('deck_metadata_artifact_case_id_mismatch')
        if (apkgEvidence) {
          if (parsed.apkg_relative_path !== apkgEvidence.relativePath) {
            failedChecks.push('deck_metadata_artifact_apkg_relative_path_mismatch')
          }
          if (parsed.apkg_sha256 !== apkgEvidence.sha256) {
            failedChecks.push('deck_metadata_artifact_apkg_sha256_mismatch')
          }
          if (parsed.apkg_size_bytes !== apkgEvidence.sizeBytes) {
            failedChecks.push('deck_metadata_artifact_apkg_size_bytes_mismatch')
          }
          if (parsed.apkg_mtime_ms !== apkgEvidence.mtimeMs) {
            failedChecks.push('deck_metadata_artifact_apkg_mtime_ms_mismatch')
          }
        }
      }
    } catch {
      failedChecks.push('deck_metadata_artifact_content_unreadable')
    }
  }

  if (writes.length !== 1) {
    failedChecks.push('write_plan_write_count_mismatch')
  }
  if (!writes.some((write) => write.kind === 'deck_metadata')) {
    failedChecks.push('deck_metadata_write_missing')
  }
  return failedChecks
}

function blockedResult({
  args,
  failedChecks,
  warnings = [],
  readErrors = {},
  plannedWrites = [],
  inputSourceFiles = {},
  notes,
}) {
  const caseDir = args.resolvedRunDir ? path.join(args.resolvedRunDir, 'cases', args.caseId ?? '') : null
  return {
    schema_version: 1,
    created_at: new Date().toISOString(),
    status: 'blocked',
    matrix_pass_created: false,
    case_id: args.caseId,
    run_dir: args.runDir,
    canonical_case_manifest_path: caseDir ? path.join(caseDir, 'case_manifest.json') : null,
    canonical_deck_metadata_path: caseDir ? path.join(caseDir, 'deck_metadata.json') : null,
    observed_path: args.observedPath,
    write_requested: args.write,
    planned_writes: plannedWrites.map(summarizeWrite),
    written_files: [],
    writer: {
      ok: false,
      failed_checks: unique(failedChecks),
      warnings: unique(warnings),
      read_errors: readErrors,
      input_source_files: inputSourceFiles,
    },
    notes,
  }
}

async function buildWriterResult(args) {
  if (args.write && args.dryRunExplicit) {
    return blockedResult({
      args,
      failedChecks: ['write_mode_conflict'],
      notes:
        'Choose either --dry-run or --write. This command did not write deck_metadata.json or create matrix proof.',
    })
  }
  if (args.overwrite) {
    return blockedResult({
      args,
      failedChecks: ['artifact_overwrite_not_supported'],
      notes:
        'Deck metadata proof artifacts are write-once. This command did not overwrite files or create matrix proof.',
    })
  }

  const runDirChecks = validateRunDirInput(args.runDir)
  if (runDirChecks.length > 0) {
    return blockedResult({
      args,
      failedChecks: runDirChecks,
      notes:
        'Run directory guard failed before reading manifests or observed data. This command did not write deck_metadata.json or create matrix proof.',
    })
  }

  const caseDir = path.join(args.resolvedRunDir, 'cases', args.caseId)
  const directoryChecks = await initializedDirectoryChecks({ runDir: args.resolvedRunDir, caseDir })
  if (directoryChecks.length > 0) {
    return blockedResult({
      args,
      failedChecks: directoryChecks,
      notes:
        'Initialized release run/case directories are required. This writer does not create run skeletons, deck_metadata.json, or matrix proof when the case is not initialized.',
    })
  }

  const caseManifestPath = path.join(caseDir, 'case_manifest.json')
  const manifestRead = await readJsonWithSourceFile(caseManifestPath, 'case_manifest_missing', 'case_manifest_unreadable')
  const observedRead = await readJsonWithSourceFile(args.observedPath, 'observed_missing', 'observed_unreadable')
  const readFailedChecks = [...manifestRead.failedChecks, ...observedRead.failedChecks]
  const readErrors = Object.fromEntries(
    [
      ['case_manifest', manifestRead.error],
      ['observed', observedRead.error],
    ].filter(([, error]) => error),
  )

  if (readFailedChecks.length > 0) {
    return blockedResult({
      args,
      failedChecks: readFailedChecks,
      readErrors,
      notes:
        'Required input JSON could not be read. This command did not write deck_metadata.json or create matrix proof.',
    })
  }

  const inputPreflight = await buildWriterInputSourceFilePreflight({
    rawObserved: observedRead.value,
    actualSourceFiles: {
      case_manifest: manifestRead.sourceFile,
      observed_handoff: observedRead.sourceFile,
    },
    requiredKeys: ['case_manifest', 'export_result', 'anki_verify'],
    enforce: true,
  })
  const inputSourceFiles = inputPreflight.inputSourceFiles
  if (inputPreflight.failedChecks.length > 0) {
    return blockedResult({
      args,
      failedChecks: inputPreflight.failedChecks,
      readErrors: {
        ...readErrors,
        ...inputPreflight.readErrors,
      },
      inputSourceFiles,
      notes:
        'Writer input source-file preflight failed. This command did not trust captured raw input, write deck_metadata.json, or create matrix proof.',
    })
  }

  const manifest = isRecord(manifestRead.value) ? manifestRead.value : {}
  const manifestShapeChecks = isRecord(manifestRead.value) ? [] : ['case_manifest_not_object']
  const observed = buildObservedDeckMetadataInputFromJson({
    caseId: args.caseId,
    manifest,
    rawObserved: observedRead.value,
    runDir: args.resolvedRunDir,
  })
  const apkgRead = await canonicalApkgEvidence({ runDir: args.resolvedRunDir, caseId: args.caseId })
  const apkgIdentityChecks = canonicalApkgIdentityChecks({
    observedInput: observed.observedInput,
    verifiedExportApkgPath: observed.verifiedExportApkgPath,
    apkgEvidence: apkgRead.evidence,
    runDir: args.resolvedRunDir,
  })
  const observedFailedChecks = unique([
    ...manifestShapeChecks,
    ...observed.failedChecks,
    ...apkgRead.failedChecks,
    ...apkgIdentityChecks,
  ])

  if (observedFailedChecks.length > 0 || !observed.observedInput || !apkgRead.evidence) {
    return blockedResult({
      args,
      failedChecks: unique([...observedFailedChecks, 'write_plan_empty']),
      warnings: observed.warnings,
      readErrors: apkgRead.errors,
      inputSourceFiles,
      notes:
        'Raw observed deck metadata input or canonical case APKG checks are blocked. This command did not plan writes, write deck_metadata.json, update manifests, or create matrix proof.',
    })
  }

  const exportResult = {
    ...observed.observedInput.exportResult,
    apkg_path: apkgRead.evidence.absolutePath,
    apkg_relative_path: apkgRead.evidence.relativePath,
    apkg_sha256: apkgRead.evidence.sha256,
    apkg_size_bytes: apkgRead.evidence.sizeBytes,
    apkg_mtime_ms: apkgRead.evidence.mtimeMs,
  }
  const ankiVerifyResult = {
    ...observed.observedInput.ankiVerifyResult,
    apkg_path: apkgRead.evidence.absolutePath,
    apkg_relative_path: apkgRead.evidence.relativePath,
    apkg_sha256: apkgRead.evidence.sha256,
    apkg_size_bytes: apkgRead.evidence.sizeBytes,
    apkg_mtime_ms: apkgRead.evidence.mtimeMs,
  }
  const plan = buildReleaseDeckMetadataArtifactWritePlan({
    caseId: args.caseId,
    manifest,
    exportResult,
    ankiVerifyResult,
    runDir: args.runDir,
  })
  const canonicalPathChecks = validateCanonicalWritePaths({
    writes: plan.writes,
    runDir: args.resolvedRunDir,
    caseId: args.caseId,
    apkgEvidence: apkgRead.evidence,
  })
  const plannedWrites = plan.writes
  const failedChecks = unique([...observed.failedChecks, ...plan.failedChecks, ...canonicalPathChecks])
  if (plan.matrixPassCreated !== false) {
    failedChecks.push('write_plan_matrix_pass_created_not_false')
  }
  if (failedChecks.length > 0 || plannedWrites.length === 0) {
    return blockedResult({
      args,
      failedChecks: plannedWrites.length === 0 ? unique([...failedChecks, 'write_plan_empty']) : failedChecks,
      warnings: plan.warnings,
      plannedWrites,
      inputSourceFiles,
      notes:
        'Write plan is blocked. This command did not write deck_metadata.json, update manifests, or create matrix proof.',
    })
  }

  const existingChecks = await existingWriteChecks(plannedWrites)
  if (existingChecks.failedChecks.length > 0) {
    return blockedResult({
      args,
      failedChecks: existingChecks.failedChecks,
      warnings: plan.warnings,
      readErrors: existingChecks.errors,
      plannedWrites,
      inputSourceFiles,
      notes:
        'Exclusive-create preflight refused to overwrite existing deck_metadata.json. This command did not update manifests or create matrix proof.',
    })
  }

  if (!args.write) {
    return {
      schema_version: 1,
      created_at: new Date().toISOString(),
      status: 'ready_to_write',
      matrix_pass_created: false,
      case_id: args.caseId,
      run_dir: args.runDir,
      canonical_case_manifest_path: caseManifestPath,
      canonical_deck_metadata_path: path.join(caseDir, 'deck_metadata.json'),
      canonical_apkg_path: apkgRead.evidence.absolutePath,
      observed_path: args.observedPath,
      write_requested: false,
      planned_writes: plannedWrites.map(summarizeWrite),
      written_files: [],
      writer: {
        ok: true,
        failed_checks: [],
        warnings: unique(plan.warnings),
        read_errors: {},
        input_source_files: inputSourceFiles,
      },
      notes:
        'Dry run only. Re-run with --write to persist deck_metadata.json with exclusive-create semantics. No APKG, Anki, Computer Use, observation, screenshot, manifest, timing/cache, or matrix proof was created.',
    }
  }

  const writtenFiles = []
  for (const write of plannedWrites) {
    try {
      await writeFile(write.absolutePath, write.content, { encoding: 'utf8', flag: 'wx' })
      writtenFiles.push(write.absolutePath)
    } catch (error) {
      return blockedResult({
        args,
        failedChecks: [error?.code === 'EEXIST' ? `${write.kind}_artifact_already_exists` : `${write.kind}_artifact_write_error`],
        warnings: plan.warnings,
        readErrors: {
          [write.kind]: error instanceof Error ? error.message : String(error),
        },
        plannedWrites,
        inputSourceFiles,
        notes:
          'A write failed during exclusive-create persistence. Any written_files listed were created before the failure; no manifest, matrix, APKG, Anki, Computer Use, observation, screenshot, timing/cache, or matrix proof was created.',
      })
    }
  }

  return {
    schema_version: 1,
    created_at: new Date().toISOString(),
    status: 'written',
    matrix_pass_created: false,
    case_id: args.caseId,
    run_dir: args.runDir,
    canonical_case_manifest_path: caseManifestPath,
    canonical_deck_metadata_path: path.join(caseDir, 'deck_metadata.json'),
    canonical_apkg_path: apkgRead.evidence.absolutePath,
    observed_path: args.observedPath,
    write_requested: true,
    planned_writes: plannedWrites.map(summarizeWrite),
    written_files: writtenFiles,
    writer: {
      ok: true,
      failed_checks: [],
      warnings: unique(plan.warnings),
      read_errors: {},
      input_source_files: inputSourceFiles,
    },
    notes:
      'Wrote only deck_metadata.json with exclusive-create semantics. This did not update case manifests, matrix summaries, APKG, Anki, Computer Use, observation, screenshot, timing/cache proof and does not verify a matrix pass.',
  }
}

try {
  const args = parseArgs(process.argv.slice(2))
  const result = await buildWriterResult(args)
  console.log(JSON.stringify(result, null, 2))
  process.exit(result.writer.ok ? 0 : 2)
} catch (error) {
  console.error(error instanceof Error ? error.message : error)
  process.exit(1)
}
