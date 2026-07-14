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
        workspaceStage="source"
      />,
    )

    expect(screen.getByText('先确认视频和字幕是否匹配')).toBeInTheDocument()
    expect(screen.getByText(/SRT 可以手动选择/)).toBeInTheDocument()
    expect(screen.getByText('本地视频')).toBeInTheDocument()
    expect(screen.queryByText('文档资料')).not.toBeInTheDocument()
    expect(screen.queryByText(/生成卡片并导出/)).not.toBeInTheDocument()
    expect(screen.getByText('卡片模式')).toBeInTheDocument()
    expect(screen.queryByText('片段预算')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /开始生成/ })).not.toBeInTheDocument()
  })
})
