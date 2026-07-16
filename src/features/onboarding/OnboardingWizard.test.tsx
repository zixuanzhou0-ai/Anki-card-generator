import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { OnboardingWizard } from './OnboardingWizard'

afterEach(() => cleanup())

function renderWizard() {
  const props: Parameters<typeof OnboardingWizard>[0] = {
    apiReady: false,
    envStatus: null,
    open: true,
    ttsReady: false,
    ttsRequired: true,
    onCheckEnv: vi.fn(),
    onComplete: vi.fn(),
    onOpenApiSettings: vi.fn(),
    onOpenTtsSettings: vi.fn(),
    onSkip: vi.fn(),
  }
  render(<OnboardingWizard {...props} />)
  return props
}

describe('OnboardingWizard', () => {
  it('automatically performs only the local read-only check', () => {
    const props = renderWizard()

    expect(props.onCheckEnv).toHaveBeenCalledOnce()
    expect(props.onOpenApiSettings).not.toHaveBeenCalled()
    expect(props.onOpenTtsSettings).not.toHaveBeenCalled()
    expect(document.querySelectorAll('[aria-live], [role="status"]')).toHaveLength(1)
    expect(screen.getByRole('status')).toHaveTextContent('当前是欢迎与隐私说明')
    expect(screen.getByText(/模型与 TTS 只在你主动点击测试时发起请求/)).toBeVisible()
  })

  it('walks through four short steps and never fabricates readiness', () => {
    const props = renderWizard()

    fireEvent.click(screen.getByRole('button', { name: '继续' }))
    expect(screen.getByRole('heading', { name: '生成与 Anki 核验能力' })).toBeVisible()
    expect(screen.getByRole('status')).toHaveTextContent('本地环境：正在检查核心生成依赖')
    expect(document.querySelectorAll('[aria-live], [role="status"]')).toHaveLength(1)
    expect(screen.getByText(/继续不会伪造完成状态/)).toBeVisible()

    fireEvent.click(screen.getByRole('button', { name: '继续' }))
    expect(screen.getByRole('heading', { name: '优先使用本机 Hermes Grok 4.5' })).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: '配置并测试模型' }))
    expect(props.onOpenApiSettings).toHaveBeenCalledOnce()

    fireEvent.click(screen.getByRole('button', { name: '继续' }))
    expect(screen.getByText('TTS 尚未验证')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: '进入素材选择' }))
    expect(props.onComplete).toHaveBeenCalledOnce()
  })

  it('allows deferring without claiming setup is complete', () => {
    const props = renderWizard()
    fireEvent.click(screen.getByRole('button', { name: '稍后设置' }))
    expect(props.onSkip).toHaveBeenCalledOnce()
    expect(props.onComplete).not.toHaveBeenCalled()
  })

  it('keeps Tab and Shift+Tab focus inside the wizard', () => {
    renderWizard()
    const first = screen.getByRole('button', { name: '稍后设置' })
    const last = screen.getByRole('button', { name: '继续' })

    last.focus()
    fireEvent.keyDown(last, { key: 'Tab' })
    expect(first).toHaveFocus()

    first.focus()
    fireEvent.keyDown(first, { key: 'Tab', shiftKey: true })
    expect(last).toHaveFocus()
  })

  it('routes Escape to defer setup', () => {
    const props = renderWizard()

    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })

    expect(props.onSkip).toHaveBeenCalledOnce()
  })

  it('restores focus to the element that opened the wizard', () => {
    const trigger = document.createElement('button')
    trigger.textContent = '重新运行启动检查'
    document.body.append(trigger)
    trigger.focus()

    renderWizard()
    cleanup()

    expect(trigger).toHaveFocus()
    trigger.remove()
  })
})
