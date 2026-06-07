import '@testing-library/jest-dom/vitest'
import type { ComponentProps } from 'react'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { contentOptions, defaultRequest, languageFocusOptions, levels, selectionStrategyOptions } from '../../domain/options'
import { LearningSettingsPanel } from './LearningSettingsPanel'

afterEach(() => cleanup())

function renderPanel(overrides: Partial<ComponentProps<typeof LearningSettingsPanel>> = {}) {
  const props: ComponentProps<typeof LearningSettingsPanel> = {
    contentOptions,
    languageFocusOptions,
    levels,
    previewRate: 0.75,
    request: defaultRequest,
    selectionStrategyOptions,
    onApplyCollectionPreset: vi.fn(),
    onPatchRequest: vi.fn(),
    onPreviewRateChange: vi.fn(),
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
  it('patches language, study depth, and segment budget', () => {
    const onPatchRequest = vi.fn()
    renderPanel({ onPatchRequest, request: { ...defaultRequest, max_segments: 0 } })

    expect(screen.getByRole('option', { name: 'Русский' })).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('学习语言'), { target: { value: 'fr' } })
    fireEvent.click(screen.getByRole('button', { name: /快速生成/ }))
    fireEvent.click(screen.getByRole('button', { name: '自动' }))

    expect(onPatchRequest).toHaveBeenCalledWith({ language: 'fr' })
    expect(onPatchRequest).toHaveBeenCalledWith({ study_depth: 'standard' })
    expect(onPatchRequest).toHaveBeenCalledWith({ max_segments: 35 })
  })

  it('selects auto/manual level and advanced collection presets', () => {
    const props = renderPanel()

    fireEvent.click(screen.getByRole('button', { name: '自动判断学习水平' }))
    fireEvent.click(screen.getAllByRole('button', { name: /B2表达块/ })[0])
    fireEvent.click(screen.getByText('高级学习设置'))
    fireEvent.click(screen.getByRole('button', { name: '上下一级' }))
    const rangePanel = screen.getByLabelText('难度关注范围')
    fireEvent.click(within(rangePanel).getByRole('button', { name: /C1语气和隐含义/ }))

    expect(props.onPatchRequest).toHaveBeenCalledWith({ level_mode: 'auto' })
    expect(props.onSelectCurrentLevel).toHaveBeenCalledWith('B2')
    expect(screen.getByRole('button', { name: /智能筛选/ })).toBeInTheDocument()
    expect(props.onApplyCollectionPreset).toHaveBeenCalledWith('around')
    expect(props.onToggleCollectionLevel).toHaveBeenCalledWith('C1')
  })

  it('changes the global preview playback speed', () => {
    const onPreviewRateChange = vi.fn()
    renderPanel({ onPreviewRateChange, previewRate: 0.75 })

    fireEvent.click(screen.getByRole('button', { name: '1.25x' }))

    expect(screen.getByText('预览播放速度')).toBeVisible()
    expect(screen.getByText('只影响应用内试听，不改变导出的 Anki 音频')).toBeVisible()
    expect(onPreviewRateChange).toHaveBeenCalledWith(1.25)
  })

  it('toggles content preferences', () => {
    const props = renderPanel()

    fireEvent.click(screen.getByText('高级学习设置'))
    fireEvent.click(screen.getByLabelText('日常表达'))

    expect(screen.getByText(/项已选/)).toBeVisible()
    expect(props.onToggleContent).toHaveBeenCalledWith('daily')
  })

  it('toggles language learning focus for video and URL sources', () => {
    const props = renderPanel()

    fireEvent.click(screen.getByText('高级学习设置'))
    fireEvent.click(screen.getByRole('button', { name: /单词用法/ }))

    expect(screen.getAllByText('词伙表达 / 单词用法 / 听力难点').length).toBeGreaterThanOrEqual(1)
    expect(props.onToggleLanguageFocus).toHaveBeenCalledWith('vocabulary')
  })

  it('makes advanced learning settings visibly expandable', () => {
    renderPanel()

    expect(screen.getByText('高级学习设置')).toBeVisible()
    expect(screen.getByText('理解深度、难度范围、内容偏好')).toBeVisible()
    expect(screen.getByText('展开')).toBeInTheDocument()
    expect(screen.getByText('收起')).toBeInTheDocument()
  })

  it('keeps document learning separate from language focus controls', () => {
    renderPanel({ request: { ...defaultRequest, source_mode: 'document' } })

    fireEvent.click(screen.getByText('高级学习设置'))
    expect(screen.getByText('文档资料')).toBeVisible()
    expect(screen.getByText(/文档会单独按知识点、术语和章节结构制卡/)).toBeVisible()
    expect(screen.queryByLabelText('语言学习重点')).not.toBeInTheDocument()
  })
})
