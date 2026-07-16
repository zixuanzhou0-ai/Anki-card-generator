import type { TaskSnapshot } from './workerTaskState'

const INTERRUPTED_RECOVERY_STATES = new Set<TaskSnapshot['state']>(['queued', 'running', 'cancelling', 'interrupted'])

export const RECOVERY_EVIDENCE_RETRY_BASE_MS = 1_000
export const RECOVERY_EVIDENCE_RETRY_MAX_MS = 30_000

export type RecoverableTaskSelectionInput = {
  checkpointTaskId?: string
  requestFingerprint: string
}

export type BoundWorkerTaskSelection =
  | { kind: 'recoverableInterrupted'; task: TaskSnapshot }
  | { kind: 'completedPendingConsumption'; task: TaskSnapshot }

export type RecoveryEvidenceRetryState = {
  attempt: number
  ready: boolean
  nextDelayMs: number | null
}

export function shouldRetryCheckpointWithBackup(
  candidate: 'primary' | 'backup',
  evidenceStatus: 'match' | 'changed' | 'unavailable',
): boolean {
  return candidate === 'primary' && evidenceStatus === 'changed'
}

export function isWorkflowRequestFingerprint(value: string): boolean {
  return /^request-v1-[0-9a-f]{8}$/u.test(value)
}

function newestTask(tasks: readonly TaskSnapshot[]): TaskSnapshot | null {
  return (
    [...tasks].sort((left, right) => {
      if (right.updatedAt !== left.updatedAt) return right.updatedAt - left.updatedAt
      return right.startedAt - left.startedAt
    })[0] ?? null
  )
}

function classifyBoundTask(task: TaskSnapshot | null): BoundWorkerTaskSelection | null {
  if (!task) return null
  if (INTERRUPTED_RECOVERY_STATES.has(task.state)) return { kind: 'recoverableInterrupted', task }
  if (task.state === 'succeeded') return { kind: 'completedPendingConsumption', task }
  return null
}

/**
 * A checkpoint-owned task id is the strongest binding. Without that id we only
 * accept the exact frontend request-v1 fingerprint; legacy summary hashes are
 * deliberately not comparable to sanitized workflow requests. Failed and
 * cancelled tasks are terminal history, while succeeded tasks still need their
 * durable result consumed exactly once after a renderer/app restart.
 */
export function selectBoundWorkerTask(
  tasks: readonly TaskSnapshot[],
  input: RecoverableTaskSelectionInput,
): BoundWorkerTaskSelection | null {
  const checkpointTaskId = input.checkpointTaskId?.trim()
  if (checkpointTaskId) {
    const byId = newestTask(tasks.filter((task) => task.id === checkpointTaskId))
    if (byId) return classifyBoundTask(byId)
  }

  if (!isWorkflowRequestFingerprint(input.requestFingerprint)) return null
  // A succeeded result may only be consumed through the exact task id that was
  // durably bound to the checkpoint. Falling back to the newest succeeded task
  // for the same request fingerprint would consume normal task history again on
  // every restart after the checkpoint has already advanced past that task.
  // Interrupted work can still be recovered by fingerprint because it has no
  // successful artifact to apply twice.
  const exactRequestTasks = tasks.filter(
    (task) => task.inputFingerprint === input.requestFingerprint && INTERRUPTED_RECOVERY_STATES.has(task.state),
  )
  return classifyBoundTask(newestTask(exactRequestTasks))
}

export function selectRecoverableWorkerTask(
  tasks: readonly TaskSnapshot[],
  input: RecoverableTaskSelectionInput,
): TaskSnapshot | null {
  const selection = selectBoundWorkerTask(tasks, input)
  return selection?.kind === 'recoverableInterrupted' ? selection.task : null
}

export function completedWorkerResultKind(
  command: TaskSnapshot['command'],
  result: unknown,
): 'workflowResult' | 'ankiMediaPreparation' {
  if (
    command === 'verify_anki_import' &&
    (!result || typeof result !== 'object' || !Array.isArray((result as { failed_checks?: unknown }).failed_checks))
  ) {
    return 'ankiMediaPreparation'
  }
  return 'workflowResult'
}
export function recoveryEvidenceRetryDelayMs(attempt: number): number {
  const safeAttempt = Math.max(0, Math.min(30, Math.floor(attempt)))
  return Math.min(RECOVERY_EVIDENCE_RETRY_MAX_MS, RECOVERY_EVIDENCE_RETRY_BASE_MS * 2 ** safeAttempt)
}

export function advanceRecoveryEvidenceRetry(
  state: RecoveryEvidenceRetryState,
  result: 'ready' | 'unavailable' | 'fatal',
): RecoveryEvidenceRetryState {
  if (result === 'ready') return { attempt: 0, ready: true, nextDelayMs: null }
  if (result === 'fatal') return { ...state, ready: false, nextDelayMs: null }
  return {
    attempt: state.attempt + 1,
    ready: false,
    nextDelayMs: recoveryEvidenceRetryDelayMs(state.attempt),
  }
}
