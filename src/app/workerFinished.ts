import type { WorkerFinishedEvent, WorkerOperation, WorkerProgress } from '../domain/types'

export const WORKER_RESULT_READ_TIMEOUT_MS = 15_000

function withWorkerResultReadTimeout<T>(promise: Promise<T>, timeoutMs: number): Promise<T> {
  let timeoutId: ReturnType<typeof setTimeout> | undefined
  const timeout = new Promise<never>((_, reject) => {
    timeoutId = setTimeout(() => {
      reject(new Error(`后台任务结果读取超过 ${Math.max(1, Math.ceil(timeoutMs / 1000))} 秒，请重试或保留日志定位。`))
    }, timeoutMs)
  })
  return Promise.race([promise, timeout]).finally(() => {
    if (timeoutId) clearTimeout(timeoutId)
  })
}

export async function resolveWorkerFinishedResult(
  payload: WorkerFinishedEvent,
  readResult: (jobId: string) => Promise<unknown>,
  timeoutMs = WORKER_RESULT_READ_TIMEOUT_MS,
): Promise<WorkerFinishedEvent> {
  if (!payload.ok || typeof payload.result !== 'undefined' || !payload.result_ref) {
    return payload
  }
  return {
    ...payload,
    result: await withWorkerResultReadTimeout(readResult(payload.job_id), timeoutMs),
  }
}

export type WorkerFinishMatchContext = {
  refOperation?: WorkerOperation
  stateOperation?: WorkerOperation
  lastProgress?: WorkerProgress | null
}

export function workerFinishMatchesActiveJob(payload: WorkerFinishedEvent, context: WorkerFinishMatchContext): boolean {
  const candidateJobIds = [
    context.refOperation?.jobId,
    context.stateOperation?.jobId,
    context.lastProgress?.job_id,
  ].filter(Boolean)
  return candidateJobIds.includes(payload.job_id)
}

export function workerFinishCarriesRequestBoundArtifacts(payload: Pick<WorkerFinishedEvent, 'command'>): boolean {
  return (
    payload.command === 'extract_learning_points' ||
    payload.command === 'generate' ||
    payload.command === 'generate_cards_from_learning_points' ||
    payload.command === 'export' ||
    payload.command === 'verify_anki_import'
  )
}

export function workerFinishInvalidatedByEditedRequest(
  payload: Pick<WorkerFinishedEvent, 'cancelled' | 'command' | 'ok'>,
  requestEditedDuringRun: boolean,
): boolean {
  return Boolean(
    requestEditedDuringRun && payload.ok && !payload.cancelled && workerFinishCarriesRequestBoundArtifacts(payload),
  )
}

export function fallbackWorkerOperationFromFinish(payload: WorkerFinishedEvent): WorkerOperation {
  return {
    status: 'running',
    command: payload.command,
    jobId: payload.job_id,
  }
}
