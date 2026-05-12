import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { ExportResult } from '../../domain/types'
import { ExportResultPanel } from './ExportResultPanel'

const exportResult: ExportResult = {
  apkg_path: 'E:\\ANKI\\out\\deck.apkg',
  cards: 12,
  media_dir: 'E:\\ANKI\\out\\media',
  segments: 6,
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
        ankiVerifyResult={{ ok: true, message: 'ok', failed_checks: [], card_count: 12, media_count_checked: 12 }}
        lastExport={exportResult}
        onOpenAnkiImport={vi.fn()}
        onRevealExport={vi.fn()}
        onVerifyAnkiImport={vi.fn()}
      />,
    )

    expect(screen.getByText('已导出 12 张卡')).toBeInTheDocument()
    expect(screen.getByText('视频 6 段')).toBeInTheDocument()
    expect(screen.getByText('媒体一致')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /打开 Anki/ })).toBeEnabled()
  })
})
