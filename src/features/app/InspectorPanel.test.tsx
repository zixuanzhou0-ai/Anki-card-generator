import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { buildWorkflowReadiness } from '../../app/readiness'
import { defaultRequest, levels } from '../../domain/options'
import type { GenerateRequest } from '../../domain/types'
import { InspectorPanel } from './InspectorPanel'

afterEach(() => cleanup())

function renderInspector(
  overrides: Partial<GenerateRequest> = {},
  propOverrides: Partial<Parameters<typeof InspectorPanel>[0]> = {},
) {
  const request: GenerateRequest = { ...defaultRequest, ...overrides }
  const readiness =
    propOverrides.readiness ??
    [
      { id: 'source', label: '素材', done: false, detail: '待选择' },
      { id: 'api', label: 'API', done: true, detail: '已测试' },
    ]
  const sourceReady = readiness.find((item) => item.id === 'source')?.done ?? false
  const workflowReadiness =
    propOverrides.workflowReadiness ??
    buildWorkflowReadiness({
      sourceReady,
      environmentReady: true,
      environmentChecked: true,
      apiProvider: 'openai',
      apiReady: true,
      apiTested: true,
      ttsRequired: false,
      ttsReady: true,
      ttsTested: true,
      selectedLearningPointCount: propOverrides.selectedLearningPointCount ?? 0,
      hasLearningPoints: propOverrides.hasLearningPointResult ?? false,
      hasProject: propOverrides.hasProject ?? false,
      exportableCardCount: propOverrides.selectedExportableCardCount ?? 0,
      repairRequiredCardCount: propOverrides.repairRequiredCardCount ?? 0,
      hasExport: false,
      ankiVerified: false,
    })
  const props: Parameters<typeof InspectorPanel>[0] = {
    activeWorkspaceStage: 'source',
    appBusy: false,
    diagnosticCount: 0,
    generatedCardCount: 0,
    hasExportableCards: false,
    hasLearningPointResult: false,
    hasProject: false,
    inspectorSheetOpen: false,
    levels,
    previewRate: 0.75,
    readiness,
    workflowReadiness,
    request,
    requestEditedDuringRun: false,
    selectedCardCount: 0,
    selectedLearningPointCount: 0,
    status: '准备生成 Anki 卡片。',
    statusTone: 'ok',
    workerBusy: false,
    workerErrorActions: [],
    workerProgress: null,
    onCloseSheet: vi.fn(),
    onExport: vi.fn(),
    onExtractLearningPointsWithoutCache: vi.fn(),
    onGenerate: vi.fn(),
    onPatchRequest: vi.fn(),
    onPreviewRateChange: vi.fn(),
    onResolveReadiness: vi.fn(),
    onSelectCurrentLevel: vi.fn(),
    onSelectPath: vi.fn(),
    onSelectSourceMode: vi.fn(),
    onSelectTemplate: vi.fn(),
    onWorkspaceStageChange: vi.fn(),
    onWorkerErrorAction: vi.fn(),
    ...propOverrides,
  }

  render(<InspectorPanel {...props} />)
  return props
}

describe('InspectorPanel', () => {
  it('renders the source stage and exposes the persistent startup check', () => {
    renderInspector()

    const stepper = screen.getByLabelText('制卡步骤')
    expect(screen.getByLabelText('制卡流程控制台')).toBeInTheDocument()
    expect(screen.getByLabelText('启动检查台')).toHaveTextContent('1 项准备未完成')
    expect(within(stepper).getByRole('button', { name: /素材配置/ })).toHaveAttribute('aria-current', 'step')
    expect(within(stepper).getByRole('button', { name: /学习设置/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /选择素材后继续/ })).toBeDisabled()
  })

  it('uses next-step navigation once a source is ready', () => {
    const props = renderInspector(
      {},
      {
        readiness: [
          { id: 'source', label: '素材', done: true, detail: '已就绪' },
          { id: 'api', label: 'API', done: true, detail: '已测试' },
        ],
      },
    )

    fireEvent.click(screen.getByRole('button', { name: /下一步：学习设置/ }))
    expect(props.onWorkspaceStageChange).toHaveBeenCalledWith('generate')
    expect(screen.getByLabelText('启动检查台')).toHaveTextContent('当前阶段已就绪')
  })

  it('shows learning and template settings in the second stage', () => {
    renderInspector({}, { activeWorkspaceStage: 'generate' })

    expect(screen.getByRole('heading', { name: '学习设置' })).toBeInTheDocument()
    expect(screen.getByText('卡片模式')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /下一步：确认抽取/ })).toBeEnabled()
  })

  it('starts extraction only when the unified readiness snapshot allows it', () => {
    const props = renderInspector(
      {},
      {
        activeWorkspaceStage: 'review',
        readiness: [{ id: 'source', label: '素材', done: true, detail: '已就绪' }],
      },
    )

    const action = screen.getByRole('button', { name: '开始抽取学习点' })
    expect(action).toBeEnabled()
    fireEvent.click(action)
    expect(props.onGenerate).toHaveBeenCalledOnce()
  })

  it('exposes the unique repair action for each blocker', () => {
    const onResolveReadiness = vi.fn()
    renderInspector(
      {},
      {
        activeWorkspaceStage: 'review',
        readiness: [{ id: 'source', label: '素材', done: true, detail: '已就绪' }],
        workflowReadiness: {
          stage: 'setup',
          canProceed: false,
          blockers: [
            {
              id: 'environment',
              stage: 'setup',
              state: 'unknown',
              title: '检查本地环境',
              detail: '本地环境尚未检查。',
              action: 'check_environment',
            },
            {
              id: 'api',
              stage: 'setup',
              state: 'unknown',
              title: '测试模型连接',
              detail: '模型尚未测试。',
              action: 'test_api',
            },
          ],
          warnings: [],
          primaryActionLabel: '完成 2 项准备',
        },
        onResolveReadiness,
      },
    )

    expect(screen.getAllByText('完成 2 项准备').length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: '完成 2 项准备' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '立即检查' }))
    fireEvent.click(screen.getByRole('button', { name: '配置并测试模型' }))
    expect(onResolveReadiness).toHaveBeenNthCalledWith(1, 'check_environment')
    expect(onResolveReadiness).toHaveBeenNthCalledWith(2, 'test_api')
  })

  it('keeps no-cache analysis secondary and hides it for batch packages', () => {
    const first = renderInspector(
      {},
      {
        activeWorkspaceStage: 'review',
        readiness: [{ id: 'source', label: '素材', done: true, detail: '已就绪' }],
      },
    )
    fireEvent.click(screen.getByRole('button', { name: '不使用缓存抽取学习点' }))
    expect(first.onExtractLearningPointsWithoutCache).toHaveBeenCalledOnce()

    cleanup()
    renderInspector(
      {
        batch_enabled: true,
        batch_items: [
          {
            id: 'ep1',
            source_mode: 'local',
            enabled: true,
            title: 'S01E01',
            subdeck_title: 'S01E01',
            video_path: 'E:/Shows/S01E01.mp4',
          },
        ],
      },
      {
        activeWorkspaceStage: 'review',
        readiness: [{ id: 'source', label: '素材', done: true, detail: '已就绪' }],
      },
    )
    expect(screen.queryByRole('button', { name: '不使用缓存抽取学习点' })).not.toBeInTheDocument()
  })

  it('locks earlier workflow steps while generation is running', () => {
    renderInspector(
      {},
      {
        activeWorkspaceStage: 'review',
        appBusy: true,
        workerBusy: true,
        workerProgress: {
          command: 'generate',
          stage: 'ai',
          percent: 42,
          message: '正在生成卡片正文。',
        },
      },
    )

    const stageButtons = within(screen.getByLabelText('制卡步骤')).getAllByRole('button')
    expect(stageButtons[0]).toBeDisabled()
    expect(stageButtons[1]).toBeDisabled()
    expect(stageButtons[2]).toBeEnabled()
    expect(screen.getByText('正在生成 APKG')).toBeInTheDocument()
  })

  it('forwards close and source mode actions', () => {
    const props = renderInspector()

    fireEvent.click(screen.getByRole('button', { name: '关闭素材设置' }))
    fireEvent.click(screen.getByRole('button', { name: /视频链接/ }))

    expect(props.onCloseSheet).toHaveBeenCalledOnce()
    expect(props.onSelectSourceMode).toHaveBeenCalledWith('url')
  })
})