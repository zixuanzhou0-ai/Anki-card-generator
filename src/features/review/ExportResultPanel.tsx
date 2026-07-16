import { CheckCircle2, ChevronDown, Loader2, PlugZap } from 'lucide-react'

import type { AnkiVerifyResult, ExportResult } from '../../domain/types'
import { ankiVerificationPassed } from '../../app/ankiVerifyState'

type ExportResultPanelProps = {
  ankiVerifying: boolean
  ankiVerifyResult: AnkiVerifyResult | null
  lastExport: ExportResult
  onOpenAnkiImport?: () => void
  onRevealExport: () => void
  onVerifyAnkiImport: () => void
  showManualImportFallback?: boolean
  showPrimaryAction?: boolean
}

function hasVerifyEvidenceDetails(ankiVerifyResult: AnkiVerifyResult) {
  return Boolean(
    ankiVerifyResult.audio_audit_verify_path ||
    ankiVerifyResult.missing_media?.length ||
    ankiVerifyResult.audio_audit_mismatches?.length ||
    ankiVerifyResult.card_media_ledger_mismatches?.length ||
    ankiVerifyResult.media_ledger_card_text_mismatches?.length ||
    ankiVerifyResult.mismatched_media?.length,
  )
}

export function ExportResultPanel({
  ankiVerifying,
  ankiVerifyResult,
  lastExport,
  onOpenAnkiImport,
  onRevealExport,
  onVerifyAnkiImport,
  showManualImportFallback = false,
  showPrimaryAction = true,
}: ExportResultPanelProps) {
  const showExportEvidenceDetails = Boolean(
    lastExport.anki_manual_import_hint || lastExport.deck_name || lastExport.apkg_path || lastExport.audio_audit_path,
  )
  const showVerifyEvidenceDetails = ankiVerifyResult ? hasVerifyEvidenceDetails(ankiVerifyResult) : false

  const verificationPassed = ankiVerificationPassed(ankiVerifyResult)
  return (
    <div className="export-result">
      <div className="export-result-main">
        <div className="export-result-head">
          <span className="export-result-title">
            <CheckCircle2 size={18} />
            <span>
              <small>导出完成</small>
              <strong>已导出 {lastExport.cards} 张卡</strong>
            </span>
          </span>
          <div className="export-result-actions">
            <button className="ghost-button" type="button" onClick={onRevealExport}>
              定位文件
            </button>
            {showManualImportFallback && onOpenAnkiImport ? (
              <button className="ghost-button" type="button" onClick={onOpenAnkiImport} disabled={ankiVerifying}>
                使用 Anki 打开 APKG
              </button>
            ) : null}
            {showPrimaryAction ? (
              <button className="primary-button" type="button" onClick={onVerifyAnkiImport} disabled={ankiVerifying}>
                {ankiVerifying ? <Loader2 className="spin" size={18} /> : <PlugZap size={18} />}
                {ankiVerifying ? '正在导入并核验' : '导入 Anki 并核验'}
              </button>
            ) : null}
          </div>
        </div>
        {lastExport.media_summary ? (
          <div className="export-media-summary" aria-label="导出媒体统计">
            <span>视频 {lastExport.media_summary.video_segments} 段</span>
            <span>原声 {lastExport.media_summary.original_audio_files} 条</span>
            <span>整句 TTS 文件 {lastExport.media_summary.sentence_tts_files} 个</span>
            <span>表达 TTS 文件 {lastExport.media_summary.phrase_tts_files} 个</span>
            <span>{lastExport.media_summary.media_mb} MB</span>
          </div>
        ) : null}
        {lastExport.audio_audit_summary ? (
          <div className="export-media-summary" aria-label="音频取证统计">
            <span>
              音频取证 {lastExport.audio_audit_summary.items ?? 0}/{lastExport.audio_audit_summary.expected_items ?? 0}
            </span>
            <span>状态 {lastExport.audio_audit_summary.status ?? 'unknown'}</span>
          </div>
        ) : null}
        {lastExport.warnings?.length ? (
          <div className="export-warnings" aria-label="导出警告">
            {lastExport.warnings.map((warning) => (
              <span key={warning}>{warning}</span>
            ))}
          </div>
        ) : null}
        {showExportEvidenceDetails ? (
          <details className="compact-details export-evidence-details">
            <summary>
              <span>导出证据</span>
              <strong>APKG / audio_audit / 牌组路径</strong>
              <span className="details-affordance" aria-hidden="true">
                <ChevronDown size={14} />
              </span>
            </summary>
            <div className="export-paths" aria-label="导出文件路径">
              <span>
                <small>导入提示</small>
                <strong>
                  {lastExport.anki_manual_import_hint || '先用 Anki 打开 APKG；导入后回到这里核验本次牌组。'}
                </strong>
              </span>
              {lastExport.deck_name ? (
                <span title={lastExport.deck_name}>
                  <small>本次牌组名</small>
                  <strong>{lastExport.deck_name}</strong>
                </span>
              ) : null}
              <span title={lastExport.apkg_path}>
                <small>APKG</small>
                <strong>{lastExport.apkg_path}</strong>
              </span>
              {lastExport.audio_audit_path ? (
                <span title={lastExport.audio_audit_path}>
                  <small>audio_audit</small>
                  <strong>audio_audit：{lastExport.audio_audit_path}</strong>
                </span>
              ) : null}
            </div>
          </details>
        ) : null}
      </div>
      {ankiVerifyResult ? (
        <div className={`anki-verify-result ${verificationPassed ? 'ok' : 'warn'}`}>
          <strong>{verificationPassed ? '已在 Anki 中核验' : '已导入，但核验未通过'}</strong>
          <span>
            卡片 {ankiVerifyResult.card_count ?? 0}
            {ankiVerifyResult.expected_cards ? `/${ankiVerifyResult.expected_cards}` : ''} · 媒体{' '}
            {ankiVerifyResult.media_count_checked ?? 0}/{ankiVerifyResult.media_count_expected ?? 0}
          </span>
          {ankiVerifyResult.duplicate_imported_card_count ? (
            <small>
              同名 deck 中已有旧导入 {ankiVerifyResult.duplicate_imported_card_count} 张；本次只按 audio_audit
              匹配卡核验。
            </small>
          ) : null}
          {ankiVerifyResult.failed_checks?.length ? <small>{ankiVerifyResult.failed_checks.join(' / ')}</small> : null}
          {ankiVerifyResult.audio_audit_summary ? (
            <small>
              音频取证：{ankiVerifyResult.audio_audit_summary.items ?? 0}/
              {ankiVerifyResult.audio_audit_summary.expected_items ?? 0} · {ankiVerifyResult.audio_audit_summary.status}
            </small>
          ) : null}
          {showVerifyEvidenceDetails ? (
            <details className="compact-details export-evidence-details">
              <summary>
                <span>核验证据</span>
                <strong>audit 路径 / 缺失 / mismatch 样本</strong>
                <span className="details-affordance" aria-hidden="true">
                  <ChevronDown size={14} />
                </span>
              </summary>
              <div className="verify-evidence-list" aria-label="Anki 核验证据详情">
                {ankiVerifyResult.audio_audit_verify_path ? (
                  <small>verify audit：{ankiVerifyResult.audio_audit_verify_path}</small>
                ) : null}
                {ankiVerifyResult.missing_media?.length ? (
                  <small>缺失：{ankiVerifyResult.missing_media.slice(0, 3).join('、')}</small>
                ) : null}
                {ankiVerifyResult.audio_audit_mismatches?.length ? (
                  <small>
                    音频取证不一致：
                    {ankiVerifyResult.audio_audit_mismatches
                      .slice(0, 2)
                      .map((item) => `${String(item.card_id ?? '')}:${String(item.field ?? '')}`)
                      .join('、')}
                  </small>
                ) : null}
                {ankiVerifyResult.card_media_ledger_mismatches?.length ? (
                  <small>
                    卡片媒体绑定不一致：
                    {ankiVerifyResult.card_media_ledger_mismatches
                      .slice(0, 2)
                      .map((item) => `${item.card_id}:${item.field}`)
                      .join('、')}
                  </small>
                ) : null}
                {ankiVerifyResult.media_ledger_card_text_mismatches?.length ? (
                  <small>
                    TTS 文本台账不一致：
                    {ankiVerifyResult.media_ledger_card_text_mismatches
                      .slice(0, 2)
                      .map((item) => `${String(item.card_id ?? '')}:${String(item.field ?? '')}`)
                      .join('、')}
                  </small>
                ) : null}
                {ankiVerifyResult.mismatched_media?.length ? (
                  <small>
                    哈希不一致：
                    {ankiVerifyResult.mismatched_media
                      .slice(0, 3)
                      .map((item) => item.file)
                      .join('、')}
                  </small>
                ) : null}
              </div>
            </details>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
