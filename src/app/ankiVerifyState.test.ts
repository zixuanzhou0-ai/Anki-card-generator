import { describe, expect, it } from 'vitest'

import type { ExportResult } from '../domain/types'
import { compactExportResultForUi } from './exportResultState'
import {
  ankiVerificationPassed,
  ankiOpenImportRequestedStatusMessage,
  ankiOpenImportStartingStatusMessage,
  ankiVerifyStartingStatusMessage,
  ankiVerifyWorkerStartedMessage,
  buildAnkiMediaPreparationPayload,
  buildAnkiVerifyPayload,
  exportResultForAnkiVerify,
  hasCompleteAnkiWriteEvidence,
  prepareAnkiVerifyStart,
} from './ankiVerifyState'

const NOTE_TAGS = ['anki_card_generator_v14', 'English', 'B1', 'immersive_v11', 'phrase', 'repetition']

function exportResult(overrides: Partial<ExportResult> = {}): ExportResult {
  const result: ExportResult = {
    schema_version: 2,
    apkg_path: 'E:\\ANKI\\out\\deck.apkg',
    apkg_sha256: 'a'.repeat(64),
    apkg_size_bytes: 4096,
    apkg_mtime_ms: 1,
    media_dir: 'E:\\ANKI\\out\\media',
    cards: 2,
    segments: 2,
    deck_name: '视频语言卡 - smoke',
    deck_names: ['视频语言卡 - smoke'],
    deck_kind: 'video_language',
    model_name: 'Anki Card Generator V14 - 沉浸复读 V11',
    note_model_id: 3157735470,
    template_name: '沉浸复读 V11',
    template_family: 'language-immersive-v11',
    template_schema: 'V14',
    template_version: 'V14',
    compatibility_contract_version: 1,
    note_model_contract_digest: 'b'.repeat(64),
    anki_tag: 'anki_card_generator_v14',
    media_manifest: {},
    media_ledger: [],
    card_media_ledger: [
      {
        card_id: 'card-1',
        segment_id: 'segment-1',
        deck_name: '视频语言卡 - smoke',
        note_tags: NOTE_TAGS,
        note_content_sha256: 'c'.repeat(64),
      },
      {
        card_id: 'card-2',
        segment_id: 'segment-2',
        deck_name: '视频语言卡 - smoke',
        note_tags: NOTE_TAGS,
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
    media_summary: {
      video_segments: 0,
      video_files: 0,
      original_audio_files: 0,
      sentence_tts_files: 0,
      phrase_tts_files: 0,
      media_files: 0,
      media_bytes: 0,
      media_mb: 0,
      card_media_ledger_items: 2,
    },
    timing_ms: {},
    warnings: [],
    ...overrides,
  }
  if (!('card_media_ledger' in overrides) && result.deck_name !== '视频语言卡 - smoke') {
    result.card_media_ledger = result.card_media_ledger.map((item) => ({
      ...item,
      deck_name: result.deck_name,
    }))
  }
  return result
}

describe('exportResultForAnkiVerify', () => {
  it('returns the matching full export because it keeps audit data for verify', () => {
    const full = exportResult({
      audio_audit_items: [{ card_id: 'card-1' }],
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
      media_summary: {
        video_segments: 1,
        video_files: 1,
        original_audio_files: 0,
        sentence_tts_files: 0,
        phrase_tts_files: 0,
        media_files: 1,
        media_bytes: 12,
        media_mb: 0,
        card_media_ledger_items: 2,
      },
    })
    full.card_media_ledger[0] = {
      ...full.card_media_ledger[0],
      video_mp4: 'clip.mp4',
    }
    const compact = compactExportResultForUi(full)
    compact.apkg_path = 'e:/anki/out/deck.apkg'
    compact.media_dir = 'e:/anki/out/media/'

    expect(exportResultForAnkiVerify(full, compact)).toBe(full)
  })

  it('fails closed unless both the full and compact export results are present', () => {
    const full = exportResult()
    const compact = compactExportResultForUi(full)

    expect(exportResultForAnkiVerify(null, compact)).toBeNull()
    expect(exportResultForAnkiVerify(full, null)).toBeNull()
  })

  it('rejects stale or mismatched full and compact export identities', () => {
    const full = exportResult()
    const differentAnkiTag = exportResult({ anki_tag: 'anki_card_generator_v14_other' })
    differentAnkiTag.card_media_ledger = differentAnkiTag.card_media_ledger.map((item) => ({
      ...item,
      note_tags: ['anki_card_generator_v14_other', ...item.note_tags.slice(1)],
    }))
    const mismatchedCompacts = [
      exportResult({ apkg_path: 'E:\\ANKI\\out\\other.apkg' }),
      exportResult({ apkg_sha256: 'f'.repeat(64) }),
      exportResult({ apkg_size_bytes: 4097 }),
      exportResult({ apkg_mtime_ms: 2 }),
      exportResult({ media_dir: 'E:\\ANKI\\other-media' }),
      exportResult({ deck_name: 'other deck', deck_names: ['other deck'] }),
      exportResult({ deck_names: ['视频语言卡 - smoke', '视频语言卡 - smoke::child'] }),
      exportResult({ deck_kind: 'document_knowledge' }),
      exportResult({ note_model_id: 3157735471 }),
      exportResult({ note_model_contract_digest: 'f'.repeat(64) }),
      differentAnkiTag,
      exportResult({ source_fingerprint: 'source-b' }),
      exportResult({
        note_content_fingerprint: {
          schema_version: 1,
          algorithm: 'sha256',
          serialization: 'json-field-pairs-v1',
          field_names: ['CardId', 'English'],
          card_count: 2,
        },
      }),
    ]

    for (const compact of mismatchedCompacts) {
      expect(hasCompleteAnkiWriteEvidence(compact)).toBe(true)
      expect(exportResultForAnkiVerify(full, compact)).toBeNull()
    }
  })
})

describe('ankiVerificationPassed', () => {
  it('requires both ok and an empty failed-check list', () => {
    expect(ankiVerificationPassed({ ok: true, failed_checks: [] })).toBe(true)
    expect(ankiVerificationPassed({ ok: true, failed_checks: ['media_missing'] })).toBe(false)
    expect(ankiVerificationPassed({ ok: false, failed_checks: [] })).toBe(false)
    expect(ankiVerificationPassed(undefined)).toBe(false)
    expect(
      ankiVerificationPassed({ ok: true } as unknown as Parameters<typeof ankiVerificationPassed>[0]),
    ).toBe(false)
    expect(
      ankiVerificationPassed({ ok: true, failed_checks: null } as unknown as Parameters<
        typeof ankiVerificationPassed
      >[0]),
    ).toBe(false)
    expect(
      ankiVerificationPassed({ ok: true, failed_checks: '' } as unknown as Parameters<
        typeof ankiVerificationPassed
      >[0]),
    ).toBe(false)
  })
})

describe('prepareAnkiVerifyStart', () => {
  it('blocks while another worker task is active', () => {
    expect(
      prepareAnkiVerifyStart({
        workerBusy: true,
        exportResult: exportResult(),
        tauriRuntime: true,
      }),
    ).toEqual({ ok: false, statusMessage: '已有任务正在运行，请先取消或等待完成。' })
  })

  it('keeps the old silent no-op when no APKG path is available', () => {
    expect(
      prepareAnkiVerifyStart({
        workerBusy: false,
        exportResult: null,
        tauriRuntime: true,
      }),
    ).toEqual({ ok: false })
  })

  it('blocks browser preview because AnkiConnect requires the desktop runtime', () => {
    expect(
      prepareAnkiVerifyStart({
        workerBusy: false,
        exportResult: exportResult(),
        tauriRuntime: false,
      }),
    ).toEqual({ ok: false, statusMessage: '浏览器预览模式不能连接 AnkiConnect。' })
  })

  it('returns the export result when verify can start', () => {
    const result = exportResult()

    expect(
      prepareAnkiVerifyStart({
        workerBusy: false,
        exportResult: result,
        tauriRuntime: true,
      }),
    ).toEqual({ ok: true, exportResult: result })
  })

  it('requires a new export when restored write evidence is incomplete', () => {
    const legacy: Partial<ExportResult> = { ...exportResult() }
    delete legacy.note_model_contract_digest

    expect(
      prepareAnkiVerifyStart({
        workerBusy: false,
        exportResult: legacy as ExportResult,
        tauriRuntime: true,
      }),
    ).toEqual({
      ok: false,
      statusMessage: '这个 APKG 来自旧版本或恢复证据不完整，请重新导出后再导入 Anki。',
    })
  })

  it('rejects missing or internally inconsistent note content fingerprints', () => {
    const missing: Partial<ExportResult> = { ...exportResult() }
    delete missing.note_content_fingerprint
    const duplicateFields = exportResult({
      note_content_fingerprint: {
        schema_version: 1,
        algorithm: 'sha256',
        serialization: 'json-field-pairs-v1',
        field_names: ['CardId', 'CardId'],
        card_count: 2,
      },
    })
    const wrongCount = exportResult({
      note_content_fingerprint: {
        schema_version: 1,
        algorithm: 'sha256',
        serialization: 'json-field-pairs-v1',
        field_names: ['CardId'],
        card_count: 1,
      },
    })

    for (const candidate of [missing as ExportResult, duplicateFields, wrongCount]) {
      expect(
        prepareAnkiVerifyStart({ workerBusy: false, exportResult: candidate, tauriRuntime: true }),
      ).toEqual({
        ok: false,
        statusMessage: '这个 APKG 来自旧版本或恢复证据不完整，请重新导出后再导入 Anki。',
      })
    }
  })

  it('rejects incomplete media evidence before starting an Anki write task', () => {
    const invalidHash = exportResult({
      media_manifest: {
        'clip.mp4': { sha256: 'not-a-sha256', bytes: 12 },
      },
      media_ledger: [
        { file: 'clip.mp4', sha256: 'e'.repeat(64), bytes: 12 },
      ] as unknown as ExportResult['media_ledger'],
      media_summary: {
        video_segments: 1,
        video_files: 1,
        original_audio_files: 0,
        sentence_tts_files: 0,
        phrase_tts_files: 0,
        media_files: 1,
        media_bytes: 12,
        media_mb: 0,
        card_media_ledger_items: 2,
      },
    })
    const missingLedgerCoverage = exportResult({
      media_manifest: {
        'clip.mp4': { sha256: 'e'.repeat(64), bytes: 12 },
      },
      media_ledger: [],
      media_summary: {
        video_segments: 1,
        video_files: 1,
        original_audio_files: 0,
        sentence_tts_files: 0,
        phrase_tts_files: 0,
        media_files: 1,
        media_bytes: 12,
        media_mb: 0,
        card_media_ledger_items: 2,
      },
    })
    const unknownCardMedia = exportResult({
      card_media_ledger: [
        {
          card_id: 'card-1',
          segment_id: 'segment-1',
          deck_name: '视频语言卡 - smoke',
          note_tags: NOTE_TAGS,
          note_content_sha256: 'c'.repeat(64),
          original_audio: 'missing.mp3',
        },
        {
          card_id: 'card-2',
          segment_id: 'segment-2',
          deck_name: '视频语言卡 - smoke',
          note_tags: NOTE_TAGS,
          note_content_sha256: 'd'.repeat(64),
        },
      ],
    })

    for (const candidate of [invalidHash, missingLedgerCoverage, unknownCardMedia]) {
      expect(
        prepareAnkiVerifyStart({
          workerBusy: false,
          exportResult: candidate,
          tauriRuntime: true,
        }),
      ).toEqual({
        ok: false,
        statusMessage: '这个 APKG 来自旧版本或恢复证据不完整，请重新导出后再导入 Anki。',
      })
    }
  })

  it('fails closed without throwing for null or non-object nested evidence', () => {
    const malformed = [
      exportResult({ media_manifest: { 'clip.mp4': null } as unknown as ExportResult['media_manifest'] }),
      exportResult({ media_ledger: [null] as unknown as ExportResult['media_ledger'] }),
      exportResult({ card_media_ledger: [null] as unknown as ExportResult['card_media_ledger'] }),
      exportResult({ note_content_fingerprint: null as unknown as ExportResult['note_content_fingerprint'] }),
      exportResult({ media_summary: null as unknown as ExportResult['media_summary'] }),
      exportResult({
        card_media_ledger: [
          {
            card_id: 'card-1',
            segment_id: '',
            deck_name: '视频语言卡 - smoke',
            note_tags: NOTE_TAGS,
            note_content_sha256: 'c'.repeat(64),
          },
          {
            card_id: 'card-2',
            segment_id: 'segment-2',
            deck_name: '视频语言卡 - smoke',
            note_tags: NOTE_TAGS,
            note_content_sha256: 'd'.repeat(64),
          },
        ],
      }),
    ]

    for (const candidate of malformed) {
      expect(() => hasCompleteAnkiWriteEvidence(candidate)).not.toThrow()
      expect(hasCompleteAnkiWriteEvidence(candidate)).toBe(false)
    }
  })

  it('rejects Windows-unsafe media basenames and case-insensitive or NFC collisions', () => {
    const mediaSummary = (count: number, bytes: number): ExportResult['media_summary'] => ({
      video_segments: 0,
      video_files: count,
      original_audio_files: 0,
      sentence_tts_files: 0,
      phrase_tts_files: 0,
      media_files: count,
      media_bytes: bytes,
      media_mb: 0,
      card_media_ledger_items: 2,
    })
    const mediaEntry = {
      sha256: 'e'.repeat(64),
      bytes: 12,
      role: 'video' as const,
      segment_id: 'segment-1',
      card_id: '',
      field: 'Video',
    }
    const candidateWithNames = (names: string[]) => {
      const base = exportResult()
      return exportResult({
        media_manifest: Object.fromEntries(names.map((name) => [name, { ...mediaEntry }])),
        media_ledger: names.map((file) => ({
          file,
          role: 'video',
          segment_id: 'segment-1',
          card_id: '',
          field: 'Video',
          sha256: mediaEntry.sha256,
          bytes: mediaEntry.bytes,
        })),
        card_media_ledger: base.card_media_ledger.map((item, index) =>
          index === 0
            ? {
                ...item,
                video_mp4: names[0],
                ...(names[1] ? { video_webm: names[1] } : {}),
              }
            : item,
        ),
        media_summary: mediaSummary(names.length, names.length * 12),
      })
    }
    const candidates = [
      candidateWithNames(['../clip.mp4']),
      candidateWithNames(['CON.mp3']),
      candidateWithNames(['CLOCK$']),
      candidateWithNames(['CLOCK$.mp3']),
      candidateWithNames(['clip.mp4.']),
      candidateWithNames(['clip:alternate.mp4']),
      candidateWithNames(['cafe\u0301.mp3']),
      candidateWithNames(['café.mp3']),
      candidateWithNames(['straße.mp3']),
      candidateWithNames(['中文.mp3']),
      candidateWithNames(['Voice.mp3', 'voice.mp3']),
      candidateWithNames(['café.mp3', 'cafe\u0301.mp3']),
    ]

    expect(hasCompleteAnkiWriteEvidence(candidateWithNames(['STRASSE.mp3']))).toBe(true)
    for (const candidate of candidates) {
      expect(hasCompleteAnkiWriteEvidence(candidate)).toBe(false)
    }
  })

  it('rejects duplicate deck declarations and duplicate media ledger ownership', () => {
    const base = exportResult()
    const withMedia = exportResult({
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
      media_summary: {
        ...base.media_summary,
        video_segments: 1,
        video_files: 1,
        media_files: 1,
        media_bytes: 12,
      },
      card_media_ledger: base.card_media_ledger.map((item, index) =>
        index === 0 ? { ...item, video_mp4: 'clip.mp4' } : item,
      ),
    })
    expect(hasCompleteAnkiWriteEvidence(withMedia)).toBe(true)
    expect(
      hasCompleteAnkiWriteEvidence(
        exportResult({ deck_names: [...base.deck_names, ...base.deck_names] }),
      ),
    ).toBe(false)
    expect(
      hasCompleteAnkiWriteEvidence(
        { ...withMedia, media_ledger: [...withMedia.media_ledger, ...withMedia.media_ledger] },
      ),
    ).toBe(false)
  })

  it('accepts one shared phrase TTS file with distinct card ownership and rejects an exact duplicate', () => {
    const sharedPhraseTts = exportResult({
      media_manifest: {
        'phrase-shared.mp3': {
          sha256: 'e'.repeat(64),
          bytes: 12,
          role: 'phrase_tts',
          segment_id: 'segment-shared',
          card_id: 'card-1',
          field: 'PhraseTtsAudio',
        },
      },
      media_ledger: [
        {
          file: 'phrase-shared.mp3',
          role: 'phrase_tts',
          segment_id: 'segment-shared',
          card_id: 'card-1',
          field: 'PhraseTtsAudio',
          sha256: 'e'.repeat(64),
          bytes: 12,
        },
        {
          file: 'phrase-shared.mp3',
          role: 'phrase_tts',
          segment_id: 'segment-shared',
          card_id: 'card-2',
          field: 'PhraseTtsAudio',
          sha256: 'e'.repeat(64),
          bytes: 12,
        },
      ],
      card_media_ledger: exportResult().card_media_ledger.map((item) => ({
        ...item,
        segment_id: 'segment-shared',
        phrase_tts_audio: 'phrase-shared.mp3',
      })),
      media_summary: {
        video_segments: 0,
        video_files: 0,
        original_audio_files: 0,
        sentence_tts_files: 0,
        phrase_tts_files: 1,
        media_files: 1,
        media_bytes: 12,
        media_mb: 0,
        card_media_ledger_items: 2,
      },
    })

    expect(hasCompleteAnkiWriteEvidence(sharedPhraseTts)).toBe(true)
    expect(
      hasCompleteAnkiWriteEvidence({
        ...sharedPhraseTts,
        media_ledger: [...sharedPhraseTts.media_ledger, sharedPhraseTts.media_ledger[0]],
      }),
    ).toBe(false)
  })

  it('requires exactly six unique canonical note tags including the declared Anki tag', () => {
    const base = exportResult()
    const withFirstCardTags = (noteTags: unknown) =>
      exportResult({
        card_media_ledger: base.card_media_ledger.map((item, index) =>
          index === 0 ? { ...item, note_tags: noteTags } : item,
        ) as ExportResult['card_media_ledger'],
      })

    const invalid = [
      withFirstCardTags(NOTE_TAGS.slice(0, 5)),
      withFirstCardTags([...NOTE_TAGS.slice(0, 5), NOTE_TAGS[0]]),
      withFirstCardTags(['wrong_tag', ...NOTE_TAGS.slice(1)]),
      withFirstCardTags([...NOTE_TAGS.slice(0, 5), 'two words']),
      withFirstCardTags(null),
    ]

    for (const candidate of invalid) {
      expect(hasCompleteAnkiWriteEvidence(candidate)).toBe(false)
    }
  })

  it('requires manifest runtime ownership to match the card and media ledgers', () => {
    const base = exportResult()
    const validManifestEntry = {
      sha256: 'e'.repeat(64),
      bytes: 12,
      role: 'video' as const,
      segment_id: 'segment-1',
      card_id: '',
      field: 'Video',
    }
    const valid = exportResult({
      media_manifest: { 'clip.mp4': validManifestEntry },
      media_ledger: [
        {
          file: 'clip.mp4',
          ...validManifestEntry,
        },
      ],
      card_media_ledger: base.card_media_ledger.map((item, index) =>
        index === 0 ? { ...item, video_mp4: 'clip.mp4' } : item,
      ),
      media_summary: {
        ...base.media_summary,
        video_segments: 1,
        video_files: 1,
        media_files: 1,
        media_bytes: 12,
      },
    })
    const { role: _role, ...withoutRole } = validManifestEntry
    const invalidEntries = [
      withoutRole,
      { ...validManifestEntry, role: 'poster' },
      { ...validManifestEntry, segment_id: 'segment-2' },
      { ...validManifestEntry, card_id: 'card-1' },
      { ...validManifestEntry, field: 'Audio' },
    ]

    expect(hasCompleteAnkiWriteEvidence(valid)).toBe(true)
    for (const entry of invalidEntries) {
      expect(
        hasCompleteAnkiWriteEvidence({
          ...valid,
          media_manifest: { 'clip.mp4': entry },
        } as ExportResult),
      ).toBe(false)
    }
  })

  it('requires template identity, segment identity, and a card deck declared by deck_names', () => {
    const missingTemplate = exportResult({ template_name: '' })
    const missingSegment = exportResult({
      card_media_ledger: exportResult().card_media_ledger.map((item) => ({ ...item, segment_id: '' })),
    })
    const unknownDeck = exportResult({
      card_media_ledger: exportResult().card_media_ledger.map((item) => ({
        ...item,
        deck_name: 'Other deck',
      })),
    })

    expect(hasCompleteAnkiWriteEvidence(missingTemplate)).toBe(false)
    expect(hasCompleteAnkiWriteEvidence(missingSegment)).toBe(false)
    expect(hasCompleteAnkiWriteEvidence(unknownDeck)).toBe(false)
  })
})

describe('buildAnkiVerifyPayload', () => {
  it('keeps the APKG import flag explicit', () => {
    const result = exportResult({
      source_identity: { source_fingerprint: 'file:freshsource1234', source_mode: 'local_video' },
      source_fingerprint: 'file:freshsource1234',
    })

    expect(buildAnkiVerifyPayload(result)).toEqual({
      export_result: result,
      import_apkg: true,
      wait_for_anki_seconds: 30,
    })
  })

  it('builds a media-only preparation payload for the native Anki dialog', () => {
    const result = exportResult()

    expect(buildAnkiMediaPreparationPayload(result)).toEqual({
      export_result: result,
      import_apkg: false,
      prepare_media_only: true,
      wait_for_anki_seconds: 15,
    })
  })
})

describe('Anki verify copy', () => {
  it('keeps manual import and verify status copy stable', () => {
    expect(ankiVerifyStartingStatusMessage()).toBe('正在通过 AnkiConnect 导入当前 APKG，并核验卡片、媒体和音频取证。')
    expect(ankiVerifyWorkerStartedMessage()).toBe('Anki 导入与媒体核验已在后台运行。')
    expect(ankiOpenImportStartingStatusMessage()).toContain('安全预置')
    expect(ankiOpenImportRequestedStatusMessage()).toContain('媒体已安全准备')
  })
})
