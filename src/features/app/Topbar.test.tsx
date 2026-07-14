import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { Topbar } from './Topbar'

afterEach(() => cleanup())

function renderTopbar(overrides: Partial<Parameters<typeof Topbar>[0]> = {}) {
  const props: Parameters<typeof Topbar>[0] = {
    inspectorActionLabel: '收起面板',
    inspectorActive: true,
    isCancelling: false,
    status: '准备生成 Anki 卡片。',
    statusTone: 'idle',
    workerBusy: false,
    workflowReadiness: {
      stage: 'setup',
      canProceed: false,
      blockers: [
        {
          id: 'environment',
          stage: 'setup',
          state: 'unknown',
          title: '检查本地环境',
          detail: '本地生成环境尚未检查。',
          action: 'check_environment',
        },
      ],
      warnings: [],
      primaryActionLabel: '完成 1 项准备',
    },
    onCancelCurrentWorker: vi.fn(),
    onDoubleClick: vi.fn(),
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
  it('shows the workflow stage and unified readiness without a duplicate primary action', () => {
    const props = renderTopbar()

    fireEvent.click(screen.getByRole('button', { name: '设置' }))
    fireEvent.click(screen.getByRole('button', { name: '最小化' }))

    expect(screen.getByRole('heading', { name: 'Anki 卡片生成器' })).toBeVisible()
    expect(screen.getByLabelText('当前步骤')).toHaveTextContent('启动准备')
    expect(screen.getByRole('status')).toHaveTextContent('完成 1 项准备 · 检查本地环境')
    expect(screen.queryByRole('button', { name: /抽取学习点|生成 APKG|导出/ })).not.toBeInTheDocument()
    expect(props.onOpenSettings).toHaveBeenCalledOnce()
    expect(props.onWindowAction).toHaveBeenCalledWith('minimize')
  })

  it('shows the live operation and cancel action while the worker is running', () => {
    const props = renderTopbar({
      status: '正在生成第 2 批卡片。',
      statusTone: 'working',
      workerBusy: true,
    })

    fireEvent.click(screen.getByRole('button', { name: '取消任务' }))

    expect(screen.getByRole('status')).toHaveTextContent('正在生成第 2 批卡片。')
    expect(screen.queryByLabelText('项目摘要')).not.toBeInTheDocument()
    expect(props.onCancelCurrentWorker).toHaveBeenCalledOnce()
  })

  it('keeps cancellation feedback visible while preserving readiness as the action gate', () => {
    renderTopbar({
      status: '任务已取消，可以继续调整后重新生成。',
      statusTone: 'idle',
      workflowReadiness: {
        stage: 'generate',
        canProceed: true,
        blockers: [],
        warnings: [],
        primaryActionLabel: '生成选中的 31 张',
      },
    })

    expect(screen.getByLabelText('当前步骤')).toHaveTextContent('生成卡片')
    expect(screen.getByRole('status')).toHaveTextContent('任务已取消，可以继续调整后重新生成。')
  })

  it('keeps a failed operation visible instead of replacing it with a ready claim', () => {
    renderTopbar({
      status: 'TTS 生成失败，未生成 APKG。',
      statusTone: 'warn',
      workflowReadiness: {
        stage: 'generate',
        canProceed: true,
        blockers: [],
        warnings: [],
        primaryActionLabel: '生成选中的 31 张',
      },
    })

    expect(screen.getByRole('status')).toHaveTextContent('TTS 生成失败，未生成 APKG。')
    expect(screen.getByRole('status')).not.toHaveTextContent('生成卡片已就绪')
  })

  it('reports a ready stage without claiming Anki verification', () => {
    renderTopbar({
      workflowReadiness: {
        stage: 'export',
        canProceed: true,
        blockers: [],
        warnings: [],
        primaryActionLabel: '导出可用的 20 张',
      },
    })

    expect(screen.getByLabelText('当前步骤')).toHaveTextContent('审核导出')
    expect(screen.getByRole('status')).toHaveTextContent('审核导出已就绪')
  })

  it('reports real Anki verification only after it succeeds', () => {
    renderTopbar({
      workflowReadiness: {
        stage: 'verify',
        canProceed: true,
        blockers: [],
        warnings: [],
        primaryActionLabel: '已在 Anki 中核验',
      },
    })

    expect(screen.getByRole('status')).toHaveTextContent('已在 Anki 中核验')
  })
})