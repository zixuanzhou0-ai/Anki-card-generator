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
  templateOptions,
} from '../../domain/options'
import type { GenerateRequest } from '../../domain/types'
import { InspectorPanel } from './InspectorPanel'

afterEach(() => cleanup())

function renderInspector(overrides: Partial<GenerateRequest> = {}) {
  const request: GenerateRequest = { ...defaultRequest, ...overrides }
  const props = {
    activeTemplateLabel: '沉浸语言 V10',
    appBusy: false,
    cardOptions,
    cardTypes: request.card_types,
    contentOptions,
    documentFocusOptions,
    inspectorSheetOpen: false,
    languageFocusOptions,
    levels,
    readiness: [
      { id: 'source', label: '素材', done: false, detail: '待选择' },
      { id: 'api', label: 'API', done: true, detail: '已测试' },
    ],
    request,
    requestEditedDuringRun: false,
    status: '准备生成 Anki 卡片。',
    statusTone: 'ok',
    templateId: request.template_id,
    templateOptions,
    workerBusy: false,
    workerErrorActions: [],
    workerProgress: null,
    onApplyCollectionPreset: vi.fn(),
    onCloseSheet: vi.fn(),
    onPatchRequest: vi.fn(),
    onSelectCurrentLevel: vi.fn(),
    onSelectPath: vi.fn(),
    onSelectSourceMode: vi.fn(),
    onSelectTemplate: vi.fn(),
    onToggleCardType: vi.fn(),
    onToggleCollectionLevel: vi.fn(),
    onToggleContent: vi.fn(),
    onToggleDocumentFocus: vi.fn(),
    onToggleLanguageFocus: vi.fn(),
    onWorkerErrorAction: vi.fn(),
  }

  render(<InspectorPanel {...props} />)
  return props
}

describe('InspectorPanel', () => {
  it('renders source, readiness, learning, and template sections', () => {
    renderInspector()

    expect(screen.getByLabelText('素材和生成设置')).toBeInTheDocument()
    expect(screen.getByText('1/2')).toBeInTheDocument()
    expect(screen.getAllByText('素材').length).toBeGreaterThan(0)
    expect(screen.getByText('学习设置')).toBeInTheDocument()
    expect(screen.getByText('卡片和模板')).toBeInTheDocument()
  })

  it('forwards close and source mode actions', () => {
    const props = renderInspector()

    fireEvent.click(screen.getByRole('button', { name: '关闭素材设置' }))
    fireEvent.click(screen.getByRole('button', { name: /视频链接/ }))

    expect(props.onCloseSheet).toHaveBeenCalledTimes(1)
    expect(props.onSelectSourceMode).toHaveBeenCalledWith('url')
  })

  it('uses document target panel instead of language learning panel for document source', () => {
    renderInspector({ source_mode: 'document' })

    expect(screen.getByText('文档目标')).toBeVisible()
    expect(screen.getByText('知识吸收')).toBeVisible()
    expect(screen.queryByText('学习设置')).not.toBeInTheDocument()
  })
})
