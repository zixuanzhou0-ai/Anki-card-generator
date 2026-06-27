import '@testing-library/jest-dom/vitest'
import type { ComponentProps } from 'react'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { defaultRequest, documentFocusOptions, languageFocusOptions, levels } from '../../domain/options'
import { DocumentStudyPanel } from './DocumentStudyPanel'

afterEach(() => cleanup())

function renderPanel(overrides: Partial<ComponentProps<typeof DocumentStudyPanel>> = {}) {
  const props: ComponentProps<typeof DocumentStudyPanel> = {
    documentFocusOptions,
    languageFocusOptions,
    levels,
    request: { ...defaultRequest, source_mode: 'document' },
    onPatchRequest: vi.fn(),
    onSelectCurrentLevel: vi.fn(),
    onToggleDocumentFocus: vi.fn(),
    onToggleLanguageFocus: vi.fn(),
    ...overrides,
  }
  render(<DocumentStudyPanel {...props} />)
  return props
}

describe('DocumentStudyPanel', () => {
  it('defaults to knowledge absorption controls', () => {
    const props = renderPanel()

    fireEvent.click(screen.getByRole('button', { name: /例子案例/ }))
    fireEvent.click(screen.getByText('答案语言'))
    fireEvent.click(screen.getByRole('button', { name: /双语/ }))
    fireEvent.click(screen.getByRole('button', { name: /深入掌握/ }))
    fireEvent.click(screen.getByRole('button', { name: '详细答案' }))

    expect(screen.getByText('文档目标')).toBeVisible()
    expect(screen.getByText('推荐路径')).toBeVisible()
    expect(screen.getByText('知识吸收 · 标准理解 · 中等答案')).toBeVisible()
    expect(screen.getByText(/一张卡只记一个可回忆点/)).toBeVisible()
    expect(screen.getByText('知识吸收')).toBeVisible()
    expect(screen.getByText('知识卡重点')).toBeVisible()
    expect(screen.getByText('答案语言')).toBeVisible()
    expect(screen.getByText('答案/解析语言')).toBeVisible()
    expect(screen.queryByText('讲解语言')).not.toBeInTheDocument()
    expect(screen.getByText('理解深度')).toBeVisible()
    expect(screen.queryByText('文档吸收设置')).not.toBeInTheDocument()
    expect(screen.queryByText('卡片深度')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('文档精读语言')).not.toBeInTheDocument()
    expect(props.onToggleDocumentFocus).toHaveBeenCalledWith('examples')
    expect(props.onPatchRequest).toHaveBeenCalledWith({ document_answer_language: 'bilingual' })
    expect(props.onPatchRequest).toHaveBeenCalledWith({ document_depth: 'deep' })
    expect(props.onPatchRequest).toHaveBeenCalledWith({ document_answer_length: 'long' })
  })

  it('keeps extra answer languages in advanced document controls', () => {
    const props = renderPanel()

    fireEvent.click(screen.getByText('答案语言'))
    fireEvent.change(screen.getByLabelText('更多答案语言'), { target: { value: 'ja' } })

    expect(screen.getByText(/自动识别原文/)).toBeVisible()
    expect(screen.getByRole('option', { name: '日本語' })).toBeInTheDocument()
    expect(props.onPatchRequest).toHaveBeenCalledWith({ document_answer_language: 'ja' })
  })

  it('shows language reading settings without listening focus', () => {
    const props = renderPanel({
      request: { ...defaultRequest, source_mode: 'document', document_study_mode: 'language_reading' },
    })

    expect(screen.getByRole('option', { name: 'Русский' })).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('文档精读语言'), { target: { value: 'fr' } })
    fireEvent.click(screen.getAllByRole('button', { name: /B2表达块/ })[0])
    fireEvent.click(screen.getByRole('button', { name: /单词用法/ }))

    expect(screen.getByText(/文档精读不生成视频\/TTS 学习卡/)).toBeVisible()
    expect(screen.queryByRole('button', { name: /听力难点/ })).not.toBeInTheDocument()
    expect(props.onPatchRequest).toHaveBeenCalledWith({ language: 'fr' })
    expect(props.onSelectCurrentLevel).toHaveBeenCalledWith('B2')
    expect(props.onToggleLanguageFocus).toHaveBeenCalledWith('vocabulary')
  })

  it('filters hidden listening focus when switching to language reading', () => {
    const props = renderPanel({
      request: { ...defaultRequest, source_mode: 'document', language_focus: ['phrases', 'listening'] },
    })

    fireEvent.click(screen.getByRole('button', { name: /语言精读/ }))

    expect(props.onPatchRequest).toHaveBeenCalledWith({
      document_study_mode: 'language_reading',
      language_focus: ['phrases'],
    })
  })
})
