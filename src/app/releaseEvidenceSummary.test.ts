import { describe, expect, it } from 'vitest'

import { buildReleaseEvidenceSummary } from './releaseEvidenceSummary'

describe('releaseEvidenceSummary', () => {
  it('aggregates release stage timings across extraction, generation, export, and Anki verify', () => {
    const summary = buildReleaseEvidenceSummary({
      learningPointResult: {
        quality_funnel: { ai_review_cache_hits: 0, ai_review_cache_misses: 3 },
        timing_ms: {
          source_prepare_ms: 100,
          learning_point_extract_ms: 200,
          ai_review_ms: 300,
          total_ms: 650,
        },
        source_sentences: [{ id: 's1' }, { id: 's2' }] as never,
        learning_points: [{ id: 'lp1' }, { id: 'lp2' }, { id: 'lp3' }] as never,
      },
      project: {
        segments: [],
        quality_funnel: {
          card_count: 3,
          generation_timing_ms: {
            source_prepare_ms: 10,
            card_body_ms: 400,
            total_ms: 450,
          },
          card_generation_cache_hits: 0,
          card_generation_cache_misses: 3,
        },
      },
      exportResult: {
        cards: 3,
        media_summary: {
          video_segments: 3,
          video_files: 3,
          original_audio_files: 3,
          sentence_tts_files: 3,
          phrase_tts_files: 3,
          media_files: 12,
          media_bytes: 1200,
          media_mb: 1.2,
          tts_cache_hits: 0,
          tts_cache_misses: 6,
          tts_cache_total: 6,
          media_cache_hits: 0,
          media_cache_misses: 12,
          media_cache_total: 12,
        },
        timing_ms: {
          tts_ms: 500,
          media_slice_ms: 600,
          apkg_pack_ms: 700,
          total_ms: 1900,
        },
        audio_audit_summary: { status: 'passed', items: 3, expected_items: 3 },
      },
      ankiVerifyResult: {
        card_count: 3,
        failed_checks: [],
        timing_ms: { anki_verify_ms: 800, total_ms: 800 },
        audio_audit_summary: { status: 'passed', items: 3, expected_items: 3 },
      },
    })

    expect(summary.stageTimings.map((stage) => stage.key)).toEqual([
      'source_prepare_ms',
      'learning_point_extract_ms',
      'ai_review_ms',
      'card_body_ms',
      'tts_ms',
      'media_slice_ms',
      'apkg_pack_ms',
      'anki_verify_ms',
    ])
    expect(summary.totalStageMs).toBe(3600)
    expect(summary.perCardMs).toBe(1200)
    expect(summary.bottleneckStage?.key).toBe('anki_verify_ms')
    expect(summary.phaseTotalsMs).toEqual({
      extraction: 650,
      cardGeneration: 450,
      export: 1900,
      ankiVerify: 800,
    })
    expect(summary.counts).toMatchObject({
      sourceSentences: 2,
      learningPoints: 3,
      generatedCards: 3,
      exportedCards: 3,
      verifiedCards: 3,
      mediaFiles: 12,
      audioAuditItems: 3,
      failedChecks: 0,
    })
    expect(summary.cache).toMatchObject({
      ttsCacheHits: 0,
      ttsCacheMisses: 6,
      ttsCacheTotal: 6,
      mediaCacheHits: 0,
      mediaCacheMisses: 12,
      mediaCacheTotal: 12,
      exportCacheCountsComplete: true,
    })
  })

  it('marks hot evidence when cache hits cover AI review or card generation misses', () => {
    const summary = buildReleaseEvidenceSummary({
      learningPointResult: {
        quality_funnel: {
          ai_review_cache_hits: 4,
          ai_review_cache_misses: 0,
          learning_point_count: 4,
          source_sentence_count: 8,
        },
        source_sentences: [],
        learning_points: [],
      },
      project: {
        segments: [],
        quality_funnel: {
          card_count: 4,
          card_generation_cache_hits: 4,
          card_generation_cache_misses: 0,
          generation_timing_ms: { card_body_ms: 25, total_ms: 30 },
        },
      },
      exportResult: {
        cards: 4,
        media_summary: {
          video_segments: 4,
          video_files: 4,
          original_audio_files: 4,
          sentence_tts_files: 4,
          phrase_tts_files: 4,
          media_files: 16,
          media_bytes: 1600,
          media_mb: 1.6,
          tts_cache_hits: 4,
          tts_cache_misses: 0,
          tts_cache_total: 4,
          media_cache_hits: 4,
          media_cache_misses: 0,
          media_cache_total: 4,
        },
        audio_audit_summary: { status: 'passed', items: 4, expected_items: 4 },
      },
      ankiVerifyResult: null,
    })

    expect(summary.cache).toMatchObject({
      aiReviewHits: 4,
      aiReviewMisses: 0,
      cardGenerationHits: 4,
      cardGenerationMisses: 0,
      ttsCacheHits: 4,
      ttsCacheMisses: 0,
      ttsCacheTotal: 4,
      mediaCacheHits: 4,
      mediaCacheMisses: 0,
      mediaCacheTotal: 4,
      exportCacheCountsComplete: true,
      hotRunLikely: true,
    })
    expect(summary.ready).toEqual({
      extraction: true,
      cardGeneration: true,
      export: true,
      ankiVerify: false,
    })
  })

  it('summarizes extraction-only evidence before cards are generated', () => {
    const summary = buildReleaseEvidenceSummary({
      learningPointResult: {
        quality_funnel: {
          learning_point_timing_ms: {
            source_prepare_ms: 12,
            learning_point_extract_ms: 34,
            ai_review_ms: 56,
            total_ms: 120,
          },
          source_sentence_count: 6,
          learning_point_count: 2,
        },
        source_sentences: [],
        learning_points: [],
      },
      project: null,
      exportResult: null,
      ankiVerifyResult: null,
    })

    expect(summary.stageTimings.map((stage) => [stage.key, stage.ms])).toEqual([
      ['source_prepare_ms', 12],
      ['learning_point_extract_ms', 34],
      ['ai_review_ms', 56],
    ])
    expect(summary.perCardMs).toBeNull()
    expect(summary.ready).toEqual({
      extraction: true,
      cardGeneration: false,
      export: false,
      ankiVerify: false,
    })
  })

  it('does not treat legacy export hit-only cache counters as complete final cache evidence', () => {
    const summary = buildReleaseEvidenceSummary({
      learningPointResult: null,
      project: null,
      exportResult: {
        cards: 1,
        media_summary: {
          video_segments: 1,
          video_files: 1,
          original_audio_files: 1,
          sentence_tts_files: 1,
          phrase_tts_files: 1,
          media_files: 4,
          media_bytes: 400,
          media_mb: 0.4,
          tts_cache_hits: 1,
          media_cache_hits: 1,
        },
      },
      ankiVerifyResult: null,
    })

    expect(summary.cache).toMatchObject({
      ttsCacheHits: 1,
      ttsCacheMisses: 0,
      ttsCacheTotal: 0,
      mediaCacheHits: 1,
      mediaCacheMisses: 0,
      mediaCacheTotal: 0,
      exportCacheCountsComplete: false,
      hotRunLikely: true,
    })
  })

  it('does not mark Anki verify ready after the current export evidence is cleared', () => {
    const summary = buildReleaseEvidenceSummary({
      learningPointResult: null,
      project: { segments: [], quality_funnel: { card_count: 2 } },
      exportResult: null,
      ankiVerifyResult: {
        card_count: 2,
        failed_checks: [],
        timing_ms: { anki_verify_ms: 50, total_ms: 50 },
        audio_audit_summary: { status: 'passed', items: 2, expected_items: 2 },
      },
    })

    expect(summary.ready).toEqual({
      extraction: false,
      cardGeneration: true,
      export: false,
      ankiVerify: false,
    })
    expect(summary.counts.verifiedCards).toBe(0)
    expect(summary.stageTimings.map((stage) => stage.key)).not.toContain('anki_verify_ms')
  })
})
