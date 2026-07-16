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

const SECURITY_AUTHORIZATION_ACTIONS = new Set<WorkerErrorActionId>([
  'allow-private-network-url',
  'allow-ytdlp-remote-components',
])

export function WorkerErrorActionsPanel({
  actions,
  onAction,
}: {
  actions: WorkerErrorAction[]
  onAction: (actionId: WorkerErrorActionId) => void
}) {
  if (!actions.length) return null
  const requiresAuthorization = actions.some((action) => SECURITY_AUTHORIZATION_ACTIONS.has(action.id))

  return (
    <section
      className={`worker-recovery-panel ${requiresAuthorization ? 'security-authorization' : ''}`}
      aria-label="失败后的可尝试操作"
    >
      <div className="worker-recovery-copy">
        <strong>{requiresAuthorization ? '需要你的明确授权' : '任务没有完成'}</strong>
        <span>
          {requiresAuthorization
            ? '系统不会自行放宽网络安全限制。请只在你信任当前素材来源时授权，然后再重试。'
            : '可以从失败处继续处理；已经完成并通过校验的结果会继续保留。'}
        </span>
      </div>
      <div className="worker-recovery-buttons">
        {actions.map((action) => {
          const securityAuthorization = SECURITY_AUTHORIZATION_ACTIONS.has(action.id)
          return (
            <button
              aria-label={action.label}
              className={`worker-recovery-action ${securityAuthorization ? 'security-authorization' : ''}`}
              data-security-authorization={securityAuthorization ? 'true' : undefined}
              key={action.id}
              type="button"
              onClick={() => onAction(action.id)}
            >
              <strong>{action.label}</strong>
              <small>{action.description}</small>
            </button>
          )
        })}
      </div>
    </section>
  )
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

