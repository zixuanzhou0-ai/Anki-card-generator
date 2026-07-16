import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { WorkflowUiSnapshot } from '../../app/workflowState'
import { Topbar } from './Topbar'

afterEach(() => cleanup())

const baseSnapshot: WorkflowUiSnapshot = {
  step: 'source',
  artifactStage: 'empty',
  heading: '添加学习素材',
  description: '选择视频或视频链接。',
  primaryAction: {
    action: 'analyze_source',
    state: 'blocked',
    primaryLabel: '选择素材后继续',
    blockers: [
      {
        id: 'source_missing',
        severity: 'blocker',
        action: 'analyze_source',
        title: '选择学习素材',
        detail: '请选择本地视频或填写可访问的视频链接。',
      },
    ],
    warnings: [],
  },
  operation: null,
  notice: null,
}

function renderTopbar(
  snapshotOverrides: Partial<WorkflowUiSnapshot> = {},
  propOverrides: Partial<Parameters<typeof Topbar>[0]> = {},
) {
  const props: Parameters<typeof Topbar>[0] = {
    inspectorActionLabel: '收起面板',
    inspectorActive: true,
    workflowUiSnapshot: {
      ...baseSnapshot,
      ...snapshotOverrides,
    },
    onCancelCurrentWorker: vi.fn(),
    onDoubleClick: vi.fn(),
    onMouseDown: vi.fn(),
    onOpenSettings: vi.fn(),
    onToggleInspector: vi.fn(),
    onWindowAction: vi.fn(),
    ...propOverrides,
  }
  render(<Topbar {...props} />)
  return props
}

describe('Topbar', () => {
  it('shows the current product step instead of inferring a page from the next action', () => {
    const props = renderTopbar({
      step: 'source',
      heading: '添加学习素材',
      primaryAction: {
        action: 'import_and_verify',
        state: 'available',
        primaryLabel: '导入 Anki 并核验',
        blockers: [],
        warnings: [],
      },
    })

    fireEvent.click(screen.getByRole('button', { name: '设置' }))
    fireEvent.click(screen.getByRole('button', { name: '最小化' }))

    expect(screen.getByRole('heading', { name: 'Anki 卡片生成器' })).toBeVisible()
    expect(screen.getByLabelText('当前步骤')).toHaveTextContent('第 1/3 步：添加学习素材')
    expect(screen.getByLabelText('当前步骤')).not.toHaveTextContent('生成并导入')
    expect(screen.getByRole('status')).toHaveTextContent('导入 Anki 并核验')
    expect(screen.queryByRole('button', { name: '导入 Anki 并核验' })).not.toBeInTheDocument()
    expect(props.onOpenSettings).toHaveBeenCalledOnce()
    expect(props.onWindowAction).toHaveBeenCalledWith('minimize')
  })

  it('owns the single primary live region for the main workspace', () => {
    renderTopbar()

    const liveRegions = document.querySelectorAll('[aria-live], [role="status"]')
    expect(liveRegions).toHaveLength(1)
    expect(liveRegions[0]).toHaveAttribute('role', 'status')
    expect(liveRegions[0]).toHaveAttribute('aria-live', 'polite')
  })
  it('pauses announcements and makes the topbar inert while a modal is open, then restores both', () => {
    renderTopbar({}, { modalActive: true })

    const modalBackground = document.querySelector('header.topbar')
    expect(modalBackground).toHaveAttribute('inert')
    expect(modalBackground).toHaveAttribute('aria-hidden', 'true')
    expect(document.querySelectorAll('[aria-live], [role="status"]')).toHaveLength(0)

    cleanup()
    renderTopbar({}, { modalActive: false })

    const restoredTopbar = document.querySelector('header.topbar')
    expect(restoredTopbar).not.toHaveAttribute('inert')
    expect(restoredTopbar).not.toHaveAttribute('aria-hidden')
    expect(document.querySelectorAll('[aria-live], [role="status"]')).toHaveLength(1)
  })
  it.each([
    ['source', '添加学习素材', '第 1/3 步：添加学习素材'],
    ['select', '选择值得复习的内容', '第 2/3 步：选择值得复习的内容'],
    ['deliver', '生成并导入', '第 3/3 步：生成并导入'],
  ] as const)('renders %s as an explicit numbered product step', (step, heading, expected) => {
    renderTopbar({ step, heading })

    expect(screen.getByLabelText('当前步骤')).toHaveTextContent(expected)
  })

  it('shows the structured blocker and uses its detail as the accessible title', () => {
    renderTopbar()

    const status = screen.getByRole('status')
    expect(status).toHaveTextContent('选择素材后继续 · 选择学习素材')
    expect(status).toHaveAttribute('title', '请选择本地视频或填写可访问的视频链接。')
    expect(status).toHaveClass('warning')
  })

  it('shows live structured task progress and a cancel action while a cancellable task runs', () => {
    const props = renderTopbar({
      step: 'deliver',
      heading: '生成并导入',
      operation: {
        schemaVersion: 1,
        id: 'generate-2',
        action: 'generate_cards',
        state: 'running',
        startedAt: 10,
        updatedAt: 20,
        cancellable: true,
        phaseLabel: '正在生成卡片正文',
        message: '正在生成第 2/5 批',
        overallPercent: 38,
      },
      primaryAction: {
        action: 'generate_cards',
        state: 'running',
        primaryLabel: '正在生成卡片…',
        blockers: [],
        warnings: [],
      },
    })

    fireEvent.click(screen.getByRole('button', { name: '取消任务' }))

    expect(screen.getByLabelText('当前步骤')).toHaveTextContent('第 3/3 步：生成并导入')
    expect(screen.getByRole('status')).toHaveTextContent('正在生成第 2/5 批')
    expect(screen.getByRole('status')).toHaveClass('working')
    expect(props.onCancelCurrentWorker).toHaveBeenCalledOnce()
  })

  it('does not offer cancellation for a non-cancellable running task', () => {
    renderTopbar({
      operation: {
        schemaVersion: 1,
        id: 'verify-1',
        action: 'import_and_verify',
        state: 'running',
        startedAt: 10,
        updatedAt: 20,
        cancellable: false,
        phaseLabel: '正在核验 Anki',
      },
      primaryAction: {
        action: 'import_and_verify',
        state: 'running',
        primaryLabel: '正在导入并核验…',
        blockers: [],
        warnings: [],
      },
    })

    expect(screen.getByRole('status')).toHaveTextContent('正在核验 Anki')
    expect(screen.queryByRole('button', { name: '取消任务' })).not.toBeInTheDocument()
  })

  it('keeps cancelling visible and disables duplicate cancellation', () => {
    renderTopbar({
      operation: {
        schemaVersion: 1,
        id: 'export-1',
        action: 'export_cards',
        state: 'cancelling',
        startedAt: 10,
        updatedAt: 20,
        cancellable: true,
        message: '正在安全停止导出…',
      },
      primaryAction: {
        action: 'export_cards',
        state: 'running',
        primaryLabel: '正在安全停止…',
        blockers: [],
        warnings: [],
      },
    })

    expect(screen.getByRole('status')).toHaveTextContent('正在安全停止导出…')
    expect(screen.getByRole('button', { name: '取消中' })).toBeDisabled()
    expect(screen.queryByRole('button', { name: '强制结束任务' })).not.toBeInTheDocument()
  })

  it('invokes the optional force-cancel action when clicked after cancellation stalls', () => {
    const onForceCancel = vi.fn()
    renderTopbar(
      {
        operation: {
          schemaVersion: 1,
          id: 'export-stuck-click',
          action: 'export_cards',
          state: 'cancelling',
          startedAt: 10,
          updatedAt: 20,
          cancellable: false,
          message: '取消已等待 10 秒。',
        },
      },
      { showForceCancel: true, onForceCancel },
    )

    fireEvent.click(screen.getByRole('button', { name: '强制结束任务' }))

    expect(onForceCancel).toHaveBeenCalledOnce()
  })

  it('keeps the optional force-cancel action operable from the keyboard', async () => {
    const user = userEvent.setup()
    const onForceCancel = vi.fn()
    renderTopbar(
      {
        operation: {
          schemaVersion: 1,
          id: 'export-stuck-keyboard',
          action: 'export_cards',
          state: 'cancelling',
          startedAt: 10,
          updatedAt: 20,
          cancellable: false,
          message: '取消已等待 10 秒。',
        },
      },
      { showForceCancel: true, onForceCancel },
    )

    const forceButton = screen.getByRole('button', { name: '强制结束任务' })
    forceButton.focus()
    await user.keyboard('{Enter}')

    expect(onForceCancel).toHaveBeenCalledOnce()
  })

  it('disables duplicate force-cancel requests while the terminal state is settling', () => {
    const onForceCancel = vi.fn()
    renderTopbar(
      {
        operation: {
          schemaVersion: 1,
          id: 'export-force-busy',
          action: 'export_cards',
          state: 'cancelling',
          startedAt: 10,
          updatedAt: 20,
          cancellable: false,
          message: '正在强制结束任务。',
        },
      },
      {
        showForceCancel: true,
        forceCancelBusy: true,
        onForceCancel,
      },
    )

    const forceButton = screen.getByRole('button', { name: '强制结束任务' })
    expect(forceButton).toBeDisabled()
    expect(forceButton).toHaveAttribute('aria-busy', 'true')
    expect(forceButton).toHaveTextContent('正在强制结束…')
    fireEvent.click(forceButton)
    expect(onForceCancel).not.toHaveBeenCalled()
  })

  it('keeps a structured failed operation visible instead of showing a ready action', () => {
    renderTopbar({
      operation: {
        schemaVersion: 1,
        id: 'tts-1',
        action: 'generate_cards',
        state: 'failed',
        startedAt: 10,
        updatedAt: 20,
        cancellable: false,
        message: '语音生成失败，未生成 APKG。',
      },
      primaryAction: {
        action: 'generate_cards',
        state: 'available',
        primaryLabel: '生成选中的 31 张',
        blockers: [],
        warnings: [],
      },
      notice: {
        id: 'older-success',
        tone: 'success',
        title: '模型连接成功',
        occurredAt: 5,
      },
    })

    const status = screen.getByRole('status')
    expect(status).toHaveTextContent('语音生成失败，未生成 APKG。')
    expect(status).not.toHaveTextContent('生成选中的 31 张')
    expect(status).toHaveClass('warning')
  })

  it('uses the structured notice tone without parsing words in its title', () => {
    renderTopbar({
      notice: {
        id: 'info-example',
        tone: 'info',
        title: '“任务已取消”只是帮助示例',
        detail: '当前没有任务被取消。',
        occurredAt: 30,
      },
      primaryAction: {
        action: 'analyze_source',
        state: 'available',
        primaryLabel: '分析素材',
        blockers: [],
        warnings: [],
      },
    })

    const status = screen.getByRole('status')
    expect(status).toHaveTextContent('“任务已取消”只是帮助示例')
    expect(status).toHaveAttribute('title', '当前没有任务被取消。')
    expect(status).toHaveClass('idle')
    expect(status).not.toHaveClass('warning')
  })

  it('reports real Anki verification only from a completed structured action', () => {
    renderTopbar({
      step: 'deliver',
      artifactStage: 'anki_verified',
      heading: '生成并导入',
      primaryAction: {
        action: 'import_and_verify',
        state: 'completed',
        primaryLabel: '已在 Anki 中核验',
        blockers: [],
        warnings: [],
      },
    })

    const status = screen.getByRole('status')
    expect(status).toHaveTextContent('已在 Anki 中核验')
    expect(status).toHaveClass('success')
  })
})
