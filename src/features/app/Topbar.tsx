import type { MouseEvent } from 'react'
import { AlertCircle, CheckCircle2, Info, Layers3, Loader2, Minus, Settings2, Square, X } from 'lucide-react'

import type { OperationState, ProductStep, WorkflowUiSnapshot } from '../../app/workflowState'

type WindowAction = 'minimize' | 'toggleMaximize' | 'close'

type TopbarProps = {
  inspectorActive: boolean
  inspectorActionLabel: string
  workflowUiSnapshot: WorkflowUiSnapshot
  modalActive?: boolean
  forceCancelBusy?: boolean
  onCancelCurrentWorker: () => void
  onForceCancel?: () => void
  showForceCancel?: boolean
  onMouseDown: (event: MouseEvent<HTMLElement>) => void
  onDoubleClick: (event: MouseEvent<HTMLElement>) => void
  onOpenSettings: () => void
  onToggleInspector: () => void
  onWindowAction: (action: WindowAction) => void
}

type StatusPresentation = {
  text: string
  title: string
  tone: 'idle' | 'success' | 'warning' | 'working'
  icon: 'alert' | 'info' | 'loader' | 'success'
}

const stepNumbers: Record<ProductStep, 1 | 2 | 3> = {
  source: 1,
  select: 2,
  deliver: 3,
}

const activeOperationStates = new Set<OperationState>(['queued', 'running', 'cancelling'])
const attentionOperationStates = new Set<OperationState>(['failed', 'cancelled', 'interrupted'])

export function Topbar({
  inspectorActive,
  inspectorActionLabel,
  workflowUiSnapshot,
  modalActive = false,
  forceCancelBusy = false,
  onCancelCurrentWorker,
  onForceCancel,
  showForceCancel = false,
  onDoubleClick,
  onMouseDown,
  onOpenSettings,
  onToggleInspector,
  onWindowAction,
}: TopbarProps) {
  const { operation, step } = workflowUiSnapshot
  const statusPresentation = selectStatusPresentation(workflowUiSnapshot)
  const operationActive = operation ? activeOperationStates.has(operation.state) : false
  const isCancelling = operation?.state === 'cancelling'
  const showCancel = operationActive && operation?.cancellable === true
  const showForceCancelAction = isCancelling && showForceCancel && typeof onForceCancel === 'function'

  return (
    <header className="topbar" aria-hidden={modalActive || undefined} inert={modalActive || undefined} onMouseDown={onMouseDown} onDoubleClick={onDoubleClick}>
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
        <strong>{`第 ${String(stepNumbers[step])}/3 步：${workflowUiSnapshot.heading}`}</strong>
      </div>
      <div className="window-drag-region" />
      <div className="topbar-actions">
        <div
          className={'status-chip ' + statusPresentation.tone}
          title={statusPresentation.title}
          role={modalActive ? undefined : 'status'}
          aria-live={modalActive ? undefined : 'polite'}
          aria-atomic={modalActive ? undefined : 'true'}
        >
          {statusPresentation.icon === 'loader' ? (
            <Loader2 className="spin" size={16} />
          ) : statusPresentation.icon === 'alert' ? (
            <AlertCircle size={16} />
          ) : statusPresentation.icon === 'success' ? (
            <CheckCircle2 size={16} />
          ) : (
            <Info size={16} />
          )}
          <span>{statusPresentation.text}</span>
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
        {showCancel ? (
          <button
            className="ghost-button cancel-button"
            type="button"
            onClick={onCancelCurrentWorker}
            disabled={isCancelling}
          >
            {isCancelling ? <Loader2 className="spin" size={18} /> : <X size={18} />}
            {isCancelling ? '取消中' : '取消任务'}
          </button>
        ) : null}
        {showForceCancelAction ? (
          <button
            className="ghost-button cancel-button force-cancel-button"
            type="button"
            aria-label="强制结束任务"
            aria-busy={forceCancelBusy || undefined}
            onClick={onForceCancel}
            disabled={forceCancelBusy}
          >
            {forceCancelBusy ? <Loader2 className="spin" size={18} /> : <AlertCircle size={18} />}
            {forceCancelBusy ? '正在强制结束…' : '强制结束任务'}
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

function selectStatusPresentation(snapshot: WorkflowUiSnapshot): StatusPresentation {
  const { operation, notice, primaryAction } = snapshot

  if (operation && activeOperationStates.has(operation.state)) {
    const text = operation.message?.trim() || operation.phaseLabel?.trim() || primaryAction.primaryLabel
    return {
      text,
      title: text,
      tone: 'working',
      icon: 'loader',
    }
  }

  if (operation && attentionOperationStates.has(operation.state)) {
    const fallbackText =
      operation.state === 'failed'
        ? '任务失败'
        : operation.state === 'cancelled'
          ? '任务已取消'
          : primaryAction.primaryLabel
    const text = operation.message?.trim() || operation.phaseLabel?.trim() || fallbackText
    return {
      text,
      title: text,
      tone: 'warning',
      icon: 'alert',
    }
  }

  if (notice) {
    const title = notice.detail?.trim() || notice.title
    if (notice.tone === 'success') {
      return { text: notice.title, title, tone: 'success', icon: 'success' }
    }
    if (notice.tone === 'warning' || notice.tone === 'error') {
      return { text: notice.title, title, tone: 'warning', icon: 'alert' }
    }
    return { text: notice.title, title, tone: 'idle', icon: 'info' }
  }

  if (primaryAction.state === 'blocked') {
    const blocker = primaryAction.blockers[0]
    const text = blocker ? `${primaryAction.primaryLabel} · ${blocker.title}` : primaryAction.primaryLabel
    return {
      text,
      title: blocker?.detail ?? text,
      tone: 'warning',
      icon: 'alert',
    }
  }

  if (primaryAction.state === 'completed') {
    return {
      text: primaryAction.primaryLabel,
      title: primaryAction.primaryLabel,
      tone: 'success',
      icon: 'success',
    }
  }

  return {
    text: primaryAction.primaryLabel,
    title: primaryAction.primaryLabel,
    tone: 'idle',
    icon: 'info',
  }
}
