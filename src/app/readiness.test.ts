import { describe, expect, it } from 'vitest'

import { buildReadinessItems } from './readiness'

describe('buildReadinessItems', () => {
  it('keeps document mode focused on document, environment, API, and cards', () => {
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

    expect(items.map((item) => item.label)).toEqual(['文档', '环境', 'API', '卡片'])
    expect(items.find((item) => item.id === 'source')?.detail).toBe('待选择 TXT / Markdown / DOCX / PDF')
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
      ttsDetail: '可稍后测试',
      currentSelectionCount: 3,
    })

    expect(items.map((item) => item.label)).toContain('TTS 增强')
    expect(items.find((item) => item.id === 'source')?.detail).toBe('已选视频，自动匹配字幕')
  })
})
