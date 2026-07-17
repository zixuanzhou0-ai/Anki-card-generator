import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { ExportResult } from '../../domain/types'
import { ExportResultPanel } from './ExportResultPanel'

afterEach(() => {
  cleanup()
})

const REVIEW_MEDIA_FIXTURES = Array.from({ length: 12 }, (_, index) => {
  const role = index < 6 ? 'video' : index < 9 ? 'sentence_tts' : 'phrase_tts'
  const field = role === 'video' ? 'Video' : role === 'sentence_tts' ? 'TtsAudio' : 'PhraseTtsAudio'
  return {
    file: 'media-' + index + '.mp3',
    role,
    segment_id: 'segment-' + (index % 6),
    card_id: role === 'phrase_tts' ? 'card-' + index : '',
    field,
    sha256: String(index).padStart(64, '0'),
    bytes: index === 11 ? 89 : 85,
  }
})

const exportResult: ExportResult = {
  schema_version: 2,
  apkg_path: 'E:\\ANKI\\out\\deck.apkg',
  apkg_sha256: 'a'.repeat(64),
  apkg_size_bytes: 4096,
  apkg_mtime_ms: 1,
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
  deck_names: ['视频语言卡 - 字幕素材 - 20260615-120000'],
  deck_kind: 'video_language',
  model_name: 'Anki Card Generator V15 - 沉浸复读 V11',
  note_model_id: 1028904201,
  template_name: '沉浸复读 V11',
  template_family: 'language-immersive-v11',
  template_schema: 'V15',
  template_version: 'V15',
  compatibility_contract_version: 1,
  note_model_contract_digest: 'b'.repeat(64),
  anki_tag: 'anki_card_generator_v15',
  media_manifest: Object.fromEntries(
    REVIEW_MEDIA_FIXTURES.map(({ file, ...entry }) => [file, entry]),
  ),
  media_ledger: REVIEW_MEDIA_FIXTURES,
  card_media_ledger: Array.from({ length: 12 }, (_, index) => {
    const media = REVIEW_MEDIA_FIXTURES[index]
    return {
      card_id: 'card-' + index,
      segment_id: media.segment_id,
      deck_name: '视频语言卡 - 字幕素材 - 20260615-120000',
      note_tags: ['anki_card_generator_v15', 'English', 'B1', 'immersive_v11', 'phrase', 'repetition'],
      note_content_sha256: String(index + 20).padStart(64, '0'),
      ...(media.role === 'video'
        ? { video_mp4: media.file }
        : media.role === 'sentence_tts'
          ? { sentence_tts_audio: media.file }
          : { phrase_tts_audio: media.file }),
    }
  }),
  note_content_fingerprint: {
    schema_version: 1,
    algorithm: 'sha256',
    serialization: 'json-field-pairs-v1',
    field_names: ['CardId', 'Answer'],
    card_count: 12,
  },
  anki_manual_import_hint: '导入后请在 Anki 牌组列表打开「视频语言卡 - 字幕素材 - 20260615-120000」。',
  anki_verify_after_manual_import_supported: true,
  media_summary: {
    media_bytes: 1024,
    media_files: 12,
    media_mb: 1,
    original_audio_files: 0,
    phrase_tts_files: 3,
    sentence_tts_files: 3,
    video_files: 6,
    video_segments: 6,
    card_media_ledger_items: 12,
  },
  timing_ms: {},
  warnings: [],
}

describe('ExportResultPanel', () => {
  it('summarizes cards, media, and Anki verification', () => {
    const { container } = render(
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
        onRevealExport={vi.fn()}
        onVerifyAnkiImport={vi.fn()}
      />,
    )

    expect(screen.getByText('已导出 12 张卡')).toBeInTheDocument()
    expect(screen.getByText('视频 6 段')).toBeInTheDocument()
    expect(screen.getByText('音频取证 12/12')).toBeInTheDocument()
    expect(screen.getAllByText('已在 Anki 中核验').length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: /导入 Anki 并核验/ })).toBeEnabled()
    expect(container.querySelectorAll('[aria-live], [role="status"]')).toHaveLength(0)

    const exportDetails = screen.getByText('导出证据').closest('details')
    expect(exportDetails).toBeInstanceOf(HTMLDetailsElement)
    expect(exportDetails).not.toHaveAttribute('open')
    expect(within(exportDetails as HTMLElement).getByText('APKG / audio_audit / 牌组路径')).toBeInTheDocument()
    expect(within(exportDetails as HTMLElement).getByText('本次牌组名')).toBeInTheDocument()
    expect(
      within(exportDetails as HTMLElement).getByText('视频语言卡 - 字幕素材 - 20260615-120000'),
    ).toBeInTheDocument()
    expect(within(exportDetails as HTMLElement).getByText(/导入后请在 Anki 牌组列表打开/)).toBeInTheDocument()
    expect(within(exportDetails as HTMLElement).getByText(exportResult.apkg_path)).toBeInTheDocument()
    expect(
      within(exportDetails as HTMLElement).getByText('audio_audit：E:\\ANKI\\out\\audio_audit.json'),
    ).toBeInTheDocument()

    const verifyDetails = screen.getByText('核验证据').closest('details')
    expect(verifyDetails).toBeInstanceOf(HTMLDetailsElement)
    expect(verifyDetails).not.toHaveAttribute('open')
    expect(within(verifyDetails as HTMLElement).getByText('audit 路径 / 缺失 / mismatch 样本')).toBeInTheDocument()
    expect(
      within(verifyDetails as HTMLElement).getByText('verify audit：E:\\ANKI\\out\\audio_audit.verify.json'),
    ).toBeInTheDocument()
  })

  it('offers manual APKG opening as a secondary action without marking verification complete', () => {
    const onOpenAnkiImport = vi.fn()
    const onVerifyAnkiImport = vi.fn()
    const { container } = render(
      <ExportResultPanel
        ankiVerifying={false}
        ankiVerifyResult={null}
        lastExport={exportResult}
        onOpenAnkiImport={onOpenAnkiImport}
        onRevealExport={vi.fn()}
        onVerifyAnkiImport={onVerifyAnkiImport}
        showManualImportFallback
      />,
    )

    expect(container.querySelectorAll('.primary-button')).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: '使用 Anki 打开 APKG' }))

    expect(onOpenAnkiImport).toHaveBeenCalledOnce()
    expect(onVerifyAnkiImport).not.toHaveBeenCalled()
    expect(screen.queryByText('已在 Anki 中核验')).not.toBeInTheDocument()
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
        onRevealExport={vi.fn()}
        onVerifyAnkiImport={vi.fn()}
      />,
    )

    expect(screen.getAllByText('已在 Anki 中核验').length).toBeGreaterThan(0)
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
        onRevealExport={vi.fn()}
        onVerifyAnkiImport={vi.fn()}
      />,
    )

    expect(screen.getByText('已导入，但核验未通过')).toBeInTheDocument()
    expect(screen.getByText('missing_media / media_hash_mismatch')).toBeInTheDocument()

    const verifyDetails = screen.getByText('核验证据').closest('details')
    expect(verifyDetails).toBeInstanceOf(HTMLDetailsElement)
    expect(verifyDetails).not.toHaveAttribute('open')
    expect(within(verifyDetails as HTMLElement).getByText('缺失：clip-009.mp4')).toBeInTheDocument()
    expect(within(verifyDetails as HTMLElement).getByText('音频取证不一致：card-9:sentence_audio')).toBeInTheDocument()
    expect(
      within(verifyDetails as HTMLElement).getByText('卡片媒体绑定不一致：card-10:phrase_audio'),
    ).toBeInTheDocument()
    expect(
      within(verifyDetails as HTMLElement).getByText('TTS 文本台账不一致：card-11:PhraseTtsAudio'),
    ).toBeInTheDocument()
    expect(within(verifyDetails as HTMLElement).getByText('哈希不一致：sentence-011.mp3')).toBeInTheDocument()
  })
})
