import { describe, expect, it } from 'vitest'

import type { LearningPointExtractionResult } from '../domain/learningPoints'
import { defaultRequest } from '../domain/options'
import type { Project } from '../domain/types'
import {
  buildDirectGenerationPayload,
  buildLearningPointExtractionPayload,
  buildLearningPointGenerationPayload,
} from './learningPointGenerationPayload'

const learningPointResult: LearningPointExtractionResult = {
  id: 'lp-project',
  title: '素材',
  source_mode: 'local',
  video_path: '',
  subtitle_path: '',
  language: 'en',
  level_mode: 'manual',
  level: 'B1',
  source_sentences: [],
  learning_points: [
    {
      id: 'lp-1',
      source_segment_id: 'src-1',
      source_sentence: 'Today I have a special guest.',
      source_time: '00:00:01.222 - 00:00:03.170',
      exact_span: 'special guest',
      answer_core: 'special guest',
      normalized_answer: 'special guest',
      type: 'phrase',
      candidate_kind: 'expression',
      phrase_type: 'collocation',
      level: 'B1',
      learning_action: '训练主持开场表达。',
      learning_action_key: 'expression:special guest',
      value_score: 4.6,
      reason: '高频口语词伙。',
      confidence: 'high',
      status: 'recommended',
      status_reason: '高价值、合法、不重复。',
      source: 'model_review',
    },
    {
      id: 'lp-blocked',
      source_segment_id: 'src-2',
      source_sentence: 'This should not be generated.',
      source_time: '00:00:04.000 - 00:00:06.000',
      exact_span: 'missing',
      answer_core: 'missing',
      normalized_answer: 'missing',
      type: 'phrase',
      candidate_kind: 'expression',
      phrase_type: 'collocation',
      level: 'B1',
      learning_action: '诊断项。',
      learning_action_key: 'expression:missing',
      value_score: 1,
      reason: '硬阻断。',
      confidence: 'low',
      status: 'hard_blocked',
      status_reason: '不可制卡。',
      source: 'model_review',
    },
  ],
  learning_point_summary: {
    total: 2,
    recommended: 1,
    candidate_only: 0,
    hidden_duplicate: 0,
    hard_blocked: 1,
    by_type: { phrase: 2 },
    by_level: { B1: 2 },
  },
}

function buildPayload(overrides: Partial<typeof defaultRequest>) {
  const request = { ...defaultRequest, ...overrides }
  return buildLearningPointGenerationPayload({
    learningPointResult,
    request,
    selectedLearningPointIds: new Set(['lp-1', 'lp-blocked']),
    apiConfig: request.api_config,
    projectId: 'project-test',
  })
}

describe('buildLearningPointGenerationPayload', () => {
  it('builds URL extraction payload with cache reuse and without stale local/document paths', () => {
    const request = {
      ...defaultRequest,
      source_mode: 'url' as const,
      source_url: 'https://www.youtube.com/watch?v=KL89K07KxYc',
      url_import_mode: 'video' as const,
      url_auto_subtitle_fallback: true,
      video_path: 'E:/stale/source.mp4',
      subtitle_path: 'E:/stale/source.srt',
      document_path: 'E:/stale/source.md',
      skip_video_slicing: true,
      reuse_ai_review_cache: false,
    }

    const payload = buildLearningPointExtractionPayload({
      request,
      apiConfig: request.api_config,
    })

    expect(payload.source_mode).toBe('url')
    expect(payload.source_url).toBe('https://www.youtube.com/watch?v=KL89K07KxYc')
    expect(payload.url_import_mode).toBe('video')
    expect(payload.url_auto_subtitle_fallback).toBe(false)
    expect(payload.allow_private_network_url).toBe(false)
    expect(payload.allow_ytdlp_remote_components).toBe(false)
    expect(payload.local_path_access_confirmed).toBe(false)
    expect(payload.video_path).toBe('')
    expect(payload.subtitle_path).toBe('')
    expect(payload.document_path).toBe('')
    expect(payload.skip_video_slicing).toBe(false)
    expect(payload.reuse_ai_review_cache).toBe(true)
    expect(payload.disable_ai_review_cache_read).toBe(false)
    expect(payload.disable_ai_review_cache_write).toBe(false)
  })

  it('can build a cold extraction payload that avoids old cache reads while still warming cache', () => {
    const request = {
      ...defaultRequest,
      source_mode: 'url' as const,
      source_url: 'https://www.youtube.com/watch?v=fresh-cold-material',
    }

    const payload = buildLearningPointExtractionPayload({
      request,
      apiConfig: request.api_config,
      reuseAiReviewCache: false,
      disableAiReviewCacheRead: true,
      disableAiReviewCacheWrite: false,
    })

    expect(payload.source_mode).toBe('url')
    expect(payload.reuse_ai_review_cache).toBe(false)
    expect(payload.disable_ai_review_cache_read).toBe(true)
    expect(payload.disable_ai_review_cache_write).toBe(false)
  })

  it('does not let stale api_config cache flags override extraction cache policy', () => {
    const request = {
      ...defaultRequest,
      source_mode: 'url' as const,
      source_url: 'https://www.youtube.com/watch?v=stale-cache-flags',
    }
    const apiConfig = {
      ...request.api_config,
      disable_ai_review_cache: true,
      disable_ai_review_cache_read: true,
      disable_ai_review_cache_write: true,
      disable_card_generation_cache: true,
      disable_card_generation_cache_read: true,
      disable_card_generation_cache_write: true,
      card_generation_cache_namespace: 'stale-api-config-namespace',
    } as typeof request.api_config & Record<string, unknown>

    const payload = buildLearningPointExtractionPayload({
      request,
      apiConfig,
      reuseAiReviewCache: true,
      disableAiReviewCacheRead: true,
      disableAiReviewCacheWrite: false,
    }) as Record<string, unknown>
    const payloadApiConfig = payload.api_config as Record<string, unknown>

    expect(payload.disable_ai_review_cache_read).toBe(true)
    expect(payload.disable_ai_review_cache_write).toBe(false)
    expect(payloadApiConfig.disable_ai_review_cache).toBeUndefined()
    expect(payloadApiConfig.disable_ai_review_cache_read).toBeUndefined()
    expect(payloadApiConfig.disable_ai_review_cache_write).toBeUndefined()
    expect(payloadApiConfig.disable_card_generation_cache).toBeUndefined()
    expect(payloadApiConfig.disable_card_generation_cache_read).toBeUndefined()
    expect(payloadApiConfig.disable_card_generation_cache_write).toBeUndefined()
    expect(payloadApiConfig.card_generation_cache_namespace).toBeUndefined()
  })

  it('strips stale ASR hard-gate fields from ordinary extraction payloads', () => {
    const request = {
      ...defaultRequest,
      source_mode: 'url' as const,
      source_url: 'https://www.youtube.com/watch?v=no-asr-gate',
      tts_semantic_verification: {
        enabled: true,
        require_pass_for_export: true,
        asr_provider: 'whisper-cli',
      },
      asr_provider: 'whisper-cli',
      require_pass_for_export: true,
      enable_asr_quality_gate: true,
    } as typeof defaultRequest & Record<string, unknown>

    const payload = buildLearningPointExtractionPayload({
      request,
      apiConfig: request.api_config,
    }) as Record<string, unknown>

    expect(payload.tts_semantic_verification).toBeUndefined()
    expect(payload.asr_provider).toBeUndefined()
    expect(payload.require_pass_for_export).toBeUndefined()
    expect(payload.enable_asr_quality_gate).toBeUndefined()
    expect(JSON.stringify(payload)).not.toContain('whisper-cli')
  })

  it('forces stale Ciba template ids out of ordinary extraction payloads', () => {
    const request = {
      ...defaultRequest,
      source_mode: 'url' as const,
      source_url: 'https://www.youtube.com/watch?v=no-ciba-extract',
      template_id: 'ciba_tianxia_v1' as const,
    }

    const payload = buildLearningPointExtractionPayload({
      request,
      apiConfig: request.api_config,
    })

    expect(payload.template_id).toBe('immersive_v11')
    expect(JSON.stringify(payload)).not.toContain('ciba_tianxia_v1')
  })

  it('builds local extraction payload without stale URL/document identity', () => {
    const request = {
      ...defaultRequest,
      source_mode: 'local' as const,
      source_url: 'https://example.com/stale',
      url_import_mode: 'video' as const,
      url_auto_subtitle_fallback: true,
      video_path: 'E:/media/source.mp4',
      subtitle_path: 'E:/media/source.srt',
      document_path: 'E:/stale/source.md',
      local_path_access_confirmed: true,
      skip_video_slicing: true,
    }

    const payload = buildLearningPointExtractionPayload({
      request,
      apiConfig: request.api_config,
    })

    expect(payload.source_mode).toBe('local')
    expect(payload.source_url).toBe('')
    expect(payload.url_import_mode).toBe('')
    expect(payload.url_auto_subtitle_fallback).toBe(false)
    expect(payload.allow_private_network_url).toBe(false)
    expect(payload.allow_ytdlp_remote_components).toBe(false)
    expect(payload.local_path_access_confirmed).toBe(true)
    expect(payload.video_path).toBe('E:/media/source.mp4')
    expect(payload.subtitle_path).toBe('E:/media/source.srt')
    expect(payload.document_path).toBe('')
    expect(payload.skip_video_slicing).toBe(false)
    expect(payload.reuse_ai_review_cache).toBe(true)
  })

  it('keeps URL video identity and clears stale local/document media fields', () => {
    const payload = buildPayload({
      source_mode: 'url',
      source_url: 'https://www.youtube.com/watch?v=KL89K07KxYc',
      url_import_mode: 'video',
      url_auto_subtitle_fallback: true,
      video_path: 'E:/stale/source.mp4',
      subtitle_path: 'E:/stale/source.srt',
      document_path: 'E:/stale/source.md',
      skip_video_slicing: true,
    })

    expect(payload.project_id).toBe('project-test')
    expect(payload.selected_learning_point_ids).toEqual(['lp-1'])
    expect(payload.learning_points.map((point) => point.id)).toEqual(['lp-1'])
    expect(payload.source_mode).toBe('url')
    expect(payload.source_url).toBe('https://www.youtube.com/watch?v=KL89K07KxYc')
    expect(payload.url_import_mode).toBe('video')
    expect(payload.url_auto_subtitle_fallback).toBe(false)
    expect(payload.allow_private_network_url).toBe(false)
    expect(payload.allow_ytdlp_remote_components).toBe(false)
    expect(payload.local_path_access_confirmed).toBe(false)
    expect(payload.skip_video_slicing).toBe(false)
    expect(payload.video_path).toBe('')
    expect(payload.subtitle_path).toBe('')
    expect(payload.document_path).toBe('')
  })

  it('strips stale ASR hard-gate fields from ordinary generation payloads', () => {
    const staleLearningPointResult = {
      ...learningPointResult,
      tts_semantic_verification: {
        enabled: true,
        require_pass_for_export: true,
        asr_provider: 'whisper-cli',
      },
      asr_provider: 'whisper-cli',
      require_pass_for_export: true,
      enable_asr_quality_gate: true,
    } as LearningPointExtractionResult & Record<string, unknown>
    const request = {
      ...defaultRequest,
      source_mode: 'url' as const,
      source_url: 'https://www.youtube.com/watch?v=no-asr-gate',
    }

    const payload = buildLearningPointGenerationPayload({
      learningPointResult: staleLearningPointResult,
      request,
      selectedLearningPointIds: new Set(['lp-1']),
      apiConfig: request.api_config,
      projectId: 'project-test',
    }) as Record<string, unknown>

    expect(payload.tts_semantic_verification).toBeUndefined()
    expect(payload.asr_provider).toBeUndefined()
    expect(payload.require_pass_for_export).toBeUndefined()
    expect(payload.enable_asr_quality_gate).toBeUndefined()
    expect(JSON.stringify(payload)).not.toContain('whisper-cli')
  })

  it('forces stale Ciba template ids out of ordinary learning-point generation payloads', () => {
    const request = {
      ...defaultRequest,
      source_mode: 'local' as const,
      video_path: 'E:/media/source.mp4',
      subtitle_path: 'E:/media/source.srt',
      template_id: 'ciba_tianxia_v1' as const,
    }

    const payload = buildLearningPointGenerationPayload({
      learningPointResult,
      request,
      selectedLearningPointIds: new Set(['lp-1']),
      apiConfig: request.api_config,
      projectId: 'project-test',
    })

    expect(payload.template_id).toBe('immersive_v11')
    expect(JSON.stringify(payload)).not.toContain('ciba_tianxia_v1')
  })

  it('does not let stale api_config card-cache flags disable ordinary generation hot cache', () => {
    const request = {
      ...defaultRequest,
      source_mode: 'local' as const,
      video_path: 'E:/media/source.mp4',
      subtitle_path: 'E:/media/source.srt',
    }
    const apiConfig = {
      ...request.api_config,
      disable_card_generation_cache: true,
      disable_card_generation_cache_read: true,
      disable_card_generation_cache_write: true,
      card_generation_cache_namespace: 'stale-generation-api-namespace',
    } as typeof request.api_config & Record<string, unknown>

    const payload = buildLearningPointGenerationPayload({
      learningPointResult,
      request,
      selectedLearningPointIds: new Set(['lp-1']),
      apiConfig,
      projectId: 'project-test',
    }) as Record<string, unknown>
    const payloadApiConfig = payload.api_config as Record<string, unknown>

    expect(payload.selected_learning_point_ids).toEqual(['lp-1'])
    expect(payloadApiConfig.disable_card_generation_cache).toBeUndefined()
    expect(payloadApiConfig.disable_card_generation_cache_read).toBeUndefined()
    expect(payloadApiConfig.disable_card_generation_cache_write).toBeUndefined()
    expect(payloadApiConfig.card_generation_cache_namespace).toBeUndefined()
  })

  it('keeps the generation payload scoped to selected exportable learning points only', () => {
    const payload = buildPayload({
      source_mode: 'local',
      video_path: 'E:/media/source.mp4',
      subtitle_path: 'E:/media/source.srt',
      local_path_access_confirmed: true,
    })

    expect(payload.selected_learning_point_ids).toEqual(['lp-1'])
    expect(payload.learning_points).toHaveLength(1)
    expect(payload.learning_points[0].id).toBe('lp-1')
    expect(JSON.stringify(payload)).not.toContain('This should not be generated')
  })

  it('passes source sentence provenance for selected learning points', () => {
    const resultWithProvenance: LearningPointExtractionResult = {
      ...learningPointResult,
      source_sentences: [
        {
          id: 'src-1',
          source_segment_id: 'src-1',
          source_sentence: 'Today I have a special guest.',
          text: 'Today I have a special guest.',
          start: 1.222,
          end: 3.17,
          source_time: '00:00:01.222 - 00:00:03.170',
          source_cue_ids: [1],
          source_cue_count: 1,
          source_cue_start: 1.222,
          source_cue_end: 3.17,
          source_cue_time: '00:00:01.222 - 00:00:03.170',
          source_cue_texts: ['Today I have a special guest.'],
          source_merge_reason: 'single_cue_sentence',
          source_sentence_quality_flags: ['clean'],
          source_sentence_quality_status: 'clean',
        },
      ],
    }
    const request = {
      ...defaultRequest,
      source_mode: 'local' as const,
      video_path: 'E:/media/source.mp4',
      subtitle_path: 'E:/media/source.srt',
      local_path_access_confirmed: true,
    }

    const payload = buildLearningPointGenerationPayload({
      learningPointResult: resultWithProvenance,
      request,
      selectedLearningPointIds: new Set(['lp-1']),
      apiConfig: request.api_config,
      projectId: 'project-test',
    })

    expect(payload.source_sentences).toHaveLength(1)
    expect(payload.source_sentences[0].source_cue_ids).toEqual([1])
    expect(payload.source_sentences[0].source_sentence_quality_status).toBe('clean')
    expect(payload.source_sentences[0].source_sentence_quality_flags).toEqual(['clean'])
  })

  it('keeps only local media paths for local learning-point generation', () => {
    const payload = buildPayload({
      source_mode: 'local',
      source_url: 'https://example.com/stale',
      url_import_mode: 'subtitles',
      url_auto_subtitle_fallback: true,
      video_path: 'E:/media/source.mp4',
      subtitle_path: 'E:/media/source.srt',
      document_path: 'E:/stale/source.md',
      local_path_access_confirmed: true,
      skip_video_slicing: true,
    })

    expect(payload.source_mode).toBe('local')
    expect(payload.source_url).toBe('')
    expect(payload.url_import_mode).toBe('')
    expect(payload.url_auto_subtitle_fallback).toBe(false)
    expect(payload.allow_private_network_url).toBe(false)
    expect(payload.allow_ytdlp_remote_components).toBe(false)
    expect(payload.local_path_access_confirmed).toBe(true)
    expect(payload.video_path).toBe('E:/media/source.mp4')
    expect(payload.subtitle_path).toBe('E:/media/source.srt')
    expect(payload.document_path).toBe('')
    expect(payload.skip_video_slicing).toBe(false)
  })

  it('keeps only document path for document generation and clears stale video flags', () => {
    const payload = buildPayload({
      source_mode: 'document',
      source_url: 'https://example.com/stale',
      url_import_mode: 'subtitles',
      url_auto_subtitle_fallback: true,
      video_path: 'E:/stale/source.mp4',
      subtitle_path: 'E:/stale/source.srt',
      document_path: 'E:/docs/source.md',
      local_path_access_confirmed: true,
      skip_video_slicing: true,
    })

    expect(payload.source_mode).toBe('document')
    expect(payload.source_url).toBe('')
    expect(payload.url_import_mode).toBe('')
    expect(payload.url_auto_subtitle_fallback).toBe(false)
    expect(payload.allow_private_network_url).toBe(false)
    expect(payload.allow_ytdlp_remote_components).toBe(false)
    expect(payload.local_path_access_confirmed).toBe(true)
    expect(payload.video_path).toBe('')
    expect(payload.subtitle_path).toBe('')
    expect(payload.document_path).toBe('E:/docs/source.md')
    expect(payload.skip_video_slicing).toBe(false)
  })

  it('passes URL security opt-ins only for URL sources', () => {
    const payload = buildPayload({
      source_mode: 'url',
      source_url: 'http://127.0.0.1:8000/video.mp4',
      allow_private_network_url: true,
      allow_ytdlp_remote_components: true,
      video_path: 'E:/stale/source.mp4',
      document_path: 'E:/stale/doc.md',
    })

    expect(payload.source_mode).toBe('url')
    expect(payload.allow_private_network_url).toBe(true)
    expect(payload.allow_ytdlp_remote_components).toBe(true)
    expect(payload.local_path_access_confirmed).toBe(false)
    expect(payload.video_path).toBe('')
    expect(payload.document_path).toBe('')
  })

  it('keeps restored local paths unconfirmed until the UI confirms them', () => {
    const payload = buildPayload({
      source_mode: 'local',
      video_path: 'E:/media/source.mp4',
      subtitle_path: 'E:/media/source.srt',
      local_path_access_confirmed: false,
    })

    expect(payload.source_mode).toBe('local')
    expect(payload.video_path).toBe('E:/media/source.mp4')
    expect(payload.subtitle_path).toBe('E:/media/source.srt')
    expect(payload.local_path_access_confirmed).toBe(false)
  })

  it('passes optional incremental project context without changing existing payloads', () => {
    const request = {
      ...defaultRequest,
      source_mode: 'local' as const,
      video_path: 'E:/media/source.mp4',
      subtitle_path: 'E:/media/source.srt',
      local_path_access_confirmed: true,
    }
    const payload = buildLearningPointGenerationPayload({
      learningPointResult,
      request,
      selectedLearningPointIds: new Set(['lp-1']),
      apiConfig: request.api_config,
      projectId: 'project-test',
      existingProject: {
        id: 'project-test',
        title: '素材',
        video_path: 'E:/media/source.mp4',
        subtitle_path: 'E:/media/source.srt',
        language: 'en',
        level: 'B1',
        template_id: 'immersive_v11',
        content_toggles: defaultRequest.content_toggles,
        card_types: ['phrase'],
        segments: [],
        created_at: 1,
      },
      existingGeneratedIds: ['lp-old'],
    })

    expect(payload.existing_project?.id).toBe('project-test')
    expect(payload.existing_generated_ids).toEqual(['lp-old'])
  })

  it('strips stale ASR hard-gate fields from restored existing projects', () => {
    const request = {
      ...defaultRequest,
      source_mode: 'local' as const,
      video_path: 'E:/media/source.mp4',
      subtitle_path: 'E:/media/source.srt',
      local_path_access_confirmed: true,
    }
    const payload = buildLearningPointGenerationPayload({
      learningPointResult,
      request,
      selectedLearningPointIds: new Set(['lp-1']),
      apiConfig: request.api_config,
      projectId: 'project-test',
      existingProject: {
        id: 'project-test',
        title: '旧项目',
        video_path: 'E:/media/source.mp4',
        subtitle_path: 'E:/media/source.srt',
        language: 'en',
        level: 'B1',
        template_id: 'ciba_tianxia_v1',
        content_toggles: defaultRequest.content_toggles,
        card_types: ['phrase'],
        segments: [],
        created_at: 1,
        tts_semantic_verification: {
          enabled: true,
          require_pass_for_export: true,
          asr_provider: 'whisper-cli',
        },
        asr_provider: 'whisper-cli',
        require_pass_for_export: true,
        enable_asr_quality_gate: true,
      } as Project & Record<string, unknown>,
      existingGeneratedIds: ['lp-old'],
    }) as Record<string, unknown>

    const existingProject = payload.existing_project as Record<string, unknown>

    expect(existingProject.template_id).toBe('immersive_v11')
    expect(existingProject.tts_semantic_verification).toBeUndefined()
    expect(existingProject.asr_provider).toBeUndefined()
    expect(existingProject.require_pass_for_export).toBeUndefined()
    expect(existingProject.enable_asr_quality_gate).toBeUndefined()
    expect(JSON.stringify(payload)).not.toContain('whisper-cli')
    expect(JSON.stringify(payload)).not.toContain('ciba_tianxia_v1')
  })
})

describe('buildDirectGenerationPayload', () => {
  it('strips stale ASR and Ciba state from ordinary direct/batch video generation payloads', () => {
    const request = {
      ...defaultRequest,
      source_mode: 'local' as const,
      source_url: 'https://example.com/stale',
      video_path: 'E:/media/source.mp4',
      subtitle_path: 'E:/media/source.srt',
      document_path: 'E:/docs/stale.pdf',
      template_id: 'ciba_tianxia_v1' as const,
      skip_video_slicing: true,
      allow_private_network_url: true,
      allow_ytdlp_remote_components: true,
      local_path_access_confirmed: true,
      tts_semantic_verification: {
        enabled: true,
        require_pass_for_export: true,
        asr_provider: 'whisper-cli',
      },
      asr_provider: 'whisper-cli',
      require_pass_for_export: true,
      enable_asr_quality_gate: true,
    } as typeof defaultRequest & Record<string, unknown>

    const payload = buildDirectGenerationPayload({
      request,
      apiConfig: {
        ...request.api_config,
        tts_semantic_verification: {
          enabled: true,
          require_pass_for_export: true,
          asr_provider: 'whisper-cli',
        },
        asr_provider: 'whisper-cli',
        require_pass_for_export: true,
        enable_asr_quality_gate: true,
      } as typeof request.api_config & Record<string, unknown>,
    }) as Record<string, unknown>
    const payloadApiConfig = payload.api_config as Record<string, unknown>

    expect(payload.source_mode).toBe('local')
    expect(payload.source_url).toBe('')
    expect(payload.video_path).toBe('E:/media/source.mp4')
    expect(payload.subtitle_path).toBe('E:/media/source.srt')
    expect(payload.document_path).toBe('')
    expect(payload.template_id).toBe('immersive_v11')
    expect(payload.skip_video_slicing).toBe(false)
    expect(payload.allow_private_network_url).toBe(false)
    expect(payload.allow_ytdlp_remote_components).toBe(false)
    expect(payload.local_path_access_confirmed).toBe(true)
    expect(payload.tts_semantic_verification).toBeUndefined()
    expect(payload.asr_provider).toBeUndefined()
    expect(payload.require_pass_for_export).toBeUndefined()
    expect(payload.enable_asr_quality_gate).toBeUndefined()
    expect(payloadApiConfig.tts_semantic_verification).toBeUndefined()
    expect(payloadApiConfig.asr_provider).toBeUndefined()
    expect(payloadApiConfig.require_pass_for_export).toBeUndefined()
    expect(payloadApiConfig.enable_asr_quality_gate).toBeUndefined()
    expect(JSON.stringify(payload)).not.toContain('whisper-cli')
    expect(JSON.stringify(payload)).not.toContain('ciba_tianxia_v1')
  })
})
