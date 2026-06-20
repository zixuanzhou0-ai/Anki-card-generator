import type {
  VideoReleaseCaseId,
  VideoReleaseCaseManifest,
  VideoReleaseScreenshotEvidence,
} from '../domain/releaseEvidenceLayout.ts'
import {
  VIDEO_RELEASE_PLAYBACK_CHECKS,
  VIDEO_RELEASE_RUN_DIR_PREFIX,
  VIDEO_RELEASE_RUN_STAMP_PATTERN,
  evaluateVideoReleaseCaseCompletionEvidence,
} from '../domain/releaseEvidenceLayout.ts'

type PlaybackRole = (typeof VIDEO_RELEASE_PLAYBACK_CHECKS)[number]

export type ReleaseComputerUseObservationsArtifact = {
  schema_version: 1
  case_id: VideoReleaseCaseId
  session_id: string
  count: number
  previewed_cards: number
  observed_cards: number
  observations: Record<string, unknown>[]
}

export type ReleaseComputerUseActionsArtifact = {
  schema_version: 1
  case_id: VideoReleaseCaseId
  session_id: string
  previewed_cards: number
  observed_cards: number
  playback_counts: Record<PlaybackRole, number>
  generation_clicks?: number
  actions: Record<string, unknown>[]
}

export type BuildReleaseComputerUseArtifactsInput = {
  caseId: VideoReleaseCaseId
  manifest: VideoReleaseCaseManifest
  sessionId: string
  observations: Record<string, unknown>[]
  computerUseActions: Record<string, unknown>[]
  screenshotManifest: Record<string, unknown> | null
  screenshotFiles?: Array<string | VideoReleaseScreenshotEvidence>
  previewedCards?: number
  generationClicks?: number
}

export type ReleaseComputerUseArtifactsResult = {
  ok: boolean
  status: 'ready_for_write_plan' | 'blocked'
  matrixPassCreated: false
  failedChecks: string[]
  warnings: string[]
  artifactPaths: {
    observations: string
    computer_use_actions: string
  }
  observations: ReleaseComputerUseObservationsArtifact | null
  computerUseActions: ReleaseComputerUseActionsArtifact | null
  notes: string
}

export type ReleaseComputerUseArtifactWrite = {
  kind: 'observations' | 'computer_use_actions'
  relativePath: string
  absolutePath: string
  content: string
  writeMode: 'exclusive_create'
}

export type BuildReleaseComputerUseArtifactWritePlanInput = BuildReleaseComputerUseArtifactsInput & {
  runDir: string
}

export type ReleaseComputerUseArtifactWritePlan = {
  ok: boolean
  status: 'ready_to_write' | 'blocked'
  matrixPassCreated: false
  failedChecks: string[]
  warnings: string[]
  runDir: string
  caseDir: string
  artifactPaths: ReleaseComputerUseArtifactsResult['artifactPaths']
  writes: ReleaseComputerUseArtifactWrite[]
  notes: string
}

const PLAYBACK_ROLE_ALIASES: Record<PlaybackRole, readonly string[]> = {
  video: ['video'],
  original_audio: ['original_audio', 'original'],
  sentence_tts: ['sentence_tts', 'slow_tts'],
  phrase_tts: ['phrase_tts', 'expression_tts'],
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

function objectRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {}
}

function isSha256Hex(value: string): boolean {
  return /^[a-f0-9]{64}$/i.test(value)
}

function screenshotEvidenceSha256(value: string | VideoReleaseScreenshotEvidence): string {
  if (typeof value === 'string') {
    return ''
  }
  return stringValue(value.sha256 ?? value.screenshot_sha256 ?? value.file_sha256 ?? value.hash).toLowerCase()
}

function screenshotFilesMissingHashEvidence(screenshotFiles: Array<string | VideoReleaseScreenshotEvidence>): boolean {
  return screenshotFiles.some((file) => !isSha256Hex(screenshotEvidenceSha256(file)))
}

function normalizePlaybackRole(value: unknown): PlaybackRole | null {
  const role = stringValue(value).toLowerCase()
  for (const playbackRole of VIDEO_RELEASE_PLAYBACK_CHECKS) {
    if (PLAYBACK_ROLE_ALIASES[playbackRole].includes(role)) {
      return playbackRole
    }
  }
  return null
}

function actionCardIndex(action: Record<string, unknown>): number | null {
  return (
    positiveIntegerValue(action.card_index) ??
    positiveIntegerValue(action.cardIndex) ??
    positiveIntegerValue(action.index)
  )
}

function previewedCardsFromActions(actions: Record<string, unknown>[]): number {
  return new Set(actions.map(actionCardIndex).filter((value): value is number => value !== null)).size
}

function countPlaybackActions(actions: Record<string, unknown>[]): Record<PlaybackRole, number> {
  const counts = {
    video: 0,
    original_audio: 0,
    sentence_tts: 0,
    phrase_tts: 0,
  }
  for (const action of actions) {
    const role = normalizePlaybackRole(action.role ?? action.target_role)
    if (role) {
      counts[role] += 1
    }
  }
  return counts
}

function observationActionArtifactPaths(caseId: VideoReleaseCaseId) {
  return {
    observations: `cases/${caseId}/observations.json`,
    computer_use_actions: `cases/${caseId}/computer_use_actions.json`,
  }
}

function isComputerUseArtifactBlockingCheck(check: string): boolean {
  return (
    check === 'case_manifest_id_mismatch' ||
    check === 'case_manifest_target_card_count_mismatch' ||
    check === 'case_manifest_required_preview_cards_mismatch' ||
    check.startsWith('screenshots_') ||
    check.startsWith('screenshot_manifest_') ||
    check.startsWith('observations_') ||
    check.startsWith('computer_use_')
  )
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

function runDirNameFromPath(value: string): string {
  return pathSegments(value).at(-1) ?? ''
}

function isReleaseRunDirName(value: string): boolean {
  if (!value.startsWith(VIDEO_RELEASE_RUN_DIR_PREFIX)) {
    return false
  }
  return VIDEO_RELEASE_RUN_STAMP_PATTERN.test(value.slice(VIDEO_RELEASE_RUN_DIR_PREFIX.length))
}

function normalizeRelativePath(value: string): string {
  return value.replace(/\\/g, '/').replace(/^\/+/, '').replace(/\/+/g, '/')
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

function validateComputerUseRelativePath({
  kind,
  relativePath,
  caseId,
  failedChecks,
}: {
  kind: ReleaseComputerUseArtifactWrite['kind']
  relativePath: string
  caseId: VideoReleaseCaseId
  failedChecks: string[]
}) {
  const normalized = normalizeRelativePath(relativePath)
  const expectedFile = kind === 'observations' ? 'observations.json' : 'computer_use_actions.json'
  if (pathLooksAbsolute(relativePath) || pathHasTraversal(relativePath)) {
    failedChecks.push(`${kind}_artifact_path_unsafe`)
  }
  if (normalized !== `cases/${caseId}/${expectedFile}`) {
    failedChecks.push(`${kind}_artifact_path_mismatch`)
  }
}

function jsonContent(value: unknown): string {
  return `${JSON.stringify(value, null, 2)}\n`
}

export function buildReleaseComputerUseArtifacts(
  input: BuildReleaseComputerUseArtifactsInput,
): ReleaseComputerUseArtifactsResult {
  const sessionId = stringValue(input.sessionId)
  const observationsRows = input.observations.map(objectRecord)
  const actionRows = input.computerUseActions.map(objectRecord)
  const previewedCards = input.previewedCards ?? previewedCardsFromActions(actionRows)
  const artifactPaths = observationActionArtifactPaths(input.caseId)
  const observations: ReleaseComputerUseObservationsArtifact = {
    schema_version: 1,
    case_id: input.caseId,
    session_id: sessionId,
    count: observationsRows.length,
    previewed_cards: observationsRows.length,
    observed_cards: observationsRows.length,
    observations: observationsRows,
  }
  const computerUseActions: ReleaseComputerUseActionsArtifact = {
    schema_version: 1,
    case_id: input.caseId,
    session_id: sessionId,
    previewed_cards: previewedCards,
    observed_cards: previewedCards,
    playback_counts: countPlaybackActions(actionRows),
    actions: actionRows,
  }
  if (typeof input.generationClicks === 'number') {
    computerUseActions.generation_clicks = input.generationClicks
  }

  const failedChecks: string[] = []
  if (screenshotFilesMissingHashEvidence(input.screenshotFiles ?? [])) {
    failedChecks.push('computer_use_screenshot_file_sha256_missing')
  }

  const completion = evaluateVideoReleaseCaseCompletionEvidence({
    caseId: input.caseId,
    manifest: input.manifest,
    screenshotFiles: input.screenshotFiles ?? [],
    observations,
    computerUseActions,
    screenshotManifest: input.screenshotManifest,
  })
  failedChecks.push(...completion.failedChecks.filter(isComputerUseArtifactBlockingCheck))

  const uniqueFailedChecks = unique(failedChecks)
  return {
    ok: uniqueFailedChecks.length === 0,
    status: uniqueFailedChecks.length === 0 ? 'ready_for_write_plan' : 'blocked',
    matrixPassCreated: false,
    failedChecks: uniqueFailedChecks,
    warnings: completion.warnings,
    artifactPaths,
    observations: uniqueFailedChecks.length === 0 ? observations : null,
    computerUseActions: uniqueFailedChecks.length === 0 ? computerUseActions : null,
    notes:
      'Pure Computer Use artifact builder only. It validates observations/actions against the final verifier screenshot/session/action-link contract, but it does not write files, create screenshots, import into Anki, update manifests, or claim a matrix pass.',
  }
}

export function buildReleaseComputerUseArtifactWritePlan(
  input: BuildReleaseComputerUseArtifactWritePlanInput,
): ReleaseComputerUseArtifactWritePlan {
  const runDir = stringValue(input.runDir)
  const failedChecks: string[] = []
  validateRunDir(runDir, failedChecks)

  const artifacts = buildReleaseComputerUseArtifacts(input)
  failedChecks.push(...artifacts.failedChecks)

  validateComputerUseRelativePath({
    kind: 'observations',
    relativePath: artifacts.artifactPaths.observations,
    caseId: input.caseId,
    failedChecks,
  })
  validateComputerUseRelativePath({
    kind: 'computer_use_actions',
    relativePath: artifacts.artifactPaths.computer_use_actions,
    caseId: input.caseId,
    failedChecks,
  })

  const caseDir = runDir ? joinRunRelativePath(runDir, `cases/${input.caseId}`) : ''
  const observationsPath = runDir ? joinRunRelativePath(runDir, artifacts.artifactPaths.observations) : ''
  const computerUseActionsPath = runDir
    ? joinRunRelativePath(runDir, artifacts.artifactPaths.computer_use_actions)
    : ''
  if (caseDir && observationsPath && !pathIsInsideDirectory(observationsPath, caseDir)) {
    failedChecks.push('observations_absolute_path_outside_case_dir')
  }
  if (caseDir && computerUseActionsPath && !pathIsInsideDirectory(computerUseActionsPath, caseDir)) {
    failedChecks.push('computer_use_actions_absolute_path_outside_case_dir')
  }

  const uniqueFailedChecks = unique(failedChecks)
  const writes: ReleaseComputerUseArtifactWrite[] =
    uniqueFailedChecks.length === 0 && artifacts.observations && artifacts.computerUseActions
      ? [
          {
            kind: 'observations',
            relativePath: artifacts.artifactPaths.observations,
            absolutePath: observationsPath,
            content: jsonContent(artifacts.observations),
            writeMode: 'exclusive_create',
          },
          {
            kind: 'computer_use_actions',
            relativePath: artifacts.artifactPaths.computer_use_actions,
            absolutePath: computerUseActionsPath,
            content: jsonContent(artifacts.computerUseActions),
            writeMode: 'exclusive_create',
          },
        ]
      : []

  return {
    ok: uniqueFailedChecks.length === 0,
    status: uniqueFailedChecks.length === 0 ? 'ready_to_write' : 'blocked',
    matrixPassCreated: false,
    failedChecks: uniqueFailedChecks,
    warnings: artifacts.warnings,
    runDir,
    caseDir,
    artifactPaths: artifacts.artifactPaths,
    writes,
    notes:
      'Pure write plan only. A caller may persist observations.json and computer_use_actions.json with exclusive-create semantics, but this plan does not write files, create screenshots, update manifests, import into Anki, or claim a matrix pass.',
  }
}
