import { describe, expect, it } from 'vitest'

import { defaultRequest } from './options'
import { isSourceInputReady, sourceRequirementMessage } from './sourceValidation'

describe('sourceValidation', () => {
  it('requires a real http or https URL for video link mode', () => {
    expect(isSourceInputReady({ ...defaultRequest, source_mode: 'url', source_url: 'not-a-url' })).toBe(false)
    expect(isSourceInputReady({ ...defaultRequest, source_mode: 'url', source_url: 'ftp://example.com/video' })).toBe(false)
    expect(isSourceInputReady({ ...defaultRequest, source_mode: 'url', source_url: 'https://example.com/video' })).toBe(true)
    expect(sourceRequirementMessage({ ...defaultRequest, source_mode: 'url', source_url: 'not-a-url' })).toBe('请输入有效的视频链接，例如 https://...')
  })

  it('requires local video and document inputs to look like supported files', () => {
    expect(isSourceInputReady({ ...defaultRequest, source_mode: 'local', video_path: 'C:/clips/readme.txt' })).toBe(false)
    expect(isSourceInputReady({ ...defaultRequest, source_mode: 'local', video_path: 'C:/clips/lesson.mp4' })).toBe(true)
    expect(sourceRequirementMessage({ ...defaultRequest, source_mode: 'local', video_path: 'C:/clips/readme.txt' })).toBe('请选择 MP4、MKV、MOV、WEBM 等视频文件。')

    expect(isSourceInputReady({ ...defaultRequest, source_mode: 'document', document_path: 'C:/docs/video.mp4' })).toBe(false)
    expect(isSourceInputReady({ ...defaultRequest, source_mode: 'document', document_path: 'C:/docs/notes.pdf' })).toBe(true)
    expect(sourceRequirementMessage({ ...defaultRequest, source_mode: 'document', document_path: 'C:/docs/video.mp4' })).toBe('请选择 TXT、Markdown、DOCX、EPUB 或 PDF 文档。')
  })

  it('requires at least one enabled item in batch mode', () => {
    expect(
      isSourceInputReady({
        ...defaultRequest,
        batch_enabled: true,
        source_mode: 'local',
        batch_items: [{ id: 'disabled', title: 'Disabled', subdeck_title: 'Disabled', source_mode: 'local', enabled: false, video_path: 'C:/a.mp4' }],
      }),
    ).toBe(false)
    expect(
      isSourceInputReady({
        ...defaultRequest,
        batch_enabled: true,
        source_mode: 'local',
        batch_items: [{ id: 'ready', title: 'Ready', subdeck_title: 'Ready', source_mode: 'local', enabled: true, video_path: 'C:/a.mp4' }],
      }),
    ).toBe(true)
    expect(sourceRequirementMessage({ ...defaultRequest, batch_enabled: true })).toBe('请先添加至少一个批量素材后继续。')
  })
})
