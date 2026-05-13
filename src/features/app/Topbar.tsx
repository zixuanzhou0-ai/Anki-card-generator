import type { MouseEvent } from 'react'
import { CheckCircle2, Download, Layers3, Loader2, Minus, Settings2, Square, Wand2, X } from 'lucide-react'

type WindowAction = 'minimize' | 'toggleMaximize' | 'close'

type TopbarProps = {
  appBusy: boolean
  hasExportableCards: boolean
  hasProject: boolean
  inspectorActive: boolean
  inspectorActionLabel: string
  isCancelling: boolean
  projectSummary?: {
    reviewCount: number
    selectedCardLabel: string
    segmentCount: number
    templateLabel: string
  }
  status: string
  statusTone: string
  workerBusy: boolean
  onCancelCurrentWorker: () => void
  onExport: () => void
  onGenerate: () => void
  onMouseDown: (event: MouseEvent<HTMLElement>) => void
  onDoubleClick: (event: MouseEvent<HTMLElement>) => void
  onOpenSettings: () => void
  onToggleInspector: () => void
  onWindowAction: (action: WindowAction) => void
}

export function Topbar({
  appBusy,
  hasExportableCards,
  hasProject,
  inspectorActive,
  inspectorActionLabel,
  isCancelling,
  projectSummary,
  status,
  statusTone,
  workerBusy,
  onCancelCurrentWorker,
  onDoubleClick,
  onExport,
  onGenerate,
  onMouseDown,
  onOpenSettings,
  onToggleInspector,
  onWindowAction,
}: TopbarProps) {
  return (
    <header className="topbar" onMouseDown={onMouseDown} onDoubleClick={onDoubleClick}>
      <div className="brand-lockup">
        <div className="app-mark" aria-hidden="true">
          <img src="/app-icon.png" alt="" />
        </div>
        <div>
          <p className="eyebrow">Anki Card Generator V1</p>
          <h1>Anki 卡片生成器</h1>
        </div>
      </div>
      <div className="window-drag-region" />
      <div className="topbar-actions">
        {projectSummary ? (
          <div className="mini-summary" aria-label="项目摘要">
            <span>{`${projectSummary.segmentCount} 个片段`}</span>
            <span>{projectSummary.selectedCardLabel}</span>
            <span>{`${projectSummary.reviewCount} 张待审`}</span>
            <span>{projectSummary.templateLabel}</span>
          </div>
        ) : null}
        <div className={`status-chip ${statusTone}`} title={status} role="status" aria-live="polite" aria-atomic="true">
          <CheckCircle2 size={16} />
          <span>{status}</span>
        </div>
        <button
          className="ghost-button inspector-toggle"
          type="button"
          onClick={onToggleInspector}
          aria-pressed={inspectorActive}
          aria-expanded={inspectorActive}
        >
          <Layers3 size={18} />
          {inspectorActionLabel}
        </button>
        <button className="ghost-button" type="button" onClick={onOpenSettings}>
          <Settings2 size={18} />
          设置
        </button>
        {workerBusy ? (
          <button className="ghost-button cancel-button" type="button" onClick={onCancelCurrentWorker} disabled={isCancelling}>
            {isCancelling ? <Loader2 className="spin" size={18} /> : <X size={18} />}
            {isCancelling ? '取消中' : '取消任务'}
          </button>
        ) : null}
        {hasProject && hasExportableCards && !workerBusy ? (
          <button className="ghost-button command-export" type="button" onClick={onExport} disabled={appBusy}>
            <Download size={18} />
            导出
          </button>
        ) : null}
        <button className="primary-button" type="button" onClick={onGenerate} disabled={appBusy}>
          {appBusy ? <Loader2 className="spin" size={18} /> : <Wand2 size={18} />}
          {hasProject ? '重新生成' : '生成卡片'}
        </button>
      </div>
      <div className="window-controls" aria-label="窗口控制">
        <button type="button" onClick={() => onWindowAction('minimize')} aria-label="最小化">
          <Minus size={17} />
        </button>
        <button type="button" onClick={() => onWindowAction('toggleMaximize')} aria-label="最大化">
          <Square size={15} />
        </button>
        <button className="close-window" type="button" onClick={() => onWindowAction('close')} aria-label="关闭">
          <X size={18} />
        </button>
      </div>
    </header>
  )
}
