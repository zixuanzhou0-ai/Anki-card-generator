import '@testing-library/jest-dom/vitest'
import type { ComponentProps } from 'react'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { GenerateRequest } from '../../domain/types'
import { defaultRequest } from '../../domain/options'
import { SourceSetupPanel } from './SourceSetupPanel'

afterEach(() => cleanup())

const request: GenerateRequest = {
  ...defaultRequest,
  max_segments: 35,
  source_mode: 'local',
  source_url: '',
  subtitle_path: '',
  title: '',
  url_auto_subtitle_fallback: true,
  url_import_mode: 'video',
  video_path: '',
}

function renderPanel(overrides: Partial<ComponentProps<typeof SourceSetupPanel>> = {}) {
  const props: ComponentProps<typeof SourceSetupPanel> = {
    request,
    onPatchRequest: vi.fn(),
    onSelectPath: vi.fn(),
    onSelectSourceMode: vi.fn(),
    ...overrides,
  }
  render(<SourceSetupPanel {...props} />)
  return props
}

describe('SourceSetupPanel', () => {
  it('renders local video fields and source mode actions', () => {
    const props = renderPanel()

    fireEvent.click(screen.getByRole('button', { name: /视频链接/ }))
    fireEvent.click(screen.getByRole('button', { name: '选择视频文件' }))

    expect(screen.getByPlaceholderText('选择本地视频')).toBeVisible()
    expect(screen.getByPlaceholderText('选择 SRT 字幕')).toBeVisible()
    expect(props.onSelectSourceMode).toHaveBeenCalledWith('url')
    expect(props.onSelectPath).toHaveBeenCalledWith('video')
  })

  it('patches URL source options', () => {
    const onPatchRequest = vi.fn()
    renderPanel({
      onPatchRequest,
      request: { ...request, source_mode: 'url', source_url: 'https://example.com/watch' },
    })

    fireEvent.click(screen.getByRole('button', { name: '只用字幕生成' }))
    fireEvent.click(screen.getByLabelText(/导出时跳过视频切片/))

    expect(screen.getByPlaceholderText('https://www.youtube.com/watch?v=...')).toHaveValue(
      'https://example.com/watch',
    )
    expect(onPatchRequest).toHaveBeenCalledWith({ url_import_mode: 'subtitles', skip_video_slicing: true })
    expect(onPatchRequest).toHaveBeenCalledWith({ skip_video_slicing: true, url_import_mode: 'subtitles' })
  })

  it('renders document path controls', () => {
    const props = renderPanel({ request: { ...request, source_mode: 'document' } })

    fireEvent.click(screen.getByRole('button', { name: '选择文档资料' }))

    expect(screen.getByText('支持 TXT、Markdown、DOCX、EPUB、PDF。扫描版 PDF 需要后续 OCR。')).toBeVisible()
    expect(props.onSelectPath).toHaveBeenCalledWith('document')
  })
})
