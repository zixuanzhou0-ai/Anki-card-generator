import { describe, expect, it } from 'vitest'

import {
  aggregateGenerationBatchQualityFunnel,
  generatedLearningPointIdsFromProject,
  generationBatchProgressSnapshot,
  mergeGeneratedBatchProject,
  retryLearningPointIdsAfterBatchFailure,
} from './generationBatch'

function makeRuntime(overrides: Record<string, unknown> = {}) {
  return {
    active: true,
    queueIds: ['lp-1', 'lp-2', 'lp-3'],
    activeBatchIds: ['lp-1'],
    batchSize: 1,
    totalBatches: 3,
    completedBatches: 1,
    completedCount: 1,
    generatedCount: 0,
    missingCount: 0,
    exportableCount: 0,
    nextIndex: 1,
    projectId: 'project-batch',
    baseGeneratedLearningPointIds: [],
    mergedProject: null,
    request: {},
    apiConfig: {},
    ...overrides,
  } as any
}

function makeProject(learningPointIds: string[], diagnostics: Record<string, unknown> = {}, qualityFunnel: Record<string, unknown> = {}) {
  return {
    id: 'project-batch',
    title: 'Batch project',
    source_mode: 'url',
    segments: learningPointIds.map((learningPointId, index) => ({
      id: `old-seg-${index + 1}`,
      start: index,
      end: index + 1,
      source_time: `00:00:0${index}.000 - 00:00:0${index + 1}.000`,
      text: `Source sentence ${index + 1}`,
      duration: 1,
      recommendation: 80,
      phrase: `phrase ${index + 1}`,
      learning_point_id: learningPointId,
      cards: [
        {
          id: `old-card-${index + 1}`,
          type: 'phrase',
          type_label: '表达卡',
          enabled: true,
          learning_point_id: learningPointId,
          english: `Source sentence ${index + 1}`,
          chinese: `中文解释 ${index + 1}`,
          phrase: `phrase ${index + 1}`,
          definition: `definition ${index + 1}`,
          collocations: '',
          context: '',
          example: `Example ${index + 1}`,
          chinese_feel: '',
          why: 'Useful expression.',
          difficulty: 'B1',
          teacher_note: 'Keep it natural.',
          cloze: '',
          quality: { score: 86, status: 'recommended', issues: [] },
        },
      ],
    })),
    quality_funnel: qualityFunnel,
    card_generation_diagnostics: {
      processed_learning_point_count: learningPointIds.length,
      selected_learning_point_count: learningPointIds.length,
      eligible_learning_point_count: learningPointIds.length,
      successful_learning_point_count: learningPointIds.length,
      generated_card_count: learningPointIds.length,
      exportable_card_count: learningPointIds.length,
      missing_learning_point_count: 0,
      items: [],
      ...diagnostics,
    },
  } as any
}

describe('retryLearningPointIdsAfterBatchFailure', () => {
  it('keeps completed batches out of the retry queue', () => {
    expect(
      retryLearningPointIdsAfterBatchFailure({
        queueIds: ['lp-1', 'lp-2', 'lp-3', 'lp-4', 'lp-5'],
        completedCount: 2,
        activeBatchIds: ['lp-3', 'lp-4'],
      }),
    ).toEqual(['lp-3', 'lp-4', 'lp-5'])
  })

  it('falls back to active batch ids if the queue cursor is already at the end', () => {
    expect(
      retryLearningPointIdsAfterBatchFailure({
        queueIds: ['lp-1', 'lp-2'],
        completedCount: 2,
        activeBatchIds: ['lp-2'],
      }),
    ).toEqual(['lp-2'])
  })

  it('clamps an invalid completed count without returning stale ids past the queue', () => {
    expect(
      retryLearningPointIdsAfterBatchFailure({
        queueIds: ['lp-1', 'lp-2', 'lp-3'],
        completedCount: -4,
        activeBatchIds: ['lp-1'],
      }),
    ).toEqual(['lp-1', 'lp-2', 'lp-3'])
    expect(
      retryLearningPointIdsAfterBatchFailure({
        queueIds: ['lp-1', 'lp-2', 'lp-3'],
        completedCount: 99,
        activeBatchIds: ['lp-3'],
      }),
    ).toEqual(['lp-3'])
  })
})

describe('generatedLearningPointIdsFromProject', () => {
  it('only counts enabled exportable cards as generated learning points', () => {
    const project = {
      segments: [
        {
          id: 'seg-empty',
          start: 0,
          end: 1,
          source_time: '',
          text: 'empty shell',
          duration: 1,
          recommendation: 0,
          phrase: '',
          learning_point_id: 'lp-empty-shell',
          cards: [],
        },
        {
          id: 'seg-disabled',
          start: 1,
          end: 2,
          source_time: '',
          text: 'disabled card',
          duration: 1,
          recommendation: 0,
          phrase: '',
          learning_point_id: 'lp-disabled',
          cards: [
            {
              id: 'card-disabled',
              type: 'phrase',
              type_label: '表达卡',
              enabled: false,
              learning_point_id: 'lp-disabled',
              english: 'I am not in the mood.',
              chinese: '禁用卡',
              phrase: 'in the mood',
              definition: 'disabled',
              collocations: '',
              context: '',
              example: '',
              chinese_feel: '',
              why: '',
              difficulty: 'B1',
              teacher_note: '',
              cloze: '',
              quality: { score: 80, status: 'recommended', issues: [] },
            },
          ],
        },
        {
          id: 'seg-blocked',
          start: 2,
          end: 3,
          source_time: '',
          text: 'blocked card',
          duration: 1,
          recommendation: 0,
          phrase: '',
          learning_point_id: 'lp-blocked',
          cards: [
            {
              id: 'card-blocked',
              type: 'phrase',
              type_label: '表达卡',
              enabled: true,
              learning_point_id: 'lp-blocked',
              english: 'Can you run the register?',
              chinese: '本地草稿，需要人工确认',
              phrase: 'run the register',
              definition: 'draft',
              collocations: '',
              context: '',
              example: '',
              chinese_feel: '',
              why: '',
              difficulty: 'B1',
              teacher_note: '',
              cloze: '',
              quality: { score: 80, status: 'recommended', issues: [] },
            },
          ],
        },
        {
          id: 'seg-ready',
          start: 3,
          end: 4,
          source_time: '',
          text: 'ready card',
          duration: 1,
          recommendation: 0,
          phrase: '',
          learning_point_id: 'lp-ready',
          cards: [
            {
              id: 'card-ready',
              type: 'phrase',
              type_label: '表达卡',
              enabled: true,
              learning_point_id: 'lp-ready',
              english: 'We can figure this out.',
              chinese: '我们可以把这件事弄清楚。',
              phrase: 'figure this out',
              definition: 'understand or solve something',
              collocations: '',
              context: '',
              example: '',
              chinese_feel: '',
              why: '',
              difficulty: 'B1',
              teacher_note: '用于表达解决问题。',
              cloze: '',
              quality: { score: 80, status: 'recommended', issues: [] },
            },
          ],
        },
      ],
    }

    expect(generatedLearningPointIdsFromProject(project as any)).toEqual(['lp-ready'])
  })
})

describe('generation batch reconciliation', () => {
  it('aggregates generation timing and cache counts across raw batch funnels', () => {
    const merged = aggregateGenerationBatchQualityFunnel(
      {
        generation_timing_ms: {
          card_body_ms: 100,
          total_ms: 120,
          first_only_ms: 7,
        },
        card_generation_cache_hits: 1,
        card_generation_cache_misses: 2,
        card_generation_cache_read_enabled: false,
        card_generation_cache_write_enabled: true,
        card_generation_cache_namespace: 'release-run',
      },
      {
        generation_timing_ms: {
          card_body_ms: 40,
          total_ms: 55,
          second_only_ms: 3,
        },
        card_generation_cache_hits: 4,
        card_generation_cache_misses: 5,
        card_generation_cache_read_enabled: false,
        card_generation_cache_write_enabled: true,
        card_generation_cache_namespace: 'release-run',
      },
      { completedBatches: 2, totalBatches: 2 },
    )

    expect(merged).toMatchObject({
      generation_timing_ms: {
        card_body_ms: 140,
        total_ms: 175,
        first_only_ms: 7,
        second_only_ms: 3,
      },
      generation_timing_aggregate_batch_count: 2,
      generation_timing_aggregate_complete: true,
      card_generation_cache_hits: 5,
      card_generation_cache_misses: 7,
      card_generation_cache_read_enabled: false,
      card_generation_cache_write_enabled: true,
      card_generation_cache_namespace: 'release-run',
      card_generation_cache_aggregate_batch_count: 2,
      card_generation_cache_aggregate_complete: true,
      card_generation_cache_policy_consistent: true,
      card_generation_cache_namespace_consistent: true,
    })
  })

  it('preserves conservative cache policy evidence when batch flags conflict', () => {
    const merged = aggregateGenerationBatchQualityFunnel(
      {
        card_generation_cache_hits: 0,
        card_generation_cache_misses: 1,
        card_generation_cache_read_enabled: false,
        card_generation_cache_write_enabled: true,
        card_generation_cache_namespace: 'cold-run',
      },
      {
        card_generation_cache_hits: 1,
        card_generation_cache_misses: 0,
        card_generation_cache_read_enabled: true,
        card_generation_cache_write_enabled: true,
        card_generation_cache_namespace: 'hot-run',
      },
      { completedBatches: 2, totalBatches: 2 },
    )

    expect(merged).toMatchObject({
      card_generation_cache_hits: 1,
      card_generation_cache_misses: 1,
      card_generation_cache_read_enabled: true,
      card_generation_cache_write_enabled: true,
      card_generation_cache_aggregate_complete: true,
      card_generation_cache_policy_consistent: false,
      card_generation_cache_namespace_consistent: false,
    })
    expect(merged.card_generation_cache_namespace).toBeUndefined()
  })

  it('keeps progress snapshots free of heavyweight runtime fields', () => {
    const snapshot = generationBatchProgressSnapshot(
      makeRuntime({
        mergedProject: makeProject(['lp-1']),
        request: { api_key: 'secret' },
        apiConfig: { api_key: 'secret' },
      }),
    )

    expect(snapshot).toEqual({
      active: true,
      queueIds: ['lp-1', 'lp-2', 'lp-3'],
      activeBatchIds: ['lp-1'],
      batchSize: 1,
      totalBatches: 3,
      completedBatches: 1,
      completedCount: 1,
      generatedCount: 0,
      missingCount: 0,
      exportableCount: 0,
      nextIndex: 1,
      projectId: 'project-batch',
      baseGeneratedLearningPointIds: [],
    })
  })

  it('renumbers and reconciles the first generated batch', () => {
    const merged = mergeGeneratedBatchProject(null, makeProject(['lp-1', 'lp-2']), makeRuntime({ activeBatchIds: ['lp-1', 'lp-2'], batchSize: 2 }))

    expect(merged.segments.map((segment: any) => segment.id)).toEqual(['seg_lp_0001', 'seg_lp_0002'])
    expect(merged.segments.map((segment: any) => segment.cards[0].id)).toEqual(['card_lp_0001_01', 'card_lp_0002_01'])
    expect(merged.generated_learning_point_ids).toEqual(['lp-1', 'lp-2'])
    expect(merged.card_generation_diagnostics).toMatchObject({
      processed_learning_point_count: 2,
      selected_learning_point_count: 2,
      successful_learning_point_count: 2,
      generated_card_count: 2,
      exportable_card_count: 2,
      missing_learning_point_count: 0,
    })
    expect(merged.quality_funnel).toMatchObject({
      generation_success_count: 2,
      generation_missing_count: 0,
      generation_reconciliation_status: 'ok',
      selected_exportable_card_count: 2,
    })
  })

  it('accumulates later batches and surfaces partial generation without dropping successful cards', () => {
    const first = mergeGeneratedBatchProject(
      null,
      makeProject(
        ['lp-1', 'lp-2'],
        {},
        {
          generation_timing_ms: { card_body_ms: 100, total_ms: 120 },
          card_generation_cache_hits: 0,
          card_generation_cache_misses: 2,
          card_generation_cache_read_enabled: false,
          card_generation_cache_write_enabled: true,
          card_generation_cache_namespace: 'batch-run',
        },
      ),
      makeRuntime({ activeBatchIds: ['lp-1', 'lp-2'], batchSize: 2 }),
    )
    const second = makeProject(['lp-3'], {
      processed_learning_point_count: 2,
      selected_learning_point_count: 2,
      eligible_learning_point_count: 2,
      items: [{ learning_point_id: 'lp-4', status: 'model_missing', reason: '模型未返回' }],
    }, {
      generation_timing_ms: { card_body_ms: 80, total_ms: 95 },
      card_generation_cache_hits: 1,
      card_generation_cache_misses: 1,
      card_generation_cache_read_enabled: false,
      card_generation_cache_write_enabled: true,
      card_generation_cache_namespace: 'batch-run',
    })
    const merged = mergeGeneratedBatchProject(
      first,
      second,
      makeRuntime({
        activeBatchIds: ['lp-3', 'lp-4'],
        batchSize: 2,
        totalBatches: 2,
        completedBatches: 2,
        completedCount: 4,
      }),
    )

    expect(merged.generated_learning_point_ids).toEqual(['lp-1', 'lp-2', 'lp-3'])
    expect(merged.segments.map((segment: any) => segment.id)).toEqual(['seg_lp_0001', 'seg_lp_0002', 'seg_lp_0003'])
    expect(merged.card_generation_diagnostics).toMatchObject({
      processed_learning_point_count: 4,
      selected_learning_point_count: 4,
      successful_learning_point_count: 3,
      generated_card_count: 3,
      exportable_card_count: 3,
      missing_learning_point_count: 1,
      model_missing_learning_point_count: 1,
    })
    expect(merged.quality_funnel).toMatchObject({
      generation_success_count: 3,
      generation_missing_count: 1,
      generation_reconciliation_status: 'partial',
      generation_timing_ms: {
        card_body_ms: 180,
        total_ms: 215,
      },
      generation_timing_aggregate_batch_count: 2,
      generation_timing_aggregate_complete: true,
      card_generation_cache_hits: 1,
      card_generation_cache_misses: 3,
      card_generation_cache_read_enabled: false,
      card_generation_cache_write_enabled: true,
      card_generation_cache_aggregate_batch_count: 2,
      card_generation_cache_aggregate_complete: true,
      selected_exportable_card_count: 3,
    })
  })
})
