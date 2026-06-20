import { describe, expect, it } from 'vitest'
import type { ExportResult } from '../domain/types'
import { compactExportResultForUi } from './exportResultState'

describe('compactExportResultForUi', () => {
  it('keeps completion metadata while removing bulky audit and media arrays from React state', () => {
    const full: ExportResult = {
      apkg_path: 'E:\\ANKI\\out\\deck.apkg',
      media_dir: 'E:\\ANKI\\out\\media',
      deck_name: '视频语言卡 - smoke',
      audio_audit_path: 'E:\\ANKI\\out\\audio_audit.json',
      audio_audit_markdown_path: 'E:\\ANKI\\out\\audio_audit.md',
      audio_audit_summary: { status: 'passed', items: 2, expected_items: 2 },
      audio_audit_items: [{ card_id: 'c1' }, { card_id: 'c2' }],
      media_manifest: {
        'clip.mp4': { sha256: 'abc', bytes: 12 },
      },
      media_ledger: [{ file: 'sentence.mp3', role: 'sentence_tts', sha256: 'def', bytes: 34 }],
      card_media_ledger: [{ card_id: 'c1', video_mp4: 'clip.mp4' }],
      cards: 2,
      segments: 2,
      media_summary: {
        video_segments: 2,
        video_files: 4,
        original_audio_files: 2,
        sentence_tts_files: 2,
        phrase_tts_files: 2,
        media_files: 12,
        media_bytes: 1024,
        media_mb: 0.1,
      },
      deck_kind: 'video_language',
    }

    const compact = compactExportResultForUi(full)

    expect(compact.apkg_path).toBe(full.apkg_path)
    expect(compact.deck_name).toBe(full.deck_name)
    expect(compact.audio_audit_path).toBe(full.audio_audit_path)
    expect(compact.audio_audit_summary).toEqual(full.audio_audit_summary)
    expect(compact.media_summary).toEqual(full.media_summary)
    expect(compact.cards).toBe(2)
    expect(compact.audio_audit_items).toBeUndefined()
    expect(compact.media_manifest).toBeUndefined()
    expect(compact.media_ledger).toBeUndefined()
    expect(compact.card_media_ledger).toBeUndefined()
  })
})
