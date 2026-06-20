import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { defaultRequest, levels } from '../../domain/options'
import type { GenerateRequest } from '../../domain/types'
import { InspectorPanel } from './InspectorPanel'

afterEach(() => cleanup())

function renderInspector(overrides: Partial<GenerateRequest> = {}, propOverrides: Partial<Parameters<typeof InspectorPanel>[0]> = {}) {
  const request: GenerateRequest = { ...defaultRequest, ...overrides }
  const props = {
    activeWorkspaceStage: 'source' as const,
    appBusy: false,
    diagnosticCount: 0,
    generatedCardCount: 0,
    hasExportableCards: false,
    hasLearningPointResult: false,
    hasProject: false,
    inspectorSheetOpen: false,
    levels,
    previewRate: 0.75,
    readiness: [
      { id: 'source', label: '素材', done: false, detail: '待选择' },
      { id: 'api', label: 'API', done: true, detail: '已测试' },
    ],
    request,
    requestEditedDuringRun: false,
    selectedCardCount: 0,
    selectedLearningPointCount: 0,
    status: '准备生成 Anki 卡片。',
    statusTone: 'ok',
    workerBusy: false,
    workerErrorActions: [],
    workerProgress: null,
    onCloseSheet: vi.fn(),
    onExport: vi.fn(),
    onCheckEnv: vi.fn(),
    onExtractLearningPointsWithoutCache: vi.fn(),
    onGenerate: vi.fn(),
    onOpenEnvSettings: vi.fn(),
    onPatchRequest: vi.fn(),
    onPreviewRateChange: vi.fn(),
    onRepairEnv: vi.fn(),
    onSelectCurrentLevel: vi.fn(),
    onSelectPath: vi.fn(),
    onSelectSourceMode: vi.fn(),
    onSelectTemplate: vi.fn(),
    onWorkspaceStageChange: vi.fn(),
    onWorkerErrorAction: vi.fn(),
    ...propOverrides,
  }

  render(<InspectorPanel {...props} />)
  return props
}

describe('InspectorPanel', () => {
  it('renders the source stage first and exposes the staged workflow', () => {
    renderInspector()

    const stepper = screen.getByLabelText('制卡步骤')
    expect(screen.getByLabelText('制卡流程控制台')).toBeInTheDocument()
    expect(within(stepper).getByRole('button', { name: /素材配置/ })).toHaveAttribute('aria-current', 'step')
    expect(within(stepper).getByRole('button', { name: /学习设置/ })).toBeDisabled()
    expect(within(stepper).getByRole('button', { name: /确认抽取/ })).toBeDisabled()
    expect(screen.getByText('1/2')).toBeInTheDocument()
    expect(screen.getAllByText('素材').length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: /选择素材后继续/ })).toBeDisabled()
    expect(screen.getByText('请选择本地视频文件后继续。')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '学习设置' })).not.toBeInTheDocument()
    expect(screen.queryByText('卡片模式')).not.toBeInTheDocument()
  })

  it('shows learning and template settings in the generation stage', () => {
    renderInspector({}, { activeWorkspaceStage: 'generate' })

    const stepper = screen.getByLabelText('制卡步骤')
    expect(screen.getByRole('heading', { name: '学习设置' })).toBeInTheDocument()
    expect(screen.getByText('卡片模式')).toBeInTheDocument()
    expect(within(stepper).getByRole('button', { name: /确认抽取/ })).not.toBeDisabled()
  })

  it('uses next-step actions instead of free future navigation', () => {
    const props = renderInspector(
      {},
      {
        readiness: [
          { id: 'source', label: '素材', done: true, detail: '已就绪' },
          { id: 'api', label: 'API', done: true, detail: '已测试' },
        ],
      },
    )

    fireEvent.click(screen.getByRole('button', { name: /下一步：学习设置/ }))

    expect(props.onWorkspaceStageChange).toHaveBeenCalledWith('generate')
  })

  it('starts learning point extraction from the confirm step before a project exists', () => {
    const props = renderInspector(
      {},
      {
        activeWorkspaceStage: 'review',
        readiness: [
          { id: 'source', label: '素材', done: true, detail: '已就绪' },
          { id: 'api', label: 'API', done: true, detail: '已测试' },
        ],
      },
    )

    fireEvent.click(screen.getByRole('button', { name: /开始抽取学习点/ }))

    expect(props.onGenerate).toHaveBeenCalledTimes(1)
  })

  it('starts no-cache learning point extraction from the confirm step before a project exists', () => {
    const onExtractLearningPointsWithoutCache = vi.fn()
    const props = renderInspector(
      {},
      {
        activeWorkspaceStage: 'review',
        onExtractLearningPointsWithoutCache,
        readiness: [
          { id: 'source', label: '素材', done: true, detail: '已就绪' },
          { id: 'api', label: 'API', done: true, detail: '已测试' },
        ],
      },
    )

    expect(screen.getByText('可以抽取学习点')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '开始抽取学习点' })).toBeEnabled()

    const noCacheButton = screen.getByRole('button', { name: '不使用缓存抽取学习点' })
    expect(noCacheButton).toBeEnabled()
    fireEvent.click(noCacheButton)

    expect(onExtractLearningPointsWithoutCache).toHaveBeenCalledTimes(1)
    expect(props.onGenerate).not.toHaveBeenCalled()
  })

  it('hides the single-source no-cache extraction action for batch packages', () => {
    renderInspector(
      {
        batch_enabled: true,
        batch_items: [
          {
            id: 'ep1',
            source_mode: 'local',
            enabled: true,
            title: 'S01E01',
            subdeck_title: 'S01E01',
            video_path: 'E:/Shows/S01E01.mp4',
          },
        ],
      },
      {
        activeWorkspaceStage: 'review',
        readiness: [
          { id: 'source', label: '素材', done: true, detail: '已就绪' },
          { id: 'api', label: 'API', done: true, detail: '已测试' },
        ],
      },
    )

    expect(screen.queryByRole('button', { name: '不使用缓存抽取学习点' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '开始抽取学习点' })).toBeEnabled()
  })

  it('generates selected cards after learning points exist', () => {
    const props = renderInspector(
      {},
      {
        activeWorkspaceStage: 'review',
        hasLearningPointResult: true,
        selectedLearningPointCount: 12,
        readiness: [
          { id: 'source', label: '素材', done: true, detail: '已就绪' },
          { id: 'env', label: '环境', done: true, detail: '可用' },
          { id: 'api', label: 'API', done: true, detail: '已通过' },
        ],
      },
    )

    expect(screen.getByText('选择学习点后一键生成 APKG')).toBeInTheDocument()
    expect(screen.getByText('12 张卡片')).toBeInTheDocument()
    expect(screen.getByText('在右侧清单确认 12 个学习点后生成 APKG')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /生成 APKG · 12 张/ })).not.toBeInTheDocument()
    expect(props.onGenerate).not.toHaveBeenCalled()
  })

  it('locks earlier workflow steps while generation is running', () => {
    renderInspector(
      {},
      {
        activeWorkspaceStage: 'review',
        appBusy: true,
        workerBusy: true,
        workerProgress: {
          command: 'generate',
          stage: 'ai',
          percent: 42,
          message: '正在生成卡片正文。',
        },
        readiness: [
          { id: 'source', label: '素材', done: true, detail: '已就绪' },
          { id: 'api', label: 'API', done: true, detail: '已测试' },
        ],
      },
    )

    const stepper = screen.getByLabelText('制卡步骤')
    const stageButtons = within(stepper).getAllByRole('button')
    expect(stageButtons[0]).toBeDisabled()
    expect(stageButtons[1]).toBeDisabled()
    expect(stageButtons[2]).not.toBeDisabled()
    expect(screen.getByText('正在生成 APKG')).toBeInTheDocument()
    expect(screen.getByText(/生成进度已移到右侧工作台/)).toBeInTheDocument()
  })

  it('lists extraction preflight checks before AI learning point extraction', () => {
    const props = renderInspector(
      {},
      {
        activeWorkspaceStage: 'review',
        readiness: [
          { id: 'source', label: '素材', done: true, detail: '已就绪' },
          { id: 'env', label: '环境', done: false, detail: '未检查' },
          { id: 'api', label: 'API', done: false, detail: '未测试' },
          { id: 'tts', label: 'TTS', done: false, detail: '未测试' },
          { id: 'cards', label: '卡片', done: true, detail: '3 张' },
        ],
      },
    )

    expect(screen.getByText('抽取学习点前还需要完成')).toBeInTheDocument()
    expect(screen.getByText('环境：未检查 / API：未测试')).toBeInTheDocument()
    expect(screen.queryByText(/TTS：未测试/)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '立即检查' }))
    fireEvent.click(screen.getByRole('button', { name: '查看详情' }))
    expect(props.onCheckEnv).toHaveBeenCalledTimes(1)
    expect(props.onOpenEnvSettings).toHaveBeenCalledTimes(1)
  })

  it('offers one-click repair from the preflight card when the environment is checked but incomplete', () => {
    const props = renderInspector(
      {},
      {
        activeWorkspaceStage: 'review',
        readiness: [
          { id: 'source', label: '素材', done: true, detail: '已就绪' },
          { id: 'env', label: '环境', done: false, detail: '缺少依赖' },
          { id: 'api', label: 'API', done: true, detail: '已测试' },
        ],
      },
    )

    expect(screen.getByText('环境：缺少依赖')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '立即检查' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '一键修复' }))
    fireEvent.click(screen.getByRole('button', { name: '查看详情' }))

    expect(props.onRepairEnv).toHaveBeenCalledWith('all')
    expect(props.onOpenEnvSettings).toHaveBeenCalledTimes(1)
  })

  it('forwards close and source mode actions', () => {
    const props = renderInspector()

    fireEvent.click(screen.getByRole('button', { name: '关闭素材设置' }))
    fireEvent.click(screen.getByRole('button', { name: /视频链接/ }))

    expect(props.onCloseSheet).toHaveBeenCalledTimes(1)
    expect(props.onSelectSourceMode).toHaveBeenCalledWith('url')
  })

  it('summarizes batch packages as nested subdeck work instead of a single source', () => {
    const batchItems = [
      {
        id: 'ep1',
        source_mode: 'local' as const,
        enabled: true,
        title: 'S01E01 - Pilot',
        subdeck_title: 'S01E01 - Pilot',
        deck_name: '无耻之徒 第一季::S01E01 - Pilot',
        video_path: 'E:/Shows/S01E01 Pilot.mp4',
      },
      {
        id: 'ep2',
        source_mode: 'local' as const,
        enabled: true,
        title: 'S01E02 - Frank the Plank',
        subdeck_title: 'S01E02 - Frank the Plank',
        deck_name: '无耻之徒 第一季::S01E02 - Frank the Plank',
        video_path: 'E:/Shows/S01E02 Frank.mp4',
      },
    ]

    renderInspector(
      { title: '无耻之徒 第一季', source_mode: 'local', batch_enabled: true, batch_items: batchItems },
      {
        activeWorkspaceStage: 'review',
        readiness: [
          { id: 'source', label: '素材', done: true, detail: '2 个素材' },
          { id: 'env', label: '环境', done: true, detail: '可用' },
          { id: 'api', label: 'API', done: true, detail: '已通过' },
        ],
      },
    )

    expect(screen.getByText('批量学习包')).toBeInTheDocument()
    expect(screen.getAllByText('2 个子牌组')[0]).toBeInTheDocument()
    expect(screen.getByText('无耻之徒 第一季')).toBeInTheDocument()
  })

  it('keeps the public generation panel focused on video learning even for an old document source state', () => {
    renderInspector({ source_mode: 'document' }, { activeWorkspaceStage: 'generate' })

    expect(screen.getByRole('heading', { name: '学习设置' })).toBeInTheDocument()
    expect(screen.getByText('卡片模式')).toBeVisible()
    expect(screen.queryByText('文档目标')).not.toBeInTheDocument()
    expect(screen.queryByText('知识吸收')).not.toBeInTheDocument()
  })
})
