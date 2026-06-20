#!/usr/bin/env node

import { createHash } from 'node:crypto'
import { mkdir, readFile, readdir, stat, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

import {
  VIDEO_RELEASE_CASES,
  VIDEO_RELEASE_RUN_DIR_PREFIX,
  VIDEO_RELEASE_RUN_STAMP_PATTERN,
  evaluateVideoReleaseCaseCompletionEvidence,
} from '../src/domain/releaseEvidenceLayout.ts'
import { pathSegments, releaseReportOutputPathChecks } from './release_report_output_guard.mjs'

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

function usage() {
  return [
    'Usage: node scripts/verify_video_release_case.mjs --run-dir PATH --case CASE_ID [options]',
    '',
    'Verifies whether a final video-release matrix case has enough real APKG, source, Anki, audio, timing, cache, Computer Use, and screenshot evidence to count as passed.',
    'This command is read-only unless --output is provided, and it never creates APKG, source, Anki, audio, timing, or screenshot proof.',
    '',
    'Options:',
    '  --run-dir PATH                    video_release_hardening_* run directory',
    '  --case CASE_ID                    matrix case id, e.g. youtube_a_full1_cold',
    '  --output PATH                     write the verification JSON report; final evidence paths are refused',
    '  --overwrite                       allow replacing an existing --output file',
  ].join('\n')
}

function parseArgs(argv) {
  const args = {
    runDirInput: null,
    runDir: null,
    caseId: null,
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
      } else if (arg === '--output') {
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
  return args
}

async function readJsonIfPresent(filePath) {
  try {
    const content = await readFile(filePath, 'utf8')
    return {
      value: JSON.parse(content.replace(/^\uFEFF/, '')),
      missing: false,
      error: null,
    }
  } catch (error) {
    if (error?.code === 'ENOENT') {
      return { value: null, missing: true, error: null }
    }
    return {
      value: null,
      missing: false,
      error: error instanceof Error ? error.message : String(error),
    }
  }
}

async function listFilesIfPresent(directoryPath, predicate) {
  try {
    const entries = await readdir(directoryPath, { withFileTypes: true })
    return {
      files: entries
        .filter((entry) => entry.isFile() && predicate(entry.name))
        .map((entry) => path.join(directoryPath, entry.name)),
      missing: false,
      error: null,
    }
  } catch (error) {
    if (error?.code === 'ENOENT') {
      return { files: [], missing: true, error: null }
    }
    return {
      files: [],
      missing: false,
      error: error instanceof Error ? error.message : String(error),
    }
  }
}

async function fileSha256(filePath) {
  const digest = createHash('sha256')
  digest.update(await readFile(filePath))
  return digest.digest('hex')
}

function validateRunDirInput(runDir, rawRunDir = runDir) {
  const failedChecks = []
  if (!runDir) {
    failedChecks.push('run_dir_missing')
    return failedChecks
  }
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

function runRelativePath(runDir, filePath) {
  return path.relative(runDir, filePath).split(path.sep).join('/')
}

function caseArtifacts(runDir, caseId) {
  const caseDir = path.join(runDir, 'cases', caseId)
  const screenshotsDir = path.join(caseDir, 'screenshots')
  return {
    case_manifest: path.join(caseDir, 'case_manifest.json'),
    apkg_dir: path.join(caseDir, 'apkg'),
    source_provenance: path.join(caseDir, 'source_provenance.json'),
    deck_metadata: path.join(caseDir, 'deck_metadata.json'),
    anki_verify: path.join(caseDir, 'anki_verify.stdout.json'),
    audio_audit: path.join(caseDir, 'audio_audit.verify.json'),
    timing: path.join(caseDir, 'timing.json'),
    cache_summary: path.join(caseDir, 'cache_summary.json'),
    observations: path.join(caseDir, 'observations.json'),
    computer_use_actions: path.join(caseDir, 'computer_use_actions.json'),
    screenshot_manifest: path.join(screenshotsDir, 'manifest.json'),
    screenshots_dir: screenshotsDir,
  }
}

async function verifierOutputPathChecks(args) {
  return releaseReportOutputPathChecks({
    prefix: 'verifier',
    outputPath: args.outputPath,
    outputPathInput: args.outputPathInput,
    overwrite: args.overwrite,
    runDir: args.runDir,
  })
}

function outputPathBlockedReport(args, failedChecks) {
  return {
    schema_version: 1,
    created_at: new Date().toISOString(),
    status: 'blocked',
    matrix_pass_verified: false,
    case_id: args.caseId,
    run_dir: args.runDir,
    artifacts: caseArtifacts(args.runDir, args.caseId),
    artifact_summary: {
      apkg_files: [],
      screenshot_files: [],
      screenshot_manifest_present: false,
      expected_cards: 0,
      required_preview_cards: 0,
    },
    verification: {
      ok: false,
      failed_checks: failedChecks,
      warnings: [],
      read_errors: {},
    },
    notes:
      'Verifier report output path guard blocked before reading or hashing case artifacts. No APKG, source, Anki, audio, timing, cache, screenshot, observation, Computer Use, case-pass, or matrix-pass proof was created.',
  }
}

async function listApkgEvidenceIfPresent(runDir, directoryPath) {
  const listed = await listFilesIfPresent(directoryPath, (name) => name.toLowerCase().endsWith('.apkg'))
  if (listed.error || listed.missing) {
    return listed
  }
  const files = []
  for (const filePath of listed.files) {
    try {
      const fileStat = await stat(filePath)
      files.push({
        path: filePath,
        relative_path: runRelativePath(runDir, filePath),
        sha256: await fileSha256(filePath),
        size_bytes: fileStat.size,
        mtime_ms: Math.round(fileStat.mtimeMs),
      })
    } catch (error) {
      return {
        files: [],
        missing: false,
        error: error instanceof Error ? error.message : String(error),
      }
    }
  }
  return { ...listed, files }
}

async function listScreenshotEvidenceIfPresent(runDir, directoryPath) {
  const listed = await listFilesIfPresent(directoryPath, (name) => /\.(png|jpe?g|webp)$/i.test(name))
  if (listed.error || listed.missing) {
    return listed
  }
  const files = []
  for (const filePath of listed.files) {
    try {
      const fileStat = await stat(filePath)
      files.push({
        path: filePath,
        relative_path: runRelativePath(runDir, filePath),
        sha256: await fileSha256(filePath),
        size_bytes: fileStat.size,
        mtime_ms: Math.round(fileStat.mtimeMs),
      })
    } catch (error) {
      return {
        files: [],
        missing: false,
        error: error instanceof Error ? error.message : String(error),
      }
    }
  }
  return { ...listed, files }
}

export async function buildVerification(args, options = {}) {
  const caseDir = path.join(args.runDir, 'cases', args.caseId)
  const artifacts = caseArtifacts(args.runDir, args.caseId)
  const caseManifestPath = artifacts.case_manifest
  const apkgDir = artifacts.apkg_dir
  const screenshotsDir = artifacts.screenshots_dir

  const boundaryChecks = [
    ...validateRunDirInput(args.runDir, args.runDirInput ?? args.runDir),
    ...(!pathIsInside(caseDir, args.runDir) ? ['case_dir_outside_run_dir'] : []),
    ...(!pathIsInside(caseManifestPath, args.runDir) ? ['case_manifest_outside_run_dir'] : []),
    ...(!pathIsInside(screenshotsDir, caseDir) ? ['screenshots_dir_outside_case_dir'] : []),
  ]
  const uniqueBoundaryChecks = [...new Set(boundaryChecks)]
  if (uniqueBoundaryChecks.length > 0) {
    return {
      schema_version: 1,
      created_at: new Date().toISOString(),
      status: 'blocked',
      matrix_pass_verified: false,
      case_id: args.caseId,
      run_dir: args.runDir,
      artifacts,
      artifact_summary: {
        apkg_files: [],
        screenshot_files: [],
        screenshot_manifest_present: false,
        expected_cards: 0,
        required_preview_cards: 0,
      },
      verification: {
        ok: false,
        failed_checks: uniqueBoundaryChecks,
        warnings: [],
        read_errors: {},
      },
      notes:
        'This is a completion verifier only. It does not create APKG, source provenance, Anki import, media playback, audio audit, timing, cache, or screenshot proof.',
    }
  }

  const caseManifest = await readJsonIfPresent(caseManifestPath)
  const sourceProvenance = await readJsonIfPresent(artifacts.source_provenance)
  const deckMetadata = await readJsonIfPresent(artifacts.deck_metadata)
  const ankiVerify = await readJsonIfPresent(artifacts.anki_verify)
  const audioAudit = await readJsonIfPresent(artifacts.audio_audit)
  const timing = await readJsonIfPresent(artifacts.timing)
  const cacheSummary = await readJsonIfPresent(artifacts.cache_summary)
  const observations = await readJsonIfPresent(artifacts.observations)
  const computerUseActions = await readJsonIfPresent(artifacts.computer_use_actions)
  const screenshotManifest = await readJsonIfPresent(artifacts.screenshot_manifest)
  const apkgFiles = await listApkgEvidenceIfPresent(args.runDir, apkgDir)
  const screenshotFiles = await listScreenshotEvidenceIfPresent(args.runDir, screenshotsDir)
  const manifestForEvaluation = options.manifestOverride ?? caseManifest.value ?? {}

  const readErrors = [
    ['case_manifest_unreadable', caseManifest.error],
    ['source_provenance_unreadable', sourceProvenance.error],
    ['deck_metadata_unreadable', deckMetadata.error],
    ['anki_verify_unreadable', ankiVerify.error],
    ['audio_audit_unreadable', audioAudit.error],
    ['timing_unreadable', timing.error],
    ['cache_summary_unreadable', cacheSummary.error],
    ['observations_unreadable', observations.error],
    ['computer_use_actions_unreadable', computerUseActions.error],
    ['screenshot_manifest_unreadable', screenshotManifest.error],
    ['apkg_dir_unreadable', apkgFiles.error],
    ['screenshots_dir_unreadable', screenshotFiles.error],
  ].filter(([, error]) => error)

  const completion = evaluateVideoReleaseCaseCompletionEvidence({
    caseId: args.caseId,
    manifest: manifestForEvaluation,
    apkgFiles: apkgFiles.files,
    screenshotFiles: screenshotFiles.files,
    sourceProvenance: sourceProvenance.value,
    deckMetadata: deckMetadata.value,
    ankiVerify: ankiVerify.value,
    audioAudit: audioAudit.value,
    timing: timing.value,
    cacheSummary: cacheSummary.value,
    observations: observations.value,
    computerUseActions: computerUseActions.value,
    screenshotManifest: screenshotManifest.value,
  })

  const failedChecks = [...new Set([...readErrors.map(([check]) => check), ...completion.failedChecks])]
  return {
    schema_version: 1,
    created_at: new Date().toISOString(),
    status: failedChecks.length === 0 ? 'passed' : 'blocked',
    matrix_pass_verified: failedChecks.length === 0,
    case_id: args.caseId,
    run_dir: args.runDir,
    artifacts,
    artifact_summary: {
      apkg_files: apkgFiles.files,
      screenshot_files: screenshotFiles.files,
      screenshot_manifest_present: !screenshotManifest.missing,
      expected_cards: completion.expectedCards,
      required_preview_cards: completion.requiredPreviewCards,
    },
    verification: {
      ok: failedChecks.length === 0,
      failed_checks: failedChecks,
      warnings: completion.warnings,
      read_errors: Object.fromEntries(readErrors),
    },
    notes:
      'This is a completion verifier only. It does not create APKG, source provenance, Anki import, media playback, audio audit, timing, cache, or screenshot proof.',
  }
}

async function writeVerification(outputPath, result, overwrite) {
  await mkdir(path.dirname(outputPath), { recursive: true })
  await writeFile(outputPath, `${JSON.stringify(result, null, 2)}\n`, {
    encoding: 'utf8',
    flag: overwrite ? 'w' : 'wx',
  })
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  try {
    const args = parseArgs(process.argv.slice(2))
    const outputPathChecks = await verifierOutputPathChecks(args)
    const result = outputPathChecks.length > 0 ? outputPathBlockedReport(args, outputPathChecks) : await buildVerification(args)
    if (args.outputPath && outputPathChecks.length === 0) {
      await writeVerification(args.outputPath, result, args.overwrite)
    }
    console.log(JSON.stringify(result, null, 2))
    process.exit(result.verification.ok ? 0 : 2)
  } catch (error) {
    console.error(error instanceof Error ? error.message : error)
    process.exit(1)
  }
}
