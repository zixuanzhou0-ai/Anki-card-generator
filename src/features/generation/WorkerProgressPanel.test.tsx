import '@testing-library/jest-dom/vitest'
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

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
          elapsed_ms: 12_300,
        }}
      />,
    )

    expect(screen.getByText('导出进度')).toBeInTheDocument()
    expect(screen.getByText('42%')).toBeInTheDocument()
    expect(screen.getByText('切片媒体')).toBeInTheDocument()
    expect(screen.getByText('已用时 12 秒')).toBeInTheDocument()
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '42')
    expect(screen.queryByText('正在切片 2/3')).not.toBeInTheDocument()
  })

  it('announces indeterminate work without rendering a fake zero percent', () => {
    const { container } = render(
      <WorkerProgressPanel
        progress={{
          command: 'check_env',
          stage: 'checking',
          percent: 0,
          indeterminate: true,
          message: '正在读取环境检查状态',
        }}
      />,
    )

    expect(container.querySelector('.progress-head strong')).toHaveTextContent('处理中')
    expect(within(container).queryByText('0%')).not.toBeInTheDocument()
    const progressbar = within(container).getByRole('progressbar')
    expect(progressbar).toHaveClass('indeterminate')
    expect(progressbar).not.toHaveAttribute('aria-valuenow')
    expect(progressbar).toHaveAttribute('aria-valuetext', '处理中')
    expect(progressbar.firstElementChild).not.toHaveAttribute('style')
  })
  it('shows when progress last changed and handles future or invalid timestamps', () => {
    const now = vi.spyOn(Date, 'now').mockReturnValue(10_000)
    const progress = {
      command: 'check_env',
      stage: 'checking',
      percent: 0,
      indeterminate: true,
      message: '正在检查环境',
    }

    try {
      const { container, rerender } = render(
        <WorkerProgressPanel progress={{ ...progress, last_progress_at_ms: 9_500 }} />,
      )
      expect(within(container).getByText('最后更新于刚刚')).toBeInTheDocument()

      rerender(<WorkerProgressPanel progress={{ ...progress, last_progress_at_ms: 6_000 }} />)
      expect(within(container).getByText('最后更新于 4 秒前')).toBeInTheDocument()

      rerender(<WorkerProgressPanel progress={{ ...progress, last_progress_at_ms: 11_000 }} />)
      expect(within(container).getByText('最后更新于刚刚')).toBeInTheDocument()

      rerender(<WorkerProgressPanel progress={{ ...progress, last_progress_at_ms: Number.NaN }} />)
      expect(within(container).queryByText(/最后更新于/)).not.toBeInTheDocument()
    } finally {
      now.mockRestore()
    }
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
