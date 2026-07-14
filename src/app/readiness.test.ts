import { describe, expect, it } from 'vitest'

import {
  buildReadinessItems,
  buildTtsReadinessDetail,
  buildWorkflowReadiness,
  isEnvironmentReadyForGeneration,
} from './readiness'

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
      ttsReadyForGeneration: true,
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
      ttsReadyForGeneration: false,
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
describe('buildWorkflowReadiness', () => {
  const base = {
    sourceReady: true,
    environmentReady: true,
    environmentChecked: true,
    apiProvider: 'openai',
    apiReady: true,
    apiTested: true,
    ttsRequired: true,
    ttsReady: true,
    ttsTested: true,
    selectedLearningPointCount: 1,
    hasLearningPoints: false,
    hasProject: false,
    exportableCardCount: 0,
    repairRequiredCardCount: 0,
    hasExport: false,
    ankiVerified: false,
  }

  it('never reports an unchecked desktop environment as ready', () => {
    const snapshot = buildWorkflowReadiness({
      ...base,
      environmentReady: false,
      environmentChecked: false,
    })

    expect(snapshot.stage).toBe('setup')
    expect(snapshot.canProceed).toBe(false)
    expect(snapshot.blockers.find((item) => item.id === 'environment')?.state).toBe('unknown')
    expect(snapshot.primaryActionLabel).toBe('完成 1 项准备')
  })

  it('allows extraction before TTS testing but blocks video-card generation', () => {
    const extract = buildWorkflowReadiness({
      ...base,
      ttsReady: false,
      ttsTested: false,
    })
    expect(extract.stage).toBe('extract')
    expect(extract.canProceed).toBe(true)
    expect(extract.warnings.find((item) => item.id === 'tts')?.title).toBe('TTS 尚未测试')

    const generate = buildWorkflowReadiness({
      ...base,
      hasLearningPoints: true,
      ttsReady: false,
      ttsTested: false,
    })
    expect(generate.stage).toBe('generate')
    expect(generate.canProceed).toBe(false)
    expect(generate.blockers.find((item) => item.id === 'tts')?.state).toBe('unknown')
  })

  it('keeps generated APKG separate from real Anki verification', () => {
    const exported = buildWorkflowReadiness({
      ...base,
      hasLearningPoints: true,
      hasProject: true,
      exportableCardCount: 1,
      hasExport: true,
    })
    expect(exported.stage).toBe('verify')
    expect(exported.canProceed).toBe(false)
    expect(exported.blockers.map((item) => item.id)).toEqual(['anki'])

    const verified = buildWorkflowReadiness({
      ...base,
      hasLearningPoints: true,
      hasProject: true,
      exportableCardCount: 1,
      hasExport: true,
      ankiVerified: true,
    })
    expect(verified.canProceed).toBe(true)
    expect(verified.primaryActionLabel).toBe('已在 Anki 中核验')
  })

  it('never mixes repair-required cards into the export gate', () => {
    const blocked = buildWorkflowReadiness({
      ...base,
      hasLearningPoints: true,
      hasProject: true,
      exportableCardCount: 0,
      repairRequiredCardCount: 2,
    })
    expect(blocked.stage).toBe('export')
    expect(blocked.canProceed).toBe(false)
    expect(blocked.blockers.find((item) => item.id === 'cards')).toBeTruthy()
    expect(blocked.warnings.find((item) => item.id === 'cards')?.detail).toContain('2 张卡片不会混入本次导出')
  })
})
