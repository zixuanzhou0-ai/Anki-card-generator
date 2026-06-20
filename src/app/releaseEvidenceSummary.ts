import type { LearningPointExtractionResult } from '../domain/learningPoints'
import type { AnkiVerifyResult, ExportResult, Project, QualityFunnel } from '../domain/types'

export type ReleaseTimingStage =
  | 'source_prepare_ms'
  | 'learning_point_extract_ms'
  | 'ai_review_ms'
  | 'card_body_ms'
  | 'tts_ms'
  | 'media_slice_ms'
  | 'apkg_pack_ms'
  | 'anki_verify_ms'

export type ReleaseEvidenceStageTiming = {
  key: ReleaseTimingStage
  label: string
  ms: number
}

export type ReleaseEvidenceSummary = {
  stageTimings: ReleaseEvidenceStageTiming[]
  phaseTotalsMs: {
    extraction: number
    cardGeneration: number
    export: number
    ankiVerify: number
  }
  totalStageMs: number
  perCardMs: number | null
  bottleneckStage: ReleaseEvidenceStageTiming | null
  cache: {
    aiReviewHits: number
    aiReviewMisses: number
    cardGenerationHits: number
    cardGenerationMisses: number
    ttsCacheHits: number
    ttsCacheMisses: number
    ttsCacheTotal: number
    mediaCacheHits: number
    mediaCacheMisses: number
    mediaCacheTotal: number
    exportCacheCountsComplete: boolean
    hotRunLikely: boolean
  }
  counts: {
    sourceSentences: number
    learningPoints: number
    generatedCards: number
    exportedCards: number
    verifiedCards: number
    mediaFiles: number
    audioAuditItems: number
    failedChecks: number
  }
  ready: {
    extraction: boolean
    cardGeneration: boolean
    export: boolean
    ankiVerify: boolean
  }
}

type BuildReleaseEvidenceSummaryInput = {
  learningPointResult: Pick<
    LearningPointExtractionResult,
    'quality_funnel' | 'timing_ms' | 'source_sentences' | 'learning_points'
  > | null
  project: Pick<Project, 'quality_funnel' | 'segments'> | null
  exportResult: Pick<ExportResult, 'cards' | 'media_summary' | 'timing_ms' | 'audio_audit_summary'> | null
  ankiVerifyResult: Pick<AnkiVerifyResult, 'card_count' | 'failed_checks' | 'audio_audit_summary' | 'timing_ms'> | null
}

const STAGE_LABELS: Record<ReleaseTimingStage, string> = {
  source_prepare_ms: '素材准备',
  learning_point_extract_ms: '学习点抽取',
  ai_review_ms: 'AI 精筛',
  card_body_ms: '正文生成',
  tts_ms: 'TTS',
  media_slice_ms: '媒体切片',
  apkg_pack_ms: 'APKG 打包',
  anki_verify_ms: 'Anki 核验',
}

function numberValue(value: unknown): number {
  const numeric = Number(value)
  return Number.isFinite(numeric) && numeric > 0 ? Math.round(numeric) : 0
}

function nonnegativeNumberValue(value: unknown): number | null {
  const numeric = Number(value)
  return Number.isFinite(numeric) && numeric >= 0 ? Math.round(numeric) : null
}

function timingValue(timing: Record<string, number> | undefined, key: string) {
  return numberValue(timing?.[key])
}

function timingFromQualityFunnel(qualityFunnel: QualityFunnel | undefined, key: keyof QualityFunnel) {
  const value = qualityFunnel?.[key]
  return value && typeof value === 'object' ? (value as Record<string, number>) : undefined
}

function firstPositive(...values: number[]) {
  return values.find((value) => value > 0) ?? 0
}

export function buildReleaseEvidenceSummary(input: BuildReleaseEvidenceSummaryInput): ReleaseEvidenceSummary {
  const extractionTiming =
    input.learningPointResult?.timing_ms ??
    timingFromQualityFunnel(input.learningPointResult?.quality_funnel, 'learning_point_timing_ms')
  const generationTiming = timingFromQualityFunnel(input.project?.quality_funnel, 'generation_timing_ms')
  const exportTiming = input.exportResult?.timing_ms
  const hasCurrentExport = Boolean(input.project && input.exportResult?.cards)
  const currentAnkiVerifyResult = hasCurrentExport ? input.ankiVerifyResult : null
  const verifyTiming = currentAnkiVerifyResult?.timing_ms

  const allStageTimings: ReleaseEvidenceStageTiming[] = [
    {
      key: 'source_prepare_ms',
      label: STAGE_LABELS.source_prepare_ms,
      ms: firstPositive(
        timingValue(extractionTiming, 'source_prepare_ms'),
        timingValue(generationTiming, 'source_prepare_ms'),
      ),
    },
    {
      key: 'learning_point_extract_ms',
      label: STAGE_LABELS.learning_point_extract_ms,
      ms: timingValue(extractionTiming, 'learning_point_extract_ms'),
    },
    {
      key: 'ai_review_ms',
      label: STAGE_LABELS.ai_review_ms,
      ms: timingValue(extractionTiming, 'ai_review_ms'),
    },
    {
      key: 'card_body_ms',
      label: STAGE_LABELS.card_body_ms,
      ms: timingValue(generationTiming, 'card_body_ms'),
    },
    {
      key: 'tts_ms',
      label: STAGE_LABELS.tts_ms,
      ms: timingValue(exportTiming, 'tts_ms'),
    },
    {
      key: 'media_slice_ms',
      label: STAGE_LABELS.media_slice_ms,
      ms: timingValue(exportTiming, 'media_slice_ms'),
    },
    {
      key: 'apkg_pack_ms',
      label: STAGE_LABELS.apkg_pack_ms,
      ms: timingValue(exportTiming, 'apkg_pack_ms'),
    },
    {
      key: 'anki_verify_ms',
      label: STAGE_LABELS.anki_verify_ms,
      ms: timingValue(verifyTiming, 'anki_verify_ms'),
    },
  ]
  const stageTimings = allStageTimings.filter((stage) => stage.ms > 0)

  const totalStageMs = stageTimings.reduce((sum, stage) => sum + stage.ms, 0)
  const timingCardCount = firstPositive(
    numberValue(currentAnkiVerifyResult?.card_count),
    numberValue(input.exportResult?.cards),
    numberValue(input.project?.quality_funnel?.selected_exportable_card_count),
    numberValue(input.project?.quality_funnel?.exportable_card_count),
    numberValue(input.project?.quality_funnel?.card_count),
  )
  const bottleneckStage = stageTimings.reduce<ReleaseEvidenceStageTiming | null>(
    (current, stage) => (!current || stage.ms > current.ms ? stage : current),
    null,
  )
  const extractionFunnel = input.learningPointResult?.quality_funnel
  const projectFunnel = input.project?.quality_funnel
  const qualityFunnel = projectFunnel ?? extractionFunnel
  const aiReviewHits = firstPositive(
    numberValue(extractionFunnel?.ai_review_cache_hits),
    numberValue(projectFunnel?.ai_review_cache_hits),
  )
  const aiReviewMisses = firstPositive(
    numberValue(extractionFunnel?.ai_review_cache_misses),
    numberValue(projectFunnel?.ai_review_cache_misses),
  )
  const cardGenerationHits = numberValue(input.project?.quality_funnel?.card_generation_cache_hits)
  const cardGenerationMisses = numberValue(input.project?.quality_funnel?.card_generation_cache_misses)
  const ttsCacheHits = numberValue(input.exportResult?.media_summary?.tts_cache_hits)
  const ttsCacheMissesValue = nonnegativeNumberValue(input.exportResult?.media_summary?.tts_cache_misses)
  const ttsCacheTotalValue = nonnegativeNumberValue(input.exportResult?.media_summary?.tts_cache_total)
  const ttsCacheMisses = ttsCacheMissesValue ?? 0
  const ttsCacheTotal = ttsCacheTotalValue ?? 0
  const mediaCacheHits = numberValue(input.exportResult?.media_summary?.media_cache_hits)
  const mediaCacheMissesValue = nonnegativeNumberValue(input.exportResult?.media_summary?.media_cache_misses)
  const mediaCacheTotalValue = nonnegativeNumberValue(input.exportResult?.media_summary?.media_cache_total)
  const mediaCacheMisses = mediaCacheMissesValue ?? 0
  const mediaCacheTotal = mediaCacheTotalValue ?? 0
  const exportCacheCountsComplete =
    ttsCacheMissesValue !== null &&
    ttsCacheTotalValue !== null &&
    mediaCacheMissesValue !== null &&
    mediaCacheTotalValue !== null &&
    ttsCacheHits + ttsCacheMisses === ttsCacheTotal &&
    mediaCacheHits + mediaCacheMisses === mediaCacheTotal

  return {
    stageTimings,
    phaseTotalsMs: {
      extraction: timingValue(extractionTiming, 'total_ms'),
      cardGeneration: timingValue(generationTiming, 'total_ms'),
      export: timingValue(exportTiming, 'total_ms'),
      ankiVerify: timingValue(verifyTiming, 'total_ms'),
    },
    totalStageMs,
    perCardMs: timingCardCount > 0 && totalStageMs > 0 ? Math.round(totalStageMs / timingCardCount) : null,
    bottleneckStage,
    cache: {
      aiReviewHits,
      aiReviewMisses,
      cardGenerationHits,
      cardGenerationMisses,
      ttsCacheHits,
      ttsCacheMisses,
      ttsCacheTotal,
      mediaCacheHits,
      mediaCacheMisses,
      mediaCacheTotal,
      exportCacheCountsComplete,
      hotRunLikely:
        (aiReviewHits > 0 && aiReviewMisses === 0) ||
        (cardGenerationHits > 0 && cardGenerationMisses === 0) ||
        ttsCacheHits > 0 ||
        mediaCacheHits > 0,
    },
    counts: {
      sourceSentences: firstPositive(
        numberValue(input.learningPointResult?.source_sentences?.length),
        numberValue(qualityFunnel?.source_sentence_count),
      ),
      learningPoints: firstPositive(
        numberValue(input.learningPointResult?.learning_points?.length),
        numberValue(qualityFunnel?.learning_point_count),
      ),
      generatedCards: numberValue(input.project?.quality_funnel?.card_count),
      exportedCards: numberValue(input.exportResult?.cards),
      verifiedCards: numberValue(currentAnkiVerifyResult?.card_count),
      mediaFiles: numberValue(input.exportResult?.media_summary?.media_files),
      audioAuditItems: firstPositive(
        numberValue(currentAnkiVerifyResult?.audio_audit_summary?.items),
        numberValue(input.exportResult?.audio_audit_summary?.items),
      ),
      failedChecks: numberValue(currentAnkiVerifyResult?.failed_checks?.length),
    },
    ready: {
      extraction: Boolean(input.learningPointResult),
      cardGeneration: Boolean(input.project),
      export: hasCurrentExport,
      ankiVerify: Boolean(currentAnkiVerifyResult),
    },
  }
}
