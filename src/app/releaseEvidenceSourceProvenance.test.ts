import { describe, expect, it } from 'vitest'

import {
  buildVideoReleaseRunInitializerPlan,
  type VideoReleaseCaseId,
  type VideoReleaseCaseManifest,
} from '../domain/releaseEvidenceLayout'
import {
  buildReleaseObservedSourceProvenanceSnapshot,
  buildReleaseObservedSourceProvenanceSnapshotFromJson,
  buildReleaseSourceProvenanceArtifactFromJson,
  buildReleaseSourceProvenanceArtifactWritePlan,
  buildReleaseSourceProvenanceArtifactWritePlanFromJson,
  extractYouTubeVideoId,
} from './releaseEvidenceSourceProvenance'

const YOUTUBE_URL = 'https://www.youtube.com/watch?v=m7IlyBEyi3c'
const YOUTUBE_SOURCE_FINGERPRINT = 'yt:779a15b6499710bd'
const LOCAL_VIDEO_PATH =
  'E:\\ANKI\\test_runs\\video_material_rotation_20260619_132237_slice109_local_srt_youtube_a_download\\url_01\\source.mp4'
const LOCAL_SUBTITLE_PATH =
  'E:\\ANKI\\test_runs\\video_material_rotation_20260619_132237_slice109_local_srt_youtube_a_download\\url_01\\source.en-GB.srt'
const LOCAL_VIDEO_SHA = '968c50e3449f71a3f65bc945a7205d5cca4699b312fa28560a7adadaaec5c9d6'
const LOCAL_SUBTITLE_SHA = '0ba2394c6d6bd9485a845d4f5b91209d06c9b04e44bab17b37803855d92314a4'
const PUBLIC_VIDEO_URL = 'https://www.youtube.com/watch?v=6PJnEdbq8qc'
const PUBLIC_VIDEO_PATH =
  'E:\\ANKI\\test_runs\\video_material_rotation_20260620_1832_stress_public_candidates\\url_01\\source.mp4'
const PUBLIC_SUBTITLE_PATH =
  'E:\\ANKI\\test_runs\\video_material_rotation_20260620_1832_stress_public_candidates\\url_01\\source.en.srt'
const PUBLIC_VIDEO_SHA = '20ca15c1be2e2e65218b525daaf17afe41d291057e072e899d65d8376ab08dc1'
const PUBLIC_SUBTITLE_SHA = '0130f2d33fc5510cce2e3b0d2153bd2d51f8d64b0dd0b67534335ecf47f2d1ec'

function manifestFor(caseId: VideoReleaseCaseId): VideoReleaseCaseManifest {
  const plan = buildVideoReleaseRunInitializerPlan('20260619_045000')
  return JSON.parse(
    plan.seedFiles.find((file) => file.relativePath === `cases/${caseId}/case_manifest.json`)?.content ?? '{}',
  )
}

function youtubeManifest(): VideoReleaseCaseManifest {
  const manifest = manifestFor('youtube_a_full1_cold')
  manifest.source_candidate = {
    url: YOUTUBE_URL,
    video_id: 'm7IlyBEyi3c',
    source_fingerprint: YOUTUBE_SOURCE_FINGERPRINT,
    material_manifest:
      'E:\\ANKI\\test_runs\\video_material_rotation_20260619_124902_slice104_verified_youtube_ab\\material_manifest.json',
    cache_probe_status: 'no_existing_url_cache_found',
  }
  return manifest
}

function localManifest(): VideoReleaseCaseManifest {
  const manifest = manifestFor('local_srt_full1_cold')
  manifest.source_candidate = {
    video_path: LOCAL_VIDEO_PATH,
    downloaded_video_path: LOCAL_VIDEO_PATH,
    subtitle_path: LOCAL_SUBTITLE_PATH,
    video_bytes: 10706306,
    subtitle_bytes: 9440,
    video_sha256: LOCAL_VIDEO_SHA,
    subtitle_sha256: LOCAL_SUBTITLE_SHA,
    source_fingerprint: 'file:968c50e3449f71a3',
    material_manifest:
      'E:\\ANKI\\test_runs\\video_material_rotation_20260619_132237_slice109_local_srt_youtube_a_download\\material_manifest.json',
    cache_probe_status: 'no_existing_url_cache_found',
  }
  return manifest
}

function publicVideoManifest(): VideoReleaseCaseManifest {
  const manifest = manifestFor('stress_100_plus_one_click')
  manifest.source_candidate = {
    url: PUBLIC_VIDEO_URL,
    video_id: '6PJnEdbq8qc',
    video_path: PUBLIC_VIDEO_PATH,
    downloaded_video_path: PUBLIC_VIDEO_PATH,
    subtitle_path: PUBLIC_SUBTITLE_PATH,
    video_bytes: 75968066,
    subtitle_bytes: 44005,
    video_sha256: PUBLIC_VIDEO_SHA,
    subtitle_sha256: PUBLIC_SUBTITLE_SHA,
    source_fingerprint: 'file:20ca15c1be2e2e65',
    material_manifest:
      'E:\\ANKI\\test_runs\\video_material_rotation_20260620_1832_stress_public_candidates\\material_manifest.json',
    cache_probe_status: 'no_existing_url_cache_found',
  }
  return manifest
}

function youtubeProject(overrides: Record<string, unknown> = {}) {
  return {
    id: 'project-youtube-a',
    source_mode: 'url',
    source_url: YOUTUBE_URL,
    url_import_mode: 'video',
    source_fingerprint: 'worker-cache-key-not-the-release-fingerprint',
    video_path:
      'E:\\ANKI\\projects\\url_cache\\url_1\\source.mp4',
    subtitle_path:
      'E:\\ANKI\\projects\\url_cache\\url_1\\source.en.srt',
    source_info: {
      url: YOUTUBE_URL,
      webpage_url: 'https://youtu.be/m7IlyBEyi3c',
      download_mode: 'video',
      transcript_only: false,
      skip_video_slicing: false,
    },
    ...overrides,
  }
}

function localProject(overrides: Record<string, unknown> = {}) {
  return {
    id: 'project-local-srt',
    source_mode: 'local',
    source_fingerprint: 'worker-cache-key-not-the-release-file-fingerprint',
    video_path: LOCAL_VIDEO_PATH,
    subtitle_path: LOCAL_SUBTITLE_PATH,
    source_info: {
      video_path: LOCAL_VIDEO_PATH.replace(/\\/g, '/'),
      subtitle_path: LOCAL_SUBTITLE_PATH.replace(/\\/g, '/'),
      subtitle_source: 'manual',
      video_fingerprint: 'abc123def456abc123def456',
      subtitle_fingerprint: 'def456abc123def456abc123',
    },
    ...overrides,
  }
}

function publicVideoProject(overrides: Record<string, unknown> = {}) {
  return {
    id: 'project-public-video',
    source_mode: 'local',
    source_fingerprint: 'worker-cache-key-not-the-release-public-file-fingerprint',
    video_path: PUBLIC_VIDEO_PATH,
    subtitle_path: PUBLIC_SUBTITLE_PATH,
    source_info: {
      video_path: PUBLIC_VIDEO_PATH,
      subtitle_path: PUBLIC_SUBTITLE_PATH,
      subtitle_source: 'manual',
      video_fingerprint: PUBLIC_VIDEO_SHA,
      subtitle_fingerprint: PUBLIC_SUBTITLE_SHA,
    },
    ...overrides,
  }
}

describe('releaseEvidenceSourceProvenance', () => {
  it('extracts YouTube ids from supported URL forms used by release materials and worker metadata', () => {
    expect(extractYouTubeVideoId('https://www.youtube.com/watch?v=m7IlyBEyi3c&t=3')).toBe('m7IlyBEyi3c')
    expect(extractYouTubeVideoId('https://youtu.be/m7IlyBEyi3c?si=abc')).toBe('m7IlyBEyi3c')
    expect(extractYouTubeVideoId('https://www.youtube.com/embed/m7IlyBEyi3c')).toBe('m7IlyBEyi3c')
    expect(extractYouTubeVideoId('https://www.youtube.com/shorts/m7IlyBEyi3c')).toBe('m7IlyBEyi3c')
  })

  it('builds a YouTube observed source provenance snapshot without requiring Project.source_fingerprint equality', () => {
    const snapshot = buildReleaseObservedSourceProvenanceSnapshot({
      caseId: 'youtube_a_full1_cold',
      manifest: youtubeManifest(),
      project: youtubeProject(),
    })

    expect(snapshot.ok).toBe(true)
    expect(snapshot.status).toBe('ready_for_artifact_guard')
    expect(snapshot.matrixPassCreated).toBe(false)
    expect(snapshot.failedChecks).toEqual([])
    expect(snapshot.sourceProvenance).toMatchObject({
      schema_version: 1,
      case_id: 'youtube_a_full1_cold',
      source_kind: 'youtube_url',
      source_fingerprint: YOUTUBE_SOURCE_FINGERPRINT,
      project_source_mode: 'url',
      manifest_video_id: 'm7IlyBEyi3c',
      project_video_id: 'm7IlyBEyi3c',
      project_source_fingerprint: 'worker-cache-key-not-the-release-fingerprint',
    })
  })

  it('accepts cached URL projects that preserve the URL only through source_info', () => {
    const snapshot = buildReleaseObservedSourceProvenanceSnapshot({
      caseId: 'youtube_a_full1_cold',
      manifest: youtubeManifest(),
      project: youtubeProject({
        source_url: '',
        source_info: {
          url: 'https://youtu.be/m7IlyBEyi3c',
          download_mode: 'video',
          transcript_only: false,
          skip_video_slicing: false,
        },
      }),
    })

    expect(snapshot.ok).toBe(true)
    expect(snapshot.sourceProvenance?.project_source_url).toBe('https://youtu.be/m7IlyBEyi3c')
  })

  it('blocks stale YouTube projects, subtitle-only imports, and video-slicing skips', () => {
    const snapshot = buildReleaseObservedSourceProvenanceSnapshot({
      caseId: 'youtube_a_full1_cold',
      manifest: youtubeManifest(),
      project: youtubeProject({
        source_url: 'https://www.youtube.com/watch?v=vOuhs1mA0xo',
        url_import_mode: 'subtitles',
        source_info: {
          webpage_url: 'https://www.youtube.com/watch?v=vOuhs1mA0xo',
          download_mode: 'subtitles',
          transcript_only: true,
          skip_video_slicing: true,
        },
      }),
    })

    expect(snapshot.ok).toBe(false)
    expect(snapshot.status).toBe('blocked')
    expect(snapshot.sourceProvenance).toBeNull()
    expect(snapshot.failedChecks).toEqual(
      expect.arrayContaining([
        'source_provenance_youtube_project_video_id_mismatch',
        'source_provenance_youtube_project_webpage_url_video_id_mismatch',
        'source_provenance_youtube_transcript_only',
        'source_provenance_youtube_skip_video_slicing',
        'source_provenance_youtube_subtitle_only_import_mode',
      ]),
    )
  })

  it('builds a local SRT observed source provenance snapshot from project paths and worker fingerprints', () => {
    const snapshot = buildReleaseObservedSourceProvenanceSnapshot({
      caseId: 'local_srt_full1_cold',
      manifest: localManifest(),
      project: localProject(),
    })

    expect(snapshot.ok).toBe(true)
    expect(snapshot.matrixPassCreated).toBe(false)
    expect(snapshot.sourceProvenance).toMatchObject({
      schema_version: 1,
      case_id: 'local_srt_full1_cold',
      source_kind: 'local_video_srt',
      source_fingerprint: 'file:968c50e3449f71a3',
      project_source_mode: 'local',
      manifest_video_sha256: LOCAL_VIDEO_SHA,
      manifest_subtitle_sha256: LOCAL_SUBTITLE_SHA,
      project_video_fingerprint: 'abc123def456abc123def456',
      project_subtitle_fingerprint: 'def456abc123def456abc123',
    })
  })

  it('builds public video provenance from a downloaded public mp4/srt project and manifest URL metadata', () => {
    const snapshot = buildReleaseObservedSourceProvenanceSnapshot({
      caseId: 'stress_100_plus_one_click',
      manifest: publicVideoManifest(),
      project: publicVideoProject(),
    })

    expect(snapshot.ok).toBe(true)
    expect(snapshot.matrixPassCreated).toBe(false)
    expect(snapshot.failedChecks).toEqual([])
    expect(snapshot.sourceProvenance).toMatchObject({
      schema_version: 1,
      case_id: 'stress_100_plus_one_click',
      source_kind: 'public_video',
      source_fingerprint: 'file:20ca15c1be2e2e65',
      project_source_mode: 'local',
      manifest_video_id: '6PJnEdbq8qc',
      manifest_url: PUBLIC_VIDEO_URL,
      manifest_video_path: PUBLIC_VIDEO_PATH,
      manifest_subtitle_path: PUBLIC_SUBTITLE_PATH,
      project_video_path: PUBLIC_VIDEO_PATH,
      project_subtitle_path: PUBLIC_SUBTITLE_PATH,
      manifest_video_sha256: PUBLIC_VIDEO_SHA,
      manifest_subtitle_sha256: PUBLIC_SUBTITLE_SHA,
      project_video_fingerprint: PUBLIC_VIDEO_SHA,
      project_subtitle_fingerprint: PUBLIC_SUBTITLE_SHA,
    })
  })

  it('blocks local SRT projects when observed paths or worker fingerprints are missing or stale', () => {
    const snapshot = buildReleaseObservedSourceProvenanceSnapshot({
      caseId: 'local_srt_full1_cold',
      manifest: localManifest(),
      project: localProject({
        video_path: 'E:\\ANKI\\other\\wrong.mp4',
        source_info: {
          video_path: LOCAL_VIDEO_PATH,
          subtitle_path: 'E:\\ANKI\\other\\wrong.srt',
          video_fingerprint: '',
          subtitle_fingerprint: '',
        },
      }),
    })

    expect(snapshot.ok).toBe(false)
    expect(snapshot.sourceProvenance).toBeNull()
    expect(snapshot.failedChecks).toEqual(
      expect.arrayContaining([
        'source_provenance_local_project_video_path_mismatch',
        'source_provenance_local_source_info_subtitle_path_mismatch',
        'source_provenance_local_video_fingerprint_missing',
        'source_provenance_local_subtitle_fingerprint_missing',
      ]),
    )
  })

  it('blocks document or cross-kind observed projects before any artifact writer can trust them', () => {
    const snapshot = buildReleaseObservedSourceProvenanceSnapshot({
      caseId: 'youtube_a_full1_cold',
      manifest: youtubeManifest(),
      project: {
        source_mode: 'document',
        source_info: { document_path: 'E:\\ANKI\\docs\\source.pdf' },
      },
    })

    expect(snapshot.ok).toBe(false)
    expect(snapshot.failedChecks).toEqual(
      expect.arrayContaining([
        'source_provenance_project_document_source_mode',
        'source_provenance_project_source_mode_mismatch',
        'source_provenance_youtube_project_source_url_missing',
      ]),
    )
    expect(snapshot.sourceProvenance).toBeNull()
  })

  it('blocks missing manifest candidates or missing raw project data without producing provenance', () => {
    const manifest = youtubeManifest()
    manifest.source_candidate = undefined

    const snapshot = buildReleaseObservedSourceProvenanceSnapshot({
      caseId: 'youtube_a_full1_cold',
      manifest,
      project: null,
    })

    expect(snapshot.ok).toBe(false)
    expect(snapshot.failedChecks).toEqual(
      expect.arrayContaining([
        'source_provenance_manifest_source_candidate_missing',
        'source_provenance_project_missing',
      ]),
    )
    expect(snapshot.sourceProvenance).toBeNull()
  })

  it('maps snake_case observed JSON through the same source provenance guard', () => {
    const snapshot = buildReleaseObservedSourceProvenanceSnapshotFromJson({
      caseId: 'youtube_a_full1_cold',
      manifest: youtubeManifest(),
      rawObserved: {
        case_id: 'youtube_a_full1_cold',
        project: youtubeProject(),
      },
    })

    expect(snapshot.ok).toBe(true)
    expect(snapshot.sourceProvenance?.project_video_id).toBe('m7IlyBEyi3c')
  })

  it('unwraps safe non-final writer handoff audits but still rejects unsafe envelopes', () => {
    const safe = buildReleaseObservedSourceProvenanceSnapshotFromJson({
      caseId: 'youtube_a_full1_cold',
      manifest: youtubeManifest(),
      rawObserved: {
        schema_kind: 'release_timing_cache_writer_handoff_audit',
        evidence_role: 'non_final_writer_handoff',
        matrix_eligibility: 'never',
        release_case_evidence: false,
        matrix_pass_created: false,
        matrix_pass_verified: false,
        raw_observed_json: {
          case_id: 'youtube_a_full1_cold',
          project: youtubeProject(),
        },
      },
    })
    const unsafe = buildReleaseObservedSourceProvenanceSnapshotFromJson({
      caseId: 'youtube_a_full1_cold',
      manifest: youtubeManifest(),
      rawObserved: {
        schema_kind: 'release_timing_cache_writer_handoff_audit',
        evidence_role: 'non_final_writer_handoff',
        matrix_eligibility: 'maybe',
        release_case_evidence: true,
        matrix_pass_created: true,
        matrix_pass_verified: true,
        case_id: 'youtube_a_full1_cold',
        raw_observed_json: {
          case_id: 'youtube_a_full1_cold',
          project: youtubeProject(),
        },
      },
    })

    expect(safe.ok).toBe(true)
    expect(safe.matrixPassCreated).toBe(false)
    expect(unsafe.ok).toBe(false)
    expect(unsafe.failedChecks).toEqual(
      expect.arrayContaining([
        'source_provenance_handoff_matrix_pass_created_not_false',
        'source_provenance_handoff_matrix_pass_verified_not_false',
        'source_provenance_handoff_release_case_evidence_not_false',
        'source_provenance_handoff_matrix_eligibility_not_never',
      ]),
    )
  })

  it('builds a write-once YouTube source provenance plan without creating matrix proof', () => {
    const runDir = 'E:\\ANKI\\test_runs\\video_release_hardening_20260619_044542'
    const plan = buildReleaseSourceProvenanceArtifactWritePlan({
      caseId: 'youtube_a_full1_cold',
      manifest: youtubeManifest(),
      project: youtubeProject(),
      runDir,
    })

    expect(plan.ok).toBe(true)
    expect(plan.status).toBe('ready_to_write')
    expect(plan.matrixPassCreated).toBe(false)
    expect(plan.caseDir).toBe(`${runDir}\\cases\\youtube_a_full1_cold`)
    expect(plan.writes).toHaveLength(1)
    expect(plan.writes[0]).toMatchObject({
      kind: 'source_provenance',
      relativePath: 'cases/youtube_a_full1_cold/source_provenance.json',
      absolutePath: `${runDir}\\cases\\youtube_a_full1_cold\\source_provenance.json`,
      writeMode: 'exclusive_create',
    })
    const artifact = JSON.parse(plan.writes[0]?.content ?? '{}')
    expect(artifact).toMatchObject({
      schema_version: 1,
      case_id: 'youtube_a_full1_cold',
      source_kind: 'youtube_url',
      source_fingerprint: YOUTUBE_SOURCE_FINGERPRINT,
      project_video_id: 'm7IlyBEyi3c',
      project_source_mode: 'url',
    })
    expect(artifact.matrix_pass_created).toBeUndefined()
  })

  it('builds local SRT source provenance artifact content from raw observed JSON', () => {
    const artifact = buildReleaseSourceProvenanceArtifactFromJson({
      caseId: 'local_srt_full1_cold',
      manifest: localManifest(),
      rawObserved: {
        case_id: 'local_srt_full1_cold',
        project: localProject(),
      },
    })

    expect(artifact.ok).toBe(true)
    expect(artifact.status).toBe('ready_for_write_plan')
    expect(artifact.matrixPassCreated).toBe(false)
    expect(artifact.artifactPath).toBe('cases/local_srt_full1_cold/source_provenance.json')
    expect(artifact.sourceProvenance).toMatchObject({
      case_id: 'local_srt_full1_cold',
      source_kind: 'local_video_srt',
      source_fingerprint: 'file:968c50e3449f71a3',
      project_source_mode: 'local',
      manifest_video_sha256: LOCAL_VIDEO_SHA,
      manifest_subtitle_sha256: LOCAL_SUBTITLE_SHA,
    })
  })

  it('refuses unsafe run directories before planning source provenance writes', () => {
    const plan = buildReleaseSourceProvenanceArtifactWritePlan({
      caseId: 'youtube_a_full1_cold',
      manifest: youtubeManifest(),
      project: youtubeProject(),
      runDir: 'E:\\ANKI\\test_runs\\video_release_hardening_20260619_044542\\..\\video_release_hardening_20260619_044542',
    })

    expect(plan.ok).toBe(false)
    expect(plan.writes).toEqual([])
    expect(plan.failedChecks).toContain('run_dir_path_unsafe')
  })

  it('refuses stale source provenance JSON before producing write payloads', () => {
    const plan = buildReleaseSourceProvenanceArtifactWritePlanFromJson({
      caseId: 'youtube_a_full1_cold',
      manifest: youtubeManifest(),
      rawObserved: {
        case_id: 'youtube_a_full1_cold',
        project: youtubeProject({
          source_url: 'https://www.youtube.com/watch?v=vOuhs1mA0xo',
          source_info: {
            url: 'https://www.youtube.com/watch?v=vOuhs1mA0xo',
            download_mode: 'video',
            transcript_only: false,
            skip_video_slicing: false,
          },
        }),
      },
      runDir: 'E:\\ANKI\\test_runs\\video_release_hardening_20260619_044542',
    })

    expect(plan.ok).toBe(false)
    expect(plan.status).toBe('blocked')
    expect(plan.writes).toEqual([])
    expect(plan.failedChecks).toContain('source_provenance_youtube_project_video_id_mismatch')
  })
})
