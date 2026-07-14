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
    expect(screen.getByText(/模型与 TTS 只在你主动点击测试时发起请求/)).toBeVisible()
  })

  it('walks through four short steps and never fabricates readiness', () => {
    const props = renderWizard()

    fireEvent.click(screen.getByRole('button', { name: '继续' }))
    expect(screen.getByRole('heading', { name: '生成与 Anki 核验能力' })).toBeVisible()
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
})