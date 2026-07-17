import type { ExportResult } from '../domain/types'

export function compactExportResultForUi(result: ExportResult): ExportResult {
  const {
    audio_audit_items: _audioAuditItems,
    ...compact
  } = result
  return compact
}
