import type { ExportResult } from '../domain/types'

export function compactExportResultForUi(result: ExportResult): ExportResult {
  const {
    audio_audit_items: _audioAuditItems,
    media_manifest: _mediaManifest,
    media_ledger: _mediaLedger,
    card_media_ledger: _cardMediaLedger,
    ...compact
  } = result
  return compact
}
