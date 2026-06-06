import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { EmptyWorkbench } from './EmptyWorkbench'

describe('EmptyWorkbench', () => {
  it('renders the current source and generation summary', () => {
    render(
      <EmptyWorkbench
        level="B1"
        maxSegments={0}
        sourceMode="document"
        templateLabel="沉浸语言"
      />,
    )

    expect(screen.getByText('审核区会在生成后展开')).toBeInTheDocument()
    expect(screen.getByText('文档资料')).toBeInTheDocument()
    expect(screen.getByText('自动片段')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /开始生成/ })).not.toBeInTheDocument()
  })
})
