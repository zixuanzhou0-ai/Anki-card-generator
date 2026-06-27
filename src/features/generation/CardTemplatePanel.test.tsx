import '@testing-library/jest-dom/vitest'
import type { ComponentProps } from 'react'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { CardTemplatePanel } from './CardTemplatePanel'

afterEach(() => cleanup())

function renderPanel(overrides: Partial<ComponentProps<typeof CardTemplatePanel>> = {}) {
  const props: ComponentProps<typeof CardTemplatePanel> = {
    documentStudyMode: 'knowledge',
    sourceMode: 'local',
    reviewDensity: 'full',
    onSelectReviewDensity: vi.fn(),
    onSelectTemplate: vi.fn(),
    ...overrides,
  }
  render(<CardTemplatePanel {...props} />)
  return props
}

describe('CardTemplatePanel', () => {
  it('shows only complete and fast repetition modes for video cards', () => {
    renderPanel()

    const modeGroup = screen.getByRole('radiogroup', { name: /选择卡片模式/ })

    expect(screen.getByText('卡片模式')).toBeVisible()
    expect(within(modeGroup).getAllByRole('radio')).toHaveLength(2)
    expect(within(modeGroup).getByRole('radio', { name: /完整复读/ })).toBeVisible()
    expect(within(modeGroup).getByRole('radio', { name: /快速复读/ })).toBeVisible()
    expect(screen.getByText('完整解释、用法、边界和听辨提示')).toBeVisible()
    expect(screen.getByText('只保留原句、中文意思、视频、原声、慢读和表达发音')).toBeVisible()
    expect(screen.queryByText('沉浸复读')).not.toBeInTheDocument()
    expect(screen.queryByText('高级 / 实验模板')).not.toBeInTheDocument()
    expect(screen.queryByText('模板选择')).not.toBeInTheDocument()
    expect(screen.queryByText('词霸天下实验 V1')).not.toBeInTheDocument()
    expect(screen.queryByText('词霸卡面风格')).not.toBeInTheDocument()
  })

  it('selecting fast repetition forces immersive v11 and fast density', () => {
    const props = renderPanel()

    fireEvent.click(screen.getByRole('radio', { name: /快速复读/ }))

    expect(props.onSelectTemplate).toHaveBeenCalledWith('immersive_v11')
    expect(props.onSelectReviewDensity).toHaveBeenCalledWith('fast')
  })

  it('selecting complete repetition forces immersive v11 and full density', () => {
    const props = renderPanel({ reviewDensity: 'fast' })

    fireEvent.click(screen.getByRole('radio', { name: /完整复读/ }))

    expect(props.onSelectTemplate).toHaveBeenCalledWith('immersive_v11')
    expect(props.onSelectReviewDensity).toHaveBeenCalledWith('full')
  })

  it('renders document mode as knowledge card only', () => {
    renderPanel({ sourceMode: 'document' })

    expect(screen.getAllByText('知识问答卡')[1]).toBeVisible()
    expect(screen.getByText('正面是问题或概念提示，反面是结构化答案、解释、例子和为什么值得记。')).toBeVisible()
    expect(screen.queryByRole('radiogroup', { name: /选择卡片模式/ })).not.toBeInTheDocument()
    expect(screen.queryByText('完整复读')).not.toBeInTheDocument()
    expect(screen.queryByText('快速复读')).not.toBeInTheDocument()
  })

  it('renders document language reading card copy', () => {
    renderPanel({ documentStudyMode: 'language_reading', sourceMode: 'document' })

    expect(screen.getAllByText('文档精读卡')[1]).toBeVisible()
    expect(screen.getByText('从文档里提取表达、词汇或语法点；不生成视频/TTS 学习卡，可导出项可一键选择。')).toBeVisible()
  })
})
