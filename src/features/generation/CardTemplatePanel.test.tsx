import '@testing-library/jest-dom/vitest'
import type { ComponentProps } from 'react'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { templateOptions } from '../../domain/options'
import { CardTemplatePanel } from './CardTemplatePanel'

afterEach(() => cleanup())

function renderPanel(overrides: Partial<ComponentProps<typeof CardTemplatePanel>> = {}) {
  const props: ComponentProps<typeof CardTemplatePanel> = {
    activeTemplateLabel: '沉浸复读 V11',
    cardStyleId: 'warm_paper',
    documentStudyMode: 'knowledge',
    sourceMode: 'local',
    templateId: 'immersive_v11',
    templateOptions,
    reviewDensity: 'full',
    onSelectCardStyle: vi.fn(),
    onSelectReviewDensity: vi.fn(),
    onSelectTemplate: vi.fn(),
    ...overrides,
  }
  render(<CardTemplatePanel {...props} />)
  return props
}


describe('CardTemplatePanel', () => {
  it('makes the card/template summary clearly expandable', () => {
    renderPanel({
      activeTemplateLabel: '词霸天下实验 V1',
      cardStyleId: 'minimal_white',
      templateId: 'ciba_tianxia_v1',
    })

    expect(screen.getByText('卡片和模板')).toBeVisible()
    expect(screen.getByText('词霸天下实验 V1 · 极简白卡')).toBeVisible()
    expect(screen.getByText('展开')).toBeVisible()

    fireEvent.click(screen.getByText('卡片和模板'))

    expect(screen.getByText('收起')).toBeVisible()
  })

  it('shows learning templates without exposing low-level card types for immersive V11', () => {
    const props = renderPanel()

    fireEvent.click(screen.getByText('卡片和模板'))
    fireEvent.click(screen.getByRole('radio', { name: /沉浸复读 V11/ }))

    expect(screen.getByRole('radio', { name: /沉浸复读 V11/ })).toBeVisible()
    expect(screen.getByText('学习模板')).toBeVisible()
    expect(screen.getByText('单选')).toBeVisible()
    expect(screen.getByText('沉浸复读 V11 使用稳定卡面；视觉风格只在词霸天下实验 V1 中生效。')).toBeVisible()
    expect(screen.queryByText('视觉风格')).not.toBeInTheDocument()
    expect(screen.queryByText('词霸卡面风格')).not.toBeInTheDocument()
    expect(screen.queryByRole('radiogroup', { name: /选择词霸卡面风格/ })).not.toBeInTheDocument()
    expect(screen.queryByText('卡型')).not.toBeInTheDocument()
    expect(screen.queryByText('可多选')).not.toBeInTheDocument()
    expect(screen.queryByText('听力卡')).not.toBeInTheDocument()
    expect(screen.queryByText('表达/语境生词卡')).not.toBeInTheDocument()
    expect(screen.queryByText('填空卡')).not.toBeInTheDocument()
    expect(props.onSelectTemplate).toHaveBeenCalledWith('immersive_v11')
    expect(props.onSelectCardStyle).not.toHaveBeenCalled()
    expect(screen.getByText('实验模板：按词块、语境义、概念视角、搭配边界和真实听辨生成语言动作卡')).toBeVisible()
    expect(screen.queryByText('沉浸语言 V10')).not.toBeInTheDocument()
  })

  it('shows back-side information amount without looking like another depth setting', () => {
    const props = renderPanel()

    fireEvent.click(screen.getByText('卡片和模板'))
    fireEvent.click(screen.getByRole('radio', { name: /精简背面/ }))

    expect(screen.getByText('背面信息量')).toBeVisible()
    expect(screen.getByText('只影响卡片背面展示')).toBeVisible()
    expect(screen.getByText('精简背面')).toBeVisible()
    expect(screen.getByText('完整背面')).toBeVisible()
    expect(screen.getByText(/只保留音频、原句、重点词伙和当前语境义/)).toBeVisible()
    expect(screen.getByText(/保留解释、边界、迁移句和听辨提示/)).toBeVisible()
    expect(screen.queryByText('复习密度')).not.toBeInTheDocument()
    expect(screen.queryByText('完整学习')).not.toBeInTheDocument()
    expect(screen.queryByText('卡型')).not.toBeInTheDocument()
    expect(props.onSelectReviewDensity).toHaveBeenCalledWith('fast')
  })

  it('shows visual styles only for Ciba Tianxia', () => {
    const props = renderPanel({
      activeTemplateLabel: '词霸天下实验 V1',
      templateId: 'ciba_tianxia_v1',
    })

    fireEvent.click(screen.getByText('卡片和模板'))
    fireEvent.click(screen.getByRole('radio', { name: /极简白卡/ }))

    expect(screen.getByText('词霸天下实验 V1 · 暖色纸感')).toBeVisible()
    expect(screen.getByText('词霸卡面风格')).toBeVisible()
    expect(screen.getByText('仅影响导出卡面')).toBeVisible()
    expect(screen.getByRole('radiogroup', { name: /选择词霸卡面风格/ })).toBeVisible()
    expect(props.onSelectTemplate).not.toHaveBeenCalled()
    expect(props.onSelectCardStyle).toHaveBeenCalledWith('minimal_white')
  })

  it('renders document mode as knowledge card only', () => {
    renderPanel({ sourceMode: 'document' })

    fireEvent.click(screen.getByText('卡片和模板'))

    expect(screen.getAllByText('知识问答卡')[1]).toBeVisible()
    expect(screen.getByText('正面是问题或概念提示，反面是结构化答案、解释、例子和为什么值得记。')).toBeVisible()
    expect(screen.queryByRole('radiogroup', { name: /选择制卡模板/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('radiogroup', { name: /选择视觉风格/ })).not.toBeInTheDocument()
  })

  it('renders document language reading card copy', () => {
    renderPanel({ documentStudyMode: 'language_reading', sourceMode: 'document' })

    fireEvent.click(screen.getByText('卡片和模板'))

    expect(screen.getAllByText('文档精读卡')[1]).toBeVisible()
    expect(screen.getByText('从文档里提取表达、词汇或语法点；不生成听力卡，可用卡默认全选。')).toBeVisible()
  })

  it('does not show parked legacy templates', () => {
    const props = renderPanel()

    fireEvent.click(screen.getByText('卡片和模板'))

    expect(screen.queryByText('词典解释')).not.toBeInTheDocument()
    expect(screen.queryByText('极简复习')).not.toBeInTheDocument()
    expect(props.onSelectTemplate).not.toHaveBeenCalledWith('dictionary')
  })
})
