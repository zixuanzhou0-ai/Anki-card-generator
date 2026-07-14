import '@testing-library/jest-dom/vitest'
import type { ComponentProps } from 'react'
import { createRef } from 'react'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  advancedApiPresets,
  advancedTtsPresets,
  defaultRequest,
  featuredApiPresets,
  featuredTtsPresets,
  mimoTextModels,
  mimoTtsModels,
  mimoTtsVoices,
  qwenTtsModels,
  qwenTtsVoices,
} from '../../domain/options'
import { SettingsDialog } from './SettingsDialog'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function renderDialog(overrides: Partial<ComponentProps<typeof SettingsDialog>> = {}) {
  const props: ComponentProps<typeof SettingsDialog> = {
    apiSettings: {
      advancedApiPresets,
      apiConfig: defaultRequest.api_config,
      apiTestMessage: '尚未测试。',
      apiTestMeta: 'provider · model',
      apiTestTitle: '尚未测试',
      apiTestTone: 'idle',
      apiTesting: false,
      apiKeySaved: false,
      activeApiProfileId: 'default',
      apiProfileDirty: false,
      apiProfileStatus: '未保存到我的模型',
      appBusy: false,
      capabilityHelp: {},
      capabilityLabels: [],
      featuredApiPresets,
      hermesChecking: false,
      hermesStarting: false,
      hermesStatus: null,
      mimoOpenAiBaseUrl: 'https://api.xiaomimimo.com/v1',
      mimoTextModels,
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
    },
    dialogRef: createRef<HTMLElement>(),
    envSettings: {
      appBusy: false,
      envRepairing: false,
      envRepairResult: null,
      envStatus: { ffmpeg: true, genanki: true, python: 'ok' },
      onCheckEnv: vi.fn(),
      onRepairEnv: vi.fn(),
    },
    motionDuration: 0,
    open: true,
    prefersReducedMotion: true,
    settingsMode: 'simple',
    settingsTab: 'api',
    ttsSettings: {
      advancedTtsPresets,
      apiConfig: defaultRequest.api_config,
      appBusy: false,
      featuredTtsPresets,
      mimoOpenAiBaseUrl: 'https://api.xiaomimimo.com/v1',
      mimoTokenPlanSgpBaseUrl: 'https://token-plan-sgp.xiaomimimo.com/v1',
      mimoTtsModels,
      mimoTtsVoices,
      qwenTtsModels,
      qwenTtsVoices,
      activeTtsProfileId: 'default',
      savedTtsProfiles: [],
      showAdvancedTts: false,
      tts: defaultRequest.api_config.tts_config,
      ttsProfileDirty: false,
      ttsKeySaved: false,
      ttsProfileStatus: '未保存到我的语音',
      ttsTestMessage: 'TTS 当前关闭。',
      ttsTestMeta: 'disabled',
      ttsTestTitle: 'TTS 未启用',
      ttsTestTone: 'idle',
      ttsTesting: false,
      onApplySavedTtsProfile: vi.fn(),
      onApplyTtsPreset: vi.fn(),
      onPatchTts: vi.fn(),
      onSaveTtsProfile: vi.fn(),
      onSetShowAdvancedTts: vi.fn(),
      onTestTts: vi.fn(),
    },
    onClose: vi.fn(),
    onRerunOnboarding: vi.fn(),
    onSettingsModeChange: vi.fn(),
    onSettingsTabChange: vi.fn(),
    ...overrides,
  }
  render(<SettingsDialog {...props} />)
  return props
}

describe('SettingsDialog', () => {
  it('switches display modes without owning or resetting configuration fields', () => {
    const props = renderDialog()

    expect(screen.getByRole('button', { name: '简单' })).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(screen.getByRole('button', { name: '高级' }))
    expect(props.onSettingsModeChange).toHaveBeenCalledWith('advanced')
  })
  it('renders the selected tab and closes from the header', () => {
    const props = renderDialog()

    fireEvent.click(screen.getByLabelText('关闭设置'))

    expect(screen.getByRole('dialog', { name: '设置' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: '模型 API' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('heading', { name: '模型 API' })).toBeInTheDocument()
    expect(props.onClose).toHaveBeenCalledOnce()
  })

  it('routes Escape through the parent close callback', () => {
    const props = renderDialog()

    fireEvent.keyDown(screen.getByRole('dialog', { name: '设置' }), { key: 'Escape' })

    expect(props.onClose).toHaveBeenCalledOnce()
  })

  it('requests tab changes without owning parent state', () => {
    const props = renderDialog({ settingsTab: 'tts' })

    fireEvent.click(screen.getByRole('tab', { name: '本地环境' }))

    expect(screen.getByRole('heading', { name: '语音 TTS' })).toBeInTheDocument()
    expect(props.onSettingsTabChange).toHaveBeenCalledWith('env')
  })

  it('summarizes API, TTS, and local environment health before the tabs', () => {
    const props = renderDialog()

    const health = screen.getByLabelText('设置状态总览')

    expect(within(health).getByText('模型 API')).toBeInTheDocument()
    expect(within(health).getByText('语音 TTS')).toBeInTheDocument()
    expect(within(health).getByText('本地环境')).toBeInTheDocument()
    expect(within(health).getAllByText('未测试')).toHaveLength(2)
    expect(within(health).getByText('开启后建议先测试 TTS。')).toBeInTheDocument()
    expect(within(health).queryByText(/只使用原声/)).not.toBeInTheDocument()

    fireEvent.click(within(health).getByRole('button', { name: /本地环境/ }))
    expect(props.onSettingsTabChange).toHaveBeenCalledWith('env')
  })

  it('keeps optional Anki integration separate from generation readiness', () => {
    renderDialog({
      envSettings: {
        appBusy: false,
        envRepairing: false,
        envRepairResult: null,
        envStatus: {
          python: '3.12',
          ffmpeg: true,
          genanki: true,
          yt_dlp: true,
          anki_installed: false,
          anki_connect: false,
          status_items: [
            { id: 'anki', label: 'Anki', status: 'blocked', detail: '未安装 Anki。' },
          ],
        },
        onCheckEnv: vi.fn(),
        onRepairEnv: vi.fn(),
      },
    })

    const health = screen.getByLabelText('设置状态总览')
    expect(within(health).getByText('基本可用')).toBeInTheDocument()
    expect(within(health).getByText('Anki 桌面端、Anki 直连还需要单独确认。')).toBeInTheDocument()
    expect(within(health).queryByText('需要处理')).not.toBeInTheDocument()
  })

  it('shows copyright and opens the GitHub repository from the about tab', () => {
    const openSpy = vi.fn()
    vi.stubGlobal('open', openSpy)

    renderDialog({ settingsTab: 'about' })

    expect(screen.getByRole('tab', { name: '关于 / 版权' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('heading', { name: 'Anki 卡片生成器' })).toBeInTheDocument()
    expect(screen.getByText('v0.9.11-beta')).toBeInTheDocument()
    expect(screen.getByText('版权所有 © 2026 Zixuan Zhou。保留所有权利。')).toBeInTheDocument()
    expect(screen.getByText(/与 Anki、AnkiWeb 或其开发团队无官方隶属关系/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /GitHub 仓库/ }))

    expect(openSpy).toHaveBeenCalledWith(
      'https://github.com/zixuanzhou0-ai/Anki-card-generator',
      '_blank',
      'noopener,noreferrer',
    )
  })
  it('closes from the frosted backdrop but keeps dialog clicks inside the modal', () => {
    const props = renderDialog()
    const overlay = document.querySelector('.settings-overlay')

    expect(overlay).not.toBeNull()

    fireEvent.click(screen.getByRole('dialog', { name: '设置' }))
    expect(props.onClose).not.toHaveBeenCalled()

    fireEvent.click(overlay as Element)
    expect(props.onClose).toHaveBeenCalledOnce()
  })
})
