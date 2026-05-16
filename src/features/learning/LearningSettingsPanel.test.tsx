import '@testing-library/jest-dom/vitest'
import type { ComponentProps } from 'react'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { contentOptions, defaultRequest, languageFocusOptions, levels } from '../../domain/options'
import { LearningSettingsPanel } from './LearningSettingsPanel'

afterEach(() => cleanup())

function renderPanel(overrides: Partial<ComponentProps<typeof LearningSettingsPanel>> = {}) {
  const props: ComponentProps<typeof LearningSettingsPanel> = {
    contentOptions,
    languageFocusOptions,
    levels,
    request: defaultRequest,
    onApplyCollectionPreset: vi.fn(),
    onPatchRequest: vi.fn(),
    onSelectCurrentLevel: vi.fn(),
    onToggleCollectionLevel: vi.fn(),
    onToggleContent: vi.fn(),
    onToggleLanguageFocus: vi.fn(),
    ...overrides,
  }
  render(<LearningSettingsPanel {...props} />)
  return props
}

describe('LearningSettingsPanel', () => {
  it('patches language and segment budget', () => {
    const onPatchRequest = vi.fn()
    renderPanel({ onPatchRequest, request: { ...defaultRequest, max_segments: 0 } })

    fireEvent.change(screen.getByLabelText('学习语言'), { target: { value: 'Français' } })
    fireEvent.click(screen.getByRole('button', { name: '自动' }))

    expect(onPatchRequest).toHaveBeenCalledWith({ language: 'Français' })
    expect(onPatchRequest).toHaveBeenCalledWith({ max_segments: 35 })
  })

  it('selects current level and collection presets', () => {
    const props = renderPanel()

    fireEvent.click(screen.getAllByRole('button', { name: /B2表达块/ })[0])
    fireEvent.click(screen.getByText('收录难度范围'))
    fireEvent.click(screen.getByRole('button', { name: '上下一级' }))
    const c1Buttons = screen.getAllByRole('button', { name: /C1语气和隐含义/ })
    fireEvent.click(c1Buttons[1])

    expect(props.onSelectCurrentLevel).toHaveBeenCalledWith('B2')
    expect(props.onApplyCollectionPreset).toHaveBeenCalledWith('around')
    expect(props.onToggleCollectionLevel).toHaveBeenCalledWith('C1')
  })

  it('toggles content preferences', () => {
    const props = renderPanel()

    fireEvent.click(screen.getByText('内容偏好'))
    fireEvent.click(screen.getByLabelText('日常表达'))

    expect(screen.getByText(/项已选/)).toBeVisible()
    expect(props.onToggleContent).toHaveBeenCalledWith('daily')
  })

  it('toggles language learning focus for video and URL sources', () => {
    const props = renderPanel()

    fireEvent.click(screen.getByRole('button', { name: /单词用法/ }))

    expect(screen.getByText('词伙表达 / 听力难点')).toBeVisible()
    expect(props.onToggleLanguageFocus).toHaveBeenCalledWith('vocabulary')
  })

  it('keeps document learning separate from language focus controls', () => {
    renderPanel({ request: { ...defaultRequest, source_mode: 'document' } })

    expect(screen.getByText('文档资料')).toBeVisible()
    expect(screen.getByText(/文档会单独按知识点、术语和章节结构制卡/)).toBeVisible()
    expect(screen.queryByLabelText('语言学习重点')).not.toBeInTheDocument()
  })
})
