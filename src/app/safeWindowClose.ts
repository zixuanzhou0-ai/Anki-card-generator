import type { WaitForWorkerTerminalResult } from './waitForWorkerTerminal'
import { isConfirmedStoppedTaskState } from './workerTaskState'

export type SafeWindowCloseFailureReason =
  | 'cancel_failed'
  | 'terminal_timeout'
  | 'task_missing'
  | 'task_read_failed'
  | 'task_not_confirmed_stopped'
  | 'checkpoint_failed'
  | 'close_failed'

export type SafeWindowCloseResult =
  | { closed: true }
  | {
      closed: false
      reason: SafeWindowCloseFailureReason
      error?: unknown
      terminalResult?: Exclude<WaitForWorkerTerminalResult, { kind: 'terminal' }>
    }

export type SafeWindowCloseOptions = {
  jobId?: string | null
  requestCancel: (jobId: string) => Promise<unknown>
  waitForTerminal: (jobId: string) => Promise<WaitForWorkerTerminalResult>
  flushCheckpoint: () => Promise<void>
  closeWindow: () => Promise<void>
}

/**
 * Coordinates the irreversible part of closing the desktop application.
 *
 * A cancel request is only an acknowledgement. The window stays open until
 * the persisted task store proves a terminal state and the latest workflow
 * checkpoint has been durably flushed.
 */
export async function safelyCloseWindow(options: SafeWindowCloseOptions): Promise<SafeWindowCloseResult> {
  const jobId = options.jobId?.trim()
  if (jobId) {
    try {
      await options.requestCancel(jobId)
    } catch (error) {
      return { closed: false, reason: 'cancel_failed', error }
    }

    const terminalResult = await options.waitForTerminal(jobId)
    if (terminalResult.kind !== 'terminal') {
      const reason: SafeWindowCloseFailureReason =
        terminalResult.kind === 'timeout'
          ? 'terminal_timeout'
          : terminalResult.kind === 'missing'
            ? 'task_missing'
            : 'task_read_failed'
      return {
        closed: false,
        reason,
        terminalResult,
        ...(terminalResult.kind === 'error' ? { error: terminalResult.error } : {}),
      }
    }
    if (!isConfirmedStoppedTaskState(terminalResult.task.state)) {
      return {
        closed: false,
        reason: 'task_not_confirmed_stopped',
      }
    }
  }

  try {
    await options.flushCheckpoint()
  } catch (error) {
    return { closed: false, reason: 'checkpoint_failed', error }
  }

  try {
    await options.closeWindow()
  } catch (error) {
    return { closed: false, reason: 'close_failed', error }
  }

  return { closed: true }
}
