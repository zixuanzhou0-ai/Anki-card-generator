import { describe, expect, it } from 'vitest'
import type { WorkerJobObservation } from '../services/tauriWorker'
import {
  FORCE_CANCEL_DELAY_MS,
  getForceCancelAvailability,
  reduceObservedWorkerTaskState,
} from './observedWorkerTaskState'
import type { OperationState, TaskProgress, TaskSnapshot } from './workerTaskState'

function task(
  input: {
    id?: string
    state?: OperationState
    startedAt?: number
    updatedAt?: number
    progress?: Partial<TaskProgress>
  } = {},
): TaskSnapshot {
  const startedAt = input.startedAt ?? 1_000
  return {
    schemaVersion: 1,
    id: input.id ?? 'job-1',
    command: 'check_env',
    state: input.state ?? 'running',
    startedAt,
    updatedAt: input.updatedAt ?? startedAt,
    progress: {
      phase: 'check',
      phaseLabel: '检查环境',
      phasePercent: 10,
      overallPercent: 10,
      message: '正在检查环境',
      lastProgressAt: startedAt,
      ...input.progress,
    },
    cancellable: true,
    inputFingerprint: 'env:test',
  }
}

describe('reduceObservedWorkerTaskState', () => {
  it('maps a started observation to a visible checking state', () => {
    const state = reduceObservedWorkerTaskState(
      null,
      {
        type: 'started',
        job: { job_id: 'job-1' },
        command: 'check_env',
      },
      1_500,
    )

    expect(state.lifecycle).toBe('checking')
    expect(state.operation).toEqual({
      status: 'running',
      command: 'check_env',
      jobId: 'job-1',
    })
    expect(state.progress).toEqual(
      expect.objectContaining({
        job_id: 'job-1',
        command: 'check_env',
        stage: 'checking',
        percent: 0,
        indeterminate: true,
        last_progress_at_ms: 1_500,
      }),
    )
    expect(state.overallPercent).toBeNull()
    expect(state.lastProgressAt).toBe(1_500)
  })

  it('prefers an explicit overall percentage for a running task', () => {
    const state = reduceObservedWorkerTaskState(
      null,
      {
        type: 'task',
        task: task({
          startedAt: 1_000,
          progress: {
            phasePercent: 80,
            overallPercent: 37,
            lastProgressAt: 2_000,
            completedBatches: 1,
            totalBatches: 4,
          },
        }),
      },
      2_500,
    )

    expect(state.lifecycle).toBe('running')
    expect(state.operation.status).toBe('running')
    expect(state.progress.percent).toBe(37)
    expect(state.progress.indeterminate).toBe(false)
    expect(state.progress.completed_batches).toBe(1)
    expect(state.progress.total_batches).toBe(4)
    expect(state.progress.elapsed_ms).toBe(1_500)
    expect(state.overallPercent).toBe(37)
    expect(state.lastProgressAt).toBe(2_000)
    expect(state.progress.last_progress_at_ms).toBe(2_000)
  })

  it('retains an honest null overall percentage while exposing phase progress', () => {
    const started = reduceObservedWorkerTaskState(
      null,
      {
        type: 'started',
        job: { job_id: 'job-1' },
        command: 'check_env',
      },
      3_000,
    )
    const state = reduceObservedWorkerTaskState(
      started,
      {
        type: 'task',
        task: task({
          progress: {
            phasePercent: 42,
            overallPercent: null,
            lastProgressAt: 2_500,
          },
        }),
      },
      4_000,
    )

    expect(state.progress.percent).toBe(42)
    expect(state.progress.indeterminate).toBe(true)
    expect(state.overallPercent).toBeNull()
    expect(state.lastProgressAt).toBe(3_000)
  })

  it('maps cancelling without losing the active job identity', () => {
    const state = reduceObservedWorkerTaskState(
      null,
      {
        type: 'task',
        task: task({
          state: 'cancelling',
          progress: {
            phase: 'cancel',
            phaseLabel: '正在取消',
            message: '正在安全停止任务',
          },
        }),
      },
      2_000,
    )

    expect(state.lifecycle).toBe('cancelling')
    expect(state.operation).toEqual({
      status: 'cancelling',
      command: 'check_env',
      jobId: 'job-1',
    })
    expect(state.progress.stage).toBe('cancel')
  })

  it.each([
    ['succeeded', 'succeeded', 100],
    ['failed', 'failed', 35],
    ['interrupted', 'failed', 35],
    ['cancelled', 'idle', 35],
  ] as const)('maps %s snapshots to a terminal operation', (taskState, operationStatus, expectedPercent) => {
    const state = reduceObservedWorkerTaskState(
      null,
      {
        type: 'task',
        task: task({
          state: taskState,
          progress: {
            phasePercent: 35,
            overallPercent: taskState === 'succeeded' ? null : 35,
          },
        }),
      },
      2_000,
    )

    expect(state.lifecycle).toBe('terminal')
    expect(state.operation.status).toBe(operationStatus)
    expect(state.progress.percent).toBe(expectedPercent)
    expect(state.progress.indeterminate).toBe(false)
    expect(state.overallPercent).toBe(expectedPercent)
  })

  it('maps finished events and never rewinds last progress activity', () => {
    const running = reduceObservedWorkerTaskState(
      null,
      {
        type: 'task',
        task: task({
          progress: {
            phasePercent: 55,
            overallPercent: 55,
            lastProgressAt: 3_000,
          },
        }),
      },
      3_500,
    )
    const failed: WorkerJobObservation = {
      type: 'finished',
      event: {
        job_id: 'job-1',
        command: 'check_env',
        ok: false,
        error: 'FFmpeg 检查失败',
        finished_at_ms: 2_500,
      },
    }
    const state = reduceObservedWorkerTaskState(running, failed, 4_000)

    expect(state.lifecycle).toBe('terminal')
    expect(state.operation.status).toBe('failed')
    expect(state.progress.percent).toBe(55)
    expect(state.progress.message).toBe('FFmpeg 检查失败')
    expect(state.overallPercent).toBe(55)
    expect(state.lastProgressAt).toBe(3_000)
    expect(state.progress.last_progress_at_ms).toBe(3_000)

    const succeeded = reduceObservedWorkerTaskState(
      null,
      {
        type: 'finished',
        event: {
          job_id: 'job-2',
          command: 'repair_env',
          ok: true,
          finished_at_ms: 5_000,
        },
      },
      6_000,
    )
    expect(succeeded.operation.status).toBe('succeeded')
    expect(succeeded.progress.percent).toBe(100)
    expect(succeeded.overallPercent).toBe(100)
    expect(succeeded.lastProgressAt).toBe(5_000)
    expect(succeeded.progress.last_progress_at_ms).toBe(5_000)
  })

  it('ignores a stale observation while another job is active', () => {
    const active = reduceObservedWorkerTaskState(
      null,
      {
        type: 'started',
        job: { job_id: 'job-new' },
        command: 'repair_env',
      },
      1_000,
    )

    const state = reduceObservedWorkerTaskState(
      active,
      {
        type: 'task',
        task: task({ id: 'job-old' }),
      },
      2_000,
    )

    expect(state).toBe(active)
  })
})
describe('getForceCancelAvailability', () => {
  it('keeps force cancel hidden one millisecond before the delay', () => {
    expect(getForceCancelAvailability('cancelling', 1_000, 1_000 + 9_999)).toEqual({
      remainingMs: 1,
      visible: false,
    })
  })

  it('shows force cancel exactly at ten seconds', () => {
    expect(getForceCancelAvailability('cancelling', 1_000, 1_000 + FORCE_CANCEL_DELAY_MS)).toEqual({
      remainingMs: 0,
      visible: true,
    })
  })

  it('does not run a force-cancel countdown outside cancelling state', () => {
    expect(getForceCancelAvailability('running', 1_000, 20_000)).toEqual({
      remainingMs: null,
      visible: false,
    })
  })

  it('clamps elapsed time when the system clock moves backwards', () => {
    expect(getForceCancelAvailability('cancelling', 10_000, 9_000)).toEqual({
      remainingMs: FORCE_CANCEL_DELAY_MS,
      visible: false,
    })
  })
})
