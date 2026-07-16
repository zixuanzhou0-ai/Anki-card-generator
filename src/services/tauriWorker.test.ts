import { invoke } from '@tauri-apps/api/core'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  acknowledgeWorkerTaskResult,
  forceCancelWorkerJob,
  getWorkerTask,
  isWorkerJobCancelled,
  listRecoverableWorkerTasks,
  runWorkerJobAndWait,
  secretExists,
  startWorkerJob,
  WorkerJobError,
} from './tauriWorker'

vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn() }))

const invokeMock = vi.mocked(invoke)

describe('runWorkerJobAndWait', () => {
  beforeEach(() => {
    invokeMock.mockReset()
  })

  it('forwards an explicit workflow fingerprint and omits it for unbound tasks', async () => {
    invokeMock.mockResolvedValue({ job_id: 'extract-1' })

    await startWorkerJob('extract_learning_points', { source_mode: 'local' }, 'request-v1-12ab34cd')
    await startWorkerJob('check_env', {})

    expect(invokeMock).toHaveBeenNthCalledWith(1, 'start_worker_job', {
      command: 'extract_learning_points',
      payload: { source_mode: 'local' },
      inputFingerprint: 'request-v1-12ab34cd',
    })
    expect(invokeMock).toHaveBeenNthCalledWith(2, 'start_worker_job', {
      command: 'check_env',
      payload: {},
    })
  })
  it('polls a background worker without blocking the renderer', async () => {
    let polls = 0
    invokeMock.mockImplementation(async (command) => {
      if (command === 'start_worker_job') return { job_id: 'tts-1' }
      if (command === 'get_worker_job_status') {
        polls += 1
        return polls === 1 ? null : { job_id: 'tts-1', command: 'test_tts', ok: true, result: { ok: true } }
      }
      throw new Error(`unexpected command: ${command}`)
    })

    await expect(runWorkerJobAndWait('test_tts', {}, 0)).resolves.toEqual({ ok: true })
    expect(polls).toBe(2)
  })

  it('recovers from one transient task-status read failure without abandoning the running job', async () => {
    let statusPolls = 0
    invokeMock.mockImplementation(async (command) => {
      if (command === 'start_worker_job') return { job_id: 'transient-1' }
      if (command === 'get_worker_job_status') {
        statusPolls += 1
        if (statusPolls === 1) throw new Error('temporary IPC failure')
        return { job_id: 'transient-1', command: 'test_api', ok: true, result: { ok: true } }
      }
      throw new Error(`unexpected command: ${command}`)
    })

    await expect(runWorkerJobAndWait('test_api', {}, 0)).resolves.toEqual({ ok: true })
    expect(statusPolls).toBe(2)
  })

  it('keeps waiting for terminal status when supplementary task snapshots are unavailable', async () => {
    const observer = vi.fn()
    invokeMock.mockImplementation(async (command) => {
      if (command === 'start_worker_job') return { job_id: 'snapshot-offline-1' }
      if (command === 'get_worker_task') throw new Error('snapshot store temporarily unavailable')
      if (command === 'get_worker_job_status') {
        return { job_id: 'snapshot-offline-1', command: 'test_api', ok: true, result: { ok: true } }
      }
      throw new Error(`unexpected command: ${command}`)
    })

    await expect(runWorkerJobAndWait('test_api', {}, 0, observer)).resolves.toEqual({ ok: true })
    expect(observer.mock.calls.map(([observation]) => observation.type)).toEqual(['started', 'finished'])
  })

  it('surfaces a durable task-status read failure after bounded retries', async () => {
    let statusPolls = 0
    invokeMock.mockImplementation(async (command) => {
      if (command === 'start_worker_job') return { job_id: 'offline-1' }
      if (command === 'get_worker_job_status') {
        statusPolls += 1
        throw new Error('IPC offline')
      }
      throw new Error(`unexpected command: ${command}`)
    })

    const error = await runWorkerJobAndWait('test_tts', {}, 0).then(
      () => null,
      (caught: unknown) => caught,
    )

    expect(error).toBeInstanceOf(Error)
    expect((error as Error).message).toContain('连续 3 次')
    expect((error as Error & { cause?: unknown }).cause).toEqual(new Error('IPC offline'))
    expect(statusPolls).toBe(3)
  })

  it('observes the started job, task snapshots, and finished event in order', async () => {
    const runningTask = {
      schemaVersion: 1 as const,
      id: 'env-1',
      command: 'check_env' as const,
      state: 'running' as const,
      startedAt: 1_000,
      updatedAt: 2_000,
      progress: {
        phase: 'check',
        phaseLabel: '检查环境',
        phasePercent: 25,
        overallPercent: 25,
        message: '正在检查 FFmpeg',
        lastProgressAt: 2_000,
      },
      cancellable: true,
      inputFingerprint: 'env:test',
    }
    const succeededTask = {
      ...runningTask,
      state: 'succeeded' as const,
      updatedAt: 3_000,
      progress: { ...runningTask.progress, phasePercent: 100, overallPercent: 100 },
    }
    const finished = {
      job_id: 'env-1',
      command: 'check_env' as const,
      ok: true,
      result: { ok: true },
    }
    const observer = vi.fn()
    let taskPolls = 0

    invokeMock.mockImplementation(async (command) => {
      if (command === 'start_worker_job') return { job_id: 'env-1' }
      if (command === 'get_worker_task') {
        taskPolls += 1
        return taskPolls === 1 ? runningTask : succeededTask
      }
      if (command === 'get_worker_job_status') return taskPolls === 1 ? null : finished
      throw new Error(`unexpected command: ${command}`)
    })

    await expect(runWorkerJobAndWait('check_env', {}, 0, observer)).resolves.toEqual({ ok: true })
    expect(observer.mock.calls.map(([observation]) => observation.type)).toEqual([
      'started',
      'task',
      'task',
      'finished',
    ])
    expect(observer).toHaveBeenNthCalledWith(1, {
      type: 'started',
      job: { job_id: 'env-1' },
      command: 'check_env',
    })
    expect(observer).toHaveBeenNthCalledWith(2, { type: 'task', task: runningTask })
    expect(observer).toHaveBeenNthCalledWith(3, { type: 'task', task: succeededTask })
    expect(observer).toHaveBeenNthCalledWith(4, { type: 'finished', event: finished })
  })
  it('loads file-backed results and preserves worker failures', async () => {
    invokeMock
      .mockResolvedValueOnce({ job_id: 'api-1' })
      .mockResolvedValueOnce({
        job_id: 'api-1',
        command: 'test_api',
        ok: true,
        result_ref: 'worker-result.json',
      })
      .mockResolvedValueOnce({ ok: true, message: 'connected' })

    await expect(runWorkerJobAndWait('test_api', {}, 0)).resolves.toEqual({
      ok: true,
      message: 'connected',
    })

    invokeMock.mockResolvedValueOnce({ job_id: 'tts-2' }).mockResolvedValueOnce({
      job_id: 'tts-2',
      command: 'test_tts',
      ok: false,
      error: 'worker 超过 75 秒没有进度，已终止。',
    })

    await expect(runWorkerJobAndWait('test_tts', {}, 0)).rejects.toThrow('超过 75 秒')
  })
  it('preserves cancellation as a typed worker outcome instead of a generic failure', async () => {
    const cancelled = {
      job_id: 'api-cancelled',
      command: 'test_api' as const,
      ok: true,
      result: { should_not_be_returned: true },
      error_code: 'WORKER_CANCELLED',
      cancelled: true,
    }
    invokeMock.mockResolvedValueOnce({ job_id: cancelled.job_id }).mockResolvedValueOnce(cancelled)

    const error = await runWorkerJobAndWait('test_api', {}, 0).then(
      () => null,
      (caught: unknown) => caught,
    )

    expect(error).toBeInstanceOf(WorkerJobError)
    expect(isWorkerJobCancelled(error)).toBe(true)
    expect((error as WorkerJobError).event).toEqual(cancelled)
    expect((error as Error).message).toBe('任务已取消。')
  })

  it('keeps ordinary worker failures distinguishable from cancellation', async () => {
    invokeMock.mockResolvedValueOnce({ job_id: 'tts-failed' }).mockResolvedValueOnce({
      job_id: 'tts-failed',
      command: 'test_tts',
      ok: false,
      error: '语音服务不可用。',
      error_code: 'TTS_CONNECTION_FAILED',
      cancelled: false,
    })

    const error = await runWorkerJobAndWait('test_tts', {}, 0).then(
      () => null,
      (caught: unknown) => caught,
    )

    expect(error).toBeInstanceOf(WorkerJobError)
    expect(isWorkerJobCancelled(error)).toBe(false)
    expect((error as Error).message).toBe('语音服务不可用。')
  })

  it('queries running and recoverable task snapshots for event-loss polling', async () => {
    const runningTask = {
      schemaVersion: 1,
      id: 'extract-1',
      command: 'extract_learning_points',
      state: 'running',
      startedAt: 1_000,
      updatedAt: 2_000,
      progress: {
        phase: 'extract',
        phaseLabel: 'Extracting',
        phasePercent: 30,
        overallPercent: 30,
        message: 'Reading subtitles',
        lastProgressAt: 2_000,
      },
      cancellable: true,
      inputFingerprint: 'summary:test',
    }

    invokeMock.mockResolvedValueOnce(runningTask).mockResolvedValueOnce({ tasks: [runningTask], errors: [] })

    await expect(getWorkerTask('extract-1')).resolves.toEqual(runningTask)
    await expect(listRecoverableWorkerTasks()).resolves.toEqual({ tasks: [runningTask], errors: [] })
    expect(invokeMock).toHaveBeenNthCalledWith(1, 'get_worker_task', { jobId: 'extract-1' })
    expect(invokeMock).toHaveBeenNthCalledWith(2, 'list_recoverable_worker_tasks')
  })

  it('keeps legacy array responses compatible while the native task-list contract migrates', async () => {
    invokeMock.mockResolvedValueOnce([])

    await expect(listRecoverableWorkerTasks()).resolves.toEqual({ tasks: [], errors: [] })
  })
  it('acknowledges an applied successful result through a dedicated command', async () => {
    invokeMock.mockResolvedValueOnce({ acknowledged: true, state: 'succeeded' })

    await expect(acknowledgeWorkerTaskResult('export-1')).resolves.toEqual({
      acknowledged: true,
      state: 'succeeded',
    })
    expect(invokeMock).toHaveBeenCalledWith('acknowledge_worker_task_result', { jobId: 'export-1' })
  })
  it('forces a stuck task into an explicit terminal state', async () => {
    invokeMock.mockResolvedValueOnce({
      found: true,
      cancelled: true,
      state: 'cancelled',
    })

    await expect(forceCancelWorkerJob('generate-1')).resolves.toEqual({
      found: true,
      cancelled: true,
      state: 'cancelled',
    })
    expect(invokeMock).toHaveBeenCalledWith('force_cancel_worker_job', {
      jobId: 'generate-1',
    })
  })

  it('checks whether a secret exists without reading its value', async () => {
    ;(window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ = {}
    invokeMock.mockResolvedValueOnce(true)

    await expect(secretExists('profile:key')).resolves.toBe(true)
    expect(invokeMock).toHaveBeenCalledWith('secret_exists', { key: 'profile:key' })
    delete (window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__
  })
})
