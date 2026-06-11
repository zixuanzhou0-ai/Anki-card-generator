import { ClipboardList, FileSearch, Layers3 } from 'lucide-react'

import type { SourceMode } from '../../domain/types'
import { segmentBudgetLabel } from '../../domain/quality'

type EmptyWorkbenchProps = {
  level: string
  maxSegments: number
  sourceMode: SourceMode
  templateLabel: string
}

function sourceModeLabel(sourceMode: SourceMode) {
  if (sourceMode === 'url') return '视频链接'
  if (sourceMode === 'document') return '文档资料'
  return '本地视频'
}

export function EmptyWorkbench({
  level,
  maxSegments,
  sourceMode,
  templateLabel,
}: EmptyWorkbenchProps) {
  return (
    <div className="empty-workbench">
      <section className="workbench-empty-state">
        <div className="workbench-empty-icon" aria-hidden="true">
          <ClipboardList size={24} />
        </div>
        <div>
          <span className="hero-kicker">等待生成结果</span>
          <h2>审核区会在生成后展开</h2>
          <p>按左侧三步完成素材、学习设置和确认抽取。先查看学习点，再把选中的学习点生成卡片并导出。</p>
        </div>
      </section>
      <div className="workbench-result-map" aria-label="生成后可检查内容">
        <span>
          <FileSearch size={17} />
          片段队列
        </span>
        <span>
          <Layers3 size={17} />
          卡片详情
        </span>
        <span>
          <ClipboardList size={17} />
          更多学习点
        </span>
      </div>
      <div className="workbench-summary-grid" aria-label="当前生成配置摘要">
        <span>
          <small>输入源</small>
          <strong>{sourceModeLabel(sourceMode)}</strong>
        </span>
        <span>
          <small>学习水平</small>
          <strong>{level}</strong>
        </span>
        <span>
          <small>片段预算</small>
          <strong>{segmentBudgetLabel(maxSegments)}</strong>
        </span>
        <span>
          <small>模板</small>
          <strong>{templateLabel}</strong>
        </span>
      </div>
    </div>
  )
}
