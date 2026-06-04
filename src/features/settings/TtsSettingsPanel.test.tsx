import '@testing-library/jest-dom/vitest'
import type { ComponentProps } from 'react'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { SecretPrefs, TtsConfig, TtsPreset } from '../../domain/types'
import { TtsSettingsPanel } from './TtsSettingsPanel'

afterEach(() => cleanup())

const tts: TtsConfig = {
  api_key: '',
  base_url: '',
  bit_rate: 128000,
  enabled: false,
  language: 'auto',
  model: '',
  provider: 'disabled',
  sample_rate: 24000,
  voice: '',
}

const enabledTts: TtsConfig = {
  ...tts,
  base_url: 'https://token-plan-sgp.xiaomimimo.com/v1',
  enabled: true,
  model: 'mimo-v2.5-tts',
  provider: 'mimo',
  voice: 'Mia',
}

const preset: TtsPreset = {
  base_url: 'https://token-plan-sgp.xiaomimimo.com/v1',
  id: 'mimo',
  key_hint: '复用 MIMO Key',
  label: 'MIMO SGP TTS',
  model: 'mimo-v2.5-tts',
  note: '推荐语音',
  provider: 'mimo',
  voice: 'Mia',
}

const secretPrefs: SecretPrefs = {
  rememberModelKey: false,
  rememberTtsKey: false,
}

function renderPanel(overrides: Partial<ComponentProps<typeof TtsSettingsPanel>> = {}) {
  const props: ComponentProps<typeof TtsSettingsPanel> = {
    advancedTtsPresets: [],
    appBusy: false,
    featuredTtsPresets: [preset],
    mimoOpenAiBaseUrl: 'https://api.xiaomimimo.com/v1',
    mimoTokenPlanSgpBaseUrl: 'https://token-plan-sgp.xiaomimimo.com/v1',
    mimoTtsModels: [{ label: 'MIMO V2.5 TTS', value: 'mimo-v2.5-tts' }],
    mimoTtsVoices: ['Mia', 'Chloe'],
    qwenTtsModels: [{ label: 'Qwen3 TTS Flash', value: 'qwen3-tts-flash' }],
    qwenTtsVoices: ['Jennifer', 'Aiden', 'Cherry', 'Serena'],
    secretPrefs,
    showAdvancedTts: false,
    tts,
    ttsTestMessage: 'TTS 当前关闭。',
    ttsTestMeta: 'disabled · 无模型名 · 无 voice',
    ttsTestTitle: 'TTS 未启用',
    ttsTestTone: 'idle',
    ttsTesting: false,
    onApplyTtsPreset: vi.fn(),
    onPatchTts: vi.fn(),
    onSetShowAdvancedTts: vi.fn(),
    onTestTts: vi.fn(),
    onToggleRememberTtsKey: vi.fn(),
    ...overrides,
  }
  render(<TtsSettingsPanel {...props} />)
  return props
}

describe('TtsSettingsPanel', () => {
  it('renders disabled state and can apply a preset', () => {
    const props = renderPanel()

    fireEvent.click(screen.getByRole('button', { name: /MIMO SGP TTS/ }))
    fireEvent.click(screen.getByRole('button', { name: /测试 TTS/ }))

    expect(screen.getByText('TTS 当前关闭')).toBeInTheDocument()
    expect(props.onApplyTtsPreset).toHaveBeenCalledWith(preset)
    expect(props.onTestTts).toHaveBeenCalledOnce()
  })

  it('renders a precise TTS failed diagnostic title', () => {
    renderPanel({
      tts: enabledTts,
      ttsTestMessage: 'TTS请求超时：timed out。',
      ttsTestTitle: 'TTS 请求超时',
      ttsTestTone: 'warn',
    })

    expect(screen.getByText('TTS 请求超时')).toBeInTheDocument()
    expect(screen.getByText('TTS请求超时：timed out。')).toBeInTheDocument()
  })

  it('enables TTS with Qwen defaults', () => {
    const onPatchTts = vi.fn()
    renderPanel({ onPatchTts })

    fireEvent.click(screen.getByLabelText(/导出时生成整句和表达 TTS/))

    expect(onPatchTts).toHaveBeenCalledWith({
      base_url: 'https://dashscope.aliyuncs.com/api/v1',
      enabled: true,
      model: 'qwen3-tts-flash',
      provider: 'qwen',
      voice: 'Jennifer',
    })
  })

  it('patches provider and advanced TTS fields', () => {
    const onPatchTts = vi.fn()
    renderPanel({ onPatchTts, showAdvancedTts: true, tts: enabledTts })

    fireEvent.change(screen.getByLabelText(/语音服务/), { target: { value: 'grok' } })
    fireEvent.change(screen.getByLabelText(/Sample Rate/), { target: { value: '48000' } })

    expect(onPatchTts).toHaveBeenCalledWith(
      expect.objectContaining({
        base_url: 'https://api.x.ai/v1',
        enabled: true,
        provider: 'grok',
      }),
    )
    expect(onPatchTts).toHaveBeenCalledWith({ sample_rate: 48000 })
  })

  it('toggles remember-key preference', () => {
    const onToggleRememberTtsKey = vi.fn()
    renderPanel({ onToggleRememberTtsKey, tts: enabledTts })

    fireEvent.click(screen.getByLabelText(/记住本机 TTS API Key/))

    expect(onToggleRememberTtsKey).toHaveBeenCalledOnce()
  })

  it('patches Qwen TTS provider defaults', () => {
    const onPatchTts = vi.fn()
    renderPanel({ onPatchTts, showAdvancedTts: true, tts: { ...enabledTts, provider: 'mimo', model: '', voice: '' } })

    fireEvent.change(screen.getByLabelText(/语音服务/), { target: { value: 'qwen' } })

    expect(onPatchTts).toHaveBeenCalledWith(
      expect.objectContaining({
        base_url: 'https://dashscope.aliyuncs.com/api/v1',
        enabled: true,
        model: 'qwen3-tts-flash',
        provider: 'qwen',
        voice: 'Jennifer',
      }),
    )
  })

  it('patches Gemini Vertex TTS provider defaults without an API key', () => {
    const onPatchTts = vi.fn()
    renderPanel({
      onPatchTts,
      showAdvancedTts: true,
      tts: { ...enabledTts, provider: 'mimo', api_key: 'sk-old', model: '', voice: '' },
    })

    fireEvent.change(screen.getByLabelText(/语音服务/), { target: { value: 'gemini-vertex' } })

    expect(onPatchTts).toHaveBeenCalledWith(
      expect.objectContaining({
        base_url: 'https://aiplatform.googleapis.com',
        api_key: '',
        enabled: true,
        model: 'gemini-3.1-flash-tts-preview',
        provider: 'gemini-vertex',
        voice: 'Kore',
      }),
    )
  })

  it('explains that Gemini Vertex TTS uses local gcloud auth', () => {
    renderPanel({
      tts: {
        ...enabledTts,
        api_key: '',
        base_url: 'https://aiplatform.googleapis.com',
        model: 'gemini-3.1-flash-tts-preview',
        provider: 'gemini-vertex',
        voice: 'Kore',
      },
    })

    expect(screen.getByText(/Vertex TTS 使用本机 gcloud OAuth token/)).toBeInTheDocument()
  })
})
