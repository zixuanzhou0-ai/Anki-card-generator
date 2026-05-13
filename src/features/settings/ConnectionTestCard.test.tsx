import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ConnectionTestCard } from './ConnectionTestCard'

describe('ConnectionTestCard', () => {
  it('renders an idle test action', () => {
    const onTest = vi.fn()

    render(
      <ConnectionTestCard
        buttonLabel="测试连接"
        disabled={false}
        message="尚未测试。"
        meta="mimo · model"
        statusLabel="连接状态"
        testing={false}
        testingLabel="测试中..."
        title="未测试"
        tone="idle"
        onTest={onTest}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /测试连接/ }))

    expect(screen.getByText('连接状态')).toBeInTheDocument()
    expect(screen.getByText('mimo · model')).toBeInTheDocument()
    expect(onTest).toHaveBeenCalledOnce()
  })

  it('disables the action while testing', () => {
    render(
      <ConnectionTestCard
        buttonLabel="测试 TTS"
        disabled
        message="正在测试。"
        meta="mimo · Mia"
        ok={undefined}
        statusLabel="TTS 状态"
        testing
        testingLabel="测试中..."
        title="测试中"
        tone="running"
        onTest={vi.fn()}
      />,
    )

    expect(screen.getByRole('button', { name: /测试中/ })).toBeDisabled()
  })
})
