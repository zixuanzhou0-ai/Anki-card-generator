import type { ExportResult } from '../domain/types'

export type AnkiVerifyStartPreparation =
  | {
      ok: true
      exportResult: ExportResult
    }
  | {
      ok: false
      statusMessage?: string
    }

export function exportResultForAnkiVerify(fullExport: ExportResult | null, compactExport: ExportResult | null) {
  if (!compactExport) return null
  return fullExport ?? compactExport
}

export function prepareAnkiVerifyStart({
  workerBusy,
  exportResult,
  tauriRuntime,
}: {
  workerBusy: boolean
  exportResult: ExportResult | null
  tauriRuntime: boolean
}): AnkiVerifyStartPreparation {
  if (workerBusy) {
    return { ok: false, statusMessage: '已有任务正在运行，请先取消或等待完成。' }
  }
  if (!exportResult?.apkg_path) {
    return { ok: false }
  }
  if (!tauriRuntime) {
    return { ok: false, statusMessage: '浏览器预览模式不能连接 AnkiConnect。' }
  }
  return { ok: true, exportResult }
}

export function buildAnkiVerifyPayload(exportResult: ExportResult) {
  return {
    export_result: exportResult,
    import_apkg: true,
  }
}

export function ankiVerifyStartingStatusMessage() {
  return '正在通过 AnkiConnect 导入当前 APKG，并核验卡片、媒体和音频取证。'
}

export function ankiVerifyWorkerStartedMessage() {
  return 'Anki 导入与媒体核验已在后台运行。'
}

export function ankiOpenImportStartingStatusMessage() {
  return '正在用 Anki 打开 APKG。'
}

export function ankiOpenImportRequestedStatusMessage() {
  return '已请求用 Anki 打开 APKG；如果没有弹出导入窗口，请在 Anki 里手动导入该 APKG，然后点击“核验媒体”。'
}
