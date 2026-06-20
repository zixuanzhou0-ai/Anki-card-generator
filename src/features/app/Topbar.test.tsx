import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { Topbar } from './Topbar'

afterEach(() => cleanup())

function renderTopbar(overrides: Partial<Parameters<typeof Topbar>[0]> = {}) {
  const props: Parameters<typeof Topbar>[0] = {
    appBusy: false,
    generateLabel: '抽取学习点',
    generateDisabled: false,
    hasExportableCards: false,
    hasProject: false,
    inspectorActionLabel: '收起面板',
    inspectorActive: true,
    isCancelling: false,
    status: '准备生成 Anki 卡片。',
    statusTone: 'idle',
    workerBusy: false,
    onCancelCurrentWorker: vi.fn(),
    onDoubleClick: vi.fn(),
    onExport: vi.fn(),
    onGenerate: vi.fn(),
    onMouseDown: vi.fn(),
    onOpenSettings: vi.fn(),
    onToggleInspector: vi.fn(),
    onWindowAction: vi.fn(),
    ...overrides,
  }
  render(<Topbar {...props} />)
  return props
}

describe('Topbar', () => {
  it('renders idle actions and triggers shell commands', () => {
    const props = renderTopbar()

    fireEvent.click(screen.getByRole('button', { name: '设置' }))
    fireEvent.click(screen.getByRole('button', { name: '抽取学习点' }))
    fireEvent.click(screen.getByRole('button', { name: '最小化' }))

    expect(screen.getByRole('heading', { name: 'Anki 卡片生成器' })).toBeVisible()
    expect(screen.getByRole('status')).toHaveTextContent('准备生成 Anki 卡片。')
    expect(props.onOpenSettings).toHaveBeenCalledOnce()
    expect(props.onGenerate).toHaveBeenCalledOnce()
    expect(props.onWindowAction).toHaveBeenCalledWith('minimize')
  })

  it('shows cancel state without duplicating review metrics in the title bar', () => {
    const props = renderTopbar({
      hasExportableCards: true,
      hasProject: true,
      workerBusy: true,
    })

    fireEvent.click(screen.getByRole('button', { name: '取消任务' }))

    expect(screen.queryByLabelText('项目摘要')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '导出' })).not.toBeInTheDocument()
    expect(props.onCancelCurrentWorker).toHaveBeenCalledOnce()
  })

  it('shows export when the worker is idle', () => {
    const props = renderTopbar({ hasExportableCards: true, hasProject: true })

    fireEvent.click(screen.getByRole('button', { name: '导出' }))

    expect(props.onExport).toHaveBeenCalledOnce()
  })

  it('disables the top generate action until the current workflow can run', () => {
    const props = renderTopbar({ generateDisabled: true })

    fireEvent.click(screen.getByRole('button', { name: '抽取学习点' }))

    expect(screen.getByRole('button', { name: '抽取学习点' })).toBeDisabled()
    expect(props.onGenerate).not.toHaveBeenCalled()
  })

  it('can hide the global generate action while the review panel owns generation confirmation', () => {
    const props = renderTopbar({
      showGenerateButton: false,
      generateLabel: '生成 APKG · 12 张',
    })

    expect(screen.queryByRole('button', { name: '生成 APKG · 12 张' })).not.toBeInTheDocument()
    expect(props.onGenerate).not.toHaveBeenCalled()
  })
})
