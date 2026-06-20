#!/usr/bin/env node

import { constants as fsConstants } from 'node:fs'
import { access, readFile, stat, writeFile } from 'node:fs/promises'
import path from 'node:path'

import { buildReleaseSourceProvenanceArtifactWritePlanFromJson } from '../src/app/releaseEvidenceSourceProvenance.ts'
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
  source_provenance: 'source_provenance.json',
}

function usage() {
  return [
    'Usage:',
    '  node scripts/write_video_release_source_provenance_artifact.mjs --run-dir PATH --case CASE_ID --observed PATH [--dry-run|--write]',
    '',
    'Writes only cases/<case_id>/source_provenance.json when --write is provided.',
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

function validateCanonicalWritePaths({ writes, runDir, caseId, manifest }) {
  const failedChecks = []
  const caseDir = path.join(path.resolve(runDir), 'cases', caseId)
  const expectedPath = path.join(caseDir, WRITE_ARTIFACTS.source_provenance)
  const expectedRelativePath = normalizeRelativePath(path.relative(path.resolve(runDir), expectedPath))
  const manifestSourceFingerprint = stringValue(manifest?.source_candidate?.source_fingerprint)
  const manifestSourceKind = stringValue(manifest?.source_kind)

  for (const write of writes) {
    if (write.kind !== 'source_provenance') {
      failedChecks.push('write_artifact_kind_unknown')
      continue
    }
    if (write.writeMode !== 'exclusive_create') {
      failedChecks.push('source_provenance_write_mode_not_exclusive_create')
    }
    if (normalizeForCompare(write.absolutePath) !== normalizeForCompare(expectedPath)) {
      failedChecks.push('source_provenance_absolute_path_not_canonical')
    }
    if (normalizeRelativePath(write.relativePath) !== expectedRelativePath) {
      failedChecks.push('source_provenance_relative_path_not_canonical')
    }
    if (!pathIsInside(write.absolutePath, caseDir)) {
      failedChecks.push('source_provenance_absolute_path_outside_case_dir')
    }
    try {
      const parsed = JSON.parse(write.content)
      if (!isRecord(parsed)) {
        failedChecks.push('source_provenance_artifact_content_not_object')
      } else {
        if (Object.hasOwn(parsed, 'matrix_pass_created')) {
          failedChecks.push('source_provenance_artifact_matrix_pass_field_present')
        }
        if (parsed.case_id !== caseId) {
          failedChecks.push('source_provenance_artifact_case_id_mismatch')
        }
        if (manifestSourceKind && parsed.source_kind !== manifestSourceKind) {
          failedChecks.push('source_provenance_artifact_source_kind_mismatch')
        }
        if (manifestSourceFingerprint && parsed.source_fingerprint !== manifestSourceFingerprint) {
          failedChecks.push('source_provenance_artifact_source_fingerprint_mismatch')
        }
      }
    } catch {
      failedChecks.push('source_provenance_artifact_content_unreadable')
    }
  }

  if (writes.length !== 1) {
    failedChecks.push('write_plan_write_count_mismatch')
  }
  if (!writes.some((write) => write.kind === 'source_provenance')) {
    failedChecks.push('source_provenance_write_missing')
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
    canonical_source_provenance_path: caseDir ? path.join(caseDir, 'source_provenance.json') : null,
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
        'Choose either --dry-run or --write. This command did not write source_provenance.json or create matrix proof.',
    })
  }
  if (args.overwrite) {
    return blockedResult({
      args,
      failedChecks: ['artifact_overwrite_not_supported'],
      notes:
        'Source provenance proof artifacts are write-once. This command did not overwrite files or create matrix proof.',
    })
  }

  const runDirChecks = validateRunDirInput(args.runDir)
  if (runDirChecks.length > 0) {
    return blockedResult({
      args,
      failedChecks: runDirChecks,
      notes:
        'Run directory guard failed before reading manifests or observed data. This command did not write source_provenance.json or create matrix proof.',
    })
  }

  const caseDir = path.join(args.resolvedRunDir, 'cases', args.caseId)
  const directoryChecks = await initializedDirectoryChecks({ runDir: args.resolvedRunDir, caseDir })
  if (directoryChecks.length > 0) {
    return blockedResult({
      args,
      failedChecks: directoryChecks,
      notes:
        'Initialized release run/case directories are required. This writer does not create run skeletons, source_provenance.json, or matrix proof when the case is not initialized.',
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
        'Required input JSON could not be read. This command did not write source_provenance.json or create matrix proof.',
    })
  }

  const inputPreflight = await buildWriterInputSourceFilePreflight({
    rawObserved: observedRead.value,
    actualSourceFiles: {
      case_manifest: manifestRead.sourceFile,
      observed_handoff: observedRead.sourceFile,
    },
    requiredKeys: ['case_manifest', 'project'],
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
        'Writer input source-file preflight failed. This command did not trust captured raw input, write source_provenance.json, or create matrix proof.',
    })
  }

  const manifest = isRecord(manifestRead.value) ? manifestRead.value : {}
  const manifestShapeChecks = isRecord(manifestRead.value) ? [] : ['case_manifest_not_object']
  const plan = buildReleaseSourceProvenanceArtifactWritePlanFromJson({
    caseId: args.caseId,
    manifest,
    rawObserved: observedRead.value,
    runDir: args.runDir,
  })
  const canonicalPathChecks = validateCanonicalWritePaths({
    writes: plan.writes,
    runDir: args.resolvedRunDir,
    caseId: args.caseId,
    manifest,
  })
  const plannedWrites = plan.writes
  const failedChecks = unique([...manifestShapeChecks, ...plan.failedChecks, ...canonicalPathChecks])
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
        'Write plan is blocked. This command did not write source_provenance.json, update manifests, or create matrix proof.',
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
        'Exclusive-create preflight refused to overwrite existing source_provenance.json. This command did not update manifests or create matrix proof.',
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
      canonical_source_provenance_path: path.join(caseDir, 'source_provenance.json'),
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
        'Dry run only. Re-run with --write to persist source_provenance.json with exclusive-create semantics. No APKG, Anki, Computer Use, observation, screenshot, manifest, timing/cache, or matrix proof was created.',
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
    canonical_source_provenance_path: path.join(caseDir, 'source_provenance.json'),
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
      'Wrote only source_provenance.json with exclusive-create semantics. This did not update case manifests, matrix summaries, APKG, Anki, Computer Use, observation, screenshot, timing/cache proof and does not verify a matrix pass.',
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
