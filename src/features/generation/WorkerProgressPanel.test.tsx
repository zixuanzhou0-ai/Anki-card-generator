import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { WorkerProgressPanel } from './WorkerProgressPanel'

describe('WorkerProgressPanel', () => {
  it('labels export progress and renders the percentage', () => {
    render(
      <WorkerProgressPanel
        progress={{
          command: 'export',
          stage: 'media',
          percent: 42,
          message: '正在切片 2/3',
        }}
      />,
    )

    expect(screen.getByText('导出进度')).toBeInTheDocument()
    expect(screen.getByText('42%')).toBeInTheDocument()
    expect(screen.getByText('正在切片 2/3')).toBeInTheDocument()
  })

  it('labels learning point extraction progress separately from card generation', () => {
    render(
      <WorkerProgressPanel
        progress={{
          command: 'extract_learning_points',
          stage: 'ai_review',
          percent: 58,
          message: 'AI 正在精筛学习点：第 3/12 批',
        }}
      />,
    )

    expect(screen.getByText('学习点筛选进度')).toBeInTheDocument()
    expect(screen.getByText('58%')).toBeInTheDocument()
  })

  it('labels selected learning point card generation progress', () => {
    render(
      <WorkerProgressPanel
        progress={{
          command: 'generate_cards_from_learning_points',
          stage: 'ai',
          percent: 66,
          message: '正在把选中学习点生成卡片',
        }}
      />,
    )

    expect(screen.getByText('制卡进度')).toBeInTheDocument()
    expect(screen.getByText('66%')).toBeInTheDocument()
  })
})
