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

  it('enables TTS with MIMO defaults', () => {
    const onPatchTts = vi.fn()
    renderPanel({ onPatchTts })

    fireEvent.click(screen.getByLabelText(/导出时生成整句和词伙 TTS/))

    expect(onPatchTts).toHaveBeenCalledWith({
      base_url: 'https://token-plan-sgp.xiaomimimo.com/v1',
      enabled: true,
      model: 'mimo-v2.5-tts',
      provider: 'mimo',
      voice: 'Mia',
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
})
