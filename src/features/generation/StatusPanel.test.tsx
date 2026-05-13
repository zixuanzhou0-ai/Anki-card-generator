import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { WorkerErrorAction } from '../../domain/workerErrors'
import { StatusPanel } from './StatusPanel'

const subtitleOnlyAction: WorkerErrorAction = {
  id: 'use-subtitle-only',
  label: '改用字幕-only',
  description: '跳过视频下载和切片，只用字幕继续生成卡片。',
}

describe('StatusPanel', () => {
  it('shows current status and recovery actions', () => {
    const onAction = vi.fn()

    render(
      <StatusPanel
        appBusy={false}
        requestEditedDuringRun={false}
        status="YouTube 返回 HTTP 429"
        statusTone="warn"
        workerBusy={false}
        workerErrorActions={[subtitleOnlyAction]}
        onWorkerErrorAction={onAction}
      />,
    )

    expect(screen.getByRole('status')).toHaveTextContent('YouTube 返回 HTTP 429')
    fireEvent.click(screen.getByRole('button', { name: '改用字幕-only' }))

    expect(onAction).toHaveBeenCalledWith('use-subtitle-only')
  })

  it('shows the running snapshot note only while worker is busy', () => {
    const { rerender } = render(
      <StatusPanel
        appBusy
        requestEditedDuringRun
        status="正在生成"
        statusTone="active"
        workerBusy
        workerErrorActions={[]}
        onWorkerErrorAction={() => undefined}
      />,
    )

    expect(screen.getByText(/本次任务使用开始时的配置/)).toBeInTheDocument()

    rerender(
      <StatusPanel
        appBusy={false}
        requestEditedDuringRun
        status="已完成"
        statusTone="ok"
        workerBusy={false}
        workerErrorActions={[]}
        onWorkerErrorAction={() => undefined}
      />,
    )

    expect(screen.queryByText(/本次任务使用开始时的配置/)).not.toBeInTheDocument()
  })
})

