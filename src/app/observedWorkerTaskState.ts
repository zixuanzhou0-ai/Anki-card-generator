import type { WorkerOperation, WorkerProgress } from '../domain/types'
import type { WorkerJobObservation } from '../services/tauriWorker'
import type { OperationState, TaskSnapshot } from './workerTaskState'

export const FORCE_CANCEL_DELAY_MS = 10_000

export type ForceCancelAvailability = {
  remainingMs: number | null
  visible: boolean
}

export type ObservedWorkerTaskLifecycle = 'checking' | 'running' | 'cancelling' | 'terminal'

export type ObservedWorkerTaskState = {
  lifecycle: ObservedWorkerTaskLifecycle
  operation: WorkerOperation
  progress: WorkerProgress
  overallPercent: number | null
  lastProgressAt: number
}

function finiteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function percent(value: unknown): number | null {
  const numeric = finiteNumber(value)
  return numeric === null ? null : Math.min(100, Math.max(0, numeric))
}

function maxTimestamp(...values: unknown[]): number {
  return Math.max(0, ...values.map(finiteNumber).filter((value): value is number => value !== null))
}

export function getForceCancelAvailability(
  status: WorkerOperation['status'],
  cancellingStartedAt: number | null | undefined,
  now: number = Date.now(),
): ForceCancelAvailability {
  const startedAt = finiteNumber(cancellingStartedAt)
  if (status !== 'cancelling' || startedAt === null) {
    return { remainingMs: null, visible: false }
  }

  const elapsedMs = Math.max(0, (finiteNumber(now) ?? startedAt) - startedAt)
  const remainingMs = Math.max(0, FORCE_CANCEL_DELAY_MS - elapsedMs)
  return { remainingMs, visible: remainingMs === 0 }
}

function lifecycleFromTaskState(state: OperationState): ObservedWorkerTaskLifecycle {
  if (state === 'idle' || state === 'queued') return 'checking'
  if (state === 'running') return 'running'
  if (state === 'cancelling') return 'cancelling'
  return 'terminal'
}

function operationStatusFromTaskState(state: OperationState): WorkerOperation['status'] {
  if (state === 'cancelling') return 'cancelling'
  if (state === 'succeeded') return 'succeeded'
  if (state === 'cancelled') return 'idle'
  if (state === 'failed' || state === 'interrupted') return 'failed'
  return 'running'
}

function taskProgress(
  task: TaskSnapshot,
  now: number,
): {
  progress: WorkerProgress
  overallPercent: number | null
} {
  const overallPercent = task.state === 'succeeded' ? 100 : percent(task.progress.overallPercent)
  const phasePercent = percent(task.progress.phasePercent)
  return {
    overallPercent,
    progress: {
      job_id: task.id,
      command: task.command,
      stage: task.progress.phase || task.state,
      stage_label: task.progress.phaseLabel,
      phase: task.progress.phase,
      percent: overallPercent ?? phasePercent ?? 0,
      indeterminate: overallPercent === null,
      message: task.progress.message,
      completed_batches: task.progress.completedBatches,
      total_batches: task.progress.totalBatches,
      elapsed_ms: Math.max(0, now - task.startedAt),
      last_progress_at_ms: task.progress.lastProgressAt,
    },
  }
}

function hasDifferentActiveJob(previous: ObservedWorkerTaskState | null | undefined, jobId: string): boolean {
  return Boolean(
    previous && previous.lifecycle !== 'terminal' && previous.operation.jobId && previous.operation.jobId !== jobId,
  )
}

export function reduceObservedWorkerTaskState(
  previous: ObservedWorkerTaskState | null | undefined,
  observation: WorkerJobObservation,
  now: number = Date.now(),
): ObservedWorkerTaskState {
  if (observation.type === 'started') {
    return {
      lifecycle: 'checking',
      operation: {
        status: 'running',
        command: observation.command,
        jobId: observation.job.job_id,
      },
      progress: {
        job_id: observation.job.job_id,
        command: observation.command,
        stage: 'checking',
        stage_label: '正在确认后台任务',
        phase: 'checking',
        percent: 0,
        indeterminate: true,
        message: '任务已开始，正在读取进度。',
        elapsed_ms: 0,
        last_progress_at_ms: now,
      },
      overallPercent: null,
      lastProgressAt: now,
    }
  }

  const jobId = observation.type === 'task' ? observation.task.id : observation.event.job_id
  if (hasDifferentActiveJob(previous, jobId)) return previous as ObservedWorkerTaskState

  if (observation.type === 'task') {
    const { task } = observation
    const projected = taskProgress(task, now)
    return {
      lifecycle: lifecycleFromTaskState(task.state),
      operation: {
        status: operationStatusFromTaskState(task.state),
        command: task.command,
        jobId: task.id,
      },
      progress: projected.progress,
      overallPercent: projected.overallPercent,
      lastProgressAt: maxTimestamp(
        previous?.operation.jobId === task.id ? previous.lastProgressAt : null,
        task.progress.lastProgressAt,
      ),
    }
  }

  const { event } = observation
  const previousForJob = previous?.operation.jobId === event.job_id ? previous : null
  const succeeded = event.ok && !event.cancelled
  const cancelled = Boolean(event.cancelled)
  const finishedAt = finiteNumber(event.finished_at_ms) ?? now
  const stage = event.stage || (cancelled ? 'cancelled' : succeeded ? 'done' : 'failed')
  const message = succeeded ? '任务已完成。' : event.error || (cancelled ? '任务已取消。' : '后台任务失败。')
  const overallPercent = succeeded ? 100 : (previousForJob?.overallPercent ?? null)

  return {
    lifecycle: 'terminal',
    operation: {
      status: succeeded ? 'succeeded' : cancelled ? 'idle' : 'failed',
      command: event.command,
      jobId: event.job_id,
    },
    progress: {
      ...(previousForJob?.progress ?? {}),
      job_id: event.job_id,
      command: event.command,
      stage,
      stage_label: cancelled ? '任务已取消' : succeeded ? '任务已完成' : '任务失败',
      phase: stage,
      percent: succeeded ? 100 : (previousForJob?.progress.percent ?? 0),
      indeterminate: overallPercent === null,
      message,
      last_progress_at_ms: maxTimestamp(previousForJob?.lastProgressAt, finishedAt),
    },
    overallPercent,
    lastProgressAt: maxTimestamp(previousForJob?.lastProgressAt, finishedAt),
  }
}
