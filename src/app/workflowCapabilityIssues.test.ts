import { describe, expect, it } from 'vitest'

import type { CapabilityReason, CapabilityState, ServiceCapabilityStatus } from './systemCapabilityState'
import type { ArtifactStage, WorkflowActionId } from './workflowState'
import {
  buildWorkflowCapabilityIssues,
  workflowRequiresCapabilityChecks,
  type BuildWorkflowCapabilityIssuesInput,
} from './workflowCapabilityIssues'

function capability(
  state: CapabilityState,
  reason: CapabilityReason = state === 'ready' ? 'verified' : 'verification_missing',
): ServiceCapabilityStatus {
  return {
    state,
    reason,
    verificationFingerprint: 'test:fingerprint',
    credentialRevision: 1,
  }
}

function build(overrides: Partial<BuildWorkflowCapabilityIssuesInput> = {}) {
  return buildWorkflowCapabilityIssues({
    action: 'analyze_source',
    environment: capability('ready'),
    model: capability('ready'),
    tts: capability('ready'),
    ttsRequired: true,
    ...overrides,
  })
}

describe('buildWorkflowCapabilityIssues', () => {
  it.each([
    ['unknown', 'verification_missing', '检查本地生成环境', '检查环境'],
    ['checking', 'checking', '正在检查本地生成环境', undefined],
    ['stale', 'verification_expired', '重新检查本地环境', '重新检查'],
    ['action_required', 'verification_missing', '修复本地生成环境', '修复环境'],
    ['blocked', 'verification_failed', '本地环境缺少必需依赖', '查看修复方法'],
    ['disabled', 'disabled', '启用本地生成环境', '启用环境'],
  ] as const)('maps environment %s to a distinct blocker', (state, reason, title, resolutionLabel) => {
    const issues = build({
      environment: capability(state, reason),
    })

    expect(issues).toHaveLength(1)
    expect(issues[0]).toEqual(
      expect.objectContaining({
        id: 'environment',
        severity: 'blocker',
        action: 'analyze_source',
        title,
      }),
    )
    expect(issues[0]?.resolutionLabel).toBe(resolutionLabel)
    expect(issues[0]?.detail.length).toBeGreaterThan(10)
  })

  it.each([
    ['checking', 'checking', '正在检查模型连接', undefined],
    ['unknown', 'verification_missing', '验证模型连接', '验证模型'],
    ['stale', 'configuration_or_credential_changed', '重新验证模型连接', '重新验证'],
    ['action_required', 'secret_missing', '完成模型授权', '配置授权'],
    ['blocked', 'verification_failed', '修复模型连接', '修复模型'],
    ['disabled', 'disabled', '启用模型服务', '配置模型'],
  ] as const)('maps model %s to a distinct blocker', (state, reason, title, resolutionLabel) => {
    const issues = build({
      model: capability(state, reason),
    })

    expect(issues).toHaveLength(1)
    expect(issues[0]).toEqual(
      expect.objectContaining({
        id: 'api',
        severity: 'blocker',
        action: 'analyze_source',
        title,
      }),
    )
    expect(issues[0]?.resolutionLabel).toBe(resolutionLabel)
  })

  it.each([
    ['action_required', 'hermes_stopped', '启动 Hermes 代理', '启动代理'],
    ['blocked', 'hermes_missing', '安装 Hermes 连接组件', '查看安装方法'],
    ['blocked', 'hermes_oauth_unready', '完成 Hermes OAuth 授权', '完成授权'],
    ['blocked', 'hermes_port_conflict', '解决 Hermes 端口冲突', '查看端口问题'],
  ] as const)('uses a concrete Hermes recovery for %s/%s', (state, reason, title, resolutionLabel) => {
    expect(
      build({
        model: capability(state, reason),
      })[0],
    ).toEqual(
      expect.objectContaining({
        title,
        resolutionLabel,
      }),
    )
  })

  it.each([
    ['checking', 'checking', '正在检查语音服务'],
    ['unknown', 'verification_missing', '验证语音服务'],
    ['stale', 'verification_expired', '重新验证语音服务'],
    ['action_required', 'secret_missing', '完成语音授权'],
    ['blocked', 'verification_failed', '修复语音服务'],
    ['disabled', 'disabled', '启用语音服务'],
  ] as const)('treats required TTS %s as a warning while analyzing', (state, reason, title) => {
    const issues = build({
      action: 'analyze_source',
      tts: capability(state, reason),
    })

    expect(issues).toHaveLength(1)
    expect(issues[0]).toEqual(
      expect.objectContaining({
        id: 'tts',
        severity: 'warning',
        action: 'analyze_source',
        title,
      }),
    )
    expect(issues[0]?.detail).toContain('素材分析可以继续')
  })

  it.each([
    ['checking', 'checking'],
    ['unknown', 'verification_missing'],
    ['stale', 'verification_expired'],
    ['action_required', 'secret_missing'],
    ['blocked', 'verification_failed'],
    ['disabled', 'disabled'],
  ] as const)('treats required TTS %s as a blocker while generating', (state, reason) => {
    const issues = build({
      action: 'generate_cards',
      tts: capability(state, reason),
    })
    const ttsIssue = issues.find((item) => item.id === 'tts')

    expect(ttsIssue).toEqual(
      expect.objectContaining({
        severity: 'blocker',
        action: 'generate_cards',
      }),
    )
    expect(ttsIssue?.detail).toContain('当前操作不能继续')
  })

  it('emits no issue for ready or optional capabilities', () => {
    expect(
      build({
        environment: capability('ready'),
        model: capability('optional'),
        tts: capability('optional'),
      }),
    ).toEqual([])
  })

  it('does not surface disabled TTS when speech is not required', () => {
    expect(
      build({
        tts: capability('disabled', 'disabled'),
        ttsRequired: false,
      }),
    ).toEqual([])
  })

  it('keeps export independent from the model while surfacing required TTS before the user starts', () => {
    const issues = build({
      action: 'export_cards',
      environment: capability('blocked', 'verification_failed'),
      model: capability('blocked', 'verification_failed'),
      tts: capability('blocked', 'verification_failed'),
    })

    expect(issues.map((item) => item.id)).toEqual(['environment', 'tts'])
    expect(issues.every((item) => item.action === 'export_cards')).toBe(true)
    expect(issues.every((item) => item.severity === 'blocker')).toBe(true)
  })

  it.each(['import_and_verify', 'resume_task', 'resolve_blocker'] satisfies WorkflowActionId[])(
    'does not infer these capabilities for %s',
    (action) => {
      expect(
        build({
          action,
          environment: capability('blocked', 'verification_failed'),
          model: capability('blocked', 'verification_failed'),
          tts: capability('blocked', 'verification_failed'),
        }),
      ).toEqual([])
    },
  )

  it('returns issues in stable environment, model, TTS order', () => {
    const issues = build({
      action: 'generate_cards',
      environment: capability('unknown'),
      model: capability('stale', 'verification_expired'),
      tts: capability('action_required', 'secret_missing'),
    })

    expect(issues.map((item) => item.id)).toEqual(['environment', 'api', 'tts'])
  })
})

describe('workflowRequiresCapabilityChecks', () => {
  it.each([
    ['analyze_source', 'source_ready', 0, true],
    ['generate_cards', 'learning_points_ready', 1, true],
    ['generate_cards', 'learning_points_ready', 50, true],
    ['export_cards', 'drafts_ready', 0, true],
  ] satisfies Array<[WorkflowActionId, ArtifactStage, number, boolean]>)(
    'requires checks for %s at %s with %i selected',
    (action, artifactStage, selectedCount, expected) => {
      expect(workflowRequiresCapabilityChecks(action, artifactStage, selectedCount)).toBe(expected)
    },
  )

  it.each([
    ['analyze_source', 'empty', 0],
    ['analyze_source', 'learning_points_ready', 0],
    ['analyze_source', 'drafts_ready', 0],
    ['analyze_source', 'apkg_ready', 0],
    ['analyze_source', 'anki_verified', 0],
    ['generate_cards', 'learning_points_ready', 0],
    ['generate_cards', 'drafts_ready', 8],
    ['generate_cards', 'apkg_ready', 8],
    ['export_cards', 'empty', 0],
    ['export_cards', 'source_ready', 0],
    ['export_cards', 'apkg_ready', 0],
    ['import_and_verify', 'apkg_ready', 0],
    ['resume_task', 'source_ready', 0],
    ['resolve_blocker', 'source_ready', 0],
  ] satisfies Array<[WorkflowActionId, ArtifactStage, number]>)(
    'does not block viewing or recovery for %s at %s with %i selected',
    (action, artifactStage, selectedCount) => {
      expect(workflowRequiresCapabilityChecks(action, artifactStage, selectedCount)).toBe(false)
    },
  )
})
