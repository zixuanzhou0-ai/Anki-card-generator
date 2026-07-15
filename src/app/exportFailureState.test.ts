import { describe, expect, it } from 'vitest'

import type { WorkerFinishedEvent } from '../domain/types'
import {
  clearStaleReviewWorkerError,
  isAnkiConnectDisconnectedFailure,
  workerFailureStatusMessage,
} from './exportFailureState'

function workerError(command: WorkerFinishedEvent['command']): WorkerFinishedEvent {
  return {
    job_id: `${command}-1`,
    command,
    ok: false,
    cancelled: false,
    error: 'previous failure',
  }
}

describe('clearStaleReviewWorkerError', () => {
  it('clears stale export and Anki verify errors after review selection changes', () => {
    expect(clearStaleReviewWorkerError(workerError('export'))).toBeNull()
    expect(clearStaleReviewWorkerError(workerError('verify_anki_import'))).toBeNull()
  })

  it('keeps generation errors that are still relevant to the current queue', () => {
    const error = workerError('generate_cards_from_learning_points')

    expect(clearStaleReviewWorkerError(error)).toBe(error)
  })
})

describe('workerFailureStatusMessage', () => {
  it('turns AnkiConnect connection failures into the manual import recovery path', () => {
    const error: WorkerFinishedEvent = {
      job_id: 'verify-1',
      command: 'verify_anki_import',
      ok: false,
      cancelled: false,
      error: 'HTTPConnectionPool(host="127.0.0.1", port=8765): connection refused 10061',
      error_code: 'ANKI_CONNECT_UNAVAILABLE',
      stage: 'anki_verify',
    }

    expect(isAnkiConnectDisconnectedFailure(error)).toBe(true)
    expect(workerFailureStatusMessage(error)).toContain('请先打开 Anki 并确认 AnkiConnect 可用')
    expect(workerFailureStatusMessage(error)).toContain('应用会先校验并预置媒体')
    expect(workerFailureStatusMessage(error)).toContain('错误码：ANKI_CONNECT_UNAVAILABLE')
    expect(workerFailureStatusMessage(error)).toContain('阶段：anki_verify')
  })

  it('keeps redacted worker errors and appends structured recovery details', () => {
    const error: WorkerFinishedEvent = {
      job_id: 'export-1',
      command: 'export',
      ok: false,
      cancelled: false,
      error: 'raw secret error',
      error_code: 'MISSING_TTS_MEDIA',
      stage: 'tts',
      fallbacks: ['重试失败 TTS', '检查语音配置'],
      details: { tts_failure_count: 2 },
    }

    expect(
      workerFailureStatusMessage(error, {
        redactedError: '2 条 TTS 生成失败，因此没有生成 APKG。',
        detailsSummary: '失败 TTS：2',
        generationFailureRecoveryHint: '已保留已完成的 12 个学习点。',
      }),
    ).toBe(
      [
        '2 条 TTS 生成失败，因此没有生成 APKG。',
        '错误码：MISSING_TTS_MEDIA；阶段：tts；可尝试：重试失败 TTS / 检查语音配置；失败 TTS：2',
        '已保留已完成的 12 个学习点。',
      ].join('\n'),
    )
  })
})
