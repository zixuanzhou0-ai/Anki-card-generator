import type {
  ApiConfig,
  CardGenerationDiagnosticItem,
  CardGenerationDiagnostics,
  GenerateRequest,
  Project,
  QualityFunnel,
} from '../domain/types'
import { isUsableCardForExport } from '../domain/quality'
import { bindReliabilityManifestToSegments, mergeReliabilityManifests } from '../domain/reliability'

export type GenerationBatchProgress = {
  active: boolean
  queueIds: string[]
  activeBatchIds: string[]
  batchSize: number
  totalBatches: number
  completedBatches: number
  completedCount: number
  generatedCount: number
  missingCount: number
  exportableCount: number
  nextIndex: number
  projectId: string
  baseGeneratedLearningPointIds: string[]
}

export type GenerationBatchRuntime = GenerationBatchProgress & {
  mergedProject: Project | null
  request: GenerateRequest
  apiConfig: ApiConfig
}

export function retryCardGenerationCacheNamespace(now = Date.now()) {
  return `retry_${now}`
}
export function retryLearningPointIdsAfterBatchFailure({
  queueIds,
  completedCount,
  activeBatchIds,
}: {
  queueIds: string[]
  completedCount: number
  activeBatchIds: string[]
}) {
  const startIndex = Math.max(0, Math.min(queueIds.length, completedCount))
  const remaining = queueIds.slice(startIndex).filter(Boolean)
  if (remaining.length > 0) return remaining
  return activeBatchIds.filter(Boolean)
}

export function generatedLearningPointIdsFromProject(project: Pick<Project, 'segments'>) {
  const ids = new Set<string>()
  ;(project.segments ?? []).forEach((segment) => {
    const segmentId = String(segment.learning_point_id || '')
    segment.cards?.forEach((card) => {
      if (card.enabled === false || !isUsableCardForExport(segment, card)) return
      const cardPointId = String(card.learning_point_id || '')
      if (cardPointId) ids.add(cardPointId)
      else if (segmentId) ids.add(segmentId)
    })
  })
  return [...ids]
}

export function generationBatchProgressSnapshot(runtime: GenerationBatchRuntime): GenerationBatchProgress {
  return {
    active: runtime.active,
    queueIds: runtime.queueIds,
    activeBatchIds: runtime.activeBatchIds,
    batchSize: runtime.batchSize,
    totalBatches: runtime.totalBatches,
    completedBatches: runtime.completedBatches,
    completedCount: runtime.completedCount,
    generatedCount: runtime.generatedCount,
    missingCount: runtime.missingCount,
    exportableCount: runtime.exportableCount,
    nextIndex: runtime.nextIndex,
    projectId: runtime.projectId,
    baseGeneratedLearningPointIds: runtime.baseGeneratedLearningPointIds,
  }
}

export function renumberBatchSegments(segments: Project['segments']) {
  return segments.map((segment, segmentIndex) => {
    const segmentNumber = segmentIndex + 1
    const segmentId = `seg_lp_${String(segmentNumber).padStart(4, '0')}`
    return {
      ...segment,
      id: segmentId,
      cards: segment.cards.map((card, cardIndex) => ({
        ...card,
        id: `card_lp_${String(segmentNumber).padStart(4, '0')}_${String(cardIndex + 1).padStart(2, '0')}`,
      })),
    }
  })
}

export function countCardsInSegments(segments: Project['segments']) {
  return segments.reduce((total, segment) => total + (segment.cards?.length ?? 0), 0)
}

export function countEnabledCardsInSegments(segments: Project['segments']) {
  return segments.reduce((total, segment) => total + (segment.cards?.filter((card) => card.enabled !== false).length ?? 0), 0)
}

function replacePreviousLearningPointSegments(
  previousSegments: Project['segments'],
  nextSegments: Project['segments'],
) {
  const replacementIds = new Set(generatedLearningPointIdsFromProject({ segments: nextSegments }))
  if (replacementIds.size === 0) return previousSegments

  return previousSegments.flatMap((segment) => {
    const segmentPointId = String(segment.learning_point_id || '')
    if (segmentPointId && replacementIds.has(segmentPointId)) return []

    const cards = segment.cards.filter((card) => !replacementIds.has(String(card.learning_point_id || '')))
    return cards.length > 0 ? [{ ...segment, cards }] : []
  })
}

function mergeDiagnosticItems(
  previous: CardGenerationDiagnosticItem[] | undefined,
  next: CardGenerationDiagnosticItem[] | undefined,
) {
  const merged = new Map<string, CardGenerationDiagnosticItem>()
  ;[...(previous ?? []), ...(next ?? [])].forEach((item) => {
    const key = `${item.learning_point_id}:${item.status}:${item.reason}`
    merged.set(key, item)
  })
  return [...merged.values()]
}

function countDiagnosticStatus(items: CardGenerationDiagnosticItem[], status: string) {
  return items.filter((item) => item.status === status).length
}

function sumDiagnosticField(
  previous: CardGenerationDiagnostics | undefined,
  next: CardGenerationDiagnostics | undefined,
  key: keyof CardGenerationDiagnostics,
) {
  const previousValue = previous?.[key]
  const nextValue = next?.[key]
  return (typeof previousValue === 'number' ? previousValue : 0) + (typeof nextValue === 'number' ? nextValue : 0)
}

function finiteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? Math.round(value) : null
}

function nonnegativeNumber(value: unknown): number | null {
  const numeric = finiteNumber(value)
  return numeric !== null && numeric >= 0 ? numeric : null
}

function numericRecord(value: unknown): Record<string, number> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const entries = Object.entries(value)
    .map(([key, item]) => [key, finiteNumber(item)] as const)
    .filter((entry): entry is readonly [string, number] => entry[1] !== null)
  return entries.length > 0 ? Object.fromEntries(entries) : null
}

function sumTimingRecords(previous: Record<string, number> | null, next: Record<string, number> | null) {
  if (!previous && !next) return undefined
  const merged: Record<string, number> = {}
  for (const [key, value] of Object.entries(previous ?? {})) {
    merged[key] = value
  }
  for (const [key, value] of Object.entries(next ?? {})) {
    merged[key] = (merged[key] ?? 0) + value
  }
  return merged
}

function aggregateEvidenceCount(funnel: QualityFunnel | undefined, countKey: keyof QualityFunnel, hasEvidence: boolean) {
  const count = finiteNumber(funnel?.[countKey])
  if (count !== null) return count
  return hasEvidence ? 1 : 0
}

function aggregateBoolean(previous: unknown, next: unknown): boolean | undefined {
  if (typeof previous !== 'boolean' && typeof next !== 'boolean') return undefined
  if (previous === true || next === true) return true
  return false
}

function sameString(previous: unknown, next: unknown): string | undefined {
  const previousValue = typeof previous === 'string' && previous.trim() ? previous.trim() : ''
  const nextValue = typeof next === 'string' && next.trim() ? next.trim() : ''
  if (!previousValue) return nextValue || undefined
  if (!nextValue) return previousValue
  return previousValue === nextValue ? previousValue : undefined
}

export function aggregateGenerationBatchQualityFunnel(
  previous: QualityFunnel | undefined,
  next: QualityFunnel | undefined,
  runtime: Pick<GenerationBatchRuntime, 'completedBatches' | 'totalBatches'>,
): QualityFunnel {
  const previousTiming = numericRecord(previous?.generation_timing_ms)
  const nextTiming = numericRecord(next?.generation_timing_ms)
  const generationTiming = sumTimingRecords(previousTiming, nextTiming)
  const timingBatchCount =
    aggregateEvidenceCount(previous, 'generation_timing_aggregate_batch_count', Boolean(previousTiming)) +
    (nextTiming ? 1 : 0)

  const previousCacheHits = nonnegativeNumber(previous?.card_generation_cache_hits)
  const previousCacheMisses = nonnegativeNumber(previous?.card_generation_cache_misses)
  const nextCacheHits = nonnegativeNumber(next?.card_generation_cache_hits)
  const nextCacheMisses = nonnegativeNumber(next?.card_generation_cache_misses)
  const previousHasCache = previousCacheHits !== null && previousCacheMisses !== null
  const nextHasCache = nextCacheHits !== null && nextCacheMisses !== null
  const cacheBatchCount =
    aggregateEvidenceCount(previous, 'card_generation_cache_aggregate_batch_count', previousHasCache) +
    (nextHasCache ? 1 : 0)
  const readEnabled = aggregateBoolean(previous?.card_generation_cache_read_enabled, next?.card_generation_cache_read_enabled)
  const writeEnabled = aggregateBoolean(previous?.card_generation_cache_write_enabled, next?.card_generation_cache_write_enabled)
  const namespace = sameString(previous?.card_generation_cache_namespace, next?.card_generation_cache_namespace)
  const readPolicyConsistent =
    typeof previous?.card_generation_cache_read_enabled !== 'boolean' ||
    typeof next?.card_generation_cache_read_enabled !== 'boolean' ||
    previous.card_generation_cache_read_enabled === next.card_generation_cache_read_enabled
  const writePolicyConsistent =
    typeof previous?.card_generation_cache_write_enabled !== 'boolean' ||
    typeof next?.card_generation_cache_write_enabled !== 'boolean' ||
    previous.card_generation_cache_write_enabled === next.card_generation_cache_write_enabled
  const previousNamespace = typeof previous?.card_generation_cache_namespace === 'string' ? previous.card_generation_cache_namespace.trim() : ''
  const nextNamespace = typeof next?.card_generation_cache_namespace === 'string' ? next.card_generation_cache_namespace.trim() : ''
  const namespaceConsistent = !previousNamespace || !nextNamespace || previousNamespace === nextNamespace

  return {
    ...(previous ?? {}),
    ...(next ?? {}),
    ...(generationTiming
      ? {
          generation_timing_ms: generationTiming,
          generation_timing_aggregate_batch_count: timingBatchCount,
          generation_timing_aggregate_complete:
            timingBatchCount === runtime.completedBatches && runtime.completedBatches >= runtime.totalBatches,
        }
      : {}),
    ...(previousHasCache || nextHasCache
      ? {
          card_generation_cache_hits: (previousCacheHits ?? 0) + (nextCacheHits ?? 0),
          card_generation_cache_misses: (previousCacheMisses ?? 0) + (nextCacheMisses ?? 0),
          card_generation_cache_read_enabled: readEnabled,
          card_generation_cache_write_enabled: writeEnabled,
          card_generation_cache_namespace: namespace,
          card_generation_cache_aggregate_batch_count: cacheBatchCount,
          card_generation_cache_aggregate_complete:
            cacheBatchCount === runtime.completedBatches && runtime.completedBatches >= runtime.totalBatches,
          card_generation_cache_policy_consistent: readPolicyConsistent && writePolicyConsistent,
          card_generation_cache_namespace_consistent: namespaceConsistent,
        }
      : {}),
  }
}

export function reconcileBatchDiagnostics({
  previous,
  next,
  runtime,
  mergedSegments,
  generatedIds,
}: {
  previous?: CardGenerationDiagnostics
  next?: CardGenerationDiagnostics
  runtime: GenerationBatchRuntime
  mergedSegments: Project['segments']
  generatedIds: string[]
}): CardGenerationDiagnostics {
  const items = mergeDiagnosticItems(previous?.items, next?.items)
  const processed =
    (previous?.processed_learning_point_count ?? previous?.selected_learning_point_count ?? 0) +
    (next?.processed_learning_point_count ?? next?.selected_learning_point_count ?? runtime.activeBatchIds.length)
  const generatedCardCount = countCardsInSegments(mergedSegments)
  const exportableCardCount = countEnabledCardsInSegments(mergedSegments)
  const newSuccessfulCount = Math.max(0, generatedIds.length - runtime.baseGeneratedLearningPointIds.length)
  const missing = Math.max(0, processed - newSuccessfulCount)
  return {
    ...(previous ?? {}),
    ...(next ?? {}),
    processed_learning_point_count: processed,
    selected_learning_point_count: processed,
    eligible_learning_point_count: sumDiagnosticField(previous, next, 'eligible_learning_point_count'),
    successful_learning_point_count: generatedIds.length,
    generated_card_count: generatedCardCount,
    exportable_card_count: exportableCardCount,
    missing_learning_point_count: missing,
    model_missing_learning_point_count: countDiagnosticStatus(items, 'model_missing'),
    filtered_learning_point_count: countDiagnosticStatus(items, 'filtered'),
    skipped_learning_point_count: countDiagnosticStatus(items, 'skipped'),
    items,
  }
}

export function qualityFunnelWithReconciledGeneration(
  qualityFunnel: QualityFunnel | undefined,
  diagnostics: CardGenerationDiagnostics,
  runtime: GenerationBatchRuntime,
): QualityFunnel {
  const missing = diagnostics.missing_learning_point_count ?? 0
  return {
    ...(qualityFunnel ?? {}),
    generation_batch_size: runtime.batchSize,
    generation_batch_count: runtime.totalBatches,
    generation_batch_completed: runtime.completedBatches,
    generation_batch_completed_learning_points: diagnostics.processed_learning_point_count ?? runtime.completedCount,
    generation_queue_count: diagnostics.processed_learning_point_count ?? runtime.completedCount,
    generation_success_count: diagnostics.successful_learning_point_count ?? 0,
    generation_missing_count: missing,
    generation_reconciliation_status: missing > 0 ? 'partial' : 'ok',
    selected_learning_point_count: diagnostics.selected_learning_point_count,
    successful_learning_point_count: diagnostics.successful_learning_point_count,
    card_generation_missing_learning_point_count: diagnostics.model_missing_learning_point_count ?? 0,
    card_generation_filtered_card_count: diagnostics.filtered_learning_point_count ?? 0,
    card_generation_skipped_learning_point_count: diagnostics.skipped_learning_point_count ?? 0,
    card_count: diagnostics.generated_card_count,
    exportable_card_count: diagnostics.exportable_card_count,
    selected_card_count: diagnostics.exportable_card_count,
    selected_exportable_card_count: diagnostics.exportable_card_count,
  }
}

export function mergeGeneratedBatchProject(previous: Project | null, next: Project, runtime: GenerationBatchRuntime): Project {
  const previousDiagnostics =
    runtime.baseGeneratedLearningPointIds.length > 0 && runtime.completedBatches === 1
      ? undefined
      : previous?.card_generation_diagnostics
  const nextDiagnostics = next.card_generation_diagnostics
  if (!previous) {
    const segments = renumberBatchSegments(next.segments)
    const generatedIds = generatedLearningPointIdsFromProject({ ...next, segments })
    const diagnostics = reconcileBatchDiagnostics({
      previous: undefined,
      next: nextDiagnostics,
      runtime,
      mergedSegments: segments,
      generatedIds,
    })
    const reliabilityManifest = bindReliabilityManifestToSegments(next.reliability_manifest, segments)
    return {
      ...next,
      segments,
      generated_learning_point_ids: generatedIds,
      reliability_manifest: reliabilityManifest,
      quality_funnel: qualityFunnelWithReconciledGeneration(
        aggregateGenerationBatchQualityFunnel(undefined, next.quality_funnel, runtime),
        diagnostics,
        runtime,
      ),
      card_generation_diagnostics: diagnostics,
    }
  }
  const generatedIds = [
    ...new Set([
      ...(previous.generated_learning_point_ids ?? []),
      ...generatedLearningPointIdsFromProject(next),
    ]),
  ]
  const retainedPreviousSegments = replacePreviousLearningPointSegments(previous.segments ?? [], next.segments ?? [])
  const mergedSegments = renumberBatchSegments([...retainedPreviousSegments, ...(next.segments ?? [])])
  const diagnostics = reconcileBatchDiagnostics({
    previous: previousDiagnostics,
    next: nextDiagnostics,
    runtime,
    mergedSegments,
    generatedIds,
  })
  const reliabilityManifest = bindReliabilityManifestToSegments(
    mergeReliabilityManifests(previous.reliability_manifest, next.reliability_manifest),
    mergedSegments,
  )
  return {
    ...previous,
    ...next,
    segments: mergedSegments,
    generated_learning_point_ids: generatedIds,
    reliability_manifest: reliabilityManifest,
    quality_funnel: qualityFunnelWithReconciledGeneration(
      aggregateGenerationBatchQualityFunnel(previous.quality_funnel, next.quality_funnel, runtime),
      diagnostics,
      runtime,
    ),
    card_generation_diagnostics: diagnostics,
  }
}
