import { invoke } from '@tauri-apps/api/core'
import type { TaskSnapshot } from '../app/workerTaskState'
import type { EnvRepairResult, EnvStatus, WorkerCommand, WorkerFinishedEvent, WorkerJob } from '../domain/types'
import { isTauriRuntime } from './runtime'

export async function runWorker<T>(command: string, payload: unknown): Promise<T> {
  return invoke<T>('run_worker', { command, payload })
}

export async function checkBootstrapEnv(): Promise<EnvStatus> {
  return invoke<EnvStatus>('check_bootstrap_env')
}

export async function repairBootstrapEnv(target = 'python_runtime'): Promise<EnvRepairResult> {
  return invoke<EnvRepairResult>('repair_bootstrap_env', { target })
}

export async function startWorkerJob(
  command: WorkerCommand,
  payload: unknown,
  inputFingerprint?: string,
): Promise<WorkerJob> {
  return invoke<WorkerJob>('start_worker_job', {
    command,
    payload,
    ...(inputFingerprint ? { inputFingerprint } : {}),
  })
}

export async function cancelWorkerJob(jobId: string): Promise<{ cancelled: boolean }> {
  return invoke<{ cancelled: boolean }>('cancel_worker_job', { jobId })
}

export type ForceCancelWorkerJobResult = {
  found: boolean
  cancelled: boolean
  state: TaskSnapshot['state'] | 'not_found'
}

export async function forceCancelWorkerJob(jobId: string): Promise<ForceCancelWorkerJobResult> {
  return invoke<ForceCancelWorkerJobResult>('force_cancel_worker_job', { jobId })
}

export async function getWorkerJobStatus(jobId: string): Promise<WorkerFinishedEvent | null> {
  return invoke<WorkerFinishedEvent | null>('get_worker_job_status', { jobId })
}
export async function getWorkerTask(jobId: string): Promise<TaskSnapshot | null> {
  return invoke<TaskSnapshot | null>('get_worker_task', { jobId })
}

export type RecoverableWorkerTasksResult = {
  tasks: TaskSnapshot[]
  errors: string[]
}

export async function listRecoverableWorkerTasks(): Promise<RecoverableWorkerTasksResult> {
  const result = await invoke<RecoverableWorkerTasksResult | TaskSnapshot[]>('list_recoverable_worker_tasks')
  if (Array.isArray(result)) {
    return { tasks: result, errors: [] }
  }
  return {
    tasks: Array.isArray(result?.tasks) ? result.tasks : [],
    errors: Array.isArray(result?.errors)
      ? result.errors.filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
      : [],
  }
}

export async function readWorkerJobResult<T>(jobId: string): Promise<T> {
  return invoke<T>('read_worker_job_result', { jobId })
}

export type WorkerTaskResultAcknowledgement = {
  acknowledged: boolean
  state: TaskSnapshot['state'] | null
}

export async function acknowledgeWorkerTaskResult(jobId: string): Promise<WorkerTaskResultAcknowledgement> {
  return invoke<WorkerTaskResultAcknowledgement>('acknowledge_worker_task_result', { jobId })
}
export type WorkerJobObservation =
  | { type: 'started'; job: WorkerJob; command: WorkerCommand }
  | { type: 'task'; task: TaskSnapshot }
  | { type: 'finished'; event: WorkerFinishedEvent }

export type WorkerJobObserver = (observation: WorkerJobObservation) => void

export class WorkerJobError extends Error {
  readonly event: WorkerFinishedEvent

  constructor(event: WorkerFinishedEvent) {
    super(event.error || (event.cancelled ? '任务已取消。' : `${event.command} 后台任务失败。`))
    this.name = 'WorkerJobError'
    this.event = event
  }
}

export function isWorkerJobCancelled(error: unknown): error is WorkerJobError {
  return error instanceof WorkerJobError && Boolean(error.event.cancelled)
}

export async function runWorkerJobAndWait<T>(
  command: WorkerCommand,
  payload: unknown,
  pollIntervalMsOrObserver: number | WorkerJobObserver = 250,
  observerOrInputFingerprint?: WorkerJobObserver | string,
  inputFingerprint?: string,
): Promise<T> {
  const pollIntervalMs = typeof pollIntervalMsOrObserver === 'number' ? pollIntervalMsOrObserver : 250
  const resolvedObserver =
    typeof pollIntervalMsOrObserver === 'function'
      ? pollIntervalMsOrObserver
      : typeof observerOrInputFingerprint === 'function'
        ? observerOrInputFingerprint
        : undefined
  const resolvedInputFingerprint =
    typeof observerOrInputFingerprint === 'string' ? observerOrInputFingerprint : inputFingerprint
  const job = await startWorkerJob(command, payload, resolvedInputFingerprint)
  const { job_id: jobId } = job
  resolvedObserver?.({ type: 'started', job, command })

  let consecutivePollFailures = 0
  for (;;) {
    let task: TaskSnapshot | null = null
    let finished: WorkerFinishedEvent | null
    if (resolvedObserver) {
      try {
        task = await getWorkerTask(jobId)
      } catch {
        // Progress snapshots are supplementary; terminal status polling remains authoritative.
      }
    }
    try {
      finished = await getWorkerJobStatus(jobId)
      consecutivePollFailures = 0
    } catch (error) {
      consecutivePollFailures += 1
      if (consecutivePollFailures >= 3) {
        throw new Error(`连续 ${consecutivePollFailures} 次无法读取 ${command} 后台任务状态。`, {
          cause: error,
        })
      }
      await new Promise((resolve) => window.setTimeout(resolve, pollIntervalMs))
      continue
    }

    if (task) resolvedObserver?.({ type: 'task', task })
    if (!finished) {
      await new Promise((resolve) => window.setTimeout(resolve, pollIntervalMs))
      continue
    }
    resolvedObserver?.({ type: 'finished', event: finished })
    if (finished.cancelled || !finished.ok) {
      throw new WorkerJobError(finished)
    }
    if (typeof finished.result !== 'undefined') {
      return finished.result as T
    }
    if (finished.result_ref) {
      return readWorkerJobResult<T>(jobId)
    }
    throw new Error(`${command} 后台任务已完成，但没有返回结果。`)
  }
}

export async function recordRendererError(payload: unknown): Promise<void> {
  if (!isTauriRuntime()) return
  await invoke('record_renderer_error', { payload })
}

export async function saveSecret(key: string, value: string) {
  if (!isTauriRuntime()) return
  await invoke('save_secret', { key, value })
}

export async function loadSecret(key: string) {
  if (!isTauriRuntime()) return ''
  return (await invoke<string | null>('load_secret', { key })) ?? ''
}

export async function secretExists(key: string) {
  if (!isTauriRuntime()) return false
  return invoke<boolean>('secret_exists', { key })
}

export async function deleteSecret(key: string) {
  if (!isTauriRuntime()) return
  await invoke('delete_secret', { key })
}
