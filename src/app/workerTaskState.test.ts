import { describe, expect, it } from 'vitest'

import {
  TASK_WAITING_AFTER_MS,
  TASK_WARNING_AFTER_MS,
  calculateBatchOverallPercent,
  canTransitionTaskState,
  createTaskSnapshot,
  getTaskActivityStatus,
  isTerminalTaskState,
  mergeTaskProgress,
  normalizeVisibleOverallPercent,
  mergeTaskSnapshot,
  shouldPollTask,
  transitionTaskState,
  type OperationState,
  type TaskProgress,
} from './workerTaskState'

const startedAt = 1_000_000

function progress(overrides: Partial<TaskProgress> = {}): TaskProgress {
  return {
    phase: 'generate',
    phaseLabel: '正在生成',
    phasePercent: 0,
    overallPercent: 0,
    message: '开始生成',
    lastProgressAt: startedAt,
    ...overrides,
  }
}

describe('workerTaskState', () => {
  it('allows forward lifecycle transitions and rejects terminal rewinds', () => {
    expect(canTransitionTaskState('idle', 'queued')).toBe(true)
    expect(canTransitionTaskState('queued', 'running')).toBe(true)
    expect(canTransitionTaskState('running', 'cancelling')).toBe(true)
    expect(canTransitionTaskState('cancelling', 'cancelled')).toBe(true)
    expect(canTransitionTaskState('queued', 'succeeded')).toBe(true)
    expect(canTransitionTaskState('succeeded', 'running')).toBe(false)
    expect(canTransitionTaskState('failed', 'queued')).toBe(false)
  })

  it.each<OperationState>(['succeeded', 'failed', 'cancelled', 'interrupted'])('recognizes %s as terminal', (state) => {
    expect(isTerminalTaskState(state)).toBe(true)
  })

  it('calculates aggregate progress across batches without showing 100 before success', () => {
    expect(calculateBatchOverallPercent({ completedBatches: 2, totalBatches: 5, phasePercent: 50 }, 'running')).toBe(50)
    expect(calculateBatchOverallPercent({ completedBatches: 5, totalBatches: 5, phasePercent: 100 }, 'running')).toBe(
      99,
    )
    expect(calculateBatchOverallPercent({ completedBatches: 5, totalBatches: 5, phasePercent: 100 }, 'succeeded')).toBe(
      100,
    )
    expect(calculateBatchOverallPercent({ completedBatches: 0, totalBatches: 0, phasePercent: 50 })).toBeNull()
  })

  it('keeps overall progress monotonic when a new phase resets its local percentage', () => {
    const current = progress({ phasePercent: 100, overallPercent: 62, completedBatches: 3, totalBatches: 5 })
    const next = mergeTaskProgress(
      current,
      {
        phase: 'audio',
        phaseLabel: '正在生成音频',
        phasePercent: 5,
        overallPercent: 40,
        message: '开始处理下一批音频',
      },
      'running',
      startedAt + 5_000,
    )

    expect(next.phasePercent).toBe(5)
    expect(next.overallPercent).toBe(62)
    expect(next.lastProgressAt).toBe(startedAt + 5_000)
  })

  it('uses batch data when no explicit overall percentage is provided', () => {
    const current = progress({ overallPercent: 20, completedBatches: 1, totalBatches: 4 })
    const next = mergeTaskProgress(
      current,
      { phasePercent: 50, completedBatches: 2, totalBatches: 4 },
      'running',
      startedAt + 1_000,
    )

    expect(next.overallPercent).toBe(62.5)
  })

  it('normalizes event and polling progress monotonically across item-weighted batches', () => {
    expect(
      normalizeVisibleOverallPercent({
        previousPercent: 60,
        phasePercent: 20,
        state: 'running',
      }),
    ).toBe(60)
    expect(
      normalizeVisibleOverallPercent({
        previousPercent: 98,
        phasePercent: 5,
        completedItems: 50,
        activeItems: 1,
        totalItems: 51,
        state: 'running',
      }),
    ).toBe(98.1)
  })

  it('caps stale 100 percent at 99 while a task is still active', () => {
    expect(
      normalizeVisibleOverallPercent({
        previousPercent: 100,
        phasePercent: 10,
        state: 'running',
      }),
    ).toBe(99)
    expect(
      normalizeVisibleOverallPercent({
        previousPercent: 99,
        phasePercent: 100,
        state: 'succeeded',
      }),
    ).toBe(100)
  })

  it('weights uneven batches by item count and never reaches 100 before success', () => {
    expect(
      normalizeVisibleOverallPercent({
        phasePercent: 100,
        completedItems: 0,
        activeItems: 50,
        totalItems: 51,
        state: 'running',
      }),
    ).toBe(98)
    expect(
      normalizeVisibleOverallPercent({
        previousPercent: 98,
        phasePercent: 50,
        completedItems: 50,
        activeItems: 1,
        totalItems: 51,
        state: 'running',
      }),
    ).toBe(99)
  })

  it('applies duplicate event and polling percentages idempotently', () => {
    const first = normalizeVisibleOverallPercent({
      previousPercent: 40,
      phasePercent: 50,
      state: 'running',
    })
    const duplicate = normalizeVisibleOverallPercent({
      previousPercent: first,
      phasePercent: 50,
      state: 'running',
    })
    expect(first).toBe(50)
    expect(duplicate).toBe(50)
  })

  it('does not refresh last activity time for an identical polling snapshot', () => {
    const current = progress({ phasePercent: 25, overallPercent: 25 })
    const next = mergeTaskProgress(
      current,
      { phasePercent: 25, overallPercent: 25, message: '开始生成' },
      'running',
      startedAt + 20_000,
    )

    expect(next.lastProgressAt).toBe(startedAt)
  })

  it('polls running and cancelling tasks but not queued or terminal tasks', () => {
    expect(shouldPollTask('running')).toBe(true)
    expect(shouldPollTask('cancelling')).toBe(true)
    expect(shouldPollTask('queued')).toBe(false)
    expect(shouldPollTask('succeeded')).toBe(false)
  })

  it('returns waiting and warning presentations at the documented inactivity thresholds', () => {
    const task = createTaskSnapshot({
      id: 'job-1',
      command: 'generate_cards_from_learning_points',
      inputFingerprint: 'input-1',
      state: 'running',
      now: startedAt,
    })

    expect(getTaskActivityStatus(task, startedAt + TASK_WAITING_AFTER_MS - 1).state).toBe('active')
    expect(getTaskActivityStatus(task, startedAt + TASK_WAITING_AFTER_MS)).toEqual({
      state: 'waiting',
      idleForMs: TASK_WAITING_AFTER_MS,
      message: '仍在等待当前服务',
    })
    expect(getTaskActivityStatus(task, startedAt + TASK_WARNING_AFTER_MS)).toEqual({
      state: 'warning',
      idleForMs: TASK_WARNING_AFTER_MS,
      message: '当前阶段已 30 秒没有新进度',
    })
  })

  it('applies polling updates idempotently and ignores stale same-state snapshots', () => {
    const current = createTaskSnapshot({
      id: 'job-1',
      command: 'generate',
      inputFingerprint: 'input-1',
      state: 'running',
      now: startedAt,
      progress: { overallPercent: 35, phasePercent: 35 },
    })
    const stale = mergeTaskSnapshot(current, {
      id: 'job-1',
      state: 'running',
      updatedAt: startedAt - 1,
      progress: { overallPercent: 10 },
    })
    const wrongTask = mergeTaskSnapshot(current, {
      id: 'job-2',
      state: 'succeeded',
      updatedAt: startedAt + 1,
    })

    expect(stale).toBe(current)
    expect(wrongTask).toBe(current)
  })

  it('makes terminal transitions complete and repeated terminal events idempotent', () => {
    const running = createTaskSnapshot({
      id: 'job-1',
      command: 'export',
      inputFingerprint: 'input-1',
      state: 'running',
      now: startedAt,
      progress: { overallPercent: 80 },
    })
    const succeeded = transitionTaskState(running, 'succeeded', startedAt + 10_000)
    const duplicate = mergeTaskSnapshot(succeeded, {
      id: 'job-1',
      state: 'succeeded',
      updatedAt: startedAt + 20_000,
    })
    const rewind = mergeTaskSnapshot(succeeded, {
      id: 'job-1',
      state: 'running',
      updatedAt: startedAt + 20_000,
    })

    expect(succeeded.progress.overallPercent).toBe(100)
    expect(duplicate).toBe(succeeded)
    expect(rewind).toBe(succeeded)
  })

  it('allows a terminal snapshot to be enriched once without changing its outcome', () => {
    const running = createTaskSnapshot({
      id: 'job-1',
      command: 'export',
      inputFingerprint: 'input-1',
      state: 'running',
      now: startedAt,
    })
    const succeeded = transitionTaskState(running, 'succeeded', startedAt + 1_000)
    const enriched = mergeTaskSnapshot(succeeded, {
      id: 'job-1',
      state: 'succeeded',
      resultRef: 'results/job-1.json',
    })
    const duplicate = mergeTaskSnapshot(enriched, {
      id: 'job-1',
      state: 'succeeded',
      resultRef: 'results/job-1.json',
    })

    expect(enriched.state).toBe('succeeded')
    expect(enriched.resultRef).toBe('results/job-1.json')
    expect(duplicate).toBe(enriched)
  })
})
