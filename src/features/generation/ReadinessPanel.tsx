import { CheckCircle2, CircleAlert } from 'lucide-react'

export type ReadinessItem = {
  id: string
  label: string
  done: boolean
  detail: string
}

type ReadinessPanelProps = {
  items: ReadinessItem[]
}

export function ReadinessPanel({ items }: ReadinessPanelProps) {
  const readyCount = items.filter((item) => item.done).length

  return (
    <details className="panel readiness-panel readiness-details">
      <summary className="readiness-head">
        <span>生成就绪</span>
        <strong>
          {readyCount}/{items.length}
        </strong>
      </summary>
      <div className="readiness-grid">
        {items.map((item) => (
          <span className={item.done ? 'ready' : 'pending'} key={item.id}>
            {item.done ? <CheckCircle2 size={14} /> : <CircleAlert size={14} />}
            <strong>{item.label}</strong>
            <small>{item.detail}</small>
          </span>
        ))}
      </div>
    </details>
  )
}

