import { CheckCircle2, ExternalLink, Loader2, PlugZap } from 'lucide-react'

import type { AnkiVerifyResult, ExportResult } from '../../domain/types'

type ExportResultPanelProps = {
  ankiVerifying: boolean
  ankiVerifyResult: AnkiVerifyResult | null
  lastExport: ExportResult
  onOpenAnkiImport: () => void
  onRevealExport: () => void
  onVerifyAnkiImport: () => void
}

export function ExportResultPanel({
  ankiVerifying,
  ankiVerifyResult,
  lastExport,
  onOpenAnkiImport,
  onRevealExport,
  onVerifyAnkiImport,
}: ExportResultPanelProps) {
  return (
    <div className="export-result" role="status">
      <CheckCircle2 size={18} />
      <div>
        <strong>已导出 {lastExport.cards} 张卡</strong>
        {lastExport.media_summary ? (
          <div className="export-media-summary" aria-label="导出媒体统计">
            <span>视频 {lastExport.media_summary.video_segments} 段</span>
            <span>原声 {lastExport.media_summary.original_audio_files} 条</span>
            <span>整句 TTS {lastExport.media_summary.sentence_tts_files} 条</span>
            <span>词伙 TTS {lastExport.media_summary.phrase_tts_files} 条</span>
            <span>{lastExport.media_summary.media_mb} MB</span>
          </div>
        ) : null}
        {lastExport.warnings?.length ? (
          <div className="export-warnings" aria-label="导出警告">
            {lastExport.warnings.map((warning) => (
              <span key={warning}>{warning}</span>
            ))}
          </div>
        ) : null}
        <span>{lastExport.apkg_path}</span>
      </div>
      <button className="ghost-button" type="button" onClick={onRevealExport}>
        定位文件
      </button>
      <button className="primary-button" type="button" onClick={onOpenAnkiImport}>
        <ExternalLink size={18} />
        打开 Anki
      </button>
      <button className="ghost-button" type="button" onClick={onVerifyAnkiImport} disabled={ankiVerifying}>
        {ankiVerifying ? <Loader2 className="spin" size={18} /> : <PlugZap size={18} />}
        核验媒体
      </button>
      {ankiVerifyResult ? (
        <div className={`anki-verify-result ${ankiVerifyResult.ok ? 'ok' : 'warn'}`}>
          <strong>{ankiVerifyResult.ok ? '媒体一致' : '需要检查媒体'}</strong>
          <span>
            卡片 {ankiVerifyResult.card_count ?? 0}
            {ankiVerifyResult.expected_cards ? `/${ankiVerifyResult.expected_cards}` : ''} · 媒体{' '}
            {ankiVerifyResult.media_count_checked ?? 0}/{ankiVerifyResult.media_count_expected ?? 0}
          </span>
          {ankiVerifyResult.failed_checks?.length ? <small>{ankiVerifyResult.failed_checks.join(' / ')}</small> : null}
          {ankiVerifyResult.missing_media?.length ? (
            <small>缺失：{ankiVerifyResult.missing_media.slice(0, 3).join('、')}</small>
          ) : null}
          {ankiVerifyResult.mismatched_media?.length ? (
            <small>
              哈希不一致：{ankiVerifyResult.mismatched_media.slice(0, 3).map((item) => item.file).join('、')}
            </small>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
