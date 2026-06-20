import { stat } from 'node:fs/promises'
import path from 'node:path'

import {
  VIDEO_RELEASE_CASES,
  VIDEO_RELEASE_CASE_EVIDENCE_ITEMS,
  VIDEO_RELEASE_RUN_DIR_PREFIX,
  VIDEO_RELEASE_RUN_STAMP_PATTERN,
  VIDEO_RELEASE_TOP_LEVEL_EVIDENCE_ITEMS,
} from '../src/domain/releaseEvidenceLayout.ts'

const RESERVED_EVIDENCE_FILENAMES = new Set(
  [
    ...VIDEO_RELEASE_TOP_LEVEL_EVIDENCE_ITEMS,
    ...VIDEO_RELEASE_CASE_EVIDENCE_ITEMS.filter((item) => item.kind === 'file').map((item) => path.basename(item.relativePath)),
  ].map((fileName) => fileName.toLowerCase()),
)

const RESERVED_EVIDENCE_DIRECTORIES = VIDEO_RELEASE_CASE_EVIDENCE_ITEMS.filter((item) => item.kind === 'directory').map(
  (item) => item.relativePath,
)

export function pathSegments(value) {
  return String(value ?? '')
    .split(/[\\/]+/)
    .filter(Boolean)
}

export function normalizeForCompare(filePath) {
  return path.resolve(filePath).replace(/\\/g, '/').replace(/\/$/, '').toLowerCase()
}

function normalizedPathSegments(value) {
  return normalizeForCompare(value).split('/').filter(Boolean)
}

function pathMatchesOrIsInside(childPath, parentPath) {
  const relativePath = path.relative(path.resolve(parentPath), path.resolve(childPath))
  return !relativePath || (!relativePath.startsWith('..') && !path.isAbsolute(relativePath))
}

function isReleaseRunDirName(value) {
  return (
    value.startsWith(VIDEO_RELEASE_RUN_DIR_PREFIX) &&
    VIDEO_RELEASE_RUN_STAMP_PATTERN.test(value.slice(VIDEO_RELEASE_RUN_DIR_PREFIX.length))
  )
}

function findReleaseRunAncestor(filePath) {
  let current = path.resolve(filePath)
  while (current && path.dirname(current) !== current) {
    if (isReleaseRunDirName(path.basename(current))) {
      return current
    }
    current = path.dirname(current)
  }
  return isReleaseRunDirName(path.basename(current)) ? current : null
}

function releaseRunFromCaseManifest(caseManifestPath, caseId) {
  if (!caseManifestPath) {
    return null
  }
  const manifestPath = path.resolve(caseManifestPath)
  if (path.basename(manifestPath).toLowerCase() !== 'case_manifest.json') {
    return null
  }
  const caseDir = path.dirname(manifestPath)
  if (path.basename(caseDir) !== caseId) {
    return null
  }
  const casesDir = path.dirname(caseDir)
  if (path.basename(casesDir).toLowerCase() !== 'cases') {
    return null
  }
  return path.dirname(casesDir)
}

function uniquePaths(paths) {
  const seen = new Set()
  const result = []
  for (const filePath of paths.filter(Boolean)) {
    const key = normalizeForCompare(filePath)
    if (!seen.has(key)) {
      seen.add(key)
      result.push(filePath)
    }
  }
  return result
}

function canonicalFinalEvidencePaths(runDir) {
  return [
    ...VIDEO_RELEASE_TOP_LEVEL_EVIDENCE_ITEMS.map((relativePath) => path.join(runDir, relativePath)),
    ...VIDEO_RELEASE_CASES.flatMap((releaseCase) =>
      VIDEO_RELEASE_CASE_EVIDENCE_ITEMS.filter((item) => item.kind === 'file').map((item) =>
        path.join(runDir, 'cases', releaseCase.id, item.relativePath),
      ),
    ),
  ]
}

function checkName(prefix, suffix) {
  return `${prefix}_output_${suffix}`
}

export async function releaseReportOutputPathChecks({
  prefix,
  outputPath,
  outputPathInput = outputPath,
  overwrite = false,
  runDir = null,
  caseId = null,
  caseManifestPath = null,
  includeSelectedCaseManifestDir = false,
  inferRunDirFromCaseManifest = false,
  inferRunDirFromOutput = false,
  allowCanonicalPreflightStart = false,
}) {
  const failedChecks = []
  if (!outputPath) {
    return failedChecks
  }

  if (pathSegments(outputPathInput ?? outputPath).some((segment) => segment === '..')) {
    failedChecks.push(checkName(prefix, 'path_unsafe'))
  }

  const fileName = path.basename(outputPath).toLowerCase()
  if (!fileName.endsWith('.json')) {
    failedChecks.push(checkName(prefix, 'not_json'))
  }
  if (RESERVED_EVIDENCE_FILENAMES.has(fileName)) {
    failedChecks.push(checkName(prefix, 'reserved_evidence_filename'))
  }

  const resolvedOutputPath = path.resolve(outputPath)
  const explicitRunDir = runDir ? path.resolve(runDir) : null
  const runDirFromCaseManifest =
    inferRunDirFromCaseManifest && caseId ? releaseRunFromCaseManifest(caseManifestPath, caseId) : null
  const resolvedRunDir =
    explicitRunDir ?? runDirFromCaseManifest ?? (inferRunDirFromOutput ? findReleaseRunAncestor(resolvedOutputPath) : null)
  const selectedCaseDir = includeSelectedCaseManifestDir && caseManifestPath ? path.dirname(caseManifestPath) : null
  const canonicalCaseDirs = resolvedRunDir
    ? VIDEO_RELEASE_CASES.map((releaseCase) => path.join(resolvedRunDir, 'cases', releaseCase.id))
    : []
  const caseDirs = uniquePaths([...canonicalCaseDirs, selectedCaseDir])

  let isAllowedCaseLocalNonDiagnosticsPath = false
  if (allowCanonicalPreflightStart && resolvedRunDir && caseId && caseManifestPath) {
    const canonicalCaseManifestPath = path.join(resolvedRunDir, 'cases', caseId, 'case_manifest.json')
    const caseManifestMatchesCanonicalRun = normalizeForCompare(caseManifestPath) === normalizeForCompare(canonicalCaseManifestPath)
    const allowedPreflightStartPath = path.join(resolvedRunDir, 'cases', caseId, 'preflight_start.json')
    isAllowedCaseLocalNonDiagnosticsPath =
      caseManifestMatchesCanonicalRun && normalizeForCompare(resolvedOutputPath) === normalizeForCompare(allowedPreflightStartPath)
  }

  if (resolvedRunDir) {
    if (
      canonicalFinalEvidencePaths(resolvedRunDir).some(
        (evidencePath) => normalizeForCompare(evidencePath) === normalizeForCompare(resolvedOutputPath),
      )
    ) {
      failedChecks.push(checkName(prefix, 'matches_final_evidence_path'))
    }
  }

  for (const caseDir of caseDirs) {
    for (const relativeDir of RESERVED_EVIDENCE_DIRECTORIES) {
      if (pathMatchesOrIsInside(resolvedOutputPath, path.join(caseDir, relativeDir))) {
        failedChecks.push(checkName(prefix, 'inside_reserved_evidence_directory'))
      }
    }
  }

  const segments = normalizedPathSegments(resolvedOutputPath)
  if (
    caseDirs.some((caseDir) => pathMatchesOrIsInside(resolvedOutputPath, caseDir)) &&
    !segments.includes('diagnostics') &&
    !isAllowedCaseLocalNonDiagnosticsPath
  ) {
    failedChecks.push(checkName(prefix, 'inside_case_without_diagnostics_dir'))
  }

  try {
    const outputStat = await stat(resolvedOutputPath)
    if (outputStat.isDirectory()) {
      failedChecks.push(checkName(prefix, 'not_file'))
    }
    if (!overwrite) {
      failedChecks.push(checkName(prefix, 'already_exists'))
    }
  } catch (error) {
    if (error?.code !== 'ENOENT') {
      failedChecks.push(checkName(prefix, 'access_error'))
    }
  }

  return [...new Set(failedChecks)]
}
