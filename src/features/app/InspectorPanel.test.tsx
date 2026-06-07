import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  cardOptions,
  contentOptions,
  defaultRequest,
  documentFocusOptions,
  languageFocusOptions,
  levels,
  selectionStrategyOptions,
  templateOptions,
} from '../../domain/options'
import type { GenerateRequest } from '../../domain/types'
import { InspectorPanel } from './InspectorPanel'

afterEach(() => cleanup())

function renderInspector(overrides: Partial<GenerateRequest> = {}, propOverrides: Partial<Parameters<typeof InspectorPanel>[0]> = {}) {
  const request: GenerateRequest = { ...defaultRequest, ...overrides }
  const props = {
    activeWorkspaceStage: 'source' as const,
    activeTemplateLabel: '沉浸语言 V10',
    appBusy: false,
    cardOptions,
    cardTypes: request.card_types,
    contentOptions,
    diagnosticCount: 0,
    documentFocusOptions,
    generatedCardCount: 0,
    hasExportableCards: false,
    hasProject: false,
    inspectorSheetOpen: false,
    languageFocusOptions,
    levels,
    previewRate: 0.75,
    readiness: [
      { id: 'source', label: '素材', done: false, detail: '待选择' },
      { id: 'api', label: 'API', done: true, detail: '已测试' },
    ],
    request,
    requestEditedDuringRun: false,
    selectedCardCount: 0,
    status: '准备生成 Anki 卡片。',
    statusTone: 'ok',
    templateId: request.template_id,
    templateOptions,
    selectionStrategyOptions,
    workerBusy: false,
    workerErrorActions: [],
    workerProgress: null,
    onApplyCollectionPreset: vi.fn(),
    onCloseSheet: vi.fn(),
    onExport: vi.fn(),
    onGenerate: vi.fn(),
    onPatchRequest: vi.fn(),
    onPreviewRateChange: vi.fn(),
    onSelectCurrentLevel: vi.fn(),
    onSelectPath: vi.fn(),
    onSelectSourceMode: vi.fn(),
    onSelectTemplate: vi.fn(),
    onToggleCardType: vi.fn(),
    onToggleCollectionLevel: vi.fn(),
    onToggleContent: vi.fn(),
    onToggleDocumentFocus: vi.fn(),
    onToggleLanguageFocus: vi.fn(),
    onWorkspaceStageChange: vi.fn(),
    onWorkerErrorAction: vi.fn(),
    ...propOverrides,
  }

  render(<InspectorPanel {...props} />)
  return props
}

describe('InspectorPanel', () => {
  it('renders the source stage first and exposes the staged workflow', () => {
    renderInspector()

    const stepper = screen.getByLabelText('制卡步骤')
    expect(screen.getByLabelText('制卡流程控制台')).toBeInTheDocument()
    expect(within(stepper).getByRole('button', { name: /素材配置/ })).toHaveAttribute('aria-current', 'step')
    expect(within(stepper).getByRole('button', { name: /学习设置/ })).toBeDisabled()
    expect(within(stepper).getByRole('button', { name: /确认生成/ })).toBeDisabled()
    expect(screen.getByText('1/2')).toBeInTheDocument()
    expect(screen.getAllByText('素材').length).toBeGreaterThan(0)
    expect(screen.queryByRole('heading', { name: '学习设置' })).not.toBeInTheDocument()
    expect(screen.queryByText('卡片和模板')).not.toBeInTheDocument()
  })

  it('shows learning and template settings in the generation stage', () => {
    renderInspector({}, { activeWorkspaceStage: 'generate' })

    const stepper = screen.getByLabelText('制卡步骤')
    expect(screen.getByRole('heading', { name: '学习设置' })).toBeInTheDocument()
    expect(screen.getByText('卡片和模板')).toBeInTheDocument()
    expect(within(stepper).getByRole('button', { name: /确认生成/ })).not.toBeDisabled()
  })

  it('uses next-step actions instead of free future navigation', () => {
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
  })

  it('starts generation from the confirm step before a project exists', () => {
    const props = renderInspector(
      {},
      {
        activeWorkspaceStage: 'review',
        readiness: [
          { id: 'source', label: '素材', done: true, detail: '已就绪' },
          { id: 'api', label: 'API', done: true, detail: '已测试' },
        ],
      },
    )

    fireEvent.click(screen.getByRole('button', { name: /开始生成卡片/ }))

    expect(props.onGenerate).toHaveBeenCalledTimes(1)
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
        readiness: [
          { id: 'source', label: '素材', done: true, detail: '已就绪' },
          { id: 'api', label: 'API', done: true, detail: '已测试' },
        ],
      },
    )

    const stepper = screen.getByLabelText('制卡步骤')
    const stageButtons = within(stepper).getAllByRole('button')
    expect(stageButtons[0]).toBeDisabled()
    expect(stageButtons[1]).toBeDisabled()
    expect(stageButtons[2]).not.toBeDisabled()
    expect(screen.getByText('正在按当前设置制作卡片')).toBeInTheDocument()
    expect(screen.getByText(/生成进度已移到右侧工作台/)).toBeInTheDocument()
  })

  it('lists unfinished preflight checks before generation', () => {
    renderInspector(
      {},
      {
        activeWorkspaceStage: 'review',
        readiness: [
          { id: 'source', label: '素材', done: true, detail: '已就绪' },
          { id: 'env', label: '环境', done: false, detail: '未检查' },
          { id: 'api', label: 'API', done: false, detail: '未测试' },
          { id: 'tts', label: 'TTS', done: false, detail: '未测试' },
          { id: 'cards', label: '卡片', done: true, detail: '3 张' },
        ],
      },
    )

    expect(screen.getByText('生成前还需要完成')).toBeInTheDocument()
    expect(screen.getByText('环境：未检查 / API：未测试 / TTS：未测试')).toBeInTheDocument()
  })

  it('forwards close and source mode actions', () => {
    const props = renderInspector()

    fireEvent.click(screen.getByRole('button', { name: '关闭素材设置' }))
    fireEvent.click(screen.getByRole('button', { name: /视频链接/ }))

    expect(props.onCloseSheet).toHaveBeenCalledTimes(1)
    expect(props.onSelectSourceMode).toHaveBeenCalledWith('url')
  })

  it('uses document target panel instead of language learning panel for document source', () => {
    renderInspector({ source_mode: 'document' }, { activeWorkspaceStage: 'generate' })

    expect(screen.getByText('文档目标')).toBeVisible()
    expect(screen.getByText('知识吸收')).toBeVisible()
    expect(screen.queryByRole('heading', { name: '学习设置' })).not.toBeInTheDocument()
  })
})
