import { CircleDot } from 'lucide-react'

import type { WorkerProgress } from '../../domain/types'

type WorkerProgressPanelProps = {
  progress: WorkerProgress
  variant?: 'compact' | 'wide'
}

export function WorkerProgressPanel({ progress, variant = 'compact' }: WorkerProgressPanelProps) {
  return (
    <section className={`progress-panel ${variant === 'wide' ? 'wide' : ''} ${progress.percent >= 100 ? 'done' : ''}`}>
      <div className="progress-head">
        <span>{progress.command === 'export' ? '导出进度' : '生成进度'}</span>
        <strong>{progress.percent}%</strong>
      </div>
      <div className="progress-bar" aria-label="任务进度">
        <span style={{ width: `${progress.percent}%` }} />
      </div>
      <p>
        <CircleDot size={14} />
        {progress.message}
      </p>
    </section>
  )
}
