import { FileText } from 'lucide-react'

import type { CardKind, SourceMode, TemplateId } from '../../domain/types'

type CardOption = {
  id: CardKind
  label: string
  note: string
}

type TemplateOption = {
  id: TemplateId
  label: string
  note: string
  locked?: boolean
}

type CardTemplatePanelProps = {
  activeTemplateLabel: string
  cardOptions: CardOption[]
  cardTypes: CardKind[]
  sourceMode: SourceMode
  templateId: TemplateId
  templateOptions: TemplateOption[]
  onSelectTemplate: (templateId: TemplateId) => void
  onToggleCardType: (type: CardKind) => void
}

export function CardTemplatePanel({
  activeTemplateLabel,
  cardOptions,
  cardTypes,
  sourceMode,
  templateId,
  templateOptions,
  onSelectTemplate,
  onToggleCardType,
}: CardTemplatePanelProps) {
  return (
    <section className="panel generation-panel">
      <details className="compact-details preference-details">
        <summary>
          <span>卡片和模板</span>
          <strong>{sourceMode === 'document' ? '知识点卡' : `${cardTypes.length} 类 · ${activeTemplateLabel}`}</strong>
        </summary>
        {sourceMode === 'document' ? (
          <div className="doc-card-mode">
            <FileText size={18} />
            <div>
              <strong>知识点卡</strong>
              <span>正面是问题或概念提示，反面是结构化答案、解释、例子和为什么值得记。</span>
            </div>
          </div>
        ) : (
          <div className="choice-row">
            {cardOptions.map((item) => (
              <button
                type="button"
                key={item.id}
                className={`choice ${cardTypes.includes(item.id) ? 'selected' : ''}`}
                onClick={() => onToggleCardType(item.id)}
              >
                <strong>{item.label}</strong>
                <span>{item.note}</span>
              </button>
            ))}
          </div>
        )}
        <div className="choice-row">
          {templateOptions.map((item) => (
            <button
              type="button"
              key={item.id}
              className={`choice template-choice ${templateId === item.id ? 'selected' : ''} ${
                item.locked ? 'locked' : ''
              }`}
              onClick={() => {
                if (!item.locked) onSelectTemplate(item.id)
              }}
              disabled={item.locked}
            >
              <strong>{item.label}</strong>
              <span>{item.note}</span>
            </button>
          ))}
        </div>
      </details>
    </section>
  )
}
