import type { WorkflowActionId, WorkflowIssue, WorkflowUiSnapshot } from '../../app/workflowState'
import { learningLanguageOptions, normalizeLearningLanguage } from '../../domain/options'
import type { GenerateRequest, Level, ReviewDensity, SourceMode, TemplateId } from '../../domain/types'
import type { WorkerErrorAction, WorkerErrorActionId } from '../../domain/workerErrors'
import { CardTemplatePanel } from '../generation/CardTemplatePanel'
import { WorkerErrorActionsPanel } from '../generation/StatusPanel'
import { LearningSettingsPanel } from '../learning/LearningSettingsPanel'
import { SourceSetupPanel } from './SourceSetupPanel'

type LevelOption = {
  id: Level
  label: string
  note: string
}

export type SourceWorkspaceProps = {
  snapshot: WorkflowUiSnapshot
  request: GenerateRequest
  levels: LevelOption[]
  previewRate: number
  onPatchRequest: (patch: Partial<GenerateRequest>) => void
  onPreviewRateChange: (rate: number) => void
  onSelectCurrentLevel: (level: Level) => void
  onSelectPath: (kind: 'video' | 'subtitle' | 'video-folder') => void
  onSelectSourceMode: (mode: SourceMode) => void
  onSelectReviewDensity: (reviewDensity: ReviewDensity) => void
  onSelectTemplate: (templateId: TemplateId) => void
  onPrimaryAction: (action: WorkflowActionId) => void
  onAbandonRecovery?: () => void
  onResolveBlockers?: (blockers: WorkflowIssue[]) => void
  workerErrorActions: WorkerErrorAction[]
  onWorkerErrorAction: (actionId: WorkerErrorActionId) => void
}

function ignoreWhileLocked<Args extends unknown[]>(locked: boolean, callback: (...args: Args) => void) {
  return (...args: Args) => {
    if (!locked) callback(...args)
  }
}
export function SourceWorkspace({
  snapshot,
  request,
  levels,
  previewRate,
  onPatchRequest,
  onPreviewRateChange,
  onSelectCurrentLevel,
  onSelectPath,
  onSelectSourceMode,
  onSelectReviewDensity,
  onSelectTemplate,
  onPrimaryAction,
  onAbandonRecovery,
  onResolveBlockers,
  workerErrorActions,
  onWorkerErrorAction,
}: SourceWorkspaceProps) {
  const gate = snapshot.primaryAction
  const running = gate.state === 'running'
  const completed = gate.state === 'completed'
  const sourceMissing = gate.blockers.some((issue) => issue.id === 'source_missing')
  const blockedActionAvailable = gate.state === 'blocked' && !sourceMissing && Boolean(onResolveBlockers)
  const primaryDisabled = running || completed || (gate.state === 'blocked' && !blockedActionAvailable)
  const preferenceSummary = buildPreferenceSummary(request, previewRate)
  const progress = normalizeProgress(snapshot.operation?.overallPercent)
  const guardedPatchRequest = ignoreWhileLocked(running, onPatchRequest)
  const guardedPreviewRateChange = ignoreWhileLocked(running, onPreviewRateChange)
  const guardedSelectCurrentLevel = ignoreWhileLocked(running, onSelectCurrentLevel)
  const guardedSelectPath = ignoreWhileLocked(running, onSelectPath)
  const guardedSelectSourceMode = ignoreWhileLocked(running, onSelectSourceMode)
  const guardedSelectReviewDensity = ignoreWhileLocked(running, onSelectReviewDensity)
  const guardedSelectTemplate = ignoreWhileLocked(running, onSelectTemplate)

  const handlePrimaryAction = () => {
    if (gate.state === 'blocked') {
      onResolveBlockers?.(gate.blockers)
      return
    }
    onPrimaryAction(gate.action)
  }

  return (
    <main className="source-workspace" aria-labelledby="source-workspace-title" aria-busy={running}>
      <header className="source-workspace-header">
        <span>第 1/3 步</span>
        <h1 id="source-workspace-title" data-workflow-page-title="true" tabIndex={-1}>
          {snapshot.heading}
        </h1>
        <p>{snapshot.description}</p>
      </header>

      <div className="source-workspace-content">
        <fieldset className="source-input-fields" disabled={running} aria-label="素材与学习偏好">
          <legend hidden>素材与学习偏好</legend>
          <SourceSetupPanel
            request={request}
            onPatchRequest={guardedPatchRequest}
            onSelectPath={guardedSelectPath}
            onSelectSourceMode={guardedSelectSourceMode}
          />

          <details className="source-preferences" aria-label="学习偏好设置">
            <summary>
              <span>学习偏好</span>
              <strong>{preferenceSummary}</strong>
              <small>修改</small>
            </summary>
            <div className="source-preferences-panels">
              <LearningSettingsPanel
                levels={levels}
                previewRate={previewRate}
                request={request}
                onPreviewRateChange={guardedPreviewRateChange}
                onPatchRequest={guardedPatchRequest}
                onSelectCurrentLevel={guardedSelectCurrentLevel}
              />
              <CardTemplatePanel
                documentStudyMode={request.document_study_mode}
                sourceMode={request.source_mode}
                reviewDensity={request.review_density}
                onSelectReviewDensity={guardedSelectReviewDensity}
                onSelectTemplate={guardedSelectTemplate}
              />
            </div>
          </details>
        </fieldset>

        <section className="source-workspace-feedback">
          {snapshot.operation ? (
            <div className="source-operation-summary">
              <strong>{snapshot.operation.phaseLabel || gate.primaryLabel}</strong>
              {snapshot.operation.message ? <span>{snapshot.operation.message}</span> : null}
              {progress !== null ? (
                <div
                  className="source-operation-progress"
                  role="progressbar"
                  aria-label="当前任务进度"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={progress}
                >
                  <span style={{ width: `${String(progress)}%` }} />
                  <small>{progress}%</small>
                </div>
              ) : null}
            </div>
          ) : null}

          {gate.blockers.length > 0 ? (
            <section className="source-blockers" aria-labelledby="source-blockers-title">
              <h2 id="source-blockers-title">开始前还需要处理</h2>
              <ul>
                {gate.blockers.map((issue) => (
                  <li key={issue.id}>
                    <strong>{issue.title}</strong>
                    <span>{issue.detail}</span>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {gate.warnings.length > 0 ? (
            <section className="source-warnings" aria-labelledby="source-warnings-title">
              <h2 id="source-warnings-title">请留意</h2>
              <ul>
                {gate.warnings.map((issue) => (
                  <li key={issue.id}>{issue.detail}</li>
                ))}
              </ul>
            </section>
          ) : null}

          {snapshot.notice ? (
            <div className={`source-notice ${snapshot.notice.tone}`} data-tone={snapshot.notice.tone}>
              <strong>{snapshot.notice.title}</strong>
              {snapshot.notice.detail ? <span>{snapshot.notice.detail}</span> : null}
            </div>
          ) : null}
          <WorkerErrorActionsPanel actions={workerErrorActions} onAction={onWorkerErrorAction} />
        </section>
      </div>

      <footer className="source-workspace-action-bar">
        <div>
          <small>{gate.blockers[0]?.detail ?? '准备完成后，系统会自动检查环境并分析素材。'}</small>
        </div>
        {gate.action === 'resume_task' && onAbandonRecovery ? (
          <button type="button" className="secondary-button" onClick={onAbandonRecovery}>
            放弃恢复
          </button>
        ) : null}
        <button
          type="button"
          className="primary-button source-workspace-primary"
          data-variant="primary"
          disabled={primaryDisabled}
          aria-describedby={gate.blockers.length > 0 ? 'source-blockers-title' : undefined}
          onClick={handlePrimaryAction}
        >
          {gate.primaryLabel}
        </button>
      </footer>
    </main>
  )
}

function buildPreferenceSummary(request: GenerateRequest, previewRate: number): string {
  const language =
    learningLanguageOptions.find((item) => item.code === normalizeLearningLanguage(request.language))?.label ??
    request.language
  const level = request.level_mode === 'manual' ? request.level : '自动判断水平'
  const reviewDensity = request.review_density === 'fast' ? '快速复读' : '完整复读'
  return `${language} · ${level} · ${reviewDensity} · ${String(previewRate)}× 预览`
}

function normalizeProgress(progress: number | null | undefined): number | null {
  if (typeof progress !== 'number' || !Number.isFinite(progress)) return null
  return Math.max(0, Math.min(100, Math.round(progress)))
}
