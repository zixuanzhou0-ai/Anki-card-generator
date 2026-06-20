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

function progressStageLabel(progress: WorkerProgress) {
  if (progress.stage_label) return progress.stage_label
  const stage = `${progress.command}:${progress.stage}`.toLowerCase()
  const message = (progress.message || '').toLowerCase()

  if (progress.percent >= 100 || stage.endsWith(':done')) return '任务完成'
  if (progress.command === 'verify_anki_import') return '核验导入'
  if (progress.command === 'extract_learning_points') {
    if (stage.includes('source') || stage.includes('subtitle') || stage.includes('prepare')) return '读取字幕'
    if (stage.includes('ai_review') || stage.includes('review') || message.includes('精筛')) return '抽取学习点'
    return '抽取学习点'
  }
  if (progress.command === 'generate_cards_from_learning_points' || progress.command === 'generate') {
    if (stage.includes('select_output_dir')) return '选择保存目录'
    if (stage.includes('source') || stage.includes('prepare')) return '准备制卡'
    if (stage.includes('ai') || stage.includes('model') || message.includes('正文')) return '生成卡片正文'
    if (stage.includes('cards') || stage.includes('field')) return '整理卡片字段'
    return '生成卡片'
  }
  if (progress.command === 'export') {
    if (stage.includes('tts') || message.includes('tts')) return '生成 TTS'
    if (stage.includes('media') || message.includes('切片')) return '切片媒体'
    if (stage.includes('package') || stage.includes('apkg') || message.includes('apkg')) return '打包 APKG'
    if (stage.includes('prepare')) return '准备导出'
    return '导出卡包'
  }
  if (progress.command === 'repair_env') return '修复环境'
  return '处理中'
}

function progressHelper(progress: WorkerProgress) {
  if (progress.command === 'generate_cards_from_learning_points') return '后台会自动分批处理，完成后统一进入审核导出。'
  return ''
}

export function WorkerProgressPanel({ progress, variant = 'compact' }: WorkerProgressPanelProps) {
  const helper = progressHelper(progress)
  const batchLabel =
    progress.completed_batches !== undefined && progress.total_batches
      ? `已完成 ${progress.completed_batches}/${progress.total_batches} 批`
      : ''
  const cacheLabel =
    progress.cache_hits !== undefined || progress.cache_misses !== undefined
      ? `缓存命中 ${progress.cache_hits ?? 0}，未命中 ${progress.cache_misses ?? 0}`
      : ''
  const detailLabel = [batchLabel, cacheLabel].filter(Boolean).join(' · ')
  const stageLabel = progressStageLabel(progress)

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
        <span title={progress.message}>{stageLabel}</span>
      </p>
      {detailLabel ? <small>{detailLabel}</small> : null}
      {helper ? <small>{helper}</small> : null}
    </section>
  )
}
