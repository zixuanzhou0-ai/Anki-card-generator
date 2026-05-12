import type { WorkerErrorAction, WorkerErrorActionId } from '../../domain/workerErrors'

type StatusPanelProps = {
  appBusy: boolean
  requestEditedDuringRun: boolean
  status: string
  statusTone: string
  workerBusy: boolean
  workerErrorActions: WorkerErrorAction[]
  onWorkerErrorAction: (actionId: WorkerErrorActionId) => void
}

export function StatusPanel({
  appBusy,
  requestEditedDuringRun,
  status,
  statusTone,
  workerBusy,
  workerErrorActions,
  onWorkerErrorAction,
}: StatusPanelProps) {
  return (
    <section className={`panel status-panel ${statusTone}`} role="status" aria-live="polite" aria-atomic="true">
      <div className="status-panel-head">
        <span>当前状态</span>
        <strong>{appBusy ? '处理中' : '就绪'}</strong>
      </div>
      <p>{status}</p>
      {workerErrorActions.length ? (
        <div className="worker-error-actions" aria-label="失败后的可尝试操作">
          {workerErrorActions.map((action) => (
            <button
              key={action.id}
              className="worker-error-action"
              type="button"
              title={action.description}
              onClick={() => onWorkerErrorAction(action.id)}
            >
              {action.label}
            </button>
          ))}
        </div>
      ) : null}
      {workerBusy && requestEditedDuringRun ? (
        <small className="run-edit-note">本次任务使用开始时的配置；你刚修改的设置会在下一次生成生效。</small>
      ) : null}
    </section>
  )
}

