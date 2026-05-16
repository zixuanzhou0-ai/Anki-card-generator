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
    fireEvent.click(screen.getByRole('button', { name: '双语' }))
    fireEvent.click(screen.getByRole('button', { name: /深入掌握/ }))
    fireEvent.click(screen.getByRole('button', { name: '详细答案' }))

    expect(screen.getByText('文档目标')).toBeVisible()
    expect(screen.getByText('知识吸收')).toBeVisible()
    expect(screen.queryByLabelText('文档精读语言')).not.toBeInTheDocument()
    expect(props.onToggleDocumentFocus).toHaveBeenCalledWith('examples')
    expect(props.onPatchRequest).toHaveBeenCalledWith({ document_answer_language: 'bilingual' })
    expect(props.onPatchRequest).toHaveBeenCalledWith({ document_depth: 'deep' })
    expect(props.onPatchRequest).toHaveBeenCalledWith({ document_answer_length: 'long' })
  })

  it('shows language reading settings without listening focus', () => {
    const props = renderPanel({
      request: { ...defaultRequest, source_mode: 'document', document_study_mode: 'language_reading' },
    })

    fireEvent.change(screen.getByLabelText('文档精读语言'), { target: { value: 'Français' } })
    fireEvent.click(screen.getAllByRole('button', { name: /B2表达块/ })[0])
    fireEvent.click(screen.getByRole('button', { name: /单词用法/ }))

    expect(screen.getByText(/文档精读不生成听力卡/)).toBeVisible()
    expect(screen.queryByRole('button', { name: /听力难点/ })).not.toBeInTheDocument()
    expect(props.onPatchRequest).toHaveBeenCalledWith({ language: 'Français' })
    expect(props.onSelectCurrentLevel).toHaveBeenCalledWith('B2')
    expect(props.onToggleLanguageFocus).toHaveBeenCalledWith('vocabulary')
  })
})
