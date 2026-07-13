import '@testing-library/jest-dom/vitest'
import type { ComponentProps } from 'react'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { ApiConfig, ApiPreset, SavedApiProfile } from '../../domain/types'
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

const mimoPreset: ApiPreset = {
  base_url: 'https://token-plan-sgp.xiaomimimo.com/v1',
  capabilities: ['structured_json', 'long_context'],
  id: 'mimo',
  key_hint: 'tp-...',
  label: 'MIMO Token Plan',
  model: 'mimo-v2.5-pro',
  note: '推荐配置',
  provider: 'mimo',
}

const deepseekPreset: ApiPreset = {
  base_url: 'https://api.deepseek.com',
  capabilities: ['structured_json', 'long_context', 'cheap_batch'],
  id: 'deepseek-v4-flash',
  key_hint: 'DeepSeek Key',
  label: 'DeepSeek V4 Flash',
  model: 'deepseek-v4-flash',
  note: '快速批量生成',
  provider: 'openai-compatible',
}

const customPreset: ApiPreset = {
  base_url: '',
  capabilities: ['structured_json', 'cheap_batch'],
  id: 'custom-compatible',
  key_hint: '任意 Key',
  label: '自定义兼容模型',
  model: '',
  note: '手动填写',
  provider: 'openai-compatible',
}

const hermesPreset: ApiPreset = {
  base_url: 'http://127.0.0.1:8645/v1',
  capabilities: ['structured_json', 'long_context'],
  id: 'hermes-grok-45',
  key_hint: '本机 OAuth · 不需要 API Key',
  label: 'Hermes · Grok 4.5（本机 OAuth）',
  model: 'grok-4.5',
  note: '本机 Hermes xAI OAuth',
  provider: 'openai-compatible',
}

const vertex35Preset: ApiPreset = {
  base_url: 'https://aiplatform.googleapis.com',
  capabilities: ['structured_json', 'long_context', 'cheap_batch'],
  id: 'gemini-35-flash-vertex',
  key_hint: '不需要 API Key，先运行 gcloud auth login / 设置项目',
  label: 'Gemini 3.5 Flash Vertex',
  model: 'gemini-3.5-flash',
  note: 'Vertex AI 快速长上下文筛选',
  provider: 'gemini-vertex',
}

function renderPanel(overrides: Partial<ComponentProps<typeof ApiSettingsPanel>> = {}) {
  const props: ComponentProps<typeof ApiSettingsPanel> = {
    activeApiProfileId: 'local',
    advancedApiPresets: [deepseekPreset, customPreset],
    apiConfig,
    apiKeySaved: false,
    apiProfileDirty: false,
    apiProfileStatus: '未保存到我的模型',
    apiTestMessage: '请先测试连接。',
    apiTestMeta: 'local · 预览模式',
    apiTestTitle: '未测试',
    apiTestTone: 'idle',
    apiTesting: false,
    appBusy: false,
    capabilityHelp: { structured_json: '结构化输出' },
    capabilityLabels: ['structured_json'],
    featuredApiPresets: [mimoPreset],
    hermesChecking: false,
    hermesStarting: false,
    hermesStatus: null,
    mimoOpenAiBaseUrl: 'https://api.xiaomimimo.com/v1',
    mimoTextModels: [{ label: 'MIMO V2.5 Pro', value: 'mimo-v2.5-pro' }],
    savedApiProfiles: [],
    showCapabilities: false,
    onApplyApiPreset: vi.fn(),
    onApplySavedApiProfile: vi.fn(),
    onCheckHermes: vi.fn(),
    onPatchApi: vi.fn(),
    onSaveApiProfile: vi.fn(),
    onSetShowCapabilities: vi.fn(),
    onStartHermes: vi.fn(),
    onTestApi: vi.fn(),
    ...overrides,
  }
  render(<ApiSettingsPanel {...props} />)
  return props
}

describe('ApiSettingsPanel', () => {
  it('uses a searchable catalog and keeps direct config fields visible', () => {
    const props = renderPanel()

    fireEvent.change(screen.getByPlaceholderText('搜索厂商、模型、Base URL'), { target: { value: 'deepseek' } })
    fireEvent.click(screen.getByRole('button', { name: /DeepSeek V4 Flash/ }))
    fireEvent.click(screen.getByRole('button', { name: /测试连接/ }))

    expect(screen.getByText('模型目录')).toBeInTheDocument()
    expect(screen.getByLabelText(/Provider/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Model/)).toBeInTheDocument()
    expect(screen.getByLabelText(/API Key/)).toBeInTheDocument()
    expect(props.onApplyApiPreset).toHaveBeenCalledWith(deepseekPreset)
    expect(props.onTestApi).toHaveBeenCalledOnce()
  })

  it('lets the user manually add an OpenAI-compatible model instead of forcing recommendations', () => {
    const props = renderPanel()

    fireEvent.click(screen.getByRole('button', { name: /OpenAI-compatible 模型/ }))

    expect(props.onApplyApiPreset).toHaveBeenCalledWith(customPreset)
  })

  it('shows saved profiles at the top and applies them from the catalog', () => {
    const savedProfile: SavedApiProfile = {
      auth: 'api_key',
      base_url: 'https://my-provider.example/v1',
      capabilities: ['structured_json'],
      has_api_key: true,
      id: 'mine',
      label: '我的高速模型',
      last_test_ok: true,
      model: 'my-fast-model',
      provider: 'openai-compatible',
      updated_at: '2026-06-16T00:00:00Z',
    }
    const props = renderPanel({ activeApiProfileId: 'mine', savedApiProfiles: [savedProfile] })

    fireEvent.click(screen.getByRole('button', { name: /我的高速模型/ }))

    expect(screen.getByText('我的模型')).toBeInTheDocument()
    expect(props.onApplySavedApiProfile).toHaveBeenCalledWith('mine')
  })

  it('uses filter chips only as catalog filters', () => {
    renderPanel()

    fireEvent.click(screen.getByRole('button', { name: '速度' }))

    expect(screen.getByRole('button', { name: /DeepSeek V4 Flash/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /MIMO Token Plan/ })).not.toBeInTheDocument()
    expect(screen.getByLabelText(/Base URL/)).toBeInTheDocument()
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

  it('patches DeepSeek V4 defaults when switching to OpenAI-compatible from empty local config', () => {
    const onPatchApi = vi.fn()
    renderPanel({ onPatchApi })

    fireEvent.change(screen.getByLabelText(/Provider/), { target: { value: 'openai-compatible' } })

    expect(onPatchApi).toHaveBeenCalledWith(
      expect.objectContaining({
        base_url: 'https://api.deepseek.com',
        model: 'deepseek-v4-pro',
        provider: 'openai-compatible',
      }),
    )
  })

  it('patches Gemini Vertex defaults and hides the API key field for gcloud auth', () => {
    const onPatchApi = vi.fn()
    renderPanel({
      apiConfig: {
        ...apiConfig,
        api_key: 'sk-old-provider-key',
        base_url: 'https://aiplatform.googleapis.com',
        model: 'gemini-3.5-flash',
        provider: 'gemini-vertex',
      },
      onPatchApi,
    })

    fireEvent.change(screen.getByLabelText(/Provider/), { target: { value: 'gemini-vertex' } })

    expect(onPatchApi).toHaveBeenCalledWith(
      expect.objectContaining({
        api_key: '',
        base_url: 'https://aiplatform.googleapis.com',
        model: 'gemini-3.5-flash',
        provider: 'gemini-vertex',
      }),
    )
    expect(screen.getByText('Vertex 授权')).toBeInTheDocument()
    expect(screen.getByText('使用本机 gcloud OAuth')).toBeInTheDocument()
    expect(screen.queryByLabelText('API Key')).not.toBeInTheDocument()
  })

  it('shows Gemini 3.5 Flash as a Vertex preset and model suggestion', () => {
    const onApplyApiPreset = vi.fn()
    renderPanel({
      advancedApiPresets: [vertex35Preset, deepseekPreset, customPreset],
      mimoTextModels: [
        { label: 'MIMO V2.5 Pro', value: 'mimo-v2.5-pro' },
        { label: 'Gemini 3.5 Flash', value: 'gemini-3.5-flash' },
      ],
      onApplyApiPreset,
    })

    fireEvent.change(screen.getByPlaceholderText('搜索厂商、模型、Base URL'), { target: { value: '3.5 flash' } })
    fireEvent.click(screen.getByRole('button', { name: /Gemini 3.5 Flash Vertex/ }))

    expect(onApplyApiPreset).toHaveBeenCalledWith(vertex35Preset)
    expect(document.querySelector('option[value="gemini-3.5-flash"]')).not.toBeNull()
  })

  it('shows Hermes Grok 4.5 as local OAuth without an API key field', () => {
    const onCheckHermes = vi.fn()
    const onStartHermes = vi.fn()
    renderPanel({
      apiConfig: {
        ...apiConfig,
        provider: 'openai-compatible',
        base_url: hermesPreset.base_url,
        model: hermesPreset.model,
        capabilities: hermesPreset.capabilities,
      },
      featuredApiPresets: [hermesPreset, mimoPreset],
      hermesStatus: {
        state: 'stopped',
        message: 'Hermes 与 xAI OAuth 已就绪，代理尚未启动。',
        base_url: hermesPreset.base_url,
        model: hermesPreset.model,
        managed: false,
        authenticated: true,
      },
      onCheckHermes,
      onStartHermes,
    })

    expect(screen.getByRole('status', { name: 'Hermes 本机代理状态' })).toBeInTheDocument()
    expect(screen.getByText('代理待启动')).toBeInTheDocument()
    expect(screen.queryByLabelText('API Key')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '检测状态' }))
    fireEvent.click(screen.getByRole('button', { name: '启动代理' }))
    expect(onCheckHermes).toHaveBeenCalledOnce()
    expect(onStartHermes).toHaveBeenCalledOnce()
  })

  it('toggles capabilities and saves the current model profile', () => {
    const onPatchApi = vi.fn()
    const onSaveApiProfile = vi.fn()
    renderPanel({ onPatchApi, onSaveApiProfile, showCapabilities: true })

    fireEvent.click(screen.getByRole('button', { name: /structured_json/ }))
    fireEvent.click(screen.getByRole('button', { name: /保存模型方案/ }))

    expect(onPatchApi).toHaveBeenCalledWith({ capabilities: [] })
    expect(onSaveApiProfile).toHaveBeenCalledOnce()
  })
})
