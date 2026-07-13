import { invoke } from '@tauri-apps/api/core'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { runWorkerJobAndWait } from './tauriWorker'

vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn() }))

const invokeMock = vi.mocked(invoke)

describe('runWorkerJobAndWait', () => {
  beforeEach(() => {
    invokeMock.mockReset()
  })

  it('polls a background worker without blocking the renderer', async () => {
    let polls = 0
    invokeMock.mockImplementation(async (command) => {
      if (command === 'start_worker_job') return { job_id: 'tts-1' }
      if (command === 'get_worker_job_status') {
        polls += 1
        return polls === 1
          ? null
          : { job_id: 'tts-1', command: 'test_tts', ok: true, result: { ok: true } }
      }
      throw new Error(`unexpected command: ${command}`)
    })

    await expect(runWorkerJobAndWait('test_tts', {}, 0)).resolves.toEqual({ ok: true })
    expect(polls).toBe(2)
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

    invokeMock
      .mockResolvedValueOnce({ job_id: 'tts-2' })
      .mockResolvedValueOnce({
        job_id: 'tts-2',
        command: 'test_tts',
        ok: false,
        error: 'worker 超过 75 秒没有进度，已终止。',
      })

    await expect(runWorkerJobAndWait('test_tts', {}, 0)).rejects.toThrow('超过 75 秒')
  })
})
