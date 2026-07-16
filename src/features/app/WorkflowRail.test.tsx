import '@testing-library/jest-dom/vitest'
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { buildWorkflowUiSnapshot, type WorkflowStateView } from '../../app/workflowState'
import { defaultRequest } from '../../domain/options'
import { WorkflowRail } from './WorkflowRail'

afterEach(() => cleanup())

function snapshot(overrides: Partial<WorkflowStateView> = {}) {
  return buildWorkflowUiSnapshot({
    step: 'source',
    artifacts: {
      sourceReady: false,
      learningPointCount: 0,
      draftCardCount: 0,
      apkgReady: false,
      ankiVerified: false,
    },
    selectedLearningPointCount: 0,
    exportableCardCount: 0,
    repairRequiredCardCount: 0,
    operation: null,
    issues: [],
    notice: null,
    ...overrides,
  })
}

describe('WorkflowRail', () => {
  it('shows only the three product steps and locks unavailable forward navigation', () => {
    render(
      <WorkflowRail
        snapshot={snapshot()}
        request={defaultRequest}
        learningPointCount={0}
        draftCardCount={0}
        onStepChange={vi.fn()}
      />,
    )

    const navigation = screen.getByRole('navigation', { name: '三步制卡流程' })
    const buttons = within(navigation).getAllByRole('button')
    expect(buttons).toHaveLength(3)
    expect(buttons[0]).toHaveAttribute('aria-current', 'step')
    expect(buttons[1]).toBeDisabled()
    expect(buttons[2]).toBeDisabled()
    expect(screen.getByLabelText('当前素材摘要')).toHaveTextContent('尚未选择视频')
  })

  it('uses reliable artifact evidence for step status and keeps past steps keyboard reachable', async () => {
    const user = userEvent.setup()
    const onStepChange = vi.fn()
    const readySnapshot = snapshot({
      step: 'select',
      artifacts: {
        sourceReady: true,
        learningPointCount: 18,
        draftCardCount: 0,
        apkgReady: false,
        ankiVerified: false,
      },
    })

    render(
      <WorkflowRail
        snapshot={readySnapshot}
        request={{ ...defaultRequest, title: 'BBC Learning English', video_path: 'E:\\Videos\\lesson.mp4' }}
        learningPointCount={18}
        onStepChange={onStepChange}
      />,
    )

    const sourceButton = screen.getByRole('button', { name: /添加素材/ })
    expect(sourceButton).toBeEnabled()
    expect(screen.getByRole('button', { name: /选择学习点/ })).toHaveAttribute('aria-current', 'step')
    expect(screen.getByText('18 个可靠学习点')).toBeInTheDocument()
    expect(screen.getByLabelText('当前素材摘要')).toHaveTextContent('lesson.mp4')
    expect(screen.getByLabelText('当前素材摘要')).not.toHaveTextContent('E:\\Videos')

    sourceButton.focus()
    await user.keyboard('{Enter}')
    expect(onStepChange).toHaveBeenCalledWith('source')
  })

  it('distinguishes APKG generation from completed Anki verification', () => {
    render(
      <WorkflowRail
        snapshot={snapshot({
          step: 'deliver',
          artifacts: {
            sourceReady: true,
            learningPointCount: 9,
            draftCardCount: 9,
            apkgReady: true,
            ankiVerified: false,
          },
          exportableCardCount: 9,
        })}
        request={{ ...defaultRequest, source_mode: 'url', source_url: 'https://example.com/video' }}
        learningPointCount={9}
        draftCardCount={9}
        onStepChange={vi.fn()}
      />,
    )

    expect(screen.getByText('APKG 已生成')).toBeInTheDocument()
    expect(screen.queryByText('已在 Anki 中核验')).not.toBeInTheDocument()
    expect(screen.getAllByRole('button')).toHaveLength(3)
    expect(screen.getAllByRole('button').every((button) => !button.hasAttribute('disabled'))).toBe(true)
  })
})
