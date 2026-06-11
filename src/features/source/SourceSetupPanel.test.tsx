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
    expect(screen.getByText('上传资料')).toBeVisible()
    expect(screen.getByText('选择目标')).toBeVisible()
    expect(screen.getByText('生成知识卡')).toBeVisible()
    expect(screen.getByText('上传后只需调整文档目标，系统会自动拆知识点，不需要字幕、切片或 TTS。')).toBeVisible()
    expect(props.onSelectPath).toHaveBeenCalledWith('document')
  })

  it('shows local video batch controls and per-episode subdeck rows', () => {
    const onPatchRequest = vi.fn()
    const onSelectPath = vi.fn()
    renderPanel({
      onPatchRequest,
      onSelectPath,
      request: {
        ...request,
        batch_enabled: true,
        batch_items: [
          {
            id: 'ep1',
            source_mode: 'local',
            enabled: true,
            title: 'S01E01 - Pilot',
            subdeck_title: 'S01E01 - Pilot',
            deck_name: '无耻之徒 第一季::S01E01 - Pilot',
            video_path: 'D:/Shows/S01E01 Pilot.mp4',
            subtitle_path: 'D:/Shows/S01E01 Pilot.srt',
          },
          {
            id: 'ep2',
            source_mode: 'local',
            enabled: true,
            title: 'S01E02 - Frank the Plank',
            subdeck_title: 'S01E02 - Frank the Plank',
            deck_name: '无耻之徒 第一季::S01E02 - Frank the Plank',
            video_path: 'D:/Shows/S01E02 Frank.mp4',
          },
        ],
      },
    })

    expect(screen.getByText('批量视频文件夹')).toBeVisible()
    expect(screen.getByText('已添加 2 个素材')).toBeVisible()
    expect(screen.getByLabelText('批量学习包预览')).toBeVisible()
    expect(screen.getByText('学习包：无标题学习包')).toBeVisible()
    expect(screen.getByText('一个 APKG · 2 个嵌套子牌组')).toBeVisible()
    expect(screen.getByText('先添加素材')).toBeVisible()
    expect(screen.getByText('确认子牌组')).toBeVisible()
    expect(screen.getByText('统一生成导出')).toBeVisible()
    expect(screen.getByText('无耻之徒 第一季::S01E01 - Pilot')).toBeVisible()
    expect(screen.getByText('无耻之徒 第一季::S01E02 - Frank the Plank')).toBeVisible()
    expect(screen.getByText('S01E01 - Pilot')).toBeVisible()
    expect(screen.getByText('S01E02 - Frank the Plank')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: '选择视频文件夹批量添加' }))
    expect(onSelectPath).toHaveBeenCalledWith('video-folder')
    fireEvent.click(screen.getByRole('button', { name: '关闭批量模式' }))
    expect(onPatchRequest).toHaveBeenCalledWith({ batch_enabled: false })
  })

  it('adds multiline URL batch items from the URL source block', () => {
    const onPatchRequest = vi.fn()
    renderPanel({
      onPatchRequest,
      request: { ...request, source_mode: 'url', batch_enabled: true, source_url: 'https://youtu.be/aaa\nhttps://youtu.be/bbb' },
    })

    expect(screen.getByText('批量视频链接')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: '添加链接到批量列表' }))
    expect(onPatchRequest).toHaveBeenCalledWith(
      expect.objectContaining({
        batch_enabled: true,
        batch_items: expect.arrayContaining([expect.objectContaining({ source_mode: 'url', source_url: 'https://youtu.be/aaa' })]),
      }),
    )
  })

  it('keeps existing URL batch rows immediately visible before the package preview', () => {
    renderPanel({
      request: {
        ...request,
        source_mode: 'url',
        batch_enabled: true,
        batch_items: [
          {
            id: 'url1',
            source_mode: 'url',
            enabled: true,
            title: '001 - example.com',
            subdeck_title: '001 - example.com',
            source_url: 'https://example.com/a',
          },
          {
            id: 'url2',
            source_mode: 'url',
            enabled: true,
            title: '002 - example.com',
            subdeck_title: '002 - example.com',
            source_url: 'https://example.com/b',
          },
        ],
      },
    })

    const firstBatchRow = screen.getByText('https://example.com/a').closest('.batch-item-row')
    const packagePreview = screen.getByLabelText('批量学习包预览')

    expect(firstBatchRow).toBeVisible()
    expect(firstBatchRow?.compareDocumentPosition(packagePreview)).toBe(Node.DOCUMENT_POSITION_FOLLOWING)
  })

  it('shows document batch controls in the document source block', () => {
    const onSelectPath = vi.fn()
    renderPanel({
      onSelectPath,
      request: {
        ...request,
        source_mode: 'document',
        batch_enabled: true,
        batch_items: [
          {
            id: 'doc1',
            source_mode: 'document',
            enabled: true,
            title: '01 - Intro',
            subdeck_title: '01 - Intro',
            deck_name: '资料包::01 - Intro',
            document_path: 'E:/Docs/01 Intro.md',
          },
        ],
      },
    })

    expect(screen.getByText('批量文档 / 文件夹')).toBeVisible()
    expect(screen.getByText('一个 APKG · 1 个嵌套子牌组')).toBeVisible()
    expect(screen.getByText('资料包::01 - Intro')).toBeVisible()
    expect(screen.getByText('01 - Intro')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: '选择文档文件夹批量添加' }))
    expect(onSelectPath).toHaveBeenCalledWith('document-folder')
  })
})
