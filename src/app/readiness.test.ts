import { describe, expect, it } from 'vitest'

import { buildReadinessItems, buildTtsReadinessDetail, isEnvironmentReadyForGeneration } from './readiness'

describe('buildReadinessItems', () => {
  it('does not expose hidden document source copy in readiness labels', () => {
    const items = buildReadinessItems({
      sourceMode: 'document',
      sourceReady: false,
      localVideoPath: '',
      localSubtitlePath: '',
      envReady: true,
      envStatusChecked: true,
      apiProvider: 'openai',
      apiReadyForGeneration: true,
      hasApiTestResult: true,
      ttsRequired: false,
      ttsDetail: '已关闭',
      currentSelectionCount: 1,
    })

    expect(items.map((item) => item.label)).toEqual(['素材', '环境', 'API', '卡片'])
    expect(items.find((item) => item.id === 'source')?.detail).toBe('当前发布版只支持本地视频和视频链接。请选择视频素材。')
    expect(items.map((item) => `${item.label} ${item.detail}`).join('\n')).not.toMatch(/文档|TXT|Markdown|DOCX|PDF/)
    expect(items.some((item) => item.label.includes('TTS'))).toBe(false)
  })

  it('keeps TTS readiness visible for video workflows', () => {
    const items = buildReadinessItems({
      sourceMode: 'local',
      sourceReady: true,
      localVideoPath: 'E:/video.mp4',
      localSubtitlePath: '',
      envReady: false,
      envStatusChecked: true,
      apiProvider: 'local',
      apiReadyForGeneration: false,
      hasApiTestResult: false,
      ttsRequired: true,
      ttsDetail: '必须先测试',
      currentSelectionCount: 3,
    })

    expect(items.map((item) => item.label)).toContain('TTS 必需')
    expect(items.find((item) => item.id === 'source')?.detail).toBe('已选视频，自动匹配字幕')
  })

  it('summarizes TTS readiness as a video export gate', () => {
    expect(buildTtsReadinessDetail({ ttsRequired: false, ttsTestResult: null })).toBe('已关闭')
    expect(buildTtsReadinessDetail({ ttsRequired: true, ttsTestResult: null })).toBe('必须先测试')
    expect(buildTtsReadinessDetail({ ttsRequired: true, ttsTestResult: { ok: true } })).toBe('导出可用')
    expect(buildTtsReadinessDetail({ ttsRequired: true, ttsTestResult: { ok: false } })).toBe('需修复后导出')
  })

  it('checks desktop environment readiness for video-only public workflows', () => {
    expect(
      isEnvironmentReadyForGeneration({
        desktopRuntime: false,
        envStatus: null,
        sourceMode: 'url',
      }),
    ).toBe(true)
    expect(
      isEnvironmentReadyForGeneration({
        desktopRuntime: true,
        envStatus: { genanki: true, ffmpeg: true },
        sourceMode: 'local',
      }),
    ).toBe(true)
    expect(
      isEnvironmentReadyForGeneration({
        desktopRuntime: true,
        envStatus: { genanki: true, ffmpeg: true, yt_dlp: true },
        sourceMode: 'url',
      }),
    ).toBe(true)
    expect(
      isEnvironmentReadyForGeneration({
        desktopRuntime: true,
        envStatus: { genanki: true, ffmpeg: true },
        sourceMode: 'url',
      }),
    ).toBe(false)
    expect(
      isEnvironmentReadyForGeneration({
        desktopRuntime: true,
        envStatus: { genanki: true, ffmpeg: true },
        sourceMode: 'document',
      }),
    ).toBe(false)
  })
})
