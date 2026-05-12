import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { EmptyWorkbench } from './EmptyWorkbench'

describe('EmptyWorkbench', () => {
  it('renders the current source and generation summary', () => {
    render(
      <EmptyWorkbench
        appBusy={false}
        level="B1"
        maxSegments={0}
        sourceMode="document"
        templateLabel="沉浸语言"
        onGenerate={vi.fn()}
        onOpenSettings={vi.fn()}
      />,
    )

    expect(screen.getByText('把真实素材变成 Anki 复习卡')).toBeInTheDocument()
    expect(screen.getByText('文档资料')).toBeInTheDocument()
    expect(screen.getByText('自动片段')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /开始生成/ })).toBeEnabled()
  })
})
