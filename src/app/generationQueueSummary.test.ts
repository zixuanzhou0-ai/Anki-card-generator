import { describe, expect, it } from 'vitest'

import type { GenerateRequest } from '../domain/types'
import type { LearningPointItem } from '../domain/learningPoints'
import type { GenerationBatchProgress } from './generationBatch'
import { buildGenerationQueueSummary } from './generationQueueSummary'

function request(overrides: Partial<GenerateRequest> = {}): GenerateRequest {
  return {
    source_mode: 'url',
    source_url: 'https://www.youtube.com/watch?v=demo',
    video_path: '',
    subtitle_path: '',
    document_path: '',
    review_density: 'fast',
    document_study_mode: 'knowledge_qa',
    allow_private_network_url: false,
    allow_ytdlp_remote_components: false,
    api_config: {
      provider: 'gemini-vertex',
      model: 'gemini-3.1-pro-preview',
      api_key: '',
      base_url: '',
      tts_config: {
        enabled: true,
        provider: 'gemini-vertex',
      },
    },
    ...overrides,
  } as GenerateRequest
}

function point(overrides: Partial<LearningPointItem> = {}): LearningPointItem {
  return {
    id: 'lp',
    source_segment_id: 'seg',
    source_sentence: 'They speak so quickly words blend together.',
    source_time: '00:00:01.000 - 00:00:03.000',
    exact_span: 'blend together',
    answer_core: 'blend together',
    normalized_answer: 'blend together',
    type: 'phrase',
    candidate_kind: 'expression',
    phrase_type: 'collocation',
    learning_action: '自然搭配',
    learning_action_key: 'blend_together',
    status: 'recommended',
    status_reason: '',
    source: 'model_review',
    confidence: 'high',
    reason: '',
    ...overrides,
  } as LearningPointItem
}

describe('generationQueueSummary', () => {
  it('summarizes URL video queues with TTS and private URL warnings', () => {
    const summary = buildGenerationQueueSummary({
      generationQueuePoints: [point({ id: 'a', answer_core: 'go' }), point({ id: 'b', answer_core: 'blend together' })],
      generationBatchProgress: null,
      request: request({ source_url: 'http://127.0.0.1:8080/video.mp4' }),
    })

    expect(summary.count).toBe(2)
    expect(summary.modeLabel).toBe('快速复读')
    expect(summary.sourceLabel).toBe('视频链接')
    expect(summary.includesVideo).toBe(true)
    expect(summary.includesOriginalAudio).toBe(true)
    expect(summary.includesSentenceTts).toBe(true)
    expect(summary.includesPhraseTts).toBe(true)
    expect(summary.estimatedMediaTasks).toBe(12)
    expect(summary.estimatedTtsSemanticChecks).toBe(4)
    expect(summary.highRiskShortExpressionCount).toBe(2)
    expect(summary.securityWarnings).toContain('本机/内网 URL 默认会被阻止')
  })

  it('uses active batch progress when present', () => {
    const progress: GenerationBatchProgress = {
      active: true,
      queueIds: ['a', 'b', 'c'],
      activeBatchIds: ['b'],
      batchSize: 12,
      totalBatches: 1,
      completedBatches: 1,
      completedCount: 2,
      generatedCount: 2,
      missingCount: 0,
      exportableCount: 2,
      nextIndex: 2,
      projectId: 'project',
      baseGeneratedLearningPointIds: [],
    }

    const summary = buildGenerationQueueSummary({
      generationQueuePoints: [point({ id: 'a' }), point({ id: 'b' }), point({ id: 'c' })],
      generationBatchProgress: progress,
      request: request(),
    })

    expect(summary.completedBatches).toBe(1)
    expect(summary.completedCount).toBe(2)
    expect(summary.generatedCount).toBe(2)
    expect(summary.exportableCount).toBe(2)
  })

  it('summarizes local video with required TTS and document queues without video media', () => {
    const local = buildGenerationQueueSummary({
      generationQueuePoints: [point()],
      generationBatchProgress: null,
      request: request({
        source_mode: 'local',
        video_path: 'E:\\videos\\clip.mp4',
        subtitle_path: 'E:\\videos\\clip.srt',
        api_config: {
          ...request().api_config,
          tts_config: {
            enabled: false,
            provider: 'disabled',
            base_url: '',
            api_key: '',
            model: '',
            voice: '',
            language: 'en-US',
            sample_rate: 24000,
            bit_rate: 128,
          },
        },
      }),
    })

    expect(local.sourceLabel).toBe('本地视频 + SRT')
    expect(local.includesVideo).toBe(true)
    expect(local.includesSentenceTts).toBe(true)
    expect(local.estimatedMediaTasks).toBe(6)
    expect(local.securityWarnings).toContain('本地文件路径将在本轮确认后读取')
    expect(local.securityWarnings).toContain('TTS 未启用，视频卡导出会被阻止')

    const document = buildGenerationQueueSummary({
      generationQueuePoints: [point()],
      generationBatchProgress: null,
      request: request({
        source_mode: 'document',
        document_study_mode: 'language_reading',
        document_path: 'E:\\docs\\notes.txt',
      }),
    })

    expect(document.modeLabel).toBe('文档精读')
    expect(document.sourceLabel).toBe('上传文档')
    expect(document.includesVideo).toBe(false)
    expect(document.includesSentenceTts).toBe(false)
    expect(document.estimatedMediaTasks).toBe(0)
  })
})
