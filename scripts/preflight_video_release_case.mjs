#!/usr/bin/env node

import { createHash } from 'node:crypto'
import { createReadStream } from 'node:fs'
import { mkdir, readFile, stat, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  VIDEO_RELEASE_CASES,
  buildVideoReleaseCaseCacheTimingPlan,
  evaluateVideoReleaseCaseStartPreflight,
} from '../src/domain/releaseEvidenceLayout.ts'
import { releaseReportOutputPathChecks } from './release_report_output_guard.mjs'

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

function usage() {
  return [
    'Usage: node scripts/preflight_video_release_case.mjs --run-dir PATH --case CASE_ID [options]',
    '',
    'Checks whether a final video-release matrix case is honestly ready to start.',
    'This command is read-only unless --output is provided, and it never creates APKG, Anki, audio, timing, or screenshot proof.',
    '',
    'Options:',
    '  --run-dir PATH                    video_release_hardening_* run directory',
    '  --case CASE_ID                    matrix case id, e.g. youtube_a_full1_cold',
    '  --case-manifest PATH              override case manifest path',
    '  --launcher-readiness PATH         launcher JSON; defaults to .tauri-launch-current.json',
    '  --computer-use-available          explicitly assert desktop Computer Use controls are available',
    '  --computer-use-unavailable        explicitly assert desktop Computer Use controls are unavailable',
    '  --cold-cache-reads-disabled       assert controllable cold-run cache reads are disabled in the planned run payload',
    '  --output PATH                     write the preflight JSON report; final evidence paths are refused',
    '  --overwrite                       allow replacing an existing --output file',
  ].join('\n')
}

function parseArgs(argv) {
  const args = {
    runDirInput: null,
    runDir: null,
    caseId: null,
    caseManifestPathInput: null,
    caseManifestPath: null,
    launcherReadinessPath: path.join(repoRoot, '.tauri-launch-current.json'),
    computerUseAvailable: null,
    coldCacheReadsDisabled: false,
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
    if (arg === '--computer-use-available') {
      args.computerUseAvailable = true
      continue
    }
    if (arg === '--computer-use-unavailable') {
      args.computerUseAvailable = false
      continue
    }
    if (arg === '--cold-cache-reads-disabled') {
      args.coldCacheReadsDisabled = true
      continue
    }
    if (arg === '--overwrite') {
      args.overwrite = true
      continue
    }
    if (['--run-dir', '--case', '--case-manifest', '--launcher-readiness', '--output'].includes(arg)) {
      const value = argv[index + 1]
      if (!value) {
        throw new Error(`${arg} requires a value`)
      }
      if (arg === '--run-dir') {
        args.runDirInput = value
        args.runDir = path.resolve(value)
      } else if (arg === '--case') {
        args.caseId = value
      } else if (arg === '--case-manifest') {
        args.caseManifestPathInput = value
        args.caseManifestPath = path.resolve(value)
      } else if (arg === '--launcher-readiness') {
        args.launcherReadinessPath = path.resolve(value)
      } else if (arg === '--output') {
        args.outputPathInput = value
        args.outputPath = path.resolve(value)
      }
      index += 1
      continue
    }
    throw new Error(`Unknown argument: ${arg}`)
  }

  if (!args.runDir && !args.caseManifestPath) {
    throw new Error('--run-dir is required unless --case-manifest is provided')
  }
  if (!args.caseId) {
    throw new Error('--case is required')
  }
  if (!VIDEO_RELEASE_CASES.some((releaseCase) => releaseCase.id === args.caseId)) {
    throw new Error(`Unknown release matrix case: ${args.caseId}`)
  }
  if (!args.caseManifestPath) {
    args.caseManifestPath = path.join(args.runDir, 'cases', args.caseId, 'case_manifest.json')
  }

  return args
}

async function preflightOutputPathChecks(args) {
  return releaseReportOutputPathChecks({
    prefix: 'preflight',
    outputPath: args.outputPath,
    outputPathInput: args.outputPathInput,
    overwrite: args.overwrite,
    runDir: args.runDir,
    caseId: args.caseId,
    caseManifestPath: args.caseManifestPath,
    includeSelectedCaseManifestDir: true,
    inferRunDirFromCaseManifest: true,
    inferRunDirFromOutput: true,
    allowCanonicalPreflightStart: true,
  })
}

function outputPathBlockedReport(args, failedChecks) {
  return {
    schema_version: 1,
    created_at: new Date().toISOString(),
    status: 'blocked',
    matrix_pass_created: false,
    case_id: args.caseId,
    run_dir: args.runDir,
    case_manifest_path: args.caseManifestPath,
    launcher_readiness_path: args.launcherReadinessPath,
    launcher_readiness_error: null,
    inputs: {
      computer_use_available_explicit: args.computerUseAvailable !== null,
      computer_use_available: args.computerUseAvailable === true,
      cold_cache_reads_disabled: args.coldCacheReadsDisabled,
    },
    preflight: {
      ok: false,
      failed_checks: failedChecks,
      warnings: [],
      required_evidence: [],
    },
    source_candidate: null,
    material_manifest_check: null,
    cache_timing_plan: null,
    notes:
      'Preflight report output path guard blocked before reading case manifest, launcher readiness, or material files. No APKG, Anki, audio, timing, cache, screenshot, case-pass, or matrix-pass proof was created.',
  }
}

async function readJson(filePath) {
  const content = await readFile(filePath, 'utf8')
  return JSON.parse(content.replace(/^\uFEFF/, ''))
}

function launcherReadinessFrom(rawLauncherJson) {
  if (!rawLauncherJson || typeof rawLauncherJson !== 'object') {
    return null
  }
  if (rawLauncherJson.readiness && typeof rawLauncherJson.readiness === 'object') {
    return rawLauncherJson.readiness
  }
  return rawLauncherJson
}

function findMaterialItem(materialManifest, sourceCandidate) {
  const items = Array.isArray(materialManifest?.items) ? materialManifest.items : []
  return items.find(
    (item) =>
      item?.video_id === sourceCandidate?.video_id ||
      item?.url === sourceCandidate?.url ||
      item?.webpage_url === sourceCandidate?.url ||
      item?.downloaded_video_path === (sourceCandidate?.downloaded_video_path ?? sourceCandidate?.video_path) ||
      item?.subtitle_path === sourceCandidate?.subtitle_path ||
      item?.source_fingerprint === sourceCandidate?.source_fingerprint,
  )
}

async function sha256File(filePath) {
  return new Promise((resolve, reject) => {
    const hash = createHash('sha256')
    const stream = createReadStream(filePath)
    stream.on('error', reject)
    stream.on('data', (chunk) => hash.update(chunk))
    stream.on('end', () => resolve(hash.digest('hex')))
  })
}

async function collectFileEvidence(filePath) {
  const fileStat = await stat(filePath)
  return {
    bytes: fileStat.size,
    sha256: await sha256File(filePath),
  }
}

async function checkMaterialManifest(sourceCandidate, sourceKind) {
  const failedChecks = []
  const warnings = []
  const summary = {
    checked: false,
    material_manifest: sourceCandidate?.material_manifest ?? null,
    matched_item_index: null,
    existing_url_cache_dirs: [],
  }

  if (!sourceCandidate?.material_manifest) {
    return {
      ok: false,
      failedChecks: [`${sourceKind}_source_candidate_material_manifest_missing`],
      warnings,
      summary,
    }
  }

  let materialManifest
  try {
    materialManifest = await readJson(sourceCandidate.material_manifest)
  } catch (error) {
    return {
      ok: false,
      failedChecks: ['material_manifest_unreadable'],
      warnings,
      summary: {
        ...summary,
        error: error instanceof Error ? error.message : String(error),
      },
    }
  }

  summary.checked = true
  const item = findMaterialItem(materialManifest, sourceCandidate)
  if (!item) {
    failedChecks.push('material_manifest_candidate_missing')
  } else {
    summary.matched_item_index = item.index ?? null
    summary.kind = item.kind ?? null
    summary.url = item.url ?? null
    summary.video_id = item.video_id ?? null
    summary.downloaded_video_path = item.downloaded_video_path ?? null
    summary.subtitle_path = item.subtitle_path ?? null
    summary.video_bytes = item.video_bytes ?? null
    summary.subtitle_bytes = item.subtitle_bytes ?? null
    summary.video_sha256 = item.video_sha256 ?? null
    summary.subtitle_sha256 = item.subtitle_sha256 ?? null
    summary.source_fingerprint = item.source_fingerprint ?? null
    summary.cache_probe_status = item.cache_probe?.status ?? null
    summary.existing_url_cache_dirs = Array.isArray(item.cache_probe?.existing_url_cache_dirs)
      ? item.cache_probe.existing_url_cache_dirs
      : []

    if (sourceKind === 'youtube_url' && item.kind !== 'youtube_url') {
      failedChecks.push('material_manifest_candidate_not_youtube')
    }
    if (sourceKind === 'youtube_url' && item.url !== sourceCandidate.url && item.webpage_url !== sourceCandidate.url) {
      failedChecks.push('material_manifest_candidate_url_mismatch')
    }
    if (sourceKind === 'youtube_url' && item.video_id !== sourceCandidate.video_id) {
      failedChecks.push('material_manifest_candidate_video_id_mismatch')
    }
    if (
      sourceKind === 'local_video_srt' &&
      item.downloaded_video_path !== (sourceCandidate.downloaded_video_path ?? sourceCandidate.video_path)
    ) {
      failedChecks.push('material_manifest_candidate_video_path_mismatch')
    }
    if (sourceKind === 'local_video_srt' && item.subtitle_path !== sourceCandidate.subtitle_path) {
      failedChecks.push('material_manifest_candidate_subtitle_path_mismatch')
    }
    if (sourceKind === 'local_video_srt') {
      if (!Number.isInteger(item.video_bytes) || item.video_bytes <= 0) {
        failedChecks.push('material_manifest_candidate_video_bytes_missing')
      } else if (item.video_bytes !== sourceCandidate.video_bytes) {
        failedChecks.push('material_manifest_candidate_video_bytes_mismatch')
      }
      if (!Number.isInteger(item.subtitle_bytes) || item.subtitle_bytes <= 0) {
        failedChecks.push('material_manifest_candidate_subtitle_bytes_missing')
      } else if (item.subtitle_bytes !== sourceCandidate.subtitle_bytes) {
        failedChecks.push('material_manifest_candidate_subtitle_bytes_mismatch')
      }
      if (!item.video_sha256 || !/^[a-f0-9]{64}$/i.test(item.video_sha256)) {
        failedChecks.push('material_manifest_candidate_video_sha256_missing')
      } else if (item.video_sha256 !== sourceCandidate.video_sha256) {
        failedChecks.push('material_manifest_candidate_video_sha256_mismatch')
      }
      if (!item.subtitle_sha256 || !/^[a-f0-9]{64}$/i.test(item.subtitle_sha256)) {
        failedChecks.push('material_manifest_candidate_subtitle_sha256_missing')
      } else if (item.subtitle_sha256 !== sourceCandidate.subtitle_sha256) {
        failedChecks.push('material_manifest_candidate_subtitle_sha256_mismatch')
      }
    }
    if (item.source_fingerprint !== sourceCandidate.source_fingerprint) {
      failedChecks.push('material_manifest_candidate_fingerprint_mismatch')
    }
    if (item.cache_probe?.status !== sourceCandidate.cache_probe_status) {
      failedChecks.push('material_manifest_candidate_cache_probe_mismatch')
    }
  }

  if (materialManifest?.cache_policy?.cold_path_rule) {
    summary.cold_path_rule = materialManifest.cache_policy.cold_path_rule
  }

  if (sourceKind === 'local_video_srt') {
    summary.file_evidence = {
      video: null,
      subtitle: null,
    }
    const videoPath = sourceCandidate.downloaded_video_path ?? sourceCandidate.video_path
    if (videoPath) {
      try {
        const videoEvidence = await collectFileEvidence(videoPath)
        summary.file_evidence.video = videoEvidence
        if (videoEvidence.bytes !== sourceCandidate.video_bytes) {
          failedChecks.push('local_srt_video_bytes_mismatch')
        }
        if (videoEvidence.sha256 !== sourceCandidate.video_sha256) {
          failedChecks.push('local_srt_video_sha256_mismatch')
        }
      } catch (error) {
        failedChecks.push('local_srt_video_file_unreadable')
        summary.file_evidence.video_error = error instanceof Error ? error.message : String(error)
      }
    }
    if (sourceCandidate.subtitle_path) {
      try {
        const subtitleEvidence = await collectFileEvidence(sourceCandidate.subtitle_path)
        summary.file_evidence.subtitle = subtitleEvidence
        if (subtitleEvidence.bytes !== sourceCandidate.subtitle_bytes) {
          failedChecks.push('local_srt_subtitle_bytes_mismatch')
        }
        if (subtitleEvidence.sha256 !== sourceCandidate.subtitle_sha256) {
          failedChecks.push('local_srt_subtitle_sha256_mismatch')
        }
      } catch (error) {
        failedChecks.push('local_srt_subtitle_file_unreadable')
        summary.file_evidence.subtitle_error = error instanceof Error ? error.message : String(error)
      }
    }
  }

  return {
    ok: failedChecks.length === 0,
    failedChecks,
    warnings,
    summary,
  }
}

async function buildPreflight(args) {
  const failedChecks = []
  const warnings = []

  const manifest = await readJson(args.caseManifestPath)
  let launcherReadiness = null
  let launcherReadinessError = null
  try {
    launcherReadiness = launcherReadinessFrom(await readJson(args.launcherReadinessPath))
  } catch (error) {
    launcherReadinessError = error instanceof Error ? error.message : String(error)
    failedChecks.push('launcher_readiness_file_unreadable')
  }

  if (args.computerUseAvailable === null) {
    failedChecks.push('computer_use_availability_flag_missing')
  }

  const domainPreflight = evaluateVideoReleaseCaseStartPreflight({
    caseId: args.caseId,
    manifest,
    launcherReadiness,
    computerUseAvailable: args.computerUseAvailable === true,
    coldCacheReadsDisabled: args.coldCacheReadsDisabled,
  })

  failedChecks.push(...domainPreflight.failedChecks)
  warnings.push(...domainPreflight.warnings)

  let materialManifestCheck = null
  if ((manifest.source_kind === 'youtube_url' || manifest.source_kind === 'local_video_srt') && manifest.source_candidate?.material_manifest) {
    materialManifestCheck = await checkMaterialManifest(manifest.source_candidate, manifest.source_kind)
    failedChecks.push(...materialManifestCheck.failedChecks)
    warnings.push(...materialManifestCheck.warnings)
  }
  const cacheTimingPlan = buildVideoReleaseCaseCacheTimingPlan({
    caseId: args.caseId,
    manifest,
    coldCacheReadsDisabled: args.coldCacheReadsDisabled,
    sourceCacheProbeStatus: materialManifestCheck?.summary?.cache_probe_status,
    existingUrlCacheDirs: materialManifestCheck?.summary?.existing_url_cache_dirs ?? [],
  })

  const uniqueFailedChecks = [...new Set(failedChecks)]
  const uniqueWarnings = [...new Set(warnings)]

  return {
    schema_version: 1,
    created_at: new Date().toISOString(),
    status: uniqueFailedChecks.length === 0 ? 'ready_to_start' : 'blocked',
    matrix_pass_created: false,
    case_id: args.caseId,
    run_dir: args.runDir,
    case_manifest_path: args.caseManifestPath,
    launcher_readiness_path: args.launcherReadinessPath,
    launcher_readiness_error: launcherReadinessError,
    inputs: {
      computer_use_available_explicit: args.computerUseAvailable !== null,
      computer_use_available: args.computerUseAvailable === true,
      cold_cache_reads_disabled: args.coldCacheReadsDisabled,
    },
    preflight: {
      ok: uniqueFailedChecks.length === 0,
      failed_checks: uniqueFailedChecks,
      warnings: uniqueWarnings,
      required_evidence: domainPreflight.requiredEvidence,
    },
    source_candidate: manifest.source_candidate ?? null,
    material_manifest_check: materialManifestCheck
      ? {
          ok: materialManifestCheck.ok,
          failed_checks: materialManifestCheck.failedChecks,
          warnings: materialManifestCheck.warnings,
          summary: materialManifestCheck.summary,
      }
      : null,
    cache_timing_plan: cacheTimingPlan,
    notes:
      'This is a start preflight only. It does not prove generation, APKG export, Anki import, media playback, audio audit, timing, cache, or screenshots.',
  }
}

async function writePreflight(outputPath, result, overwrite) {
  await mkdir(path.dirname(outputPath), { recursive: true })
  await writeFile(outputPath, `${JSON.stringify(result, null, 2)}\n`, {
    encoding: 'utf8',
    flag: overwrite ? 'w' : 'wx',
  })
}

try {
  const args = parseArgs(process.argv.slice(2))
  const outputPathChecks = await preflightOutputPathChecks(args)
  const result = outputPathChecks.length > 0 ? outputPathBlockedReport(args, outputPathChecks) : await buildPreflight(args)
  if (args.outputPath && outputPathChecks.length === 0) {
    await writePreflight(args.outputPath, result, args.overwrite)
  }
  console.log(JSON.stringify(result, null, 2))
  process.exit(result.preflight.ok ? 0 : 2)
} catch (error) {
  console.error(error instanceof Error ? error.message : error)
  process.exit(1)
}
