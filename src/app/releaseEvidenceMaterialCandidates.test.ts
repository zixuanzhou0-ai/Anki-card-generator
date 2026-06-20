import { describe, expect, it } from 'vitest'

import {
  buildVideoReleaseRunInitializerPlan,
  type VideoReleaseCaseId,
  type VideoReleaseCaseManifest,
} from '../domain/releaseEvidenceLayout'
import { buildReleaseMaterialCandidatePromotionPlan } from './releaseEvidenceMaterialCandidates'

const RUN_DIR = 'E:\\ANKI\\test_runs\\video_release_hardening_20260620_000427'
const YOUTUBE_MATERIAL_PATH =
  'E:\\ANKI\\test_runs\\video_material_rotation_20260619_124902_slice104_verified_youtube_ab\\material_manifest.json'
const LOCAL_MATERIAL_PATH =
  'E:\\ANKI\\test_runs\\video_material_rotation_20260619_132237_slice109_local_srt_youtube_a_download\\material_manifest.json'
const LOCAL_VIDEO_PATH =
  'E:\\ANKI\\test_runs\\video_material_rotation_20260619_132237_slice109_local_srt_youtube_a_download\\url_01\\source.mp4'
const LOCAL_SUBTITLE_PATH =
  'E:\\ANKI\\test_runs\\video_material_rotation_20260619_132237_slice109_local_srt_youtube_a_download\\url_01\\source.en-GB.srt'
const LOCAL_VIDEO_SHA = '968c50e3449f71a3f65bc945a7205d5cca4699b312fa28560a7adadaaec5c9d6'
const LOCAL_SUBTITLE_SHA = '0ba2394c6d6bd9485a845d4f5b91209d06c9b04e44bab17b37803855d92314a4'

function seededCaseManifests(): Partial<Record<VideoReleaseCaseId, VideoReleaseCaseManifest>> {
  const plan = buildVideoReleaseRunInitializerPlan('20260620_000427')
  return Object.fromEntries(
    plan.seedFiles
      .filter((file) => file.relativePath.endsWith('/case_manifest.json'))
      .map((file) => {
        const manifest = JSON.parse(file.content) as VideoReleaseCaseManifest
        return [manifest.case_id, manifest]
      }),
  ) as Partial<Record<VideoReleaseCaseId, VideoReleaseCaseManifest>>
}

function youtubeMaterialManifest(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: 1,
    items: [
      {
        index: 1,
        kind: 'youtube_url',
        url: 'https://www.youtube.com/watch?v=m7IlyBEyi3c',
        title: 'Limiting screen time for children',
        duration_seconds: 385,
        channel: 'BBC Learning English',
        video_id: 'm7IlyBEyi3c',
        webpage_url: 'https://www.youtube.com/watch?v=m7IlyBEyi3c',
        source_fingerprint: 'yt:779a15b6499710bd',
        cache_probe: { status: 'no_existing_url_cache_found', existing_url_cache_dirs: [] },
      },
      {
        index: 2,
        kind: 'youtube_url',
        url: 'https://www.youtube.com/watch?v=vOuhs1mA0xo',
        title: 'How advertisers make us spend money',
        duration_seconds: 374,
        channel: 'BBC Learning English',
        video_id: 'vOuhs1mA0xo',
        webpage_url: 'https://www.youtube.com/watch?v=vOuhs1mA0xo',
        source_fingerprint: 'yt:21aa74fa7215f3d8',
        cache_probe: {
          status: 'possible_existing_cache',
          existing_url_cache_dirs: ['E:\\ANKI\\projects\\url_cache\\url_89fa2c5b'],
        },
      },
    ],
    ...overrides,
  }
}

function localMaterialManifest(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: 1,
    items: [
      {
        index: 1,
        kind: 'youtube_url',
        url: 'https://www.youtube.com/watch?v=m7IlyBEyi3c',
        title: 'Limiting screen time for children',
        duration_seconds: 385,
        channel: 'BBC Learning English',
        video_id: 'm7IlyBEyi3c',
        downloaded_video_path: LOCAL_VIDEO_PATH,
        subtitle_path: LOCAL_SUBTITLE_PATH,
        video_bytes: 10706306,
        subtitle_bytes: 9440,
        video_sha256: LOCAL_VIDEO_SHA,
        subtitle_sha256: LOCAL_SUBTITLE_SHA,
        source_fingerprint: 'file:968c50e3449f71a3',
        cache_probe: { status: 'no_existing_url_cache_found', existing_url_cache_dirs: [] },
      },
    ],
    ...overrides,
  }
}

function buildPlan(
  overrides: Partial<Parameters<typeof buildReleaseMaterialCandidatePromotionPlan>[0]> = {},
) {
  return buildReleaseMaterialCandidatePromotionPlan({
    runDir: RUN_DIR,
    selectedAt: '2026-06-20T00:04:27+08:00',
    youtubeMaterialManifest: { path: YOUTUBE_MATERIAL_PATH, value: youtubeMaterialManifest() },
    localSrtMaterialManifest: { path: LOCAL_MATERIAL_PATH, value: localMaterialManifest() },
    caseManifests: seededCaseManifests(),
    ...overrides,
  })
}

describe('releaseEvidenceMaterialCandidates', () => {
  it('promotes verified YouTube and local-SRT material candidates into every initialized case manifest', () => {
    const plan = buildPlan()

    expect(plan.ok).toBe(true)
    expect(plan.status).toBe('ready_to_write')
    expect(plan.matrixPassCreated).toBe(false)
    expect(plan.failedChecks).toEqual([])
    expect(plan.writes).toHaveLength(7)
    expect(plan.promotedCases).toEqual([
      'youtube_a_full1_cold',
      'youtube_a_quick20_cold',
      'youtube_a_quick20_hot',
      'youtube_b_quick20_cold',
      'local_srt_full1_cold',
      'local_srt_quick20_cold',
      'local_srt_quick20_hot',
    ])

    const localWrite = plan.writes.find((write) => write.caseId === 'local_srt_full1_cold')
    expect(localWrite?.writeMode).toBe('replace_existing_case_manifest')
    expect(localWrite?.relativePath).toBe('cases/local_srt_full1_cold/case_manifest.json')
    expect(JSON.parse(localWrite?.content ?? '{}').source_candidate).toMatchObject({
      material_manifest: LOCAL_MATERIAL_PATH,
      video_path: LOCAL_VIDEO_PATH,
      subtitle_path: LOCAL_SUBTITLE_PATH,
      source_fingerprint: 'file:968c50e3449f71a3',
      video_sha256: LOCAL_VIDEO_SHA,
      subtitle_sha256: LOCAL_SUBTITLE_SHA,
    })
  })

  it('blocks promotion when a required material item is missing', () => {
    const plan = buildPlan({
      youtubeMaterialManifest: {
        path: YOUTUBE_MATERIAL_PATH,
        value: youtubeMaterialManifest({ items: [youtubeMaterialManifest().items[0]] }),
      },
    })

    expect(plan.ok).toBe(false)
    expect(plan.status).toBe('blocked')
    expect(plan.writes).toEqual([])
    expect(plan.failedChecks).toContain('youtube_b_material_item_2_missing')
  })

  it('blocks promotion when local video or subtitle file identity evidence is incomplete', () => {
    const badLocal = localMaterialManifest()
    badLocal.items[0] = {
      ...badLocal.items[0],
      video_sha256: '',
      subtitle_bytes: 0,
    }

    const plan = buildPlan({
      localSrtMaterialManifest: { path: LOCAL_MATERIAL_PATH, value: badLocal },
    })

    expect(plan.ok).toBe(false)
    expect(plan.failedChecks).toEqual(
      expect.arrayContaining(['local_video_srt_local_video_sha256_invalid', 'local_video_srt_local_subtitle_bytes_missing']),
    )
  })

  it('refuses to overwrite existing source candidates unless explicitly allowed', () => {
    const caseManifests = seededCaseManifests()
    caseManifests.local_srt_full1_cold = {
      ...caseManifests.local_srt_full1_cold,
      source_candidate: { source_fingerprint: 'file:oldoldoldoldold0' },
    }

    const blocked = buildPlan({ caseManifests })

    expect(blocked.ok).toBe(false)
    expect(blocked.failedChecks).toContain('case_local_srt_full1_cold_source_candidate_already_exists')

    const allowed = buildPlan({ caseManifests, overwriteExisting: true })

    expect(allowed.ok).toBe(true)
    expect(JSON.parse(allowed.writes.find((write) => write.caseId === 'local_srt_full1_cold')?.content ?? '{}')).toMatchObject({
      source_candidate: { source_fingerprint: 'file:968c50e3449f71a3' },
    })
  })
})
