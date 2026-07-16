import { describe, expect, it } from 'vitest'

import {
  buildWorkflowUiSnapshot,
  selectActionGate,
  selectArtifactStage,
  selectProductStepForArtifact,
  type ArtifactEvidence,
  type WorkflowStateView,
} from './workflowState'

const emptyArtifacts: ArtifactEvidence = {
  sourceReady: false,
  learningPointCount: 0,
  draftCardCount: 0,
  apkgReady: false,
  ankiVerified: false,
}

function view(overrides: Partial<WorkflowStateView> = {}): WorkflowStateView {
  return {
    step: 'source',
    artifacts: emptyArtifacts,
    selectedLearningPointCount: 0,
    repairRequiredCardCount: 0,
    operation: null,
    issues: [],
    notice: null,
    ...overrides,
  }
}

describe('selectArtifactStage', () => {
  it.each([
    [emptyArtifacts, 'empty'],
    [{ ...emptyArtifacts, sourceReady: true }, 'source_ready'],
    [{ ...emptyArtifacts, sourceReady: true, learningPointCount: 12 }, 'learning_points_ready'],
    [{ ...emptyArtifacts, sourceReady: true, learningPointCount: 12, draftCardCount: 9 }, 'drafts_ready'],
    [
      {
        ...emptyArtifacts,
        sourceReady: true,
        learningPointCount: 12,
        draftCardCount: 9,
        apkgReady: true,
      },
      'apkg_ready',
    ],
    [
      {
        ...emptyArtifacts,
        sourceReady: true,
        learningPointCount: 12,
        draftCardCount: 9,
        apkgReady: true,
        ankiVerified: true,
      },
      'anki_verified',
    ],
  ] satisfies Array<[ArtifactEvidence, string]>)('maps reliable artifact evidence to %s', (evidence, expected) => {
    expect(selectArtifactStage(evidence)).toBe(expected)
  })

  it('keeps the source root contract while preserving downstream artifacts after in-memory lists are released', () => {
    expect(
      selectArtifactStage({
        sourceReady: false,
        learningPointCount: 50,
        draftCardCount: 50,
        apkgReady: true,
        ankiVerified: true,
      }),
    ).toBe('empty')

    expect(
      selectArtifactStage({
        sourceReady: true,
        learningPointCount: 0,
        draftCardCount: 50,
        apkgReady: true,
        ankiVerified: true,
      }),
    ).toBe('anki_verified')

    expect(
      selectArtifactStage({
        sourceReady: true,
        learningPointCount: 0,
        draftCardCount: 50,
        apkgReady: false,
        ankiVerified: false,
      }),
    ).toBe('drafts_ready')
  })

  it('does not infer learning points or cards from request configuration', () => {
    const configuredCardTypes = ['video_sentence', 'expression']
    expect(configuredCardTypes).toHaveLength(2)
    expect(selectArtifactStage({ ...emptyArtifacts, sourceReady: true })).toBe('source_ready')
  })
})

describe('product-step selectors', () => {
  it('offers a suggested step without overwriting the page the user is viewing', () => {
    expect(selectProductStepForArtifact('source_ready')).toBe('source')
    expect(selectProductStepForArtifact('learning_points_ready')).toBe('select')
    expect(selectProductStepForArtifact('drafts_ready')).toBe('deliver')

    const snapshot = buildWorkflowUiSnapshot(
      view({
        step: 'select',
        artifacts: { ...emptyArtifacts, sourceReady: true },
      }),
    )

    expect(snapshot.step).toBe('select')
    expect(snapshot.heading).toBe('选择值得复习的内容')
    expect(snapshot.artifactStage).toBe('source_ready')
    expect(snapshot.primaryAction.action).toBe('generate_cards')
    expect(snapshot.primaryAction.state).toBe('blocked')
    expect(snapshot.primaryAction.primaryLabel).toBe('先分析素材')
  })
})

describe('selectActionGate', () => {
  it('returns users to the farthest reliable result instead of pretending an upstream list is missing', () => {
    expect(
      selectActionGate(
        view({
          step: 'source',
          artifacts: { ...emptyArtifacts, sourceReady: true, draftCardCount: 9 },
        }),
      ),
    ).toMatchObject({ state: 'available', primaryLabel: '查看已生成的 9 张卡片' })

    expect(
      selectActionGate(
        view({
          step: 'source',
          artifacts: { ...emptyArtifacts, sourceReady: true, apkgReady: true },
        }),
      ),
    ).toMatchObject({ state: 'available', primaryLabel: '查看已导出的 APKG' })
  })
  it('requires a real non-empty learning-point result before generation', () => {
    const gate = selectActionGate(
      view({
        step: 'select',
        artifacts: { ...emptyArtifacts, sourceReady: true },
        selectedLearningPointCount: 9,
      }),
    )

    expect(gate.state).toBe('blocked')
    expect(gate.blockers.map((issue) => issue.id)).toContain('learning_points_missing')
  })

  it('keeps repair-required cards out of the export count without another confirmation gate', () => {
    const gate = selectActionGate(
      view({
        step: 'deliver',
        artifacts: {
          ...emptyArtifacts,
          sourceReady: true,
          learningPointCount: 10,
          draftCardCount: 10,
        },
        exportableCardCount: 9,
        repairRequiredCardCount: 1,
      }),
    )

    expect(gate).toMatchObject({
      action: 'export_cards',
      state: 'available',
      primaryLabel: '导出可用的 9 张',
    })
    expect(gate.blockers).toEqual([])
    expect(gate.warnings[0]?.detail).toContain('1 张需要修复的卡片会自动排除')
  })

  it('lets an interrupted task resume from its safe checkpoint', () => {
    const gate = selectActionGate(
      view({
        step: 'deliver',
        artifacts: {
          ...emptyArtifacts,
          sourceReady: true,
          learningPointCount: 50,
          draftCardCount: 24,
        },
        operation: {
          schemaVersion: 1,
          id: 'job-1',
          action: 'generate_cards',
          state: 'interrupted',
          startedAt: 1,
          updatedAt: 2,
          cancellable: true,
          remainingItems: 26,
        },
      }),
    )

    expect(gate).toMatchObject({
      action: 'resume_task',
      state: 'available',
      primaryLabel: '继续生成剩余 26 张',
    })
  })

  it('exposes an active task without changing the page heading', () => {
    const snapshot = buildWorkflowUiSnapshot(
      view({
        step: 'source',
        artifacts: { ...emptyArtifacts, sourceReady: true },
        operation: {
          schemaVersion: 1,
          id: 'job-2',
          action: 'analyze_source',
          state: 'running',
          startedAt: 1,
          updatedAt: 2,
          cancellable: true,
        },
      }),
    )

    expect(snapshot.heading).toBe('添加学习素材')
    expect(snapshot.primaryAction).toMatchObject({
      action: 'analyze_source',
      state: 'running',
      primaryLabel: '正在分析素材…',
    })
  })

  it('applies only blockers relevant to the current action', () => {
    const gate = selectActionGate(
      view({
        artifacts: { ...emptyArtifacts, sourceReady: true },
        issues: [
          {
            id: 'model_unavailable',
            severity: 'blocker',
            action: 'analyze_source',
            title: '模型需要验证',
            detail: '请先验证当前模型。',
          },
          {
            id: 'anki_unavailable',
            severity: 'blocker',
            action: 'import_and_verify',
            title: 'AnkiConnect 不可用',
            detail: '请启动 Anki。',
          },
        ],
      }),
    )

    expect(gate.state).toBe('blocked')
    expect(gate.primaryLabel).toBe('还需完成 1 项准备')
    expect(gate.blockers.map((issue) => issue.id)).toEqual(['model_unavailable'])
  })
})

describe('structured notices', () => {
  it('reports the latest result without changing readiness or the primary gate', () => {
    const baseView = view({
      artifacts: { ...emptyArtifacts, sourceReady: true },
    })
    const withoutNotice = buildWorkflowUiSnapshot(baseView)
    const withFailureNotice = buildWorkflowUiSnapshot({
      ...baseView,
      notice: {
        id: 'notice-1',
        tone: 'error',
        title: '上一次字幕匹配失败',
        detail: '素材仍然可以重新分析。',
        occurredAt: 123,
        relatedAction: 'analyze_source',
        retryable: true,
      },
    })

    expect(withFailureNotice.notice?.tone).toBe('error')
    expect(withFailureNotice.primaryAction).toEqual(withoutNotice.primaryAction)
    expect(withFailureNotice.artifactStage).toBe(withoutNotice.artifactStage)
  })
})
