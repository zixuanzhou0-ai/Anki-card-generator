import { describe, expect, it, vi } from 'vitest'

import { acknowledgeAppliedWorkerResults } from './workerResultAcknowledgement'

describe('acknowledgeAppliedWorkerResults', () => {
  it('persists the applied artifact checkpoint before acknowledging worker results', async () => {
    const order: string[] = []

    const outcome = await acknowledgeAppliedWorkerResults({
      jobIds: ['job-1', 'job-1', 'job-2'],
      persistCheckpoint: async () => {
        order.push('checkpoint')
      },
      acknowledge: async (jobId) => {
        order.push(`ack:${jobId}`)
        return { acknowledged: true, state: 'succeeded' }
      },
    })

    expect(order).toEqual(['checkpoint', 'ack:job-1', 'ack:job-2'])
    expect(outcome).toEqual({ consumedIds: ['job-1', 'job-2'], rejected: [], retryIds: [] })
  })

  it('does not acknowledge anything when the checkpoint cannot be persisted', async () => {
    const acknowledge = vi.fn()

    await expect(
      acknowledgeAppliedWorkerResults({
        jobIds: ['job-1'],
        persistCheckpoint: async () => {
          throw new Error('disk unavailable')
        },
        acknowledge,
      }),
    ).rejects.toThrow('disk unavailable')
    expect(acknowledge).not.toHaveBeenCalled()
  })

  it('keeps transient acknowledgement failures retryable without retrying completed acknowledgements', async () => {
    const outcome = await acknowledgeAppliedWorkerResults({
      jobIds: ['consumed', 'missing', 'retry'],
      persistCheckpoint: async () => undefined,
      acknowledge: async (jobId) => {
        if (jobId === 'consumed') return { acknowledged: true, state: 'succeeded' }
        if (jobId === 'missing') return { acknowledged: false, state: null }
        throw new Error('temporary filesystem failure')
      },
    })

    expect(outcome).toEqual({ consumedIds: ['consumed', 'missing'], rejected: [], retryIds: ['retry'] })
  })

  it('reports non-success terminal states as rejected instead of consuming their diagnostics', async () => {
    const outcome = await acknowledgeAppliedWorkerResults({
      jobIds: ['failed-job', 'running-job'],
      persistCheckpoint: async () => undefined,
      acknowledge: async (jobId) => ({
        acknowledged: false,
        state: jobId === 'failed-job' ? 'failed' : 'running',
      }),
    })

    expect(outcome).toEqual({
      consumedIds: [],
      rejected: [
        { jobId: 'failed-job', state: 'failed' },
        { jobId: 'running-job', state: 'running' },
      ],
      retryIds: [],
    })
  })
})
