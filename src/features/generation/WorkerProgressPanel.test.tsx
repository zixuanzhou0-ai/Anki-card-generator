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
})

