import { createHash } from 'node:crypto'
import { constants as fsConstants } from 'node:fs'
import { access, mkdir, readFile, stat, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

import { buildReleaseObservedSourceProvenanceSnapshotFromJson } from '../src/app/releaseEvidenceSourceProvenance.ts'
import { buildReleaseObservedTimingCacheInputSnapshotFromJson } from '../src/app/releaseEvidenceObservedInput.ts'
import {
  VIDEO_RELEASE_CASES,
  VIDEO_RELEASE_RUN_DIR_PREFIX,
  VIDEO_RELEASE_RUN_STAMP_PATTERN,
} from '../src/domain/releaseEvidenceLayout.ts'

const DIAGNOSTIC_FILE_NAMES = {
  observed: 'observed_raw.final.json',
  screenshots: 'screenshots.raw.final.json',
  computerUse: 'computer_use.raw.final.json',
}

function usage() {
  return [
    'Usage:',
    '  node scripts/capture_video_release_case_observed_artifacts.mjs --run-dir PATH --case CASE_ID [inputs] [--dry-run|--write]',
    '',
    'Collects raw release case outputs into guarded final-shaped observed JSON diagnostics.',
    'With --write, it writes only diagnostics plus anki_verify.stdout.json when APKG identity matches the canonical case APKG.',
    'Default mode is dry-run. Existing files are never overwritten.',
    '',
    'Inputs:',
    '  --observed PATH                  optional raw observed JSON envelope or prior app snapshot',
    '  --learning-point PATH           full learning-point result JSON',
    '  --project PATH                  full project JSON',
    '  --export PATH                   full APKG export result JSON',
    '  --anki-verify PATH              Anki import verification result JSON',
    '  --screenshots PATH              raw screenshot rows/envelope for the screenshot manifest writer',
    '  --computer-use PATH             raw observation/action rows for the Computer Use writer',
    '  --verified-apkg-path PATH       explicit verified APKG path reported by the Anki pass',
    '',
    'Options:',
    '  --run-dir PATH                  video_release_hardening_YYYYMMDD_HHMMSS run directory',
    '  --case CASE_ID                  matrix case id, e.g. local_srt_full1_cold',
    '  --label LABEL                   diagnostics subdirectory label, default: final',
    '  --session-id ID                 Computer Use session id for screenshot/action envelopes',
    '  --cold-cache-reads-disabled     mark controllable cache reads disabled for cold runs',
    '  --source-cache-probe-status S   observed source cache probe status',
    '  --existing-url-cache-dir PATH   repeatable observed URL cache directory',
    '  --job-id ID                     repeatable generation/export job id',
    '  --dry-run                       validate and print planned writes without writing files',
    '  --write                         persist planned writes using write-once exclusive create',
  ].join('\n')
}

function parseArgs(argv) {
  const args = {
    runDir: null,
    resolvedRunDir: null,
    caseId: null,
    label: 'final',
    observedPath: null,
    learningPointPath: null,
    projectPath: null,
    exportPath: null,
    ankiVerifyPath: null,
    screenshotsPath: null,
    computerUsePath: null,
    verifiedApkgPath: null,
    sessionId: null,
    coldCacheReadsDisabled: undefined,
    sourceCacheProbeStatus: null,
    existingUrlCacheDirs: [],
    jobIds: [],
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
    if (arg === '--cold-cache-reads-disabled') {
      args.coldCacheReadsDisabled = true
      continue
    }
    if (arg === '--cold-cache-reads-enabled') {
      args.coldCacheReadsDisabled = false
      continue
    }

    if (
      [
        '--run-dir',
        '--case',
        '--label',
        '--observed',
        '--learning-point',
        '--project',
        '--export',
        '--anki-verify',
        '--screenshots',
        '--computer-use',
        '--verified-apkg-path',
        '--session-id',
        '--source-cache-probe-status',
        '--existing-url-cache-dir',
        '--job-id',
      ].includes(arg)
    ) {
      const value = argv[index + 1]
      if (!value) {
        throw new Error(`${arg} requires a value`)
      }
      if (arg === '--run-dir') {
        args.runDir = value
        args.resolvedRunDir = path.resolve(value)
      } else if (arg === '--case') {
        args.caseId = value
      } else if (arg === '--label') {
        args.label = value
      } else if (arg === '--observed') {
        args.observedPath = path.resolve(value)
      } else if (arg === '--learning-point') {
        args.learningPointPath = path.resolve(value)
      } else if (arg === '--project') {
        args.projectPath = path.resolve(value)
      } else if (arg === '--export') {
        args.exportPath = path.resolve(value)
      } else if (arg === '--anki-verify') {
        args.ankiVerifyPath = path.resolve(value)
      } else if (arg === '--screenshots') {
        args.screenshotsPath = path.resolve(value)
      } else if (arg === '--computer-use') {
        args.computerUsePath = path.resolve(value)
      } else if (arg === '--verified-apkg-path') {
        args.verifiedApkgPath = value
      } else if (arg === '--session-id') {
        args.sessionId = value
      } else if (arg === '--source-cache-probe-status') {
        args.sourceCacheProbeStatus = value
      } else if (arg === '--existing-url-cache-dir') {
        args.existingUrlCacheDirs.push(value)
      } else if (arg === '--job-id') {
        args.jobIds.push(value)
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

function isRecord(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function unique(values) {
  return [...new Set(values.filter(Boolean))]
}

function stringValue(value) {
  return typeof value === 'string' && value.trim() ? value.trim() : ''
}

function stringArrayValue(value) {
  return Array.isArray(value) ? value.filter((item) => typeof item === 'string' && item.trim()) : []
}

function firstValue(...values) {
  return values.find((value) => typeof value !== 'undefined')
}

function finitePositiveNumber(value) {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? Math.round(value) : null
}

function sha256Value(value) {
  return typeof value === 'string' && /^[a-f0-9]{64}$/i.test(value.trim()) ? value.trim().toLowerCase() : ''
}

function pathSegments(value) {
  return String(value ?? '')
    .split(/[\\/]+/)
    .filter(Boolean)
}

function normalizeRelativePath(value) {
  return String(value ?? '')
    .replace(/\\/g, '/')
    .replace(/^\/+/, '')
    .replace(/\/+/g, '/')
    .replace(/\/$/, '')
}

function normalizeForCompare(filePath) {
  return path.resolve(filePath).replace(/\\/g, '/').replace(/\/$/, '').toLowerCase()
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

function summarizeWrite(write) {
  return {
    kind: write.kind,
    relative_path: write.relativePath,
    absolute_path: write.absolutePath,
    bytes: Buffer.byteLength(write.content, 'utf8'),
    write_mode: 'exclusive_create',
  }
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

function validateLabel(label) {
  if (!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/.test(label)) {
    return ['diagnostics_label_invalid']
  }
  if (label === '.' || label === '..') {
    return ['diagnostics_label_invalid']
  }
  return []
}

async function pathExists(filePath) {
  try {
    await access(filePath, fsConstants.F_OK)
    return true
  } catch {
    return false
  }
}

async function initializedDirectoryChecks({ runDir, caseDir }) {
  const failedChecks = []
  if (!(await pathExists(runDir))) failedChecks.push('run_dir_missing')
  if (!(await pathExists(caseDir))) failedChecks.push('case_dir_missing')
  if (!(await pathExists(path.join(caseDir, 'case_manifest.json')))) failedChecks.push('case_manifest_missing')
  return failedChecks
}

async function readJsonDetailed(filePath, missingCheck, unreadableCheck) {
  if (!filePath) {
    return { value: null, failedChecks: [missingCheck], error: null, sourceFile: null }
  }
  let bytes
  let fileStat
  try {
    bytes = await readFile(filePath)
    fileStat = await stat(filePath)
  } catch (error) {
    const code = error?.code
    return {
      value: null,
      failedChecks: [code === 'ENOENT' ? missingCheck : unreadableCheck],
      error: error instanceof Error ? error.message : String(error),
      sourceFile: null,
    }
  }
  const sourceFile = {
    absolute_path: path.resolve(filePath),
    sha256: createHash('sha256').update(bytes).digest('hex'),
    size_bytes: fileStat.size,
    mtime_ms: Math.round(fileStat.mtimeMs),
  }
  try {
    const text = bytes.toString('utf8').replace(/^\uFEFF/, '')
    return { value: JSON.parse(text), failedChecks: [], error: null, sourceFile }
  } catch (error) {
    return {
      value: null,
      failedChecks: [unreadableCheck],
      error: error instanceof Error ? error.message : String(error),
      sourceFile,
    }
  }
}

async function optionalJson(filePath, missingCheck, unreadableCheck) {
  if (!filePath) return { provided: false, value: null, failedChecks: [], error: null }
  const read = await readJsonDetailed(filePath, missingCheck, unreadableCheck)
  return { provided: true, ...read }
}

function componentFromJson(value, keys) {
  if (!isRecord(value)) return value
  const nested = firstValue(...keys.map((key) => value[key]))
  return typeof nested === 'undefined' ? value : nested
}

function canonicalObservedFromBase(base) {
  const observed = isRecord(base) ? base : {}
  return {
    case_id: firstValue(observed.case_id, observed.caseId),
    learning_point_result: firstValue(observed.learning_point_result, observed.learningPointResult),
    project: observed.project,
    export_result: firstValue(observed.export_result, observed.exportResult),
    anki_verify_result: firstValue(observed.anki_verify_result, observed.ankiVerifyResult),
    verified_export_apkg_path: firstValue(observed.verified_export_apkg_path, observed.verifiedExportApkgPath),
    cold_cache_reads_disabled: firstValue(observed.cold_cache_reads_disabled, observed.coldCacheReadsDisabled),
    source_cache_probe_status: firstValue(observed.source_cache_probe_status, observed.sourceCacheProbeStatus),
    existing_url_cache_dirs: firstValue(observed.existing_url_cache_dirs, observed.existingUrlCacheDirs),
    job_ids: firstValue(observed.job_ids, observed.jobIds),
  }
}

function normalizeProjectSourceInfo({ project, manifest, normalizations }) {
  if (!isRecord(project)) return project
  const candidate = isRecord(manifest?.source_candidate) ? manifest.source_candidate : null
  const sourceKind = stringValue(firstValue(manifest?.source_kind, manifest?.source))
  if (!['local_video_srt', 'public_video'].includes(sourceKind) || !candidate) return project

  const nextProject = { ...project }
  const sourceInfo = isRecord(nextProject.source_info) ? { ...nextProject.source_info } : {}
  if (!isRecord(nextProject.source_info)) {
    normalizations.push('project_source_info_created_from_manifest_candidate')
  }

  const videoPath = stringValue(firstValue(nextProject.video_path, sourceInfo.video_path, candidate.video_path, candidate.downloaded_video_path))
  const subtitlePath = stringValue(firstValue(nextProject.subtitle_path, sourceInfo.subtitle_path, candidate.subtitle_path))
  const videoFingerprint = stringValue(firstValue(sourceInfo.video_fingerprint, candidate.video_sha256))
  const subtitleFingerprint = stringValue(firstValue(sourceInfo.subtitle_fingerprint, candidate.subtitle_sha256))

  if (!stringValue(nextProject.video_path) && videoPath) {
    nextProject.video_path = videoPath
    normalizations.push('project_video_path_from_manifest_candidate')
  }
  if (!stringValue(nextProject.subtitle_path) && subtitlePath) {
    nextProject.subtitle_path = subtitlePath
    normalizations.push('project_subtitle_path_from_manifest_candidate')
  }
  if (!stringValue(sourceInfo.video_path) && videoPath) {
    sourceInfo.video_path = videoPath
    normalizations.push('project_source_info_video_path_from_manifest_candidate')
  }
  if (!stringValue(sourceInfo.subtitle_path) && subtitlePath) {
    sourceInfo.subtitle_path = subtitlePath
    normalizations.push('project_source_info_subtitle_path_from_manifest_candidate')
  }
  if (!stringValue(sourceInfo.video_fingerprint) && sha256Value(videoFingerprint)) {
    sourceInfo.video_fingerprint = sha256Value(videoFingerprint)
    normalizations.push('project_source_info_video_fingerprint_from_manifest_sha256')
  }
  if (!stringValue(sourceInfo.subtitle_fingerprint) && sha256Value(subtitleFingerprint)) {
    sourceInfo.subtitle_fingerprint = sha256Value(subtitleFingerprint)
    normalizations.push('project_source_info_subtitle_fingerprint_from_manifest_sha256')
  }
  if (!stringValue(nextProject.source_mode)) {
    nextProject.source_mode = 'local'
    normalizations.push(`project_source_mode_local_defaulted_for_${sourceKind}`)
  }
  nextProject.source_info = sourceInfo
  return nextProject
}

function normalizeObserved({ args, baseObserved, inputs, manifest, normalizations }) {
  const observed = {
    schema_version: 1,
    case_id: args.caseId,
    ...canonicalObservedFromBase(baseObserved),
  }

  if (inputs.learningPoint.provided) {
    observed.learning_point_result = componentFromJson(inputs.learningPoint.value, [
      'learning_point_result',
      'learningPointResult',
    ])
  }
  if (inputs.project.provided) {
    observed.project = componentFromJson(inputs.project.value, ['project'])
  }
  if (inputs.exportResult.provided) {
    observed.export_result = componentFromJson(inputs.exportResult.value, ['export_result', 'exportResult'])
  }
  if (inputs.ankiVerify.provided) {
    observed.anki_verify_result = componentFromJson(inputs.ankiVerify.value, [
      'anki_verify_result',
      'ankiVerifyResult',
    ])
  }

  if (isRecord(observed.project)) {
    observed.project = normalizeProjectSourceInfo({ project: observed.project, manifest, normalizations })
  }
  if (args.verifiedApkgPath) {
    observed.verified_export_apkg_path = args.verifiedApkgPath
  }
  if (!stringValue(observed.verified_export_apkg_path)) {
    observed.verified_export_apkg_path = stringValue(
      firstValue(observed.anki_verify_result?.apkg_path, observed.export_result?.apkg_path),
    )
    if (observed.verified_export_apkg_path) {
      normalizations.push('verified_export_apkg_path_from_observed_apkg_path')
    }
  }
  if (typeof args.coldCacheReadsDisabled === 'boolean') {
    observed.cold_cache_reads_disabled = args.coldCacheReadsDisabled
  }
  if (args.sourceCacheProbeStatus) {
    observed.source_cache_probe_status = args.sourceCacheProbeStatus
  } else if (!stringValue(observed.source_cache_probe_status)) {
    const cacheProbeStatus = stringValue(manifest?.source_candidate?.cache_probe_status)
    if (cacheProbeStatus) {
      observed.source_cache_probe_status = cacheProbeStatus
      normalizations.push('source_cache_probe_status_from_manifest_candidate')
    }
  }
  if (args.existingUrlCacheDirs.length > 0) {
    observed.existing_url_cache_dirs = args.existingUrlCacheDirs
  } else {
    observed.existing_url_cache_dirs = stringArrayValue(observed.existing_url_cache_dirs)
  }
  if (args.jobIds.length > 0) {
    observed.job_ids = args.jobIds
  } else {
    observed.job_ids = stringArrayValue(observed.job_ids)
  }

  return Object.fromEntries(
    Object.entries(observed).filter(([, value]) => typeof value !== 'undefined' && value !== null && value !== ''),
  )
}

function extractRows(root, keys, nestedKeys) {
  if (Array.isArray(root)) return root
  if (!isRecord(root)) return []
  for (const key of keys) {
    if (Array.isArray(root[key])) return root[key]
  }
  for (const nestedKey of nestedKeys) {
    if (!isRecord(root[nestedKey])) continue
    for (const key of keys) {
      if (Array.isArray(root[nestedKey][key])) return root[nestedKey][key]
    }
  }
  return []
}

function sessionIdFrom(root, fallback) {
  if (!isRecord(root)) return stringValue(fallback)
  return stringValue(
    firstValue(
      root.session_id,
      root.sessionId,
      root.computer_use_session_id,
      root.computerUseSessionId,
      root.screenshot_manifest?.session_id,
      root.screenshotManifest?.sessionId,
      fallback,
    ),
  )
}

function addSessionIdToRows(rows, sessionId) {
  if (!sessionId) return rows
  return rows.map((row) => {
    if (!isRecord(row)) return row
    if (stringValue(firstValue(row.session_id, row.sessionId, row.computer_use_session_id, row.computerUseSessionId))) {
      return row
    }
    return { ...row, session_id: sessionId }
  })
}

function normalizeScreenshotsRaw({ args, raw, sourceFile }) {
  const sessionId = sessionIdFrom(raw, args.sessionId)
  const rows = extractRows(
    raw,
    ['screenshots', 'files', 'items', 'screenshot_files', 'screenshotFiles'],
    ['screenshot_manifest', 'screenshotManifest', 'screenshots_manifest', 'screenshotsManifest'],
  )
  return {
    schema_version: 1,
    case_id: args.caseId,
    ...(sessionId ? { session_id: sessionId } : {}),
    screenshots: addSessionIdToRows(rows, sessionId),
    adapter_diagnostics: {
      source_path: args.screenshotsPath,
      ...(sourceFile ? { source_file: sourceFile } : {}),
      row_count: rows.length,
      matrix_pass_created: false,
    },
  }
}

function normalizeComputerUseRaw({ args, raw, sourceFile }) {
  const sessionId = sessionIdFrom(raw, args.sessionId)
  const observations = extractRows(raw, ['observations', 'observationRows', 'observation_rows'], [])
  const actions = extractRows(
    raw,
    ['computer_use_actions', 'computerUseActionRows', 'computer_use_action_rows'],
    ['computer_use_actions', 'computerUseActions'],
  )
  return {
    schema_version: 1,
    case_id: args.caseId,
    ...(sessionId ? { session_id: sessionId } : {}),
    observations: addSessionIdToRows(observations, sessionId),
    computer_use_actions: addSessionIdToRows(actions, sessionId),
    adapter_diagnostics: {
      source_path: args.computerUsePath,
      ...(sourceFile ? { source_file: sourceFile } : {}),
      observation_count: observations.length,
      action_count: actions.length,
      matrix_pass_created: false,
    },
  }
}

async function canonicalApkgEvidence({ runDir, caseId }) {
  const absolutePath = path.join(runDir, 'cases', caseId, 'apkg', `${caseId}.apkg`)
  const relativePath = normalizeRelativePath(path.relative(runDir, absolutePath))
  try {
    const bytes = await readFile(absolutePath)
    const fileStat = await stat(absolutePath)
    return {
      evidence: {
        absolutePath,
        relativePath,
        sha256: createHash('sha256').update(bytes).digest('hex'),
        sizeBytes: fileStat.size,
        mtimeMs: Math.round(fileStat.mtimeMs),
      },
      failedChecks: [],
      errors: {},
    }
  } catch (error) {
    return {
      evidence: null,
      failedChecks: [error?.code === 'ENOENT' ? 'canonical_apkg_missing' : 'canonical_apkg_unreadable'],
      errors: {
        canonical_apkg: error instanceof Error ? error.message : String(error),
      },
    }
  }
}

function apkgFieldIdentityChecks({ label, value, apkgEvidence, runDir }) {
  const failedChecks = []
  if (!isRecord(value)) {
    failedChecks.push(`${label}_missing`)
    return failedChecks
  }
  const apkgPath = resolveReportedPath(value.apkg_path, runDir)
  if (!apkgPath) {
    failedChecks.push(`${label}_apkg_path_missing`)
  } else if (normalizeForCompare(apkgPath) !== normalizeForCompare(apkgEvidence.absolutePath)) {
    failedChecks.push(`${label}_apkg_path_mismatch`)
  }
  const relativePath = normalizeRelativePath(value.apkg_relative_path)
  if (relativePath && relativePath.toLowerCase() !== apkgEvidence.relativePath.toLowerCase()) {
    failedChecks.push(`${label}_apkg_relative_path_mismatch`)
  }
  const sha256 = sha256Value(value.apkg_sha256)
  if (!sha256) {
    failedChecks.push(`${label}_apkg_sha256_missing`)
  } else if (sha256 !== apkgEvidence.sha256) {
    failedChecks.push(`${label}_apkg_sha256_mismatch`)
  }
  const sizeBytes = finitePositiveNumber(value.apkg_size_bytes)
  if (sizeBytes === null) {
    failedChecks.push(`${label}_apkg_size_bytes_missing`)
  } else if (sizeBytes !== apkgEvidence.sizeBytes) {
    failedChecks.push(`${label}_apkg_size_bytes_mismatch`)
  }
  const mtimeMs = finitePositiveNumber(value.apkg_mtime_ms)
  if (mtimeMs === null) {
    failedChecks.push(`${label}_apkg_mtime_ms_missing`)
  } else if (Math.abs(mtimeMs - apkgEvidence.mtimeMs) > 1) {
    failedChecks.push(`${label}_apkg_mtime_ms_mismatch`)
  }
  return failedChecks
}

function sourceFingerprintFrom(value) {
  if (!isRecord(value)) return ''
  const direct = stringValue(value.source_fingerprint)
  if (direct) return direct
  const sourceIdentity = value.source_identity
  if (!isRecord(sourceIdentity)) return ''
  return stringValue(sourceIdentity.source_fingerprint)
}

function sourceIdentityChecks({ exportResult, ankiVerify }) {
  const failedChecks = []
  const exportSourceFingerprint = sourceFingerprintFrom(exportResult)
  const verifySourceFingerprint = sourceFingerprintFrom(ankiVerify)
  if (exportSourceFingerprint && !verifySourceFingerprint) {
    failedChecks.push('anki_verify_source_fingerprint_missing')
  } else if (
    exportSourceFingerprint &&
    verifySourceFingerprint &&
    exportSourceFingerprint !== verifySourceFingerprint
  ) {
    failedChecks.push('anki_verify_source_fingerprint_mismatch')
  }
  return failedChecks
}

export function releaseSourceFingerprintFromManifest(manifest) {
  if (!isRecord(manifest)) return ''
  const sourceCandidate = manifest.source_candidate
  if (!isRecord(sourceCandidate)) return ''
  return stringValue(sourceCandidate.source_fingerprint)
}

function ankiVerifyChecks({ observed, apkgEvidence, runDir }) {
  const failedChecks = []
  const exportResult = observed.export_result
  const ankiVerify = observed.anki_verify_result
  if (!isRecord(ankiVerify)) {
    failedChecks.push('anki_verify_result_missing')
    return failedChecks
  }
  if (ankiVerify.ok !== true) {
    failedChecks.push('anki_verify_result_not_ok')
  }
  if (!Array.isArray(ankiVerify.failed_checks) || ankiVerify.failed_checks.length > 0) {
    failedChecks.push('anki_verify_failed_checks_present')
  }
  failedChecks.push(...apkgFieldIdentityChecks({ label: 'anki_verify', value: ankiVerify, apkgEvidence, runDir }))
  const verifiedPath = resolveReportedPath(observed.verified_export_apkg_path, runDir)
  if (!verifiedPath) {
    failedChecks.push('verified_export_apkg_path_missing')
  } else if (normalizeForCompare(verifiedPath) !== normalizeForCompare(apkgEvidence.absolutePath)) {
    failedChecks.push('verified_export_apkg_path_mismatch')
  }
  if (isRecord(exportResult)) {
    failedChecks.push(...apkgFieldIdentityChecks({ label: 'export_result', value: exportResult, apkgEvidence, runDir }))
    failedChecks.push(...sourceIdentityChecks({ exportResult, ankiVerify }))
    const exportCards = finitePositiveNumber(exportResult.cards)
    const verifyCards = finitePositiveNumber(ankiVerify.card_count)
    if (exportCards !== null && verifyCards !== null && exportCards !== verifyCards) {
      failedChecks.push('anki_verify_card_count_mismatch')
    }
  }
  return failedChecks
}

export function buildAnkiVerifyWrite({ runDir, caseId, manifest, observed, apkgEvidence }) {
  if (!isRecord(observed.anki_verify_result)) return null
  const releaseSourceFingerprint = releaseSourceFingerprintFromManifest(manifest)
  const exportSourceFingerprint = sourceFingerprintFrom(observed.export_result)
  const verifySourceFingerprint = sourceFingerprintFrom(observed.anki_verify_result)
  const ankiVerify = {
    ...observed.anki_verify_result,
    case_id: caseId,
    source_fingerprint: releaseSourceFingerprint,
    apkg_path: apkgEvidence.absolutePath,
    apkg_relative_path: apkgEvidence.relativePath,
    apkg_sha256: apkgEvidence.sha256,
    apkg_size_bytes: apkgEvidence.sizeBytes,
    apkg_mtime_ms: apkgEvidence.mtimeMs,
    ...(exportSourceFingerprint ? { export_source_fingerprint: exportSourceFingerprint } : {}),
    ...(verifySourceFingerprint ? { worker_source_fingerprint: verifySourceFingerprint } : {}),
    ...(isRecord(observed.export_result?.source_identity) && !isRecord(observed.anki_verify_result?.source_identity)
      ? { source_identity: observed.export_result.source_identity }
      : {}),
  }
  return {
    kind: 'anki_verify_stdout',
    relativePath: normalizeRelativePath(path.join('cases', caseId, 'anki_verify.stdout.json')),
    absolutePath: path.join(runDir, 'cases', caseId, 'anki_verify.stdout.json'),
    content: `${JSON.stringify(ankiVerify, null, 2)}\n`,
  }
}

export function existingAnkiVerifyArtifactIdentityChecks({ artifact, caseId, releaseSourceFingerprint }) {
  if (!isRecord(artifact)) return ['existing_anki_verify_stdout_not_object']
  const failedChecks = []
  if (artifact.case_id !== caseId) {
    failedChecks.push('existing_anki_verify_stdout_case_id_mismatch')
  }
  if (releaseSourceFingerprint) {
    const artifactSourceFingerprint = stringValue(artifact.source_fingerprint)
    if (!artifactSourceFingerprint) {
      failedChecks.push('existing_anki_verify_stdout_source_fingerprint_missing')
    } else if (artifactSourceFingerprint !== releaseSourceFingerprint) {
      failedChecks.push('existing_anki_verify_stdout_source_fingerprint_mismatch')
    }
  }
  return failedChecks
}

function diagnosticWrite({ runDir, caseId, label, kind, fileName, value }) {
  return {
    kind,
    relativePath: normalizeRelativePath(path.join('cases', caseId, 'diagnostics', `capture_observed_${label}`, fileName)),
    absolutePath: path.join(runDir, 'cases', caseId, 'diagnostics', `capture_observed_${label}`, fileName),
    content: `${JSON.stringify(value, null, 2)}\n`,
  }
}

async function existingWriteChecks(writes, { caseId = '', releaseSourceFingerprint = '' } = {}) {
  const failedChecks = []
  const errors = {}
  for (const write of writes) {
    try {
      await access(write.absolutePath, fsConstants.F_OK)
      failedChecks.push(`${write.kind}_artifact_already_exists`)
      if (write.kind === 'anki_verify_stdout') {
        try {
          const text = await readFile(write.absolutePath, 'utf8')
          const artifact = JSON.parse(text)
          failedChecks.push(
            ...existingAnkiVerifyArtifactIdentityChecks({
              artifact,
              caseId,
              releaseSourceFingerprint,
            }),
          )
        } catch (error) {
          const parseOrReadCheck =
            error instanceof SyntaxError
              ? 'existing_anki_verify_stdout_json_parse_error'
              : 'existing_anki_verify_stdout_unreadable'
          failedChecks.push(parseOrReadCheck)
          errors.existing_anki_verify_stdout = error instanceof Error ? error.message : String(error)
        }
      }
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
  writtenFiles = [],
  notes,
}) {
  const caseDir = args.resolvedRunDir ? path.join(args.resolvedRunDir, 'cases', args.caseId ?? '') : null
  return {
    schema_version: 1,
    created_at: new Date().toISOString(),
    status: 'blocked',
    matrix_pass_created: false,
    release_case_evidence: false,
    case_id: args.caseId,
    run_dir: args.runDir,
    diagnostic_dir: caseDir ? path.join(caseDir, 'diagnostics', `capture_observed_${args.label}`) : null,
    canonical_case_manifest_path: caseDir ? path.join(caseDir, 'case_manifest.json') : null,
    canonical_anki_verify_stdout_path: caseDir ? path.join(caseDir, 'anki_verify.stdout.json') : null,
    write_requested: args.write,
    planned_writes: plannedWrites.map(summarizeWrite),
    written_files: writtenFiles,
    writer: {
      ok: false,
      failed_checks: unique(failedChecks),
      warnings: unique(warnings),
      read_errors: readErrors,
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
        'Choose either --dry-run or --write. This command did not write observed diagnostics, Anki stdout, or matrix proof.',
    })
  }
  if (args.overwrite) {
    return blockedResult({
      args,
      failedChecks: ['artifact_overwrite_not_supported'],
      notes:
        'Observed capture artifacts are write-once. This command did not overwrite files or create matrix proof.',
    })
  }

  const runDirChecks = validateRunDirInput(args.runDir)
  const labelChecks = validateLabel(args.label)
  if (runDirChecks.length > 0 || labelChecks.length > 0) {
    return blockedResult({
      args,
      failedChecks: [...runDirChecks, ...labelChecks],
      notes:
        'Run directory or diagnostics label guard failed before reading manifests or raw inputs. No files were written.',
    })
  }

  const caseDir = path.join(args.resolvedRunDir, 'cases', args.caseId)
  const directoryChecks = await initializedDirectoryChecks({ runDir: args.resolvedRunDir, caseDir })
  if (directoryChecks.length > 0) {
    return blockedResult({
      args,
      failedChecks: directoryChecks,
      notes:
        'Initialized release run/case directories are required. This command does not create run skeletons or matrix proof.',
    })
  }

  const caseManifestPath = path.join(caseDir, 'case_manifest.json')
  const manifestRead = await readJsonDetailed(caseManifestPath, 'case_manifest_missing', 'case_manifest_unreadable')
  const baseRead = await optionalJson(args.observedPath, 'observed_missing', 'observed_unreadable')
  const inputs = {
    learningPoint: await optionalJson(args.learningPointPath, 'learning_point_missing', 'learning_point_unreadable'),
    project: await optionalJson(args.projectPath, 'project_missing', 'project_unreadable'),
    exportResult: await optionalJson(args.exportPath, 'export_result_missing', 'export_result_unreadable'),
    ankiVerify: await optionalJson(args.ankiVerifyPath, 'anki_verify_missing', 'anki_verify_unreadable'),
    screenshots: await optionalJson(args.screenshotsPath, 'screenshots_raw_missing', 'screenshots_raw_unreadable'),
    computerUse: await optionalJson(args.computerUsePath, 'computer_use_raw_missing', 'computer_use_raw_unreadable'),
  }

  const readFailedChecks = unique([
    ...manifestRead.failedChecks,
    ...baseRead.failedChecks,
    ...Object.values(inputs).flatMap((read) => read.failedChecks),
  ])
  const readErrors = Object.fromEntries(
    [
      ['case_manifest', manifestRead.error],
      ['observed', baseRead.error],
      ['learning_point', inputs.learningPoint.error],
      ['project', inputs.project.error],
      ['export_result', inputs.exportResult.error],
      ['anki_verify', inputs.ankiVerify.error],
      ['screenshots', inputs.screenshots.error],
      ['computer_use', inputs.computerUse.error],
    ].filter(([, error]) => error),
  )
  if (readFailedChecks.length > 0) {
    return blockedResult({
      args,
      failedChecks: readFailedChecks,
      readErrors,
      notes:
        'Required JSON inputs could not be read. This command did not write observed diagnostics, Anki stdout, or matrix proof.',
    })
  }

  const manifest = isRecord(manifestRead.value) ? manifestRead.value : {}
  const manifestShapeChecks = isRecord(manifestRead.value) ? [] : ['case_manifest_not_object']
  const normalizations = []
  const observed = normalizeObserved({
    args,
    baseObserved: baseRead.value,
    inputs,
    manifest,
    normalizations,
  })
  observed.adapter_diagnostics = {
    schema_version: 1,
    created_at: new Date().toISOString(),
    source_paths: {
      observed: args.observedPath,
      learning_point: args.learningPointPath,
      project: args.projectPath,
      export_result: args.exportPath,
      anki_verify: args.ankiVerifyPath,
      screenshots: args.screenshotsPath,
      computer_use: args.computerUsePath,
    },
    source_files: Object.fromEntries(
      [
        ['case_manifest', manifestRead.sourceFile],
        ['observed', baseRead.sourceFile],
        ['learning_point', inputs.learningPoint.sourceFile],
        ['project', inputs.project.sourceFile],
        ['export_result', inputs.exportResult.sourceFile],
        ['anki_verify', inputs.ankiVerify.sourceFile],
        ['screenshots', inputs.screenshots.sourceFile],
        ['computer_use', inputs.computerUse.sourceFile],
      ].filter(([, sourceFile]) => sourceFile),
    ),
    normalizations: unique(normalizations),
    release_case_evidence: false,
    matrix_pass_created: false,
  }

  const timingSnapshot = buildReleaseObservedTimingCacheInputSnapshotFromJson({
    caseId: args.caseId,
    manifest,
    rawObserved: observed,
  })
  const sourceSnapshot = buildReleaseObservedSourceProvenanceSnapshotFromJson({
    caseId: args.caseId,
    manifest,
    rawObserved: observed,
  })
  const apkgRead = await canonicalApkgEvidence({ runDir: args.resolvedRunDir, caseId: args.caseId })
  observed.adapter_diagnostics.canonical_apkg = apkgRead.evidence
    ? {
        absolute_path: apkgRead.evidence.absolutePath,
        relative_path: apkgRead.evidence.relativePath,
        sha256: apkgRead.evidence.sha256,
        size_bytes: apkgRead.evidence.sizeBytes,
        mtime_ms: apkgRead.evidence.mtimeMs,
      }
    : null
  observed.adapter_diagnostics.canonical_apkg_failed_checks = apkgRead.failedChecks
  const apkgIdentityChecks = apkgRead.evidence
    ? ankiVerifyChecks({ observed, apkgEvidence: apkgRead.evidence, runDir: args.resolvedRunDir })
    : apkgRead.failedChecks

  const diagnosticWrites = [
    diagnosticWrite({
      runDir: args.resolvedRunDir,
      caseId: args.caseId,
      label: args.label,
      kind: 'observed_raw',
      fileName: DIAGNOSTIC_FILE_NAMES.observed,
      value: observed,
    }),
  ]
  if (inputs.screenshots.provided) {
    diagnosticWrites.push(
      diagnosticWrite({
        runDir: args.resolvedRunDir,
        caseId: args.caseId,
        label: args.label,
        kind: 'screenshots_raw',
        fileName: DIAGNOSTIC_FILE_NAMES.screenshots,
        value: normalizeScreenshotsRaw({ args, raw: inputs.screenshots.value, sourceFile: inputs.screenshots.sourceFile }),
      }),
    )
  }
  if (inputs.computerUse.provided) {
    diagnosticWrites.push(
      diagnosticWrite({
        runDir: args.resolvedRunDir,
        caseId: args.caseId,
        label: args.label,
        kind: 'computer_use_raw',
        fileName: DIAGNOSTIC_FILE_NAMES.computerUse,
        value: normalizeComputerUseRaw({ args, raw: inputs.computerUse.value, sourceFile: inputs.computerUse.sourceFile }),
      }),
    )
  }
  const finalWrites = []
  if (apkgRead.evidence && apkgIdentityChecks.length === 0) {
    const ankiVerifyWrite = buildAnkiVerifyWrite({
      runDir: args.resolvedRunDir,
      caseId: args.caseId,
      manifest,
      observed,
      apkgEvidence: apkgRead.evidence,
    })
    if (ankiVerifyWrite) finalWrites.push(ankiVerifyWrite)
  }
  const plannedWrites = [...diagnosticWrites, ...finalWrites]
  const releaseSourceFingerprint = releaseSourceFingerprintFromManifest(manifest)

  const failedChecks = unique([
    ...manifestShapeChecks,
    ...timingSnapshot.failedChecks,
    ...sourceSnapshot.failedChecks,
    ...apkgIdentityChecks,
    ...(releaseSourceFingerprint ? [] : ['case_manifest_source_fingerprint_missing_for_anki_verify']),
    ...(timingSnapshot.matrixPassCreated === false ? [] : ['timing_snapshot_matrix_pass_created_not_false']),
    ...(sourceSnapshot.matrixPassCreated === false ? [] : ['source_snapshot_matrix_pass_created_not_false']),
  ])
  if (!isRecord(observed.learning_point_result)) failedChecks.push('observed_learning_point_result_missing')
  if (!isRecord(observed.project)) failedChecks.push('observed_project_missing')
  if (!isRecord(observed.export_result)) failedChecks.push('observed_export_result_missing')
  if (!isRecord(observed.anki_verify_result)) failedChecks.push('observed_anki_verify_result_missing')

  if (failedChecks.length > 0) {
    const diagnosticExistingChecks = await existingWriteChecks(diagnosticWrites)
    if (diagnosticExistingChecks.failedChecks.length > 0) {
      return blockedResult({
        args,
        failedChecks: diagnosticExistingChecks.failedChecks,
        warnings: unique([...timingSnapshot.warnings, ...sourceSnapshot.warnings]),
        readErrors: diagnosticExistingChecks.errors,
        plannedWrites: diagnosticWrites,
        notes:
          'Exclusive-create preflight refused to overwrite existing observed capture diagnostics. No files were written.',
      })
    }
    if (args.write) {
      const writtenFiles = []
      for (const write of diagnosticWrites) {
        try {
          await mkdir(path.dirname(write.absolutePath), { recursive: true })
          await writeFile(write.absolutePath, write.content, { encoding: 'utf8', flag: 'wx' })
          writtenFiles.push(write.absolutePath)
        } catch (error) {
          return blockedResult({
            args,
            failedChecks: [
              error?.code === 'EEXIST' ? `${write.kind}_artifact_already_exists` : `${write.kind}_artifact_write_error`,
            ],
            warnings: unique([...timingSnapshot.warnings, ...sourceSnapshot.warnings]),
            readErrors: {
              [write.kind]: error instanceof Error ? error.message : String(error),
            },
            plannedWrites: diagnosticWrites,
            writtenFiles,
            notes:
              'A blocked diagnostics write failed during exclusive-create persistence. Any written_files listed were created before the failure; no final evidence or matrix proof was created.',
          })
        }
      }
      return blockedResult({
        args,
        failedChecks,
        warnings: unique([...timingSnapshot.warnings, ...sourceSnapshot.warnings]),
        readErrors: apkgRead.errors,
        plannedWrites: diagnosticWrites,
        writtenFiles,
        notes:
          'Raw observed data is still blocked, so only non-final diagnostics were written. No Anki stdout, final release evidence, or matrix proof was created.',
      })
    }
    return blockedResult({
      args,
      failedChecks,
      warnings: unique([...timingSnapshot.warnings, ...sourceSnapshot.warnings]),
      readErrors: apkgRead.errors,
      plannedWrites: diagnosticWrites,
      notes:
        'Raw observed data is not ready for final release writers. Planned diagnostics are shown, but no files were written and no matrix proof was created.',
    })
  }

  const existingChecks = await existingWriteChecks(plannedWrites, {
    caseId: args.caseId,
    releaseSourceFingerprint,
  })
  if (existingChecks.failedChecks.length > 0) {
    return blockedResult({
      args,
      failedChecks: existingChecks.failedChecks,
      warnings: unique([...timingSnapshot.warnings, ...sourceSnapshot.warnings]),
      readErrors: existingChecks.errors,
      plannedWrites,
      notes:
        'Exclusive-create preflight refused to overwrite existing observed capture artifacts. No files were written.',
    })
  }

  if (!args.write) {
    return {
      schema_version: 1,
      created_at: new Date().toISOString(),
      status: 'ready_to_write',
      matrix_pass_created: false,
      release_case_evidence: false,
      case_id: args.caseId,
      run_dir: args.runDir,
      diagnostic_dir: path.join(caseDir, 'diagnostics', `capture_observed_${args.label}`),
      canonical_case_manifest_path: caseManifestPath,
      canonical_anki_verify_stdout_path: path.join(caseDir, 'anki_verify.stdout.json'),
      canonical_apkg_path: apkgRead.evidence?.absolutePath ?? null,
      write_requested: false,
      planned_writes: plannedWrites.map(summarizeWrite),
      written_files: [],
      writer: {
        ok: true,
        failed_checks: [],
        warnings: unique([...timingSnapshot.warnings, ...sourceSnapshot.warnings]),
        normalizations: unique(normalizations),
        read_errors: {},
      },
      notes:
        'Dry run only. Re-run with --write to persist observed diagnostics and guarded anki_verify.stdout.json with exclusive-create semantics. No matrix proof was created.',
    }
  }

  const writtenFiles = []
  for (const write of plannedWrites) {
    try {
      await mkdir(path.dirname(write.absolutePath), { recursive: true })
      await writeFile(write.absolutePath, write.content, { encoding: 'utf8', flag: 'wx' })
      writtenFiles.push(write.absolutePath)
    } catch (error) {
      return blockedResult({
        args,
        failedChecks: [error?.code === 'EEXIST' ? `${write.kind}_artifact_already_exists` : `${write.kind}_artifact_write_error`],
        warnings: unique([...timingSnapshot.warnings, ...sourceSnapshot.warnings]),
        readErrors: {
          [write.kind]: error instanceof Error ? error.message : String(error),
        },
        plannedWrites,
        notes:
          'A write failed during exclusive-create persistence. Any written_files listed were created before the failure; no matrix proof was created.',
      })
    }
  }

  return {
    schema_version: 1,
    created_at: new Date().toISOString(),
    status: 'written',
    matrix_pass_created: false,
    release_case_evidence: false,
    case_id: args.caseId,
    run_dir: args.runDir,
    diagnostic_dir: path.join(caseDir, 'diagnostics', `capture_observed_${args.label}`),
    canonical_case_manifest_path: caseManifestPath,
    canonical_anki_verify_stdout_path: path.join(caseDir, 'anki_verify.stdout.json'),
    canonical_apkg_path: apkgRead.evidence?.absolutePath ?? null,
    write_requested: true,
    planned_writes: plannedWrites.map(summarizeWrite),
    written_files: writtenFiles,
    writer: {
      ok: true,
      failed_checks: [],
      warnings: unique([...timingSnapshot.warnings, ...sourceSnapshot.warnings]),
      normalizations: unique(normalizations),
      read_errors: {},
    },
    notes:
      'Wrote only observed diagnostics and guarded anki_verify.stdout.json using exclusive-create semantics. This did not update manifests, matrix summaries, APKG, audio, timing/cache, source, deck, Computer Use, screenshot, or observation proof.',
  }
}

async function main() {
  try {
    const args = parseArgs(process.argv.slice(2))
    const result = await buildWriterResult(args)
    console.log(JSON.stringify(result, null, 2))
    process.exit(result.writer.ok ? 0 : 2)
  } catch (error) {
    console.error(error instanceof Error ? error.message : error)
    process.exit(1)
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await main()
}
