import '@testing-library/jest-dom/vitest'
import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { ExportResult } from '../../domain/types'
import { ExportResultPanel } from './ExportResultPanel'

afterEach(() => {
  cleanup()
})

const exportResult: ExportResult = {
  apkg_path: 'E:\\ANKI\\out\\deck.apkg',
  cards: 12,
  media_dir: 'E:\\ANKI\\out\\media',
  audio_audit_path: 'E:\\ANKI\\out\\audio_audit.json',
  audio_audit_summary: {
    status: 'passed',
    items: 12,
    expected_items: 12,
    passed: 24,
    failed: 0,
    manual_review_required: 0,
    mismatches: 0,
  },
  segments: 6,
  deck_name: '视频语言卡 - 字幕素材 - 20260615-120000',
  anki_manual_import_hint: '导入后请在 Anki 牌组列表打开「视频语言卡 - 字幕素材 - 20260615-120000」。',
  anki_verify_after_manual_import_supported: true,
  media_summary: {
    media_bytes: 1024,
    media_files: 12,
    media_mb: 1,
    original_audio_files: 6,
    phrase_tts_files: 3,
    sentence_tts_files: 3,
    video_files: 6,
    video_segments: 6,
  },
}

describe('ExportResultPanel', () => {
  it('summarizes cards, media, and Anki verification', () => {
    render(
      <ExportResultPanel
        ankiVerifying={false}
        ankiVerifyResult={{
          ok: true,
          message: 'ok',
          failed_checks: [],
          card_count: 12,
          media_count_checked: 12,
          audio_audit_verify_path: 'E:\\ANKI\\out\\audio_audit.verify.json',
          audio_audit_summary: {
            status: 'passed',
            items: 12,
            expected_items: 12,
            passed: 24,
            failed: 0,
            manual_review_required: 0,
            mismatches: 0,
          },
        }}
        lastExport={exportResult}
        onOpenAnkiImport={vi.fn()}
        onRevealExport={vi.fn()}
        onVerifyAnkiImport={vi.fn()}
      />,
    )

    expect(screen.getByText('已导出 12 张卡')).toBeInTheDocument()
    expect(screen.getByText('视频 6 段')).toBeInTheDocument()
    expect(screen.getByText('音频取证 12/12')).toBeInTheDocument()
    expect(screen.getAllByText('媒体一致').length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: /用 Anki 打开 APKG/ })).toBeEnabled()
    expect(screen.getByRole('button', { name: /导入并核验本次牌组/ })).toBeEnabled()

    const exportDetails = screen.getByText('导出证据').closest('details')
    expect(exportDetails).toBeInstanceOf(HTMLDetailsElement)
    expect(exportDetails).not.toHaveAttribute('open')
    expect(within(exportDetails as HTMLElement).getByText('APKG / audio_audit / 牌组路径')).toBeInTheDocument()
    expect(within(exportDetails as HTMLElement).getByText('本次牌组名')).toBeInTheDocument()
    expect(within(exportDetails as HTMLElement).getByText('视频语言卡 - 字幕素材 - 20260615-120000')).toBeInTheDocument()
    expect(within(exportDetails as HTMLElement).getByText(/导入后请在 Anki 牌组列表打开/)).toBeInTheDocument()
    expect(within(exportDetails as HTMLElement).getByText(exportResult.apkg_path)).toBeInTheDocument()
    expect(within(exportDetails as HTMLElement).getByText('audio_audit：E:\\ANKI\\out\\audio_audit.json')).toBeInTheDocument()

    const verifyDetails = screen.getByText('核验证据').closest('details')
    expect(verifyDetails).toBeInstanceOf(HTMLDetailsElement)
    expect(verifyDetails).not.toHaveAttribute('open')
    expect(within(verifyDetails as HTMLElement).getByText('audit 路径 / 缺失 / mismatch 样本')).toBeInTheDocument()
    expect(within(verifyDetails as HTMLElement).getByText('verify audit：E:\\ANKI\\out\\audio_audit.verify.json')).toBeInTheDocument()
  })

  it('explains duplicate previous imports without making media look broken', () => {
    render(
      <ExportResultPanel
        ankiVerifying={false}
        ankiVerifyResult={{
          ok: true,
          message: 'ok',
          failed_checks: [],
          card_count: 1,
          expected_cards: 1,
          imported_card_count: 2,
          duplicate_imported_card_count: 1,
          media_count_checked: 6,
          media_count_expected: 6,
        }}
        lastExport={{ ...exportResult, cards: 1 }}
        onOpenAnkiImport={vi.fn()}
        onRevealExport={vi.fn()}
        onVerifyAnkiImport={vi.fn()}
      />,
    )

    expect(screen.getAllByText('媒体一致').length).toBeGreaterThan(0)
    expect(screen.getByText('同名 deck 中已有旧导入 1 张；本次只按 audio_audit 匹配卡核验。')).toBeInTheDocument()
  })

  it('keeps failed verification checks visible while folding mismatch samples', () => {
    render(
      <ExportResultPanel
        ankiVerifying={false}
        ankiVerifyResult={{
          ok: false,
          message: 'media mismatch',
          failed_checks: ['missing_media', 'media_hash_mismatch'],
          card_count: 12,
          expected_cards: 12,
          media_count_checked: 11,
          media_count_expected: 12,
          missing_media: ['clip-009.mp4'],
          audio_audit_mismatches: [{ card_id: 'card-9', field: 'sentence_audio' }],
          card_media_ledger_mismatches: [
            {
              card_id: 'card-10',
              field: 'phrase_audio',
              expected: ['phrase-010.mp3'],
              actual: [],
              missing_expected: ['phrase-010.mp3'],
              unexpected_actual: [],
            },
          ],
          media_ledger_card_text_mismatches: [{ card_id: 'card-11', field: 'PhraseTtsAudio' }],
          mismatched_media: [{ file: 'sentence-011.mp3', expected_sha256: 'expected', actual_sha256: 'actual' }],
        }}
        lastExport={exportResult}
        onOpenAnkiImport={vi.fn()}
        onRevealExport={vi.fn()}
        onVerifyAnkiImport={vi.fn()}
      />,
    )

    expect(screen.getByText('需要检查媒体')).toBeInTheDocument()
    expect(screen.getByText('missing_media / media_hash_mismatch')).toBeInTheDocument()

    const verifyDetails = screen.getByText('核验证据').closest('details')
    expect(verifyDetails).toBeInstanceOf(HTMLDetailsElement)
    expect(verifyDetails).not.toHaveAttribute('open')
    expect(within(verifyDetails as HTMLElement).getByText('缺失：clip-009.mp4')).toBeInTheDocument()
    expect(within(verifyDetails as HTMLElement).getByText('音频取证不一致：card-9:sentence_audio')).toBeInTheDocument()
    expect(within(verifyDetails as HTMLElement).getByText('卡片媒体绑定不一致：card-10:phrase_audio')).toBeInTheDocument()
    expect(within(verifyDetails as HTMLElement).getByText('TTS 文本台账不一致：card-11:PhraseTtsAudio')).toBeInTheDocument()
    expect(within(verifyDetails as HTMLElement).getByText('哈希不一致：sentence-011.mp3')).toBeInTheDocument()
  })
})
