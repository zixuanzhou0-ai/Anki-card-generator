import '@testing-library/jest-dom/vitest'
import type { ComponentProps } from 'react'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { ApiConfig, ApiPreset, SecretPrefs } from '../../domain/types'
import { ApiSettingsPanel } from './ApiSettingsPanel'

afterEach(() => cleanup())

const apiConfig: ApiConfig = {
  api_key: '',
  base_url: '',
  capabilities: ['structured_json'],
  model: '',
  provider: 'local',
  tts_config: {
    api_key: '',
    base_url: '',
    bit_rate: 128000,
    enabled: false,
    language: 'auto',
    model: '',
    provider: 'disabled',
    sample_rate: 24000,
    voice: '',
  },
}

const preset: ApiPreset = {
  base_url: 'https://token-plan-sgp.xiaomimimo.com/v1',
  capabilities: ['structured_json', 'long_context'],
  id: 'mimo',
  key_hint: 'tp-...',
  label: 'MIMO Token Plan',
  model: 'mimo-v2.5-pro',
  note: '推荐配置',
  provider: 'mimo',
}

const secretPrefs: SecretPrefs = {
  rememberModelKey: false,
  rememberTtsKey: false,
}

function renderPanel(overrides: Partial<ComponentProps<typeof ApiSettingsPanel>> = {}) {
  const props: ComponentProps<typeof ApiSettingsPanel> = {
    advancedApiPresets: [],
    apiConfig,
    apiTestMessage: '请先测试连接。',
    apiTestMeta: 'local · 本地草稿',
    apiTestTitle: '未测试',
    apiTestTone: 'idle',
    apiTesting: false,
    appBusy: false,
    capabilityHelp: { structured_json: '结构化输出' },
    capabilityLabels: ['structured_json'],
    featuredApiPresets: [preset],
    mimoOpenAiBaseUrl: 'https://api.xiaomimimo.com/v1',
    mimoTextModels: [{ label: 'MIMO V2.5 Pro', value: 'mimo-v2.5-pro' }],
    secretPrefs,
    showAdvancedApi: false,
    showCapabilities: true,
    onApplyApiPreset: vi.fn(),
    onPatchApi: vi.fn(),
    onSetShowAdvancedApi: vi.fn(),
    onSetShowCapabilities: vi.fn(),
    onTestApi: vi.fn(),
    onToggleRememberModelKey: vi.fn(),
    ...overrides,
  }
  render(<ApiSettingsPanel {...props} />)
  return props
}

describe('ApiSettingsPanel', () => {
  it('renders presets and can test the API connection', () => {
    const props = renderPanel()

    fireEvent.click(screen.getByRole('button', { name: /测试连接/ }))
    fireEvent.click(screen.getByRole('button', { name: /MIMO Token Plan/ }))

    expect(screen.getByText('模型 API')).toBeInTheDocument()
    expect(screen.getByText('请先测试连接。')).toBeInTheDocument()
    expect(props.onTestApi).toHaveBeenCalledOnce()
    expect(props.onApplyApiPreset).toHaveBeenCalledWith(preset)
  })

  it('patches provider defaults when switching to MIMO', () => {
    const onPatchApi = vi.fn()
    renderPanel({ onPatchApi })

    fireEvent.change(screen.getByLabelText(/Provider/), { target: { value: 'mimo' } })

    expect(onPatchApi).toHaveBeenCalledWith(
      expect.objectContaining({
        base_url: 'https://api.xiaomimimo.com/v1',
        model: 'mimo-v2.5-pro',
        provider: 'mimo',
      }),
    )
  })

  it('toggles capabilities and remember-key preference', () => {
    const onPatchApi = vi.fn()
    const onToggleRememberModelKey = vi.fn()
    renderPanel({ onPatchApi, onToggleRememberModelKey })

    fireEvent.click(screen.getByRole('button', { name: /structured_json/ }))
    fireEvent.click(screen.getByLabelText(/记住本机模型 API Key/))

    expect(onPatchApi).toHaveBeenCalledWith({ capabilities: [] })
    expect(onToggleRememberModelKey).toHaveBeenCalledOnce()
  })
})
