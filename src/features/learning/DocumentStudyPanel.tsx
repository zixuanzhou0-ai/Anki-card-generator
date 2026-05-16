import { BookOpenCheck, Languages } from 'lucide-react'

import {
  documentAnswerLanguageLabel,
  documentAnswerLanguageOptions,
  documentAnswerLengthLabel,
  documentAnswerLengthOptions,
  documentDepthLabel,
  documentDepthOptions,
  documentFocusSummary,
  documentReadingFocusOptions,
  documentStudyModeOptions,
} from '../../domain/options'
import type { DocumentFocus, GenerateRequest, LanguageFocus, Level } from '../../domain/types'

type LevelOption = {
  id: Level
  label: string
  note: string
}

type LanguageFocusOption = {
  id: LanguageFocus
  label: string
  note: string
  defaultOn: boolean
}

type DocumentFocusOption = {
  id: DocumentFocus
  label: string
  note: string
  defaultOn: boolean
}

type DocumentStudyPanelProps = {
  documentFocusOptions: DocumentFocusOption[]
  languageFocusOptions: LanguageFocusOption[]
  levels: LevelOption[]
  request: GenerateRequest
  onPatchRequest: (patch: Partial<GenerateRequest>) => void
  onSelectCurrentLevel: (level: Level) => void
  onToggleDocumentFocus: (focus: DocumentFocus) => void
  onToggleLanguageFocus: (focus: LanguageFocus) => void
}

export function DocumentStudyPanel({
  documentFocusOptions,
  languageFocusOptions,
  levels,
  request,
  onPatchRequest,
  onSelectCurrentLevel,
  onToggleDocumentFocus,
  onToggleLanguageFocus,
}: DocumentStudyPanelProps) {
  const isLanguageReading = request.document_study_mode === 'language_reading'
  const allowedReadingFocus = languageFocusOptions.filter((item) => documentReadingFocusOptions.includes(item.id))
  const selectedReadingFocus = request.language_focus.filter((item) => documentReadingFocusOptions.includes(item))
  const studySummary = isLanguageReading
    ? `语言精读 · ${request.language} · ${request.level}`
    : `${documentAnswerLanguageLabel(request.document_answer_language)} · ${documentDepthLabel(
        request.document_depth,
      )} · ${documentFocusSummary(request.document_focus)}`

  return (
    <section className="panel document-study-panel">
      <div className="panel-heading">
        <BookOpenCheck size={20} />
        <div className="panel-title-stack">
          <h3>文档目标</h3>
          <span>{studySummary}</span>
        </div>
      </div>

      <div className="document-study-mode-grid" aria-label="文档学习路径">
        {documentStudyModeOptions.map((item) => (
          <button
            type="button"
            key={item.id}
            className={request.document_study_mode === item.id ? 'document-study-mode selected' : 'document-study-mode'}
            aria-pressed={request.document_study_mode === item.id}
            onClick={() => {
              if (item.id === 'language_reading' && selectedReadingFocus.length === 0) {
                onPatchRequest({ document_study_mode: item.id, language_focus: ['phrases'] })
                return
              }
              onPatchRequest({ document_study_mode: item.id })
            }}
          >
            <strong>{item.label}</strong>
            <span>{item.note}</span>
          </button>
        ))}
      </div>

      {isLanguageReading ? (
        <div className="document-reading-settings" aria-label="语言精读设置">
          <div className="document-mode-note">
            <Languages size={16} />
            <span>文档精读不生成听力卡；这里只训练文档里的表达、词汇和语法框架。</span>
          </div>
          <label className="learning-setting-row compact-row">
            <span>
              <strong>学习语言</strong>
              <small>用于解释、例句和老师提醒</small>
            </span>
            <select
              aria-label="文档精读语言"
              value={request.language}
              onChange={(event) => onPatchRequest({ language: event.target.value })}
            >
              <option>English</option>
              <option>Français</option>
              <option>Español</option>
              <option>日本語</option>
            </select>
          </label>
          <div className="settings-subheading refined-level-heading">
            <strong>当前水平</strong>
            <span>{levels.find((level) => level.id === request.level)?.note ?? '控制解释深度'}</span>
          </div>
          <div className="level-strip" aria-label="文档精读水平">
            {levels.map((level) => (
              <button
                type="button"
                key={level.id}
                className={request.level === level.id ? 'selected' : ''}
                aria-label={`${level.id}${level.note}`}
                title={`${level.label} · ${level.note}`}
                onClick={() => onSelectCurrentLevel(level.id)}
              >
                <strong>{level.id}</strong>
              </button>
            ))}
          </div>
          <details className="compact-details language-focus-panel" open>
            <summary>
              <span>精读重点</span>
              <strong>
                {selectedReadingFocus.length
                  ? selectedReadingFocus
                      .map((focus) => allowedReadingFocus.find((item) => item.id === focus)?.label ?? focus)
                      .join(' / ')
                  : '词伙表达'}
              </strong>
            </summary>
            <div className="focus-choice-grid" aria-label="文档语言精读重点">
              {allowedReadingFocus.map((item) => {
                const selected = request.language_focus.includes(item.id)
                return (
                  <button
                    type="button"
                    key={item.id}
                    className={selected ? 'focus-choice selected' : 'focus-choice'}
                    aria-pressed={selected}
                    onClick={() => onToggleLanguageFocus(item.id)}
                  >
                    <strong>{item.label}</strong>
                    <span>{item.note}</span>
                  </button>
                )
              })}
            </div>
          </details>
        </div>
      ) : (
        <div className="document-knowledge-settings" aria-label="文档吸收设置">
          <details className="compact-details document-focus-panel" open>
            <summary>
              <span>文档吸收设置</span>
              <strong>{documentFocusSummary(request.document_focus)}</strong>
            </summary>
            <div className="document-focus-grid">
              {documentFocusOptions.map((item) => {
                const selected = request.document_focus.includes(item.id)
                return (
                  <button
                    type="button"
                    key={item.id}
                    className={selected ? 'document-focus-choice selected' : 'document-focus-choice'}
                    aria-pressed={selected}
                    onClick={() => onToggleDocumentFocus(item.id)}
                  >
                    <strong>{item.label}</strong>
                    <span>{item.note}</span>
                  </button>
                )
              })}
            </div>
          </details>

          <div className="document-option-block">
            <div className="settings-subheading">
              <strong>讲解语言</strong>
              <span>{documentAnswerLanguageLabel(request.document_answer_language)}</span>
            </div>
            <div className="segmented document-segmented" aria-label="文档讲解语言">
              {documentAnswerLanguageOptions.map((item) => (
                <button
                  type="button"
                  key={item.id}
                  className={request.document_answer_language === item.id ? 'selected' : ''}
                  onClick={() => onPatchRequest({ document_answer_language: item.id })}
                  title={item.note}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>

          <div className="document-option-block">
            <div className="settings-subheading">
              <strong>卡片深度</strong>
              <span>{documentDepthLabel(request.document_depth)}</span>
            </div>
            <div className="document-mini-choice-grid" aria-label="文档卡片深度">
              {documentDepthOptions.map((item) => (
                <button
                  type="button"
                  key={item.id}
                  className={request.document_depth === item.id ? 'selected' : ''}
                  onClick={() => onPatchRequest({ document_depth: item.id })}
                >
                  <strong>{item.label}</strong>
                  <span>{item.note}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="document-option-block">
            <div className="settings-subheading">
              <strong>答案长度</strong>
              <span>{documentAnswerLengthLabel(request.document_answer_length)}</span>
            </div>
            <div className="segmented document-segmented" aria-label="文档答案长度">
              {documentAnswerLengthOptions.map((item) => (
                <button
                  type="button"
                  key={item.id}
                  className={request.document_answer_length === item.id ? 'selected' : ''}
                  onClick={() => onPatchRequest({ document_answer_length: item.id })}
                  title={item.note}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
