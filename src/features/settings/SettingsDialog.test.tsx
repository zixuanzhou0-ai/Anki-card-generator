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
    dirty: false,
    saving: false,
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
    onApplyWithoutVerification: vi.fn(),
    onClose: vi.fn(),
    onDiscardChanges: vi.fn(),
    onRerunOnboarding: vi.fn(),
    onSaveAndVerify: vi.fn(),
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
    expect(props.apiSettings.onPatchApi).not.toHaveBeenCalled()
    expect(props.ttsSettings.onPatchTts).not.toHaveBeenCalled()
  })

  it('owns the only settings commit actions at dialog level', () => {
    const props = renderDialog({ dirty: true })

    expect(screen.queryByRole('button', { name: '保存模型方案' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '应用但稍后验证' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '保存并验证' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '应用但稍后验证' }))
    fireEvent.click(screen.getByRole('button', { name: '保存并验证' }))

    expect(props.onApplyWithoutVerification).toHaveBeenCalledOnce()
    expect(props.onSaveAndVerify).toHaveBeenCalledOnce()
  })

  it('uses one aggregate live region for settings and connection-test state', () => {
    renderDialog({ dirty: true })

    const liveRegions = document.querySelectorAll('[aria-live], [role="status"]')
    expect(liveRegions).toHaveLength(1)
    expect(screen.getByRole('status')).toHaveAttribute('aria-atomic', 'true')
    expect(screen.getByRole('status')).toHaveTextContent('模型 API：未测试')
    expect(screen.getByRole('status')).toHaveTextContent('更改尚未应用到制卡流程')
  })
  it('confirms before discarding a dirty settings draft', () => {
    const confirm = vi.fn().mockReturnValueOnce(false).mockReturnValueOnce(true)
    vi.stubGlobal('confirm', confirm)
    const props = renderDialog({ dirty: true })

    fireEvent.click(screen.getByLabelText('关闭设置'))
    expect(props.onDiscardChanges).not.toHaveBeenCalled()
    expect(props.onClose).not.toHaveBeenCalled()

    fireEvent.click(screen.getByLabelText('关闭设置'))
    expect(props.onDiscardChanges).toHaveBeenCalledOnce()
    expect(props.onClose).toHaveBeenCalledOnce()
    expect(confirm).toHaveBeenCalledWith('设置还有尚未应用的更改。要放弃这些更改吗？')
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

  it('keeps Tab and Shift+Tab focus inside the dialog', () => {
    renderDialog()
    const first = screen.getByRole('button', { name: '简单' })
    const last = screen.getByRole('button', { name: '保存并验证' })

    last.focus()
    fireEvent.keyDown(last, { key: 'Tab' })
    expect(first).toHaveFocus()

    first.focus()
    fireEvent.keyDown(first, { key: 'Tab', shiftKey: true })
    expect(last).toHaveFocus()
  })

  it('restores focus to the element that opened the dialog', () => {
    const trigger = document.createElement('button')
    trigger.textContent = '打开设置'
    document.body.append(trigger)
    trigger.focus()

    renderDialog()
    cleanup()

    expect(trigger).toHaveFocus()
    trigger.remove()
  })

  it('keeps dirty confirmation semantics when Escape is pressed', () => {
    const confirm = vi.fn().mockReturnValueOnce(false).mockReturnValueOnce(true)
    vi.stubGlobal('confirm', confirm)
    const props = renderDialog({ dirty: true })
    const dialog = screen.getByRole('dialog', { name: '设置' })

    fireEvent.keyDown(dialog, { key: 'Escape' })
    expect(props.onDiscardChanges).not.toHaveBeenCalled()
    expect(props.onClose).not.toHaveBeenCalled()

    fireEvent.keyDown(dialog, { key: 'Escape' })
    expect(props.onDiscardChanges).toHaveBeenCalledOnce()
    expect(props.onClose).toHaveBeenCalledOnce()
  })

  it('requests tab changes without owning parent state', () => {
    const props = renderDialog({ settingsTab: 'tts' })

    fireEvent.click(screen.getByRole('tab', { name: '本地环境' }))

    expect(screen.getByRole('heading', { name: '语音 TTS' })).toBeInTheDocument()
    expect(props.onSettingsTabChange).toHaveBeenCalledWith('env')
  })

  it('summarizes model, TTS, generation environment, and Anki as four separate cards', () => {
    const props = renderDialog()

    const health = screen.getByLabelText('设置状态总览')

    expect(within(health).getByText('模型 API')).toBeInTheDocument()
    expect(within(health).getByText('语音 TTS')).toBeInTheDocument()
    expect(within(health).getByText('本地环境')).toBeInTheDocument()
    expect(within(health).getByText('Anki')).toBeInTheDocument()
    expect(within(health).getByText('导入时检查')).toBeInTheDocument()
    expect(within(health).getAllByRole('button')).toHaveLength(4)
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
          status_items: [{ id: 'anki', label: 'Anki', status: 'blocked', detail: '未安装 Anki。' }],
        },
        onCheckEnv: vi.fn(),
        onRepairEnv: vi.fn(),
      },
    })

    const health = screen.getByLabelText('设置状态总览')
    expect(within(health).getByText('已就绪')).toBeInTheDocument()
    expect(within(health).getByText('生成、切片和 APKG 导出所需依赖已就绪。')).toBeInTheDocument()
    expect(
      within(health).getByRole('button', { name: 'Anki：需要安装，打开导入与核验区域' }),
    ).toBeInTheDocument()
    expect(within(health).queryByText(/Anki 桌面端、Anki 直连/)).not.toBeInTheDocument()
    expect(within(health).queryByText('需要处理')).not.toBeInTheDocument()
  })

  it.each([
    [{ anki_installed: true, anki_connect: true }, 'AnkiConnect 可用'],
    [{ anki_installed: true, anki_connect: false }, '导入时检查'],
    [{ anki_installed: false, anki_connect: false }, '需要安装'],
  ] as const)('shows independent Anki state %s as %s and opens import diagnostics', (ankiState, expected) => {
    const props = renderDialog({
      envSettings: {
        appBusy: false,
        envRepairing: false,
        envRepairResult: null,
        envStatus: {
          python: '3.12',
          ffmpeg: true,
          genanki: true,
          yt_dlp: true,
          ...ankiState,
        },
        onCheckEnv: vi.fn(),
        onRepairEnv: vi.fn(),
      },
    })

    const health = screen.getByLabelText('设置状态总览')
    const ankiCard = within(health).getByRole('button', {
      name: `Anki：${expected}，打开导入与核验区域`,
    })
    expect(ankiCard).toBeInTheDocument()
    expect(within(ankiCard).getByText(expected)).toBeInTheDocument()

    fireEvent.click(ankiCard)
    expect(props.onSettingsTabChange).toHaveBeenCalledWith('env')
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
