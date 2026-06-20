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

type SupportedSourceKind = 'youtube_url' | 'local_video_srt' | 'public_video'
type FileBackedSourceKind = Extract<SupportedSourceKind, 'local_video_srt' | 'public_video'>

export type BuildReleaseObservedSourceProvenanceSnapshotInput = {
  caseId: VideoReleaseCaseId
  manifest: VideoReleaseCaseManifest
  project: unknown
}

export type BuildReleaseObservedSourceProvenanceSnapshotFromJsonInput = {
  caseId: VideoReleaseCaseId
  manifest: VideoReleaseCaseManifest
  rawObserved: unknown
}

export type BuildReleaseSourceProvenanceArtifactWritePlanInput = BuildReleaseObservedSourceProvenanceSnapshotInput & {
  runDir: string
}

export type BuildReleaseSourceProvenanceArtifactWritePlanFromJsonInput =
  BuildReleaseObservedSourceProvenanceSnapshotFromJsonInput & {
    runDir: string
  }

export type ReleaseObservedSourceProvenance = {
  schema_version: 1
  case_id: VideoReleaseCaseId
  source_kind: SupportedSourceKind
  source_fingerprint: string
  project_source_mode: string
  manifest_video_id?: string
  project_video_id?: string
  manifest_url?: string
  project_source_url?: string
  project_webpage_url?: string
  url_import_mode?: string
  download_mode?: string
  transcript_only?: boolean | null
  skip_video_slicing?: boolean | null
  manifest_video_path?: string
  manifest_subtitle_path?: string
  project_video_path?: string
  project_subtitle_path?: string
  project_source_fingerprint?: string
  project_video_fingerprint?: string
  project_subtitle_fingerprint?: string
  manifest_video_sha256?: string
  manifest_subtitle_sha256?: string
  manifest_video_bytes?: number
  manifest_subtitle_bytes?: number
}

export type ReleaseObservedSourceProvenanceSnapshot = {
  ok: boolean
  status: 'ready_for_artifact_guard' | 'blocked'
  matrixPassCreated: false
  failedChecks: string[]
  warnings: string[]
  sourceProvenance: ReleaseObservedSourceProvenance | null
  notes: string
}

export type ReleaseSourceProvenanceArtifactResult = {
  ok: boolean
  status: 'ready_for_write_plan' | 'blocked'
  matrixPassCreated: false
  failedChecks: string[]
  warnings: string[]
  artifactPath: string
  sourceProvenance: ReleaseObservedSourceProvenance | null
  notes: string
}

export type ReleaseSourceProvenanceArtifactWrite = {
  kind: 'source_provenance'
  relativePath: string
  absolutePath: string
  content: string
  writeMode: 'exclusive_create'
}

export type ReleaseSourceProvenanceArtifactWritePlan = {
  ok: boolean
  status: 'ready_to_write' | 'blocked'
  matrixPassCreated: false
  failedChecks: string[]
  warnings: string[]
  runDir: string
  caseDir: string
  artifactPath: string
  writes: ReleaseSourceProvenanceArtifactWrite[]
  notes: string
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function numberValue(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function positiveNumberValue(value: unknown): number | null {
  const numeric = numberValue(value)
  return numeric !== null && numeric > 0 ? numeric : null
}

function booleanValue(value: unknown): boolean | null {
  return typeof value === 'boolean' ? value : null
}

function firstValue(...values: unknown[]): unknown {
  return values.find((value) => typeof value !== 'undefined')
}

function firstString(...values: unknown[]): string {
  for (const value of values) {
    const text = stringValue(value)
    if (text) {
      return text
    }
  }
  return ''
}

function unique(values: string[]): string[] {
  return [...new Set(values)]
}

function isYoutubeFingerprint(value: string): boolean {
  return /^yt:[a-f0-9]{16}$/i.test(value)
}

function isLocalFileFingerprint(value: string): boolean {
  return /^file:[a-f0-9]{16}$/i.test(value)
}

function isSha256Hex(value: string): boolean {
  return /^[a-f0-9]{64}$/i.test(value)
}

function isPositiveInteger(value: unknown): boolean {
  return Number.isInteger(value) && Number(value) > 0
}

function isProjectFileFingerprint(value: string): boolean {
  return /^(?:file:)?[a-f0-9]{16,64}$/i.test(value)
}

function normalizedPath(value: string): string {
  return value.replace(/\\/g, '/').replace(/\/+/g, '/').replace(/\/$/, '').toLowerCase()
}

function pathMatchesAny(value: string, candidates: string[]): boolean {
  const normalized = normalizedPath(value)
  return candidates.some((candidate) => normalized === normalizedPath(candidate))
}

function sourceInfoRecord(project: Record<string, unknown>): Record<string, unknown> {
  return isRecord(project.source_info) ? project.source_info : {}
}

function sourceProvenanceArtifactPath(caseId: VideoReleaseCaseId): string {
  return `cases/${caseId}/source_provenance.json`
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
  return value.replace(/\\/g, '/').replace(/^\/+/, '').replace(/\/+/g, '/').replace(/\/$/, '')
}

function joinRunRelativePath(runDir: string, relativePath: string): string {
  const separator = runDir.includes('\\') ? '\\' : '/'
  const cleanRunDir = runDir.replace(/[\\/]+$/, '')
  return [cleanRunDir, ...normalizeRelativePath(relativePath).split('/')].join(separator)
}

function pathIsInsideDirectory(pathValue: string, directory: string): boolean {
  return normalizedPath(pathValue).startsWith(`${normalizedPath(directory)}/`)
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

function validateSourceProvenanceRelativePath({
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
    failedChecks.push('source_provenance_artifact_path_unsafe')
  }
  if (normalized !== sourceProvenanceArtifactPath(caseId)) {
    failedChecks.push('source_provenance_artifact_path_mismatch')
  }
}

function jsonContent(value: unknown): string {
  return `${JSON.stringify(value, null, 2)}\n`
}

export function extractYouTubeVideoId(value: string): string | null {
  const raw = value.trim()
  if (!raw) {
    return null
  }
  try {
    const url = new URL(raw)
    const hostname = url.hostname.toLowerCase().replace(/^www\./, '').replace(/^m\./, '')
    if (hostname === 'youtu.be') {
      return url.pathname.split('/').filter(Boolean)[0] ?? null
    }
    if (hostname === 'youtube.com' || hostname === 'youtube-nocookie.com') {
      const watchId = url.searchParams.get('v')
      if (watchId) {
        return watchId
      }
      const segments = url.pathname.split('/').filter(Boolean)
      const embeddedIndex = ['embed', 'shorts', 'live', 'v'].indexOf(segments[0] ?? '')
      return embeddedIndex >= 0 ? (segments[1] ?? null) : null
    }
  } catch {
    return null
  }
  return null
}

function releaseCaseFor(caseId: VideoReleaseCaseId) {
  return VIDEO_RELEASE_CASES.find((releaseCase) => releaseCase.id === caseId)
}

function supportedSourceKind(value: string): value is SupportedSourceKind {
  return value === 'youtube_url' || value === 'local_video_srt' || value === 'public_video'
}

function baseManifestChecks({
  caseId,
  manifest,
  failedChecks,
}: {
  caseId: VideoReleaseCaseId
  manifest: VideoReleaseCaseManifest
  failedChecks: string[]
}): SupportedSourceKind | null {
  const releaseCase = releaseCaseFor(caseId)
  if (!releaseCase) {
    failedChecks.push('source_provenance_release_case_unknown')
    return null
  }
  if (!supportedSourceKind(releaseCase.sourceKind)) {
    failedChecks.push('source_provenance_case_source_kind_unsupported')
    return null
  }
  if (manifest.case_id !== caseId) {
    failedChecks.push('source_provenance_manifest_case_id_mismatch')
  }
  if (manifest.source_kind !== releaseCase.sourceKind) {
    failedChecks.push('source_provenance_manifest_source_kind_mismatch')
  }
  return releaseCase.sourceKind
}

function candidateRecord(
  manifest: VideoReleaseCaseManifest,
  failedChecks: string[],
): VideoReleaseSourceCandidate | null {
  if (!manifest.source_candidate) {
    failedChecks.push('source_provenance_manifest_source_candidate_missing')
    return null
  }
  return manifest.source_candidate
}

function youtubeCandidateChecks(candidate: VideoReleaseSourceCandidate, failedChecks: string[]): string {
  const sourceFingerprint = stringValue(candidate.source_fingerprint).toLowerCase()
  const candidateUrl = stringValue(candidate.url)
  const manifestVideoId = stringValue(candidate.video_id)
  const candidateUrlVideoId = extractYouTubeVideoId(candidateUrl)
  if (!candidateUrlVideoId) {
    failedChecks.push('source_provenance_youtube_candidate_url_invalid')
  }
  if (!manifestVideoId || !candidateUrlVideoId || candidateUrlVideoId !== manifestVideoId) {
    failedChecks.push('source_provenance_youtube_candidate_video_id_mismatch')
  }
  if (!isYoutubeFingerprint(sourceFingerprint)) {
    failedChecks.push('source_provenance_youtube_candidate_fingerprint_invalid')
  }
  if (!stringValue(candidate.material_manifest)) {
    failedChecks.push('source_provenance_youtube_candidate_material_manifest_missing')
  }
  if (!stringValue(candidate.cache_probe_status)) {
    failedChecks.push('source_provenance_youtube_candidate_cache_probe_missing')
  }
  return sourceFingerprint
}

function localCandidateChecks(candidate: VideoReleaseSourceCandidate, failedChecks: string[]): string {
  const sourceFingerprint = stringValue(candidate.source_fingerprint).toLowerCase()
  const videoPath = firstString(candidate.video_path, candidate.downloaded_video_path)
  const subtitlePath = stringValue(candidate.subtitle_path)
  const videoSha256 = stringValue(candidate.video_sha256).toLowerCase()
  const subtitleSha256 = stringValue(candidate.subtitle_sha256).toLowerCase()
  if (!videoPath) {
    failedChecks.push('source_provenance_local_candidate_video_path_missing')
  }
  if (!subtitlePath) {
    failedChecks.push('source_provenance_local_candidate_subtitle_path_missing')
  }
  if (!isPositiveInteger(candidate.video_bytes)) {
    failedChecks.push('source_provenance_local_candidate_video_bytes_missing')
  }
  if (!isPositiveInteger(candidate.subtitle_bytes)) {
    failedChecks.push('source_provenance_local_candidate_subtitle_bytes_missing')
  }
  if (!isSha256Hex(videoSha256)) {
    failedChecks.push('source_provenance_local_candidate_video_sha256_missing')
  }
  if (!isSha256Hex(subtitleSha256)) {
    failedChecks.push('source_provenance_local_candidate_subtitle_sha256_missing')
  }
  if (!isLocalFileFingerprint(sourceFingerprint)) {
    failedChecks.push('source_provenance_local_candidate_fingerprint_invalid')
  } else if (isSha256Hex(videoSha256) && !videoSha256.startsWith(sourceFingerprint.slice('file:'.length))) {
    failedChecks.push('source_provenance_local_manifest_fingerprint_sha_mismatch')
  }
  if (!stringValue(candidate.material_manifest)) {
    failedChecks.push('source_provenance_local_candidate_material_manifest_missing')
  }
  if (!stringValue(candidate.cache_probe_status)) {
    failedChecks.push('source_provenance_local_candidate_cache_probe_missing')
  }
  return sourceFingerprint
}

function publicVideoCandidateChecks(candidate: VideoReleaseSourceCandidate, failedChecks: string[]): string {
  const sourceFingerprint = localCandidateChecks(candidate, failedChecks)
  const candidateUrl = stringValue(candidate.url)
  const manifestVideoId = stringValue(candidate.video_id)
  const candidateUrlVideoId = extractYouTubeVideoId(candidateUrl)

  if (!candidateUrl) {
    failedChecks.push('source_provenance_public_candidate_url_missing')
  } else if (!candidateUrlVideoId) {
    failedChecks.push('source_provenance_public_candidate_url_invalid')
  }
  if (!manifestVideoId) {
    failedChecks.push('source_provenance_public_candidate_video_id_missing')
  } else if (candidateUrlVideoId && candidateUrlVideoId !== manifestVideoId) {
    failedChecks.push('source_provenance_public_candidate_video_id_mismatch')
  }

  return sourceFingerprint
}

function projectRecord(project: unknown, failedChecks: string[]): Record<string, unknown> | null {
  if (!isRecord(project)) {
    failedChecks.push('source_provenance_project_missing')
    return null
  }
  return project
}

function projectSourceModeChecks({
  project,
  expectedMode,
  failedChecks,
}: {
  project: Record<string, unknown>
  expectedMode: 'url' | 'local'
  failedChecks: string[]
}): string {
  const sourceMode = stringValue(project.source_mode)
  if (sourceMode === 'document') {
    failedChecks.push('source_provenance_project_document_source_mode')
  }
  if (sourceMode !== expectedMode) {
    failedChecks.push('source_provenance_project_source_mode_mismatch')
  }
  return sourceMode
}

function youtubeProjectProvenance({
  caseId,
  candidate,
  sourceFingerprint,
  project,
  failedChecks,
}: {
  caseId: VideoReleaseCaseId
  candidate: VideoReleaseSourceCandidate
  sourceFingerprint: string
  project: Record<string, unknown>
  failedChecks: string[]
}): ReleaseObservedSourceProvenance {
  const sourceMode = projectSourceModeChecks({ project, expectedMode: 'url', failedChecks })
  const sourceInfo = sourceInfoRecord(project)
  if (!isRecord(project.source_info)) {
    failedChecks.push('source_provenance_project_source_info_missing')
  }

  const manifestUrl = stringValue(candidate.url)
  const manifestVideoId = stringValue(candidate.video_id)
  const projectSourceUrl = firstString(project.source_url, sourceInfo.url, sourceInfo.webpage_url)
  const projectSourceVideoId = extractYouTubeVideoId(projectSourceUrl)
  const webpageUrl = firstString(sourceInfo.webpage_url, sourceInfo.url)
  const webpageVideoId = webpageUrl ? extractYouTubeVideoId(webpageUrl) : null
  const urlImportMode = stringValue(project.url_import_mode)
  const downloadMode = stringValue(sourceInfo.download_mode)
  const transcriptOnly = booleanValue(sourceInfo.transcript_only)
  const skipVideoSlicing = booleanValue(firstValue(sourceInfo.skip_video_slicing, project.skip_video_slicing))

  if (!projectSourceUrl) {
    failedChecks.push('source_provenance_youtube_project_source_url_missing')
  }
  if (!projectSourceVideoId || projectSourceVideoId !== manifestVideoId) {
    failedChecks.push('source_provenance_youtube_project_video_id_mismatch')
  }
  if (webpageUrl && (!webpageVideoId || webpageVideoId !== manifestVideoId)) {
    failedChecks.push('source_provenance_youtube_project_webpage_url_video_id_mismatch')
  }
  if (transcriptOnly === true) {
    failedChecks.push('source_provenance_youtube_transcript_only')
  }
  if (skipVideoSlicing === true) {
    failedChecks.push('source_provenance_youtube_skip_video_slicing')
  }
  if (urlImportMode === 'subtitles' || downloadMode === 'subtitles') {
    failedChecks.push('source_provenance_youtube_subtitle_only_import_mode')
  }

  return {
    schema_version: 1,
    case_id: caseId,
    source_kind: 'youtube_url',
    source_fingerprint: sourceFingerprint,
    project_source_mode: sourceMode,
    manifest_video_id: manifestVideoId,
    project_video_id: projectSourceVideoId ?? undefined,
    manifest_url: manifestUrl,
    project_source_url: projectSourceUrl,
    project_webpage_url: webpageUrl,
    url_import_mode: urlImportMode || undefined,
    download_mode: downloadMode || undefined,
    transcript_only: transcriptOnly,
    skip_video_slicing: skipVideoSlicing,
    project_source_fingerprint: stringValue(project.source_fingerprint) || undefined,
  }
}

function localProjectProvenance({
  caseId,
  sourceKind,
  candidate,
  sourceFingerprint,
  project,
  failedChecks,
}: {
  caseId: VideoReleaseCaseId
  sourceKind: FileBackedSourceKind
  candidate: VideoReleaseSourceCandidate
  sourceFingerprint: string
  project: Record<string, unknown>
  failedChecks: string[]
}): ReleaseObservedSourceProvenance {
  const sourceMode = projectSourceModeChecks({ project, expectedMode: 'local', failedChecks })
  const sourceInfo = sourceInfoRecord(project)
  if (!isRecord(project.source_info)) {
    failedChecks.push('source_provenance_project_source_info_missing')
  }

  const candidateVideoPaths = [candidate.video_path, candidate.downloaded_video_path].map(stringValue).filter(Boolean)
  const candidateSubtitlePath = stringValue(candidate.subtitle_path)
  const projectVideoPath = firstString(project.video_path, sourceInfo.video_path)
  const projectSubtitlePath = firstString(project.subtitle_path, sourceInfo.subtitle_path)
  const topLevelVideoPath = stringValue(project.video_path)
  const infoVideoPath = stringValue(sourceInfo.video_path)
  const topLevelSubtitlePath = stringValue(project.subtitle_path)
  const infoSubtitlePath = stringValue(sourceInfo.subtitle_path)
  const videoFingerprint = stringValue(sourceInfo.video_fingerprint)
  const subtitleFingerprint = stringValue(sourceInfo.subtitle_fingerprint)

  if (!projectVideoPath) {
    failedChecks.push('source_provenance_local_project_video_path_missing')
  } else if (!pathMatchesAny(projectVideoPath, candidateVideoPaths)) {
    failedChecks.push('source_provenance_local_video_path_mismatch')
  }
  if (topLevelVideoPath && !pathMatchesAny(topLevelVideoPath, candidateVideoPaths)) {
    failedChecks.push('source_provenance_local_project_video_path_mismatch')
  }
  if (infoVideoPath && !pathMatchesAny(infoVideoPath, candidateVideoPaths)) {
    failedChecks.push('source_provenance_local_source_info_video_path_mismatch')
  }
  if (!projectSubtitlePath) {
    failedChecks.push('source_provenance_local_project_subtitle_path_missing')
  } else if (!pathMatchesAny(projectSubtitlePath, [candidateSubtitlePath])) {
    failedChecks.push('source_provenance_local_subtitle_path_mismatch')
  }
  if (topLevelSubtitlePath && !pathMatchesAny(topLevelSubtitlePath, [candidateSubtitlePath])) {
    failedChecks.push('source_provenance_local_project_subtitle_path_mismatch')
  }
  if (infoSubtitlePath && !pathMatchesAny(infoSubtitlePath, [candidateSubtitlePath])) {
    failedChecks.push('source_provenance_local_source_info_subtitle_path_mismatch')
  }
  if (!isProjectFileFingerprint(videoFingerprint)) {
    failedChecks.push('source_provenance_local_video_fingerprint_missing')
  }
  if (!isProjectFileFingerprint(subtitleFingerprint)) {
    failedChecks.push('source_provenance_local_subtitle_fingerprint_missing')
  }

  return {
    schema_version: 1,
    case_id: caseId,
    source_kind: sourceKind,
    source_fingerprint: sourceFingerprint,
    project_source_mode: sourceMode,
    manifest_video_id: sourceKind === 'public_video' ? stringValue(candidate.video_id) || undefined : undefined,
    manifest_url: sourceKind === 'public_video' ? stringValue(candidate.url) || undefined : undefined,
    manifest_video_path: firstString(candidate.video_path, candidate.downloaded_video_path),
    manifest_subtitle_path: candidateSubtitlePath,
    project_video_path: projectVideoPath,
    project_subtitle_path: projectSubtitlePath,
    project_source_fingerprint: stringValue(project.source_fingerprint) || undefined,
    project_video_fingerprint: videoFingerprint,
    project_subtitle_fingerprint: subtitleFingerprint,
    manifest_video_sha256: stringValue(candidate.video_sha256).toLowerCase(),
    manifest_subtitle_sha256: stringValue(candidate.subtitle_sha256).toLowerCase(),
    manifest_video_bytes: positiveNumberValue(candidate.video_bytes) ?? undefined,
    manifest_subtitle_bytes: positiveNumberValue(candidate.subtitle_bytes) ?? undefined,
  }
}

export function buildReleaseObservedSourceProvenanceSnapshot({
  caseId,
  manifest,
  project,
}: BuildReleaseObservedSourceProvenanceSnapshotInput): ReleaseObservedSourceProvenanceSnapshot {
  const failedChecks: string[] = []
  const sourceKind = baseManifestChecks({ caseId, manifest, failedChecks })
  const candidate = candidateRecord(manifest, failedChecks)
  const observedProject = projectRecord(project, failedChecks)
  let sourceProvenance: ReleaseObservedSourceProvenance | null = null

  if (sourceKind && candidate && observedProject) {
    if (sourceKind === 'youtube_url') {
      const sourceFingerprint = youtubeCandidateChecks(candidate, failedChecks)
      sourceProvenance = youtubeProjectProvenance({
        caseId,
        candidate,
        sourceFingerprint,
        project: observedProject,
        failedChecks,
      })
    } else if (sourceKind === 'local_video_srt') {
      const sourceFingerprint = localCandidateChecks(candidate, failedChecks)
      sourceProvenance = localProjectProvenance({
        caseId,
        sourceKind,
        candidate,
        sourceFingerprint,
        project: observedProject,
        failedChecks,
      })
    } else {
      const sourceFingerprint = publicVideoCandidateChecks(candidate, failedChecks)
      sourceProvenance = localProjectProvenance({
        caseId,
        sourceKind,
        candidate,
        sourceFingerprint,
        project: observedProject,
        failedChecks,
      })
    }
  }

  const uniqueFailedChecks = unique(failedChecks)
  return {
    ok: uniqueFailedChecks.length === 0,
    status: uniqueFailedChecks.length === 0 ? 'ready_for_artifact_guard' : 'blocked',
    matrixPassCreated: false,
    failedChecks: uniqueFailedChecks,
    warnings: [],
    sourceProvenance: uniqueFailedChecks.length === 0 ? sourceProvenance : null,
    notes:
      'Pure observed source-provenance guard only. It compares raw project source identity with the release case manifest before future artifact writers trust the run, but it does not write files, update manifests, create APKG/Anki/Computer Use evidence, or claim a matrix pass.',
  }
}

function looksLikeWriterHandoffEnvelope(value: Record<string, unknown>): boolean {
  return (
    value.schema_kind === 'release_timing_cache_writer_handoff_audit' ||
    value.artifact_kind === 'timing_cache_writer_handoff' ||
    value.handoff_kind === 'timing_cache_writer_dry_run_handoff' ||
    value.evidence_role === 'non_final_writer_handoff' ||
    value.matrix_eligibility === 'never' ||
    Object.hasOwn(value, 'raw_observed_json')
  )
}

function handoffEnvelopeFailedChecks(value: Record<string, unknown>, caseId: VideoReleaseCaseId): string[] {
  const failedChecks: string[] = []
  if (value.matrix_pass_created !== false) {
    failedChecks.push('source_provenance_handoff_matrix_pass_created_not_false')
  }
  if (value.matrix_pass_verified !== false && Object.hasOwn(value, 'matrix_pass_verified')) {
    failedChecks.push('source_provenance_handoff_matrix_pass_verified_not_false')
  }
  if (value.release_case_evidence !== false && Object.hasOwn(value, 'release_case_evidence')) {
    failedChecks.push('source_provenance_handoff_release_case_evidence_not_false')
  }
  if (value.matrix_eligibility !== 'never' && Object.hasOwn(value, 'matrix_eligibility')) {
    failedChecks.push('source_provenance_handoff_matrix_eligibility_not_never')
  }
  const envelopeCaseId = firstString(value.caseId, value.case_id)
  if (envelopeCaseId && envelopeCaseId !== caseId) {
    failedChecks.push('source_provenance_handoff_case_id_mismatch')
  }
  if (!isRecord(value.raw_observed_json)) {
    failedChecks.push('source_provenance_handoff_raw_observed_json_missing')
  }
  return failedChecks
}

export function buildReleaseObservedSourceProvenanceSnapshotFromJson({
  caseId,
  manifest,
  rawObserved,
}: BuildReleaseObservedSourceProvenanceSnapshotFromJsonInput): ReleaseObservedSourceProvenanceSnapshot {
  const rootObserved = isRecord(rawObserved) ? rawObserved : {}
  const isHandoffEnvelope = looksLikeWriterHandoffEnvelope(rootObserved)
  const handoffFailedChecks = isHandoffEnvelope ? handoffEnvelopeFailedChecks(rootObserved, caseId) : []
  const observed =
    isHandoffEnvelope && isRecord(rootObserved.raw_observed_json) ? rootObserved.raw_observed_json : rootObserved
  const observedCaseId = firstString(observed.caseId, observed.case_id)
  const snapshot = buildReleaseObservedSourceProvenanceSnapshot({
    caseId,
    manifest,
    project: observed.project,
  })
  const failedChecks = unique([
    ...snapshot.failedChecks,
    ...(observedCaseId && observedCaseId !== caseId ? ['source_provenance_observed_case_id_mismatch'] : []),
    ...handoffFailedChecks,
  ])
  if (failedChecks.length === snapshot.failedChecks.length) {
    return snapshot
  }
  return {
    ...snapshot,
    ok: false,
    status: 'blocked',
    failedChecks,
    sourceProvenance: null,
  }
}

export function buildReleaseSourceProvenanceArtifact(
  input: BuildReleaseObservedSourceProvenanceSnapshotInput,
): ReleaseSourceProvenanceArtifactResult {
  const snapshot = buildReleaseObservedSourceProvenanceSnapshot(input)
  return {
    ok: snapshot.ok,
    status: snapshot.ok ? 'ready_for_write_plan' : 'blocked',
    matrixPassCreated: false,
    failedChecks: snapshot.failedChecks,
    warnings: snapshot.warnings,
    artifactPath: sourceProvenanceArtifactPath(input.caseId),
    sourceProvenance: snapshot.ok ? snapshot.sourceProvenance : null,
    notes:
      'Pure source provenance artifact only. It can prepare future source_provenance.json content, but it does not write files, update manifests, create APKG/Anki/Computer Use evidence, or claim a matrix pass.',
  }
}

export function buildReleaseSourceProvenanceArtifactFromJson(
  input: BuildReleaseObservedSourceProvenanceSnapshotFromJsonInput,
): ReleaseSourceProvenanceArtifactResult {
  const snapshot = buildReleaseObservedSourceProvenanceSnapshotFromJson(input)
  return {
    ok: snapshot.ok,
    status: snapshot.ok ? 'ready_for_write_plan' : 'blocked',
    matrixPassCreated: false,
    failedChecks: snapshot.failedChecks,
    warnings: snapshot.warnings,
    artifactPath: sourceProvenanceArtifactPath(input.caseId),
    sourceProvenance: snapshot.ok ? snapshot.sourceProvenance : null,
    notes:
      'Pure source provenance artifact only. It can prepare future source_provenance.json content from raw observed JSON, but it does not write files, update manifests, create APKG/Anki/Computer Use evidence, or claim a matrix pass.',
  }
}

export function buildReleaseSourceProvenanceArtifactWritePlan(
  input: BuildReleaseSourceProvenanceArtifactWritePlanInput,
): ReleaseSourceProvenanceArtifactWritePlan {
  const runDir = String(input.runDir ?? '').trim()
  const failedChecks: string[] = []
  validateRunDir(runDir, failedChecks)

  const artifact = buildReleaseSourceProvenanceArtifact(input)
  failedChecks.push(...artifact.failedChecks)
  validateSourceProvenanceRelativePath({
    relativePath: artifact.artifactPath,
    caseId: input.caseId,
    failedChecks,
  })

  const caseDir = runDir ? joinRunRelativePath(runDir, `cases/${input.caseId}`) : ''
  const sourceProvenancePath = runDir ? joinRunRelativePath(runDir, artifact.artifactPath) : ''
  if (caseDir && sourceProvenancePath && !pathIsInsideDirectory(sourceProvenancePath, caseDir)) {
    failedChecks.push('source_provenance_absolute_path_outside_case_dir')
  }

  const uniqueFailedChecks = unique(failedChecks)
  const writes: ReleaseSourceProvenanceArtifactWrite[] =
    uniqueFailedChecks.length === 0 && artifact.sourceProvenance
      ? [
          {
            kind: 'source_provenance',
            relativePath: artifact.artifactPath,
            absolutePath: sourceProvenancePath,
            content: jsonContent(artifact.sourceProvenance),
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
    artifactPath: artifact.artifactPath,
    writes,
    notes:
      'Pure write plan only. A caller may persist source_provenance.json with exclusive-create semantics, but this plan does not write files, update manifests, create APKG/Anki/Computer Use evidence, or claim a matrix pass.',
  }
}

export function buildReleaseSourceProvenanceArtifactWritePlanFromJson(
  input: BuildReleaseSourceProvenanceArtifactWritePlanFromJsonInput,
): ReleaseSourceProvenanceArtifactWritePlan {
  const runDir = String(input.runDir ?? '').trim()
  const failedChecks: string[] = []
  validateRunDir(runDir, failedChecks)

  const artifact = buildReleaseSourceProvenanceArtifactFromJson(input)
  failedChecks.push(...artifact.failedChecks)
  validateSourceProvenanceRelativePath({
    relativePath: artifact.artifactPath,
    caseId: input.caseId,
    failedChecks,
  })

  const caseDir = runDir ? joinRunRelativePath(runDir, `cases/${input.caseId}`) : ''
  const sourceProvenancePath = runDir ? joinRunRelativePath(runDir, artifact.artifactPath) : ''
  if (caseDir && sourceProvenancePath && !pathIsInsideDirectory(sourceProvenancePath, caseDir)) {
    failedChecks.push('source_provenance_absolute_path_outside_case_dir')
  }

  const uniqueFailedChecks = unique(failedChecks)
  const writes: ReleaseSourceProvenanceArtifactWrite[] =
    uniqueFailedChecks.length === 0 && artifact.sourceProvenance
      ? [
          {
            kind: 'source_provenance',
            relativePath: artifact.artifactPath,
            absolutePath: sourceProvenancePath,
            content: jsonContent(artifact.sourceProvenance),
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
    artifactPath: artifact.artifactPath,
    writes,
    notes:
      'Pure write plan only. A caller may persist source_provenance.json from raw observed JSON with exclusive-create semantics, but this plan does not write files, update manifests, create APKG/Anki/Computer Use evidence, or claim a matrix pass.',
  }
}
