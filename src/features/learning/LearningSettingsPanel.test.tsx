import '@testing-library/jest-dom/vitest'
import type { ComponentProps } from 'react'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { defaultRequest, levels } from '../../domain/options'
import { LearningSettingsPanel } from './LearningSettingsPanel'

afterEach(() => cleanup())

function renderPanel(overrides: Partial<ComponentProps<typeof LearningSettingsPanel>> = {}) {
  const props: ComponentProps<typeof LearningSettingsPanel> = {
    levels,
    previewRate: 0.75,
    request: defaultRequest,
    onPatchRequest: vi.fn(),
    onPreviewRateChange: vi.fn(),
    onSelectCurrentLevel: vi.fn(),
    ...overrides,
  }
  render(<LearningSettingsPanel {...props} />)
  return props
}

describe('LearningSettingsPanel', () => {
  it('keeps the main flow to language, level, and preview speed', () => {
    renderPanel()

    expect(screen.getByText('学习语言')).toBeVisible()
    expect(screen.getByText('学习水平')).toBeVisible()
    expect(screen.getByText('预览播放速度')).toBeVisible()
    expect(screen.getByRole('option', { name: 'Русский' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '自动判断学习水平' })).toBeVisible()

    expect(screen.queryByText('智能筛选')).not.toBeInTheDocument()
    expect(screen.queryByText('片段预算')).not.toBeInTheDocument()
    expect(screen.queryByText('高级学习设置')).not.toBeInTheDocument()
    expect(screen.queryByText('解析精度')).not.toBeInTheDocument()
    expect(screen.queryByText('深入解析')).not.toBeInTheDocument()
    expect(screen.queryByText('快速提取')).not.toBeInTheDocument()
    expect(screen.queryByText('复用上次 AI 精筛结果')).not.toBeInTheDocument()
    expect(screen.queryByText('学习重点')).not.toBeInTheDocument()
    expect(screen.queryByText('难度关注范围')).not.toBeInTheDocument()
    expect(screen.queryByText('内容偏好')).not.toBeInTheDocument()
  })

  it('patches the selected learning language', () => {
    const onPatchRequest = vi.fn()
    renderPanel({ onPatchRequest })

    fireEvent.change(screen.getByLabelText('学习语言'), { target: { value: 'fr' } })

    expect(onPatchRequest).toHaveBeenCalledWith({ language: 'fr' })
  })

  it('selects auto and manual learning levels', () => {
    const props = renderPanel({ request: { ...defaultRequest, level_mode: 'manual', level: 'B1' } })

    fireEvent.click(screen.getByRole('button', { name: '自动判断学习水平' }))
    fireEvent.click(screen.getByRole('button', { name: /B2表达块/ }))

    expect(props.onPatchRequest).toHaveBeenCalledWith({ level_mode: 'auto' })
    expect(props.onSelectCurrentLevel).toHaveBeenCalledWith('B2')
  })

  it('changes the global preview playback speed', () => {
    const onPreviewRateChange = vi.fn()
    renderPanel({ onPreviewRateChange, previewRate: 0.75 })

    fireEvent.click(screen.getByRole('button', { name: '1.25x' }))

    expect(screen.getByText('只影响应用内试听，不改变导出的 Anki 音频')).toBeVisible()
    expect(onPreviewRateChange).toHaveBeenCalledWith(1.25)
  })
})
