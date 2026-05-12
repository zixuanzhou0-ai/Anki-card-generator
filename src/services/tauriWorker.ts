import { invoke } from '@tauri-apps/api/core'
import type { WorkerCommand, WorkerJob } from '../domain/types'
import { isTauriRuntime } from './runtime'

export async function runWorker<T>(command: string, payload: unknown): Promise<T> {
  return invoke<T>('run_worker', { command, payload })
}

export async function startWorkerJob(command: WorkerCommand, payload: unknown): Promise<WorkerJob> {
  return invoke<WorkerJob>('start_worker_job', { command, payload })
}

export async function cancelWorkerJob(jobId: string): Promise<{ cancelled: boolean }> {
  return invoke<{ cancelled: boolean }>('cancel_worker_job', { jobId })
}

export async function saveSecret(key: 'model_api_key' | 'tts_api_key', value: string) {
  if (!isTauriRuntime()) return
  await invoke('save_secret', { key, value })
}

export async function loadSecret(key: 'model_api_key' | 'tts_api_key') {
  if (!isTauriRuntime()) return ''
  return (await invoke<string | null>('load_secret', { key })) ?? ''
}

export async function deleteSecret(key: 'model_api_key' | 'tts_api_key') {
  if (!isTauriRuntime()) return
  await invoke('delete_secret', { key })
}
