import { invoke } from '@tauri-apps/api/core'
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

export async function startWorkerJob(command: WorkerCommand, payload: unknown): Promise<WorkerJob> {
  return invoke<WorkerJob>('start_worker_job', { command, payload })
}

export async function cancelWorkerJob(jobId: string): Promise<{ cancelled: boolean }> {
  return invoke<{ cancelled: boolean }>('cancel_worker_job', { jobId })
}

export async function getWorkerJobStatus(jobId: string): Promise<WorkerFinishedEvent | null> {
  return invoke<WorkerFinishedEvent | null>('get_worker_job_status', { jobId })
}

export async function readWorkerJobResult<T>(jobId: string): Promise<T> {
  return invoke<T>('read_worker_job_result', { jobId })
}

export async function runWorkerJobAndWait<T>(
  command: WorkerCommand,
  payload: unknown,
  pollIntervalMs = 250,
): Promise<T> {
  const { job_id: jobId } = await startWorkerJob(command, payload)

  for (;;) {
    const finished = await getWorkerJobStatus(jobId)
    if (!finished) {
      await new Promise((resolve) => window.setTimeout(resolve, pollIntervalMs))
      continue
    }
    if (!finished.ok) {
      throw new Error(finished.error || `${command} 后台任务失败。`)
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

export async function deleteSecret(key: string) {
  if (!isTauriRuntime()) return
  await invoke('delete_secret', { key })
}
