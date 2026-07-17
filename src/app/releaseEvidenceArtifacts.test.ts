import { describe, expect, it } from 'vitest'

import {
  buildVideoReleaseRunInitializerPlan,
  evaluateVideoReleaseCaseCompletionEvidence,
} from '../domain/releaseEvidenceLayout'
import type { VideoReleaseCaseId, VideoReleaseCaseManifest } from '../domain/releaseEvidenceLayout'
import {
  buildReleaseDeckMetadataArtifact,
  buildReleaseDeckMetadataArtifactWritePlan,
  buildReleaseTimingCacheArtifactWritePlan,
  buildReleaseTimingCacheArtifacts,
} from './releaseEvidenceArtifacts'
import type {
  BuildReleaseDeckMetadataArtifactInput,
  BuildReleaseTimingCacheArtifactsInput,
} from './releaseEvidenceArtifacts'

type CompleteColdArtifactInput = Omit<BuildReleaseTimingCacheArtifactsInput, 'exportResult'> & {
  exportResult: NonNullable<BuildReleaseTimingCacheArtifactsInput['exportResult']> &
    NonNullable<BuildReleaseDeckMetadataArtifactInput['exportResult']>
}

function manifestFor(caseId: VideoReleaseCaseId): VideoReleaseCaseManifest {
  const plan = buildVideoReleaseRunInitializerPlan('20260619_045000')
  return JSON.parse(
    plan.seedFiles.find((file) => file.relativePath === `cases/${caseId}/case_manifest.json`)?.content ?? '{}',
  )
}

function missingTimingCacheChecks(failedChecks: string[]) {
  return failedChecks.filter(
    (check) =>
      check === 'timing_missing' ||
      check === 'cache_summary_missing' ||
      check.startsWith('timing_') ||
      check.startsWith('cache_summary_'),
  )
}

function apkgEvidenceFor(caseId: VideoReleaseCaseId) {
  return {
    relative_path: `cases/${caseId}/apkg/${caseId}.apkg`,
    sha256: 'd'.repeat(64),
    size_bytes: 123456,
    mtime_ms: 1781740000000,
  }
}

function exportApkgIdentityFor(caseId: VideoReleaseCaseId) {
  return {
    apkg_path: `E:\\ANKI\\test_runs\\video_release_hardening_20260619_044542\\cases\\${caseId}\\apkg\\${caseId}.apkg`,
    apkg_sha256: 'd'.repeat(64),
    apkg_size_bytes: 123456,
    apkg_mtime_ms: 1781740000000,
  }
}

function completeColdArtifactInput(): CompleteColdArtifactInput {
  const manifest = manifestFor('youtube_a_full1_cold')
  manifest.source_candidate = {
    url: 'https://www.youtube.com/watch?v=m7IlyBEyi3c',
    video_id: 'm7IlyBEyi3c',
    source_fingerprint: 'yt:779a15b6499710bd',
    material_manifest:
      'E:\\ANKI\\test_runs\\video_material_rotation_20260619_124902_slice104_verified_youtube_ab\\material_manifest.json',
    cache_probe_status: 'no_existing_url_cache_found',
  }

  return {
    caseId: 'youtube_a_full1_cold',
    manifest,
    coldCacheReadsDisabled: true,
    learningPointResult: {
      timing_ms: {
        source_prepare_ms: 1,
        learning_point_extract_ms: 2,
        ai_review_ms: 3,
      },
      quality_funnel: {
        ai_review_cache_read_enabled: false,
        ai_review_cache_write_enabled: true,
        ai_review_cache_hits: 0,
        ai_review_cache_misses: 1,
      },
    },
    project: {
      quality_funnel: {
        card_count: 1,
        generation_timing_ms: { card_body_ms: 4 },
        card_generation_cache_read_enabled: false,
        card_generation_cache_write_enabled: true,
        card_generation_cache_hits: 0,
        card_generation_cache_misses: 1,
      },
    },
    exportResult: {
      ...exportApkgIdentityFor('youtube_a_full1_cold'),
      cards: 1,
      deck_name: '视频语言卡 - release proof',
      deck_kind: 'video_language',
      model_name: 'Anki Card Generator V12 - 沉浸复读 V11',
      template_name: '沉浸复读 V11',
      template_version: 'V12',
      anki_tag: 'anki_card_generator_v12',
      timing_ms: {
        tts_ms: 5,
        media_slice_ms: 6,
        apkg_pack_ms: 7,
      },
      media_summary: {
        video_segments: 1,
        video_files: 1,
        original_audio_files: 1,
        sentence_tts_files: 1,
        phrase_tts_files: 1,
        media_files: 4,
        media_bytes: 400,
        media_mb: 0.4,
        card_media_ledger_items: 1,
        tts_cache_hits: 0,
        tts_cache_misses: 2,
        tts_cache_total: 2,
        media_cache_hits: 0,
        media_cache_misses: 1,
        media_cache_total: 1,
      },
    },
    ankiVerifyResult: {
      card_count: 1,
      timing_ms: { anki_verify_ms: 8 },
    },
  }
}

describe('releaseEvidenceArtifacts', () => {
  it('builds deck metadata that satisfies only the final verifier deck contract', () => {
    const input = completeColdArtifactInput()
    input.manifest.status = 'passed'
    const artifact = buildReleaseDeckMetadataArtifact({
      caseId: input.caseId,
      manifest: input.manifest,
      exportResult: input.exportResult,
      ankiVerifyResult: {
        deck_name: '视频语言卡 - release proof',
        card_count: 1,
        model_names: ['Anki Card Generator V12 - 沉浸复读 V11'],
      },
    })

    expect(artifact.ok).toBe(true)
    expect(artifact.matrixPassCreated).toBe(false)
    expect(artifact.artifactPath).toBe('cases/youtube_a_full1_cold/deck_metadata.json')
    expect(artifact.deckMetadata).toMatchObject({
      schema_version: 1,
      case_id: 'youtube_a_full1_cold',
      source_fingerprint: 'yt:779a15b6499710bd',
      apkg_relative_path: 'cases/youtube_a_full1_cold/apkg/youtube_a_full1_cold.apkg',
      apkg_sha256: 'd'.repeat(64),
      apkg_size_bytes: 123456,
      apkg_mtime_ms: 1781740000000,
      deck_name: '视频语言卡 - release proof',
      deck_kind: 'video_language',
      model_name: 'Anki Card Generator V12 - 沉浸复读 V11',
      template_name: '沉浸复读 V11',
      template_version: 'V12',
      anki_tag: 'anki_card_generator_v12',
      card_count: 1,
      exported_count: 1,
    })

    const completion = evaluateVideoReleaseCaseCompletionEvidence({
      caseId: input.caseId,
      manifest: input.manifest,
      apkgFiles: [apkgEvidenceFor(input.caseId)],
      deckMetadata: artifact.deckMetadata,
    })

    expect(completion.ok).toBe(false)
    expect(completion.failedChecks.filter((check) => check.startsWith('deck_metadata'))).toEqual([])
    expect(completion.failedChecks).toEqual(
      expect.arrayContaining([
        'anki_verify_missing',
        'audio_audit_missing',
        'timing_missing',
        'cache_summary_missing',
        'observations_missing',
        'computer_use_actions_missing',
      ]),
    )
  })

  it('refuses deck metadata when source or APKG identity is incomplete', () => {
    const input = completeColdArtifactInput()
    const manifest = { ...input.manifest, source_candidate: undefined }
    const exportResult = {
      ...input.exportResult,
      deck_name: '',
      apkg_sha256: 'not-a-sha',
    }

    const artifact = buildReleaseDeckMetadataArtifact({
      caseId: input.caseId,
      manifest,
      exportResult,
    })

    expect(artifact.ok).toBe(false)
    expect(artifact.deckMetadata).toBeNull()
    expect(artifact.failedChecks).toEqual(
      expect.arrayContaining([
        'release_identity_source_fingerprint_missing',
        'release_identity_apkg_sha256_missing',
        'deck_metadata_deck_name_missing',
      ]),
    )
  })

  it('refuses deck metadata for non-canonical APKG filenames inside the case APKG folder', () => {
    const input = completeColdArtifactInput()

    const artifact = buildReleaseDeckMetadataArtifact({
      caseId: input.caseId,
      manifest: input.manifest,
      exportResult: {
        ...input.exportResult,
        apkg_path:
          'E:\\ANKI\\test_runs\\video_release_hardening_20260619_044542\\cases\\youtube_a_full1_cold\\apkg\\stale.apkg',
        apkg_relative_path: 'cases/youtube_a_full1_cold/apkg/stale.apkg',
      },
    })

    expect(artifact.ok).toBe(false)
    expect(artifact.deckMetadata).toBeNull()
    expect(artifact.failedChecks).toContain('release_identity_apkg_relative_path_not_canonical')
  })

  it('refuses deck metadata for nested APKG paths that only share the case APKG prefix', () => {
    const input = completeColdArtifactInput()

    const artifact = buildReleaseDeckMetadataArtifact({
      caseId: input.caseId,
      manifest: input.manifest,
      exportResult: {
        ...input.exportResult,
        apkg_path:
          'E:\\ANKI\\test_runs\\video_release_hardening_20260619_044542\\cases\\youtube_a_full1_cold\\apkg\\AnkiCard-old\\youtube_a_full1_cold.apkg',
        apkg_relative_path: 'cases/youtube_a_full1_cold/apkg/AnkiCard-old/youtube_a_full1_cold.apkg',
      },
    })

    expect(artifact.ok).toBe(false)
    expect(artifact.deckMetadata).toBeNull()
    expect(artifact.failedChecks).toContain('release_identity_apkg_relative_path_not_canonical')
  })

  it('refuses deck metadata when verified deck or model identity disagrees', () => {
    const input = completeColdArtifactInput()

    const artifact = buildReleaseDeckMetadataArtifact({
      caseId: input.caseId,
      manifest: input.manifest,
      exportResult: input.exportResult,
      ankiVerifyResult: {
        deck_name: '视频语言卡 - stale deck',
        card_count: 2,
        model_names: ['Anki Card Generator V12 - 词霸天下'],
      },
    })

    expect(artifact.ok).toBe(false)
    expect(artifact.deckMetadata).toBeNull()
    expect(artifact.failedChecks).toEqual(
      expect.arrayContaining([
        'deck_metadata_anki_verify_card_count_mismatch',
        'deck_metadata_anki_verify_deck_name_mismatch',
        'deck_metadata_model_name_not_verified',
      ]),
    )
  })

  it('builds a write-once deck metadata plan without writing final evidence', () => {
    const runDir = 'E:\\ANKI\\test_runs\\video_release_hardening_20260619_044542'
    const input = completeColdArtifactInput()
    const plan = buildReleaseDeckMetadataArtifactWritePlan({
      caseId: input.caseId,
      manifest: input.manifest,
      exportResult: input.exportResult,
      runDir,
    })

    expect(plan.ok).toBe(true)
    expect(plan.status).toBe('ready_to_write')
    expect(plan.matrixPassCreated).toBe(false)
    expect(plan.caseDir).toBe(`${runDir}\\cases\\youtube_a_full1_cold`)
    expect(plan.writes).toHaveLength(1)
    expect(plan.writes[0]).toMatchObject({
      kind: 'deck_metadata',
      relativePath: 'cases/youtube_a_full1_cold/deck_metadata.json',
      absolutePath: `${runDir}\\cases\\youtube_a_full1_cold\\deck_metadata.json`,
      writeMode: 'exclusive_create',
    })
    const metadata = JSON.parse(plan.writes[0]?.content ?? '{}')
    expect(metadata).toMatchObject({
      case_id: 'youtube_a_full1_cold',
      deck_name: '视频语言卡 - release proof',
      apkg_sha256: 'd'.repeat(64),
    })
    expect(metadata.matrix_pass_created).toBeUndefined()
  })

  it('refuses unsafe deck metadata write-plan run directories', () => {
    const input = completeColdArtifactInput()
    const plan = buildReleaseDeckMetadataArtifactWritePlan({
      caseId: input.caseId,
      manifest: input.manifest,
      exportResult: input.exportResult,
      runDir: 'E:\\ANKI\\test_runs\\video_release_hardening_20260619_044542\\..\\video_release_hardening_20260619_044542',
    })

    expect(plan.ok).toBe(false)
    expect(plan.writes).toEqual([])
    expect(plan.failedChecks).toContain('run_dir_path_unsafe')
  })

  it('builds cold timing and cache artifacts that satisfy the final verifier timing/cache contract without claiming a matrix pass', () => {
    for (const caseId of ['youtube_a_full1_cold', 'local_srt_full1_cold'] as const) {
      const manifest = manifestFor(caseId)
      manifest.status = 'passed'
      manifest.source_candidate =
        caseId === 'youtube_a_full1_cold'
          ? {
              url: 'https://www.youtube.com/watch?v=m7IlyBEyi3c',
              video_id: 'm7IlyBEyi3c',
              source_fingerprint: 'yt:779a15b6499710bd',
              material_manifest:
                'E:\\ANKI\\test_runs\\video_material_rotation_20260619_124902_slice104_verified_youtube_ab\\material_manifest.json',
              cache_probe_status: 'no_existing_url_cache_found',
            }
          : {
              video_path:
                'E:\\ANKI\\test_runs\\video_material_rotation_20260619_132237_slice109_local_srt_youtube_a_download\\url_01\\source.mp4',
              subtitle_path:
                'E:\\ANKI\\test_runs\\video_material_rotation_20260619_132237_slice109_local_srt_youtube_a_download\\url_01\\source.en-GB.srt',
              source_fingerprint: 'file:968c50e3449f71a3',
              material_manifest:
                'E:\\ANKI\\test_runs\\video_material_rotation_20260619_132237_slice109_local_srt_youtube_a_download\\material_manifest.json',
              cache_probe_status: 'no_existing_url_cache_found',
            }

      const artifacts = buildReleaseTimingCacheArtifacts({
        caseId,
        manifest,
        coldCacheReadsDisabled: true,
        learningPointResult: {
          timing_ms: {
            source_prepare_ms: 1,
            learning_point_extract_ms: 2,
            ai_review_ms: 3,
          },
          quality_funnel: {
            ai_review_cache_read_enabled: false,
            ai_review_cache_write_enabled: true,
            ai_review_cache_hits: 0,
            ai_review_cache_misses: 1,
          },
        },
        project: {
          quality_funnel: {
            card_count: 1,
            generation_timing_ms: { card_body_ms: 4 },
            card_generation_cache_read_enabled: false,
            card_generation_cache_write_enabled: true,
            card_generation_cache_hits: 0,
            card_generation_cache_misses: 1,
          },
        },
        exportResult: {
          ...exportApkgIdentityFor(caseId),
          cards: 1,
          timing_ms: {
            tts_ms: 5,
            media_slice_ms: 6,
            apkg_pack_ms: 7,
          },
          media_summary: {
            video_segments: 1,
            video_files: 1,
            original_audio_files: 1,
            sentence_tts_files: 1,
            phrase_tts_files: 1,
            media_files: 4,
            media_bytes: 400,
            media_mb: 0.4,
            card_media_ledger_items: 1,
            tts_cache_hits: 0,
            tts_cache_misses: 2,
            tts_cache_total: 2,
            media_cache_hits: 0,
            media_cache_misses: 1,
            media_cache_total: 1,
          },
        },
        ankiVerifyResult: {
          card_count: 1,
          timing_ms: { anki_verify_ms: 8 },
        },
      })

      expect(artifacts.ok).toBe(true)
      expect(artifacts.artifactPaths).toEqual({
        timing: `cases/${caseId}/timing.json`,
        cache_summary: `cases/${caseId}/cache_summary.json`,
      })
      expect(artifacts.timing).toMatchObject({
        case_id: caseId,
        declared_cache_state: 'cold',
        observed_cache_state: 'cold',
        total_ms: 36,
        timing_card_count: 1,
        per_card_ms: 36,
        bottleneck_stage: 'anki_verify',
        bottleneck_ms: 8,
      })
      expect(artifacts.cacheSummary).toMatchObject({
        case_id: caseId,
        cold_cache_reads_disabled: true,
        cold_claim_scope: 'source_probe_clean_ai_card_cache_reads_disabled',
        ai_review_cache: { read_enabled: false, hits: 0, misses: 1, total: 1 },
        card_generation_cache: { read_enabled: false, hits: 0, misses: 1, total: 1 },
        tts_cache: { hits: 0, misses: 2, total: 2 },
        media_cache: { hits: 0, misses: 1, total: 1 },
      })
      if (!artifacts.timing || !artifacts.cacheSummary) throw new Error('expected timing and cache artifacts')

      const completion = evaluateVideoReleaseCaseCompletionEvidence({
        caseId,
        manifest,
        apkgFiles: [apkgEvidenceFor(caseId)],
        timing: artifacts.timing,
        cacheSummary: artifacts.cacheSummary,
      })

      expect(completion.ok).toBe(false)
      expect(missingTimingCacheChecks(completion.failedChecks)).toEqual([])
      expect(completion.failedChecks).toEqual(
        expect.arrayContaining([
          'deck_metadata_missing',
          'anki_verify_missing',
          'audio_audit_missing',
          'observations_missing',
          'computer_use_actions_missing',
          'screenshots_below_required_preview_count',
        ]),
      )
    }
  })

  it('refuses legacy export hit-only counters instead of deriving final cache evidence', () => {
    const manifest = manifestFor('youtube_a_full1_cold')
    manifest.source_candidate = {
      cache_probe_status: 'no_existing_url_cache_found',
    }

    const artifacts = buildReleaseTimingCacheArtifacts({
      caseId: 'youtube_a_full1_cold',
      manifest,
      coldCacheReadsDisabled: true,
      learningPointResult: {
        timing_ms: { source_prepare_ms: 1, learning_point_extract_ms: 2, ai_review_ms: 3 },
        quality_funnel: {
          ai_review_cache_read_enabled: false,
          ai_review_cache_write_enabled: true,
          ai_review_cache_hits: 0,
          ai_review_cache_misses: 1,
        },
      },
      project: {
        quality_funnel: {
          card_count: 1,
          generation_timing_ms: { card_body_ms: 4 },
          card_generation_cache_read_enabled: false,
          card_generation_cache_write_enabled: true,
          card_generation_cache_hits: 0,
          card_generation_cache_misses: 1,
        },
      },
      exportResult: {
        ...exportApkgIdentityFor('youtube_a_full1_cold'),
        cards: 1,
        timing_ms: { tts_ms: 5, media_slice_ms: 6, apkg_pack_ms: 7 },
        media_summary: {
          video_segments: 1,
          video_files: 1,
          original_audio_files: 1,
          sentence_tts_files: 1,
          phrase_tts_files: 1,
          media_files: 4,
          media_bytes: 400,
          media_mb: 0.4,
          card_media_ledger_items: 1,
          tts_cache_hits: 0,
          media_cache_hits: 0,
        },
      },
      ankiVerifyResult: { card_count: 1, timing_ms: { anki_verify_ms: 8 } },
    })

    expect(artifacts.ok).toBe(false)
    expect(artifacts.failedChecks).toEqual(
      expect.arrayContaining([
        'tts_cache_misses_missing',
        'tts_cache_total_missing',
        'media_cache_misses_missing',
        'media_cache_total_missing',
      ]),
    )
    expect(artifacts.timing).toBeNull()
    expect(artifacts.cacheSummary).toBeNull()
  })

  it('refuses timing and cache artifacts for non-canonical APKG identity', () => {
    const input = completeColdArtifactInput()

    const artifacts = buildReleaseTimingCacheArtifacts({
      ...input,
      exportResult: {
        ...input.exportResult,
        apkg_path:
          'E:\\ANKI\\test_runs\\video_release_hardening_20260619_044542\\cases\\youtube_a_full1_cold\\apkg\\AnkiCard-old\\youtube_a_full1_cold.apkg',
        apkg_relative_path: 'cases/youtube_a_full1_cold/apkg/AnkiCard-old/youtube_a_full1_cold.apkg',
      },
    })

    expect(artifacts.ok).toBe(false)
    expect(artifacts.timing).toBeNull()
    expect(artifacts.cacheSummary).toBeNull()
    expect(artifacts.failedChecks).toContain('release_identity_apkg_relative_path_not_canonical')
  })

  it('builds hot cache artifacts only from explicit read-enabled flags and hit/miss/total coverage', () => {
    const manifest = manifestFor('youtube_a_quick20_hot')
    manifest.status = 'passed'
    manifest.source_candidate = {
      url: 'https://www.youtube.com/watch?v=m7IlyBEyi3c',
      video_id: 'm7IlyBEyi3c',
      source_fingerprint: 'yt:779a15b6499710bd',
      material_manifest:
        'E:\\ANKI\\test_runs\\video_material_rotation_20260619_124902_slice104_verified_youtube_ab\\material_manifest.json',
      cache_probe_status: 'no_existing_url_cache_found',
    }

    const artifacts = buildReleaseTimingCacheArtifacts({
      caseId: 'youtube_a_quick20_hot',
      manifest,
      learningPointResult: {
        timing_ms: { source_prepare_ms: 10, learning_point_extract_ms: 20, ai_review_ms: 30 },
        quality_funnel: {
          ai_review_cache_read_enabled: true,
          ai_review_cache_write_enabled: true,
          ai_review_cache_hits: 20,
          ai_review_cache_misses: 0,
        },
      },
      project: {
        quality_funnel: {
          card_count: 20,
          generation_timing_ms: { card_body_ms: 0 },
          card_generation_cache_read_enabled: true,
          card_generation_cache_write_enabled: true,
          card_generation_cache_hits: 20,
          card_generation_cache_misses: 0,
        },
      },
      exportResult: {
        ...exportApkgIdentityFor('youtube_a_quick20_hot'),
        cards: 20,
        timing_ms: { tts_ms: 50, media_slice_ms: 60, apkg_pack_ms: 70 },
        media_summary: {
          video_segments: 20,
          video_files: 20,
          original_audio_files: 20,
          sentence_tts_files: 20,
          phrase_tts_files: 19,
          media_files: 80,
          media_bytes: 8000,
          media_mb: 8,
          card_media_ledger_items: 20,
          tts_cache_hits: 39,
          tts_cache_misses: 0,
          tts_cache_total: 39,
          media_cache_hits: 20,
          media_cache_misses: 0,
          media_cache_total: 20,
        },
      },
      ankiVerifyResult: {
        card_count: 20,
        timing_ms: { anki_verify_ms: 80 },
      },
    })

    expect(artifacts.ok).toBe(true)
    expect(artifacts.cacheSummary).toMatchObject({
      case_id: 'youtube_a_quick20_hot',
      declared_cache_state: 'hot',
      observed_cache_state: 'hot',
      cold_cache_reads_disabled: null,
      cold_claim_scope: 'not_cold_run',
      card_generation_cache: { read_enabled: true, hits: 20, misses: 0, total: 20 },
      tts_cache: { hits: 39, misses: 0, total: 39 },
      media_cache: { hits: 20, misses: 0, total: 20 },
    })
    if (!artifacts.timing || !artifacts.cacheSummary) throw new Error('expected hot timing and cache artifacts')

    const completion = evaluateVideoReleaseCaseCompletionEvidence({
      caseId: 'youtube_a_quick20_hot',
      manifest,
      apkgFiles: [apkgEvidenceFor('youtube_a_quick20_hot')],
      timing: artifacts.timing,
      cacheSummary: artifacts.cacheSummary,
    })

    expect(completion.ok).toBe(false)
    expect(missingTimingCacheChecks(completion.failedChecks)).toEqual([])
  })

  it('builds a write-once case-local write plan without creating matrix-pass evidence', () => {
    const runDir = 'E:\\ANKI\\test_runs\\video_release_hardening_20260619_044542'
    const plan = buildReleaseTimingCacheArtifactWritePlan({
      ...completeColdArtifactInput(),
      runDir,
    })

    expect(plan.ok).toBe(true)
    expect(plan.status).toBe('ready_to_write')
    expect(plan.matrixPassCreated).toBe(false)
    expect(plan.caseDir).toBe(`${runDir}\\cases\\youtube_a_full1_cold`)
    expect(
      plan.writes.map((write) => ({
        kind: write.kind,
        relativePath: write.relativePath,
        absolutePath: write.absolutePath,
        writeMode: write.writeMode,
      })),
    ).toEqual([
      {
        kind: 'timing',
        relativePath: 'cases/youtube_a_full1_cold/timing.json',
        absolutePath: `${runDir}\\cases\\youtube_a_full1_cold\\timing.json`,
        writeMode: 'exclusive_create',
      },
      {
        kind: 'cache_summary',
        relativePath: 'cases/youtube_a_full1_cold/cache_summary.json',
        absolutePath: `${runDir}\\cases\\youtube_a_full1_cold\\cache_summary.json`,
        writeMode: 'exclusive_create',
      },
    ])

    const timing = JSON.parse(plan.writes.find((write) => write.kind === 'timing')?.content ?? '{}')
    const cacheSummary = JSON.parse(plan.writes.find((write) => write.kind === 'cache_summary')?.content ?? '{}')
    expect(timing).toMatchObject({ case_id: 'youtube_a_full1_cold', timing_card_count: 1 })
    expect(cacheSummary).toMatchObject({ case_id: 'youtube_a_full1_cold', cold_cache_reads_disabled: true })
    expect(timing.matrix_pass_created).toBeUndefined()
    expect(cacheSummary.matrix_pass_created).toBeUndefined()
    expect(plan.writes.map((write) => write.relativePath)).not.toContain(
      'cases/youtube_a_full1_cold/case_manifest.json',
    )
  })

  it('refuses unsafe or non-release run directories before planning writes', () => {
    const plan = buildReleaseTimingCacheArtifactWritePlan({
      ...completeColdArtifactInput(),
      runDir:
        'E:\\ANKI\\test_runs\\video_release_hardening_20260619_044542\\..\\video_release_hardening_20260619_044542',
    })

    expect(plan.ok).toBe(false)
    expect(plan.failedChecks).toContain('run_dir_path_unsafe')
    expect(plan.writes).toEqual([])
  })

  it('refuses incomplete raw timing/cache evidence instead of returning write payloads', () => {
    const input = completeColdArtifactInput()
    const mediaSummary = { ...input.exportResult?.media_summary } as Record<string, unknown>
    delete mediaSummary.tts_cache_total
    input.exportResult = {
      ...input.exportResult,
      media_summary: mediaSummary as never,
    } as never

    const plan = buildReleaseTimingCacheArtifactWritePlan({
      ...input,
      runDir: 'E:\\ANKI\\test_runs\\video_release_hardening_20260619_044542',
    })

    expect(plan.ok).toBe(false)
    expect(plan.failedChecks).toContain('tts_cache_total_missing')
    expect(plan.writes).toEqual([])
  })

  it('refuses case manifest mismatches before any timing/cache write can be planned', () => {
    const input = completeColdArtifactInput()
    input.manifest = {
      ...input.manifest,
      case_id: 'local_srt_full1_cold',
    } as never

    const plan = buildReleaseTimingCacheArtifactWritePlan({
      ...input,
      runDir: 'E:\\ANKI\\test_runs\\video_release_hardening_20260619_044542',
    })

    expect(plan.ok).toBe(false)
    expect(plan.failedChecks).toContain('write_plan_case_manifest_id_mismatch')
    expect(plan.writes).toEqual([])
  })
})
