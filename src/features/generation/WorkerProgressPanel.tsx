import { CircleDot } from 'lucide-react'

import type { WorkerProgress } from '../../domain/types'

type WorkerProgressPanelProps = {
  progress: WorkerProgress
  variant?: 'compact' | 'wide'
}

function progressLabel(command: string) {
  switch (command) {
    case 'extract_learning_points':
      return '学习点筛选进度'
    case 'generate_cards_from_learning_points':
      return '制卡进度'
    case 'export':
      return '导出进度'
    case 'repair_env':
      return '环境修复进度'
    default:
      return '生成进度'
  }
}

export function WorkerProgressPanel({ progress, variant = 'compact' }: WorkerProgressPanelProps) {
  return (
    <section className={`progress-panel ${variant === 'wide' ? 'wide' : ''} ${progress.percent >= 100 ? 'done' : ''}`}>
      <div className="progress-head">
        <span>{progressLabel(progress.command)}</span>
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
