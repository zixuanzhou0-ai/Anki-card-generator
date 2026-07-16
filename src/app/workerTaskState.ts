import type { WorkerCommand } from '../domain/types'

export const TASK_WAITING_AFTER_MS = 15_000
export const TASK_WARNING_AFTER_MS = 30_000
export const MAX_ACTIVE_OVERALL_PERCENT = 99

export type OperationState =
  | 'idle'
  | 'queued'
  | 'running'
  | 'cancelling'
  | 'succeeded'
  | 'failed'
  | 'cancelled'
  | 'interrupted'

export type TaskFailure = {
  code: string
  message: string
  retryable: boolean
  phase?: string
  detail?: string
}

export type TaskProgress = {
  phase: string
  phaseLabel: string
  phasePercent: number | null
  overallPercent: number | null
  completedItems?: number
  totalItems?: number
  completedBatches?: number
  totalBatches?: number
  message: string
  lastProgressAt: number
}

export type TaskSnapshot = {
  schemaVersion: 1
  id: string
  command: WorkerCommand
  state: OperationState
  startedAt: number
  updatedAt: number
  progress: TaskProgress
  cancellable: boolean
  inputFingerprint: string
  resultRef?: string
  error?: TaskFailure
}

export type TaskSnapshotUpdate = Partial<
  Omit<TaskSnapshot, 'schemaVersion' | 'id' | 'command' | 'startedAt' | 'inputFingerprint' | 'progress'>
> & {
  schemaVersion?: 1
  id: string
  progress?: Partial<TaskProgress>
}

export type TaskActivityStatus = {
  state: 'inactive' | 'active' | 'waiting' | 'warning'
  idleForMs: number
  message: string | null
}

const ALLOWED_TRANSITIONS: Record<OperationState, ReadonlySet<OperationState>> = {
  idle: new Set(['queued', 'running']),
  queued: new Set(['running', 'cancelling', 'succeeded', 'failed', 'cancelled', 'interrupted']),
  running: new Set(['cancelling', 'succeeded', 'failed', 'cancelled', 'interrupted']),
  cancelling: new Set(['succeeded', 'failed', 'cancelled', 'interrupted']),
  succeeded: new Set(),
  failed: new Set(),
  cancelled: new Set(),
  interrupted: new Set(),
}

const TERMINAL_STATES = new Set<OperationState>(['succeeded', 'failed', 'cancelled', 'interrupted'])
const CONFIRMED_STOPPED_STATES = new Set<OperationState>(['succeeded', 'failed', 'cancelled'])
const POLLED_STATES = new Set<OperationState>(['running', 'cancelling'])

function hasOwn<T extends object>(value: T, key: PropertyKey): boolean {
  return Object.prototype.hasOwnProperty.call(value, key)
}

function finiteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function clampPercent(value: unknown): number | null {
  const number = finiteNumber(value)
  if (number === null) return null
  return Math.min(100, Math.max(0, number))
}

function normalizeCount(value: unknown): number | undefined {
  const number = finiteNumber(value)
  if (number === null) return undefined
  return Math.max(0, Math.floor(number))
}

function progressChanged(current: TaskProgress, next: TaskProgress): boolean {
  return (
    current.phase !== next.phase ||
    current.phaseLabel !== next.phaseLabel ||
    current.phasePercent !== next.phasePercent ||
    current.overallPercent !== next.overallPercent ||
    current.completedItems !== next.completedItems ||
    current.totalItems !== next.totalItems ||
    current.completedBatches !== next.completedBatches ||
    current.totalBatches !== next.totalBatches ||
    current.message !== next.message
  )
}

export function isTerminalTaskState(state: OperationState): boolean {
  return TERMINAL_STATES.has(state)
}

/**
 * States that prove the current worker process reached a terminal outcome.
 * `interrupted` is intentionally excluded: it describes recovery after an
 * unclean shutdown and is not proof that a live process stopped.
 */
export function isConfirmedStoppedTaskState(state: OperationState): boolean {
  return CONFIRMED_STOPPED_STATES.has(state)
}

export function canTransitionTaskState(from: OperationState, to: OperationState): boolean {
  return from === to || ALLOWED_TRANSITIONS[from].has(to)
}

export function shouldPollTask(task: Pick<TaskSnapshot, 'state'> | OperationState): boolean {
  return POLLED_STATES.has(typeof task === 'string' ? task : task.state)
}

export function calculateBatchOverallPercent(
  progress: Pick<TaskProgress, 'completedBatches' | 'totalBatches' | 'phasePercent'>,
  state: OperationState = 'running',
): number | null {
  if (state === 'succeeded') return 100

  const totalBatches = normalizeCount(progress.totalBatches)
  const completedBatches = normalizeCount(progress.completedBatches)
  if (!totalBatches || completedBatches === undefined) return null

  const currentBatchPercent = clampPercent(progress.phasePercent) ?? 0
  const completed = Math.min(completedBatches, totalBatches)
  const rawOverall = ((completed + currentBatchPercent / 100) / totalBatches) * 100
  const upperBound = shouldPollTask(state) || state === 'queued' ? MAX_ACTIVE_OVERALL_PERCENT : 100

  return Math.min(upperBound, Math.max(0, Math.round(rawOverall * 10) / 10))
}

export type VisibleOverallProgressInput = {
  phasePercent: number | null | undefined
  previousPercent?: number | null
  completedItems?: number
  totalItems?: number
  activeItems?: number
  state?: OperationState
}

/**
 * Converts per-worker progress into one monotonic workflow percentage. For
 * learning-point batches it weights by item count so a final one-card batch
 * cannot look as large as the preceding 50-card batch.
 */
export function normalizeVisibleOverallPercent(input: VisibleOverallProgressInput): number | null {
  const state = input.state ?? 'running'
  if (state === 'succeeded') return 100

  const phasePercent = clampPercent(input.phasePercent)
  const previousPercent = clampPercent(input.previousPercent)
  const completedItems = normalizeCount(input.completedItems)
  const totalItems = normalizeCount(input.totalItems)
  const activeItems = normalizeCount(input.activeItems)

  let candidate = phasePercent
  if (totalItems && completedItems !== undefined && activeItems !== undefined) {
    const completed = Math.min(totalItems, completedItems)
    const remaining = Math.max(0, totalItems - completed)
    const active = Math.min(remaining, activeItems)
    const weighted = ((completed + active * ((phasePercent ?? 0) / 100)) / totalItems) * 100
    candidate = Math.round(weighted * 10) / 10
  }

  if (candidate === null && previousPercent === null) return null
  const monotonic = Math.max(previousPercent ?? 0, candidate ?? 0)
  const upperBound = shouldPollTask(state) || state === 'queued' ? MAX_ACTIVE_OVERALL_PERCENT : 100
  return Math.min(upperBound, monotonic)
}

export function mergeTaskProgress(
  current: TaskProgress,
  update: Partial<TaskProgress>,
  state: OperationState,
  now: number = Date.now(),
): TaskProgress {
  const next: TaskProgress = {
    ...current,
    ...update,
    phasePercent: hasOwn(update, 'phasePercent') ? clampPercent(update.phasePercent) : current.phasePercent,
    overallPercent: current.overallPercent,
    completedItems: hasOwn(update, 'completedItems') ? normalizeCount(update.completedItems) : current.completedItems,
    totalItems: hasOwn(update, 'totalItems') ? normalizeCount(update.totalItems) : current.totalItems,
    completedBatches: hasOwn(update, 'completedBatches')
      ? normalizeCount(update.completedBatches)
      : current.completedBatches,
    totalBatches: hasOwn(update, 'totalBatches') ? normalizeCount(update.totalBatches) : current.totalBatches,
    lastProgressAt: current.lastProgressAt,
  }

  const explicitOverall = hasOwn(update, 'overallPercent') ? clampPercent(update.overallPercent) : null
  const batchOverall = calculateBatchOverallPercent(next, state)
  const candidateOverall = explicitOverall ?? batchOverall
  const previousOverall = clampPercent(current.overallPercent)

  if (state === 'succeeded') {
    next.overallPercent = 100
  } else if (candidateOverall !== null || previousOverall !== null) {
    const monotonicOverall = Math.max(previousOverall ?? 0, candidateOverall ?? 0)
    next.overallPercent =
      shouldPollTask(state) || state === 'queued'
        ? Math.min(MAX_ACTIVE_OVERALL_PERCENT, monotonicOverall)
        : monotonicOverall
  } else {
    next.overallPercent = null
  }

  const explicitActivityAt = finiteNumber(update.lastProgressAt)
  if (explicitActivityAt !== null && explicitActivityAt > current.lastProgressAt) {
    next.lastProgressAt = explicitActivityAt
  } else if (progressChanged(current, next)) {
    next.lastProgressAt = Math.max(current.lastProgressAt, now)
  }

  return next
}

export function transitionTaskState(
  task: TaskSnapshot,
  nextState: OperationState,
  at: number = Date.now(),
): TaskSnapshot {
  if (task.state === nextState || !canTransitionTaskState(task.state, nextState)) return task

  return {
    ...task,
    state: nextState,
    updatedAt: Math.max(task.updatedAt, at),
    progress: mergeTaskProgress(task.progress, {}, nextState, at),
  }
}

export function mergeTaskSnapshot(
  current: TaskSnapshot,
  update: TaskSnapshotUpdate,
  now: number = Date.now(),
): TaskSnapshot {
  if (update.id !== current.id || (update.schemaVersion !== undefined && update.schemaVersion !== 1)) {
    return current
  }

  const nextState = update.state ?? current.state
  if (!canTransitionTaskState(current.state, nextState)) return current

  if (isTerminalTaskState(current.state)) {
    if (nextState !== current.state) return current

    const resultRef = current.resultRef ?? update.resultRef
    const error = current.error ?? update.error
    if (resultRef === current.resultRef && error === current.error) return current
    return { ...current, resultRef, error }
  }

  const updateTimestamp = finiteNumber(update.updatedAt)
  if (nextState === current.state && updateTimestamp !== null && updateTimestamp < current.updatedAt) {
    return current
  }

  return {
    ...current,
    state: nextState,
    updatedAt: Math.max(current.updatedAt, updateTimestamp ?? now),
    progress: mergeTaskProgress(current.progress, update.progress ?? {}, nextState, now),
    cancellable: update.cancellable ?? current.cancellable,
    resultRef: update.resultRef ?? current.resultRef,
    error: update.error ?? current.error,
  }
}

export function getTaskActivityStatus(
  task: Pick<TaskSnapshot, 'state' | 'progress'>,
  now: number = Date.now(),
): TaskActivityStatus {
  if (!shouldPollTask(task.state)) {
    return { state: 'inactive', idleForMs: 0, message: null }
  }

  const idleForMs = Math.max(0, now - task.progress.lastProgressAt)
  if (idleForMs >= TASK_WARNING_AFTER_MS) {
    return {
      state: 'warning',
      idleForMs,
      message: `当前阶段已 ${Math.floor(idleForMs / 1_000)} 秒没有新进度`,
    }
  }

  if (idleForMs >= TASK_WAITING_AFTER_MS) {
    return { state: 'waiting', idleForMs, message: '仍在等待当前服务' }
  }

  return { state: 'active', idleForMs, message: null }
}

export function createTaskSnapshot(input: {
  id: string
  command: WorkerCommand
  inputFingerprint: string
  now?: number
  state?: Extract<OperationState, 'queued' | 'running'>
  cancellable?: boolean
  progress?: Partial<TaskProgress>
}): TaskSnapshot {
  const now = input.now ?? Date.now()
  const state = input.state ?? 'queued'
  const baseProgress: TaskProgress = {
    phase: 'queued',
    phaseLabel: '准备中',
    phasePercent: null,
    overallPercent: null,
    message: '任务已排队',
    lastProgressAt: now,
  }

  return {
    schemaVersion: 1,
    id: input.id,
    command: input.command,
    state,
    startedAt: now,
    updatedAt: now,
    progress: mergeTaskProgress(baseProgress, input.progress ?? {}, state, now),
    cancellable: input.cancellable ?? true,
    inputFingerprint: input.inputFingerprint,
  }
}
