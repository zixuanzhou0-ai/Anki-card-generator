import { CheckCircle2, ChevronDown, Circle, FileText, Layers3, Palette, Zap } from 'lucide-react'

import { cardStyleOptions, reviewDensityOptions } from '../../domain/options'
import type { CardStyleId, DocumentStudyMode, ReviewDensity, SourceMode, TemplateId } from '../../domain/types'

type TemplateOption = {
  id: TemplateId
  label: string
  note: string
  locked?: boolean
}

type CardTemplatePanelProps = {
  activeTemplateLabel: string
  cardStyleId: CardStyleId
  documentStudyMode: DocumentStudyMode
  sourceMode: SourceMode
  templateId: TemplateId
  templateOptions: TemplateOption[]
  reviewDensity: ReviewDensity
  onSelectCardStyle: (styleId: CardStyleId) => void
  onSelectReviewDensity: (reviewDensity: ReviewDensity) => void
  onSelectTemplate: (templateId: TemplateId) => void
}

export function CardTemplatePanel({
  activeTemplateLabel,
  cardStyleId,
  documentStudyMode,
  sourceMode,
  templateId,
  templateOptions,
  reviewDensity,
  onSelectCardStyle,
  onSelectReviewDensity,
  onSelectTemplate,
}: CardTemplatePanelProps) {
  const isDocument = sourceMode === 'document'
  const isCibaTemplate = templateId === 'ciba_tianxia_v1'
  const activeStyle = cardStyleOptions.find((style) => style.id === cardStyleId) ?? cardStyleOptions[0]
  const summaryText = isDocument
    ? documentStudyMode === 'language_reading'
      ? '文档精读卡'
      : '知识问答卡'
    : isCibaTemplate
      ? `${activeTemplateLabel} · ${activeStyle.label}`
      : activeTemplateLabel

  return (
    <section className="panel generation-panel">
      <details className="compact-details preference-details">
        <summary>
          <span>卡片和模板</span>
          <strong>{summaryText}</strong>
          <span className="details-affordance" aria-hidden="true">
            <span className="details-affordance-open">展开</span>
            <span className="details-affordance-close">收起</span>
            <ChevronDown size={14} />
          </span>
        </summary>
        {isDocument ? (
          <div className="doc-card-mode">
            <FileText size={18} />
            <div>
              <strong>{documentStudyMode === 'language_reading' ? '文档精读卡' : '知识问答卡'}</strong>
              <span>
                {documentStudyMode === 'language_reading'
                  ? '从文档里提取表达、词汇或语法点；不生成听力卡，可用卡默认全选。'
                  : '正面是问题或概念提示，反面是结构化答案、解释、例子和为什么值得记。'}
              </span>
            </div>
          </div>
        ) : (
          <div className="card-template-body">
            <div className="card-template-section">
              <div className="card-template-heading">
                <span>学习模板</span>
                <strong>单选</strong>
              </div>
              <div className="template-radio-list" role="radiogroup" aria-label="选择制卡模板">
                {templateOptions.map((item) => {
                  const selected = templateId === item.id
                  return (
                    <button
                      type="button"
                      key={item.id}
                      className={`template-radio-option ${selected ? 'selected' : ''} ${item.locked ? 'locked' : ''}`}
                      role="radio"
                      aria-checked={selected}
                      onClick={() => {
                        if (!item.locked) onSelectTemplate(item.id)
                      }}
                      disabled={item.locked}
                    >
                      <span className="option-state" aria-hidden="true">
                        {selected ? <CheckCircle2 size={16} /> : <Circle size={16} />}
                      </span>
                      <span className="option-copy">
                        <strong>{item.label}</strong>
                        <small>{item.note}</small>
                      </span>
                      {item.id === 'ciba_tianxia_v1' ? (
                        <span className="experiment-badge">
                          <Layers3 size={12} />
                          实验
                        </span>
                      ) : null}
                    </button>
                  )
                })}
              </div>
            </div>
            <div className="card-template-section">
              <div className="card-template-heading">
                <span>背面信息量</span>
                <strong>只影响卡片背面展示</strong>
              </div>
              <div className="template-radio-list" role="radiogroup" aria-label="选择背面信息量">
                {reviewDensityOptions.map((item) => {
                  const selected = reviewDensity === item.id
                  return (
                    <button
                      type="button"
                      key={item.id}
                      className={`template-radio-option ${selected ? 'selected' : ''}`}
                      role="radio"
                      aria-checked={selected}
                      onClick={() => onSelectReviewDensity(item.id)}
                    >
                      <span className="option-state" aria-hidden="true">
                        {selected ? <CheckCircle2 size={16} /> : <Circle size={16} />}
                      </span>
                      <span className="option-copy">
                        <strong>{item.label}</strong>
                        <small>{item.note}</small>
                      </span>
                      <span className="experiment-badge">
                        <Zap size={12} />
                        {item.badge}
                      </span>
                    </button>
                  )
                })}
              </div>
            </div>
            {isCibaTemplate ? (
              <div className="card-template-section">
                <div className="card-template-heading">
                  <span>词霸卡面风格</span>
                  <strong>仅影响导出卡面</strong>
                </div>
                <div className="style-radio-list" role="radiogroup" aria-label="选择词霸卡面风格">
                  {cardStyleOptions.map((item) => {
                    const selected = cardStyleId === item.id
                    return (
                      <button
                        type="button"
                        key={item.id}
                        className={`style-radio-option ${selected ? 'selected' : ''}`}
                        role="radio"
                        aria-checked={selected}
                        onClick={() => onSelectCardStyle(item.id)}
                      >
                        <span className={`style-swatch ${item.tone}`} aria-hidden="true">
                          <Palette size={14} />
                        </span>
                        <span className="option-copy">
                          <strong>{item.label}</strong>
                          <small>{item.note}</small>
                        </span>
                        <span className="option-state" aria-hidden="true">
                          {selected ? <CheckCircle2 size={16} /> : <Circle size={16} />}
                        </span>
                      </button>
                    )
                  })}
                </div>
              </div>
            ) : (
              <p className="template-style-note">沉浸复读 V11 使用稳定卡面；视觉风格只在词霸天下实验 V1 中生效。</p>
            )}
          </div>
        )}
      </details>
    </section>
  )
}
