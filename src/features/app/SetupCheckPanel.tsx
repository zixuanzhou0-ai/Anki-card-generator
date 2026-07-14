import { AlertTriangle, CheckCircle2, CircleHelp, Wrench } from 'lucide-react'

import type {
  ReadinessBlocker,
  ReadinessBlockerAction,
  WorkflowReadinessSnapshot,
} from '../../app/readiness'

type SetupCheckPanelProps = {
  busy: boolean
  snapshot: WorkflowReadinessSnapshot
  onResolve: (action: ReadinessBlockerAction) => void
}

const actionLabels: Record<ReadinessBlockerAction, string> = {
  select_source: '选择素材',
  check_environment: '立即检查',
  repair_environment: '一键修复',
  test_api: '配置并测试模型',
  test_tts: '配置并测试 TTS',
  select_learning_points: '查看学习点',
  repair_cards: '查看需修复卡片',
  open_anki: '打开 Anki 核验',
}

function ReadinessIssueRow({
  busy,
  issue,
  warning = false,
  onResolve,
}: {
  busy: boolean
  issue: ReadinessBlocker
  warning?: boolean
  onResolve: (action: ReadinessBlockerAction) => void
}) {
  const Icon = warning ? AlertTriangle : issue.state === 'unknown' ? CircleHelp : Wrench

  return (
    <li className={'setup-check-item ' + (warning ? 'warning' : issue.state)}>
      <Icon size={18} aria-hidden="true" />
      <span>
        <strong>{issue.title}</strong>
        <small>{issue.detail}</small>
      </span>
      <button type="button" className="setup-check-action" onClick={() => onResolve(issue.action)} disabled={busy}>
        {actionLabels[issue.action]}
      </button>
    </li>
  )
}

export function SetupCheckPanel({ busy, snapshot, onResolve }: SetupCheckPanelProps) {
  if (snapshot.canProceed && snapshot.warnings.length === 0) {
    return (
      <section className="setup-check-panel compact-ready" aria-label="启动检查台">
        <CheckCircle2 size={19} aria-hidden="true" />
        <span>
          <strong>当前阶段已就绪</strong>
          <small>{snapshot.primaryActionLabel}</small>
        </span>
      </section>
    )
  }

  return (
    <section className="setup-check-panel" aria-label="启动检查台">
      <div className="setup-check-head">
        <span>
          <small>启动检查台</small>
          <strong>
            {snapshot.blockers.length > 0
              ? snapshot.blockers.length + ' 项准备未完成'
              : '当前阶段可继续'}
          </strong>
        </span>
        <span className={snapshot.blockers.length > 0 ? 'setup-check-count blocked' : 'setup-check-count ready'}>
          {snapshot.blockers.length > 0 ? snapshot.blockers.length : '✓'}
        </span>
      </div>
      {snapshot.blockers.length > 0 ? (
        <ul className="setup-check-list">
          {snapshot.blockers.map((issue) => (
            <ReadinessIssueRow key={issue.id} busy={busy} issue={issue} onResolve={onResolve} />
          ))}
        </ul>
      ) : null}
      {snapshot.warnings.length > 0 ? (
        <div className="setup-check-warnings">
          <strong>之后需要处理</strong>
          <ul className="setup-check-list">
            {snapshot.warnings.map((issue) => (
              <ReadinessIssueRow key={issue.id} busy={busy} issue={issue} warning onResolve={onResolve} />
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  )
}