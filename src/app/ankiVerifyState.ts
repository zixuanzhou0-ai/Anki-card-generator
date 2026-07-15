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

export function buildAnkiMediaPreparationPayload(exportResult: ExportResult) {
  return {
    export_result: exportResult,
    import_apkg: false,
    prepare_media_only: true,
    wait_for_anki_seconds: 15,
  }
}

export function ankiVerifyStartingStatusMessage() {
  return '正在通过 AnkiConnect 导入当前 APKG，并核验卡片、媒体和音频取证。'
}

export function ankiVerifyWorkerStartedMessage() {
  return 'Anki 导入与媒体核验已在后台运行。'
}

export function ankiOpenImportStartingStatusMessage() {
  return '正在启动 Anki，并安全预置本次 APKG 的媒体文件。'
}

export function ankiOpenImportRequestedStatusMessage() {
  return '媒体已安全准备，Anki 导入选项已打开；确认导入后可继续点击“导入并核验本次牌组”。'
}
