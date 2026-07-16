import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { buildWorkflowUiSnapshot, type WorkflowIssue, type WorkflowStateView } from '../../app/workflowState'
import { defaultRequest, levels } from '../../domain/options'
import type { GenerateRequest } from '../../domain/types'
import type { WorkerErrorAction } from '../../domain/workerErrors'
import { SourceWorkspace, type SourceWorkspaceProps } from './SourceWorkspace'

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

function renderWorkspace(
  requestOverrides: Partial<GenerateRequest> = {},
  propOverrides: Partial<SourceWorkspaceProps> = {},
) {
  const props: SourceWorkspaceProps = {
    snapshot: snapshot(),
    request: { ...defaultRequest, ...requestOverrides },
    levels,
    previewRate: 0.75,
    onPatchRequest: vi.fn(),
    onPreviewRateChange: vi.fn(),
    onSelectCurrentLevel: vi.fn(),
    onSelectPath: vi.fn(),
    onSelectSourceMode: vi.fn(),
    onSelectReviewDensity: vi.fn(),
    onSelectTemplate: vi.fn(),
    onPrimaryAction: vi.fn(),
    onResolveBlockers: vi.fn(),
    workerErrorActions: [],
    onWorkerErrorAction: vi.fn(),
    ...propOverrides,
  }

  render(<SourceWorkspace {...props} />)
  return props
}

describe('SourceWorkspace', () => {
  it('combines source input with a collapsed learning-preference summary and one primary action', () => {
    renderWorkspace()

    expect(screen.getByRole('heading', { level: 1, name: '添加学习素材' })).toBeInTheDocument()
    expect(screen.getByText('English · 自动判断水平 · 完整复读 · 0.75× 预览')).toBeInTheDocument()
    expect(screen.getByLabelText('学习偏好设置')).not.toHaveAttribute('open')
    expect(document.querySelectorAll('[data-variant="primary"]')).toHaveLength(1)
    expect(screen.getByRole('button', { name: '选择素材后继续' })).toBeDisabled()
    expect(screen.getByRole('heading', { name: '开始前还需要处理' })).toBeInTheDocument()
  })

  it('shows structured security authorization actions in the source workflow', () => {
    const onWorkerErrorAction = vi.fn()
    const authorizationAction = {
      id: 'allow-private-network-url',
      label: '允许本机/内网 URL 后重试',
      description: '仅当这个链接确实是你主动选择的本机或内网素材时使用。',
    } satisfies WorkerErrorAction

    renderWorkspace(
      { source_url: 'http://127.0.0.1:8080/video' },
      { workerErrorActions: [authorizationAction], onWorkerErrorAction },
    )

    expect(screen.getByText('需要你的明确授权')).toBeInTheDocument()
    expect(screen.getByText(authorizationAction.description)).toBeInTheDocument()
    const authorize = screen.getByRole('button', { name: authorizationAction.label })
    expect(authorize).toHaveAttribute('data-security-authorization', 'true')
    fireEvent.click(authorize)
    expect(onWorkerErrorAction).toHaveBeenCalledWith('allow-private-network-url')
  })
  it('runs the snapshot action directly once source analysis is available', () => {
    const onPrimaryAction = vi.fn()
    const request = { ...defaultRequest, video_path: 'E:\\Videos\\lesson.mp4' }
    renderWorkspace(request, {
      snapshot: snapshot({
        artifacts: {
          sourceReady: true,
          learningPointCount: 0,
          draftCardCount: 0,
          apkgReady: false,
          ankiVerified: false,
        },
      }),
      onPrimaryAction,
    })

    fireEvent.click(screen.getByRole('button', { name: '分析素材' }))
    expect(onPrimaryAction).toHaveBeenCalledWith('analyze_source')
  })

  it('focuses actionable readiness blockers without starting analysis', () => {
    const blocker: WorkflowIssue = {
      id: 'environment',
      severity: 'blocker',
      action: 'analyze_source',
      title: '完成本地环境准备',
      detail: 'FFmpeg 尚未就绪。',
      resolutionLabel: '修复环境',
    }
    const onPrimaryAction = vi.fn()
    const onResolveBlockers = vi.fn()

    renderWorkspace(
      { video_path: 'E:\\Videos\\lesson.mp4' },
      {
        snapshot: snapshot({
          artifacts: {
            sourceReady: true,
            learningPointCount: 0,
            draftCardCount: 0,
            apkgReady: false,
            ankiVerified: false,
          },
          issues: [blocker],
        }),
        onPrimaryAction,
        onResolveBlockers,
      },
    )

    const action = screen.getByRole('button', { name: '还需完成 1 项准备' })
    expect(action).toBeEnabled()
    fireEvent.click(action)
    expect(onResolveBlockers).toHaveBeenCalledWith([blocker])
    expect(onPrimaryAction).not.toHaveBeenCalled()
  })

  it('exposes honest progress semantics and locks request inputs while analysis is running', () => {
    const onSelectPath = vi.fn()
    renderWorkspace(
      { video_path: 'E:\\Videos\\lesson.mp4' },
      {
        onSelectPath,
        snapshot: snapshot({
          artifacts: {
            sourceReady: true,
            learningPointCount: 0,
            draftCardCount: 0,
            apkgReady: false,
            ankiVerified: false,
          },
          operation: {
            schemaVersion: 1,
            id: 'task-1',
            action: 'analyze_source',
            state: 'running',
            startedAt: 1,
            updatedAt: 2,
            cancellable: true,
            phaseLabel: '正在读取字幕',
            overallPercent: 42.4,
          },
        }),
      },
    )

    expect(screen.getByRole('progressbar', { name: '当前任务进度' })).toHaveAttribute('aria-valuenow', '42')
    expect(screen.getByRole('button', { name: '正在分析素材…' })).toBeDisabled()
    expect(screen.getByRole('group', { name: '素材与学习偏好' })).toBeDisabled()
    const videoPicker = screen.getByRole('button', { name: '选择视频文件' })
    expect(videoPicker).toBeDisabled()
    fireEvent.click(videoPicker)
    expect(onSelectPath).not.toHaveBeenCalled()
  })
})
