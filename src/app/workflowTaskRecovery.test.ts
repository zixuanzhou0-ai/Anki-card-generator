import { describe, expect, it } from 'vitest'
import type { TaskSnapshot } from './workerTaskState'
import {
  RECOVERY_EVIDENCE_RETRY_MAX_MS,
  advanceRecoveryEvidenceRetry,
  completedWorkerResultKind,
  recoveryEvidenceRetryDelayMs,
  selectBoundWorkerTask,
  selectRecoverableWorkerTask,
  shouldRetryCheckpointWithBackup,
} from './workflowTaskRecovery'

function task(id: string, inputFingerprint: string, state: TaskSnapshot['state'], updatedAt: number): TaskSnapshot {
  return {
    schemaVersion: 1,
    id,
    command: 'extract_learning_points',
    state,
    startedAt: updatedAt - 100,
    updatedAt,
    progress: {
      phase: 'extract',
      phaseLabel: '正在分析',
      phasePercent: 20,
      overallPercent: 20,
      message: '处理中',
      lastProgressAt: updatedAt,
    },
    cancellable: state === 'running' || state === 'queued',
    inputFingerprint,
  }
}

describe('selectRecoverableWorkerTask', () => {
  const requestFingerprint = 'request-v1-12ab34cd'

  it('prefers the checkpoint task id and otherwise selects the newest exact request match', () => {
    const tasks = [
      task('by-request-new', requestFingerprint, 'interrupted', 4_000),
      task('checkpoint-job', 'summary-fnv1a64:legacy', 'interrupted', 2_000),
      task('by-request-old', requestFingerprint, 'running', 1_000),
    ]
    expect(selectRecoverableWorkerTask(tasks, { checkpointTaskId: 'checkpoint-job', requestFingerprint })?.id).toBe(
      'checkpoint-job',
    )
    expect(selectRecoverableWorkerTask(tasks, { requestFingerprint })?.id).toBe('by-request-new')
  })

  it('classifies an exactly bound success as pending result consumption, never as a rerun', () => {
    const succeeded = task('verify-1', requestFingerprint, 'succeeded', 5_000)
    const selection = selectBoundWorkerTask([succeeded], {
      checkpointTaskId: 'verify-1',
      requestFingerprint,
    })

    expect(selection).toEqual({ kind: 'completedPendingConsumption', task: succeeded })
    expect(selectRecoverableWorkerTask([succeeded], { checkpointTaskId: 'verify-1', requestFingerprint })).toBeNull()
  })

  it('never consumes succeeded task history without an exact checkpoint task id', () => {
    const succeeded = task('already-consumed', requestFingerprint, 'succeeded', 5_000)

    expect(selectBoundWorkerTask([succeeded], { requestFingerprint })).toBeNull()
    expect(
      selectBoundWorkerTask([succeeded], {
        checkpointTaskId: 'missing-task-id',
        requestFingerprint,
      }),
    ).toBeNull()
  })

  it('ignores terminal tasks, different requests, and legacy summary fingerprints', () => {
    const tasks = [
      task('terminal', requestFingerprint, 'failed', 9_000),
      task('other-request', 'request-v1-deadbeef', 'interrupted', 8_000),
      task('legacy', 'summary-fnv1a64:1234567890abcdef', 'interrupted', 7_000),
    ]
    expect(selectRecoverableWorkerTask(tasks, { requestFingerprint })).toBeNull()
    expect(
      selectRecoverableWorkerTask([task('legacy', 'summary-fnv1a64:1234567890abcdef', 'interrupted', 1_000)], {
        requestFingerprint: 'summary-fnv1a64:1234567890abcdef',
      }),
    ).toBeNull()
  })

  it('does not fall back to another request match when the checkpoint-owned task is terminal', () => {
    const tasks = [
      task('checkpoint-job', requestFingerprint, 'cancelled', 9_000),
      task('older-interrupted', requestFingerprint, 'interrupted', 8_000),
    ]
    expect(
      selectBoundWorkerTask(tasks, {
        checkpointTaskId: 'checkpoint-job',
        requestFingerprint,
      }),
    ).toBeNull()
  })

  it('allows every resumable lifecycle state and picks the newest duplicate snapshot', () => {
    const snapshots = [
      task('same', requestFingerprint, 'queued', 1_000),
      task('same', requestFingerprint, 'running', 2_000),
      task('same', requestFingerprint, 'cancelling', 3_000),
      task('same', requestFingerprint, 'interrupted', 4_000),
    ]
    expect(selectRecoverableWorkerTask(snapshots, { checkpointTaskId: 'same', requestFingerprint })?.state).toBe(
      'interrupted',
    )
  })
})

describe('completedWorkerResultKind', () => {
  it('keeps Anki media preparation separate from a completed import verification', () => {
    expect(completedWorkerResultKind('verify_anki_import', { ok: true, message: '媒体已预置' })).toBe(
      'ankiMediaPreparation',
    )
    expect(
      completedWorkerResultKind('verify_anki_import', {
        ok: true,
        message: '核验完成',
        failed_checks: [],
      }),
    ).toBe('workflowResult')
  })

  it('treats other completed workflow commands as consumable results', () => {
    expect(completedWorkerResultKind('export', { apkg_path: 'E:/cards.apkg' })).toBe('workflowResult')
  })
})

describe('recovery evidence retry policy', () => {
  it('moves from an initial unavailable check to ready without permanently disabling writes', () => {
    const initial = { attempt: 0, ready: false, nextDelayMs: null }
    const retrying = advanceRecoveryEvidenceRetry(initial, 'unavailable')
    expect(retrying).toEqual({ attempt: 1, ready: false, nextDelayMs: 1_000 })
    expect(advanceRecoveryEvidenceRetry(retrying, 'ready')).toEqual({ attempt: 0, ready: true, nextDelayMs: null })
  })

  it('uses capped exponential backoff and never schedules fatal evidence', () => {
    expect(recoveryEvidenceRetryDelayMs(0)).toBe(1_000)
    expect(recoveryEvidenceRetryDelayMs(3)).toBe(8_000)
    expect(recoveryEvidenceRetryDelayMs(20)).toBe(RECOVERY_EVIDENCE_RETRY_MAX_MS)
    expect(advanceRecoveryEvidenceRetry({ attempt: 2, ready: false, nextDelayMs: 2_000 }, 'fatal')).toEqual({
      attempt: 2,
      ready: false,
      nextDelayMs: null,
    })
  })
})

describe('shouldRetryCheckpointWithBackup', () => {
  it('tries the backup exactly for changed primary evidence', () => {
    expect(shouldRetryCheckpointWithBackup('primary', 'changed')).toBe(true)
    expect(shouldRetryCheckpointWithBackup('primary', 'match')).toBe(false)
    expect(shouldRetryCheckpointWithBackup('primary', 'unavailable')).toBe(false)
  })

  it('never loops after the backup candidate has been selected', () => {
    expect(shouldRetryCheckpointWithBackup('backup', 'changed')).toBe(false)
    expect(shouldRetryCheckpointWithBackup('backup', 'match')).toBe(false)
    expect(shouldRetryCheckpointWithBackup('backup', 'unavailable')).toBe(false)
  })
})
