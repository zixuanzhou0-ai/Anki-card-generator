#!/usr/bin/env node

import { createHash } from 'node:crypto'
import { constants as fsConstants } from 'node:fs'
import { access, readFile, readdir, stat, writeFile } from 'node:fs/promises'
import path from 'node:path'

import { buildReleaseComputerUseArtifactWritePlan } from '../src/app/releaseEvidenceComputerUseArtifacts.ts'
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
  observations: 'observations.json',
  computer_use_actions: 'computer_use_actions.json',
}

function usage() {
  return [
    'Usage:',
    '  node scripts/write_video_release_computer_use_artifacts.mjs --run-dir PATH --case CASE_ID --observed PATH [--dry-run|--write]',
    '',
    'Writes only cases/<case_id>/observations.json and computer_use_actions.json when --write is provided.',
    'Default mode is dry-run. Existing files are never overwritten.',
    'This command requires canonical cases/<case_id>/screenshots/manifest.json and hashes case screenshot image files before planning writes.',
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

function stringValue(value) {
  return typeof value === 'string' && value.trim() ? value.trim() : ''
}

function numberValue(value) {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function arrayValue(value) {
  return Array.isArray(value) ? value : []
}

function firstValue(...values) {
  return values.find((value) => typeof value !== 'undefined')
}

function firstStringValue(source, keys) {
  for (const key of keys) {
    const value = stringValue(source[key])
    if (value) return value
  }
  return ''
}

function firstNumberValue(source, keys) {
  for (const key of keys) {
    const value = numberValue(source[key])
    if (value !== null) return value
  }
  return null
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

function runRelativePath(runDir, filePath) {
  return path.relative(path.resolve(runDir), path.resolve(filePath)).split(path.sep).join('/')
}

function pathIsInside(childPath, parentPath) {
  const relativePath = path.relative(path.resolve(parentPath), path.resolve(childPath))
  return Boolean(relativePath) && !relativePath.startsWith('..') && !path.isAbsolute(relativePath)
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

async function initializedDirectoryChecks({ runDir, caseDir, screenshotsDir }) {
  const failedChecks = []
  for (const [name, directoryPath] of [
    ['run_dir', runDir],
    ['case_dir', caseDir],
    ['screenshots_dir', screenshotsDir],
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
  if (!pathIsInside(screenshotsDir, caseDir)) {
    failedChecks.push('screenshots_dir_outside_case_dir')
  }
  return failedChecks
}

async function fileSha256(filePath) {
  const digest = createHash('sha256')
  digest.update(await readFile(filePath))
  return digest.digest('hex')
}

async function listScreenshotEvidence(runDir, screenshotsDir) {
  try {
    const entries = await readdir(screenshotsDir, { withFileTypes: true })
    const files = []
    for (const entry of entries.filter((item) => item.isFile() && /\.(png|jpe?g|webp)$/i.test(item.name))) {
      const absolutePath = path.join(screenshotsDir, entry.name)
      const fileStat = await stat(absolutePath)
      files.push({
        path: absolutePath,
        relative_path: runRelativePath(runDir, absolutePath),
        sha256: await fileSha256(absolutePath),
        size_bytes: fileStat.size,
        mtime_ms: Math.round(fileStat.mtimeMs),
      })
    }
    return { files, failedChecks: [], errors: {} }
  } catch (error) {
    return {
      files: [],
      failedChecks: [error?.code === 'ENOENT' ? 'screenshots_dir_not_found' : 'screenshots_dir_read_error'],
      errors: {
        screenshots_dir: error instanceof Error ? error.message : String(error),
      },
    }
  }
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

function looksLikeWriterHandoffEnvelope(value) {
  return (
    value.schema_kind === 'release_timing_cache_writer_handoff_audit' ||
    value.artifact_kind === 'timing_cache_writer_handoff' ||
    value.evidence_role === 'non_final_writer_handoff' ||
    value.matrix_eligibility === 'never' ||
    Object.hasOwn(value, 'raw_observed_json')
  )
}

function looksLikeWorkerProgress(value) {
  return (
    typeof value.command === 'string' &&
    typeof value.stage === 'string' &&
    typeof value.percent === 'number' &&
    typeof value.message === 'string'
  )
}

function lossyShapeChecks(value) {
  if (!isRecord(value)) return []
  const failedChecks = []
  if (looksLikeWriterHandoffEnvelope(value)) {
    failedChecks.push('observed_writer_handoff_not_raw')
  }
  if (looksLikeWorkerProgress(value)) {
    failedChecks.push('observed_worker_progress_not_raw')
  }
  return failedChecks
}

function rowsFromObserved(rootObserved, key) {
  const direct = rootObserved[key]
  if (Array.isArray(direct)) {
    return direct.filter(isRecord)
  }
  if (isRecord(direct)) {
    const nestedRows = arrayValue(direct[key === 'observations' ? 'observations' : 'actions']).filter(isRecord)
    if (nestedRows.length > 0) {
      return nestedRows
    }
  }
  const camelKey = key === 'observations' ? 'observationRows' : 'computerUseActionRows'
  const snakeKey = key === 'observations' ? 'observation_rows' : 'computer_use_action_rows'
  return arrayValue(firstValue(rootObserved[camelKey], rootObserved[snakeKey])).filter(isRecord)
}

function buildObservedComputerUseInputFromJson({ caseId, manifest, rawObserved, screenshotManifest, screenshotFiles }) {
  const rootObserved = isRecord(rawObserved) ? rawObserved : {}
  const observedComputerUseActions = isRecord(rootObserved.computer_use_actions)
    ? rootObserved.computer_use_actions
    : isRecord(rootObserved.computerUseActions)
      ? rootObserved.computerUseActions
      : {}
  const observedObservations = isRecord(rootObserved.observations) ? rootObserved.observations : {}
  const failedChecks = []
  if (!isRecord(rawObserved)) {
    failedChecks.push('observed_not_object')
  }
  failedChecks.push(...lossyShapeChecks(rootObserved))

  const observedCaseId = stringValue(firstValue(rootObserved.caseId, rootObserved.case_id))
  if (observedCaseId && observedCaseId !== caseId) {
    failedChecks.push('observed_case_id_mismatch')
  }

  const sessionId = firstStringValue(
    {
      ...rootObserved,
      ...observedObservations,
      ...observedComputerUseActions,
    },
    ['session_id', 'sessionId', 'computer_use_session_id', 'computerUseSessionId'],
  )
  if (!sessionId) {
    failedChecks.push('observed_computer_use_session_id_missing')
  }

  const observations = rowsFromObserved(rootObserved, 'observations')
  const computerUseActions = rowsFromObserved(rootObserved, 'computer_use_actions')
  if (observations.length === 0) {
    failedChecks.push('observed_observations_missing')
  }
  if (computerUseActions.length === 0) {
    failedChecks.push('observed_computer_use_actions_missing')
  }

  const previewedCards = firstNumberValue(
    {
      ...rootObserved,
      ...observedObservations,
      ...observedComputerUseActions,
    },
    ['previewed_cards', 'observed_cards', 'count'],
  )
  const generationClicks = firstNumberValue(
    {
      ...rootObserved,
      ...observedComputerUseActions,
    },
    ['generation_clicks', 'generate_clicks', 'primary_generate_clicks'],
  )

  const uniqueFailedChecks = unique(failedChecks)
  return {
    ok: uniqueFailedChecks.length === 0,
    failedChecks: uniqueFailedChecks,
    warnings: [],
    observedInput:
      uniqueFailedChecks.length === 0
        ? {
            caseId,
            manifest,
            sessionId,
            observations,
            computerUseActions,
            screenshotManifest,
            screenshotFiles,
            previewedCards: previewedCards ?? undefined,
            generationClicks: generationClicks ?? undefined,
          }
        : null,
    notes:
      'Pure raw-observed Computer Use input snapshot only. It accepts raw observations/action rows, rejects handoff/progress envelopes, and does not write files, create screenshots, update manifests, or claim a matrix pass.',
  }
}

function validateCanonicalWritePaths({ writes, runDir, caseId }) {
  const failedChecks = []
  const caseDir = path.join(path.resolve(runDir), 'cases', caseId)
  const expectedPaths = {
    observations: path.join(caseDir, WRITE_ARTIFACTS.observations),
    computer_use_actions: path.join(caseDir, WRITE_ARTIFACTS.computer_use_actions),
  }
  const expectedKinds = Object.keys(expectedPaths)

  for (const write of writes) {
    if (!expectedKinds.includes(write.kind)) {
      failedChecks.push('write_artifact_kind_unknown')
      continue
    }
    if (write.writeMode !== 'exclusive_create') {
      failedChecks.push(`${write.kind}_write_mode_not_exclusive_create`)
    }
    if (normalizeForCompare(write.absolutePath) !== normalizeForCompare(expectedPaths[write.kind])) {
      failedChecks.push(`${write.kind}_absolute_path_not_canonical`)
    }
    if (normalizeRelativePath(write.relativePath) !== normalizeRelativePath(path.relative(path.resolve(runDir), expectedPaths[write.kind]))) {
      failedChecks.push(`${write.kind}_relative_path_not_canonical`)
    }
    if (!pathIsInside(write.absolutePath, caseDir)) {
      failedChecks.push(`${write.kind}_absolute_path_outside_case_dir`)
    }
    try {
      const parsed = JSON.parse(write.content)
      if (!isRecord(parsed)) {
        failedChecks.push(`${write.kind}_artifact_content_not_object`)
      } else {
        if (Object.hasOwn(parsed, 'matrix_pass_created')) {
          failedChecks.push(`${write.kind}_artifact_matrix_pass_field_present`)
        }
        if (parsed.case_id !== caseId) {
          failedChecks.push(`${write.kind}_artifact_case_id_mismatch`)
        }
      }
    } catch {
      failedChecks.push(`${write.kind}_artifact_content_unreadable`)
    }
  }

  if (writes.length !== 2) {
    failedChecks.push('write_plan_write_count_mismatch')
  }
  for (const kind of expectedKinds) {
    if (!writes.some((write) => write.kind === kind)) {
      failedChecks.push(`${kind}_write_missing`)
    }
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
  const screenshotsDir = caseDir ? path.join(caseDir, 'screenshots') : null
  return {
    schema_version: 1,
    created_at: new Date().toISOString(),
    status: 'blocked',
    matrix_pass_created: false,
    case_id: args.caseId,
    run_dir: args.runDir,
    canonical_case_manifest_path: caseDir ? path.join(caseDir, 'case_manifest.json') : null,
    canonical_observations_path: caseDir ? path.join(caseDir, 'observations.json') : null,
    canonical_computer_use_actions_path: caseDir ? path.join(caseDir, 'computer_use_actions.json') : null,
    canonical_screenshot_manifest_path: screenshotsDir ? path.join(screenshotsDir, 'manifest.json') : null,
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
        'Choose either --dry-run or --write. This command did not write observations/actions artifacts or create matrix proof.',
    })
  }
  if (args.overwrite) {
    return blockedResult({
      args,
      failedChecks: ['artifact_overwrite_not_supported'],
      notes:
        'Computer Use proof artifacts are write-once. This command did not overwrite files or create matrix proof.',
    })
  }

  const runDirChecks = validateRunDirInput(args.runDir)
  if (runDirChecks.length > 0) {
    return blockedResult({
      args,
      failedChecks: runDirChecks,
      notes:
        'Run directory guard failed before reading manifests or observed data. This command did not write observations/actions artifacts or create matrix proof.',
    })
  }

  const caseDir = path.join(args.resolvedRunDir, 'cases', args.caseId)
  const screenshotsDir = path.join(caseDir, 'screenshots')
  const directoryChecks = await initializedDirectoryChecks({
    runDir: args.resolvedRunDir,
    caseDir,
    screenshotsDir,
  })
  if (directoryChecks.length > 0) {
    return blockedResult({
      args,
      failedChecks: directoryChecks,
      notes:
        'Initialized release run/case/screenshots directories are required. This writer does not create run skeletons, observations/actions artifacts, screenshots, or matrix proof when the case is not initialized.',
    })
  }

  const caseManifestPath = path.join(caseDir, 'case_manifest.json')
  const screenshotManifestPath = path.join(screenshotsDir, 'manifest.json')
  const manifestRead = await readJsonWithSourceFile(caseManifestPath, 'case_manifest_missing', 'case_manifest_unreadable')
  const observedRead = await readJsonWithSourceFile(args.observedPath, 'observed_missing', 'observed_unreadable')
  const screenshotManifestRead = await readJsonWithSourceFile(
    screenshotManifestPath,
    'screenshot_manifest_missing',
    'screenshot_manifest_unreadable',
  )
  const screenshotEvidence = await listScreenshotEvidence(args.resolvedRunDir, screenshotsDir)
  const readFailedChecks = [
    ...manifestRead.failedChecks,
    ...observedRead.failedChecks,
    ...screenshotManifestRead.failedChecks,
    ...screenshotEvidence.failedChecks,
  ]
  const readErrors = Object.fromEntries(
    [
      ['case_manifest', manifestRead.error],
      ['observed', observedRead.error],
      ['screenshot_manifest', screenshotManifestRead.error],
      ...Object.entries(screenshotEvidence.errors),
    ].filter(([, error]) => error),
  )

  if (readFailedChecks.length > 0) {
    return blockedResult({
      args,
      failedChecks: readFailedChecks,
      readErrors,
      notes:
        'Required input JSON or screenshot evidence could not be read. This command did not write observations/actions artifacts or create matrix proof.',
    })
  }

  const inputPreflight = await buildWriterInputSourceFilePreflight({
    rawObserved: observedRead.value,
    actualSourceFiles: {
      case_manifest: manifestRead.sourceFile,
      observed_handoff: observedRead.sourceFile,
      screenshot_manifest: screenshotManifestRead.sourceFile,
    },
    requiredKeys: ['computer_use'],
    singularSourceFileKey: 'computer_use',
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
        'Writer input source-file preflight failed. This command did not trust captured Computer Use raw input, write observations/actions artifacts, or create matrix proof.',
    })
  }

  const manifest = isRecord(manifestRead.value) ? manifestRead.value : {}
  const manifestShapeChecks = isRecord(manifestRead.value) ? [] : ['case_manifest_not_object']
  const screenshotManifest = isRecord(screenshotManifestRead.value) ? screenshotManifestRead.value : {}
  const screenshotManifestShapeChecks = isRecord(screenshotManifestRead.value) ? [] : ['screenshot_manifest_not_object']
  const observed = buildObservedComputerUseInputFromJson({
    caseId: args.caseId,
    manifest,
    rawObserved: observedRead.value,
    screenshotManifest,
    screenshotFiles: screenshotEvidence.files,
  })
  const observedFailedChecks = unique([
    ...manifestShapeChecks,
    ...screenshotManifestShapeChecks,
    ...observed.failedChecks,
  ])
  if (observedFailedChecks.length > 0 || !observed.observedInput) {
    return blockedResult({
      args,
      failedChecks: unique([...observedFailedChecks, 'write_plan_empty']),
      warnings: observed.warnings,
      inputSourceFiles,
      notes:
        'Raw observed Computer Use input is blocked. This command did not plan writes, write observations/actions artifacts, update manifests, or create matrix proof.',
    })
  }

  const plan = buildReleaseComputerUseArtifactWritePlan({
    ...observed.observedInput,
    runDir: args.runDir,
  })
  const canonicalPathChecks = validateCanonicalWritePaths({
    writes: plan.writes,
    runDir: args.resolvedRunDir,
    caseId: args.caseId,
  })
  const plannedWrites = plan.writes
  const failedChecks = unique([...plan.failedChecks, ...canonicalPathChecks])
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
        'Write plan is blocked. This command did not write observations/actions artifacts, update manifests, or create matrix proof.',
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
        'Exclusive-create preflight refused to overwrite existing observations/actions artifacts. This command did not update manifests or create matrix proof.',
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
      canonical_observations_path: path.join(caseDir, 'observations.json'),
      canonical_computer_use_actions_path: path.join(caseDir, 'computer_use_actions.json'),
      canonical_screenshot_manifest_path: screenshotManifestPath,
      observed_path: args.observedPath,
      screenshot_files: screenshotEvidence.files,
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
        'Dry run only. Re-run with --write to persist observations.json and computer_use_actions.json with exclusive-create semantics. No screenshots, screenshot manifest, APKG, Anki, audio audit, timing/cache, source/deck proof, or matrix proof was created.',
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
        failedChecks: [
          error?.code === 'EEXIST' ? `${write.kind}_artifact_already_exists` : `${write.kind}_artifact_write_error`,
        ],
        warnings: plan.warnings,
        readErrors: {
          [write.kind]: error instanceof Error ? error.message : String(error),
        },
        plannedWrites,
        inputSourceFiles,
        notes:
          'A write failed during exclusive-create persistence. Any written_files listed were created before the failure; no screenshots, screenshot manifest, APKG, Anki, audio audit, timing/cache, source/deck proof, or matrix proof was created.',
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
    canonical_observations_path: path.join(caseDir, 'observations.json'),
    canonical_computer_use_actions_path: path.join(caseDir, 'computer_use_actions.json'),
    canonical_screenshot_manifest_path: screenshotManifestPath,
    observed_path: args.observedPath,
    screenshot_files: screenshotEvidence.files,
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
      'Wrote only observations.json and computer_use_actions.json with exclusive-create semantics. This did not create screenshots, update screenshot manifests, update case manifests, update matrix summaries, create APKG, import/verify Anki, write audio/timing/cache/source/deck proof, or verify a matrix pass.',
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
