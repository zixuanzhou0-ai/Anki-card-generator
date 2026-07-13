import type {
  Card,
  FieldProvenance,
  Project,
  ReliabilityManifest,
  SelectedPointOutcome,
} from './types'

export const USER_EDIT_REQUIRES_REVERIFICATION = 'USER_EDIT_REQUIRES_REVERIFICATION'
export const SELECTED_POINT_ACCOUNTING_INCOMPLETE = 'SELECTED_POINT_ACCOUNTING_INCOMPLETE'
export const FALLBACK_CARD_REQUIRES_REVIEW = 'FALLBACK_CARD_REQUIRES_REVIEW'
export const CARD_VERIFICATION_STALE = 'CARD_VERIFICATION_STALE'

const NON_SEMANTIC_CARD_FIELDS = new Set<keyof Card>(['enabled'])

function unique(values: Array<string | null | undefined>) {
  return [...new Set(values.map((value) => String(value || '').trim()).filter(Boolean))]
}

export function buildReliabilityManifest({
  outcomes,
  selectedPointCount = outcomes.length,
  sourceFingerprint,
  modelProvider,
  modelName,
  verificationProfile = 'structural_v1',
  createdAt = Date.now(),
}: {
  outcomes: SelectedPointOutcome[]
  selectedPointCount?: number
  sourceFingerprint?: string
  modelProvider?: string
  modelName?: string
  verificationProfile?: string
  createdAt?: number
}): ReliabilityManifest {
  const normalizedOutcomes = outcomes.map((outcome) => ({
    ...outcome,
    blocker_codes: unique(outcome.blocker_codes),
  }))
  const outcomeIds = normalizedOutcomes.map((outcome) => outcome.learning_point_id).filter(Boolean)
  const accountingComplete =
    normalizedOutcomes.length === selectedPointCount &&
    outcomeIds.length === selectedPointCount &&
    new Set(outcomeIds).size === selectedPointCount
  const verifiedCount = normalizedOutcomes.filter((outcome) => outcome.status === 'verified').length
  const needsReviewCount = normalizedOutcomes.filter((outcome) => outcome.status === 'needs_review').length
  const hardFailedCount = normalizedOutcomes.filter((outcome) => outcome.status === 'hard_failed').length
  const blockerCodes = unique([
    ...normalizedOutcomes.flatMap((outcome) => outcome.blocker_codes),
    accountingComplete ? '' : SELECTED_POINT_ACCOUNTING_INCOMPLETE,
  ])

  return {
    schema_version: 1,
    verification_profile: verificationProfile,
    decision: accountingComplete && needsReviewCount === 0 && hardFailedCount === 0 ? 'pass' : 'block',
    accounting_complete: accountingComplete,
    selected_point_count: selectedPointCount,
    verified_count: verifiedCount,
    needs_review_count: needsReviewCount,
    hard_failed_count: hardFailedCount,
    selected_point_outcomes: normalizedOutcomes,
    blocker_codes: blockerCodes,
    source_fingerprint: sourceFingerprint,
    model_provider: modelProvider,
    model_name: modelName,
    created_at: createdAt,
  }
}

export function mergeReliabilityManifests(
  previous: ReliabilityManifest | undefined,
  next: ReliabilityManifest | undefined,
): ReliabilityManifest | undefined {
  if (!previous) return next
  if (!next) return previous

  const merged = new Map<string, SelectedPointOutcome>()
  previous.selected_point_outcomes.forEach((outcome) => merged.set(outcome.learning_point_id, outcome))
  const overlap = next.selected_point_outcomes.filter((outcome) => merged.has(outcome.learning_point_id)).length
  next.selected_point_outcomes.forEach((outcome) => merged.set(outcome.learning_point_id, outcome))

  return buildReliabilityManifest({
    outcomes: [...merged.values()],
    selectedPointCount: previous.selected_point_count + next.selected_point_count - overlap,
    sourceFingerprint: next.source_fingerprint || previous.source_fingerprint,
    modelProvider: next.model_provider || previous.model_provider,
    modelName: next.model_name || previous.model_name,
    verificationProfile: next.verification_profile || previous.verification_profile,
    createdAt: Math.max(previous.created_at, next.created_at),
  })
}

export function bindReliabilityManifestToSegments(
  manifest: ReliabilityManifest | undefined,
  segments: Project['segments'],
): ReliabilityManifest | undefined {
  if (!manifest) return undefined
  const cardIdByPointId = new Map<string, string>()
  segments.forEach((segment) => {
    segment.cards.forEach((card) => {
      const pointId = String(card.learning_point_id || segment.learning_point_id || '')
      if (pointId && !cardIdByPointId.has(pointId)) cardIdByPointId.set(pointId, card.id)
    })
  })
  return buildReliabilityManifest({
    outcomes: manifest.selected_point_outcomes.map((outcome) => {
      const cardId = cardIdByPointId.get(outcome.learning_point_id)
      return cardId ? { ...outcome, card_id: cardId } : outcome
    }),
    selectedPointCount: manifest.selected_point_count,
    sourceFingerprint: manifest.source_fingerprint,
    modelProvider: manifest.model_provider,
    modelName: manifest.model_name,
    verificationProfile: manifest.verification_profile,
    createdAt: manifest.created_at,
  })
}

export type ReliabilityGateResult =
  | { decision: 'pass'; blockerCodes: string[]; legacyCompatibility: boolean }
  | { decision: 'block'; blockerCodes: string[]; legacyCompatibility: boolean }

function cardReliabilityBlockers(card: Card) {
  const blockers: string[] = []
  if (
    card.generation_source === 'fallback_from_selected_learning_point' ||
    card.generation_source === 'basic_from_selected_learning_point'
  ) {
    blockers.push(FALLBACK_CARD_REQUIRES_REVIEW)
  }
  if (card.verification_status && card.verification_status !== 'verified') {
    blockers.push(card.verification_status === 'stale' ? CARD_VERIFICATION_STALE : 'CARD_VERIFICATION_NOT_PASSED')
  }
  return blockers
}

export function reliabilityBlockerCodesForProject(project: Project) {
  const manifest = project.reliability_manifest
  const cardBlockers = project.segments.flatMap((segment) =>
    segment.cards.flatMap((card) => cardReliabilityBlockers(card)),
  )
  if (!manifest) return unique(cardBlockers)

  const rebuilt = buildReliabilityManifest({
    outcomes: manifest.selected_point_outcomes,
    selectedPointCount: manifest.selected_point_count,
    sourceFingerprint: manifest.source_fingerprint,
    modelProvider: manifest.model_provider,
    modelName: manifest.model_name,
    verificationProfile: manifest.verification_profile,
    createdAt: manifest.created_at,
  })
  return unique([
    ...manifest.blocker_codes,
    ...rebuilt.blocker_codes,
    ...cardBlockers,
    manifest.decision === 'pass' && rebuilt.decision === 'pass' ? '' : 'RELIABILITY_GATE_NOT_PASSED',
  ])
}

export function evaluateProjectReliabilityGate(project: Project): ReliabilityGateResult {
  const blockerCodes = reliabilityBlockerCodesForProject(project)
  if (!project.reliability_manifest && blockerCodes.length === 0) {
    return { decision: 'pass', blockerCodes: [], legacyCompatibility: true }
  }
  return blockerCodes.length === 0
    ? { decision: 'pass', blockerCodes: [], legacyCompatibility: false }
    : { decision: 'block', blockerCodes, legacyCompatibility: false }
}

function editedFieldProvenance(existing: FieldProvenance | undefined): FieldProvenance {
  return {
    ...existing,
    source: 'user_edited',
    verifier_status: 'not_checked',
    verifier_codes: [USER_EDIT_REQUIRES_REVERIFICATION],
  }
}

function invalidateManifestForCard(
  manifest: ReliabilityManifest | undefined,
  learningPointId: string,
  cardId: string,
) {
  if (!manifest) return undefined
  const outcomes = manifest.selected_point_outcomes.map((outcome) =>
    outcome.learning_point_id === learningPointId
      ? {
          ...outcome,
          status: 'needs_review' as const,
          card_id: cardId,
          blocker_codes: unique([...outcome.blocker_codes, USER_EDIT_REQUIRES_REVERIFICATION]),
          reason: '卡片关键字段已被用户编辑，需要重新验证。',
        }
      : outcome,
  )
  const rebuilt = buildReliabilityManifest({
    outcomes,
    selectedPointCount: manifest.selected_point_count,
    sourceFingerprint: manifest.source_fingerprint,
    modelProvider: manifest.model_provider,
    modelName: manifest.model_name,
    verificationProfile: manifest.verification_profile,
  })
  if (outcomes.some((outcome) => outcome.learning_point_id === learningPointId)) return rebuilt
  return {
    ...rebuilt,
    decision: 'block' as const,
    blocker_codes: unique([...rebuilt.blocker_codes, USER_EDIT_REQUIRES_REVERIFICATION]),
  }
}

export function applyCardPatchWithReliabilityInvalidation(
  project: Project,
  segmentId: string,
  cardId: string,
  patch: Partial<Card>,
): Project {
  const semanticFields = (Object.keys(patch) as Array<keyof Card>).filter(
    (field) => !NON_SEMANTIC_CARD_FIELDS.has(field),
  )
  let changedLearningPointId = ''
  let changedCardId = ''
  const segments = project.segments.map((segment) => {
    if (segment.id !== segmentId) return segment
    return {
      ...segment,
      cards: segment.cards.map((card) => {
        if (card.id !== cardId) return card
        if (semanticFields.length === 0) return { ...card, ...patch }
        changedLearningPointId = String(card.learning_point_id || segment.learning_point_id || '')
        changedCardId = card.id
        const provenance = { ...(card.field_provenance ?? {}) }
        semanticFields.forEach((field) => {
          provenance[String(field)] = editedFieldProvenance(provenance[String(field)])
        })
        return {
          ...card,
          ...patch,
          enabled: false,
          verification_status: 'stale' as const,
          verification_stale_fields: unique([
            ...(card.verification_stale_fields ?? []),
            ...semanticFields.map(String),
          ]),
          field_provenance: provenance,
          quality: {
            score: card.quality?.score ?? 0,
            status: 'needs_review' as const,
            issues: unique([...(card.quality?.issues ?? []), '用户编辑后需要重新验证。']),
          },
        }
      }),
    }
  })

  return {
    ...project,
    segments,
    reliability_manifest:
      semanticFields.length > 0 && changedCardId
        ? invalidateManifestForCard(project.reliability_manifest, changedLearningPointId, changedCardId)
        : project.reliability_manifest,
  }
}
