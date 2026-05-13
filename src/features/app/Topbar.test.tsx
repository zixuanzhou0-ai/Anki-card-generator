import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { Topbar } from './Topbar'

afterEach(() => cleanup())

function renderTopbar(overrides: Partial<Parameters<typeof Topbar>[0]> = {}) {
  const props: Parameters<typeof Topbar>[0] = {
    appBusy: false,
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
    fireEvent.click(screen.getByRole('button', { name: '生成卡片' }))
    fireEvent.click(screen.getByRole('button', { name: '最小化' }))

    expect(screen.getByRole('heading', { name: 'Anki 卡片生成器' })).toBeVisible()
    expect(screen.getByRole('status')).toHaveTextContent('准备生成 Anki 卡片。')
    expect(props.onOpenSettings).toHaveBeenCalledOnce()
    expect(props.onGenerate).toHaveBeenCalledOnce()
    expect(props.onWindowAction).toHaveBeenCalledWith('minimize')
  })

  it('shows project summary, export, and cancel states', () => {
    const props = renderTopbar({
      hasExportableCards: true,
      hasProject: true,
      projectSummary: {
        reviewCount: 2,
        selectedCardLabel: '6 张已选',
        segmentCount: 4,
        templateLabel: '沉浸语言 V10',
      },
      workerBusy: true,
    })

    fireEvent.click(screen.getByRole('button', { name: '取消任务' }))

    expect(screen.getByLabelText('项目摘要')).toHaveTextContent('4 个片段')
    expect(screen.queryByRole('button', { name: '导出' })).not.toBeInTheDocument()
    expect(props.onCancelCurrentWorker).toHaveBeenCalledOnce()
  })

  it('shows export when the worker is idle', () => {
    const props = renderTopbar({ hasExportableCards: true, hasProject: true })

    fireEvent.click(screen.getByRole('button', { name: '导出' }))

    expect(props.onExport).toHaveBeenCalledOnce()
  })
})
