import { Loader2, Settings2, Sparkles, Wand2 } from 'lucide-react'

import type { SourceMode } from '../../domain/types'
import { segmentBudgetLabel } from '../../domain/quality'

type EmptyWorkbenchProps = {
  appBusy: boolean
  level: string
  maxSegments: number
  sourceMode: SourceMode
  templateLabel: string
  onGenerate: () => void
  onOpenSettings: () => void
}

function sourceModeLabel(sourceMode: SourceMode) {
  if (sourceMode === 'url') return '视频链接'
  if (sourceMode === 'document') return '文档资料'
  return '本地视频'
}

export function EmptyWorkbench({
  appBusy,
  level,
  maxSegments,
  sourceMode,
  templateLabel,
  onGenerate,
  onOpenSettings,
}: EmptyWorkbenchProps) {
  return (
    <div className="empty-workbench">
      <section className="workbench-hero">
        <span className="hero-kicker">Ready to build</span>
        <Sparkles size={32} />
        <h2>把真实素材变成 Anki 复习卡</h2>
        <p>
          选择视频、字幕或文档，设置学习范围，然后让模型提取值得记的表达。生成完成后，这里会显示片段、评分、理由和可导出的卡片。
        </p>
        <div className="hero-actions">
          <button className="primary-button" type="button" onClick={onGenerate} disabled={appBusy}>
            {appBusy ? <Loader2 className="spin" size={18} /> : <Wand2 size={18} />}
            开始生成
          </button>
          <button className="ghost-button" type="button" onClick={onOpenSettings}>
            <Settings2 size={18} />
            检查 API
          </button>
        </div>
      </section>
      <div className="workflow-strip" aria-label="生成流程">
        <span>
          <strong>1</strong>
          素材
        </span>
        <span>
          <strong>2</strong>
          评审
        </span>
        <span>
          <strong>3</strong>
          制卡
        </span>
        <span>
          <strong>4</strong>
          导出
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
