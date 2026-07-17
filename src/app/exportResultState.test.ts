import { describe, expect, it } from 'vitest'
import type { ExportResult } from '../domain/types'
import { compactExportResultForUi } from './exportResultState'

describe('compactExportResultForUi', () => {
  it('keeps write-critical manifests while removing only bulky derived audit items', () => {
    const full: ExportResult = {
      schema_version: 2,
      apkg_path: 'E:\\ANKI\\out\\deck.apkg',
      apkg_sha256: 'a'.repeat(64),
      apkg_size_bytes: 4096,
      apkg_mtime_ms: 1,
      media_dir: 'E:\\ANKI\\out\\media',
      deck_name: '视频语言卡 - smoke',
      deck_names: ['视频语言卡 - smoke'],
      model_name: 'Anki Card Generator V15 - 沉浸复读 V11',
      note_model_id: 1028904201,
      template_name: '沉浸复读 V11',
      template_family: 'language-immersive-v11',
      template_schema: 'V15',
      template_version: 'V15',
      compatibility_contract_version: 1,
      note_model_contract_digest: 'b'.repeat(64),
      anki_tag: 'anki_card_generator_v15',
      audio_audit_path: 'E:\\ANKI\\out\\audio_audit.json',
      audio_audit_markdown_path: 'E:\\ANKI\\out\\audio_audit.md',
      audio_audit_summary: { status: 'passed', items: 2, expected_items: 2 },
      audio_audit_items: [{ card_id: 'c1' }, { card_id: 'c2' }],
      media_manifest: {
        'clip.mp4': {
          sha256: 'e'.repeat(64),
          bytes: 12,
          role: 'video',
          segment_id: 'segment-1',
          card_id: '',
          field: 'Video',
        },
      },
      media_ledger: [
        {
          file: 'clip.mp4',
          role: 'video',
          segment_id: 'segment-1',
          card_id: '',
          field: 'Video',
          sha256: 'e'.repeat(64),
          bytes: 12,
        },
      ],
      card_media_ledger: [
        {
          card_id: 'c1',
          segment_id: 'segment-1',
          deck_name: '视频语言卡 - smoke',
          note_tags: ['anki_card_generator_v15', 'English', 'B1', 'immersive_v11', 'phrase', 'repetition'],
          note_content_sha256: 'c'.repeat(64),
          video_mp4: 'clip.mp4',
        },
        {
          card_id: 'c2',
          segment_id: 'segment-2',
          deck_name: '视频语言卡 - smoke',
          note_tags: ['anki_card_generator_v15', 'English', 'B1', 'immersive_v11', 'phrase', 'repetition'],
          note_content_sha256: 'd'.repeat(64),
        },
      ],
      note_content_fingerprint: {
        schema_version: 1,
        algorithm: 'sha256',
        serialization: 'json-field-pairs-v1',
        field_names: ['CardId', 'Answer'],
        card_count: 2,
      },
      cards: 2,
      segments: 2,
      media_summary: {
        video_segments: 1,
        video_files: 1,
        original_audio_files: 0,
        sentence_tts_files: 0,
        phrase_tts_files: 0,
        media_files: 1,
        media_bytes: 12,
        media_mb: 0.1,
        card_media_ledger_items: 2,
      },
      timing_ms: {},
      warnings: [],
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
    expect(compact.media_manifest).toEqual(full.media_manifest)
    expect(compact.media_ledger).toEqual(full.media_ledger)
    expect(compact.card_media_ledger).toEqual(full.card_media_ledger)
    expect(compact.note_content_fingerprint).toEqual(full.note_content_fingerprint)
  })
})
