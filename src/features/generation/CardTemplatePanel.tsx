import { CheckCircle2, Circle, FileText } from 'lucide-react'

import { reviewDensityOptions } from '../../domain/options'
import type { DocumentStudyMode, ReviewDensity, SourceMode, TemplateId } from '../../domain/types'

type CardTemplatePanelProps = {
  documentStudyMode: DocumentStudyMode
  sourceMode: SourceMode
  reviewDensity: ReviewDensity
  onSelectReviewDensity: (reviewDensity: ReviewDensity) => void
  onSelectTemplate: (templateId: TemplateId) => void
}

const reviewModeCopy: Record<ReviewDensity, { label: string; note: string }> = {
  full: {
    label: '完整复读',
    note: '完整解释、用法、边界和听辨提示',
  },
  fast: {
    label: '快速复读',
    note: '只保留原句、中文意思、视频、原声、慢读和表达发音',
  },
}

export function CardTemplatePanel({
  documentStudyMode,
  sourceMode,
  reviewDensity,
  onSelectReviewDensity,
  onSelectTemplate,
}: CardTemplatePanelProps) {
  const isDocument = sourceMode === 'document'
  const activeReviewMode = reviewModeCopy[reviewDensity] ?? reviewModeCopy.full
  const selectImmersiveMode = (density: ReviewDensity) => {
    onSelectTemplate('immersive_v11')
    onSelectReviewDensity(density)
  }

  return (
    <section className="panel generation-panel">
      <div className="panel-heading">
        <FileText size={20} />
        <div className="panel-title-stack">
          <h3>卡片模式</h3>
          <span>
            {isDocument
              ? documentStudyMode === 'language_reading'
                ? '文档精读卡'
                : '知识问答卡'
              : activeReviewMode.label}
          </span>
        </div>
      </div>
      {isDocument ? (
        <div className="doc-card-mode compact-card-mode">
          <FileText size={18} />
          <div>
            <strong>{documentStudyMode === 'language_reading' ? '文档精读卡' : '知识问答卡'}</strong>
            <span>
              {documentStudyMode === 'language_reading'
                ? '从文档里提取表达、词汇或语法点；不生成视频/TTS 学习卡，可导出项可一键选择。'
                : '正面是问题或概念提示，反面是结构化答案、解释、例子和为什么值得记。'}
            </span>
          </div>
        </div>
      ) : (
        <div className="card-template-body compact-card-mode">
          <div className="template-radio-list" role="radiogroup" aria-label="选择卡片模式">
            {reviewDensityOptions.map((item) => {
              const selected = reviewDensity === item.id
              const copy = reviewModeCopy[item.id] ?? { label: item.label, note: item.note }
              return (
                <button
                  type="button"
                  key={item.id}
                  className={`template-radio-option ${selected ? 'selected' : ''}`}
                  role="radio"
                  aria-checked={selected}
                  onClick={() => selectImmersiveMode(item.id)}
                >
                  <span className="option-state" aria-hidden="true">
                    {selected ? <CheckCircle2 size={16} /> : <Circle size={16} />}
                  </span>
                  <span className="option-copy">
                    <strong>{copy.label}</strong>
                    <small>{copy.note}</small>
                  </span>
                </button>
              )
            })}
          </div>
        </div>
      )}
    </section>
  )
}
