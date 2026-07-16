import { isTerminalTaskState, type TaskSnapshot } from './workerTaskState'

export const DEFAULT_WORKER_TERMINAL_POLL_MS = 250
export const DEFAULT_WORKER_TERMINAL_TIMEOUT_MS = 10_000
export const MIN_WORKER_TERMINAL_POLL_MS = 200
export const MAX_WORKER_TERMINAL_POLL_MS = 500

export type WaitForWorkerTerminalResult =
  | {
      kind: 'terminal'
      task: TaskSnapshot
      elapsedMs: number
    }
  | {
      kind: 'timeout'
      lastTask: TaskSnapshot
      elapsedMs: number
    }
  | {
      kind: 'missing'
      jobId: string
      elapsedMs: number
    }
  | {
      kind: 'error'
      jobId: string
      error: unknown
      elapsedMs: number
    }

export type WaitForWorkerTerminalOptions = {
  readTask: (jobId: string) => Promise<TaskSnapshot | null>
  sleep?: (delayMs: number) => Promise<void>
  now?: () => number
  pollIntervalMs?: number
  timeoutMs?: number
}

function defaultSleep(delayMs: number): Promise<void> {
  return new Promise((resolve) => globalThis.setTimeout(resolve, delayMs))
}

function finiteNonNegative(value: number | undefined, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : fallback
}

function normalizePollInterval(value: number | undefined): number {
  const interval = finiteNonNegative(value, DEFAULT_WORKER_TERMINAL_POLL_MS)
  return Math.min(MAX_WORKER_TERMINAL_POLL_MS, Math.max(MIN_WORKER_TERMINAL_POLL_MS, interval))
}

/**
 * Wait until a persisted Worker task reports a real terminal state.
 *
 * A missing task, a read failure, or a timeout is deliberately not treated as
 * safe completion. Callers can therefore keep the application open and offer
 * recovery instead of assuming that the Worker has stopped.
 */
export async function waitForWorkerTerminal(
  jobId: string,
  options: WaitForWorkerTerminalOptions,
): Promise<WaitForWorkerTerminalResult> {
  const now = options.now ?? Date.now
  const sleep = options.sleep ?? defaultSleep
  const pollIntervalMs = normalizePollInterval(options.pollIntervalMs)
  const timeoutMs = finiteNonNegative(options.timeoutMs, DEFAULT_WORKER_TERMINAL_TIMEOUT_MS)
  const startedAt = now()

  while (true) {
    let task: TaskSnapshot | null
    try {
      task = await options.readTask(jobId)
    } catch (error) {
      return {
        kind: 'error',
        jobId,
        error,
        elapsedMs: Math.max(0, now() - startedAt),
      }
    }

    const elapsedMs = Math.max(0, now() - startedAt)
    if (!task) {
      return { kind: 'missing', jobId, elapsedMs }
    }
    if (isTerminalTaskState(task.state)) {
      return { kind: 'terminal', task, elapsedMs }
    }
    if (elapsedMs >= timeoutMs) {
      return { kind: 'timeout', lastTask: task, elapsedMs }
    }

    await sleep(Math.min(pollIntervalMs, timeoutMs - elapsedMs))
  }
}
