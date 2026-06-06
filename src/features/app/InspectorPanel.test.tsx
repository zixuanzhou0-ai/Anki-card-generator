import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
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

    expect(screen.getByLabelText('制卡流程控制台')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /素材配置/ })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: /生成设置/ })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /审核导出/ })).toBeInTheDocument()
    expect(screen.getByText('1/2')).toBeInTheDocument()
    expect(screen.getAllByText('素材').length).toBeGreaterThan(0)
    expect(screen.queryByText('学习路径')).not.toBeInTheDocument()
    expect(screen.queryByText('卡片和模板')).not.toBeInTheDocument()
  })

  it('shows learning and template settings in the generation stage', () => {
    renderInspector({}, { activeWorkspaceStage: 'generate' })

    expect(screen.getByText('学习路径')).toBeInTheDocument()
    expect(screen.getByText('卡片和模板')).toBeInTheDocument()
  })

  it('forwards stage navigation actions', () => {
    const props = renderInspector()

    fireEvent.click(screen.getByRole('tab', { name: /生成设置/ }))

    expect(props.onWorkspaceStageChange).toHaveBeenCalledWith('generate')
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
    expect(screen.queryByText('学习路径')).not.toBeInTheDocument()
  })
})
