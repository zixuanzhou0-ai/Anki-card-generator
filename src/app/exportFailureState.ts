import type { WorkerFinishedEvent } from '../domain/types'

const ANKI_CONNECT_DISCONNECTED_MESSAGE =
  'AnkiConnect 未连接，APKG 已安全保留。请先打开 Anki 并确认 AnkiConnect 可用，再重试“用 Anki 打开 APKG”；应用会先校验并预置媒体，避免 Anki 26.5 的媒体写入失败。'

export function clearStaleReviewWorkerError(error: WorkerFinishedEvent | null): WorkerFinishedEvent | null {
  if (!error) return null
  if (error.command === 'export' || error.command === 'verify_anki_import') return null
  return error
}

export function isAnkiConnectDisconnectedFailure(error: Pick<WorkerFinishedEvent, 'command' | 'error'>) {
  return error.command === 'verify_anki_import' && /(10061|connection refused|refused|AnkiConnect)/i.test(error.error || '')
}

export function workerFailureStatusMessage(
  error: WorkerFinishedEvent,
  {
    redactedError,
    detailsSummary = '',
    generationFailureRecoveryHint = '',
  }: {
    redactedError?: string
    detailsSummary?: string
    generationFailureRecoveryHint?: string
  } = {},
) {
  const fallbackError = redactedError || error.error || '任务失败。'
  const safeError = isAnkiConnectDisconnectedFailure(error) ? ANKI_CONNECT_DISCONNECTED_MESSAGE : fallbackError
  const structuredDetails = [
    error.error_code ? `错误码：${error.error_code}` : '',
    error.stage ? `阶段：${error.stage}` : '',
    error.fallbacks?.length ? `可尝试：${error.fallbacks.join(' / ')}` : '',
    detailsSummary,
  ]
    .filter(Boolean)
    .join('；')
  return `${safeError}${structuredDetails ? `\n${structuredDetails}` : ''}${
    generationFailureRecoveryHint ? `\n${generationFailureRecoveryHint}` : ''
  }`
}
