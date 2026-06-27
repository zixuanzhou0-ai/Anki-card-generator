import { describe, expect, it } from 'vitest'

import type { ApiConfig, ApiTestResult, SavedApiProfile, TtsConfig, TtsTestResult } from '../domain/types'
import { buildApiTestStatus, buildEffectiveApiTestResult, buildTtsTestStatus } from './settingsTestStatus'

const ttsConfig: TtsConfig = {
  enabled: true,
  provider: 'gemini-vertex',
  base_url: 'https://aiplatform.googleapis.com',
  api_key: '',
  model: 'gemini-3.1-flash-tts-preview',
  voice: 'Kore',
  language: 'en',
  sample_rate: 24000,
  bit_rate: 128000,
  output_volume: 1,
}

const apiConfig: ApiConfig = {
  provider: 'gemini-vertex',
  base_url: 'https://aiplatform.googleapis.com',
  api_key: '',
  model: 'gemini-3.5-flash',
  capabilities: ['learning-points', 'card-generation'],
  tts_config: ttsConfig,
}

const savedApiProfile: SavedApiProfile = {
  id: 'vertex-quality',
  label: 'Gemini Vertex Flash',
  provider: 'gemini-vertex',
  base_url: 'https://aiplatform.googleapis.com',
  model: 'gemini-3.5-flash',
  capabilities: ['learning-points', 'card-generation'],
  auth: 'gcloud',
  has_api_key: false,
  updated_at: '2026-06-19T00:00:00+08:00',
  last_test_ok: true,
}

describe('settingsTestStatus', () => {
  it('builds idle API status from the current API config', () => {
    const status = buildApiTestStatus({
      result: null,
      testing: false,
      apiConfig,
    })

    expect(status.tone).toBe('idle')
    expect(status.title).toBe('尚未测试')
    expect(status.message).toContain('测试连接')
    expect(status.meta).toBe('gemini-vertex · gemini-3.5-flash')
  })

  it('builds testing API status without replacing the current config meta', () => {
    const status = buildApiTestStatus({
      result: null,
      testing: true,
      apiConfig,
    })

    expect(status.tone).toBe('testing')
    expect(status.title).toBe('正在测试连接')
    expect(status.message).toContain('正在向当前接口')
    expect(status.meta).toBe('gemini-vertex · gemini-3.5-flash')
  })

  it('builds API result status from the latest test result', () => {
    const status = buildApiTestStatus({
      result: {
        ok: false,
        provider: 'mimo',
        model: 'mimo-v2.5-pro',
        message: 'API key invalid',
        error_code: 'MODEL_AUTH_FAILED',
        latency_ms: 732,
      } satisfies ApiTestResult,
      testing: false,
      apiConfig,
    })

    expect(status.tone).toBe('warn')
    expect(status.title).toBe('授权失败')
    expect(status.message).toBe('API key invalid')
    expect(status.meta).toBe('mimo · mimo-v2.5-pro · 732 ms')
  })

  it('keeps the latest API test result ahead of saved profile fallback', () => {
    const result: ApiTestResult = {
      ok: false,
      provider: 'deepseek',
      model: 'deepseek-v4-pro',
      message: 'Current config failed',
      error_code: 'MODEL_AUTH_FAILED',
    }

    expect(
      buildEffectiveApiTestResult({
        result,
        savedProfileTestOk: true,
        activeProfile: savedApiProfile,
      }),
    ).toBe(result)
  })

  it('synthesizes a passing API test result for an unchanged saved tested profile', () => {
    expect(
      buildEffectiveApiTestResult({
        result: null,
        savedProfileTestOk: true,
        activeProfile: savedApiProfile,
      }),
    ).toEqual({
      ok: true,
      provider: 'gemini-vertex',
      model: 'gemini-3.5-flash',
      message: '已保存的模型方案测试通过。配置未改变，无需重复测试。',
    })
  })

  it('does not synthesize an API test result without both a tested saved profile and active profile', () => {
    expect(
      buildEffectiveApiTestResult({
        result: null,
        savedProfileTestOk: false,
        activeProfile: savedApiProfile,
      }),
    ).toBeNull()
    expect(
      buildEffectiveApiTestResult({
        result: null,
        savedProfileTestOk: true,
        activeProfile: null,
      }),
    ).toBeNull()
  })

  it('builds disabled TTS idle status without suggesting missing ASR or quality gates', () => {
    const status = buildTtsTestStatus({
      result: null,
      testing: false,
      tts: { ...ttsConfig, enabled: false, provider: 'disabled', model: '', voice: '' },
    })

    expect(status.tone).toBe('idle')
    expect(status.title).toBe('TTS 已关闭')
    expect(status.message).toBe('关闭时不能导出视频卡；导出前需要开启整句 TTS 和表达 TTS。')
    expect(status.message).not.toContain('原声')
    expect(status.meta).toBe('disabled · 无模型名 · 无 voice')
  })

  it('builds TTS result status with latency and audio byte meta', () => {
    const status = buildTtsTestStatus({
      result: {
        ok: true,
        provider: 'gemini-vertex',
        model: 'gemini-3.1-flash-tts-preview',
        voice: 'Kore',
        message: 'TTS test passed',
        latency_ms: 1280,
        bytes: 4096,
      } satisfies TtsTestResult,
      testing: false,
      tts: ttsConfig,
    })

    expect(status.tone).toBe('ok')
    expect(status.title).toBe('TTS 连接成功')
    expect(status.message).toBe('TTS test passed')
    expect(status.meta).toBe('gemini-vertex · gemini-3.1-flash-tts-preview · Kore · 1280 ms · 4096 bytes')
  })
})
