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
    expect(
      screen.getByText('可留空；生成时会自动匹配同目录 SRT/VTT，也会尝试提取 MKV/MP4 内嵌文字字幕。'),
    ).toBeVisible()
    expect(screen.getByText('视频过大、切片很慢或媒体失败时，可先用字幕-only 产出可复习卡。')).toBeVisible()
    expect(props.onSelectSourceMode).toHaveBeenCalledWith('url')
    expect(props.onSelectPath).toHaveBeenCalledWith('video')
  })

  it('patches local subtitle-only export mode', () => {
    const onPatchRequest = vi.fn()
    renderPanel({ onPatchRequest })

    fireEvent.click(screen.getByLabelText(/导出时跳过视频切片/))

    expect(onPatchRequest).toHaveBeenCalledWith({ skip_video_slicing: true })
  })

  it('keeps local source mode when choosing a local video', () => {
    const onPatchRequest = vi.fn()
    const onSelectPath = vi.fn()
    const onSelectSourceMode = vi.fn()
    renderPanel({ onPatchRequest, onSelectPath, onSelectSourceMode })

    fireEvent.change(screen.getByPlaceholderText('选择本地视频'), {
      target: { value: 'F:\\Videos\\episode.mkv' },
    })
    fireEvent.click(screen.getByRole('button', { name: '选择视频文件' }))

    expect(onPatchRequest).toHaveBeenCalledWith({ video_path: 'F:\\Videos\\episode.mkv' })
    expect(onSelectPath).toHaveBeenCalledWith('video')
    expect(onSelectSourceMode).not.toHaveBeenCalled()
  })

  it('patches URL source options', () => {
    const onPatchRequest = vi.fn()
    renderPanel({
      onPatchRequest,
      request: { ...request, source_mode: 'url', source_url: 'https://example.com/watch' },
    })

    fireEvent.click(screen.getByRole('button', { name: '只用字幕生成' }))
    fireEvent.click(screen.getByLabelText(/导出时跳过视频切片/))

    expect(screen.getByPlaceholderText('https://www.youtube.com/watch?v=...')).toHaveValue('https://example.com/watch')
    expect(onPatchRequest).toHaveBeenCalledWith({ url_import_mode: 'subtitles', skip_video_slicing: true })
    expect(onPatchRequest).toHaveBeenCalledWith({ skip_video_slicing: true, url_import_mode: 'subtitles' })
  })

  it('renders document path controls', () => {
    const props = renderPanel({ request: { ...request, source_mode: 'document' } })

    fireEvent.click(screen.getByRole('button', { name: '选择文档资料' }))

    expect(screen.getByText('支持 TXT、Markdown、DOCX、EPUB、PDF。扫描版 PDF 需要后续 OCR。')).toBeVisible()
    expect(screen.getByText('文档目标、讲解语言和吸收深度在下方“文档目标”里调整。')).toBeVisible()
    expect(props.onSelectPath).toHaveBeenCalledWith('document')
  })
})
