import type { WorkerFinishedEvent } from '../domain/types'

const ANKI_CONNECT_DISCONNECTED_MESSAGE =
  'AnkiConnect 未连接，已生成 APKG；请点击“用 Anki 打开 APKG”手动导入。手动导入后可重新启动 AnkiConnect，再点击“我已导入，核验本次牌组”。'

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
