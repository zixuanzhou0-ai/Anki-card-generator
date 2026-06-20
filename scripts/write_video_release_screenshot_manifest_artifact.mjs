#!/usr/bin/env node

import { createHash } from 'node:crypto'
import { constants as fsConstants } from 'node:fs'
import { access, readFile, readdir, stat, writeFile } from 'node:fs/promises'
import path from 'node:path'

import { buildReleaseScreenshotManifestArtifactWritePlan } from '../src/app/releaseEvidenceScreenshotArtifacts.ts'
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
    '  node scripts/write_video_release_screenshot_manifest_artifact.mjs --run-dir PATH --case CASE_ID --observed PATH [--dry-run|--write]',
    '',
    'Writes only cases/<case_id>/screenshots/manifest.json when --write is provided.',
    'Default mode is dry-run. Existing files are never overwritten.',
    'Screenshot image files must already exist directly under cases/<case_id>/screenshots/; this command hashes them but does not capture or copy screenshots.',
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

async function listCanonicalScreenshotFiles(runDir, screenshotsDir) {
  try {
    const entries = await readdir(screenshotsDir, { withFileTypes: true })
    const files = []
    for (const entry of entries.filter((item) => item.isFile() && /\.(png|jpe?g|webp)$/i.test(item.name))) {
      const absolutePath = path.join(screenshotsDir, entry.name)
      const fileStat = await stat(absolutePath)
      files.push({
        absolutePath,
        fileName: entry.name,
        relativePath: runRelativePath(runDir, absolutePath),
        sha256: await fileSha256(absolutePath),
        sizeBytes: fileStat.size,
        mtimeMs: Math.round(fileStat.mtimeMs),
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
    isRecord(value) &&
    (value.schema_kind === 'release_timing_cache_writer_handoff_audit' ||
      value.evidence_role === 'non_final_writer_handoff' ||
      value.matrix_eligibility === 'never' ||
      Object.hasOwn(value, 'raw_observed_json'))
  )
}

function looksLikeWorkerProgress(value) {
  return (
    isRecord(value) &&
    typeof value.command === 'string' &&
    typeof value.stage === 'string' &&
    typeof value.percent === 'number' &&
    typeof value.message === 'string'
  )
}

function lossyShapeChecks(value) {
  const failedChecks = []
  if (looksLikeWriterHandoffEnvelope(value)) {
    failedChecks.push('observed_writer_handoff_not_raw')
  }
  if (looksLikeWorkerProgress(value)) {
    failedChecks.push('observed_worker_progress_not_raw')
  }
  return failedChecks
}

function screenshotRowsFromObserved(rootObserved) {
  const directRows = [
    ...arrayValue(rootObserved.screenshots),
    ...arrayValue(rootObserved.files),
    ...arrayValue(rootObserved.items),
    ...arrayValue(rootObserved.screenshot_files),
    ...arrayValue(rootObserved.screenshotFiles),
  ]
  if (directRows.length > 0) {
    return directRows.filter(isRecord)
  }
  for (const key of ['screenshot_manifest', 'screenshotManifest', 'screenshots_manifest', 'screenshotsManifest']) {
    const nested = rootObserved[key]
    const nestedRecord = isRecord(nested) ? nested : {}
    const rows = [
      ...arrayValue(nestedRecord.screenshots),
      ...arrayValue(nestedRecord.files),
      ...arrayValue(nestedRecord.items),
    ].filter(isRecord)
    if (rows.length > 0) {
      return rows
    }
  }
  return []
}

function rawSessionId(rootObserved) {
  const nested = isRecord(rootObserved.screenshot_manifest)
    ? rootObserved.screenshot_manifest
    : isRecord(rootObserved.screenshotManifest)
      ? rootObserved.screenshotManifest
      : {}
  return firstStringValue({ ...rootObserved, ...nested }, [
    'session_id',
    'sessionId',
    'computer_use_session_id',
    'computerUseSessionId',
  ])
}

function observedScreenshotPath(row) {
  return firstStringValue(row, [
    'path',
    'absolute_path',
    'absolutePath',
    'file',
    'filename',
    'name',
    'relative_path',
    'relativePath',
    'screenshot',
    'screenshot_file',
    'screenshot_path',
  ])
}

function resolveScreenshotPath({ row, runDir, screenshotsDir }) {
  const reported = observedScreenshotPath(row)
  if (!reported) {
    return ''
  }
  if (path.isAbsolute(reported)) {
    return path.resolve(reported)
  }
  const normalized = normalizeRelativePath(reported)
  if (normalized.toLowerCase().startsWith('cases/')) {
    return path.resolve(runDir, normalized)
  }
  return path.resolve(screenshotsDir, reported)
}

function screenshotFileForRow({ row, files, runDir, screenshotsDir }) {
  const resolved = resolveScreenshotPath({ row, runDir, screenshotsDir })
  if (!resolved) {
    return null
  }
  return files.find((file) => normalizeForCompare(file.absolutePath) === normalizeForCompare(resolved)) ?? null
}

function buildObservedScreenshotInputFromJson({ caseId, manifest, rawObserved, runDir, screenshotsDir, files }) {
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

  const sessionId = rawSessionId(rootObserved)
  if (!sessionId) {
    failedChecks.push('observed_screenshot_session_id_missing')
  }

  const rows = screenshotRowsFromObserved(rootObserved)
  if (rows.length === 0) {
    failedChecks.push('observed_screenshots_missing')
  }

  const screenshots = []
  for (const row of rows) {
    const resolved = resolveScreenshotPath({ row, runDir, screenshotsDir })
    if (!resolved) {
      failedChecks.push('observed_screenshot_path_missing')
      continue
    }
    if (!pathIsInside(resolved, screenshotsDir)) {
      failedChecks.push('observed_screenshot_path_outside_screenshots_dir')
      continue
    }
    const file = screenshotFileForRow({ row, files, runDir, screenshotsDir })
    if (!file) {
      failedChecks.push('observed_screenshot_file_not_found')
      continue
    }
    screenshots.push({
      ...row,
      path: file.absolutePath,
      relative_path: file.relativePath,
      filename: file.fileName,
      sha256: file.sha256,
      size_bytes: file.sizeBytes,
      mtime_ms: file.mtimeMs,
    })
  }

  const uniqueFailedChecks = unique(failedChecks)
  return {
    ok: uniqueFailedChecks.length === 0,
    failedChecks: uniqueFailedChecks,
    observedInput:
      uniqueFailedChecks.length === 0
        ? {
            caseId,
            manifest,
            sessionId,
            screenshots,
          }
        : null,
    notes:
      'Pure raw observed screenshot input only. It accepts raw screenshot rows and actual hashed case-local image files, rejects handoff/progress envelopes, and does not write files, create screenshots, or claim a matrix pass.',
  }
}

function validateCanonicalWritePaths({ writes, runDir, caseId }) {
  const failedChecks = []
  const screenshotsDir = path.join(path.resolve(runDir), 'cases', caseId, 'screenshots')
  const expectedPath = path.join(screenshotsDir, 'manifest.json')

  if (writes.length !== 1) {
    failedChecks.push('write_plan_write_count_mismatch')
  }
  for (const write of writes) {
    if (write.kind !== 'screenshot_manifest') {
      failedChecks.push('write_artifact_kind_unknown')
      continue
    }
    if (write.writeMode !== 'exclusive_create') {
      failedChecks.push('screenshot_manifest_write_mode_not_exclusive_create')
    }
    if (normalizeForCompare(write.absolutePath) !== normalizeForCompare(expectedPath)) {
      failedChecks.push('screenshot_manifest_absolute_path_not_canonical')
    }
    if (!pathIsInside(write.absolutePath, screenshotsDir)) {
      failedChecks.push('screenshot_manifest_absolute_path_outside_screenshots_dir')
    }
    try {
      const parsed = JSON.parse(write.content)
      if (!isRecord(parsed)) {
        failedChecks.push('screenshot_manifest_artifact_content_not_object')
      } else {
        if (Object.hasOwn(parsed, 'matrix_pass_created') || Object.hasOwn(parsed, 'matrixPassCreated')) {
          failedChecks.push('screenshot_manifest_artifact_matrix_pass_field_present')
        }
        if (parsed.case_id !== caseId) {
          failedChecks.push('screenshot_manifest_artifact_case_id_mismatch')
        }
        if (parsed.schema_version !== 1 || !Array.isArray(parsed.screenshots)) {
          failedChecks.push('screenshot_manifest_artifact_content_not_payload')
        }
      }
    } catch {
      failedChecks.push('screenshot_manifest_artifact_content_unreadable')
    }
  }
  if (!writes.some((write) => write.kind === 'screenshot_manifest')) {
    failedChecks.push('screenshot_manifest_write_missing')
  }
  return failedChecks
}

function blockedResult({ args, failedChecks, readErrors = {}, plannedWrites = [], inputSourceFiles = {}, notes }) {
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
    canonical_screenshot_manifest_path: screenshotsDir ? path.join(screenshotsDir, 'manifest.json') : null,
    screenshots_dir: screenshotsDir,
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
        'Choose either --dry-run or --write. This command did not write screenshots/manifest.json or create matrix proof.',
    })
  }
  if (args.overwrite) {
    return blockedResult({
      args,
      failedChecks: ['artifact_overwrite_not_supported'],
      notes:
        'Screenshot manifest proof artifacts are write-once. This command did not overwrite files or create matrix proof.',
    })
  }

  const runDirChecks = validateRunDirInput(args.runDir)
  if (runDirChecks.length > 0) {
    return blockedResult({
      args,
      failedChecks: runDirChecks,
      notes:
        'Run directory guard failed before reading manifests or observed data. This command did not write screenshots/manifest.json or create matrix proof.',
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
        'Initialized release run/case/screenshots directories are required. This writer does not create run skeletons, screenshots, screenshots/manifest.json, or matrix proof when the case is not initialized.',
    })
  }

  const caseManifestPath = path.join(caseDir, 'case_manifest.json')
  const targetManifestPath = path.join(screenshotsDir, 'manifest.json')
  const manifestRead = await readJsonWithSourceFile(caseManifestPath, 'case_manifest_missing', 'case_manifest_unreadable')
  const observedRead = await readJsonWithSourceFile(args.observedPath, 'observed_missing', 'observed_unreadable')
  const screenshotFiles = await listCanonicalScreenshotFiles(args.resolvedRunDir, screenshotsDir)
  const readFailedChecks = [
    ...manifestRead.failedChecks,
    ...observedRead.failedChecks,
    ...screenshotFiles.failedChecks,
  ]
  const readErrors = Object.fromEntries(
    [
      ['case_manifest', manifestRead.error],
      ['observed', observedRead.error],
      ...Object.entries(screenshotFiles.errors),
    ].filter(([, error]) => error),
  )

  if (readFailedChecks.length > 0) {
    return blockedResult({
      args,
      failedChecks: readFailedChecks,
      readErrors,
      notes:
        'Required input JSON or screenshot files could not be read. This command did not write screenshots/manifest.json or create matrix proof.',
    })
  }

  const inputPreflight = await buildWriterInputSourceFilePreflight({
    rawObserved: observedRead.value,
    actualSourceFiles: {
      case_manifest: manifestRead.sourceFile,
      observed_handoff: observedRead.sourceFile,
    },
    requiredKeys: ['screenshots'],
    singularSourceFileKey: 'screenshots',
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
        'Writer input source-file preflight failed. This command did not trust captured screenshot raw input, write screenshots/manifest.json, or create matrix proof.',
    })
  }

  const manifest = isRecord(manifestRead.value) ? manifestRead.value : {}
  const observed = buildObservedScreenshotInputFromJson({
    caseId: args.caseId,
    manifest,
    rawObserved: observedRead.value,
    runDir: args.resolvedRunDir,
    screenshotsDir,
    files: screenshotFiles.files,
  })
  if (!observed.ok || !observed.observedInput) {
    return blockedResult({
      args,
      failedChecks: unique([...observed.failedChecks, 'write_plan_empty']),
      inputSourceFiles,
      notes:
        'Raw observed screenshot input is blocked. This command did not plan writes, write screenshots/manifest.json, create screenshots, or create matrix proof.',
    })
  }

  const plan = buildReleaseScreenshotManifestArtifactWritePlan({
    ...observed.observedInput,
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
        'Write plan is blocked. This command did not write screenshots/manifest.json, create screenshots, update observations/actions, or create matrix proof.',
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
        'Exclusive-create preflight refused to overwrite existing screenshots/manifest.json. This command did not update observations/actions or create matrix proof.',
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
      canonical_screenshot_manifest_path: targetManifestPath,
      screenshots_dir: screenshotsDir,
      screenshot_files: screenshotFiles.files.map((file) => ({
        path: file.absolutePath,
        relative_path: file.relativePath,
        sha256: file.sha256,
        size_bytes: file.sizeBytes,
        mtime_ms: file.mtimeMs,
      })),
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
        'Dry run only. Re-run with --write to persist screenshots/manifest.json with exclusive-create semantics. No screenshots, observations/actions, APKG, Anki, audio audit, timing/cache, source/deck proof, or matrix proof was created.',
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
        failedChecks: [
          error?.code === 'EEXIST'
            ? `${write.kind}_artifact_already_exists`
            : `${write.kind}_artifact_write_error`,
        ],
        readErrors: {
          [write.kind]: error instanceof Error ? error.message : String(error),
        },
        plannedWrites: plan.writes,
        inputSourceFiles,
        notes:
          'A write failed during exclusive-create persistence. Any written_files listed were created before the failure; no screenshots, observations/actions, APKG, Anki, audio, timing/cache, source/deck proof, or matrix proof was created.',
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
    canonical_screenshot_manifest_path: targetManifestPath,
    screenshots_dir: screenshotsDir,
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
      'Wrote only screenshots/manifest.json with exclusive-create semantics. This did not capture screenshots, update case manifests, update matrix summaries, write observations/actions, create APKG, import/verify Anki, write audio/timing/cache/source/deck proof, or verify a matrix pass.',
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
