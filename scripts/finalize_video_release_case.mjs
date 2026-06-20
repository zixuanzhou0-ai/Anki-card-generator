#!/usr/bin/env node

import { mkdir, readFile, rename, stat, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

import {
  VIDEO_RELEASE_CASES,
  VIDEO_RELEASE_RUN_DIR_PREFIX,
  VIDEO_RELEASE_RUN_STAMP_PATTERN,
} from '../src/domain/releaseEvidenceLayout.ts'
import { pathSegments, releaseReportOutputPathChecks } from './release_report_output_guard.mjs'
import { buildVerification } from './verify_video_release_case.mjs'

function usage() {
  return [
    'Usage: node scripts/finalize_video_release_case.mjs --run-dir PATH --case CASE_ID [--dry-run|--write] [options]',
    '',
    'Finalizes one video-release matrix case only after the existing verifier would pass with an in-memory candidate passed manifest.',
    'Default mode is dry-run. Write mode updates only cases/<case>/case_manifest.json and immediately re-runs the normal verifier.',
    '',
    'Options:',
    '  --run-dir PATH                    video_release_hardening_* run directory',
    '  --case CASE_ID                    matrix case id, e.g. youtube_a_full1_cold',
    '  --dry-run                         report the guarded decision without writing (default)',
    '  --write                           update case_manifest.json when guarded evidence is complete',
    '  --output PATH                     write the finalizer JSON report; final evidence paths are refused',
    '  --overwrite                       allow replacing an existing --output file',
  ].join('\n')
}

function parseArgs(argv) {
  const args = {
    runDir: null,
    runDirInput: null,
    caseId: null,
    write: false,
    dryRunExplicit: false,
    outputPath: null,
    outputPathInput: null,
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
    if (['--run-dir', '--case', '--output'].includes(arg)) {
      const value = argv[index + 1]
      if (!value) {
        throw new Error(`${arg} requires a value`)
      }
      if (arg === '--run-dir') {
        args.runDirInput = value
        args.runDir = path.resolve(value)
      } else if (arg === '--case') {
        args.caseId = value
      } else {
        args.outputPathInput = value
        args.outputPath = path.resolve(value)
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
  if (!VIDEO_RELEASE_CASES.some((releaseCase) => releaseCase.id === args.caseId)) {
    throw new Error(`Unknown release matrix case: ${args.caseId}`)
  }
  if (args.write && args.dryRunExplicit) {
    throw new Error('Use either --write or --dry-run, not both')
  }
  return args
}

function validateRunDirInput(runDir, rawRunDir = runDir) {
  const failedChecks = []
  if (!path.isAbsolute(runDir)) {
    failedChecks.push('run_dir_not_absolute')
  }
  if (pathSegments(rawRunDir).some((segment) => segment === '..')) {
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

function pathIsInside(childPath, parentPath) {
  const relativePath = path.relative(path.resolve(parentPath), path.resolve(childPath))
  return Boolean(relativePath) && !relativePath.startsWith('..') && !path.isAbsolute(relativePath)
}

function casePaths(runDir, caseId) {
  const caseDir = path.join(runDir, 'cases', caseId)
  return {
    caseDir,
    caseManifestPath: path.join(caseDir, 'case_manifest.json'),
  }
}

async function finalizerOutputPathChecks(args) {
  return releaseReportOutputPathChecks({
    prefix: 'finalizer',
    outputPath: args.outputPath,
    outputPathInput: args.outputPathInput,
    overwrite: args.overwrite,
    runDir: args.runDir,
  })
}

async function initializedCaseChecks(runDir, caseId, rawRunDir = runDir) {
  const failedChecks = validateRunDirInput(runDir, rawRunDir)
  const { caseDir, caseManifestPath } = casePaths(runDir, caseId)
  if (!pathIsInside(caseDir, runDir)) {
    failedChecks.push('case_dir_outside_run_dir')
  }
  if (!pathIsInside(caseManifestPath, runDir)) {
    failedChecks.push('case_manifest_outside_run_dir')
  }

  try {
    const runStat = await stat(runDir)
    if (!runStat.isDirectory()) {
      failedChecks.push('run_dir_not_directory')
    }
  } catch (error) {
    failedChecks.push(error?.code === 'ENOENT' ? 'run_dir_not_found' : 'run_dir_access_error')
  }

  try {
    const caseStat = await stat(caseDir)
    if (!caseStat.isDirectory()) {
      failedChecks.push('case_dir_not_directory')
    }
  } catch (error) {
    failedChecks.push(error?.code === 'ENOENT' ? 'case_dir_not_found' : 'case_dir_access_error')
  }

  try {
    const manifestStat = await stat(caseManifestPath)
    if (!manifestStat.isFile()) {
      failedChecks.push('case_manifest_not_file')
    }
  } catch (error) {
    failedChecks.push(error?.code === 'ENOENT' ? 'case_manifest_missing' : 'case_manifest_access_error')
  }

  return [...new Set(failedChecks)]
}

async function readManifestFile(caseManifestPath) {
  try {
    const content = await readFile(caseManifestPath, 'utf8')
    return {
      ok: true,
      content,
      value: JSON.parse(content.replace(/^\uFEFF/, '')),
      error: null,
    }
  } catch (error) {
    return {
      ok: false,
      content: null,
      value: null,
      error: error instanceof Error ? error.message : String(error),
    }
  }
}

function buildCandidateManifest(manifest, finalizedAt) {
  return {
    ...manifest,
    status: 'passed',
    finalized_at: finalizedAt,
    finalization: {
      schema_version: 1,
      finalized_at: finalizedAt,
      finalized_by: 'release:finalize-case',
      previous_status: manifest.status ?? null,
      guard: 'evaluateVideoReleaseCaseCompletionEvidence(candidate manifest)',
      case_pass_created: true,
      matrix_pass_created: false,
    },
  }
}

function summarizeVerification(verification) {
  return {
    status: verification.status,
    ok: verification.verification.ok,
    failed_checks: verification.verification.failed_checks,
    warnings: verification.verification.warnings,
    read_errors: verification.verification.read_errors,
  }
}

function uniqueChecks(checks) {
  return [...new Set(checks.filter(Boolean))]
}

function manifestWriteSummary(caseManifestPath, runDir, content) {
  return {
    kind: 'case_manifest',
    relative_path: path.relative(runDir, caseManifestPath).split(path.sep).join('/'),
    absolute_path: caseManifestPath,
    write_mode: 'atomic_temp_rename_after_compare',
    bytes: Buffer.byteLength(content, 'utf8'),
  }
}

function buildReport({
  args,
  status,
  failedChecks = [],
  currentVerification = null,
  candidateVerification = null,
  postWriteVerification = null,
  candidateManifest = null,
  plannedWrites = [],
  writtenFiles = [],
  manifestReadError = null,
}) {
  const finalVerification = postWriteVerification ?? candidateVerification ?? currentVerification
  return {
    schema_version: 1,
    created_at: new Date().toISOString(),
    status,
    ok: failedChecks.length === 0,
    write_requested: args.write,
    dry_run: !args.write,
    case_pass_created: status === 'written',
    case_pass_verified: finalVerification?.verification.ok ?? false,
    matrix_pass_created: false,
    matrix_pass_verified: false,
    case_id: args.caseId,
    run_dir: args.runDir,
    current_verification: currentVerification ? summarizeVerification(currentVerification) : null,
    candidate_verification: candidateVerification ? summarizeVerification(candidateVerification) : null,
    post_write_verification: postWriteVerification ? summarizeVerification(postWriteVerification) : null,
    finalizer: {
      ok: failedChecks.length === 0,
      failed_checks: failedChecks,
      warnings: finalVerification?.verification.warnings ?? [],
      read_errors: finalVerification?.verification.read_errors ?? {},
      manifest_read_error: manifestReadError,
      candidate_status: candidateManifest?.status ?? null,
      candidate_finalized_at: candidateManifest?.finalized_at ?? null,
    },
    planned_writes: plannedWrites,
    written_files: writtenFiles,
    notes:
      'This finalizer only updates case_manifest.json after all real final evidence already passes with a candidate manifest. It never creates APKG, source, Anki, audio, timing, cache, Computer Use, observation, screenshot, or matrix proof.',
  }
}

async function writeReport(outputPath, result, overwrite) {
  if (!outputPath) {
    return
  }
  await mkdir(path.dirname(outputPath), { recursive: true })
  await writeFile(outputPath, `${JSON.stringify(result, null, 2)}\n`, {
    encoding: 'utf8',
    flag: overwrite ? 'w' : 'wx',
  })
}

async function writeManifestAtomically({ caseManifestPath, expectedContent, nextContent }) {
  const currentContent = await readFile(caseManifestPath, 'utf8')
  if (currentContent !== expectedContent) {
    return {
      ok: false,
      failed_check: 'case_manifest_changed_before_write',
      temp_path: null,
    }
  }

  const tempPath = path.join(
    path.dirname(caseManifestPath),
    `.case_manifest.finalize.${process.pid}.${Date.now()}.tmp`,
  )
  await writeFile(tempPath, nextContent, { encoding: 'utf8', flag: 'wx' })
  await rename(tempPath, caseManifestPath)
  return {
    ok: true,
    failed_check: null,
    temp_path: tempPath,
  }
}

async function finalizeCase(args) {
  const runChecks = await initializedCaseChecks(args.runDir, args.caseId, args.runDirInput ?? args.runDir)
  if (runChecks.length > 0) {
    return buildReport({
      args,
      status: 'blocked',
      failedChecks: runChecks,
    })
  }

  const { caseManifestPath } = casePaths(args.runDir, args.caseId)
  const currentVerification = await buildVerification(args)
  const manifestRead = await readManifestFile(caseManifestPath)
  if (!manifestRead.ok) {
    return buildReport({
      args,
      status: 'blocked',
      failedChecks: uniqueChecks(['case_manifest_unreadable_for_finalization', ...currentVerification.verification.failed_checks]),
      currentVerification,
      manifestReadError: manifestRead.error,
    })
  }

  if (currentVerification.verification.ok && manifestRead.value.status === 'passed') {
    return buildReport({
      args,
      status: 'already_finalized',
      currentVerification,
      candidateManifest: manifestRead.value,
    })
  }

  const finalizedAt = new Date().toISOString()
  const candidateManifest = buildCandidateManifest(manifestRead.value, finalizedAt)
  const candidateVerification = await buildVerification(args, { manifestOverride: candidateManifest })
  const candidateFailedChecks = candidateVerification.verification.failed_checks
  const candidateContent = `${JSON.stringify(candidateManifest, null, 2)}\n`
  const plannedWrites = [manifestWriteSummary(caseManifestPath, args.runDir, candidateContent)]

  if (candidateFailedChecks.length > 0) {
    return buildReport({
      args,
      status: 'blocked',
      failedChecks: candidateFailedChecks,
      currentVerification,
      candidateVerification,
      candidateManifest,
      plannedWrites: [],
    })
  }

  if (!args.write) {
    return buildReport({
      args,
      status: 'ready_to_finalize',
      currentVerification,
      candidateVerification,
      candidateManifest,
      plannedWrites,
    })
  }

  const writeResult = await writeManifestAtomically({
    caseManifestPath,
    expectedContent: manifestRead.content,
    nextContent: candidateContent,
  })
  if (!writeResult.ok) {
    return buildReport({
      args,
      status: 'blocked',
      failedChecks: [writeResult.failed_check],
      currentVerification,
      candidateVerification,
      candidateManifest,
      plannedWrites,
    })
  }

  const postWriteVerification = await buildVerification(args)
  if (!postWriteVerification.verification.ok) {
    return buildReport({
      args,
      status: 'post_write_verification_failed',
      failedChecks: postWriteVerification.verification.failed_checks,
      currentVerification,
      candidateVerification,
      postWriteVerification,
      candidateManifest,
      plannedWrites,
      writtenFiles: [plannedWrites[0]],
    })
  }

  return buildReport({
    args,
    status: 'written',
    currentVerification,
    candidateVerification,
    postWriteVerification,
    candidateManifest,
    plannedWrites,
    writtenFiles: [plannedWrites[0]],
  })
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  try {
    const args = parseArgs(process.argv.slice(2))
    const outputPathChecks = await finalizerOutputPathChecks(args)
    const result =
      outputPathChecks.length > 0
        ? buildReport({
            args,
            status: 'blocked',
            failedChecks: outputPathChecks,
          })
        : await finalizeCase(args)
    if (outputPathChecks.length === 0) {
      await writeReport(args.outputPath, result, args.overwrite)
    }
    console.log(JSON.stringify(result, null, 2))
    process.exit(result.ok ? 0 : 2)
  } catch (error) {
    console.error(error instanceof Error ? error.message : error)
    process.exit(1)
  }
}
