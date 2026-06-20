import { describe, expect, it, vi } from 'vitest'

import type { WorkerFinishedEvent } from '../domain/types'
import {
  fallbackWorkerOperationFromFinish,
  resolveWorkerFinishedResult,
  workerFinishInvalidatedByEditedRequest,
  workerFinishMatchesActiveJob,
} from './workerFinished'

describe('resolveWorkerFinishedResult', () => {
  it('reads a referenced result when a successful worker-finished event is lightweight', async () => {
    const readResult = vi.fn().mockResolvedValue({ learning_points: [{ id: 'lp-1' }] })
    const payload: WorkerFinishedEvent = {
      job_id: 'extract_learning_points-1',
      command: 'extract_learning_points',
      ok: true,
      cancelled: false,
      result_ref: 'extract_learning_points-1',
      result_size_bytes: 80000,
    }

    const resolved = await resolveWorkerFinishedResult(payload, readResult)

    expect(readResult).toHaveBeenCalledWith('extract_learning_points-1')
    expect(resolved.result).toEqual({ learning_points: [{ id: 'lp-1' }] })
  })

  it('does not read results for failed events or events that already include a result', async () => {
    const readResult = vi.fn()
    const failed: WorkerFinishedEvent = {
      job_id: 'extract_learning_points-2',
      command: 'extract_learning_points',
      ok: false,
      cancelled: false,
      result_ref: 'extract_learning_points-2',
      error: 'failed',
    }
    const inline: WorkerFinishedEvent = {
      job_id: 'export-1',
      command: 'export',
      ok: true,
      cancelled: false,
      result_ref: 'export-1',
      result: { cards: 1 },
    }

    await expect(resolveWorkerFinishedResult(failed, readResult)).resolves.toBe(failed)
    await expect(resolveWorkerFinishedResult(inline, readResult)).resolves.toBe(inline)
    expect(readResult).not.toHaveBeenCalled()
  })

  it('fails fast when a referenced result read never resolves', async () => {
    vi.useFakeTimers()
    const readResult = vi.fn().mockReturnValue(new Promise(() => {}))
    const payload: WorkerFinishedEvent = {
      job_id: 'extract_learning_points-stuck',
      command: 'extract_learning_points',
      ok: true,
      cancelled: false,
      result_ref: 'extract_learning_points-stuck',
    }

    const resolved = resolveWorkerFinishedResult(payload, readResult, 100)
    const assertion = expect(resolved).rejects.toThrow('后台任务结果读取超过')
    await vi.advanceTimersByTimeAsync(100)

    await assertion
    vi.useRealTimers()
  })
})

describe('worker finish matching', () => {
  const payload: WorkerFinishedEvent = {
    job_id: 'extract_learning_points-123',
    command: 'extract_learning_points',
    ok: true,
    cancelled: false,
  }

  it('accepts a finished job that matches the last progress event even when React state is stale', () => {
    expect(
      workerFinishMatchesActiveJob(payload, {
        refOperation: { status: 'idle' },
        stateOperation: { status: 'idle' },
        lastProgress: {
          job_id: 'extract_learning_points-123',
          command: 'extract_learning_points',
          stage: 'ai_review',
          percent: 53,
          message: 'AI 精筛已完成 2/19 批。',
        },
      }),
    ).toBe(true)
  })

  it('rejects completed jobs from a different run', () => {
    expect(
      workerFinishMatchesActiveJob(payload, {
        refOperation: { status: 'running', command: 'export', jobId: 'export-456' },
        stateOperation: { status: 'running', command: 'export', jobId: 'export-456' },
        lastProgress: {
          job_id: 'export-456',
          command: 'export',
          stage: 'pack',
          percent: 50,
          message: '正在导出。',
        },
      }),
    ).toBe(false)
  })

  it('builds a running operation from a recovered finish payload', () => {
    expect(fallbackWorkerOperationFromFinish(payload)).toEqual({
      status: 'running',
      command: 'extract_learning_points',
      jobId: 'extract_learning_points-123',
    })
  })

  it('marks successful request-bound artifacts stale when inputs changed during the run', () => {
    for (const command of [
      'extract_learning_points',
      'generate',
      'generate_cards_from_learning_points',
      'export',
      'verify_anki_import',
    ] as const) {
      expect(workerFinishInvalidatedByEditedRequest({ command, ok: true, cancelled: false }, true)).toBe(true)
    }

    expect(workerFinishInvalidatedByEditedRequest({ command: 'export', ok: true, cancelled: false }, false)).toBe(false)
    expect(workerFinishInvalidatedByEditedRequest({ command: 'export', ok: false, cancelled: false }, true)).toBe(false)
    expect(workerFinishInvalidatedByEditedRequest({ command: 'export', ok: true, cancelled: true }, true)).toBe(false)
  })
})
