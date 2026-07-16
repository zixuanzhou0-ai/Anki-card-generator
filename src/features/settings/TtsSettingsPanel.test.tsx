import '@testing-library/jest-dom/vitest'
import type { ComponentProps } from 'react'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { SavedTtsProfile, TtsConfig, TtsPreset } from '../../domain/types'
import {
  GEMINI_VERTEX_TTS_DEFAULT_MODEL,
  GEMINI_VERTEX_TTS_DEFAULT_VOICE,
  GEMINI_VERTEX_TTS_GLOBAL_BASE_URL,
} from '../../domain/ttsProviders'
import { TtsSettingsPanel } from './TtsSettingsPanel'

afterEach(() => cleanup())

const tts: TtsConfig = {
  api_key: '',
  base_url: '',
  bit_rate: 128000,
  enabled: false,
  language: 'auto',
  model: '',
  output_volume: 0.65,
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

const mimoPreset: TtsPreset = {
  base_url: 'https://token-plan-sgp.xiaomimimo.com/v1',
  id: 'mimo-token-plan-sgp-tts',
  key_hint: '复用 MIMO Key',
  label: 'MIMO SGP TTS',
  model: 'mimo-v2.5-tts',
  note: '推荐语音',
  provider: 'mimo',
  voice: 'Mia',
}

const qwenPreset: TtsPreset = {
  base_url: 'https://dashscope.aliyuncs.com/api/v1',
  id: 'qwen-tts-flash',
  key_hint: '可复用千问 Key',
  label: 'Qwen TTS Flash',
  model: 'qwen3-tts-flash',
  note: '快速语音',
  provider: 'qwen',
  voice: 'Jennifer',
}

const disabledPreset: TtsPreset = {
  base_url: '',
  id: 'disabled',
  key_hint: '不需要填写',
  label: '关闭 TTS',
  model: '',
  note: '不额外生成 AI 朗读。',
  provider: 'disabled',
  voice: '',
}

const customSpeechPreset: TtsPreset = {
  base_url: '',
  id: 'openai-speech',
  key_hint: '任意兼容 Speech Key',
  label: 'OpenAI-compatible Speech',
  model: 'gpt-4o-mini-tts',
  note: '手动填写',
  provider: 'openai-compatible',
  voice: 'alloy',
}

function renderPanel(overrides: Partial<ComponentProps<typeof TtsSettingsPanel>> = {}) {
  const props: ComponentProps<typeof TtsSettingsPanel> = {
    activeTtsProfileId: 'disabled',
    advancedTtsPresets: [qwenPreset, customSpeechPreset],
    apiConfig: {
      api_key: '',
      base_url: 'https://token-plan-sgp.xiaomimimo.com/v1',
      capabilities: ['structured_json', 'long_context'],
      model: 'mimo-v2.5-pro',
      provider: 'mimo',
      tts_config: tts,
    },
    appBusy: false,
    featuredTtsPresets: [mimoPreset],
    mimoOpenAiBaseUrl: 'https://api.xiaomimimo.com/v1',
    mimoTokenPlanSgpBaseUrl: 'https://token-plan-sgp.xiaomimimo.com/v1',
    mimoTtsModels: [{ label: 'MIMO V2.5 TTS', value: 'mimo-v2.5-tts' }],
    mimoTtsVoices: ['Mia', 'Chloe'],
    qwenTtsModels: [{ label: 'Qwen3 TTS Flash', value: 'qwen3-tts-flash' }],
    qwenTtsVoices: ['Jennifer', 'Aiden', 'Cherry', 'Serena'],
    savedTtsProfiles: [],
    showAdvancedTts: false,
    tts,
    ttsKeySaved: false,
    ttsProfileDirty: false,
    ttsProfileStatus: '未保存到我的语音',
    ttsTestMessage: 'TTS 当前关闭。',
    ttsTestMeta: 'disabled · 无模型名 · 无 voice',
    ttsTestTitle: 'TTS 未启用',
    ttsTestTone: 'idle',
    ttsTesting: false,
    onApplySavedTtsProfile: vi.fn(),
    onApplyTtsPreset: vi.fn(),
    onPatchTts: vi.fn(),
    onSaveTtsProfile: vi.fn(),
    onSetShowAdvancedTts: vi.fn(),
    onTestTts: vi.fn(),
    ...overrides,
  }
  render(<TtsSettingsPanel {...props} />)
  return props
}

describe('TtsSettingsPanel', () => {
  it('uses a searchable TTS catalog and can apply a preset', () => {
    const props = renderPanel()

    fireEvent.change(screen.getByPlaceholderText('搜索语音厂商、模型、voice'), { target: { value: 'qwen' } })
    fireEvent.click(screen.getByRole('button', { name: /Qwen TTS Flash/ }))
    fireEvent.click(screen.getByRole('button', { name: /测试 TTS/ }))

    expect(screen.getByText('语音目录')).toBeInTheDocument()
    expect(screen.getAllByText('TTS 当前关闭').length).toBeGreaterThan(0)
    expect(screen.getAllByText(/视频卡导出前需要开启整句 TTS 和表达 TTS/).length).toBeGreaterThan(0)
    expect(screen.queryByText(/只使用视频原声/)).not.toBeInTheDocument()
    expect(props.onApplyTtsPreset).toHaveBeenCalledWith(qwenPreset)
    expect(props.onTestTts).toHaveBeenCalledOnce()
  })

  it('lets the user manually add an OpenAI-compatible Speech provider', () => {
    const props = renderPanel()

    fireEvent.click(screen.getAllByRole('button', { name: /OpenAI-compatible Speech/ })[0])

    expect(props.onApplyTtsPreset).toHaveBeenCalledWith(customSpeechPreset)
  })

  it('shows saved voices at the top and applies them from the catalog', () => {
    const savedProfile: SavedTtsProfile = {
      auth: 'api_key',
      base_url: 'https://voice.example/v1',
      bit_rate: 128000,
      enabled: true,
      has_api_key: true,
      id: 'voice-mine',
      label: '我的女声',
      language: 'auto',
      last_test_ok: true,
      model: 'my-tts',
      output_volume: 0.7,
      provider: 'openai-compatible',
      sample_rate: 24000,
      updated_at: '2026-06-16T00:00:00Z',
      voice: 'my-voice',
    }
    const props = renderPanel({ activeTtsProfileId: 'voice-mine', savedTtsProfiles: [savedProfile] })

    fireEvent.click(screen.getByRole('button', { name: /我的女声/ }))

    expect(screen.getByText('我的语音')).toBeInTheDocument()
    expect(props.onApplySavedTtsProfile).toHaveBeenCalledWith('voice-mine')
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

    fireEvent.click(screen.getByLabelText(/导出时生成 AI 朗读/))

    expect(onPatchTts).toHaveBeenCalledWith({
      base_url: 'https://dashscope.aliyuncs.com/api/v1',
      enabled: true,
      model: 'qwen3-tts-flash',
      provider: 'qwen',
      voice: 'Jennifer',
    })
  })

  it('keeps provider, model, voice, and key fields directly editable when TTS is enabled', () => {
    const onPatchTts = vi.fn()
    renderPanel({ onPatchTts, tts: enabledTts })

    fireEvent.change(screen.getByLabelText(/语音服务/), { target: { value: 'grok' } })
    fireEvent.change(screen.getByLabelText(/语音模型/), { target: { value: 'custom-tts' } })
    fireEvent.change(screen.getByLabelText(/声音/), { target: { value: 'eve' } })

    expect(onPatchTts).toHaveBeenCalledWith(
      expect.objectContaining({
        base_url: 'https://api.x.ai/v1',
        enabled: true,
        provider: 'grok',
      }),
    )
    expect(onPatchTts).toHaveBeenCalledWith({ model: 'custom-tts' })
    expect(onPatchTts).toHaveBeenCalledWith({ voice: 'eve' })
    expect(screen.getByLabelText(/语音 Base URL/)).toBeInTheDocument()
    expect(screen.getByLabelText(/TTS API Key/)).toBeInTheDocument()
  })

  it('keeps low-frequency audio parameters in the advanced area', () => {
    const onPatchTts = vi.fn()
    renderPanel({ onPatchTts, showAdvancedTts: true, tts: enabledTts })

    fireEvent.change(screen.getByLabelText(/Sample Rate/), { target: { value: '48000' } })
    fireEvent.change(screen.getByLabelText(/导出 TTS 音量/), { target: { value: '0.8' } })

    expect(onPatchTts).toHaveBeenCalledWith({ sample_rate: 48000 })
    expect(onPatchTts).toHaveBeenCalledWith({ output_volume: 0.8 })
    expect(screen.getByText('导出 TTS 音量：65%')).toBeInTheDocument()
  })

  it('saves the current TTS profile', () => {
    const onSaveTtsProfile = vi.fn()
    renderPanel({ onSaveTtsProfile, tts: enabledTts })

    fireEvent.click(screen.getByRole('button', { name: /保存语音方案/ }))

    expect(onSaveTtsProfile).toHaveBeenCalledOnce()
  })

  it('patches Gemini Vertex TTS provider defaults without an API key', () => {
    const onPatchTts = vi.fn()
    renderPanel({
      onPatchTts,
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

    expect(screen.getByText('Vertex TTS 授权')).toBeInTheDocument()
    expect(screen.getByText('使用本机 gcloud OAuth')).toBeInTheDocument()
    expect(screen.queryByLabelText('TTS API Key')).not.toBeInTheDocument()
  })
  it('deletes a saved standalone TTS key without rendering its plaintext value', () => {
    const onDeleteSavedCredential = vi.fn()
    renderPanel({
      tts: {
        ...enabledTts,
        api_key: '',
        base_url: 'https://api.x.ai/v1',
        model: '',
        provider: 'grok',
        voice: 'eve',
      },
      ttsKeySaved: true,
      onDeleteSavedCredential,
    })

    const deleteButton = screen.getByRole('button', { name: '删除已保存的 Key' })
    expect(screen.getByLabelText(/TTS API Key/)).toHaveValue('')
    fireEvent.click(deleteButton)

    expect(onDeleteSavedCredential).toHaveBeenCalledOnce()
  })

  it('disables saved TTS key deletion while an operation is running', () => {
    renderPanel({
      appBusy: true,
      tts: {
        ...enabledTts,
        base_url: 'https://api.x.ai/v1',
        provider: 'grok',
        voice: 'eve',
      },
      ttsKeySaved: true,
      onDeleteSavedCredential: vi.fn(),
    })

    expect(screen.getByRole('button', { name: '删除已保存的 Key' })).toBeDisabled()
  })

  it('does not offer key deletion for OAuth-backed TTS authorization', () => {
    renderPanel({
      tts: {
        ...enabledTts,
        api_key: '',
        base_url: GEMINI_VERTEX_TTS_GLOBAL_BASE_URL,
        model: GEMINI_VERTEX_TTS_DEFAULT_MODEL,
        provider: 'gemini-vertex',
        voice: GEMINI_VERTEX_TTS_DEFAULT_VOICE,
      },
      ttsKeySaved: true,
      onDeleteSavedCredential: vi.fn(),
    })

    expect(screen.queryByRole('button', { name: '删除已保存的 Key' })).not.toBeInTheDocument()
  })
  it('keeps simple mode focused on recommended, saved, and disabled schemes', () => {
    renderPanel({
      featuredTtsPresets: [disabledPreset, mimoPreset],
      simpleMode: true,
      tts: enabledTts,
    })

    expect(screen.getByRole('button', { name: /关闭 TTS/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /MIMO SGP TTS/ })).toBeInTheDocument()
    expect(screen.getAllByText('复用当前模型授权')).toHaveLength(2)
    expect(screen.queryByPlaceholderText('搜索语音厂商、模型、voice')).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/语音服务/)).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/语音 Base URL/)).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/语音模型/)).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/声音 \/ voice_id/)).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/TTS API Key/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /OpenAI-compatible Speech/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Qwen TTS Flash/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /高级：语言/ })).not.toBeInTheDocument()
    expect(screen.queryByText('mimo-v2.5-tts')).not.toBeInTheDocument()
  })
})
