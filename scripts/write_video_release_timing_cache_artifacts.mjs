#!/usr/bin/env node

import { access, mkdir, readFile, stat, writeFile } from 'node:fs/promises'
import path from 'node:path'

import { constants as fsConstants } from 'node:fs'
import {
  VIDEO_RELEASE_CASES,
  VIDEO_RELEASE_RUN_DIR_PREFIX,
  VIDEO_RELEASE_RUN_STAMP_PATTERN,
} from '../src/domain/releaseEvidenceLayout.ts'
import { buildReleaseTimingCacheArtifactWritePlan } from '../src/app/releaseEvidenceArtifacts.ts'
import { buildReleaseObservedTimingCacheInputSnapshotFromJson } from '../src/app/releaseEvidenceObservedInput.ts'
import {
  buildWriterInputSourceFilePreflight,
  readJsonWithSourceFile,
} from './release_input_source_files.mjs'

const WRITE_ARTIFACTS = {
  timing: 'timing.json',
  cache_summary: 'cache_summary.json',
}

const RESERVED_EVIDENCE_FILENAMES = new Set([
  'case_manifest.json',
  'deck_metadata.json',
  'anki_verify.stdout.json',
  'audio_audit.verify.json',
  'timing.json',
  'cache_summary.json',
  'observations.json',
  'computer_use_actions.json',
  'matrix_summary.json',
  'release_risk_report.md',
  'run_observations.md',
])

const RESERVED_EVIDENCE_DIRECTORIES = new Set(['apkg', 'screenshots'])

function usage() {
  return [
    'Usage: node scripts/write_video_release_timing_cache_artifacts.mjs --run-dir PATH --case CASE_ID --observed PATH [--dry-run|--write] [--handoff-output PATH]',
    '',
    'Builds a guarded timing/cache artifact write plan from raw observed release data.',
    'Dry-run is the default. With --write, this command writes only timing.json and cache_summary.json with exclusive-create semantics.',
    'It never updates case manifests, matrix summaries, APKG, Anki, audio, Computer Use, observation, or screenshot proof.',
    '',
    'Options:',
    '  --run-dir PATH                    video_release_hardening_YYYYMMDD_HHMMSS run directory',
    '  --case CASE_ID                    matrix case id, e.g. youtube_a_full1_cold',
    '  --observed PATH                   raw observed JSON with learningPointResult, project, exportResult, ankiVerifyResult',
    '  --dry-run                         validate and print the write plan without writing files',
    '  --write                           persist timing.json and cache_summary.json using write-once exclusive create',
    '  --handoff-output PATH             write a diagnostic dry-run handoff audit JSON; refused with --write',
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
    handoffOutputPath: null,
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
    if (arg === '--overwrite') {
      args.overwrite = true
      continue
    }
    if (arg === '--dry-run') {
      args.dryRunExplicit = true
      continue
    }
    if (['--run-dir', '--case', '--observed', '--handoff-output'].includes(arg)) {
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
      } else if (arg === '--handoff-output') {
        args.handoffOutputPath = path.resolve(value)
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

function pathSegments(value) {
  return String(value ?? '')
    .split(/[\\/]+/)
    .filter(Boolean)
}

function normalizedPathSegments(value) {
  return normalizeForCompare(value).split('/').filter(Boolean)
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

function normalizeForCompare(filePath) {
  return path.resolve(filePath).replace(/\\/g, '/').replace(/\/$/, '').toLowerCase()
}

function pathIsInside(childPath, parentPath) {
  const relativePath = path.relative(path.resolve(parentPath), path.resolve(childPath))
  return Boolean(relativePath) && !relativePath.startsWith('..') && !path.isAbsolute(relativePath)
}

function validateHandoffOutputPath({ outputPath, runDir, caseId }) {
  const failedChecks = []
  if (!outputPath) {
    failedChecks.push('handoff_output_missing')
    return failedChecks
  }
  if (!path.isAbsolute(outputPath)) {
    failedChecks.push('handoff_output_not_absolute')
  }
  if (pathSegments(outputPath).some((segment) => segment === '..')) {
    failedChecks.push('handoff_output_path_unsafe')
  }

  const fileName = path.basename(outputPath).toLowerCase()
  if (!fileName.endsWith('.json')) {
    failedChecks.push('handoff_output_not_json')
  }
  if (!fileName.includes('handoff') || !/(dry[-_]?run|dryrun)/.test(fileName)) {
    failedChecks.push('handoff_output_name_not_explicitly_non_final')
  }
  if (RESERVED_EVIDENCE_FILENAMES.has(fileName)) {
    failedChecks.push('handoff_output_reserved_evidence_filename')
  }

  const segments = normalizedPathSegments(outputPath)
  if (segments.some((segment) => RESERVED_EVIDENCE_DIRECTORIES.has(segment))) {
    failedChecks.push('handoff_output_reserved_evidence_directory')
  }

  const resolvedRunDir = path.resolve(runDir)
  const caseDir = path.join(resolvedRunDir, 'cases', caseId)
  const canonicalFinalEvidencePaths = [
    path.join(resolvedRunDir, 'matrix_summary.json'),
    path.join(resolvedRunDir, 'release_risk_report.md'),
    path.join(resolvedRunDir, 'run_observations.md'),
    path.join(caseDir, 'case_manifest.json'),
    path.join(caseDir, 'deck_metadata.json'),
    path.join(caseDir, 'anki_verify.stdout.json'),
    path.join(caseDir, 'audio_audit.verify.json'),
    path.join(caseDir, 'timing.json'),
    path.join(caseDir, 'cache_summary.json'),
    path.join(caseDir, 'observations.json'),
    path.join(caseDir, 'computer_use_actions.json'),
  ]
  if (canonicalFinalEvidencePaths.some((evidencePath) => normalizeForCompare(evidencePath) === normalizeForCompare(outputPath))) {
    failedChecks.push('handoff_output_matches_final_evidence_path')
  }
  if (pathIsInside(outputPath, caseDir) && !segments.includes('diagnostics')) {
    failedChecks.push('handoff_output_inside_case_without_diagnostics_dir')
  }
  return failedChecks
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

async function readJsonDetailed(filePath, missingCheck, invalidCheck) {
  try {
    const content = await readFile(filePath, 'utf8')
    return {
      value: JSON.parse(content.replace(/^\uFEFF/, '')),
      failedChecks: [],
      error: null,
    }
  } catch (error) {
    const failedChecks = [error?.code === 'ENOENT' ? missingCheck : invalidCheck]
    return {
      value: null,
      failedChecks,
      error: error instanceof Error ? error.message : String(error),
    }
  }
}

function validateCanonicalWritePaths({ writes, runDir, caseId }) {
  const failedChecks = []
  const caseDir = path.join(path.resolve(runDir), 'cases', caseId)
  const expectedPaths = {
    timing: path.join(caseDir, WRITE_ARTIFACTS.timing),
    cache_summary: path.join(caseDir, WRITE_ARTIFACTS.cache_summary),
  }

  for (const write of writes) {
    if (!Object.hasOwn(WRITE_ARTIFACTS, write.kind)) {
      failedChecks.push('write_artifact_kind_unknown')
      continue
    }
    if (write.writeMode !== 'exclusive_create') {
      failedChecks.push(`${write.kind}_write_mode_not_exclusive_create`)
    }
    const expectedPath = expectedPaths[write.kind]
    if (normalizeForCompare(write.absolutePath) !== normalizeForCompare(expectedPath)) {
      failedChecks.push(`${write.kind}_absolute_path_not_canonical`)
    }
    if (!pathIsInside(write.absolutePath, caseDir)) {
      failedChecks.push(`${write.kind}_absolute_path_outside_case_dir`)
    }
    try {
      const parsed = JSON.parse(write.content)
      if (isRecord(parsed) && Object.hasOwn(parsed, 'matrix_pass_created')) {
        failedChecks.push(`${write.kind}_artifact_matrix_pass_field_present`)
      }
    } catch {
      failedChecks.push(`${write.kind}_artifact_content_unreadable`)
    }
  }

  if (writes.length !== 2) {
    failedChecks.push('write_plan_write_count_mismatch')
  }
  if (!writes.some((write) => write.kind === 'timing')) {
    failedChecks.push('timing_write_missing')
  }
  if (!writes.some((write) => write.kind === 'cache_summary')) {
    failedChecks.push('cache_summary_write_missing')
  }
  return failedChecks
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
    observed_path: args.observedPath,
    handoff_output_path: args.handoffOutputPath,
    handoff_written_file: null,
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
  if (args.handoffOutputPath && args.write) {
    return blockedResult({
      args,
      failedChecks: ['handoff_output_requires_dry_run'],
      notes:
        'Diagnostic handoff audits are dry-run only. This command did not write timing/cache artifacts, handoff audit files, or matrix proof.',
    })
  }
  if (args.write && args.dryRunExplicit) {
    return blockedResult({
      args,
      failedChecks: ['write_mode_conflict'],
      notes:
        'Choose either --dry-run or --write. This command did not write timing/cache artifacts or create matrix proof.',
    })
  }
  if (args.overwrite) {
    return blockedResult({
      args,
      failedChecks: ['artifact_overwrite_not_supported'],
      notes:
        'Timing/cache proof artifacts are write-once. This command did not overwrite files or create matrix proof.',
    })
  }

  const runDirChecks = validateRunDirInput(args.runDir)
  if (runDirChecks.length > 0) {
    return blockedResult({
      args,
      failedChecks: runDirChecks,
      notes:
        'Run directory guard failed before reading manifests or observed data. This command did not write timing/cache artifacts or create matrix proof.',
    })
  }

  const caseDir = path.join(args.resolvedRunDir, 'cases', args.caseId)
  const directoryChecks = await initializedDirectoryChecks({ runDir: args.resolvedRunDir, caseDir })
  if (directoryChecks.length > 0) {
    return blockedResult({
      args,
      failedChecks: directoryChecks,
      notes:
        'Initialized release run/case directories are required. This writer does not create run skeletons, timing/cache artifacts, or matrix proof when the case is not initialized.',
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
        'Required input JSON could not be read. This command did not write timing/cache artifacts or create matrix proof.',
    })
  }

  const inputPreflight = await buildWriterInputSourceFilePreflight({
    rawObserved: observedRead.value,
    actualSourceFiles: {
      case_manifest: manifestRead.sourceFile,
      observed_handoff: observedRead.sourceFile,
    },
    requiredKeys: ['case_manifest', 'learning_point', 'project', 'export_result', 'anki_verify'],
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
        'Writer input source-file preflight failed. This command did not trust captured timing/cache raw input, write timing/cache artifacts, or create matrix proof.',
    })
  }

  const observed = buildReleaseObservedTimingCacheInputSnapshotFromJson({
    caseId: args.caseId,
    manifest: isRecord(manifestRead.value) ? manifestRead.value : {},
    rawObserved: observedRead.value,
  })
  if (observed.matrixPassCreated !== false) {
    observed.failedChecks.push('observed_snapshot_matrix_pass_created_not_false')
  }
  if (!observed.ok || !observed.observedInput) {
    return blockedResult({
      args,
      failedChecks: unique([...observed.failedChecks, 'write_plan_empty']),
      warnings: observed.warnings,
      inputSourceFiles,
      notes:
        'Raw observed snapshot is blocked. This command did not plan writes, write timing/cache artifacts, update manifests, or create matrix proof.',
    })
  }
  const plan = buildReleaseTimingCacheArtifactWritePlan({
    ...observed.observedInput,
    runDir: args.runDir,
  })
  if (plan.matrixPassCreated !== false) {
    observed.failedChecks.push('write_plan_matrix_pass_created_not_false')
  }
  const canonicalPathChecks = validateCanonicalWritePaths({
    writes: plan.writes,
    runDir: args.resolvedRunDir,
    caseId: args.caseId,
  })
  const plannedWrites = plan.writes
  const failedChecks = unique([...observed.failedChecks, ...plan.failedChecks, ...canonicalPathChecks])
  if (failedChecks.length > 0 || plannedWrites.length === 0) {
    return blockedResult({
      args,
      failedChecks: plannedWrites.length === 0 ? unique([...failedChecks, 'write_plan_empty']) : failedChecks,
      warnings: plan.warnings,
      plannedWrites,
      inputSourceFiles,
      notes:
        'Write plan is blocked. This command did not write timing/cache artifacts, update manifests, or create matrix proof.',
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
        'Exclusive-create preflight refused to overwrite existing timing/cache artifacts. This command did not update manifests or create matrix proof.',
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
      observed_path: args.observedPath,
      handoff_output_path: args.handoffOutputPath,
      handoff_written_file: null,
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
        'Dry run only. Re-run with --write to persist timing.json and cache_summary.json with exclusive-create semantics. No APKG, Anki, Computer Use, observation, screenshot, manifest, or matrix proof was created.',
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
          'A write failed during exclusive-create persistence. Any written_files listed were created before the failure; no manifest, matrix, APKG, Anki, Computer Use, observation, or screenshot proof was created.',
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
    observed_path: args.observedPath,
    handoff_output_path: args.handoffOutputPath,
    handoff_written_file: null,
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
      'Wrote only timing.json and cache_summary.json with exclusive-create semantics. This did not update case manifests, matrix summaries, APKG, Anki, Computer Use, observation, or screenshot proof and does not verify a matrix pass.',
  }
}

function buildHandoffAudit({ args, writerResult, rawObservedJson }) {
  return {
    schema_version: 1,
    schema_kind: 'release_timing_cache_writer_handoff_audit',
    handoff_kind: 'timing_cache_writer_dry_run_handoff',
    evidence_role: 'non_final_writer_handoff',
    artifact_scope: 'timing_cache_writer_only',
    matrix_eligibility: 'never',
    release_case_evidence: false,
    matrix_pass_verified: false,
    promotion_policy: 'never_satisfies_release_verify_case',
    created_at: new Date().toISOString(),
    status: writerResult.status,
    matrix_pass_created: false,
    case_id: writerResult.case_id,
    run_dir: writerResult.run_dir,
    canonical_case_manifest_path: writerResult.canonical_case_manifest_path,
    observed_path: writerResult.observed_path,
    handoff_output_path: args.handoffOutputPath,
    write_requested: false,
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
    raw_observed_json: rawObservedJson,
    planned_writes: writerResult.planned_writes,
    written_files: [],
    writer: writerResult.writer,
    notes:
      'Durable dry-run writer handoff audit only. Planned writes are summaries without file content. This file is diagnostic evidence and must not be used as timing.json, cache_summary.json, APKG, Anki, Computer Use, observation, screenshot, manifest, or matrix-pass proof.',
  }
}

async function persistHandoffAudit({ args, writerResult }) {
  const outputChecks = validateHandoffOutputPath({
    outputPath: args.handoffOutputPath,
    runDir: args.resolvedRunDir,
    caseId: args.caseId,
  })
  if (outputChecks.length > 0) {
    return {
      ok: false,
      failedChecks: outputChecks,
      outputPath: null,
      error: null,
    }
  }

  const observedRead = await readJsonDetailed(args.observedPath, 'observed_missing', 'observed_unreadable')
  const audit = buildHandoffAudit({
    args,
    writerResult,
    rawObservedJson: observedRead.failedChecks.length === 0 ? observedRead.value : null,
  })
  if (observedRead.failedChecks.length > 0) {
    audit.writer = {
      ...audit.writer,
      failed_checks: unique([...audit.writer.failed_checks, ...observedRead.failedChecks]),
      read_errors: {
        ...audit.writer.read_errors,
        handoff_observed: observedRead.error,
      },
    }
  }
  try {
    await mkdir(path.dirname(args.handoffOutputPath), { recursive: true })
    await writeFile(args.handoffOutputPath, `${JSON.stringify(audit, null, 2)}\n`, { encoding: 'utf8', flag: 'wx' })
    return {
      ok: true,
      failedChecks: [],
      outputPath: args.handoffOutputPath,
      error: null,
    }
  } catch (error) {
    return {
      ok: false,
      failedChecks: [error?.code === 'EEXIST' ? 'handoff_output_already_exists' : 'handoff_output_write_error'],
      outputPath: null,
      error: error instanceof Error ? error.message : String(error),
    }
  }
}

try {
  const args = parseArgs(process.argv.slice(2))
  const result = await buildWriterResult(args)
  if (args.handoffOutputPath && !args.write) {
    const handoffWrite = await persistHandoffAudit({ args, writerResult: result })
    if (handoffWrite.ok) {
      result.handoff_written_file = handoffWrite.outputPath
    } else {
      result.status = 'blocked'
      result.writer.ok = false
      result.writer.failed_checks = unique([...result.writer.failed_checks, ...handoffWrite.failedChecks])
      if (handoffWrite.error) {
        result.writer.read_errors = {
          ...result.writer.read_errors,
          handoff_output: handoffWrite.error,
        }
      }
      result.notes =
        'Diagnostic handoff audit output failed validation or persistence. This command did not write timing/cache artifacts, update manifests, or create matrix proof.'
    }
  }
  console.log(JSON.stringify(result, null, 2))
  process.exit(result.writer.ok ? 0 : 2)
} catch (error) {
  console.error(error instanceof Error ? error.message : error)
  process.exit(1)
}
