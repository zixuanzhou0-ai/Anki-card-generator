#!/usr/bin/env node

import { readFile, stat, writeFile } from 'node:fs/promises'
import path from 'node:path'

import { buildReleaseMaterialCandidatePromotionPlan } from '../src/app/releaseEvidenceMaterialCandidates.ts'
import {
  VIDEO_RELEASE_CASES,
  VIDEO_RELEASE_RUN_DIR_PREFIX,
  VIDEO_RELEASE_RUN_STAMP_PATTERN,
} from '../src/domain/releaseEvidenceLayout.ts'

function usage() {
  return [
    'Usage:',
    '  node scripts/promote_video_release_material_candidates.mjs --run-dir PATH --youtube-material-manifest PATH --local-srt-material-manifest PATH [--dry-run|--write] [--overwrite-source-candidates]',
    '',
    'Promotes verified material rotation source candidates into initialized case_manifest.json files.',
    'Default mode is dry-run. It never creates APKG, Anki, audio, timing/cache, Computer Use, screenshot, or matrix-pass proof.',
  ].join('\n')
}

function parseArgs(argv) {
  const args = {
    runDir: null,
    youtubeMaterialManifestPath: null,
    localSrtMaterialManifestPath: null,
    write: false,
    dryRunExplicit: false,
    overwriteSourceCandidates: false,
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
    if (arg === '--overwrite-source-candidates') {
      args.overwriteSourceCandidates = true
      continue
    }
    if (['--run-dir', '--youtube-material-manifest', '--local-srt-material-manifest'].includes(arg)) {
      const value = argv[index + 1]
      if (!value) {
        throw new Error(`${arg} requires a value`)
      }
      if (arg === '--run-dir') {
        args.runDir = path.resolve(value)
      } else if (arg === '--youtube-material-manifest') {
        args.youtubeMaterialManifestPath = path.resolve(value)
      } else if (arg === '--local-srt-material-manifest') {
        args.localSrtMaterialManifestPath = path.resolve(value)
      }
      index += 1
      continue
    }
    throw new Error(`Unknown argument: ${arg}`)
  }

  if (!args.runDir) {
    throw new Error('--run-dir is required')
  }
  if (!args.youtubeMaterialManifestPath) {
    throw new Error('--youtube-material-manifest is required')
  }
  if (!args.localSrtMaterialManifestPath) {
    throw new Error('--local-srt-material-manifest is required')
  }
  if (args.write && args.dryRunExplicit) {
    throw new Error('Use either --write or --dry-run, not both')
  }

  return args
}

function pathSegments(value) {
  return String(value ?? '')
    .split(/[\\/]+/)
    .filter(Boolean)
}

function validateRunDirInput(runDir) {
  const failedChecks = []
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

function pathIsInside(childPath, parentPath) {
  const relativePath = path.relative(path.resolve(parentPath), path.resolve(childPath))
  return Boolean(relativePath) && !relativePath.startsWith('..') && !path.isAbsolute(relativePath)
}

async function readJson(filePath) {
  const content = await readFile(filePath, 'utf8')
  return JSON.parse(content.replace(/^\uFEFF/, ''))
}

async function readMaterialManifest(filePath, label) {
  try {
    return await readJson(filePath)
  } catch (error) {
    throw new Error(`${label} material manifest is unreadable: ${error instanceof Error ? error.message : String(error)}`)
  }
}

async function readCaseManifests(runDir) {
  const result = {}
  for (const releaseCase of VIDEO_RELEASE_CASES) {
    const manifestPath = path.join(runDir, 'cases', releaseCase.id, 'case_manifest.json')
    try {
      result[releaseCase.id] = await readJson(manifestPath)
    } catch (error) {
      throw new Error(
        `case manifest ${releaseCase.id} is unreadable: ${error instanceof Error ? error.message : String(error)}`,
      )
    }
  }
  return result
}

async function initializedRunChecks(runDir) {
  const failedChecks = validateRunDirInput(runDir)
  try {
    const runStat = await stat(runDir)
    if (!runStat.isDirectory()) {
      failedChecks.push('run_dir_not_directory')
    }
  } catch (error) {
    failedChecks.push(error?.code === 'ENOENT' ? 'run_dir_not_found' : 'run_dir_access_error')
  }
  for (const releaseCase of VIDEO_RELEASE_CASES) {
    const caseDir = path.join(runDir, 'cases', releaseCase.id)
    if (!pathIsInside(caseDir, runDir)) {
      failedChecks.push(`case_${releaseCase.id}_dir_outside_run_dir`)
    }
    try {
      const caseStat = await stat(caseDir)
      if (!caseStat.isDirectory()) {
        failedChecks.push(`case_${releaseCase.id}_dir_not_directory`)
      }
    } catch (error) {
      failedChecks.push(error?.code === 'ENOENT' ? `case_${releaseCase.id}_dir_not_found` : `case_${releaseCase.id}_dir_access_error`)
    }
  }
  return [...new Set(failedChecks)]
}

function summarizeWrites(writes) {
  return writes.map((write) => ({
    kind: write.kind,
    case_id: write.caseId,
    relative_path: write.relativePath,
    absolute_path: write.absolutePath,
    write_mode: write.writeMode,
    bytes: Buffer.byteLength(write.content, 'utf8'),
  }))
}

try {
  const args = parseArgs(process.argv.slice(2))
  const runChecks = await initializedRunChecks(args.runDir)
  if (runChecks.length > 0) {
    console.log(
      JSON.stringify(
        {
          ok: false,
          status: 'blocked',
          matrix_pass_created: false,
          failed_checks: runChecks,
          notes: 'Run directory is not a valid initialized video release run.',
        },
        null,
        2,
      ),
    )
    process.exit(1)
  }

  const youtubeManifest = await readMaterialManifest(args.youtubeMaterialManifestPath, 'YouTube')
  const localSrtManifest = await readMaterialManifest(args.localSrtMaterialManifestPath, 'local-SRT')
  const caseManifests = await readCaseManifests(args.runDir)
  const selectedAt = new Date().toISOString()
  const plan = buildReleaseMaterialCandidatePromotionPlan({
    runDir: args.runDir,
    youtubeMaterialManifest: {
      path: args.youtubeMaterialManifestPath,
      value: youtubeManifest,
    },
    localSrtMaterialManifest: {
      path: args.localSrtMaterialManifestPath,
      value: localSrtManifest,
    },
    caseManifests,
    selectedAt,
    overwriteExisting: args.overwriteSourceCandidates,
  })

  const dryRun = !args.write
  if (!plan.ok) {
    console.log(
      JSON.stringify(
        {
          ok: false,
          status: 'blocked',
          matrix_pass_created: false,
          failed_checks: plan.failedChecks,
          warnings: plan.warnings,
          run_dir: args.runDir,
          notes: plan.notes,
        },
        null,
        2,
      ),
    )
    process.exit(1)
  }

  if (!dryRun) {
    for (const write of plan.writes) {
      await writeFile(write.absolutePath, write.content, { encoding: 'utf8', flag: 'w' })
    }
  }

  console.log(
    JSON.stringify(
      {
        ok: true,
        status: dryRun ? 'dry_run_not_written' : 'written',
        matrix_pass_created: false,
        run_dir: args.runDir,
        promoted_cases: plan.promotedCases,
        writes: summarizeWrites(plan.writes),
        notes: plan.notes,
      },
      null,
      2,
    ),
  )
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error))
  process.exit(1)
}
