export type ProductStep = 'source' | 'select' | 'deliver'

export type ArtifactStage =
  | 'empty'
  | 'source_ready'
  | 'learning_points_ready'
  | 'drafts_ready'
  | 'apkg_ready'
  | 'anki_verified'

export type OperationState =
  | 'idle'
  | 'queued'
  | 'running'
  | 'cancelling'
  | 'succeeded'
  | 'failed'
  | 'cancelled'
  | 'interrupted'

export type WorkflowActionId =
  | 'analyze_source'
  | 'generate_cards'
  | 'export_cards'
  | 'import_and_verify'
  | 'resume_task'
  | 'resolve_blocker'

export type ActionGateState = 'available' | 'blocked' | 'running' | 'completed'

export type WorkflowIssueSeverity = 'blocker' | 'warning'

export type WorkflowIssue = {
  id: string
  severity: WorkflowIssueSeverity
  /** The intended workflow action this issue blocks or warns about. */
  action: WorkflowActionId
  title: string
  detail: string
  resolutionLabel?: string
}

export type UserNoticeTone = 'info' | 'success' | 'warning' | 'error'

/**
 * A notice only describes the latest result. It never participates in readiness
 * or artifact derivation; callers must add a WorkflowIssue for a real blocker.
 */
export type UserNotice = {
  id: string
  tone: UserNoticeTone
  title: string
  detail?: string
  occurredAt: number
  relatedAction?: WorkflowActionId
  retryable?: boolean
}

export type TaskSnapshot = {
  schemaVersion: 1
  id: string
  action: WorkflowActionId
  state: OperationState
  startedAt: number
  updatedAt: number
  cancellable: boolean
  phaseLabel?: string
  message?: string
  overallPercent?: number | null
  remainingItems?: number
}

export type ArtifactEvidence = {
  sourceReady: boolean
  learningPointCount: number
  draftCardCount: number
  apkgReady: boolean
  ankiVerified: boolean
}

export type ActionGate = {
  action: WorkflowActionId
  state: ActionGateState
  primaryLabel: string
  blockers: WorkflowIssue[]
  warnings: WorkflowIssue[]
}

export type WorkflowUiSnapshot = {
  step: ProductStep
  artifactStage: ArtifactStage
  heading: string
  description: string
  primaryAction: ActionGate
  operation: TaskSnapshot | null
  notice: UserNotice | null
}

export type WorkflowStateView = {
  step: ProductStep
  artifacts: ArtifactEvidence
  selectedLearningPointCount: number
  exportableCardCount?: number
  repairRequiredCardCount: number
  operation: TaskSnapshot | null
  issues: readonly WorkflowIssue[]
  notice: UserNotice | null
}

type ProductStepMeta = {
  number: 1 | 2 | 3
  heading: string
  description: string
}

const STEP_META: Record<ProductStep, ProductStepMeta> = {
  source: {
    number: 1,
    heading: '添加学习素材',
    description: '选择视频或视频链接，系统会自动完成必要的生成预检。',
  },
  select: {
    number: 2,
    heading: '选择值得复习的内容',
    description: '从已经分析出的学习点中，选择真正值得进入 Anki 的内容。',
  },
  deliver: {
    number: 3,
    heading: '生成并导入',
    description: '生成卡片、审核可用结果，并在你确认后导入 Anki 核验。',
  },
}

const ACTIVE_OPERATION_STATES = new Set<OperationState>(['queued', 'running', 'cancelling'])

export function selectArtifactStage(evidence: ArtifactEvidence): ArtifactStage {
  // A downstream artifact is stronger evidence than an in-memory upstream list.
  // Learning-point results are intentionally released after card generation, so
  // deriving from every upstream list first would make a completed workflow move backwards.
  // The source itself remains the root contract; request invalidation clears all downstream evidence.
  if (!evidence.sourceReady) return 'empty'
  if (evidence.apkgReady && evidence.ankiVerified) return 'anki_verified'
  if (evidence.apkgReady) return 'apkg_ready'
  if (hasPositiveCount(evidence.draftCardCount)) return 'drafts_ready'
  if (hasPositiveCount(evidence.learningPointCount)) return 'learning_points_ready'
  if (evidence.sourceReady) return 'source_ready'
  return 'empty'
}

/**
 * Suggests the page to enter after a reliable artifact transition. This selector
 * deliberately does not change WorkflowStateView.step; navigation remains an
 * explicit UI event instead of being inferred from readiness on every render.
 */
export function selectProductStepForArtifact(stage: ArtifactStage): ProductStep {
  if (stage === 'empty' || stage === 'source_ready') return 'source'
  if (stage === 'learning_points_ready') return 'select'
  return 'deliver'
}

export function selectProductStepMeta(step: ProductStep): ProductStepMeta {
  return STEP_META[step]
}

export function selectActionGate(view: WorkflowStateView): ActionGate {
  const artifactStage = selectArtifactStage(view.artifacts)
  const operationGate = selectOperationGate(view.operation)
  const baseGate = operationGate ?? selectPageGate(view, artifactStage)
  const builtInIssues = selectBuiltInIssues(view, artifactStage, baseGate.action)
  const applicableIssues = [...builtInIssues, ...view.issues].filter((issue) => issue.action === baseGate.action)
  const blockers = applicableIssues.filter((issue) => issue.severity === 'blocker')
  const warnings = applicableIssues.filter((issue) => issue.severity === 'warning')

  if (baseGate.state === 'running' || baseGate.state === 'completed') {
    return { ...baseGate, blockers, warnings }
  }

  if (blockers.length === 0) {
    return { ...baseGate, blockers, warnings }
  }

  return {
    ...baseGate,
    state: 'blocked',
    primaryLabel: baseGate.state === 'blocked' ? baseGate.primaryLabel : `还需完成 ${String(blockers.length)} 项准备`,
    blockers,
    warnings,
  }
}

export function buildWorkflowUiSnapshot(view: WorkflowStateView): WorkflowUiSnapshot {
  const meta = selectProductStepMeta(view.step)

  return {
    step: view.step,
    artifactStage: selectArtifactStage(view.artifacts),
    heading: meta.heading,
    description: meta.description,
    primaryAction: selectActionGate(view),
    operation: view.operation,
    notice: view.notice,
  }
}

function selectPageGate(view: WorkflowStateView, artifactStage: ArtifactStage): ActionGate {
  if (view.step === 'source') {
    if (artifactStage === 'empty') {
      return baseGate('analyze_source', 'blocked', '选择素材后继续')
    }
    if (artifactStage === 'anki_verified') {
      return baseGate('analyze_source', 'available', '查看已核验的 Anki 牌组')
    }
    if (artifactStage === 'apkg_ready') {
      return baseGate('analyze_source', 'available', '查看已导出的 APKG')
    }
    if (artifactStage === 'drafts_ready') {
      return baseGate(
        'analyze_source',
        'available',
        `查看已生成的 ${String(positiveInteger(view.artifacts.draftCardCount))} 张卡片`,
      )
    }
    if (artifactStage === 'learning_points_ready') {
      return baseGate(
        'analyze_source',
        'available',
        `查看已分析的 ${String(view.artifacts.learningPointCount)} 个学习点`,
      )
    }
    return baseGate('analyze_source', 'available', '分析素材')
  }

  if (view.step === 'select') {
    if (!artifactAtLeast(artifactStage, 'learning_points_ready')) {
      return baseGate('generate_cards', 'blocked', '先分析素材')
    }
    if (!hasPositiveCount(view.selectedLearningPointCount)) {
      return baseGate('generate_cards', 'blocked', '至少选择 1 个学习点')
    }
    return baseGate('generate_cards', 'available', `生成选中的 ${String(view.selectedLearningPointCount)} 张`)
  }

  if (artifactStage === 'anki_verified') {
    return baseGate('import_and_verify', 'completed', '已在 Anki 中核验')
  }
  if (artifactStage === 'apkg_ready') {
    return baseGate('import_and_verify', 'available', '导入 Anki 并核验')
  }
  if (artifactStage === 'drafts_ready') {
    const exportableCardCount = positiveInteger(view.exportableCardCount)
    if (exportableCardCount < 1) {
      return baseGate('export_cards', 'blocked', '没有可安全导出的卡片')
    }
    return baseGate('export_cards', 'available', `导出可用的 ${String(exportableCardCount)} 张`)
  }
  if (artifactStage === 'learning_points_ready') {
    if (!hasPositiveCount(view.selectedLearningPointCount)) {
      return baseGate('generate_cards', 'blocked', '至少选择 1 个学习点')
    }
    return baseGate('generate_cards', 'available', `生成选中的 ${String(view.selectedLearningPointCount)} 张`)
  }
  return baseGate('generate_cards', 'blocked', '先选择学习点')
}

function selectOperationGate(operation: TaskSnapshot | null): ActionGate | null {
  if (!operation) return null

  if (operation.state === 'interrupted') {
    const remainingItems = positiveInteger(operation.remainingItems)
    const label =
      operation.action === 'generate_cards' && remainingItems > 0
        ? `继续生成剩余 ${String(remainingItems)} 张`
        : '继续上次任务'
    return baseGate('resume_task', 'available', label)
  }

  if (!ACTIVE_OPERATION_STATES.has(operation.state)) return null

  if (operation.state === 'cancelling') {
    return baseGate(operation.action, 'running', '正在安全停止…')
  }
  if (operation.state === 'queued') {
    return baseGate(operation.action, 'running', '正在准备…')
  }

  return baseGate(operation.action, 'running', runningLabel(operation.action))
}

function selectBuiltInIssues(
  view: WorkflowStateView,
  artifactStage: ArtifactStage,
  action: WorkflowActionId,
): WorkflowIssue[] {
  const issues: WorkflowIssue[] = []

  if (action === 'analyze_source' && artifactStage === 'empty') {
    issues.push({
      id: 'source_missing',
      severity: 'blocker',
      action,
      title: '选择学习素材',
      detail: '请选择本地视频或填写可访问的视频链接。',
      resolutionLabel: '选择素材',
    })
  }

  if (action === 'generate_cards') {
    if (!artifactAtLeast(artifactStage, 'learning_points_ready')) {
      issues.push({
        id: 'learning_points_missing',
        severity: 'blocker',
        action,
        title: '先分析素材',
        detail: '没有可靠的学习点结果，不能根据卡片类型配置推断已有卡片。',
        resolutionLabel: '返回分析素材',
      })
    } else if (!hasPositiveCount(view.selectedLearningPointCount)) {
      issues.push({
        id: 'selection_empty',
        severity: 'blocker',
        action,
        title: '选择学习点',
        detail: '至少选择一个可制卡的学习点。',
        resolutionLabel: '选择学习点',
      })
    }
  }

  if (action === 'export_cards') {
    const exportableCardCount = positiveInteger(view.exportableCardCount)
    if (exportableCardCount < 1) {
      issues.push({
        id: 'exportable_cards_missing',
        severity: 'blocker',
        action,
        title: '没有可安全导出的卡片',
        detail: '请修复失败项或重新生成，系统不会输出空牌组或半成品。',
        resolutionLabel: '查看需修复卡片',
      })
    }

    const repairRequiredCardCount = positiveInteger(view.repairRequiredCardCount)
    if (repairRequiredCardCount > 0) {
      issues.push({
        id: 'repair_required_cards_excluded',
        severity: 'warning',
        action,
        title: '部分卡片需要修复',
        detail: `${String(repairRequiredCardCount)} 张需要修复的卡片会自动排除，不会混入本次导出。`,
        resolutionLabel: '查看需修复卡片',
      })
    }
  }

  return issues
}

function runningLabel(action: WorkflowActionId): string {
  switch (action) {
    case 'analyze_source':
      return '正在分析素材…'
    case 'generate_cards':
      return '正在生成卡片…'
    case 'export_cards':
      return '正在导出 APKG…'
    case 'import_and_verify':
      return '正在导入并核验…'
    case 'resume_task':
      return '正在恢复任务…'
    case 'resolve_blocker':
      return '正在完成准备…'
  }
}

function baseGate(action: WorkflowActionId, state: ActionGateState, primaryLabel: string): ActionGate {
  return {
    action,
    state,
    primaryLabel,
    blockers: [],
    warnings: [],
  }
}

function hasPositiveCount(value: number | undefined): boolean {
  return positiveInteger(value) > 0
}

function positiveInteger(value: number | undefined): number {
  if (!Number.isFinite(value)) return 0
  return Math.max(0, Math.floor(value ?? 0))
}

function artifactAtLeast(current: ArtifactStage, expected: ArtifactStage): boolean {
  const order: Record<ArtifactStage, number> = {
    empty: 0,
    source_ready: 1,
    learning_points_ready: 2,
    drafts_ready: 3,
    apkg_ready: 4,
    anki_verified: 5,
  }
  return order[current] >= order[expected]
}
