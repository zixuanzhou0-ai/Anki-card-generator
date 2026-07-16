import { describe, expect, it, vi } from 'vitest'
import type { TaskSnapshot } from './workerTaskState'
import { DEFAULT_WORKER_TERMINAL_TIMEOUT_MS, waitForWorkerTerminal } from './waitForWorkerTerminal'

function task(state: TaskSnapshot['state'], updatedAt = 0): TaskSnapshot {
  return {
    schemaVersion: 1,
    id: 'worker-1',
    command: 'generate',
    state,
    startedAt: 0,
    updatedAt,
    progress: {
      phase: 'generate',
      phaseLabel: '正在生成',
      phasePercent: null,
      overallPercent: null,
      message: '处理中',
      lastProgressAt: updatedAt,
    },
    cancellable: state === 'running' || state === 'cancelling',
    inputFingerprint: 'request-v1-test',
  }
}

function fakeClock() {
  let current = 0
  return {
    now: () => current,
    sleep: vi.fn(async (delayMs: number) => {
      current += delayMs
    }),
  }
}

describe('waitForWorkerTerminal', () => {
  it('waits through cancelling and returns only after cancelled is observed', async () => {
    const clock = fakeClock()
    const readTask = vi
      .fn<(jobId: string) => Promise<TaskSnapshot | null>>()
      .mockResolvedValueOnce(task('cancelling'))
      .mockResolvedValueOnce(task('cancelled', 250))

    const result = await waitForWorkerTerminal('worker-1', {
      readTask,
      sleep: clock.sleep,
      now: clock.now,
    })

    expect(result).toEqual({ kind: 'terminal', task: task('cancelled', 250), elapsedMs: 250 })
    expect(readTask).toHaveBeenCalledTimes(2)
    expect(clock.sleep).toHaveBeenCalledWith(250)
  })

  it('times out instead of treating a continuously cancelling task as stopped', async () => {
    const clock = fakeClock()
    const readTask = vi.fn(async () => task('cancelling', clock.now()))

    const result = await waitForWorkerTerminal('worker-1', {
      readTask,
      sleep: clock.sleep,
      now: clock.now,
    })

    expect(result.kind).toBe('timeout')
    if (result.kind !== 'timeout') throw new Error('expected timeout')
    expect(result.elapsedMs).toBe(DEFAULT_WORKER_TERMINAL_TIMEOUT_MS)
    expect(result.lastTask.state).toBe('cancelling')
    expect(clock.sleep).toHaveBeenCalledTimes(DEFAULT_WORKER_TERMINAL_TIMEOUT_MS / 250)
  })

  it('returns a distinct error result when the task cannot be read', async () => {
    const failure = new Error('task store unavailable')
    const readTask = vi.fn(async () => {
      throw failure
    })

    await expect(waitForWorkerTerminal('worker-1', { readTask })).resolves.toEqual({
      kind: 'error',
      jobId: 'worker-1',
      error: failure,
      elapsedMs: expect.any(Number),
    })
  })

  it('returns missing and never reports a missing task as a safe terminal state', async () => {
    const readTask = vi.fn(async () => null)

    await expect(waitForWorkerTerminal('worker-missing', { readTask })).resolves.toEqual({
      kind: 'missing',
      jobId: 'worker-missing',
      elapsedMs: expect.any(Number),
    })
  })
})
