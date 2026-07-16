import type { EnvironmentCapabilityStatus, ServiceCapabilityStatus } from './systemCapabilityState'
import type { ArtifactStage, WorkflowActionId, WorkflowIssue, WorkflowIssueSeverity } from './workflowState'

export type BuildWorkflowCapabilityIssuesInput = {
  action: WorkflowActionId
  environment: EnvironmentCapabilityStatus
  model: ServiceCapabilityStatus
  tts: ServiceCapabilityStatus
  ttsRequired: boolean
}

type CapabilityRequirements = {
  environment: boolean
  model: boolean
  ttsSeverity: WorkflowIssueSeverity | null
}

const ACTION_REQUIREMENTS: Record<WorkflowActionId, CapabilityRequirements> = {
  analyze_source: { environment: true, model: true, ttsSeverity: 'warning' },
  generate_cards: { environment: true, model: true, ttsSeverity: 'blocker' },
  export_cards: { environment: true, model: false, ttsSeverity: 'blocker' },
  import_and_verify: { environment: false, model: false, ttsSeverity: null },
  resume_task: { environment: false, model: false, ttsSeverity: null },
  resolve_blocker: { environment: false, model: false, ttsSeverity: null },
}

/**
 * Capability checks belong to the operation that is about to start, not merely
 * to the page that happens to be visible. Existing artifacts must remain
 * inspectable even when a model, TTS service, or local dependency later becomes
 * unavailable.
 */
export function workflowRequiresCapabilityChecks(
  action: WorkflowActionId,
  artifactStage: ArtifactStage,
  selectedLearningPointCount: number,
): boolean {
  switch (action) {
    case 'analyze_source':
      return artifactStage === 'source_ready'
    case 'generate_cards':
      return artifactStage === 'learning_points_ready' && selectedLearningPointCount > 0
    case 'export_cards':
      return artifactStage === 'drafts_ready'
    case 'import_and_verify':
    case 'resume_task':
    case 'resolve_blocker':
      return false
  }
}

export function buildWorkflowCapabilityIssues(input: BuildWorkflowCapabilityIssuesInput): WorkflowIssue[] {
  const requirements = ACTION_REQUIREMENTS[input.action]
  const issues: WorkflowIssue[] = []

  if (requirements.environment) {
    const environmentIssue = issueForEnvironment(input.environment, input.action)
    if (environmentIssue) issues.push(environmentIssue)
  }
  if (requirements.model) {
    const modelIssue = issueForModel(input.model, input.action)
    if (modelIssue) issues.push(modelIssue)
  }
  if (requirements.ttsSeverity && input.ttsRequired) {
    const ttsIssue = issueForTts(input.tts, input.action, requirements.ttsSeverity)
    if (ttsIssue) issues.push(ttsIssue)
  }

  return issues
}

function issueForEnvironment(status: EnvironmentCapabilityStatus, action: WorkflowActionId): WorkflowIssue | null {
  switch (status.state) {
    case 'ready':
    case 'optional':
      return null
    case 'checking':
      return createIssue({
        id: 'environment',
        action,
        title: '正在检查本地生成环境',
        detail: '正在确认 Python、FFmpeg 和制卡依赖；检查完成前不会假定环境可用。',
      })
    case 'unknown':
      return createIssue({
        id: 'environment',
        action,
        title: '检查本地生成环境',
        detail: '本地生成环境尚未检查，不能假定依赖已经就绪。',
        resolutionLabel: '检查环境',
      })
    case 'stale':
      return createIssue({
        id: 'environment',
        action,
        title: '重新检查本地环境',
        detail: '上次环境结果已经过期或配置发生变化，需要重新检查当前依赖。',
        resolutionLabel: '重新检查',
      })
    case 'action_required':
      return createIssue({
        id: 'environment',
        action,
        title: '修复本地生成环境',
        detail: '系统已发现可修复的环境问题，请完成修复并自动复检。',
        resolutionLabel: '修复环境',
      })
    case 'blocked':
      return createIssue({
        id: 'environment',
        action,
        title: '本地环境缺少必需依赖',
        detail: '生成所需依赖不可用；修复完成前不会输出缺媒体或无法导入的半成品。',
        resolutionLabel: '查看修复方法',
      })
    case 'disabled':
      return createIssue({
        id: 'environment',
        action,
        title: '启用本地生成环境',
        detail: '当前操作依赖本地生成能力，环境被停用时不能继续。',
        resolutionLabel: '启用环境',
      })
  }
}

function issueForModel(status: ServiceCapabilityStatus, action: WorkflowActionId): WorkflowIssue | null {
  switch (status.state) {
    case 'ready':
    case 'optional':
      return null
    case 'checking':
      return createIssue({
        id: 'api',
        action,
        title: '正在检查模型连接',
        detail: '正在验证当前模型、授权和连接状态，完成前不会开始新的模型任务。',
      })
    case 'unknown':
      return createIssue({
        id: 'api',
        action,
        title: '验证模型连接',
        detail: '当前模型尚未完成有效验证，不能把未测试的连接显示为可用。',
        resolutionLabel: '验证模型',
      })
    case 'stale':
      return createIssue({
        id: 'api',
        action,
        title: '重新验证模型连接',
        detail: '模型配置、凭据或验证时效已经变化，需要重新验证后再继续。',
        resolutionLabel: '重新验证',
      })
    case 'action_required':
      return modelActionRequiredIssue(status, action)
    case 'blocked':
      return modelBlockedIssue(status, action)
    case 'disabled':
      return createIssue({
        id: 'api',
        action,
        title: '启用模型服务',
        detail: '学习点分析和卡片正文生成需要可用模型，当前模型服务已停用。',
        resolutionLabel: '配置模型',
      })
  }
}

function modelActionRequiredIssue(status: ServiceCapabilityStatus, action: WorkflowActionId): WorkflowIssue {
  if (status.reason === 'hermes_stopped') {
    return createIssue({
      id: 'api',
      action,
      title: '启动 Hermes 代理',
      detail: 'Hermes 已配置，但本地代理尚未运行；启动并通过健康检查后才能继续。',
      resolutionLabel: '启动代理',
    })
  }
  if (status.reason === 'secret_missing') {
    return createIssue({
      id: 'api',
      action,
      title: '完成模型授权',
      detail: '当前模型缺少所需凭据，请完成授权后再验证连接。',
      resolutionLabel: '配置授权',
    })
  }
  return createIssue({
    id: 'api',
    action,
    title: '完成模型准备',
    detail: '当前模型需要一次明确的准备操作，完成后系统会重新验证连接。',
    resolutionLabel: '完成准备',
  })
}

function modelBlockedIssue(status: ServiceCapabilityStatus, action: WorkflowActionId): WorkflowIssue {
  if (status.reason === 'hermes_missing') {
    return createIssue({
      id: 'api',
      action,
      title: '安装 Hermes 连接组件',
      detail: '本机没有可用的 Hermes 连接组件，无法调用当前模型。',
      resolutionLabel: '查看安装方法',
    })
  }
  if (status.reason === 'hermes_oauth_unready') {
    return createIssue({
      id: 'api',
      action,
      title: '完成 Hermes OAuth 授权',
      detail: 'Hermes 代理已找到，但 OAuth 尚未就绪，当前不能安全调用模型。',
      resolutionLabel: '完成授权',
    })
  }
  if (status.reason === 'hermes_port_conflict') {
    return createIssue({
      id: 'api',
      action,
      title: '解决 Hermes 端口冲突',
      detail: 'Hermes 所需端口被其他进程占用，请解决冲突后重新检查。',
      resolutionLabel: '查看端口问题',
    })
  }
  return createIssue({
    id: 'api',
    action,
    title: '修复模型连接',
    detail:
      status.reason === 'verification_failed'
        ? '最近一次模型验证失败，请检查授权、网络和连接参数。'
        : '当前模型连接不可用，请查看诊断并完成修复。',
    resolutionLabel: '修复模型',
  })
}

function issueForTts(
  status: ServiceCapabilityStatus,
  action: WorkflowActionId,
  severity: WorkflowIssueSeverity,
): WorkflowIssue | null {
  switch (status.state) {
    case 'ready':
    case 'optional':
      return null
    case 'checking':
      return createIssue({
        id: 'tts',
        action,
        severity,
        title: '正在检查语音服务',
        detail: ttsDetailForAction(action, '正在验证当前语音配置，完成前不能确认音频可用。'),
      })
    case 'unknown':
      return createIssue({
        id: 'tts',
        action,
        severity,
        title: '验证语音服务',
        detail: ttsDetailForAction(action, 'TTS 已启用但尚未完成有效验证。'),
        resolutionLabel: '验证语音',
      })
    case 'stale':
      return createIssue({
        id: 'tts',
        action,
        severity,
        title: '重新验证语音服务',
        detail: ttsDetailForAction(action, '语音配置、凭据或验证时效已经变化。'),
        resolutionLabel: '重新验证',
      })
    case 'action_required':
      return createIssue({
        id: 'tts',
        action,
        severity,
        title: status.reason === 'secret_missing' ? '完成语音授权' : '完成语音服务准备',
        detail: ttsDetailForAction(
          action,
          status.reason === 'secret_missing' ? '当前语音服务缺少所需凭据。' : '当前语音服务需要先完成准备操作。',
        ),
        resolutionLabel: status.reason === 'secret_missing' ? '配置授权' : '完成准备',
      })
    case 'blocked':
      return createIssue({
        id: 'tts',
        action,
        severity,
        title: '修复语音服务',
        detail: ttsDetailForAction(
          action,
          status.reason === 'verification_failed'
            ? '最近一次 TTS 验证失败，请检查授权、网络和语音参数。'
            : '当前语音服务不可用。',
        ),
        resolutionLabel: '修复语音',
      })
    case 'disabled':
      return createIssue({
        id: 'tts',
        action,
        severity,
        title: '启用语音服务',
        detail: ttsDetailForAction(action, '当前卡片方案要求语音，但 TTS 已停用。'),
        resolutionLabel: '启用语音',
      })
  }
}

function ttsDetailForAction(action: WorkflowActionId, detail: string): string {
  return action === 'analyze_source'
    ? detail + ' 素材分析可以继续，但生成卡片前必须解决。'
    : detail + ' 为避免缺少语音的半成品，当前操作不能继续。'
}

function createIssue({
  severity = 'blocker',
  ...value
}: Omit<WorkflowIssue, 'severity'> & {
  severity?: WorkflowIssueSeverity
}): WorkflowIssue {
  return { severity, ...value }
}
