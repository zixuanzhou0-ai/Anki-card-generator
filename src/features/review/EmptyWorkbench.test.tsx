import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { EmptyWorkbench } from './EmptyWorkbench'

describe('EmptyWorkbench', () => {
  it('renders the current source and generation summary', () => {
    render(
      <EmptyWorkbench
        level="B1"
        sourceMode="document"
        templateLabel="沉浸语言"
      />,
    )

    expect(screen.getByText('审核区会在生成后展开')).toBeInTheDocument()
    expect(screen.getByText(/一键生成 APKG/)).toBeInTheDocument()
    expect(screen.getByText('本地视频')).toBeInTheDocument()
    expect(screen.queryByText('文档资料')).not.toBeInTheDocument()
    expect(screen.queryByText(/生成卡片并导出/)).not.toBeInTheDocument()
    expect(screen.getByText('卡片模式')).toBeInTheDocument()
    expect(screen.queryByText('片段预算')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /开始生成/ })).not.toBeInTheDocument()
  })
})
