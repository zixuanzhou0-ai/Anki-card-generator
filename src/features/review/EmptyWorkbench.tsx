import { ClipboardList, FileSearch, Layers3, Settings2 } from 'lucide-react'

import type { SourceMode, WorkspaceStage } from '../../domain/types'

type EmptyWorkbenchProps = {
  level: string
  sourceMode: SourceMode
  templateLabel: string
  workspaceStage: WorkspaceStage
}

function sourceModeLabel(sourceMode: SourceMode) {
  if (sourceMode === 'url') return '视频链接'
  return '本地视频'
}

const stageCopy: Record<WorkspaceStage, { kicker: string; title: string; detail: string }> = {
  source: {
    kicker: '第 1 步 · 素材',
    title: '先确认视频和字幕是否匹配',
    detail: '选择本地视频或视频链接。SRT 可以手动选择，也可以按同名文件自动匹配；下一步会定义学习难度和复习方式。',
  },
  generate: {
    kicker: '第 2 步 · 学习设置',
    title: '现在定义将生成怎样的卡片',
    detail: '确认学习水平、复习密度和卡片模式。继续后会汇总素材、模型、TTS 与所有阻塞项，再开始抽取。',
  },
  review: {
    kicker: '第 3 步 · 抽取与制卡',
    title: '准备抽取可制卡的学习点',
    detail: '就绪检查通过后，先得到可筛选的学习点清单；只有你选中的项目才会进入卡片生成与 APKG 导出。',
  },
}

export function EmptyWorkbench({
  level,
  sourceMode,
  templateLabel,
  workspaceStage,
}: EmptyWorkbenchProps) {
  const copy = stageCopy[workspaceStage]

  return (
    <div className="empty-workbench">
      <section className="workbench-empty-state">
        <div className="workbench-empty-icon" aria-hidden="true">
          {workspaceStage === 'source' ? <FileSearch size={24} /> : workspaceStage === 'generate' ? <Settings2 size={24} /> : <ClipboardList size={24} />}
        </div>
        <div>
          <span className="hero-kicker">{copy.kicker}</span>
          <h2>{copy.title}</h2>
          <p>{copy.detail}</p>
        </div>
      </section>
      <div className="workbench-result-map" aria-label="本阶段将完成的内容">
        <span>
          <FileSearch size={17} />
          {workspaceStage === 'source' ? '素材与字幕匹配' : '素材已保留'}
        </span>
        <span>
          <Layers3 size={17} />
          {workspaceStage === 'generate' ? '卡片方案预览' : '可制卡学习点'}
        </span>
        <span>
          <ClipboardList size={17} />
          {workspaceStage === 'review' ? '抽取后逐项选择' : '下一步有明确确认'}
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
          <small>卡片模式</small>
          <strong>{templateLabel}</strong>
        </span>
      </div>
    </div>
  )
}