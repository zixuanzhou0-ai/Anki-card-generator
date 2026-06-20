import { describe, expect, it } from 'vitest'

import { buildAppStatusTone } from './appStatusTone'

describe('appStatusTone', () => {
  it('uses active tone while the app is busy', () => {
    expect(
      buildAppStatusTone({
        appBusy: true,
        hasWorkerProgress: false,
        status: '导出失败，但仍在收尾。',
      }),
    ).toBe('active')
  })

  it('uses active tone while worker progress is present', () => {
    expect(
      buildAppStatusTone({
        appBusy: false,
        hasWorkerProgress: true,
        status: '准备生成 Anki 卡片。',
      }),
    ).toBe('active')
  })

  it('maps common failure and preflight messages to warning tone', () => {
    for (const status of ['TTS 生成失败，未生成 APKG。', '请先选择视频素材。', '导出目录不存在。']) {
      expect(
        buildAppStatusTone({
          appBusy: false,
          hasWorkerProgress: false,
          status,
        }),
      ).toBe('warn')
    }
  })

  it('maps success and ready messages to ok tone', () => {
    for (const status of ['导出完成：20 张卡。', 'TTS 测试通过。', '模型 API 已套用。', '已保留当前生成结果。']) {
      expect(
        buildAppStatusTone({
          appBusy: false,
          hasWorkerProgress: false,
          status,
        }),
      ).toBe('ok')
    }
  })

  it('falls back to idle for neutral status messages', () => {
    expect(
      buildAppStatusTone({
        appBusy: false,
        hasWorkerProgress: false,
        status: '准备生成 Anki 卡片。',
      }),
    ).toBe('idle')
  })
})
