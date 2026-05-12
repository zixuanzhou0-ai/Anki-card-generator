import { CircleDot } from 'lucide-react'

import type { WorkerProgress } from '../../domain/types'

type WorkerProgressPanelProps = {
  progress: WorkerProgress
}

export function WorkerProgressPanel({ progress }: WorkerProgressPanelProps) {
  return (
    <section className={`panel progress-panel ${progress.percent >= 100 ? 'done' : ''}`}>
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

