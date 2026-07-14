import type { MouseEvent } from 'react'
import { AlertCircle, CheckCircle2, Layers3, Loader2, Minus, Settings2, Square, X } from 'lucide-react'

import type { WorkflowReadinessSnapshot, WorkflowStageId } from '../../app/readiness'

type WindowAction = 'minimize' | 'toggleMaximize' | 'close'

type TopbarProps = {
  inspectorActive: boolean
  inspectorActionLabel: string
  isCancelling: boolean
  status: string
  statusTone: string
  workerBusy: boolean
  workflowReadiness: WorkflowReadinessSnapshot
  onCancelCurrentWorker: () => void
  onMouseDown: (event: MouseEvent<HTMLElement>) => void
  onDoubleClick: (event: MouseEvent<HTMLElement>) => void
  onOpenSettings: () => void
  onToggleInspector: () => void
  onWindowAction: (action: WindowAction) => void
}

const stageLabels: Record<WorkflowStageId, string> = {
  setup: '启动准备',
  extract: '抽取学习点',
  generate: '生成卡片',
  export: '审核导出',
  verify: 'Anki 核验',
}

export function Topbar({
  inspectorActive,
  inspectorActionLabel,
  isCancelling,
  status,
  statusTone,
  workerBusy,
  workflowReadiness,
  onCancelCurrentWorker,
  onDoubleClick,
  onMouseDown,
  onOpenSettings,
  onToggleInspector,
  onWindowAction,
}: TopbarProps) {
  const stageLabel = stageLabels[workflowReadiness.stage]
  const readinessText = workflowReadiness.canProceed
    ? workflowReadiness.stage === 'verify'
      ? workflowReadiness.primaryActionLabel
      : stageLabel + '已就绪'
    : workflowReadiness.primaryActionLabel + ' · ' + workflowReadiness.blockers[0]?.title
  const operationNeedsAttention = statusTone === 'warn' || /取消|暂停|丢弃/.test(status)
  const showOperationStatus = workerBusy || operationNeedsAttention
  const visibleStatus = showOperationStatus ? status : readinessText
  const visibleTone = workerBusy
    ? statusTone
    : operationNeedsAttention
      ? statusTone === 'warn'
        ? 'warning'
        : 'idle'
      : workflowReadiness.canProceed
        ? 'success'
        : 'warning'

  return (
    <header className="topbar" onMouseDown={onMouseDown} onDoubleClick={onDoubleClick}>
      <div className="brand-lockup">
        <div className="app-mark" aria-hidden="true">
          <img src="app-icon.png" alt="" />
        </div>
        <div>
          <p className="eyebrow">Anki Card Generator</p>
          <h1>Anki 卡片生成器</h1>
        </div>
      </div>
      <div className="topbar-stage" aria-label="当前步骤">
        <span>当前步骤</span>
        <strong>{stageLabel}</strong>
      </div>
      <div className="window-drag-region" />
      <div className="topbar-actions">
        <div
          className={'status-chip ' + visibleTone}
          title={showOperationStatus ? status : workflowReadiness.blockers[0]?.detail ?? visibleStatus}
          role="status"
          aria-live="polite"
          aria-atomic="true"
        >
          {workerBusy ? (
            <Loader2 className="spin" size={16} />
          ) : operationNeedsAttention ? (
            <AlertCircle size={16} />
          ) : workflowReadiness.canProceed ? (
            <CheckCircle2 size={16} />
          ) : (
            <AlertCircle size={16} />
          )}
          <span>{visibleStatus}</span>
        </div>
        <button
          className="ghost-button quiet-button inspector-toggle"
          type="button"
          data-inspector-toggle="true"
          onClick={onToggleInspector}
          aria-pressed={inspectorActive}
          aria-expanded={inspectorActive}
        >
          <Layers3 size={18} />
          {inspectorActionLabel}
        </button>
        <button className="ghost-button" type="button" onClick={onOpenSettings}>
          <Settings2 size={18} />
          设置
        </button>
        {workerBusy ? (
          <button className="ghost-button cancel-button" type="button" onClick={onCancelCurrentWorker} disabled={isCancelling}>
            {isCancelling ? <Loader2 className="spin" size={18} /> : <X size={18} />}
            {isCancelling ? '取消中' : '取消任务'}
          </button>
        ) : null}
      </div>
      <div className="window-controls" aria-label="窗口控制">
        <button type="button" onClick={() => onWindowAction('minimize')} aria-label="最小化">
          <Minus size={17} />
        </button>
        <button type="button" onClick={() => onWindowAction('toggleMaximize')} aria-label="最大化">
          <Square size={15} />
        </button>
        <button className="close-window" type="button" onClick={() => onWindowAction('close')} aria-label="关闭">
          <X size={18} />
        </button>
      </div>
    </header>
  )
}