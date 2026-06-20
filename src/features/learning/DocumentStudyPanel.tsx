import { BookOpenCheck, Languages } from 'lucide-react'

import {
  documentAnswerLanguageLabel,
  documentAnswerLanguageMoreOptions,
  documentAnswerLanguageOptions,
  documentAnswerLanguagePrimaryOptions,
  documentAnswerLengthLabel,
  documentAnswerLengthOptions,
  documentDepthLabel,
  documentDepthOptions,
  documentFocusSummary,
  documentReadingFocusOptions,
  documentStudyModeOptions,
  learningLanguageLabel,
  learningLanguageOptions,
  normalizeLearningLanguage,
} from '../../domain/options'
import type { DocumentAnswerLanguage, DocumentFocus, GenerateRequest, LanguageFocus, Level } from '../../domain/types'

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
  const autoLevel = request.level_mode !== 'manual'
  const levelSummary = autoLevel ? '自动判断' : request.level
  const answerLanguageLabel = documentAnswerLanguageLabel(request.document_answer_language)
  const moreLanguageValue = documentAnswerLanguageMoreOptions.some((item) => item.id === request.document_answer_language)
    ? request.document_answer_language
    : ''
  const studySummary = isLanguageReading
    ? `语言精读 · ${learningLanguageLabel(request.language)} · ${levelSummary}`
    : `答案${answerLanguageLabel} · ${documentDepthLabel(request.document_depth)} · ${documentFocusSummary(
        request.document_focus,
      )}`

  return (
    <section className="panel document-study-panel">
      <div className="panel-heading">
        <BookOpenCheck size={20} />
        <div className="panel-title-stack">
          <h3>文档目标</h3>
          <span>{studySummary}</span>
        </div>
      </div>

      <div className="document-recommendation-card" aria-label="文档推荐路径">
        <span>推荐路径</span>
        <strong>{isLanguageReading ? '语言精读 · 表达/词汇/语法 · 自动判断' : '知识吸收 · 标准理解 · 中等答案'}</strong>
        <p>
          {isLanguageReading
            ? '适合英文资料精读：只抽文档里的表达、词汇和语法框架，不做听力卡。'
            : '适合书籍、论文、课程讲义：一张卡只记一个可回忆点，先问自己再看解释。'}
        </p>
      </div>

      <div className="document-study-mode-grid" aria-label="文档学习路径">
        {documentStudyModeOptions.map((item) => (
          <button
            type="button"
            key={item.id}
            className={request.document_study_mode === item.id ? 'document-study-mode selected' : 'document-study-mode'}
            aria-pressed={request.document_study_mode === item.id}
            onClick={() => {
              if (item.id === 'language_reading') {
                onPatchRequest({
                  document_study_mode: item.id,
                  language_focus: selectedReadingFocus.length ? selectedReadingFocus : ['phrases'],
                })
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
              onChange={(event) => onPatchRequest({ language: normalizeLearningLanguage(event.target.value) })}
            >
              {learningLanguageOptions.map((item) => (
                <option key={item.code} value={item.code}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <div className="settings-subheading refined-level-heading">
            <strong>学习水平</strong>
            <span>{autoLevel ? '自动判断每张卡难度' : levels.find((level) => level.id === request.level)?.note ?? '控制解释深度'}</span>
          </div>
          <div className="level-strip" aria-label="文档精读水平">
            <button
              type="button"
              className={autoLevel ? 'selected' : ''}
              aria-label="自动判断文档精读水平"
              title="自动判断每张精读卡难度"
              onClick={() => onPatchRequest({ level_mode: 'auto' })}
            >
              <strong>Auto</strong>
            </button>
            {levels.map((level) => (
              <button
                type="button"
                key={level.id}
                className={!autoLevel && request.level === level.id ? 'selected' : ''}
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
        <div className="document-knowledge-settings" aria-label="文档知识卡设置">
          <details className="compact-details document-focus-panel" open>
            <summary>
              <span>知识卡重点</span>
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

          <details className="compact-details document-language-settings">
            <summary>
              <span>答案语言</span>
              <strong>{answerLanguageLabel}</strong>
            </summary>
            <div className="document-answer-language-body">
              <div className="document-language-status">
                <span>
                  <strong>文档语言</strong>
                  <small>自动识别原文；双语会保留原文语言线索</small>
                </span>
                <em>自动</em>
              </div>
              <div className="document-language-copy">
                <strong>答案/解析语言</strong>
                <span>控制卡片答案、解释和老师提醒的语言。默认中文；需要其他语言时在这里改。</span>
              </div>
              <div className="document-answer-language-quick" aria-label="常用答案语言">
                {documentAnswerLanguagePrimaryOptions.map((item) => (
                  <button
                    type="button"
                    key={item.id}
                    className={request.document_answer_language === item.id ? 'selected' : ''}
                    aria-pressed={request.document_answer_language === item.id}
                    onClick={() => onPatchRequest({ document_answer_language: item.id })}
                    title={item.note}
                  >
                    <strong>{item.label}</strong>
                    <span>{item.note}</span>
                  </button>
                ))}
              </div>
              <label className="document-language-select-row">
                <span>
                  <strong>更多语言</strong>
                  <small>适合日语、韩语、西语、法语等资料或复习习惯</small>
                </span>
                <select
                  aria-label="更多答案语言"
                  value={moreLanguageValue}
                  onChange={(event) => {
                    const nextLanguage = event.target.value as DocumentAnswerLanguage
                    if (documentAnswerLanguageOptions.some((item) => item.id === nextLanguage)) {
                      onPatchRequest({ document_answer_language: nextLanguage })
                    }
                  }}
                >
                  <option value="">选择语言...</option>
                  {documentAnswerLanguageMoreOptions.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </details>

          <div className="document-option-block">
            <div className="settings-subheading">
              <strong>理解深度</strong>
              <span>{documentDepthLabel(request.document_depth)}</span>
            </div>
            <div className="document-mini-choice-grid" aria-label="文档理解深度">
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
