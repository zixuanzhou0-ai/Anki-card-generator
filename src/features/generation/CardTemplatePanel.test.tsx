import '@testing-library/jest-dom/vitest'
import type { ComponentProps } from 'react'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { cardOptions, templateOptions } from '../../domain/options'
import { CardTemplatePanel } from './CardTemplatePanel'

afterEach(() => cleanup())

function renderPanel(overrides: Partial<ComponentProps<typeof CardTemplatePanel>> = {}) {
  const props: ComponentProps<typeof CardTemplatePanel> = {
    activeTemplateLabel: '沉浸语言 V10',
    cardOptions,
    cardTypes: ['listening', 'phrase'],
    sourceMode: 'local',
    templateId: 'immersive',
    templateOptions,
    onSelectTemplate: vi.fn(),
    onToggleCardType: vi.fn(),
    ...overrides,
  }
  render(<CardTemplatePanel {...props} />)
  return props
}

describe('CardTemplatePanel', () => {
  it('toggles card types and selects unlocked templates', () => {
    const props = renderPanel()

    fireEvent.click(screen.getByText('卡片和模板'))
    fireEvent.click(screen.getByRole('button', { name: /填空卡/ }))
    fireEvent.click(screen.getByRole('button', { name: /沉浸语言 V10/ }))

    expect(screen.getByText('2 类 · 沉浸语言 V10')).toBeVisible()
    expect(props.onToggleCardType).toHaveBeenCalledWith('cloze')
    expect(props.onSelectTemplate).toHaveBeenCalledWith('immersive')
  })

  it('renders document mode as knowledge card only', () => {
    renderPanel({ sourceMode: 'document' })

    fireEvent.click(screen.getByText('卡片和模板'))

    expect(screen.getAllByText('知识点卡')[1]).toBeVisible()
    expect(screen.getByText('正面是问题或概念提示，反面是结构化答案、解释、例子和为什么值得记。')).toBeVisible()
  })

  it('does not select locked templates', () => {
    const props = renderPanel()

    fireEvent.click(screen.getByText('卡片和模板'))
    fireEvent.click(screen.getByRole('button', { name: /词典解释/ }))

    expect(screen.getByRole('button', { name: /词典解释/ })).toBeDisabled()
    expect(props.onSelectTemplate).not.toHaveBeenCalledWith('dictionary')
  })
})
