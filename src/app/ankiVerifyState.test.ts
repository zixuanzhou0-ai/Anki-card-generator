import { describe, expect, it } from 'vitest'

import type { ExportResult } from '../domain/types'
import {
  ankiVerificationPassed,
  ankiOpenImportRequestedStatusMessage,
  ankiOpenImportStartingStatusMessage,
  ankiVerifyStartingStatusMessage,
  ankiVerifyWorkerStartedMessage,
  buildAnkiMediaPreparationPayload,
  buildAnkiVerifyPayload,
  exportResultForAnkiVerify,
  prepareAnkiVerifyStart,
} from './ankiVerifyState'

function exportResult(overrides: Partial<ExportResult> = {}): ExportResult {
  return {
    apkg_path: 'E:\\ANKI\\out\\deck.apkg',
    media_dir: 'E:\\ANKI\\out\\media',
    cards: 2,
    segments: 2,
    deck_name: '视频语言卡 - smoke',
    ...overrides,
  }
}

describe('exportResultForAnkiVerify', () => {
  it('prefers the full export result because it keeps audit and manifest data for verify', () => {
    const compact = exportResult({ deck_name: 'compact' })
    const full = exportResult({
      deck_name: 'full',
      audio_audit_items: [{ card_id: 'card-1' }],
      media_manifest: { 'clip.mp4': { sha256: 'abc', bytes: 12 } },
    })

    expect(exportResultForAnkiVerify(full, compact)).toBe(full)
  })

  it('falls back to the compact export result when the full ref is absent', () => {
    const compact = exportResult({ deck_name: 'compact' })

    expect(exportResultForAnkiVerify(null, compact)).toBe(compact)
  })

  it('does not revive stale full export evidence after compact export state was cleared', () => {
    const full = exportResult({
      deck_name: 'stale full export',
      audio_audit_items: [{ card_id: 'old-card' }],
    })

    expect(exportResultForAnkiVerify(full, null)).toBeNull()
  })
})

describe('ankiVerificationPassed', () => {
  it('requires both ok and an empty failed-check list', () => {
    expect(ankiVerificationPassed({ ok: true, failed_checks: [] })).toBe(true)
    expect(ankiVerificationPassed({ ok: true, failed_checks: ['media_missing'] })).toBe(false)
    expect(ankiVerificationPassed({ ok: false, failed_checks: [] })).toBe(false)
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
