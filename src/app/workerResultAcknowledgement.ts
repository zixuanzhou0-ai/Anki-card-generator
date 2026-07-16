export type WorkerResultAcknowledgement = {
  acknowledged: boolean
  state: string | null
}

export type AppliedWorkerResultAcknowledgementOutcome = {
  consumedIds: string[]
  rejected: Array<{ jobId: string; state: string }>
  retryIds: string[]
}

type AppliedWorkerResultAcknowledgementOptions = {
  jobIds: Iterable<string>
  persistCheckpoint: () => Promise<void>
  acknowledge: (jobId: string) => Promise<WorkerResultAcknowledgement>
}

/**
 * Persists the renderer's latest artifact state before releasing durable worker results.
 * A failed checkpoint write is intentionally allowed to reject the whole operation so
 * no acknowledgement can run against a result that is not yet recoverable elsewhere.
 */
export async function acknowledgeAppliedWorkerResults({
  jobIds,
  persistCheckpoint,
  acknowledge,
}: AppliedWorkerResultAcknowledgementOptions): Promise<AppliedWorkerResultAcknowledgementOutcome> {
  const uniqueJobIds = [...new Set([...jobIds].filter(Boolean))]
  if (uniqueJobIds.length === 0) {
    return { consumedIds: [], rejected: [], retryIds: [] }
  }

  await persistCheckpoint()

  const outcome: AppliedWorkerResultAcknowledgementOutcome = {
    consumedIds: [],
    rejected: [],
    retryIds: [],
  }
  for (const jobId of uniqueJobIds) {
    try {
      const result = await acknowledge(jobId)
      if (result.acknowledged || result.state === null) {
        outcome.consumedIds.push(jobId)
      } else {
        outcome.rejected.push({ jobId, state: result.state })
      }
    } catch {
      outcome.retryIds.push(jobId)
    }
  }
  return outcome
}
