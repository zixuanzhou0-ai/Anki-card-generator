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
    expect(screen.getByText('切片媒体')).toBeInTheDocument()
    expect(screen.queryByText('正在切片 2/3')).not.toBeInTheDocument()
  })

  it('labels learning point extraction progress separately from card generation', () => {
    render(
      <WorkerProgressPanel
        progress={{
          command: 'extract_learning_points',
          stage: 'ai_review',
          percent: 58,
          message: 'AI 正在精筛学习点：第 3/12 批',
          completed_batches: 3,
          total_batches: 12,
          cache_hits: 2,
          cache_misses: 1,
        }}
      />,
    )

    expect(screen.getByText('学习点筛选进度')).toBeInTheDocument()
    expect(screen.getByText('58%')).toBeInTheDocument()
    expect(screen.getByText('抽取学习点')).toBeInTheDocument()
    expect(screen.getByText('已完成 3/12 批 · 缓存命中 2，未命中 1')).toBeInTheDocument()
    expect(screen.queryByText(/本地候选不会直接生成卡片/)).not.toBeInTheDocument()
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
    expect(screen.getByText('生成卡片正文')).toBeInTheDocument()
    expect(screen.getByText(/后台会自动分批处理/)).toBeInTheDocument()
  })
})
