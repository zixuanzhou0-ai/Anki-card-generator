import type {
  VideoReleaseCaseId,
  VideoReleaseCaseManifest,
  VideoReleaseScreenshotEvidence,
} from '../domain/releaseEvidenceLayout.ts'
import {
  VIDEO_RELEASE_CASES,
  VIDEO_RELEASE_RUN_DIR_PREFIX,
  VIDEO_RELEASE_RUN_STAMP_PATTERN,
  evaluateVideoReleaseCaseCompletionEvidence,
} from '../domain/releaseEvidenceLayout.ts'

type ScreenshotInputRecord = VideoReleaseScreenshotEvidence & Record<string, unknown>

export type ReleaseScreenshotManifestArtifact = {
  schema_version: 1
  case_id: VideoReleaseCaseId
  session_id: string
  count: number
  screenshots: Array<{
    screenshot_id: string
    session_id: string
    card_index: number
    path: string
    relative_path: string
    sha256: string
    size_bytes: number
    mtime_ms: number
  }>
}

export type BuildReleaseScreenshotManifestArtifactInput = {
  caseId: VideoReleaseCaseId
  manifest: VideoReleaseCaseManifest
  sessionId: string
  screenshots: ScreenshotInputRecord[]
}

export type ReleaseScreenshotManifestArtifactResult = {
  ok: boolean
  status: 'ready_for_write_plan' | 'blocked'
  matrixPassCreated: false
  failedChecks: string[]
  warnings: string[]
  artifactPath: string
  screenshotFiles: VideoReleaseScreenshotEvidence[]
  screenshotManifest: ReleaseScreenshotManifestArtifact | null
  notes: string
}

export type ReleaseScreenshotManifestArtifactWrite = {
  kind: 'screenshot_manifest'
  relativePath: string
  absolutePath: string
  content: string
  writeMode: 'exclusive_create'
}

export type BuildReleaseScreenshotManifestArtifactWritePlanInput =
  BuildReleaseScreenshotManifestArtifactInput & {
    runDir: string
  }

export type ReleaseScreenshotManifestArtifactWritePlan = {
  ok: boolean
  status: 'ready_to_write' | 'blocked'
  matrixPassCreated: false
  failedChecks: string[]
  warnings: string[]
  runDir: string
  caseDir: string
  screenshotsDir: string
  artifactPath: string
  writes: ReleaseScreenshotManifestArtifactWrite[]
  notes: string
}

function unique(values: string[]) {
  return [...new Set(values)]
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function numberValue(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function positiveIntegerValue(value: unknown): number | null {
  const numeric = numberValue(value)
  return numeric !== null && Number.isInteger(numeric) && numeric > 0 ? numeric : null
}

function firstStringValue(record: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = stringValue(record[key])
    if (value) {
      return value
    }
  }
  return ''
}

function firstPositiveNumberValue(record: Record<string, unknown>, keys: string[]): number | null {
  for (const key of keys) {
    const value = positiveIntegerValue(record[key])
    if (value !== null) {
      return value
    }
  }
  return null
}

function isSha256Hex(value: string): boolean {
  return /^[a-f0-9]{64}$/i.test(value)
}

function pathSegments(value: string): string[] {
  return value.split(/[\\/]+/).filter(Boolean)
}

function pathHasTraversal(value: string): boolean {
  return pathSegments(value).some((segment) => segment === '..')
}

function pathLooksAbsolute(value: string): boolean {
  return /^[A-Za-z]:[\\/]/.test(value) || value.startsWith('\\\\') || value.startsWith('/')
}

function normalizeRelativePath(value: string): string {
  return value.replace(/\\/g, '/').replace(/^\/+/, '').replace(/\/+/g, '/').replace(/\/$/, '')
}

function pathTail(value: string): string {
  const normalized = value.replace(/\\/g, '/')
  return normalized.split('/').filter(Boolean).at(-1) ?? normalized
}

function runDirNameFromPath(value: string): string {
  return pathSegments(value).at(-1) ?? ''
}

function isReleaseRunDirName(value: string): boolean {
  return value.startsWith(VIDEO_RELEASE_RUN_DIR_PREFIX) && VIDEO_RELEASE_RUN_STAMP_PATTERN.test(value.slice(VIDEO_RELEASE_RUN_DIR_PREFIX.length))
}

function joinRunRelativePath(runDir: string, relativePath: string): string {
  const separator = runDir.includes('\\') ? '\\' : '/'
  const cleanRunDir = runDir.replace(/[\\/]+$/, '')
  return [cleanRunDir, ...normalizeRelativePath(relativePath).split('/')].join(separator)
}

function comparePath(value: string): string {
  return value.replace(/\\/g, '/').replace(/\/+/g, '/').replace(/\/$/, '').toLowerCase()
}

function pathIsInsideDirectory(pathValue: string, directory: string): boolean {
  return comparePath(pathValue).startsWith(`${comparePath(directory)}/`)
}

function screenshotManifestArtifactPath(caseId: VideoReleaseCaseId): string {
  return `cases/${caseId}/screenshots/manifest.json`
}

function canonicalScreenshotRelativePath(caseId: VideoReleaseCaseId, fileName: string): string {
  return `cases/${caseId}/screenshots/${fileName}`
}

function isImageFileName(value: string): boolean {
  return /\.(png|jpe?g|webp)$/i.test(value)
}

function validateRunDir(runDir: string, failedChecks: string[]) {
  if (!runDir) {
    failedChecks.push('run_dir_missing')
    return
  }
  if (!pathLooksAbsolute(runDir)) {
    failedChecks.push('run_dir_not_absolute')
  }
  if (pathHasTraversal(runDir)) {
    failedChecks.push('run_dir_path_unsafe')
  }
  if (!isReleaseRunDirName(runDirNameFromPath(runDir))) {
    failedChecks.push('run_dir_not_release_hardening_dir')
  }
}

function validateScreenshotManifestRelativePath({
  relativePath,
  caseId,
  failedChecks,
}: {
  relativePath: string
  caseId: VideoReleaseCaseId
  failedChecks: string[]
}) {
  const normalized = normalizeRelativePath(relativePath)
  if (pathLooksAbsolute(relativePath) || pathHasTraversal(relativePath)) {
    failedChecks.push('screenshot_manifest_artifact_path_unsafe')
  }
  if (normalized !== screenshotManifestArtifactPath(caseId)) {
    failedChecks.push('screenshot_manifest_artifact_path_mismatch')
  }
}

function jsonContent(value: unknown): string {
  return `${JSON.stringify(value, null, 2)}\n`
}

function releaseCaseById(caseId: VideoReleaseCaseId) {
  return VIDEO_RELEASE_CASES.find((releaseCase) => releaseCase.id === caseId)
}

function completionExpectedCards(caseId: VideoReleaseCaseId): number {
  const releaseCase = releaseCaseById(caseId)
  return releaseCase && 'minimumGeneratedCards' in releaseCase ? releaseCase.minimumGeneratedCards : (releaseCase?.targetCardCount ?? 0)
}

function requiredScreenshotIndices(caseId: VideoReleaseCaseId): number[] {
  const releaseCase = releaseCaseById(caseId)
  if (!releaseCase) {
    return []
  }
  if (releaseCase.inspection === 'all_cards') {
    return Array.from({ length: releaseCase.requiredPreviewCards }, (_, index) => index + 1)
  }
  return []
}

function hasStressSampleCoverage(caseId: VideoReleaseCaseId, indices: Set<number>): boolean {
  const releaseCase = releaseCaseById(caseId)
  if (releaseCase?.inspection !== 'sample_open_middle_end') {
    return true
  }
  const hasStart = [...indices].some((index) => index <= 4)
  const hasMiddle = [...indices].some((index) => index >= 45 && index <= 60)
  const hasEnd = [...indices].some((index) => index >= 97)
  return hasStart && hasMiddle && hasEnd
}

function screenshotCardIndex(record: Record<string, unknown>): number | null {
  return (
    positiveIntegerValue(record.card_index) ??
    positiveIntegerValue(record.cardIndex) ??
    positiveIntegerValue(record.index)
  )
}

function screenshotFileName(record: Record<string, unknown>): string {
  const candidate = firstStringValue(record, [
    'filename',
    'name',
    'file',
    'path',
    'absolute_path',
    'absolutePath',
    'relative_path',
    'relativePath',
    'screenshot',
    'screenshot_file',
    'screenshot_path',
  ])
  return pathTail(candidate)
}

function screenshotEvidencePath(record: Record<string, unknown>, caseId: VideoReleaseCaseId, fileName: string): string {
  const relativePath = firstStringValue(record, ['relative_path', 'relativePath'])
  if (relativePath) {
    return normalizeRelativePath(relativePath)
  }
  return canonicalScreenshotRelativePath(caseId, fileName)
}

function screenshotEvidenceSha256(record: Record<string, unknown>): string {
  return firstStringValue(record, ['sha256', 'screenshot_sha256', 'file_sha256', 'hash']).toLowerCase()
}

function screenshotEvidenceSize(record: Record<string, unknown>): number | null {
  return firstPositiveNumberValue(record, ['size_bytes', 'sizeBytes', 'bytes'])
}

function screenshotEvidenceMtime(record: Record<string, unknown>): number | null {
  return firstPositiveNumberValue(record, ['mtime_ms', 'mtimeMs', 'modified_time_ms'])
}

function screenshotId(record: Record<string, unknown>, cardIndex: number, fileName: string): string {
  return firstStringValue(record, ['screenshot_id', 'screenshotId', 'id']) || `card-${cardIndex}-${fileName.replace(/\W+/g, '-').replace(/^-|-$/g, '')}`
}

function normalizeScreenshots({
  caseId,
  sessionId,
  screenshots,
  failedChecks,
}: {
  caseId: VideoReleaseCaseId
  sessionId: string
  screenshots: ScreenshotInputRecord[]
  failedChecks: string[]
}): {
  screenshotFiles: VideoReleaseScreenshotEvidence[]
  screenshotManifest: ReleaseScreenshotManifestArtifact
} {
  const releaseCase = releaseCaseById(caseId)
  const expectedCards = completionExpectedCards(caseId)
  const screenshotFiles: VideoReleaseScreenshotEvidence[] = []
  const manifestScreenshots: ReleaseScreenshotManifestArtifact['screenshots'] = []
  const seenFileNames = new Set<string>()
  const seenCardIndices = new Set<number>()
  const seenScreenshotIds = new Set<string>()

  screenshots.forEach((record, index) => {
    const cardIndex = screenshotCardIndex(record)
    const fileName = screenshotFileName(record)
    const relativePath = fileName ? screenshotEvidencePath(record, caseId, fileName) : ''
    const sha256 = screenshotEvidenceSha256(record)
    const sizeBytes = screenshotEvidenceSize(record)
    const mtimeMs = screenshotEvidenceMtime(record)

    if (cardIndex === null || cardIndex < 1 || cardIndex > expectedCards) {
      failedChecks.push('screenshot_manifest_card_index_invalid')
    }
    if (!fileName || pathHasTraversal(fileName) || pathLooksAbsolute(fileName) || fileName.toLowerCase() === 'manifest.json') {
      failedChecks.push('screenshot_manifest_file_name_invalid')
    }
    if (fileName && !isImageFileName(fileName)) {
      failedChecks.push('screenshot_manifest_file_extension_invalid')
    }
    if (!relativePath || pathHasTraversal(relativePath) || pathLooksAbsolute(relativePath)) {
      failedChecks.push('screenshot_manifest_relative_path_unsafe')
    }
    if (relativePath && normalizeRelativePath(relativePath) !== canonicalScreenshotRelativePath(caseId, fileName)) {
      failedChecks.push('screenshot_manifest_relative_path_mismatch')
    }
    if (!isSha256Hex(sha256)) {
      failedChecks.push('screenshot_manifest_sha256_missing')
    }
    if (sizeBytes === null) {
      failedChecks.push('screenshot_manifest_size_bytes_missing')
    }
    if (mtimeMs === null) {
      failedChecks.push('screenshot_manifest_mtime_ms_missing')
    }
    const entrySessionId = firstStringValue(record, ['session_id', 'sessionId', 'computer_use_session_id', 'computerUseSessionId'])
    if (entrySessionId && entrySessionId !== sessionId) {
      failedChecks.push('screenshot_manifest_session_id_mismatch')
    }

    const lowerFileName = fileName.toLowerCase()
    if (lowerFileName && seenFileNames.has(lowerFileName)) {
      failedChecks.push('screenshot_manifest_file_reused_for_multiple_card_indices')
    }
    if (lowerFileName) {
      seenFileNames.add(lowerFileName)
    }
    if (cardIndex !== null) {
      if (seenCardIndices.has(cardIndex)) {
        failedChecks.push('screenshot_manifest_duplicate_card_index')
      }
      seenCardIndices.add(cardIndex)
    }
    const id = cardIndex === null ? `invalid-screenshot-${index + 1}` : screenshotId(record, cardIndex, fileName)
    if (seenScreenshotIds.has(id)) {
      failedChecks.push('screenshot_manifest_duplicate_screenshot_id')
    }
    seenScreenshotIds.add(id)

    if (cardIndex !== null && fileName && relativePath && isSha256Hex(sha256) && sizeBytes !== null && mtimeMs !== null) {
      screenshotFiles.push({
        path: firstStringValue(record, ['path', 'absolute_path', 'absolutePath']) || fileName,
        relative_path: relativePath,
        sha256,
        size_bytes: sizeBytes,
        mtime_ms: mtimeMs,
      })
      manifestScreenshots.push({
        screenshot_id: id,
        session_id: sessionId,
        card_index: cardIndex,
        path: fileName,
        relative_path: relativePath,
        sha256,
        size_bytes: sizeBytes,
        mtime_ms: mtimeMs,
      })
    }
  })

  if (releaseCase && manifestScreenshots.length < releaseCase.requiredPreviewCards) {
    failedChecks.push('screenshots_below_required_preview_count')
  }
  for (const requiredIndex of requiredScreenshotIndices(caseId)) {
    if (!seenCardIndices.has(requiredIndex)) {
      failedChecks.push('screenshot_manifest_missing_required_card_indices')
      break
    }
  }
  if (!hasStressSampleCoverage(caseId, seenCardIndices)) {
    failedChecks.push('screenshot_manifest_stress_sample_coverage_missing')
  }

  return {
    screenshotFiles,
    screenshotManifest: {
      schema_version: 1,
      case_id: caseId,
      session_id: sessionId,
      count: manifestScreenshots.length,
      screenshots: manifestScreenshots,
    },
  }
}

function isScreenshotArtifactBlockingCheck(check: string): boolean {
  return (
    check === 'case_manifest_id_mismatch' ||
    check === 'case_manifest_target_card_count_mismatch' ||
    check === 'case_manifest_required_preview_cards_mismatch' ||
    check.startsWith('screenshots_') ||
    check.startsWith('screenshot_manifest_')
  )
}

export function buildReleaseScreenshotManifestArtifact(
  input: BuildReleaseScreenshotManifestArtifactInput,
): ReleaseScreenshotManifestArtifactResult {
  const failedChecks: string[] = []
  const releaseCase = releaseCaseById(input.caseId)
  const sessionId = stringValue(input.sessionId)
  if (!releaseCase) {
    failedChecks.push('release_case_unknown')
  }
  if (!sessionId) {
    failedChecks.push('screenshot_manifest_session_id_missing')
  }
  if (input.manifest.case_id !== input.caseId) {
    failedChecks.push('screenshot_manifest_manifest_case_id_mismatch')
  }
  if (releaseCase && input.manifest.target_card_count !== releaseCase.targetCardCount) {
    failedChecks.push('screenshot_manifest_manifest_target_card_count_mismatch')
  }
  if (releaseCase && input.manifest.required_preview_cards !== releaseCase.requiredPreviewCards) {
    failedChecks.push('screenshot_manifest_manifest_required_preview_cards_mismatch')
  }

  const normalized = normalizeScreenshots({
    caseId: input.caseId,
    sessionId,
    screenshots: input.screenshots,
    failedChecks,
  })

  const completion = evaluateVideoReleaseCaseCompletionEvidence({
    caseId: input.caseId,
    manifest: input.manifest,
    screenshotFiles: normalized.screenshotFiles,
    screenshotManifest: normalized.screenshotManifest,
  })
  failedChecks.push(...completion.failedChecks.filter(isScreenshotArtifactBlockingCheck))

  const uniqueFailedChecks = unique(failedChecks)
  return {
    ok: uniqueFailedChecks.length === 0,
    status: uniqueFailedChecks.length === 0 ? 'ready_for_write_plan' : 'blocked',
    matrixPassCreated: false,
    failedChecks: uniqueFailedChecks,
    warnings: completion.warnings,
    artifactPath: screenshotManifestArtifactPath(input.caseId),
    screenshotFiles: uniqueFailedChecks.length === 0 ? normalized.screenshotFiles : [],
    screenshotManifest: uniqueFailedChecks.length === 0 ? normalized.screenshotManifest : null,
    notes:
      'Pure screenshot manifest artifact guard only. It validates existing case-local screenshot file identity and prepares screenshots/manifest.json, but it does not capture images, write files, create observations/actions, import into Anki, or claim a matrix pass.',
  }
}

export function buildReleaseScreenshotManifestArtifactWritePlan(
  input: BuildReleaseScreenshotManifestArtifactWritePlanInput,
): ReleaseScreenshotManifestArtifactWritePlan {
  const runDir = stringValue(input.runDir)
  const failedChecks: string[] = []
  validateRunDir(runDir, failedChecks)

  const artifact = buildReleaseScreenshotManifestArtifact(input)
  failedChecks.push(...artifact.failedChecks)
  validateScreenshotManifestRelativePath({
    relativePath: artifact.artifactPath,
    caseId: input.caseId,
    failedChecks,
  })

  const caseDir = runDir ? joinRunRelativePath(runDir, `cases/${input.caseId}`) : ''
  const screenshotsDir = runDir ? joinRunRelativePath(runDir, `cases/${input.caseId}/screenshots`) : ''
  const manifestPath = runDir ? joinRunRelativePath(runDir, artifact.artifactPath) : ''
  if (caseDir && screenshotsDir && !pathIsInsideDirectory(screenshotsDir, caseDir)) {
    failedChecks.push('screenshots_dir_outside_case_dir')
  }
  if (screenshotsDir && manifestPath && !pathIsInsideDirectory(manifestPath, screenshotsDir)) {
    failedChecks.push('screenshot_manifest_absolute_path_outside_screenshots_dir')
  }

  const uniqueFailedChecks = unique(failedChecks)
  const writes: ReleaseScreenshotManifestArtifactWrite[] =
    uniqueFailedChecks.length === 0 && artifact.screenshotManifest
      ? [
          {
            kind: 'screenshot_manifest',
            relativePath: artifact.artifactPath,
            absolutePath: manifestPath,
            content: jsonContent(artifact.screenshotManifest),
            writeMode: 'exclusive_create',
          },
        ]
      : []

  return {
    ok: uniqueFailedChecks.length === 0,
    status: uniqueFailedChecks.length === 0 ? 'ready_to_write' : 'blocked',
    matrixPassCreated: false,
    failedChecks: uniqueFailedChecks,
    warnings: artifact.warnings,
    runDir,
    caseDir,
    screenshotsDir,
    artifactPath: artifact.artifactPath,
    writes,
    notes:
      'Pure write plan only. A caller may persist screenshots/manifest.json with exclusive-create semantics after screenshot image files already exist, but this plan does not capture images, create observations/actions, import into Anki, or claim a matrix pass.',
  }
}
