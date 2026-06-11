import '@testing-library/jest-dom/vitest'
import type { ComponentProps } from 'react'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { ApiConfig, ApiPreset } from '../../domain/types'
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

function renderPanel(overrides: Partial<ComponentProps<typeof ApiSettingsPanel>> = {}) {
  const props: ComponentProps<typeof ApiSettingsPanel> = {
    advancedApiPresets: [],
    apiConfig,
    apiTestMessage: '请先测试连接。',
    apiTestMeta: 'local · 预览模式',
    apiTestTitle: '未测试',
    apiTestTone: 'idle',
    apiTesting: false,
    activeApiProfileId: 'local',
    apiProfileDirty: false,
    apiProfileStatus: '未保存到我的模型',
    appBusy: false,
    capabilityHelp: { structured_json: '结构化输出' },
    capabilityLabels: ['structured_json'],
    featuredApiPresets: [preset],
    mimoOpenAiBaseUrl: 'https://api.xiaomimimo.com/v1',
    mimoTextModels: [{ label: 'MIMO V2.5 Pro', value: 'mimo-v2.5-pro' }],
    savedApiProfiles: [],
    showAdvancedApi: false,
    showCapabilities: true,
    onApplyApiPreset: vi.fn(),
    onApplySavedApiProfile: vi.fn(),
    onPatchApi: vi.fn(),
    onSaveApiProfile: vi.fn(),
    onSetShowAdvancedApi: vi.fn(),
    onSetShowCapabilities: vi.fn(),
    onTestApi: vi.fn(),
    ...overrides,
  }
  render(<ApiSettingsPanel {...props} />)
  return props
}

describe('ApiSettingsPanel', () => {
  it('renders presets and can test the API connection', () => {
    const props = renderPanel()

    fireEvent.click(screen.getByRole('button', { name: /测试连接/ }))
    fireEvent.change(screen.getByRole('combobox', { name: /^模型方案$/ }), { target: { value: 'preset:mimo' } })

    expect(screen.getByText('模型 API')).toBeInTheDocument()
    expect(screen.getByText('请先测试连接。')).toBeInTheDocument()
    expect(props.onTestApi).toHaveBeenCalledOnce()
    expect(props.onApplyApiPreset).toHaveBeenCalledWith(preset)
  })

  it('renders a precise failed diagnostic title', () => {
    renderPanel({
      apiTestMessage: '模型请求超时：timed out。',
      apiTestTitle: '请求超时',
      apiTestTone: 'warn',
    })

    expect(screen.getByText('请求超时')).toBeInTheDocument()
    expect(screen.getByText('模型请求超时：timed out。')).toBeInTheDocument()
  })

  it('patches provider defaults when switching to MIMO', () => {
    const onPatchApi = vi.fn()
    renderPanel({ onPatchApi, showAdvancedApi: true })

    fireEvent.change(screen.getByLabelText(/Provider/), { target: { value: 'mimo' } })

    expect(onPatchApi).toHaveBeenCalledWith(
      expect.objectContaining({
        base_url: 'https://api.xiaomimimo.com/v1',
        model: 'mimo-v2.5-pro',
        provider: 'mimo',
      }),
    )
  })

  it('patches DeepSeek V4 defaults when switching to OpenAI-compatible from empty local config', () => {
    const onPatchApi = vi.fn()
    renderPanel({ onPatchApi, showAdvancedApi: true })

    fireEvent.change(screen.getByLabelText(/Provider/), { target: { value: 'openai-compatible' } })

    expect(onPatchApi).toHaveBeenCalledWith(
      expect.objectContaining({
        base_url: 'https://api.deepseek.com',
        model: 'deepseek-v4-pro',
        provider: 'openai-compatible',
      }),
    )
  })

  it('patches Gemini Vertex defaults when switching to the Vertex provider', () => {
    const onPatchApi = vi.fn()
    renderPanel({ onPatchApi, showAdvancedApi: true })

    fireEvent.change(screen.getByLabelText(/Provider/), { target: { value: 'gemini-vertex' } })

    expect(onPatchApi).toHaveBeenCalledWith(
      expect.objectContaining({
        api_key: '',
        base_url: 'https://aiplatform.googleapis.com',
        model: 'gemini-3.1-pro-preview',
        provider: 'gemini-vertex',
      }),
    )
  })

  it('patches Gemini Vertex defaults from the model-row shortcut', () => {
    const onPatchApi = vi.fn()
    renderPanel({ onPatchApi, showAdvancedApi: true })

    fireEvent.click(screen.getByRole('button', { name: /Vertex AI/ }))

    expect(onPatchApi).toHaveBeenCalledWith(
      expect.objectContaining({
        api_key: '',
        base_url: 'https://aiplatform.googleapis.com',
        model: 'gemini-3.1-pro-preview',
        provider: 'gemini-vertex',
      }),
    )
  })

  it('hides the API key field when Gemini Vertex uses local gcloud auth', () => {
    renderPanel({
      apiConfig: {
        ...apiConfig,
        api_key: 'sk-old-provider-key',
        base_url: 'https://aiplatform.googleapis.com',
        model: 'gemini-3.1-pro-preview',
        provider: 'gemini-vertex',
      },
    })

    expect(screen.getByText('Vertex 授权')).toBeInTheDocument()
    expect(screen.getByText('使用本机 gcloud OAuth')).toBeInTheDocument()
    expect(screen.queryByLabelText('API Key')).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/记住本机模型 API Key/)).not.toBeInTheDocument()
  })

  it('toggles capabilities and saves the current model profile', () => {
    const onPatchApi = vi.fn()
    const onSaveApiProfile = vi.fn()
    renderPanel({ onPatchApi, onSaveApiProfile })

    fireEvent.click(screen.getByRole('button', { name: /structured_json/ }))
    fireEvent.click(screen.getByRole('button', { name: /保存模型方案/ }))

    expect(onPatchApi).toHaveBeenCalledWith({ capabilities: [] })
    expect(onSaveApiProfile).toHaveBeenCalledOnce()
  })
})
