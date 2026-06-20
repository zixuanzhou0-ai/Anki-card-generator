import type {
  VideoReleaseCaseId,
  VideoReleaseCaseManifest,
  VideoReleaseSourceCandidate,
} from '../domain/releaseEvidenceLayout.ts'
import {
  VIDEO_RELEASE_CASES,
  VIDEO_RELEASE_RUN_DIR_PREFIX,
  VIDEO_RELEASE_RUN_STAMP_PATTERN,
} from '../domain/releaseEvidenceLayout.ts'

type MaterialKind = 'youtube_url' | 'local_video_srt'

type MaterialManifestInput = {
  path: string
  value: unknown
}

export type ReleaseMaterialCandidatePromotionInput = {
  runDir: string
  youtubeMaterialManifest: MaterialManifestInput
  localSrtMaterialManifest: MaterialManifestInput
  caseManifests: Partial<Record<VideoReleaseCaseId, VideoReleaseCaseManifest>>
  selectedAt: string
  overwriteExisting?: boolean
}

export type ReleaseMaterialCandidateWrite = {
  kind: 'case_manifest_source_candidate'
  caseId: VideoReleaseCaseId
  relativePath: string
  absolutePath: string
  content: string
  writeMode: 'replace_existing_case_manifest'
}

export type ReleaseMaterialCandidatePromotionPlan = {
  ok: boolean
  status: 'ready_to_write' | 'blocked'
  matrixPassCreated: false
  failedChecks: string[]
  warnings: string[]
  runDir: string
  writes: ReleaseMaterialCandidateWrite[]
  promotedCases: VideoReleaseCaseId[]
  notes: string
}

type MaterialSelection = {
  caseIds: VideoReleaseCaseId[]
  manifest: MaterialManifestInput
  itemIndex: number
  sourceKind: MaterialKind
  releaseSource: string
}

type MaterialItemRecord = Record<string, unknown>

const MATERIAL_PROMOTIONS: MaterialSelection[] = [
  {
    caseIds: ['youtube_a_full1_cold', 'youtube_a_quick20_cold', 'youtube_a_quick20_hot'],
    manifest: { path: '', value: null },
    itemIndex: 1,
    sourceKind: 'youtube_url',
    releaseSource: 'youtube_a',
  },
  {
    caseIds: ['youtube_b_quick20_cold'],
    manifest: { path: '', value: null },
    itemIndex: 2,
    sourceKind: 'youtube_url',
    releaseSource: 'youtube_b',
  },
  {
    caseIds: ['local_srt_full1_cold', 'local_srt_quick20_cold', 'local_srt_quick20_hot'],
    manifest: { path: '', value: null },
    itemIndex: 1,
    sourceKind: 'local_video_srt',
    releaseSource: 'local_video_srt',
  },
]

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function numberValue(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function positiveInteger(value: unknown): number | null {
  const numeric = numberValue(value)
  return numeric !== null && Number.isInteger(numeric) && numeric > 0 ? numeric : null
}

function isSha256(value: string): boolean {
  return /^[a-f0-9]{64}$/i.test(value)
}

function isYoutubeFingerprint(value: string): boolean {
  return /^yt:[a-f0-9]{16}$/i.test(value)
}

function isLocalFingerprint(value: string): boolean {
  return /^file:[a-f0-9]{16}$/i.test(value)
}

function pathSegments(value: string): string[] {
  return value.split(/[\\/]+/).filter(Boolean)
}

function pathLooksAbsolute(value: string): boolean {
  return /^[A-Za-z]:[\\/]/.test(value) || value.startsWith('\\\\') || value.startsWith('/')
}

function pathHasTraversal(value: string): boolean {
  return pathSegments(value).some((segment) => segment === '..')
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
  return value.replace(/\\/g, '/').replace(/^\/+/, '').replace(/\/+/g, '/').replace(/\/$/, '')
}

function joinRunRelativePath(runDir: string, relativePath: string): string {
  const separator = runDir.includes('\\') ? '\\' : '/'
  const cleanRunDir = runDir.replace(/[\\/]+$/, '')
  return [cleanRunDir, ...normalizeRelativePath(relativePath).split('/')].join(separator)
}

function unique(values: string[]): string[] {
  return [...new Set(values)]
}

function prettyJson(value: unknown): string {
  return `${JSON.stringify(value, null, 2)}\n`
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

function materialItems(manifest: MaterialManifestInput, failedChecks: string[], label: string): MaterialItemRecord[] {
  if (!manifest.path) {
    failedChecks.push(`${label}_material_manifest_path_missing`)
  }
  if (!isRecord(manifest.value)) {
    failedChecks.push(`${label}_material_manifest_invalid`)
    return []
  }
  const items = Array.isArray(manifest.value.items) ? manifest.value.items : []
  if (items.length === 0) {
    failedChecks.push(`${label}_material_manifest_items_missing`)
    return []
  }
  return items.filter(isRecord)
}

function itemByIndex(
  manifest: MaterialManifestInput,
  itemIndex: number,
  failedChecks: string[],
  label: string,
): MaterialItemRecord | null {
  const item = materialItems(manifest, failedChecks, label).find((candidate) => candidate.index === itemIndex)
  if (!item) {
    failedChecks.push(`${label}_material_item_${itemIndex}_missing`)
    return null
  }
  return item
}

function youtubeCandidateFromItem({
  item,
  materialManifestPath,
  selectedAt,
  failedChecks,
  label,
}: {
  item: MaterialItemRecord
  materialManifestPath: string
  selectedAt: string
  failedChecks: string[]
  label: string
}): VideoReleaseSourceCandidate & Record<string, unknown> {
  const kind = stringValue(item.kind)
  const url = stringValue(item.url || item.webpage_url)
  const videoId = stringValue(item.video_id)
  const fingerprint = stringValue(item.source_fingerprint)
  const cacheProbe = isRecord(item.cache_probe) ? item.cache_probe : {}
  const cacheProbeStatus = stringValue(cacheProbe.status)

  if (kind !== 'youtube_url') {
    failedChecks.push(`${label}_material_item_not_youtube`)
  }
  if (!/^https?:\/\//i.test(url)) {
    failedChecks.push(`${label}_youtube_url_invalid`)
  }
  if (!videoId) {
    failedChecks.push(`${label}_youtube_video_id_missing`)
  }
  if (!isYoutubeFingerprint(fingerprint)) {
    failedChecks.push(`${label}_youtube_fingerprint_invalid`)
  }
  if (!cacheProbeStatus) {
    failedChecks.push(`${label}_cache_probe_status_missing`)
  }

  return {
    selected_at: selectedAt,
    material_manifest: materialManifestPath,
    url,
    title: stringValue(item.title),
    duration_seconds: numberValue(item.duration_seconds),
    channel: stringValue(item.channel),
    video_id: videoId,
    source_fingerprint: fingerprint,
    cache_probe_status: cacheProbeStatus,
    note: 'Promoted from verified material rotation manifest. Cold runs must still disable controllable cache reads.',
  }
}

function localCandidateFromItem({
  item,
  materialManifestPath,
  selectedAt,
  failedChecks,
  label,
}: {
  item: MaterialItemRecord
  materialManifestPath: string
  selectedAt: string
  failedChecks: string[]
  label: string
}): VideoReleaseSourceCandidate & Record<string, unknown> {
  const videoPath = stringValue(item.downloaded_video_path || item.video_path)
  const subtitlePath = stringValue(item.subtitle_path)
  const videoBytes = positiveInteger(item.video_bytes)
  const subtitleBytes = positiveInteger(item.subtitle_bytes)
  const videoSha = stringValue(item.video_sha256)
  const subtitleSha = stringValue(item.subtitle_sha256)
  const fingerprint = stringValue(item.source_fingerprint)
  const cacheProbe = isRecord(item.cache_probe) ? item.cache_probe : {}
  const cacheProbeStatus = stringValue(cacheProbe.status)

  if (!videoPath) {
    failedChecks.push(`${label}_local_video_path_missing`)
  }
  if (!subtitlePath) {
    failedChecks.push(`${label}_local_subtitle_path_missing`)
  }
  if (videoBytes === null) {
    failedChecks.push(`${label}_local_video_bytes_missing`)
  }
  if (subtitleBytes === null) {
    failedChecks.push(`${label}_local_subtitle_bytes_missing`)
  }
  if (!isSha256(videoSha)) {
    failedChecks.push(`${label}_local_video_sha256_invalid`)
  }
  if (!isSha256(subtitleSha)) {
    failedChecks.push(`${label}_local_subtitle_sha256_invalid`)
  }
  if (!isLocalFingerprint(fingerprint)) {
    failedChecks.push(`${label}_local_fingerprint_invalid`)
  }
  if (!cacheProbeStatus) {
    failedChecks.push(`${label}_cache_probe_status_missing`)
  }

  return {
    selected_at: selectedAt,
    material_manifest: materialManifestPath,
    url: stringValue(item.url || item.webpage_url),
    title: stringValue(item.title),
    duration_seconds: numberValue(item.duration_seconds),
    channel: stringValue(item.channel),
    video_id: stringValue(item.video_id),
    downloaded_video_path: videoPath,
    video_path: videoPath,
    subtitle_path: subtitlePath,
    source_fingerprint: fingerprint,
    cache_probe_status: cacheProbeStatus,
    note: 'Promoted from verified local video+SRT material rotation manifest. Cold runs must still disable controllable cache reads.',
    video_bytes: videoBytes ?? undefined,
    subtitle_bytes: subtitleBytes ?? undefined,
    video_sha256: videoSha,
    subtitle_sha256: subtitleSha,
  }
}

function releaseCaseDefinition(caseId: VideoReleaseCaseId) {
  return VIDEO_RELEASE_CASES.find((releaseCase) => releaseCase.id === caseId)
}

function writeForCase({
  runDir,
  caseId,
  manifest,
}: {
  runDir: string
  caseId: VideoReleaseCaseId
  manifest: VideoReleaseCaseManifest
}): ReleaseMaterialCandidateWrite {
  const relativePath = `cases/${caseId}/case_manifest.json`
  return {
    kind: 'case_manifest_source_candidate',
    caseId,
    relativePath,
    absolutePath: joinRunRelativePath(runDir, relativePath),
    content: prettyJson(manifest),
    writeMode: 'replace_existing_case_manifest',
  }
}

export function buildReleaseMaterialCandidatePromotionPlan(
  input: ReleaseMaterialCandidatePromotionInput,
): ReleaseMaterialCandidatePromotionPlan {
  const failedChecks: string[] = []
  const warnings: string[] = []
  const writes: ReleaseMaterialCandidateWrite[] = []
  const promotedCases: VideoReleaseCaseId[] = []

  validateRunDir(input.runDir, failedChecks)

  const selections = MATERIAL_PROMOTIONS.map((selection) => ({
    ...selection,
    manifest:
      selection.sourceKind === 'local_video_srt' ? input.localSrtMaterialManifest : input.youtubeMaterialManifest,
  }))

  const candidatesBySelection = new Map<MaterialSelection, VideoReleaseSourceCandidate & Record<string, unknown>>()

  for (const selection of selections) {
    const label = selection.releaseSource
    const item = itemByIndex(selection.manifest, selection.itemIndex, failedChecks, label)
    if (!item) {
      continue
    }
    candidatesBySelection.set(
      selection,
      selection.sourceKind === 'local_video_srt'
        ? localCandidateFromItem({
            item,
            materialManifestPath: selection.manifest.path,
            selectedAt: input.selectedAt,
            failedChecks,
            label,
          })
        : youtubeCandidateFromItem({
            item,
            materialManifestPath: selection.manifest.path,
            selectedAt: input.selectedAt,
            failedChecks,
            label,
          }),
    )
  }

  for (const selection of selections) {
    const candidate = candidatesBySelection.get(selection)
    if (!candidate) {
      continue
    }
    for (const caseId of selection.caseIds) {
      const manifest = input.caseManifests[caseId]
      const releaseCase = releaseCaseDefinition(caseId)
      if (!releaseCase) {
        failedChecks.push(`case_${caseId}_unknown`)
        continue
      }
      if (!manifest) {
        failedChecks.push(`case_${caseId}_manifest_missing`)
        continue
      }
      if (manifest.case_id !== caseId) {
        failedChecks.push(`case_${caseId}_manifest_case_id_mismatch`)
      }
      if (manifest.source_kind !== releaseCase.sourceKind) {
        failedChecks.push(`case_${caseId}_manifest_source_kind_mismatch`)
      }
      if (manifest.mode !== releaseCase.mode) {
        failedChecks.push(`case_${caseId}_manifest_mode_mismatch`)
      }
      if (manifest.cache_state !== releaseCase.cacheState) {
        failedChecks.push(`case_${caseId}_manifest_cache_state_mismatch`)
      }
      if (manifest.source_candidate && !input.overwriteExisting) {
        failedChecks.push(`case_${caseId}_source_candidate_already_exists`)
      }
      if (releaseCase.source !== selection.releaseSource || releaseCase.sourceKind !== selection.sourceKind) {
        failedChecks.push(`case_${caseId}_promotion_mapping_mismatch`)
      }
      const updatedManifest = {
        ...manifest,
        status: manifest.status ?? 'not_started',
        source_candidate: candidate,
      }
      writes.push(writeForCase({ runDir: input.runDir, caseId, manifest: updatedManifest }))
      promotedCases.push(caseId)
    }
  }

  const uniqueFailedChecks = unique(failedChecks)
  return {
    ok: uniqueFailedChecks.length === 0,
    status: uniqueFailedChecks.length === 0 ? 'ready_to_write' : 'blocked',
    matrixPassCreated: false,
    failedChecks: uniqueFailedChecks,
    warnings,
    runDir: input.runDir,
    writes: uniqueFailedChecks.length === 0 ? writes : [],
    promotedCases: uniqueFailedChecks.length === 0 ? promotedCases : [],
    notes:
      'Promotes verified material rotation candidates into initialized case manifests only. It creates no APKG, Anki, timing/cache, audio, Computer Use, screenshot, or matrix-pass proof.',
  }
}
