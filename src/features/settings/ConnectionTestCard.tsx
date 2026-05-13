import { CheckCircle2, CircleAlert, Loader2, PlugZap } from 'lucide-react'

type ConnectionTestCardProps = {
  buttonLabel: string
  disabled: boolean
  message: string
  meta: string
  ok?: boolean
  testing: boolean
  testingLabel: string
  title: string
  tone: string
  statusLabel: string
  onTest: () => void
}

export function ConnectionTestCard({
  buttonLabel,
  disabled,
  message,
  meta,
  ok,
  testing,
  testingLabel,
  title,
  tone,
  statusLabel,
  onTest,
}: ConnectionTestCardProps) {
  return (
    <div className={`api-test-card ${tone}`} aria-live="polite" aria-atomic="true">
      <div className="api-test-icon" aria-hidden="true">
        {testing ? (
          <Loader2 className="spin" size={22} />
        ) : ok ? (
          <CheckCircle2 size={22} />
        ) : ok === false ? (
          <CircleAlert size={22} />
        ) : (
          <PlugZap size={22} />
        )}
      </div>
      <div className="api-test-copy">
        <span className="label">{statusLabel}</span>
        <strong>{title}</strong>
        <p>{message}</p>
        <small>{meta}</small>
      </div>
      <button className="primary-button" type="button" onClick={onTest} disabled={disabled}>
        {testing ? <Loader2 className="spin" size={18} /> : <PlugZap size={18} />}
        {testing ? testingLabel : buttonLabel}
      </button>
    </div>
  )
}
