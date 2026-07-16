import { describe, expect, it, vi } from 'vitest'
import type { TaskSnapshot } from './workerTaskState'
import type { WaitForWorkerTerminalResult } from './waitForWorkerTerminal'
import { safelyCloseWindow } from './safeWindowClose'

function terminalTask(state: Extract<TaskSnapshot['state'], 'succeeded' | 'failed' | 'cancelled'>): TaskSnapshot {
  return {
    schemaVersion: 1,
    id: 'job-1',
    command: 'generate',
    state,
    startedAt: 1,
    updatedAt: 2,
    progress: {
      phase: 'done',
      phaseLabel: '已完成',
      phasePercent: 100,
      overallPercent: 100,
      message: '已完成',
      lastProgressAt: 2,
    },
    cancellable: false,
    inputFingerprint: 'request-v1-12345678',
  }
}

function dependencies() {
  const order: string[] = []
  return {
    order,
    requestCancel: vi.fn(async () => {
      order.push('cancel')
    }),
    waitForTerminal: vi.fn<() => Promise<WaitForWorkerTerminalResult>>(async () => {
      order.push('terminal')
      return { kind: 'terminal' as const, task: terminalTask('cancelled'), elapsedMs: 250 }
    }),
    flushCheckpoint: vi.fn(async () => {
      order.push('checkpoint')
    }),
    closeWindow: vi.fn(async () => {
      order.push('close')
    }),
  }
}

describe('safelyCloseWindow', () => {
  it('waits for a real terminal state and a durable checkpoint before closing', async () => {
    const deps = dependencies()

    await expect(safelyCloseWindow({ jobId: 'job-1', ...deps })).resolves.toEqual({ closed: true })
    expect(deps.order).toEqual(['cancel', 'terminal', 'checkpoint', 'close'])
  })

  it.each([
    ['terminal_timeout', { kind: 'timeout' as const, lastTask: terminalTask('cancelled'), elapsedMs: 10_000 }],
    ['task_missing', { kind: 'missing' as const, jobId: 'job-1', elapsedMs: 1 }],
    ['task_read_failed', { kind: 'error' as const, jobId: 'job-1', error: new Error('read'), elapsedMs: 1 }],
  ])('keeps the window open for %s', async (reason, terminalResult) => {
    const deps = dependencies()
    deps.waitForTerminal.mockResolvedValue(terminalResult)

    const result = await safelyCloseWindow({ jobId: 'job-1', ...deps })

    expect(result).toMatchObject({ closed: false, reason })
    expect(deps.flushCheckpoint).not.toHaveBeenCalled()
    expect(deps.closeWindow).not.toHaveBeenCalled()
  })

  it('keeps the window open if the latest checkpoint cannot be flushed', async () => {
    const deps = dependencies()
    deps.flushCheckpoint.mockRejectedValue(new Error('disk full'))

    await expect(safelyCloseWindow({ jobId: null, ...deps })).resolves.toMatchObject({
      closed: false,
      reason: 'checkpoint_failed',
    })
    expect(deps.requestCancel).not.toHaveBeenCalled()
    expect(deps.closeWindow).not.toHaveBeenCalled()
  })

  it('does not treat an interrupted recovery marker as proof that the live process stopped', async () => {
    const deps = dependencies()
    deps.waitForTerminal.mockResolvedValue({
      kind: 'terminal',
      task: { ...terminalTask('cancelled'), state: 'interrupted' },
      elapsedMs: 250,
    })

    await expect(safelyCloseWindow({ jobId: 'job-1', ...deps })).resolves.toEqual({
      closed: false,
      reason: 'task_not_confirmed_stopped',
    })
    expect(deps.flushCheckpoint).not.toHaveBeenCalled()
    expect(deps.closeWindow).not.toHaveBeenCalled()
  })
})
