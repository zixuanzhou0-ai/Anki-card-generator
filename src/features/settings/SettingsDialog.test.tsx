import '@testing-library/jest-dom/vitest'
import type { ComponentProps } from 'react'
import { createRef } from 'react'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { advancedApiPresets, advancedTtsPresets, defaultRequest, featuredApiPresets, featuredTtsPresets, mimoTextModels, mimoTtsModels, mimoTtsVoices } from '../../domain/options'
import { SettingsDialog } from './SettingsDialog'

afterEach(() => cleanup())

function renderDialog(overrides: Partial<ComponentProps<typeof SettingsDialog>> = {}) {
  const secretPrefs = { rememberModelKey: false, rememberTtsKey: false }
  const props: ComponentProps<typeof SettingsDialog> = {
    apiSettings: {
      advancedApiPresets,
      apiConfig: defaultRequest.api_config,
      apiTestMessage: '尚未测试。',
      apiTestMeta: 'provider · model',
      apiTestTitle: '尚未测试',
      apiTestTone: 'idle',
      apiTesting: false,
      appBusy: false,
      capabilityHelp: {},
      capabilityLabels: [],
      featuredApiPresets,
      mimoOpenAiBaseUrl: 'https://api.xiaomimimo.com/v1',
      mimoTextModels,
      secretPrefs,
      showAdvancedApi: false,
      showCapabilities: false,
      onApplyApiPreset: vi.fn(),
      onPatchApi: vi.fn(),
      onSetShowAdvancedApi: vi.fn(),
      onSetShowCapabilities: vi.fn(),
      onTestApi: vi.fn(),
      onToggleRememberModelKey: vi.fn(),
    },
    dialogRef: createRef<HTMLElement>(),
    envSettings: {
      appBusy: false,
      envStatus: { ffmpeg: true, genanki: true, python: 'ok' },
      onCheckEnv: vi.fn(),
    },
    motionDuration: 0,
    open: true,
    prefersReducedMotion: true,
    settingsTab: 'api',
    ttsSettings: {
      advancedTtsPresets,
      appBusy: false,
      featuredTtsPresets,
      mimoOpenAiBaseUrl: 'https://api.xiaomimimo.com/v1',
      mimoTokenPlanSgpBaseUrl: 'https://token-plan-sgp.xiaomimimo.com/v1',
      mimoTtsModels,
      mimoTtsVoices,
      secretPrefs,
      showAdvancedTts: false,
      tts: defaultRequest.api_config.tts_config,
      ttsTestMessage: 'TTS 当前关闭。',
      ttsTestMeta: 'disabled',
      ttsTestTitle: 'TTS 未启用',
      ttsTestTone: 'idle',
      ttsTesting: false,
      onApplyTtsPreset: vi.fn(),
      onPatchTts: vi.fn(),
      onSetShowAdvancedTts: vi.fn(),
      onTestTts: vi.fn(),
      onToggleRememberTtsKey: vi.fn(),
    },
    onClose: vi.fn(),
    onSettingsTabChange: vi.fn(),
    ...overrides,
  }
  render(<SettingsDialog {...props} />)
  return props
}

describe('SettingsDialog', () => {
  it('renders the selected tab and closes from the header', () => {
    const props = renderDialog()

    fireEvent.click(screen.getByLabelText('关闭设置'))

    expect(screen.getByRole('dialog', { name: '设置' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: '模型 API' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('heading', { name: '模型 API' })).toBeInTheDocument()
    expect(props.onClose).toHaveBeenCalledOnce()
  })

  it('requests tab changes without owning parent state', () => {
    const props = renderDialog({ settingsTab: 'tts' })

    fireEvent.click(screen.getByRole('tab', { name: '本地环境' }))

    expect(screen.getByRole('heading', { name: '语音 TTS' })).toBeInTheDocument()
    expect(props.onSettingsTabChange).toHaveBeenCalledWith('env')
  })
})
