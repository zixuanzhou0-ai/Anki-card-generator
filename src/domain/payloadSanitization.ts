export const staleOrdinaryAsrHardGateKeys = [
  'tts_semantic_verification',
  'asr_provider',
  'require_pass_for_export',
  'enable_asr_quality_gate',
] as const

export function stripStaleOrdinaryAsrGate<T extends Record<string, unknown>>(value: T): T {
  const sanitized = { ...value }
  for (const key of staleOrdinaryAsrHardGateKeys) {
    delete sanitized[key]
  }
  return sanitized
}
