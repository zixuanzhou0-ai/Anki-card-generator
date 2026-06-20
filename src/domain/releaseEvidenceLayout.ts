export const VIDEO_RELEASE_RUN_DIR_PREFIX = 'video_release_hardening_'

export const VIDEO_RELEASE_RUN_STAMP_PATTERN = /^\d{8}_\d{6}$/

export const VIDEO_RELEASE_CASES = [
  {
    id: 'youtube_a_full1_cold',
    source: 'youtube_a',
    sourceKind: 'youtube_url',
    mode: 'full',
    cacheState: 'cold',
    targetCardCount: 1,
    requiredPreviewCards: 1,
    inspection: 'all_cards',
  },
  {
    id: 'youtube_a_quick20_cold',
    source: 'youtube_a',
    sourceKind: 'youtube_url',
    mode: 'quick',
    cacheState: 'cold',
    targetCardCount: 20,
    requiredPreviewCards: 20,
    inspection: 'all_cards',
  },
  {
    id: 'youtube_a_quick20_hot',
    source: 'youtube_a',
    sourceKind: 'youtube_url',
    mode: 'quick',
    cacheState: 'hot',
    targetCardCount: 20,
    requiredPreviewCards: 20,
    inspection: 'all_cards',
  },
  {
    id: 'youtube_b_quick20_cold',
    source: 'youtube_b',
    sourceKind: 'youtube_url',
    mode: 'quick',
    cacheState: 'cold',
    targetCardCount: 20,
    requiredPreviewCards: 20,
    inspection: 'all_cards',
  },
  {
    id: 'local_srt_full1_cold',
    source: 'local_video_srt',
    sourceKind: 'local_video_srt',
    mode: 'full',
    cacheState: 'cold',
    targetCardCount: 1,
    requiredPreviewCards: 1,
    inspection: 'all_cards',
  },
  {
    id: 'local_srt_quick20_cold',
    source: 'local_video_srt',
    sourceKind: 'local_video_srt',
    mode: 'quick',
    cacheState: 'cold',
    targetCardCount: 20,
    requiredPreviewCards: 20,
    inspection: 'all_cards',
  },
  {
    id: 'local_srt_quick20_hot',
    source: 'local_video_srt',
    sourceKind: 'local_video_srt',
    mode: 'quick',
    cacheState: 'hot',
    targetCardCount: 20,
    requiredPreviewCards: 20,
    inspection: 'all_cards',
  },
  {
    id: 'stress_100_plus_one_click',
    source: 'public_video',
    sourceKind: 'public_video',
    mode: 'quick',
    cacheState: 'cold',
    targetCardCount: 100,
    minimumGeneratedCards: 100,
    requiredPreviewCards: 10,
    inspection: 'sample_open_middle_end',
  },
] as const

export const VIDEO_RELEASE_CASE_EVIDENCE_ITEMS = [
  { key: 'case_manifest', kind: 'file', relativePath: 'case_manifest.json' },
  { key: 'apkg', kind: 'directory', relativePath: 'apkg' },
  { key: 'source_provenance', kind: 'file', relativePath: 'source_provenance.json' },
  { key: 'deck_metadata', kind: 'file', relativePath: 'deck_metadata.json' },
  { key: 'anki_verify', kind: 'file', relativePath: 'anki_verify.stdout.json' },
  { key: 'audio_audit', kind: 'file', relativePath: 'audio_audit.verify.json' },
  { key: 'timing', kind: 'file', relativePath: 'timing.json' },
  { key: 'cache_summary', kind: 'file', relativePath: 'cache_summary.json' },
  { key: 'observations', kind: 'file', relativePath: 'observations.json' },
  { key: 'computer_use_actions', kind: 'file', relativePath: 'computer_use_actions.json' },
  { key: 'screenshot_manifest', kind: 'file', relativePath: 'screenshots/manifest.json' },
  { key: 'screenshots', kind: 'directory', relativePath: 'screenshots' },
] as const

export const VIDEO_RELEASE_TOP_LEVEL_EVIDENCE_ITEMS = [
  'matrix_summary.json',
  'release_risk_report.md',
  'run_observations.md',
] as const

export const VIDEO_RELEASE_PLAYBACK_CHECKS = ['video', 'original_audio', 'sentence_tts', 'phrase_tts'] as const

export type VideoReleaseCase = (typeof VIDEO_RELEASE_CASES)[number]
export type VideoReleaseCaseId = VideoReleaseCase['id']
export type VideoReleaseCaseEvidenceItem = (typeof VIDEO_RELEASE_CASE_EVIDENCE_ITEMS)[number]
type VideoReleasePlaybackCheck = (typeof VIDEO_RELEASE_PLAYBACK_CHECKS)[number]
export type VideoReleaseInitializerFile = {
  relativePath: string
  content: string
}
export type VideoReleaseSourceCandidate = {
  url?: string
  video_id?: string
  video_path?: string
  downloaded_video_path?: string
  subtitle_path?: string
  video_sha256?: string
  subtitle_sha256?: string
  video_bytes?: number
  subtitle_bytes?: number
  source_fingerprint?: string
  material_manifest?: string
  cache_probe_status?: string
}
export type VideoReleaseCaseManifest = {
  case_id?: string
  status?: string
  source_kind?: string
  mode?: string
  cache_state?: string
  target_card_count?: number
  minimum_generated_cards?: number
  required_preview_cards?: number
  required_playback_checks?: string[]
  required_evidence?: string[]
  source_candidate?: VideoReleaseSourceCandidate
}
export type VideoReleaseLauncherReadiness = {
  ready_for_release_matrix?: boolean
  failed_checks?: string[]
  vite_ready?: boolean
  vite_still_ready?: boolean
  tauri_is_expected_debug_executable?: boolean
  tauri_still_running?: boolean
  webview_pid?: number | null
  window_pid?: number | null
  window_bound_to_tauri_pid?: boolean
}
export type VideoReleaseCaseStartPreflightInput = {
  caseId: VideoReleaseCaseId
  manifest: VideoReleaseCaseManifest
  launcherReadiness: VideoReleaseLauncherReadiness | null | undefined
  computerUseAvailable: boolean
  coldCacheReadsDisabled?: boolean
}
export type VideoReleaseCaseStartPreflight = {
  ok: boolean
  failedChecks: string[]
  warnings: string[]
  requiredEvidence: string[]
}
export type VideoReleaseCaseCacheTimingPlan = {
  schema_version: 1
  case_id: VideoReleaseCaseId
  status: 'planned_not_observed'
  matrix_pass_created: false
  declared_cache_state: VideoReleaseCase['cacheState']
  source_kind: VideoReleaseCase['sourceKind']
  target_card_count: number
  source_cache_probe_status: string | null
  existing_url_cache_dirs: string[]
  cold_cache_reads_disabled: boolean | null
  cold_claim_scope:
    | 'not_cold_run'
    | 'source_probe_clean_ai_card_cache_reads_disabled'
    | 'ai_card_cache_cold_source_cache_possible'
    | 'invalid_until_cache_reads_disabled'
  planned_payload_flags: {
    disable_ai_review_cache_read: boolean
    disable_ai_review_cache_write: boolean
    disable_card_generation_cache_read: boolean
    disable_card_generation_cache_write: boolean
  }
  required_cache_summary_fields: string[]
  required_timing_fields: string[]
  artifact_paths: {
    timing: string
    cache_summary: string
  }
  notes: string
}
export type VideoReleaseCaseCompletionEvidenceInput = {
  caseId: VideoReleaseCaseId
  manifest: VideoReleaseCaseManifest
  apkgFiles?: Array<string | VideoReleaseApkgEvidence>
  screenshotFiles?: Array<string | VideoReleaseScreenshotEvidence>
  sourceProvenance?: Record<string, unknown> | null
  deckMetadata?: Record<string, unknown> | null
  ankiVerify?: Record<string, unknown> | null
  audioAudit?: Record<string, unknown> | null
  timing?: Record<string, unknown> | null
  cacheSummary?: Record<string, unknown> | null
  observations?: Record<string, unknown> | null
  computerUseActions?: Record<string, unknown> | null
  screenshotManifest?: Record<string, unknown> | null
}
export type VideoReleaseCaseCompletionEvidence = {
  ok: boolean
  failedChecks: string[]
  warnings: string[]
  expectedCards: number
  requiredPreviewCards: number
}
export type VideoReleaseApkgEvidence = {
  path?: string
  absolute_path?: string
  absolutePath?: string
  relative_path?: string
  relativePath?: string
  sha256?: string
  apkg_sha256?: string
  size_bytes?: number
  sizeBytes?: number
  bytes?: number
  mtime_ms?: number
  mtimeMs?: number
  modified_time_ms?: number
}
export type VideoReleaseScreenshotEvidence = {
  path?: string
  absolute_path?: string
  absolutePath?: string
  relative_path?: string
  relativePath?: string
  file?: string
  filename?: string
  name?: string
  sha256?: string
  screenshot_sha256?: string
  file_sha256?: string
  hash?: string
  size_bytes?: number
  sizeBytes?: number
  bytes?: number
  mtime_ms?: number
  mtimeMs?: number
  modified_time_ms?: number
}

export function videoReleaseRunDirName(runStamp: string): string {
  if (!VIDEO_RELEASE_RUN_STAMP_PATTERN.test(runStamp)) {
    throw new Error('Expected video release run stamp in YYYYMMDD_HHMMSS format')
  }
  return `${VIDEO_RELEASE_RUN_DIR_PREFIX}${runStamp}`
}

export function videoReleaseCaseEvidencePaths(caseId: VideoReleaseCaseId): string[] {
  return VIDEO_RELEASE_CASE_EVIDENCE_ITEMS.map((item) => `cases/${caseId}/${item.relativePath}`)
}

function releaseCaseById(caseId: VideoReleaseCaseId): VideoReleaseCase {
  const releaseCase = VIDEO_RELEASE_CASES.find((item) => item.id === caseId)
  if (!releaseCase) {
    throw new Error(`Unknown video release case: ${caseId}`)
  }
  return releaseCase
}

function arrayContainsAll(values: string[] | undefined, required: readonly string[]): boolean {
  if (!Array.isArray(values)) {
    return false
  }
  return required.every((value) => values.includes(value))
}

function isYoutubeUrl(value: string | undefined): boolean {
  if (!value) {
    return false
  }
  try {
    const url = new URL(value)
    return (
      (url.hostname === 'www.youtube.com' || url.hostname === 'youtube.com') &&
      url.pathname === '/watch' &&
      Boolean(url.searchParams.get('v'))
    )
  } catch {
    return false
  }
}

function isYoutubeFingerprint(value: string | undefined): boolean {
  return Boolean(value && /^yt:[a-f0-9]{16}$/i.test(value))
}

function isLocalFileFingerprint(value: string | undefined): boolean {
  return Boolean(value && /^file:[a-f0-9]{16}$/i.test(value))
}

function isSha256Hex(value: string | undefined): boolean {
  return Boolean(value && /^[a-f0-9]{64}$/i.test(value))
}

function isPositiveInteger(value: number | undefined): boolean {
  return Number.isInteger(value) && Number(value) > 0
}

function hasPath(value: string | undefined): boolean {
  return Boolean(value && value.trim().length > 0)
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function unknownRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {}
}

function arrayValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function numberValue(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function booleanValue(value: unknown): boolean | null {
  return typeof value === 'boolean' ? value : null
}

function positiveNumberValue(value: unknown): number | null {
  const numeric = numberValue(value)
  return numeric !== null && numeric > 0 ? numeric : null
}

function firstStringValue(source: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = stringValue(source[key])
    if (value) {
      return value
    }
  }
  return ''
}

function firstPositiveNumberValue(source: Record<string, unknown>, keys: string[]): number | null {
  for (const key of keys) {
    const value = positiveNumberValue(source[key])
    if (value !== null) {
      return value
    }
  }
  return null
}

function valueAtPath(source: Record<string, unknown>, dottedPath: string): unknown {
  return dottedPath.split('.').reduce<unknown>((current, part) => unknownRecord(current)[part], source)
}

function countFromRecord(source: Record<string, unknown>, keys: string[]): number | null {
  for (const key of keys) {
    const value = numberValue(source[key])
    if (value !== null) {
      return value
    }
  }
  return null
}

function looksLikeWriterHandoffArtifact(value: Record<string, unknown>): boolean {
  return (
    value.schema_kind === 'release_timing_cache_writer_handoff_audit' ||
    value.artifact_kind === 'timing_cache_writer_handoff' ||
    value.handoff_kind === 'timing_cache_writer_dry_run_handoff' ||
    value.evidence_role === 'non_final_writer_handoff' ||
    value.matrix_eligibility === 'never' ||
    (Array.isArray(value.planned_writes) && Object.hasOwn(value, 'raw_observed_json') && Object.hasOwn(value, 'writer'))
  )
}

function completionExpectedCards(releaseCase: VideoReleaseCase): number {
  return 'minimumGeneratedCards' in releaseCase ? releaseCase.minimumGeneratedCards : releaseCase.targetCardCount
}

function countMismatchesExpectedCards(value: number | null, releaseCase: VideoReleaseCase): boolean {
  const expected = completionExpectedCards(releaseCase)
  if (value === null) {
    return true
  }
  return 'minimumGeneratedCards' in releaseCase ? value < expected : value !== expected
}

function hasNoFailures(value: unknown): boolean {
  return arrayValue(value).length === 0
}

function playbackSummaryCountFromActions(actions: Record<string, unknown>, aliases: readonly string[]): number | null {
  const directCounts = unknownRecord(actions.playback_counts ?? actions.clicked_counts ?? actions.click_counts)
  for (const alias of aliases) {
    const direct = numberValue(directCounts[alias])
    if (direct !== null) {
      return direct
    }
  }
  const checks = unknownRecord(actions.playback_checks)
  for (const alias of aliases) {
    const checkValue = checks[alias]
    if (typeof checkValue === 'number') {
      return checkValue
    }
    if (typeof checkValue === 'boolean') {
      return checkValue ? Number.POSITIVE_INFINITY : 0
    }
  }
  return null
}

const COMPUTER_USE_PLAYBACK_ROLE_ALIASES = {
  video: ['video'],
  original_audio: ['original_audio', 'original'],
  sentence_tts: ['sentence_tts', 'slow_tts'],
  phrase_tts: ['phrase_tts', 'expression_tts'],
} as const

const COMPUTER_USE_PLAYBACK_ACTION_VERBS = new Set(['click', 'tap', 'play', 'playback_check', 'playback_click'])
const COMPUTER_USE_PLAYBACK_SUCCESS_OUTCOMES = new Set([
  'played',
  'playback_started',
  'playback_completed',
  'success',
  'succeeded',
  'ok',
  'passed',
])

function actionCardIndex(action: Record<string, unknown>): number | null {
  return countFromRecord(action, ['card_index', 'cardIndex', 'index'])
}

function actionCardIndexInBounds(
  action: Record<string, unknown>,
  releaseCase: VideoReleaseCase,
): number | null {
  const index = actionCardIndex(action)
  if (index === null || !Number.isInteger(index) || index < 1 || index > completionExpectedCards(releaseCase)) {
    return null
  }
  return index
}

function actionSemanticRole(action: Record<string, unknown>): string {
  return String(
    action.role ??
      action.check ??
      action.kind ??
      action.target_role ??
      action.semantic_control ??
      action.control ??
      action.target ??
      '',
  )
}

function normalizeComputerUsePlaybackRole(value: unknown): VideoReleasePlaybackCheck | null {
  const role = stringValue(value).toLowerCase()
  for (const key of VIDEO_RELEASE_PLAYBACK_CHECKS) {
    if ((COMPUTER_USE_PLAYBACK_ROLE_ALIASES[key] as readonly string[]).includes(role)) {
      return key
    }
  }
  return null
}

function actionExplicitPlaybackRole(action: Record<string, unknown>): VideoReleasePlaybackCheck | null {
  return normalizeComputerUsePlaybackRole(action.role ?? action.target_role)
}

function actionLoosePlaybackRole(action: Record<string, unknown>): VideoReleasePlaybackCheck | null {
  return normalizeComputerUsePlaybackRole(actionSemanticRole(action))
}

function actionLooksLikePlaybackCandidate(action: Record<string, unknown>): boolean {
  return (
    Object.hasOwn(action, 'role') ||
    Object.hasOwn(action, 'target_role') ||
    actionLoosePlaybackRole(action) !== null
  )
}

function actionOrder(action: Record<string, unknown>): number | null {
  const order = countFromRecord(action, ['order', 'sequence', 'seq', 'action_order', 'actionOrder'])
  return order !== null && Number.isInteger(order) && order > 0 ? order : null
}

function actionHasPlaybackVerb(action: Record<string, unknown>): boolean {
  const verb = stringValue(action.action ?? action.type ?? action.kind ?? action.event).toLowerCase()
  return COMPUTER_USE_PLAYBACK_ACTION_VERBS.has(verb)
}

function actionHasExplicitSuccessfulPlaybackOutcome(action: Record<string, unknown>): boolean {
  const outcome = stringValue(action.outcome ?? action.result ?? action.status).toLowerCase()
  return action.ok === true && COMPUTER_USE_PLAYBACK_SUCCESS_OUTCOMES.has(outcome)
}

function actionIsCanonicalPlaybackForRole(
  action: Record<string, unknown>,
  releaseCase: VideoReleaseCase,
  role: VideoReleasePlaybackCheck,
): boolean {
  return (
    actionOrder(action) !== null &&
    actionCardIndexInBounds(action, releaseCase) !== null &&
    actionExplicitPlaybackRole(action) === role &&
    actionHasPlaybackVerb(action) &&
    actionHasExplicitSuccessfulPlaybackOutcome(action)
  )
}

function actionTraceHasPositiveUniqueOrders(actionItems: Record<string, unknown>[]): boolean {
  const seen = new Set<number>()
  for (const action of actionItems) {
    const order = actionOrder(action)
    if (order === null || seen.has(order)) {
      return false
    }
    seen.add(order)
  }
  return true
}

function playbackCandidateRows(actionItems: Record<string, unknown>[]): Record<string, unknown>[] {
  return actionItems.filter(actionLooksLikePlaybackCandidate)
}

function playbackCandidateRowsMissingExplicitRole(actionItems: Record<string, unknown>[]): boolean {
  return playbackCandidateRows(actionItems).some((action) => actionExplicitPlaybackRole(action) === null)
}

function playbackCandidateRowsMissingExplicitSuccessfulOutcome(actionItems: Record<string, unknown>[]): boolean {
  return playbackCandidateRows(actionItems).some(
    (action) => !actionHasPlaybackVerb(action) || !actionHasExplicitSuccessfulPlaybackOutcome(action),
  )
}

function playbackCandidateRowsHaveOutOfBoundsCardIndex(
  actionItems: Record<string, unknown>[],
  releaseCase: VideoReleaseCase,
): boolean {
  return playbackCandidateRows(actionItems).some((action) => actionCardIndexInBounds(action, releaseCase) === null)
}

function playbackCardIndicesForRole(
  actionItems: Record<string, unknown>[],
  releaseCase: VideoReleaseCase,
  role: VideoReleasePlaybackCheck,
): Set<number> {
  const indices = new Set<number>()
  for (const action of actionItems) {
    if (actionIsCanonicalPlaybackForRole(action, releaseCase, role)) {
      const index = actionCardIndexInBounds(action, releaseCase)
      if (index !== null) {
        indices.add(index)
      }
    }
  }
  return indices
}

function referenceTokens(value: unknown): string[] {
  const tokens: string[] = []
  const addToken = (candidate: unknown) => {
    if (typeof candidate === 'number' && Number.isFinite(candidate)) {
      tokens.push(String(candidate))
      return
    }
    const text = stringValue(candidate)
    if (text) {
      tokens.push(text)
    }
  }

  addToken(value)

  const record = unknownRecord(value)
  for (const key of ['action_id', 'actionId', 'id', 'order', 'sequence', 'seq', 'trace_id', 'traceId', 'event_id']) {
    addToken(record[key])
  }

  for (const item of arrayValue(value)) {
    tokens.push(...referenceTokens(item))
  }

  return [...new Set(tokens)]
}

function actionReferenceTokens(action: Record<string, unknown>): Set<string> {
  return new Set(referenceTokens(action))
}

function actionTraceCardHasRole(
  actionItems: Record<string, unknown>[],
  releaseCase: VideoReleaseCase,
  cardIndex: number,
  role: VideoReleasePlaybackCheck,
): boolean {
  return playbackCardIndicesForRole(actionItems, releaseCase, role).has(cardIndex)
}

function actionTraceCardHasPlaybackCoverage(
  actionItems: Record<string, unknown>[],
  releaseCase: VideoReleaseCase,
  cardIndex: number,
): boolean {
  return VIDEO_RELEASE_PLAYBACK_CHECKS.every((role) =>
    actionTraceCardHasRole(actionItems, releaseCase, cardIndex, role),
  )
}

function actionTraceHasRequiredPlaybackCoverage(
  actionItems: Record<string, unknown>[],
  releaseCase: VideoReleaseCase,
): boolean {
  if (releaseCase.inspection === 'all_cards') {
    for (let index = 1; index <= releaseCase.requiredPreviewCards; index += 1) {
      if (!actionTraceCardHasPlaybackCoverage(actionItems, releaseCase, index)) {
        return false
      }
    }
    return true
  }

  const completeIndices = new Set<number>()
  for (const action of actionItems) {
    const index = actionCardIndexInBounds(action, releaseCase)
    if (index !== null && actionTraceCardHasPlaybackCoverage(actionItems, releaseCase, index)) {
      completeIndices.add(index)
    }
  }
  if (completeIndices.size < releaseCase.requiredPreviewCards) {
    return false
  }
  const indices = [...completeIndices]
  return (
    indices.some((index) => index <= 4) &&
    indices.some((index) => index >= 45 && index <= 60) &&
    indices.some((index) => index >= 97)
  )
}

function observationCardIndex(item: Record<string, unknown>): number | null {
  return countFromRecord(item, ['index', 'card_index', 'cardIndex'])
}

function observationPlaybackActionReferences(item: Record<string, unknown>, aliases: readonly string[]): Set<string> {
  const tokens = new Set<string>()
  const addTokens = (value: unknown) => {
    for (const token of referenceTokens(value)) {
      tokens.add(token)
    }
  }
  const addRoleKeyedReferences = (value: unknown) => {
    const record = unknownRecord(value)
    for (const alias of aliases) {
      addTokens(record[alias])
    }
    if (aliases.includes(actionSemanticRole(record))) {
      addTokens(record)
    }
    for (const entry of arrayValue(value).map(unknownRecord)) {
      if (aliases.includes(actionSemanticRole(entry))) {
        addTokens(entry)
      }
    }
  }

  for (const container of [
    item.playback_action_refs,
    item.computer_use_action_refs,
    item.computer_use_actions,
    item.action_refs,
    item.action_ids,
    item.playback_actions,
    item.actions,
    unknownRecord(item.checks).playback_action_refs,
    unknownRecord(item.checks).computer_use_action_refs,
  ]) {
    addRoleKeyedReferences(container)
  }

  return tokens
}

function observationHasLinkedPlaybackActions(
  item: Record<string, unknown>,
  actionItems: Record<string, unknown>[],
  releaseCase: VideoReleaseCase,
): boolean {
  const cardIndex = observationCardIndex(item)
  if (cardIndex === null) {
    return false
  }

  return VIDEO_RELEASE_PLAYBACK_CHECKS.every((role) => {
    const aliases = COMPUTER_USE_PLAYBACK_ROLE_ALIASES[role]
    const roleAliases: readonly string[] = aliases
    const references = observationPlaybackActionReferences(item, roleAliases)
    if (references.size === 0) {
      return false
    }
    return actionItems.some((action) => {
      if (
        actionCardIndexInBounds(action, releaseCase) !== cardIndex ||
        !actionIsCanonicalPlaybackForRole(action, releaseCase, role)
      ) {
        return false
      }
      return [...actionReferenceTokens(action)].some((token) => references.has(token))
    })
  })
}

function evidenceSessionId(value: Record<string, unknown>): string {
  return firstStringValue(value, ['session_id', 'sessionId', 'computer_use_session_id', 'computerUseSessionId'])
}

function screenshotManifestEntries(source: Record<string, unknown>): Record<string, unknown>[] {
  const entries: Record<string, unknown>[] = []
  entries.push(
    ...arrayValue(source.screenshots).map(unknownRecord),
    ...arrayValue(source.files).map(unknownRecord),
    ...arrayValue(source.items).map(unknownRecord),
  )
  for (const key of ['screenshot_manifest', 'screenshotManifest', 'screenshots_manifest', 'screenshotsManifest']) {
    const value = source[key]
    entries.push(...arrayValue(value).map(unknownRecord))
    const record = unknownRecord(value)
    entries.push(
      ...arrayValue(record.files).map(unknownRecord),
      ...arrayValue(record.screenshots).map(unknownRecord),
      ...arrayValue(record.items).map(unknownRecord),
    )
  }
  return entries
}

function screenshotManifestSchemaVersion(source: Record<string, unknown>): number | null {
  return countFromRecord(source, ['schema_version', 'schemaVersion'])
}

function screenshotManifestEntryReferences(entry: Record<string, unknown>): string[] {
  const refs: string[] = []
  for (const key of [
    'screenshot_id',
    'screenshotId',
    'id',
    'path',
    'file',
    'filename',
    'relative_path',
    'relativePath',
    'screenshot',
    'screenshot_file',
    'screenshot_path',
  ]) {
    const value = stringValue(entry[key])
    if (value) {
      refs.push(value)
    }
  }
  return refs
}

function screenshotManifestEntrySha256(entry: Record<string, unknown>): string {
  return firstStringValue(entry, ['sha256', 'screenshot_sha256', 'file_sha256', 'hash'])
}

function screenshotManifestEntryCardIndexInBounds(
  entry: Record<string, unknown>,
  releaseCase: VideoReleaseCase,
): boolean {
  const index = screenshotManifestEntryCardIndex(entry)
  return (
    index !== null &&
    Number.isInteger(index) &&
    index >= 1 &&
    index <= completionExpectedCards(releaseCase)
  )
}

function screenshotManifestEntryCardIndex(entry: Record<string, unknown>): number | null {
  return countFromRecord(entry, ['card_index', 'cardIndex', 'index'])
}

function screenshotManifestEntryHasFileReference(entry: Record<string, unknown>, screenshotFiles: ScreenshotEvidence[]): boolean {
  return screenshotManifestEntryReferences(entry).some((reference) =>
    screenshotReferenceMatches(reference, screenshotFiles),
  )
}

function screenshotManifestEntryHasSha256(entry: Record<string, unknown>): boolean {
  return isSha256Hex(screenshotManifestEntrySha256(entry))
}

function screenshotManifestEntryValidForSession(
  entry: Record<string, unknown>,
  screenshotFiles: ScreenshotEvidence[],
  releaseCase: VideoReleaseCase,
  sessionId: string,
): boolean {
  return (
    evidenceSessionId(entry) === sessionId &&
    screenshotManifestEntryCardIndexInBounds(entry, releaseCase) &&
    screenshotManifestEntryHasFileReference(entry, screenshotFiles) &&
    screenshotManifestEntryHasSha256(entry)
  )
}

function screenshotManifestHasInvalidEntries(
  entries: Record<string, unknown>[],
  screenshotFiles: ScreenshotEvidence[],
  releaseCase: VideoReleaseCase,
  sessionId: string,
): boolean {
  return entries.some((entry) => !screenshotManifestEntryValidForSession(entry, screenshotFiles, releaseCase, sessionId))
}

function matchedScreenshotEvidenceForManifestEntry(
  entry: Record<string, unknown>,
  screenshotFiles: ScreenshotEvidence[],
): ScreenshotEvidence | null {
  return (
    screenshotFiles.find((file) =>
      screenshotManifestEntryReferences(entry).some((reference) => screenshotReferenceMatches(reference, [file])),
    ) ?? null
  )
}

function screenshotManifestHasSha256Mismatch(
  entries: Record<string, unknown>[],
  screenshotFiles: ScreenshotEvidence[],
): boolean {
  return entries.some((entry) => {
    const expectedSha256 = screenshotManifestEntrySha256(entry).toLowerCase()
    if (!isSha256Hex(expectedSha256)) {
      return false
    }
    const evidenceFile = matchedScreenshotEvidenceForManifestEntry(entry, screenshotFiles)
    return Boolean(evidenceFile?.sha256 && evidenceFile.sha256 !== expectedSha256)
  })
}

function screenshotManifestHasFileReusedForMultipleCardIndices(
  entries: Record<string, unknown>[],
  screenshotFiles: ScreenshotEvidence[],
): boolean {
  const cardIndicesByFile = new Map<string, Set<number>>()
  for (const entry of entries) {
    const cardIndex = screenshotManifestEntryCardIndex(entry)
    const evidenceFile = matchedScreenshotEvidenceForManifestEntry(entry, screenshotFiles)
    if (cardIndex === null || !evidenceFile) {
      continue
    }
    const indices = cardIndicesByFile.get(evidenceFile.key) ?? new Set<number>()
    indices.add(cardIndex)
    cardIndicesByFile.set(evidenceFile.key, indices)
  }
  return [...cardIndicesByFile.values()].some((indices) => indices.size > 1)
}

function screenshotReferenceMatchesManifestEntryReference(
  reference: string,
  entry: Record<string, unknown>,
  screenshotFiles: ScreenshotEvidence[],
): boolean {
  const referenceTail = pathTail(reference).toLowerCase()
  return (
    screenshotManifestEntryHasFileReference(entry, screenshotFiles) &&
    screenshotManifestEntryReferences(entry).some((candidate) => {
      const normalizedCandidate = candidate.toLowerCase()
      return normalizedCandidate === reference.toLowerCase() || pathTail(candidate).toLowerCase() === referenceTail
    })
  )
}

function observationScreenshotReferencesPresentInManifest(
  item: Record<string, unknown>,
  entries: Record<string, unknown>[],
  screenshotFiles: ScreenshotEvidence[],
): boolean {
  const references = observationScreenshotReferences(item)
  return references.length > 0 && references.every((reference) =>
    entries.some((entry) => screenshotReferenceMatchesManifestEntryReference(reference, entry, screenshotFiles)),
  )
}

function observationScreenshotReferencesMatchManifestCardIndex(
  item: Record<string, unknown>,
  entries: Record<string, unknown>[],
  screenshotFiles: ScreenshotEvidence[],
): boolean {
  const index = observationCardIndex(item)
  if (index === null) {
    return false
  }
  const references = observationScreenshotReferences(item)
  return references.length > 0 && references.every((reference) =>
    entries.some(
      (entry) =>
        screenshotReferenceMatchesManifestEntryReference(reference, entry, screenshotFiles) &&
        screenshotManifestEntryCardIndex(entry) === index,
    ),
  )
}

function recordsMissingSessionId(records: Record<string, unknown>[], sessionId: string): boolean {
  return records.some((record) => evidenceSessionId(record) !== sessionId)
}

function pathTail(value: string): string {
  const normalized = value.replaceAll('\\', '/')
  return normalized.split('/').filter(Boolean).at(-1) ?? normalized
}

function normalizeEvidencePath(value: string): string {
  return value.replaceAll('\\', '/').replace(/^\/+/, '').replace(/\/+/g, '/')
}

function deriveCaseRelativeApkgPath(value: string, caseId: VideoReleaseCaseId): string {
  const normalized = normalizeEvidencePath(value)
  const marker = `cases/${caseId}/apkg/`
  const lower = normalized.toLowerCase()
  const markerIndex = lower.indexOf(marker.toLowerCase())
  return markerIndex >= 0 ? normalized.slice(markerIndex) : normalized
}

function pathMatchesCanonicalApkg(value: string, identity: CanonicalApkgIdentity): boolean {
  const normalized = deriveCaseRelativeApkgPath(value, identity.caseId).toLowerCase()
  const relative = identity.relativePath.toLowerCase()
  return normalized === relative
}

function apkgMtimeMatchesArtifact(artifactMtimeMs: number, identityMtimeMs: number): boolean {
  return Math.abs(artifactMtimeMs - identityMtimeMs) <= 1
}

type CanonicalApkgIdentity = {
  caseId: VideoReleaseCaseId
  relativePath: string
  fileName: string
  sha256: string
  sizeBytes: number
  mtimeMs: number
}

type ScreenshotEvidence = {
  key: string
  references: string[]
  fileName: string
  sha256: string | null
}

function screenshotEvidenceReferences(raw: string | VideoReleaseScreenshotEvidence): string[] {
  if (typeof raw === 'string') {
    return raw.trim() ? [raw.trim()] : []
  }
  const record = unknownRecord(raw)
  return [
    firstStringValue(record, ['path', 'absolute_path', 'absolutePath', 'file', 'full_path']),
    firstStringValue(record, ['relative_path', 'relativePath']),
    firstStringValue(record, ['filename', 'name']),
  ].filter(Boolean)
}

function normalizeScreenshotEvidenceFiles(
  screenshotFiles: Array<string | VideoReleaseScreenshotEvidence>,
): ScreenshotEvidence[] {
  return screenshotFiles
    .map((raw) => {
      const references = screenshotEvidenceReferences(raw)
      const primaryReference = references[0] ?? ''
      const record = typeof raw === 'string' ? {} : unknownRecord(raw)
      const sha256 = firstStringValue(record, ['sha256', 'screenshot_sha256', 'file_sha256', 'hash']).toLowerCase()
      return {
        key: normalizeEvidencePath(primaryReference || pathTail(primaryReference)).toLowerCase(),
        references,
        fileName: pathTail(primaryReference),
        sha256: isSha256Hex(sha256) ? sha256 : null,
      }
    })
    .filter((file) => file.references.length > 0 && file.fileName.toLowerCase() !== 'manifest.json')
}

function canonicalApkgIdentity(
  apkgFiles: Array<string | VideoReleaseApkgEvidence>,
  caseId: VideoReleaseCaseId,
  failedChecks: string[],
): CanonicalApkgIdentity | null {
  if (apkgFiles.length < 1) {
    failedChecks.push('apkg_missing')
    return null
  }
  if (apkgFiles.length !== 1) {
    failedChecks.push('apkg_canonical_count_mismatch')
  }

  const raw = apkgFiles[0]
  const record = typeof raw === 'string' ? {} : unknownRecord(raw)
  const rawPath =
    typeof raw === 'string'
      ? raw.trim()
      : firstStringValue(record, ['path', 'absolute_path', 'absolutePath', 'file', 'full_path'])
  const declaredRelativePath = firstStringValue(record, ['relative_path', 'relativePath'])
  const relativePath = declaredRelativePath
    ? normalizeEvidencePath(declaredRelativePath)
    : rawPath
      ? deriveCaseRelativeApkgPath(rawPath, caseId)
      : ''
  const fileName = pathTail(relativePath || rawPath)
  const expectedPrefix = `cases/${caseId}/apkg/`
  const expectedFileName = `${caseId}.apkg`
  const sha256 = firstStringValue(record, ['sha256', 'apkg_sha256'])
  const sizeBytes = firstPositiveNumberValue(record, ['size_bytes', 'sizeBytes', 'bytes'])
  const mtimeMs = firstPositiveNumberValue(record, ['mtime_ms', 'mtimeMs', 'modified_time_ms'])

  if (!relativePath || !relativePath.toLowerCase().startsWith(expectedPrefix.toLowerCase())) {
    failedChecks.push('apkg_relative_path_mismatch')
  }
  if (!fileName.toLowerCase().endsWith('.apkg')) {
    failedChecks.push('apkg_extension_invalid')
  }
  if (fileName.toLowerCase() !== expectedFileName.toLowerCase()) {
    failedChecks.push('apkg_canonical_filename_mismatch')
  }
  if (!isSha256Hex(sha256)) {
    failedChecks.push('apkg_sha256_missing')
  }
  if (sizeBytes === null) {
    failedChecks.push('apkg_size_bytes_missing')
  }
  if (mtimeMs === null) {
    failedChecks.push('apkg_mtime_ms_missing')
  }

  if (
    !relativePath ||
    !relativePath.toLowerCase().startsWith(expectedPrefix.toLowerCase()) ||
    !fileName.toLowerCase().endsWith('.apkg') ||
    fileName.toLowerCase() !== expectedFileName.toLowerCase() ||
    !isSha256Hex(sha256) ||
    sizeBytes === null ||
    mtimeMs === null
  ) {
    return null
  }

  return {
    caseId,
    relativePath,
    fileName,
    sha256: sha256.toLowerCase(),
    sizeBytes,
    mtimeMs,
  }
}

function isKnownSourceFingerprint(value: string | undefined): boolean {
  return isYoutubeFingerprint(value) || isLocalFileFingerprint(value)
}

function completionSourceFingerprint(
  manifest: VideoReleaseCaseManifest,
  releaseCase: VideoReleaseCase,
  failedChecks: string[],
): string {
  if (manifest.source_kind !== releaseCase.sourceKind) {
    failedChecks.push('case_manifest_source_kind_mismatch')
  }
  if (manifest.mode !== releaseCase.mode) {
    failedChecks.push('case_manifest_mode_mismatch')
  }
  if (manifest.cache_state !== releaseCase.cacheState) {
    failedChecks.push('case_manifest_cache_state_mismatch')
  }
  if (!arrayContainsAll(manifest.required_playback_checks, VIDEO_RELEASE_PLAYBACK_CHECKS)) {
    failedChecks.push('case_manifest_missing_playback_checks')
  }
  if (!arrayContainsAll(manifest.required_evidence, videoReleaseCaseEvidencePaths(releaseCase.id))) {
    failedChecks.push('case_manifest_missing_required_evidence')
  }

  const candidate = manifest.source_candidate
  if (!candidate) {
    failedChecks.push('case_manifest_source_candidate_missing')
    return ''
  }

  const sourceFingerprint = stringValue(candidate.source_fingerprint)
  if (releaseCase.sourceKind === 'youtube_url' && !isYoutubeFingerprint(sourceFingerprint)) {
    failedChecks.push('case_manifest_source_fingerprint_invalid')
    return ''
  }
  if (releaseCase.sourceKind === 'local_video_srt' && !isLocalFileFingerprint(sourceFingerprint)) {
    failedChecks.push('case_manifest_source_fingerprint_invalid')
    return ''
  }
  if (releaseCase.sourceKind === 'public_video' && !isKnownSourceFingerprint(sourceFingerprint)) {
    failedChecks.push('case_manifest_source_fingerprint_invalid')
    return ''
  }
  return sourceFingerprint
}

function artifactIdentityPath(value: Record<string, unknown>): string {
  return firstStringValue(value, [
    'apkg_relative_path',
    'apkgRelativePath',
    'apkg_path',
    'apkgPath',
    'verified_export_apkg_path',
    'verifiedExportApkgPath',
  ])
}

function validateArtifactIdentity({
  artifact,
  prefix,
  caseId,
  sourceFingerprint,
  apkgIdentity,
  failedChecks,
}: {
  artifact: Record<string, unknown>
  prefix: string
  caseId: VideoReleaseCaseId
  sourceFingerprint: string
  apkgIdentity: CanonicalApkgIdentity | null
  failedChecks: string[]
}) {
  if (artifact.case_id !== caseId) {
    failedChecks.push(`${prefix}_case_id_mismatch`)
  }
  if (sourceFingerprint && artifact.source_fingerprint !== sourceFingerprint) {
    failedChecks.push(`${prefix}_source_fingerprint_mismatch`)
  }
  if (!apkgIdentity) {
    failedChecks.push(`${prefix}_apkg_identity_unavailable`)
    return
  }

  const artifactPath = artifactIdentityPath(artifact)
  const artifactSha = firstStringValue(artifact, ['apkg_sha256', 'verified_apkg_sha256'])
  const artifactSizeBytes = firstPositiveNumberValue(artifact, ['apkg_size_bytes', 'size_bytes', 'apkgSizeBytes'])
  const artifactMtimeMs = firstPositiveNumberValue(artifact, ['apkg_mtime_ms', 'mtime_ms', 'apkgMtimeMs'])
  if (!artifactPath) {
    failedChecks.push(`${prefix}_apkg_path_missing`)
  } else if (!pathMatchesCanonicalApkg(artifactPath, apkgIdentity)) {
    failedChecks.push(`${prefix}_apkg_path_mismatch`)
  }
  if (!isSha256Hex(artifactSha)) {
    failedChecks.push(`${prefix}_apkg_sha256_missing`)
  } else if (artifactSha.toLowerCase() !== apkgIdentity.sha256) {
    failedChecks.push(`${prefix}_apkg_sha256_mismatch`)
  }
  if (artifactSizeBytes !== null && artifactSizeBytes !== apkgIdentity.sizeBytes) {
    failedChecks.push(`${prefix}_apkg_size_bytes_mismatch`)
  }
  if (artifactMtimeMs !== null && !apkgMtimeMatchesArtifact(artifactMtimeMs, apkgIdentity.mtimeMs)) {
    failedChecks.push(`${prefix}_apkg_mtime_ms_mismatch`)
  }
}

function validateSourceProvenanceArtifact({
  artifact,
  releaseCase,
  caseId,
  sourceFingerprint,
  failedChecks,
}: {
  artifact: Record<string, unknown>
  releaseCase: VideoReleaseCase
  caseId: VideoReleaseCaseId
  sourceFingerprint: string
  failedChecks: string[]
}) {
  if (numberValue(artifact.schema_version) !== 1) {
    failedChecks.push('source_provenance_schema_version_mismatch')
  }
  if (artifact.case_id !== caseId) {
    failedChecks.push('source_provenance_case_id_mismatch')
  }
  if (artifact.source_kind !== releaseCase.sourceKind) {
    failedChecks.push('source_provenance_source_kind_mismatch')
  }
  if (sourceFingerprint && artifact.source_fingerprint !== sourceFingerprint) {
    failedChecks.push('source_provenance_source_fingerprint_mismatch')
  }

  const projectSourceMode = stringValue(artifact.project_source_mode)
  if (projectSourceMode === 'document') {
    failedChecks.push('source_provenance_project_document_source_mode')
  }
  if (!projectSourceMode) {
    failedChecks.push('source_provenance_project_source_mode_missing')
  }

  if (releaseCase.sourceKind === 'youtube_url') {
    if (projectSourceMode !== 'url') {
      failedChecks.push('source_provenance_project_source_mode_mismatch')
    }
    const manifestVideoId = stringValue(artifact.manifest_video_id)
    const projectVideoId = stringValue(artifact.project_video_id)
    if (!manifestVideoId || !projectVideoId) {
      failedChecks.push('source_provenance_youtube_video_id_missing')
    } else if (manifestVideoId !== projectVideoId) {
      failedChecks.push('source_provenance_youtube_video_id_mismatch')
    }
    if (!stringValue(artifact.manifest_url)) {
      failedChecks.push('source_provenance_youtube_manifest_url_missing')
    }
    if (!stringValue(artifact.project_source_url)) {
      failedChecks.push('source_provenance_youtube_project_source_url_missing')
    }
    if (artifact.transcript_only === true) {
      failedChecks.push('source_provenance_youtube_transcript_only')
    }
    if (artifact.skip_video_slicing === true) {
      failedChecks.push('source_provenance_youtube_skip_video_slicing')
    }
    if (artifact.url_import_mode === 'subtitles' || artifact.download_mode === 'subtitles') {
      failedChecks.push('source_provenance_youtube_subtitle_only_import_mode')
    }
  } else if (releaseCase.sourceKind === 'local_video_srt') {
    if (projectSourceMode !== 'local') {
      failedChecks.push('source_provenance_project_source_mode_mismatch')
    }
    for (const [field, check] of [
      ['manifest_video_path', 'source_provenance_manifest_video_path_missing'],
      ['manifest_subtitle_path', 'source_provenance_manifest_subtitle_path_missing'],
      ['project_video_path', 'source_provenance_project_video_path_missing'],
      ['project_subtitle_path', 'source_provenance_project_subtitle_path_missing'],
      ['project_video_fingerprint', 'source_provenance_project_video_fingerprint_missing'],
      ['project_subtitle_fingerprint', 'source_provenance_project_subtitle_fingerprint_missing'],
      ['manifest_video_sha256', 'source_provenance_manifest_video_sha256_missing'],
      ['manifest_subtitle_sha256', 'source_provenance_manifest_subtitle_sha256_missing'],
    ] as const) {
      if (!stringValue(artifact[field])) {
        failedChecks.push(check)
      }
    }
    if (!isSha256Hex(stringValue(artifact.manifest_video_sha256))) {
      failedChecks.push('source_provenance_manifest_video_sha256_invalid')
    }
    if (!isSha256Hex(stringValue(artifact.manifest_subtitle_sha256))) {
      failedChecks.push('source_provenance_manifest_subtitle_sha256_invalid')
    }
    if (positiveNumberValue(artifact.manifest_video_bytes) === null) {
      failedChecks.push('source_provenance_manifest_video_bytes_missing')
    }
    if (positiveNumberValue(artifact.manifest_subtitle_bytes) === null) {
      failedChecks.push('source_provenance_manifest_subtitle_bytes_missing')
    }
  } else if (!['url', 'local'].includes(projectSourceMode)) {
    failedChecks.push('source_provenance_project_source_mode_mismatch')
  }
}

function observationScreenshotReferences(item: Record<string, unknown>): string[] {
  const references: string[] = []
  const addReference = (value: unknown) => {
    const reference = String(value ?? '').trim()
    if (reference) {
      references.push(reference)
    }
  }

  for (const value of [item.screenshot, item.screenshot_file, item.screenshot_path]) {
    addReference(value)
  }
  for (const value of arrayValue(item.screenshots)) {
    addReference(value)
  }
  const screenshots = unknownRecord(item.screenshots)
  for (const [key, value] of Object.entries(screenshots)) {
    if (/(sha|hash|checksum|digest|size|bytes|mtime|timestamp)/i.test(key)) {
      continue
    }
    addReference(value)
  }
  return [...new Set(references)]
}

function screenshotReferenceMatches(reference: string, screenshotFiles: ScreenshotEvidence[]): boolean {
  const referenceTail = pathTail(reference).toLowerCase()
  return screenshotFiles.some((file) => {
    return file.references.some((candidate) => {
      const normalizedCandidate = candidate.toLowerCase()
      return normalizedCandidate === reference.toLowerCase() || pathTail(candidate).toLowerCase() === referenceTail
    })
  })
}

function observationHasVisibleCardEvidence(item: Record<string, unknown>): boolean {
  const expected = unknownRecord(item.expected)
  const visible = unknownRecord(item.visible)
  const directFields = [
    'visible_answer',
    'answer',
    'source_sentence',
    'card_display_sentence',
    'source_time',
    'media_source_time',
  ]
  if (directFields.some((field) => String(item[field] ?? expected[field] ?? '').trim())) {
    return true
  }
  if (arrayValue(item.visible_lines).some((value) => String(value ?? '').trim())) {
    return true
  }
  if (arrayValue(visible.visible_text_lines).some((value) => String(value ?? '').trim())) {
    return true
  }
  const summary = unknownRecord(item.summary)
  return arrayValue(summary.texts).some((value) => String(value ?? '').trim())
}

function observationHasObservedCardMarker(item: Record<string, unknown>): boolean {
  const visible = unknownRecord(item.visible)
  return (
    item.anki_card_observed === true ||
    item.card_observed === true ||
    item.visible_card === true ||
    (visible.answer_seen === true && visible.source_sentence_seen === true && visible.time_seen === true)
  )
}

function observationHasReleaseRiskClaims(item: Record<string, unknown>): boolean {
  const checks = unknownRecord(item.checks)
  return ['no_wrong_audio', 'no_video_misalignment', 'no_field_mixing', 'no_missing_media', 'no_crash'].every(
    (key) => item[key] === true || checks[key] === true,
  )
}

function observationHasMatchedScreenshot(item: Record<string, unknown>, screenshotFiles: ScreenshotEvidence[]): boolean {
  return observationScreenshotReferences(item).some((reference) =>
    screenshotReferenceMatches(reference, screenshotFiles),
  )
}

function observationHasRequiredFullCardEvidence(
  item: Record<string, unknown>,
  screenshotFiles: ScreenshotEvidence[],
): boolean {
  return (
    observationCardIndex(item) !== null &&
    observationHasMatchedScreenshot(item, screenshotFiles) &&
    observationHasVisibleCardEvidence(item) &&
    observationHasObservedCardMarker(item) &&
    observationHasReleaseRiskClaims(item)
  )
}

const TIMING_STAGE_MS_FIELDS = [
  'source_prepare_ms',
  'learning_point_extract_ms',
  'ai_review_ms',
  'card_body_ms',
  'tts_ms',
  'media_slice_ms',
  'apkg_pack_ms',
  'anki_verify_ms',
] as const

const TIMING_BOTTLENECK_STAGES = [
  ['source_prepare', 'source_prepare_ms'],
  ['learning_point_extract', 'learning_point_extract_ms'],
  ['ai_review', 'ai_review_ms'],
  ['card_body', 'card_body_ms'],
  ['tts', 'tts_ms'],
  ['media_slice', 'media_slice_ms'],
  ['apkg_pack', 'apkg_pack_ms'],
  ['anki_verify', 'anki_verify_ms'],
] as const

const TIMING_STAGE_PER_CARD_FIELDS = [
  ['card_body_ms', 'stage_per_card_ms.card_body'],
  ['tts_ms', 'stage_per_card_ms.tts'],
  ['media_slice_ms', 'stage_per_card_ms.media_slice'],
  ['apkg_pack_ms', 'stage_per_card_ms.apkg_pack'],
  ['anki_verify_ms', 'stage_per_card_ms.anki_verify'],
] as const

const CACHE_GROUP_KEYS = ['ai_review_cache', 'card_generation_cache', 'tts_cache', 'media_cache'] as const

function cacheGroupCounts(
  cacheRecord: Record<string, unknown>,
  groupKey: string,
): { hits: number; misses: number; total: number } | null {
  const group = unknownRecord(cacheRecord[groupKey])
  const hits = numberValue(group.hits)
  const misses = numberValue(group.misses)
  const total = numberValue(group.total)
  if (hits === null || misses === null || total === null) {
    return null
  }
  return { hits, misses, total }
}

export function evaluateVideoReleaseCaseStartPreflight({
  caseId,
  manifest,
  launcherReadiness,
  computerUseAvailable,
  coldCacheReadsDisabled = false,
}: VideoReleaseCaseStartPreflightInput): VideoReleaseCaseStartPreflight {
  const releaseCase = releaseCaseById(caseId)
  const failedChecks: string[] = []
  const warnings: string[] = []
  const requiredEvidence = videoReleaseCaseEvidencePaths(caseId)

  if (manifest.case_id !== caseId) {
    failedChecks.push('case_manifest_id_mismatch')
  }
  if (manifest.status !== 'not_started') {
    failedChecks.push('case_manifest_not_not_started')
  }
  if (manifest.source_kind !== releaseCase.sourceKind) {
    failedChecks.push('case_manifest_source_kind_mismatch')
  }
  if (manifest.mode !== releaseCase.mode) {
    failedChecks.push('case_manifest_mode_mismatch')
  }
  if (manifest.cache_state !== releaseCase.cacheState) {
    failedChecks.push('case_manifest_cache_state_mismatch')
  }
  if (manifest.target_card_count !== releaseCase.targetCardCount) {
    failedChecks.push('case_manifest_target_card_count_mismatch')
  }
  if (manifest.required_preview_cards !== releaseCase.requiredPreviewCards) {
    failedChecks.push('case_manifest_required_preview_cards_mismatch')
  }
  if (!arrayContainsAll(manifest.required_playback_checks, VIDEO_RELEASE_PLAYBACK_CHECKS)) {
    failedChecks.push('case_manifest_missing_playback_checks')
  }
  if (!arrayContainsAll(manifest.required_evidence, requiredEvidence)) {
    failedChecks.push('case_manifest_missing_required_evidence')
  }

  if (!computerUseAvailable) {
    failedChecks.push('computer_use_unavailable')
  }
  if (!launcherReadiness?.ready_for_release_matrix) {
    failedChecks.push('launcher_not_ready_for_release_matrix')
  }
  if (launcherReadiness?.failed_checks?.length) {
    failedChecks.push('launcher_failed_checks_present')
  }
  if (!launcherReadiness?.vite_ready || !launcherReadiness?.vite_still_ready) {
    failedChecks.push('launcher_vite_not_ready')
  }
  if (!launcherReadiness?.tauri_is_expected_debug_executable) {
    failedChecks.push('launcher_not_debug_executable')
  }
  if (!launcherReadiness?.tauri_still_running) {
    failedChecks.push('launcher_tauri_not_running')
  }
  if (!launcherReadiness?.webview_pid) {
    failedChecks.push('launcher_webview_missing')
  }
  if (!launcherReadiness?.window_pid || !launcherReadiness?.window_bound_to_tauri_pid) {
    failedChecks.push('launcher_pid_bound_window_missing')
  }

  if (releaseCase.sourceKind === 'youtube_url') {
    const candidate = manifest.source_candidate
    if (!candidate) {
      failedChecks.push('youtube_source_candidate_missing')
    } else {
      if (!isYoutubeUrl(candidate.url)) {
        failedChecks.push('youtube_source_candidate_url_invalid')
      }
      if (!candidate.video_id || !candidate.url?.includes(candidate.video_id)) {
        failedChecks.push('youtube_source_candidate_video_id_mismatch')
      }
      if (!isYoutubeFingerprint(candidate.source_fingerprint)) {
        failedChecks.push('youtube_source_candidate_fingerprint_invalid')
      }
      if (!candidate.material_manifest) {
        failedChecks.push('youtube_source_candidate_material_manifest_missing')
      }
      if (!candidate.cache_probe_status) {
        failedChecks.push('youtube_source_candidate_cache_probe_missing')
      }
      if (releaseCase.cacheState === 'cold' && !coldCacheReadsDisabled) {
        failedChecks.push('cold_youtube_requires_disabled_cache_reads')
        if (candidate.cache_probe_status === 'possible_existing_cache') {
          failedChecks.push('cold_youtube_possible_cache_requires_disabled_cache_reads')
        }
      }
      if (releaseCase.cacheState === 'hot' && candidate.cache_probe_status === 'no_existing_url_cache_found') {
        warnings.push('hot_youtube_source_needs_prior_cold_or_warm_run')
      }
    }
  }
  if (releaseCase.sourceKind === 'local_video_srt') {
    const candidate = manifest.source_candidate
    if (!candidate) {
      failedChecks.push('local_srt_source_candidate_missing')
    } else {
      if (!hasPath(candidate.video_path ?? candidate.downloaded_video_path)) {
        failedChecks.push('local_srt_source_candidate_video_path_missing')
      }
      if (!hasPath(candidate.subtitle_path)) {
        failedChecks.push('local_srt_source_candidate_subtitle_path_missing')
      }
      if (!isPositiveInteger(candidate.video_bytes)) {
        failedChecks.push('local_srt_source_candidate_video_bytes_missing')
      }
      if (!isPositiveInteger(candidate.subtitle_bytes)) {
        failedChecks.push('local_srt_source_candidate_subtitle_bytes_missing')
      }
      if (!isSha256Hex(candidate.video_sha256)) {
        failedChecks.push('local_srt_source_candidate_video_sha256_missing')
      }
      if (!isSha256Hex(candidate.subtitle_sha256)) {
        failedChecks.push('local_srt_source_candidate_subtitle_sha256_missing')
      }
      if (!isLocalFileFingerprint(candidate.source_fingerprint)) {
        failedChecks.push('local_srt_source_candidate_fingerprint_invalid')
      }
      if (!candidate.material_manifest) {
        failedChecks.push('local_srt_source_candidate_material_manifest_missing')
      }
      if (releaseCase.cacheState === 'cold' && !coldCacheReadsDisabled) {
        failedChecks.push('cold_local_srt_requires_disabled_cache_reads')
      }
    }
  }

  return {
    ok: failedChecks.length === 0,
    failedChecks,
    warnings,
    requiredEvidence,
  }
}

export function buildVideoReleaseCaseCacheTimingPlan({
  caseId,
  manifest,
  coldCacheReadsDisabled = false,
  sourceCacheProbeStatus,
  existingUrlCacheDirs = [],
}: {
  caseId: VideoReleaseCaseId
  manifest: VideoReleaseCaseManifest
  coldCacheReadsDisabled?: boolean
  sourceCacheProbeStatus?: string | null
  existingUrlCacheDirs?: string[]
}): VideoReleaseCaseCacheTimingPlan {
  const releaseCase = releaseCaseById(caseId)
  const isCold = releaseCase.cacheState === 'cold'
  const cacheProbeStatus = sourceCacheProbeStatus ?? manifest.source_candidate?.cache_probe_status ?? null
  const coldClaimScope: VideoReleaseCaseCacheTimingPlan['cold_claim_scope'] = !isCold
    ? 'not_cold_run'
    : !coldCacheReadsDisabled
      ? 'invalid_until_cache_reads_disabled'
      : cacheProbeStatus === 'possible_existing_cache'
        ? 'ai_card_cache_cold_source_cache_possible'
        : 'source_probe_clean_ai_card_cache_reads_disabled'
  const disableCacheRead = isCold && coldCacheReadsDisabled

  return {
    schema_version: 1,
    case_id: caseId,
    status: 'planned_not_observed',
    matrix_pass_created: false,
    declared_cache_state: releaseCase.cacheState,
    source_kind: releaseCase.sourceKind,
    target_card_count: releaseCase.targetCardCount,
    source_cache_probe_status: cacheProbeStatus,
    existing_url_cache_dirs: [...existingUrlCacheDirs],
    cold_cache_reads_disabled: isCold ? coldCacheReadsDisabled : null,
    cold_claim_scope: coldClaimScope,
    planned_payload_flags: {
      disable_ai_review_cache_read: disableCacheRead,
      disable_ai_review_cache_write: false,
      disable_card_generation_cache_read: disableCacheRead,
      disable_card_generation_cache_write: false,
    },
    required_cache_summary_fields: [
      'schema_version',
      'case_id',
      'declared_cache_state',
      'observed_cache_state',
      'source_cache_probe_status',
      'existing_url_cache_dirs',
      'cold_cache_reads_disabled',
      'cold_claim_scope',
      'ai_review_cache.read_enabled',
      'ai_review_cache.write_enabled',
      'ai_review_cache.hits',
      'ai_review_cache.misses',
      'ai_review_cache.total',
      'card_generation_cache.read_enabled',
      'card_generation_cache.write_enabled',
      'card_generation_cache.hits',
      'card_generation_cache.misses',
      'card_generation_cache.total',
      'tts_cache.hits',
      'tts_cache.misses',
      'tts_cache.total',
      'media_cache.hits',
      'media_cache.misses',
      'media_cache.total',
    ],
    required_timing_fields: [
      'schema_version',
      'case_id',
      'declared_cache_state',
      'observed_cache_state',
      'source_prepare_ms',
      'learning_point_extract_ms',
      'ai_review_ms',
      'card_body_ms',
      'tts_ms',
      'media_slice_ms',
      'apkg_pack_ms',
      'anki_verify_ms',
      'total_ms',
      'timing_card_count',
      'per_card_ms',
      'stage_per_card_ms.card_body',
      'stage_per_card_ms.tts',
      'stage_per_card_ms.media_slice',
      'stage_per_card_ms.apkg_pack',
      'stage_per_card_ms.anki_verify',
      'stage_per_card_ms.total',
      'bottleneck_stage',
      'bottleneck_ms',
    ],
    artifact_paths: {
      timing: `cases/${caseId}/timing.json`,
      cache_summary: `cases/${caseId}/cache_summary.json`,
    },
    notes:
      'Plan only. The real run must write timing.json and cache_summary.json from observed extraction/generation/export/verify results before this case can pass.',
  }
}

export function evaluateVideoReleaseCaseCompletionEvidence({
  caseId,
  manifest,
  apkgFiles = [],
  screenshotFiles = [],
  sourceProvenance,
  deckMetadata,
  ankiVerify,
  audioAudit,
  timing,
  cacheSummary,
  observations,
  computerUseActions,
  screenshotManifest,
}: VideoReleaseCaseCompletionEvidenceInput): VideoReleaseCaseCompletionEvidence {
  const releaseCase = releaseCaseById(caseId)
  const expectedCards = completionExpectedCards(releaseCase)
  const failedChecks: string[] = []
  const warnings: string[] = []
  const sourceFingerprint = completionSourceFingerprint(manifest, releaseCase, failedChecks)

  if (manifest.case_id !== caseId) {
    failedChecks.push('case_manifest_id_mismatch')
  }
  if (manifest.status !== 'passed') {
    failedChecks.push('case_manifest_not_passed')
  }
  if (manifest.target_card_count !== releaseCase.targetCardCount) {
    failedChecks.push('case_manifest_target_card_count_mismatch')
  }
  if (manifest.required_preview_cards !== releaseCase.requiredPreviewCards) {
    failedChecks.push('case_manifest_required_preview_cards_mismatch')
  }

  const apkgIdentity = canonicalApkgIdentity(apkgFiles, caseId, failedChecks)
  const screenshotEvidenceFiles = normalizeScreenshotEvidenceFiles(screenshotFiles)
  if (screenshotEvidenceFiles.length < releaseCase.requiredPreviewCards) {
    failedChecks.push('screenshots_below_required_preview_count')
  }

  const screenshotManifestRecord = unknownRecord(screenshotManifest)
  const screenshotManifestSessionId = evidenceSessionId(screenshotManifestRecord)
  const screenshotManifestItems = screenshotManifestEntries(screenshotManifestRecord)
  if (!screenshotManifest) {
    failedChecks.push('screenshot_manifest_missing')
  } else {
    if (screenshotManifestSchemaVersion(screenshotManifestRecord) !== 1) {
      failedChecks.push('screenshot_manifest_schema_version_mismatch')
    }
    if (screenshotManifestRecord.case_id !== caseId) {
      failedChecks.push('screenshot_manifest_case_id_mismatch')
    }
    if (!screenshotManifestSessionId) {
      failedChecks.push('screenshot_manifest_session_id_missing')
    }
    if (screenshotManifestItems.length === 0) {
      failedChecks.push('screenshot_manifest_entry_invalid')
    } else {
      if (
        screenshotManifestItems.some(
          (entry) => !screenshotManifestEntryHasFileReference(entry, screenshotEvidenceFiles),
        )
      ) {
        failedChecks.push('screenshot_manifest_file_not_found')
      }
      if (
        screenshotManifestSessionId &&
        screenshotManifestHasInvalidEntries(
          screenshotManifestItems,
          screenshotEvidenceFiles,
          releaseCase,
          screenshotManifestSessionId,
        )
      ) {
        failedChecks.push('screenshot_manifest_entry_invalid')
      }
      if (screenshotManifestHasSha256Mismatch(screenshotManifestItems, screenshotEvidenceFiles)) {
        failedChecks.push('screenshot_manifest_sha256_mismatch')
      }
      if (screenshotManifestHasFileReusedForMultipleCardIndices(screenshotManifestItems, screenshotEvidenceFiles)) {
        failedChecks.push('screenshot_manifest_file_reused_for_multiple_card_indices')
      }
    }
  }

  const provenance = unknownRecord(sourceProvenance)
  if (!sourceProvenance) {
    failedChecks.push('source_provenance_missing')
  } else {
    if (looksLikeWriterHandoffArtifact(provenance)) {
      failedChecks.push('source_provenance_writer_handoff_artifact_present')
    }
    validateSourceProvenanceArtifact({
      artifact: provenance,
      releaseCase,
      caseId,
      sourceFingerprint,
      failedChecks,
    })
  }

  const deck = unknownRecord(deckMetadata)
  if (!deckMetadata) {
    failedChecks.push('deck_metadata_missing')
  } else {
    if (!String(deck.deck_name ?? '').trim()) {
      failedChecks.push('deck_metadata_deck_name_missing')
    }
    if (!String(deck.model_name ?? deck.template_name ?? '').trim()) {
      failedChecks.push('deck_metadata_model_name_missing')
    }
    const deckCardCount = countFromRecord(deck, ['card_count', 'exported_count', 'generated_count'])
    if (countMismatchesExpectedCards(deckCardCount, releaseCase)) {
      failedChecks.push('deck_metadata_card_count_mismatch')
    }
    validateArtifactIdentity({
      artifact: deck,
      prefix: 'deck_metadata',
      caseId,
      sourceFingerprint,
      apkgIdentity,
      failedChecks,
    })
  }

  const anki = unknownRecord(ankiVerify)
  if (!ankiVerify) {
    failedChecks.push('anki_verify_missing')
  } else {
    if (looksLikeWriterHandoffArtifact(anki)) {
      failedChecks.push('anki_verify_writer_handoff_artifact_present')
    }
    if (anki.ok !== true) {
      failedChecks.push('anki_verify_not_ok')
    }
    if (anki.import_attempted !== true) {
      failedChecks.push('anki_verify_import_not_attempted')
    }
    if (anki.import_result !== true) {
      failedChecks.push('anki_verify_import_result_not_true')
    }
    if (!hasNoFailures(anki.failed_checks)) {
      failedChecks.push('anki_verify_failed_checks_present')
    }
    const verifiedCards = countFromRecord(anki, ['card_count', 'imported_card_count', 'verified_card_count'])
    if (countMismatchesExpectedCards(verifiedCards, releaseCase)) {
      failedChecks.push('anki_verify_card_count_mismatch')
    }
    const expectedVerifyCards = numberValue(anki.expected_cards)
    if (countMismatchesExpectedCards(expectedVerifyCards, releaseCase)) {
      failedChecks.push('anki_verify_expected_cards_mismatch')
    }
    const importedCards = numberValue(anki.imported_card_count)
    if (importedCards !== null && importedCards < expectedCards) {
      failedChecks.push('anki_verify_imported_card_count_below_expected')
    }
    const ledgerCount = numberValue(anki.card_media_ledger_count)
    if (countMismatchesExpectedCards(ledgerCount, releaseCase)) {
      failedChecks.push('anki_verify_card_media_ledger_count_mismatch')
    }
    const mediaExpected = numberValue(anki.media_count_expected)
    const mediaReferenced = numberValue(anki.media_count_referenced)
    const mediaChecked = numberValue(anki.media_count_checked)
    if (mediaExpected === null || mediaExpected <= 0) {
      failedChecks.push('anki_verify_media_count_expected_missing')
    }
    if (mediaExpected !== null && mediaReferenced !== mediaExpected) {
      failedChecks.push('anki_verify_media_count_referenced_mismatch')
    }
    if (mediaExpected !== null && mediaChecked !== mediaExpected) {
      failedChecks.push('anki_verify_media_count_checked_mismatch')
    }
    if (!hasNoFailures(anki.mismatched_media)) {
      failedChecks.push('anki_verify_media_hash_mismatch')
    }
    if (!hasNoFailures(anki.missing_media)) {
      failedChecks.push('anki_verify_missing_media')
    }
    for (const [field, check] of [
      ['audio_audit_mismatches', 'anki_verify_audio_audit_mismatch'],
      ['card_media_ledger_mismatches', 'anki_verify_card_media_ledger_mismatch'],
      ['media_ledger_card_text_mismatches', 'anki_verify_media_ledger_card_text_mismatch'],
      ['unexpected_media_references', 'anki_verify_unexpected_media_references'],
      ['unreferenced_expected_media', 'anki_verify_unreferenced_expected_media'],
      ['ledger_text_hash_mismatch', 'anki_verify_ledger_text_hash_mismatch'],
      ['missing_video_field_media', 'anki_verify_missing_video_field_media'],
      ['imported_tts_text_hash_mismatch', 'anki_verify_imported_tts_text_hash_mismatch'],
      ['inaccessible_media', 'anki_verify_inaccessible_media'],
      ['ledger_missing_manifest', 'anki_verify_ledger_missing_manifest'],
      ['manifest_tts_without_ledger', 'anki_verify_manifest_tts_without_ledger'],
      ['audio_audit_write_errors', 'anki_verify_audio_audit_write_errors'],
      ['ciba_model_names', 'anki_verify_ciba_model_present'],
      ['video_template_mismatches', 'anki_verify_video_template_mismatch'],
      ['document_template_mismatches', 'anki_verify_document_template_mismatch'],
    ] as const) {
      if (!hasNoFailures(anki[field])) {
        failedChecks.push(check)
      }
    }
    const auditSummary = unknownRecord(anki.audio_audit_summary)
    if (auditSummary.status !== 'passed') {
      failedChecks.push('anki_verify_audio_audit_status_not_passed')
    }
    const ankiAuditItems = numberValue(auditSummary.items ?? auditSummary.expected_items)
    if (countMismatchesExpectedCards(ankiAuditItems, releaseCase)) {
      failedChecks.push('anki_verify_audio_audit_count_mismatch')
    }
    validateArtifactIdentity({
      artifact: anki,
      prefix: 'anki_verify',
      caseId,
      sourceFingerprint,
      apkgIdentity,
      failedChecks,
    })
  }

  const audit = unknownRecord(audioAudit)
  const auditSummary = unknownRecord(audit.summary)
  const auditItems = arrayValue(audit.items).map(unknownRecord)
  if (!audioAudit) {
    failedChecks.push('audio_audit_missing')
  } else {
    if (auditSummary.status !== 'passed') {
      failedChecks.push('audio_audit_status_not_passed')
    }
    const itemCount = numberValue(auditSummary.items)
    const expectedItemCount = numberValue(auditSummary.expected_items)
    if (
      countMismatchesExpectedCards(itemCount, releaseCase) ||
      countMismatchesExpectedCards(auditItems.length, releaseCase) ||
      countMismatchesExpectedCards(expectedItemCount, releaseCase)
    ) {
      failedChecks.push('audio_audit_count_mismatch')
    }
    if (numberValue(auditSummary.failed) !== 0) {
      failedChecks.push('audio_audit_failed_nonzero')
    }
    if (numberValue(auditSummary.mismatches) !== 0) {
      failedChecks.push('audio_audit_mismatch_nonzero')
    }
    if (numberValue(auditSummary.manual_review_required) !== 0) {
      failedChecks.push('audio_audit_manual_review_nonzero')
    }
    const alignment = unknownRecord(auditSummary.media_subtitle_alignment)
    if ((numberValue(alignment.mismatch) ?? 0) > 0 || (numberValue(alignment.unknown) ?? 0) > 0) {
      failedChecks.push('audio_audit_media_subtitle_alignment_not_clean')
    }
    const missingItemFields = auditItems.some((item) => {
      const hashes = unknownRecord(item.media_hashes)
      const ttsHashes = unknownRecord(item.tts_text_hashes)
      const ankiFields = unknownRecord(item.anki_fields)
      const ankiMediaExists = unknownRecord(item.anki_media_exists)
      const requiredMediaNames = [
        item.original_audio,
        item.sentence_tts_file,
        item.phrase_tts_file,
        item.video_mp4 || item.video_webm,
      ]
        .map((value) => String(value ?? '').trim())
        .filter(Boolean)
      return (
        !String(item.card_id ?? '').trim() ||
        !String(item.source_sentence ?? '').trim() ||
        !String(item.card_display_sentence ?? '').trim() ||
        !String(item.media_alignment_text ?? '').trim() ||
        !String(item.media_alignment_source_text ?? '').trim() ||
        !String(item.media_window_subtitle_text ?? '').trim() ||
        !String(item.visible_answer ?? '').trim() ||
        !String(item.original_audio ?? '').trim() ||
        !String(item.sentence_tts_expected_text ?? '').trim() ||
        !String(item.phrase_tts_expected_text ?? '').trim() ||
        !String(item.sentence_tts_file ?? '').trim() ||
        !String(item.phrase_tts_file ?? '').trim() ||
        !String(ttsHashes.sentence_tts ?? '').trim() ||
        !String(ttsHashes.phrase_tts ?? '').trim() ||
        numberValue(item.media_start) === null ||
        numberValue(item.media_end) === null ||
        !String(item.media_source_time ?? '').trim() ||
        (!String(item.video_mp4 ?? '').trim() && !String(item.video_webm ?? '').trim()) ||
        String(item.media_subtitle_alignment_status ?? '') !== 'matched' ||
        !String(hashes.original_audio ?? '').trim() ||
        !String(hashes.sentence_tts_audio ?? '').trim() ||
        !String(hashes.phrase_tts_audio ?? '').trim() ||
        arrayValue(ankiFields.Audio).length === 0 ||
        arrayValue(ankiFields.TtsAudio).length === 0 ||
        arrayValue(ankiFields.PhraseTtsAudio).length === 0 ||
        arrayValue(ankiFields.Video).length === 0 ||
        requiredMediaNames.some((name) => ankiMediaExists[name] !== true)
      )
    })
    if (missingItemFields) {
      failedChecks.push('audio_audit_item_required_fields_missing')
    }
  }

  const timingRecord = unknownRecord(timing)
  const timingRequired = buildVideoReleaseCaseCacheTimingPlan({ caseId, manifest }).required_timing_fields
  if (!timing) {
    failedChecks.push('timing_missing')
  } else {
    if (looksLikeWriterHandoffArtifact(timingRecord)) {
      failedChecks.push('timing_writer_handoff_artifact_present')
    }
    for (const field of timingRequired) {
      const value = valueAtPath(timingRecord, field)
      if (
        field === 'case_id' ||
        field === 'declared_cache_state' ||
        field === 'observed_cache_state' ||
        field === 'bottleneck_stage'
      ) {
        if (!String(value ?? '').trim()) {
          failedChecks.push(`timing_${field}_missing`)
        }
      } else if (numberValue(value) === null) {
        failedChecks.push(`timing_${field}_missing`)
      }
    }
    if (numberValue(timingRecord.schema_version) !== 1) {
      failedChecks.push('timing_schema_version_mismatch')
    }
    if (timingRecord.case_id !== caseId) {
      failedChecks.push('timing_case_id_mismatch')
    }
    validateArtifactIdentity({
      artifact: timingRecord,
      prefix: 'timing',
      caseId,
      sourceFingerprint,
      apkgIdentity,
      failedChecks,
    })
    if (timingRecord.declared_cache_state !== releaseCase.cacheState) {
      failedChecks.push('timing_declared_cache_state_mismatch')
    }
    if (timingRecord.observed_cache_state !== releaseCase.cacheState) {
      failedChecks.push('timing_observed_cache_state_mismatch')
    }
    const totalMs = numberValue(timingRecord.total_ms)
    const timingCardCount = numberValue(timingRecord.timing_card_count)
    if (totalMs === null || totalMs <= 0) {
      failedChecks.push('timing_total_ms_not_positive')
    }
    if (countMismatchesExpectedCards(timingCardCount, releaseCase)) {
      failedChecks.push('timing_card_count_mismatch')
    }
    const perCardMs = numberValue(timingRecord.per_card_ms)
    if (
      totalMs !== null &&
      timingCardCount !== null &&
      timingCardCount > 0 &&
      perCardMs !== Math.round(totalMs / timingCardCount)
    ) {
      failedChecks.push('timing_per_card_ms_mismatch')
    }
    for (const [stageField, perCardField] of TIMING_STAGE_PER_CARD_FIELDS) {
      const stageMs = numberValue(timingRecord[stageField])
      const stagePerCardMs = numberValue(valueAtPath(timingRecord, perCardField))
      if (
        stageMs !== null &&
        timingCardCount !== null &&
        timingCardCount > 0 &&
        stagePerCardMs !== Math.round(stageMs / timingCardCount)
      ) {
        failedChecks.push(`timing_${perCardField.replaceAll('.', '_')}_mismatch`)
      }
    }
    const totalStagePerCardMs = numberValue(valueAtPath(timingRecord, 'stage_per_card_ms.total'))
    if (perCardMs !== null && totalStagePerCardMs !== perCardMs) {
      failedChecks.push('timing_stage_per_card_ms_total_mismatch')
    }
    const bottleneckStage = String(timingRecord.bottleneck_stage ?? '')
    const bottleneckMs = numberValue(timingRecord.bottleneck_ms)
    const stageValues = TIMING_STAGE_MS_FIELDS.map((field) => numberValue(timingRecord[field]))
    if (!TIMING_BOTTLENECK_STAGES.some(([stage]) => stage === bottleneckStage)) {
      failedChecks.push('timing_bottleneck_stage_invalid')
    }
    if (stageValues.every((value): value is number => value !== null)) {
      const maxStageMs = Math.max(...stageValues)
      const matchedBottleneck = TIMING_BOTTLENECK_STAGES.find(([stage]) => stage === bottleneckStage)
      if (bottleneckMs !== maxStageMs) {
        failedChecks.push('timing_bottleneck_ms_mismatch')
      }
      if (matchedBottleneck && numberValue(timingRecord[matchedBottleneck[1]]) !== maxStageMs) {
        failedChecks.push('timing_bottleneck_stage_not_max')
      }
    }
  }

  const cacheRecord = unknownRecord(cacheSummary)
  const cachePlan = buildVideoReleaseCaseCacheTimingPlan({ caseId, manifest })
  if (!cacheSummary) {
    failedChecks.push('cache_summary_missing')
  } else {
    if (looksLikeWriterHandoffArtifact(cacheRecord)) {
      failedChecks.push('cache_summary_writer_handoff_artifact_present')
    }
    for (const field of cachePlan.required_cache_summary_fields) {
      if (valueAtPath(cacheRecord, field) === undefined) {
        failedChecks.push(`cache_summary_${field}_missing`)
      }
    }
    if (numberValue(cacheRecord.schema_version) !== 1) {
      failedChecks.push('cache_summary_schema_version_mismatch')
    }
    if (cacheRecord.case_id !== caseId) {
      failedChecks.push('cache_summary_case_id_mismatch')
    }
    validateArtifactIdentity({
      artifact: cacheRecord,
      prefix: 'cache_summary',
      caseId,
      sourceFingerprint,
      apkgIdentity,
      failedChecks,
    })
    if (cacheRecord.declared_cache_state !== releaseCase.cacheState) {
      failedChecks.push('cache_summary_declared_cache_state_mismatch')
    }
    if (cacheRecord.observed_cache_state !== releaseCase.cacheState) {
      failedChecks.push('cache_summary_observed_cache_state_mismatch')
    }
    if (!Array.isArray(cacheRecord.existing_url_cache_dirs)) {
      failedChecks.push('cache_summary_existing_url_cache_dirs_not_array')
    }
    const cacheCounts = Object.fromEntries(
      CACHE_GROUP_KEYS.map((groupKey) => [groupKey, cacheGroupCounts(cacheRecord, groupKey)]),
    )
    for (const groupKey of CACHE_GROUP_KEYS) {
      const counts = cacheCounts[groupKey]
      if (!counts) {
        failedChecks.push(`cache_summary_${groupKey}_counts_missing`)
      } else if (counts.hits < 0 || counts.misses < 0 || counts.total < 0) {
        failedChecks.push(`cache_summary_${groupKey}_counts_negative`)
      } else if (counts.hits + counts.misses !== counts.total) {
        failedChecks.push(`cache_summary_${groupKey}_total_mismatch`)
      }
    }
    if (releaseCase.cacheState === 'cold' && cacheRecord.cold_cache_reads_disabled !== true) {
      failedChecks.push('cache_summary_cold_reads_not_disabled')
    }
    if (releaseCase.cacheState === 'cold') {
      const aiRead = booleanValue(valueAtPath(cacheRecord, 'ai_review_cache.read_enabled'))
      const cardRead = booleanValue(valueAtPath(cacheRecord, 'card_generation_cache.read_enabled'))
      if (aiRead !== false || cardRead !== false) {
        failedChecks.push('cache_summary_cold_ai_card_reads_enabled')
      }
      const aiCounts = cacheCounts.ai_review_cache
      const cardCounts = cacheCounts.card_generation_cache
      const ttsCounts = cacheCounts.tts_cache
      const mediaCounts = cacheCounts.media_cache
      if ((aiCounts && aiCounts.hits !== 0) || (cardCounts && cardCounts.hits !== 0)) {
        failedChecks.push('cache_summary_cold_ai_card_hits_nonzero')
      }
      if (cardCounts && cardCounts.misses < expectedCards) {
        failedChecks.push('cache_summary_cold_card_generation_misses_below_expected')
      }
      if ((ttsCounts && ttsCounts.hits !== 0) || (mediaCounts && mediaCounts.hits !== 0)) {
        failedChecks.push('cache_summary_cold_tts_media_hits_nonzero')
      }
    }
    if (releaseCase.cacheState === 'hot') {
      const aiRead = booleanValue(valueAtPath(cacheRecord, 'ai_review_cache.read_enabled'))
      const cardRead = booleanValue(valueAtPath(cacheRecord, 'card_generation_cache.read_enabled'))
      const cardCounts = cacheCounts.card_generation_cache
      const ttsCounts = cacheCounts.tts_cache
      const mediaCounts = cacheCounts.media_cache
      if (aiRead !== true || cardRead !== true) {
        failedChecks.push('cache_summary_hot_ai_card_reads_not_enabled')
      }
      if (cardCounts && cardCounts.hits < expectedCards) {
        failedChecks.push('cache_summary_hot_card_generation_hits_below_expected')
      }
      if (cardCounts && cardCounts.misses !== 0) {
        failedChecks.push('cache_summary_hot_card_generation_misses_nonzero')
      }
      if (ttsCounts && (ttsCounts.total <= 0 || ttsCounts.misses !== 0 || ttsCounts.hits !== ttsCounts.total)) {
        failedChecks.push('cache_summary_hot_tts_hits_below_expected')
      }
      if (mediaCounts && mediaCounts.hits < expectedCards) {
        failedChecks.push('cache_summary_hot_media_hits_below_expected')
      }
    }
  }

  const obs = unknownRecord(observations)
  const observedCount = countFromRecord(obs, ['count', 'previewed_cards', 'observed_cards'])
  const observationItems = arrayValue(obs.observations).map(unknownRecord)
  const observationSessionId = evidenceSessionId(obs)
  const actions = unknownRecord(computerUseActions)
  const actionItems = arrayValue(actions.actions).map(unknownRecord)
  const actionSessionId = evidenceSessionId(actions)
  const sessionIds = [screenshotManifestSessionId, observationSessionId, actionSessionId].filter(Boolean)
  if (new Set(sessionIds).size > 1) {
    failedChecks.push('computer_use_session_id_mismatch')
  }
  if (!observations) {
    failedChecks.push('observations_missing')
  } else {
    if (looksLikeWriterHandoffArtifact(obs)) {
      failedChecks.push('observations_writer_handoff_artifact_present')
    }
    if (obs.case_id !== caseId) {
      failedChecks.push('observations_case_id_mismatch')
    }
    if (!observationSessionId) {
      failedChecks.push('observations_session_id_missing')
    } else if (recordsMissingSessionId(observationItems, observationSessionId)) {
      failedChecks.push('observations_item_session_id_missing_or_mismatch')
    }
    if (
      screenshotManifestItems.length > 0 &&
      observationItems.some(
        (item) =>
          observationScreenshotReferences(item).length > 0 &&
          !observationScreenshotReferencesPresentInManifest(item, screenshotManifestItems, screenshotEvidenceFiles),
      )
    ) {
      failedChecks.push('observations_item_screenshot_not_in_manifest')
    }
    if (
      screenshotManifestItems.length > 0 &&
      observationItems.some(
        (item) =>
          observationScreenshotReferences(item).length > 0 &&
          observationScreenshotReferencesPresentInManifest(item, screenshotManifestItems, screenshotEvidenceFiles) &&
          !observationScreenshotReferencesMatchManifestCardIndex(item, screenshotManifestItems, screenshotEvidenceFiles),
      )
    ) {
      failedChecks.push('observations_item_screenshot_card_index_mismatch')
    }
    if ((observedCount ?? observationItems.length) < releaseCase.requiredPreviewCards) {
      failedChecks.push('observations_below_required_preview_count')
    }
    if (observationItems.length < releaseCase.requiredPreviewCards) {
      failedChecks.push('observations_items_below_required_preview_count')
    }
    const fullObservationItems = observationItems.filter((item) =>
      observationHasRequiredFullCardEvidence(item, screenshotEvidenceFiles),
    )
    if (fullObservationItems.length < observationItems.length) {
      failedChecks.push('observations_missing_required_full_card_evidence')
    }
    const computerUseBackedObservationItems = fullObservationItems.filter((item) =>
      observationHasLinkedPlaybackActions(item, actionItems, releaseCase),
    )
    if (computerUseBackedObservationItems.length < fullObservationItems.length) {
      failedChecks.push('observations_missing_computer_use_action_links')
    }
    if (
      observationItems.some(
        (item) =>
          observationScreenshotReferences(item).length > 0 &&
          !observationHasMatchedScreenshot(item, screenshotEvidenceFiles),
      )
    ) {
      failedChecks.push('observations_item_screenshot_not_found')
    }
    const observedIndices = new Set(
      computerUseBackedObservationItems.map(observationCardIndex).filter((value): value is number => value !== null),
    )
    if (releaseCase.inspection === 'all_cards') {
      for (let index = 1; index <= releaseCase.requiredPreviewCards; index += 1) {
        if (!observedIndices.has(index)) {
          failedChecks.push('observations_missing_required_card_indices')
          break
        }
      }
    }
    if (releaseCase.inspection === 'sample_open_middle_end') {
      const hasStart = [...observedIndices].some((index) => index <= 4)
      const hasMiddle = [...observedIndices].some((index) => index >= 45 && index <= 60)
      const hasEnd = [...observedIndices].some((index) => index >= 97)
      if (!hasStart || !hasMiddle || !hasEnd) {
        failedChecks.push('observations_stress_sample_missing_start_middle_end')
      }
    }
  }

  if (!computerUseActions) {
    failedChecks.push('computer_use_actions_missing')
  } else {
    if (looksLikeWriterHandoffArtifact(actions)) {
      failedChecks.push('computer_use_writer_handoff_artifact_present')
    }
    if (actions.case_id !== caseId) {
      failedChecks.push('computer_use_actions_case_id_mismatch')
    }
    if (!actionSessionId) {
      failedChecks.push('computer_use_actions_session_id_missing')
    } else if (recordsMissingSessionId(actionItems, actionSessionId)) {
      failedChecks.push('computer_use_action_session_id_missing_or_mismatch')
    }
    if (actionItems.length === 0) {
      failedChecks.push('computer_use_actions_trace_missing')
    } else {
      if (!actionTraceHasPositiveUniqueOrders(actionItems)) {
        failedChecks.push('computer_use_action_order_not_positive_unique')
      }
      if (playbackCandidateRowsMissingExplicitRole(actionItems)) {
        failedChecks.push('computer_use_action_role_missing_or_invalid')
      }
      if (playbackCandidateRowsMissingExplicitSuccessfulOutcome(actionItems)) {
        failedChecks.push('computer_use_action_rows_missing_explicit_successful_playback_outcome')
      }
      if (playbackCandidateRowsHaveOutOfBoundsCardIndex(actionItems, releaseCase)) {
        failedChecks.push('computer_use_action_card_index_out_of_bounds')
      }
      if (!actionTraceHasRequiredPlaybackCoverage(actionItems, releaseCase)) {
        failedChecks.push('computer_use_action_trace_missing_required_playback_coverage')
      }
    }
    const previewedCards = countFromRecord(actions, ['previewed_cards', 'observed_cards', 'count'])
    if (previewedCards === null || previewedCards < releaseCase.requiredPreviewCards) {
      failedChecks.push('computer_use_previewed_cards_below_required')
    }
    for (const role of VIDEO_RELEASE_PLAYBACK_CHECKS) {
      const roleCount = playbackCardIndicesForRole(actionItems, releaseCase, role).size
      const summaryCount = playbackSummaryCountFromActions(actions, COMPUTER_USE_PLAYBACK_ROLE_ALIASES[role])
      if (summaryCount !== null && summaryCount !== roleCount) {
        failedChecks.push('computer_use_playback_counts_disagree_with_action_trace')
      }
      if (roleCount < releaseCase.requiredPreviewCards) {
        failedChecks.push(`computer_use_${role}_clicks_below_required`)
      }
    }
    if (releaseCase.id === 'stress_100_plus_one_click') {
      const generationClicks = countFromRecord(actions, [
        'generation_clicks',
        'generate_clicks',
        'primary_generate_clicks',
      ])
      if (generationClicks !== 1) {
        failedChecks.push('computer_use_stress_generation_click_not_one')
      }
    }
  }

  const uniqueFailedChecks = [...new Set(failedChecks)]
  return {
    ok: uniqueFailedChecks.length === 0,
    failedChecks: uniqueFailedChecks,
    warnings,
    expectedCards,
    requiredPreviewCards: releaseCase.requiredPreviewCards,
  }
}

export function buildVideoReleaseEvidenceLayout(runStamp: string) {
  return {
    runDirName: videoReleaseRunDirName(runStamp),
    topLevelEvidence: [...VIDEO_RELEASE_TOP_LEVEL_EVIDENCE_ITEMS],
    cases: VIDEO_RELEASE_CASES.map((releaseCase) => ({
      ...releaseCase,
      relativeDir: `cases/${releaseCase.id}`,
      evidencePaths: videoReleaseCaseEvidencePaths(releaseCase.id),
    })),
  }
}

function prettyJson(value: unknown): string {
  return `${JSON.stringify(value, null, 2)}\n`
}

function releaseCaseChecklist(releaseCase: VideoReleaseCase) {
  return {
    case_id: releaseCase.id,
    status: 'not_started',
    source: releaseCase.source,
    source_kind: releaseCase.sourceKind,
    mode: releaseCase.mode,
    cache_state: releaseCase.cacheState,
    target_card_count: releaseCase.targetCardCount,
    minimum_generated_cards:
      'minimumGeneratedCards' in releaseCase ? releaseCase.minimumGeneratedCards : releaseCase.targetCardCount,
    required_preview_cards: releaseCase.requiredPreviewCards,
    inspection: releaseCase.inspection,
    required_playback_checks: [...VIDEO_RELEASE_PLAYBACK_CHECKS],
    required_evidence: videoReleaseCaseEvidencePaths(releaseCase.id),
    pass_criteria: {
      verify_anki_import_ok: true,
      failed_checks: [],
      media_hash_mismatch_count: 0,
      audio_audit_count_equals_video_card_count: true,
      no_wrong_audio: true,
      no_video_misalignment: true,
      no_field_mixing: true,
      no_missing_media: true,
      no_crash: true,
    },
    notes:
      'Do not mark passed until Computer Use has opened the required Anki cards and clicked video, original audio, sentence TTS, and expression TTS.',
  }
}

export function buildVideoReleaseRunInitializerPlan(runStamp: string) {
  const layout = buildVideoReleaseEvidenceLayout(runStamp)
  const directories = [
    'cases',
    ...layout.cases.flatMap((releaseCase) => [
      releaseCase.relativeDir,
      `${releaseCase.relativeDir}/apkg`,
      `${releaseCase.relativeDir}/screenshots`,
    ]),
  ]
  const caseFiles: VideoReleaseInitializerFile[] = layout.cases.map((releaseCase) => ({
    relativePath: `${releaseCase.relativeDir}/case_manifest.json`,
    content: prettyJson(releaseCaseChecklist(releaseCase)),
  }))
  const seedFiles: VideoReleaseInitializerFile[] = [
    {
      relativePath: 'matrix_summary.json',
      content: prettyJson({
        run_dir: layout.runDirName,
        status: 'not_started',
        release_ready: false,
        cases: layout.cases.map((releaseCase) => ({
          case_id: releaseCase.id,
          status: 'not_started',
          target_card_count: releaseCase.targetCardCount,
          required_preview_cards: releaseCase.requiredPreviewCards,
          required_evidence_count: releaseCase.evidencePaths.length,
        })),
      }),
    },
    {
      relativePath: 'release_risk_report.md',
      content: [
        '# Video Release Risk Report',
        '',
        'Status: not started',
        '',
        'Do not mark production-grade until every matrix case passes APKG export, Anki import, Anki verify, audio audit, media hash checks, and Computer Use playback inspection.',
        '',
      ].join('\n'),
    },
    {
      relativePath: 'run_observations.md',
      content: [
        '# Video Release Run Observations',
        '',
        'Record source URLs/files, deck names, template names, timing bottlenecks, cache state, and any manual observations here.',
        '',
      ].join('\n'),
    },
    ...caseFiles,
  ]
  return {
    ...layout,
    directories,
    seedFiles,
  }
}
