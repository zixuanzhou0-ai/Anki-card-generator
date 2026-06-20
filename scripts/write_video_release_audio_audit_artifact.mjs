#!/usr/bin/env node

import { constants as fsConstants } from 'node:fs'
import { access, readFile, stat, writeFile } from 'node:fs/promises'
import path from 'node:path'

import { buildReleaseAudioAuditArtifactWritePlan } from '../src/app/releaseEvidenceAudioAudit.ts'
import {
  VIDEO_RELEASE_CASES,
  VIDEO_RELEASE_RUN_DIR_PREFIX,
  VIDEO_RELEASE_RUN_STAMP_PATTERN,
} from '../src/domain/releaseEvidenceLayout.ts'
import {
  buildWriterInputSourceFilePreflight,
  readJsonWithSourceFile,
} from './release_input_source_files.mjs'

function usage() {
  return [
    'Usage:',
    '  node scripts/write_video_release_audio_audit_artifact.mjs --run-dir PATH --case CASE_ID --observed PATH [--dry-run|--write]',
    '',
    'Writes only cases/<case_id>/audio_audit.verify.json when --write is provided.',
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

function resolveReportedPath(value, baseDir) {
  const reported = stringValue(value)
  if (!reported) return ''
  if (path.isAbsolute(reported)) {
    return path.resolve(reported)
  }
  return path.resolve(baseDir, reported)
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

function summarizeWrite(write) {
  return {
    kind: write.kind,
    relative_path: write.relativePath,
    absolute_path: write.absolutePath,
    write_mode: write.writeMode,
    bytes: Buffer.byteLength(write.content, 'utf8'),
  }
}

function looksLikeReleaseEvidenceSummary(value) {
  return (
    isRecord(value) &&
    Array.isArray(value.stageTimings) &&
    isRecord(value.phaseTotalsMs) &&
    isRecord(value.cache) &&
    isRecord(value.counts)
  )
}

function looksLikeWorkerFinishedEnvelope(value) {
  return isRecord(value) && typeof value.command === 'string' && (Object.hasOwn(value, 'result_summary') || Object.hasOwn(value, 'result_ref'))
}

function looksLikeWriterHandoffEnvelope(value) {
  return (
    isRecord(value) &&
    (value.schema_kind === 'release_timing_cache_writer_handoff_audit' ||
      value.evidence_role === 'non_final_writer_handoff' ||
      value.matrix_eligibility === 'never' ||
      Object.hasOwn(value, 'raw_observed_json'))
  )
}

function lossyShapeChecks(value) {
  const failedChecks = []
  if (looksLikeReleaseEvidenceSummary(value)) {
    failedChecks.push('observed_release_evidence_summary_not_raw')
  }
  if (looksLikeWorkerFinishedEnvelope(value)) {
    failedChecks.push('observed_worker_result_summary_not_raw')
  }
  if (looksLikeWriterHandoffEnvelope(value)) {
    failedChecks.push('observed_writer_handoff_not_raw')
  }
  return failedChecks
}

function hasNoFailures(value) {
  return Array.isArray(value) && value.length === 0
}

function rawAnkiVerifyChecks(value) {
  if (!isRecord(value)) return ['observed_anki_verify_result_missing']
  const failedChecks = []
  if (value.ok !== true) failedChecks.push('observed_anki_verify_not_ok')
  if (!hasNoFailures(value.failed_checks)) failedChecks.push('observed_anki_verify_failed_checks_present')
  if (typeof value.card_count !== 'number' || !Number.isFinite(value.card_count) || value.card_count <= 0) {
    failedChecks.push('observed_anki_verify_card_count_missing')
  }
  if (!stringValue(value.audio_audit_verify_path)) {
    failedChecks.push('observed_anki_verify_audio_audit_verify_path_missing')
  }
  if (!hasNoFailures(value.audio_audit_mismatches)) {
    failedChecks.push('observed_anki_verify_audio_audit_mismatches_present')
  }
  if (!hasNoFailures(value.audio_audit_write_errors)) {
    failedChecks.push('observed_anki_verify_audio_audit_write_errors_present')
  }
  const summary = isRecord(value.audio_audit_summary) ? value.audio_audit_summary : {}
  if (summary.status !== 'passed') {
    failedChecks.push('observed_anki_verify_audio_audit_summary_not_passed')
  }
  return failedChecks
}

function rawExportChecks(value) {
  if (!isRecord(value)) return []
  const failedChecks = []
  if (typeof value.cards !== 'number' || !Number.isFinite(value.cards) || value.cards <= 0) {
    failedChecks.push('observed_export_cards_missing')
  }
  const summary = isRecord(value.audio_audit_summary) ? value.audio_audit_summary : {}
  if (Object.keys(summary).length > 0 && summary.status !== 'passed') {
    failedChecks.push('observed_export_audio_audit_summary_not_passed')
  }
  if (Object.hasOwn(value, 'audio_audit_items') && !Array.isArray(value.audio_audit_items)) {
    failedChecks.push('observed_export_audio_audit_items_not_array')
  }
  return failedChecks
}

function buildObservedAudioAuditInputFromJson({ caseId, manifest, rawObserved, observedPath }) {
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
  failedChecks.push(...lossyShapeChecks(exportResult))
  failedChecks.push(...lossyShapeChecks(ankiVerifyResult))
  failedChecks.push(...rawExportChecks(exportResult))
  failedChecks.push(...rawAnkiVerifyChecks(ankiVerifyResult))

  const auditPath = resolveReportedPath(
    firstValue(
      rootObserved.audioAuditVerifyPath,
      rootObserved.audio_audit_verify_path,
      isRecord(ankiVerifyResult) ? ankiVerifyResult.audio_audit_verify_path : undefined,
    ),
    path.dirname(observedPath),
  )
  if (!auditPath) {
    failedChecks.push('audio_audit_verify_path_missing')
  } else if (path.basename(auditPath).toLowerCase() !== 'audio_audit.verify.json') {
    failedChecks.push('audio_audit_verify_path_not_verify_json')
  }

  return {
    ok: failedChecks.length === 0,
    failedChecks: unique(failedChecks),
    observedInput:
      failedChecks.length === 0 && isRecord(ankiVerifyResult)
        ? {
            caseId,
            manifest,
            exportResult: isRecord(exportResult) ? exportResult : null,
            ankiVerifyResult,
            audioAuditVerifyPath: auditPath,
          }
        : null,
  }
}

function validateCanonicalWritePaths({ writes, runDir, caseId }) {
  const failedChecks = []
  const caseDir = path.join(path.resolve(runDir), 'cases', caseId)
  const expectedPath = path.join(caseDir, 'audio_audit.verify.json')

  if (writes.length !== 1) {
    failedChecks.push('write_plan_write_count_mismatch')
  }
  for (const write of writes) {
    if (write.kind !== 'audio_audit') {
      failedChecks.push('write_artifact_kind_unknown')
      continue
    }
    if (write.writeMode !== 'exclusive_create') {
      failedChecks.push('audio_audit_write_mode_not_exclusive_create')
    }
    if (normalizeForCompare(write.absolutePath) !== normalizeForCompare(expectedPath)) {
      failedChecks.push('audio_audit_absolute_path_not_canonical')
    }
    if (!pathIsInside(write.absolutePath, caseDir)) {
      failedChecks.push('audio_audit_absolute_path_outside_case_dir')
    }
    try {
      const parsed = JSON.parse(write.content)
      if (isRecord(parsed) && (Object.hasOwn(parsed, 'matrix_pass_created') || Object.hasOwn(parsed, 'matrixPassCreated'))) {
        failedChecks.push('audio_audit_artifact_matrix_pass_field_present')
      }
      if (!isRecord(parsed) || !isRecord(parsed.summary) || !Array.isArray(parsed.items)) {
        failedChecks.push('audio_audit_artifact_content_not_payload')
      }
    } catch {
      failedChecks.push('audio_audit_artifact_content_unreadable')
    }
  }
  if (!writes.some((write) => write.kind === 'audio_audit')) {
    failedChecks.push('audio_audit_write_missing')
  }
  return failedChecks
}

function blockedResult({ args, failedChecks, readErrors = {}, plannedWrites = [], inputSourceFiles = {}, notes }) {
  const caseDir = args.resolvedRunDir ? path.join(args.resolvedRunDir, 'cases', args.caseId ?? '') : null
  return {
    schema_version: 1,
    created_at: new Date().toISOString(),
    status: 'blocked',
    matrix_pass_created: false,
    case_id: args.caseId,
    run_dir: args.runDir,
    canonical_case_manifest_path: caseDir ? path.join(caseDir, 'case_manifest.json') : null,
    canonical_audio_audit_path: caseDir ? path.join(caseDir, 'audio_audit.verify.json') : null,
    observed_path: args.observedPath,
    write_requested: args.write,
    planned_writes: plannedWrites.map(summarizeWrite),
    written_files: [],
    writer: {
      ok: false,
      failed_checks: unique(failedChecks),
      warnings: [],
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
        'Choose either --dry-run or --write. This command did not write audio_audit.verify.json or create matrix proof.',
    })
  }
  if (args.overwrite) {
    return blockedResult({
      args,
      failedChecks: ['artifact_overwrite_not_supported'],
      notes:
        'Audio audit proof artifacts are write-once. This command did not overwrite files or create matrix proof.',
    })
  }

  const runDirChecks = validateRunDirInput(args.runDir)
  if (runDirChecks.length > 0) {
    return blockedResult({
      args,
      failedChecks: runDirChecks,
      notes:
        'Run directory guard failed before reading manifests or observed data. This command did not write audio_audit.verify.json or create matrix proof.',
    })
  }

  const caseDir = path.join(args.resolvedRunDir, 'cases', args.caseId)
  const directoryChecks = await initializedDirectoryChecks({ runDir: args.resolvedRunDir, caseDir })
  if (directoryChecks.length > 0) {
    return blockedResult({
      args,
      failedChecks: directoryChecks,
      notes:
        'Initialized release run/case directories are required. This writer does not create run skeletons, audio_audit.verify.json, or matrix proof when the case is not initialized.',
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
        'Required input JSON could not be read. This command did not write audio_audit.verify.json or create matrix proof.',
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
  let inputSourceFiles = inputPreflight.inputSourceFiles
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
        'Writer input source-file preflight failed. This command did not trust captured raw input, write audio_audit.verify.json, or create matrix proof.',
    })
  }

  const manifest = isRecord(manifestRead.value) ? manifestRead.value : {}
  const observed = buildObservedAudioAuditInputFromJson({
    caseId: args.caseId,
    manifest,
    rawObserved: observedRead.value,
    observedPath: args.observedPath,
  })
  if (!observed.ok || !observed.observedInput) {
    return blockedResult({
      args,
      failedChecks: unique([...observed.failedChecks, 'write_plan_empty']),
      inputSourceFiles,
      notes:
        'Raw observed audio audit input is blocked. This command did not plan writes, write audio_audit.verify.json, update manifests, or create matrix proof.',
    })
  }

  const auditRead = await readJsonWithSourceFile(
    observed.observedInput.audioAuditVerifyPath,
    'audio_audit_verify_json_missing',
    'audio_audit_verify_json_unreadable',
  )
  inputSourceFiles = {
    ...inputSourceFiles,
    ...(auditRead.sourceFile ? { audio_audit_verify_json: auditRead.sourceFile } : {}),
  }
  if (auditRead.failedChecks.length > 0) {
    return blockedResult({
      args,
      failedChecks: auditRead.failedChecks,
      readErrors: {
        audio_audit_verify_json: auditRead.error,
      },
      inputSourceFiles,
      notes:
        'The Anki verify audio_audit.verify.json could not be read. This command did not write case-local audio audit proof or create matrix proof.',
    })
  }

  const plan = buildReleaseAudioAuditArtifactWritePlan({
    caseId: args.caseId,
    manifest,
    audioAudit: auditRead.value,
    exportResult: observed.observedInput.exportResult,
    ankiVerifyResult: observed.observedInput.ankiVerifyResult,
    runDir: args.runDir,
  })
  const canonicalPathChecks = validateCanonicalWritePaths({
    writes: plan.writes,
    runDir: args.resolvedRunDir,
    caseId: args.caseId,
  })
  const failedChecks = unique([...plan.failedChecks, ...canonicalPathChecks])
  if (plan.matrixPassCreated !== false) {
    failedChecks.push('write_plan_matrix_pass_created_not_false')
  }
  if (failedChecks.length > 0 || plan.writes.length === 0) {
    return blockedResult({
      args,
      failedChecks: plan.writes.length === 0 ? unique([...failedChecks, 'write_plan_empty']) : failedChecks,
      plannedWrites: plan.writes,
      inputSourceFiles,
      notes:
        'Write plan is blocked. This command did not write audio_audit.verify.json, update manifests, or create matrix proof.',
    })
  }

  const existingChecks = await existingWriteChecks(plan.writes)
  if (existingChecks.failedChecks.length > 0) {
    return blockedResult({
      args,
      failedChecks: existingChecks.failedChecks,
      readErrors: existingChecks.errors,
      plannedWrites: plan.writes,
      inputSourceFiles,
      notes:
        'Exclusive-create preflight refused to overwrite existing audio_audit.verify.json. This command did not update manifests or create matrix proof.',
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
      canonical_audio_audit_path: path.join(caseDir, 'audio_audit.verify.json'),
      source_audio_audit_verify_path: observed.observedInput.audioAuditVerifyPath,
      observed_path: args.observedPath,
      write_requested: false,
      planned_writes: plan.writes.map(summarizeWrite),
      written_files: [],
      writer: {
        ok: true,
        failed_checks: [],
        warnings: [],
        read_errors: {},
        input_source_files: inputSourceFiles,
      },
      notes:
        'Dry run only. Re-run with --write to persist audio_audit.verify.json with exclusive-create semantics. No APKG, Anki, Computer Use, observation, screenshot, manifest, timing/cache, or matrix proof was created.',
    }
  }

  const writtenFiles = []
  for (const write of plan.writes) {
    try {
      await writeFile(write.absolutePath, write.content, { encoding: 'utf8', flag: 'wx' })
      writtenFiles.push(write.absolutePath)
    } catch (error) {
      return blockedResult({
        args,
        failedChecks: [error?.code === 'EEXIST' ? `${write.kind}_artifact_already_exists` : `${write.kind}_artifact_write_error`],
        readErrors: {
          [write.kind]: error instanceof Error ? error.message : String(error),
        },
        plannedWrites: plan.writes,
        inputSourceFiles,
        notes:
          'A write failed during exclusive-create persistence. Any written_files listed were created before the failure; no manifest, matrix, APKG, Anki, Computer Use, observation, screenshot, or timing/cache proof was created.',
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
    canonical_audio_audit_path: path.join(caseDir, 'audio_audit.verify.json'),
    source_audio_audit_verify_path: observed.observedInput.audioAuditVerifyPath,
    observed_path: args.observedPath,
    write_requested: true,
    planned_writes: plan.writes.map(summarizeWrite),
    written_files: writtenFiles,
    writer: {
      ok: true,
      failed_checks: [],
      warnings: [],
      read_errors: {},
      input_source_files: inputSourceFiles,
    },
    notes:
      'Wrote only audio_audit.verify.json with exclusive-create semantics. This did not update case manifests, matrix summaries, APKG, Anki, Computer Use, observation, screenshot, timing/cache proof and does not verify a matrix pass.',
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
