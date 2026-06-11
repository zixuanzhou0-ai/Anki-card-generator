import { ChevronDown, Languages, SlidersHorizontal } from 'lucide-react'

import type { ContentToggles, GenerateRequest, LanguageFocus, Level, SelectionStrategy } from '../../domain/types'
import {
  languageFocusSummary,
  learningLanguageOptions,
  normalizeCollectionLevels,
  normalizeLearningLanguage,
  studyDepthOptions,
} from '../../domain/options'

type LevelOption = {
  id: Level
  label: string
  note: string
}

type ContentOption = {
  key: keyof ContentToggles
  label: string
  defaultOn: boolean
}

type LanguageFocusOption = {
  id: LanguageFocus
  label: string
  note: string
  defaultOn: boolean
}

type SelectionStrategyOption = {
  id: SelectionStrategy
  label: string
  note: string
  badge: string
}

type CollectionPreset = 'current' | 'below' | 'around'

type LearningSettingsPanelProps = {
  contentOptions: ContentOption[]
  languageFocusOptions: LanguageFocusOption[]
  levels: LevelOption[]
  previewRate: number
  request: GenerateRequest
  selectionStrategyOptions: SelectionStrategyOption[]
  onPreviewRateChange: (rate: number) => void
  onApplyCollectionPreset: (preset: CollectionPreset) => void
  onPatchRequest: (patch: Partial<GenerateRequest>) => void
  onSelectCurrentLevel: (level: Level) => void
  onToggleCollectionLevel: (level: Level) => void
  onToggleContent: (key: keyof ContentToggles) => void
  onToggleLanguageFocus: (focus: LanguageFocus) => void
}

export function LearningSettingsPanel({
  contentOptions,
  languageFocusOptions,
  levels,
  previewRate,
  request,
  selectionStrategyOptions,
  onPreviewRateChange,
  onApplyCollectionPreset,
  onPatchRequest,
  onSelectCurrentLevel,
  onToggleCollectionLevel,
  onToggleContent,
  onToggleLanguageFocus,
}: LearningSettingsPanelProps) {
  const collectionLevels = normalizeCollectionLevels(request.collection_levels, request.level)
  const selectedContentCount = contentOptions.filter((item) => request.content_toggles[item.key]).length
  const focusSummary = languageFocusSummary(request.language_focus)
  const currentLevel = levels.find((level) => level.id === request.level) ?? levels[0]
  const currentStrategy =
    selectionStrategyOptions.find((option) => option.id === request.selection_strategy) ?? selectionStrategyOptions[0]
  const currentLanguage =
    learningLanguageOptions.find((item) => item.code === normalizeLearningLanguage(request.language)) ??
    learningLanguageOptions[0]
  const segmentBudgetLabel = request.max_segments <= 0 ? '自动片段' : `${request.max_segments} 段`
  const autoLevel = request.level_mode !== 'manual'
  const levelSummary = autoLevel ? '自动判断' : request.level

  return (
    <div className="panel settings-panel">
      <div className="panel-heading">
        <Languages size={20} />
        <div className="panel-title-stack">
          <h3>学习设置</h3>
          <span>{`${currentLanguage.label} · ${levelSummary} · ${segmentBudgetLabel}`}</span>
        </div>
      </div>
      <div className="learning-core-card">
        <label className="learning-setting-row language-picker-row">
          <span>
            <strong>学习语言</strong>
            <small>决定发音体系、解释口径和 TTS 语言</small>
          </span>
          <select
            aria-label="学习语言"
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
        <div className="learning-setting-row level-picker-row">
          <span>
            <strong>学习水平</strong>
            <small>
              {autoLevel
                ? '自动判断每张卡的难度；手动水平只作为解释深度和筛选倾向'
                : currentLevel
                  ? `${currentLevel.label} · 作为软偏好，不硬过滤学习点`
                  : '控制解释深度和质量判断'}
            </small>
          </span>
          <div className="level-strip" aria-label="当前语言水平">
            <button
              type="button"
              className={autoLevel ? 'selected' : ''}
              aria-label="自动判断学习水平"
              title="自动判断每张卡的难度"
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
        </div>
        <div className="learning-setting-row strategy-picker-row">
          <span>
            <strong>智能筛选</strong>
            <small>系统逐句发现学习点，只输出可用卡片；生成后默认全选</small>
          </span>
          <div className="selection-strategy-grid single-strategy" aria-label="智能筛选">
            <button type="button" className="selected" aria-pressed="true" title={currentStrategy?.note}>
              <span>
                <strong>{currentStrategy?.label ?? '智能筛选'}</strong>
                <em>{currentStrategy?.badge ?? '默认'}</em>
              </span>
              <small>{currentStrategy?.note ?? '每句最多 4 个不同学习点，重复和低价值内容进入更多学习点说明。'}</small>
            </button>
          </div>
        </div>
        <label className="learning-setting-row">
          <span>
            <strong>片段预算</strong>
            <small>
              {request.max_segments <= 0
                ? '按视频长度、字幕密度和句子完整性自动估算'
                : '手动限制最终进入制卡的片段数量'}
            </small>
          </span>
          <div className="segment-budget-input">
            <input
              aria-label="最大片段数"
              type="number"
              min={3}
              max={120}
              value={request.max_segments > 0 ? request.max_segments : ''}
              placeholder="自动"
              disabled={request.max_segments <= 0}
              onChange={(event) => onPatchRequest({ max_segments: Number(event.target.value) })}
            />
            <button
              type="button"
              className={request.max_segments <= 0 ? 'selected' : ''}
              onClick={() => onPatchRequest({ max_segments: request.max_segments <= 0 ? 35 : 0 })}
            >
              自动
            </button>
          </div>
        </label>
        <div className="learning-setting-row preview-rate-row">
          <span>
            <strong>预览播放速度</strong>
            <small>只影响应用内试听，不改变导出的 Anki 音频</small>
          </span>
          <div className="preview-rate global-preview-rate" aria-label="预览播放速度">
            {[0.75, 1, 1.25].map((rate) => (
              <button
                type="button"
                key={rate}
                className={previewRate === rate ? 'selected' : ''}
                aria-pressed={previewRate === rate}
                onClick={() => onPreviewRateChange(rate)}
              >
                {rate}x
              </button>
            ))}
          </div>
        </div>
      </div>
      <details className="compact-details advanced-learning-options">
        <summary className="advanced-learning-summary">
          <span className="advanced-learning-summary-title">
            <SlidersHorizontal size={16} aria-hidden="true" />
            <span>
              <strong>高级学习设置</strong>
              <small>素材解析、难度范围、内容偏好</small>
            </span>
          </span>
          <span className="advanced-learning-summary-meta">
            <strong>{focusSummary}</strong>
            <small>{collectionLevels.join(' / ')}</small>
          </span>
          <span className="advanced-learning-summary-action" aria-hidden="true">
            <span className="when-closed">展开</span>
            <span className="when-open">收起</span>
            <ChevronDown size={16} />
          </span>
        </summary>
        <div className="advanced-learning-body">
          <div className="learning-setting-row compact-learning-row">
            <span>
              <strong>素材解析方式</strong>
              <small>影响生成前 AI 如何理解素材，不直接决定卡片背面信息量</small>
            </span>
            <div className="study-depth-toggle" aria-label="素材解析方式">
              {studyDepthOptions.map((item) => (
                <button
                  type="button"
                  key={item.id}
                  className={request.study_depth === item.id ? 'selected' : ''}
                  aria-pressed={request.study_depth === item.id}
                  title={item.note}
                  onClick={() => onPatchRequest({ study_depth: item.id })}
                >
                  <strong>{item.label}</strong>
                  <small>{item.id === 'deep' ? '推荐' : '提速'}</small>
                </button>
              ))}
            </div>
          </div>
          <label className="learning-setting-row compact-learning-row cache-learning-row">
            <span>
              <strong>复用上次 AI 精筛结果</strong>
              <small>
                默认关闭。打开后，同一字幕、语言和模型会优先用缓存，速度更快，但不是重新调用 AI。
              </small>
            </span>
            <span className="toggle inline-toggle">
              <input
                aria-label="复用上次 AI 精筛结果"
                type="checkbox"
                checked={request.reuse_ai_review_cache}
                onChange={(event) => onPatchRequest({ reuse_ai_review_cache: event.target.checked })}
              />
              <span>{request.reuse_ai_review_cache ? '允许复用缓存' : '每次重新精筛'}</span>
            </span>
          </label>
          {request.source_mode !== 'document' ? (
            <div className="advanced-subsection">
              <div className="settings-subheading">
                <strong>学习重点</strong>
                <span>{focusSummary}</span>
              </div>
              <div className="focus-choice-grid" aria-label="语言学习重点">
                {languageFocusOptions.map((item) => {
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
            </div>
          ) : (
            <div className="document-focus-note">
              <strong>文档资料</strong>
              <span>文档会单独按知识点、术语和章节结构制卡，不混入语言素材的词伙 / 听力选择。</span>
            </div>
          )}
          <div className="advanced-subsection level-range-panel" aria-label="难度关注范围">
            <div className="settings-subheading">
              <strong>难度关注范围</strong>
              <span>
                {autoLevel
                  ? '自动模式下仅作提示上下文'
                  : `${collectionLevels.join(' / ')} · 高级调参，不再作为主要硬过滤`}
              </span>
            </div>
            <div className="level-range-body">
              <div className="range-actions" aria-label="难度关注范围快捷设置">
                <button
                  type="button"
                  onClick={() => onApplyCollectionPreset('current')}
                >
                  只当前
                </button>
                <button type="button" onClick={() => onApplyCollectionPreset('below')}>
                  当前及以下
                </button>
                <button type="button" onClick={() => onApplyCollectionPreset('around')}>
                  上下一级
                </button>
              </div>
              <div className="level-range-grid">
                {levels.map((level) => {
                  const selected = collectionLevels.includes(level.id)
                  return (
                    <button
                      type="button"
                      key={level.id}
                      className={selected ? 'selected' : ''}
                      onClick={() => onToggleCollectionLevel(level.id)}
                      aria-pressed={selected}
                    >
                      <strong>{level.id}</strong>
                      <span>{level.note}</span>
                    </button>
                  )
                })}
              </div>
            </div>
          </div>
          <div className="advanced-subsection content-preferences">
            <div className="settings-subheading">
              <strong>内容偏好</strong>
              <span>{selectedContentCount} 项已选</span>
            </div>
            <div className="toggle-grid">
              {contentOptions.map((item) => (
                <label className="toggle" key={item.key}>
                  <input
                    type="checkbox"
                    checked={request.content_toggles[item.key]}
                    onChange={() => onToggleContent(item.key)}
                  />
                  <span>{item.label}</span>
                </label>
              ))}
            </div>
          </div>
        </div>
      </details>
    </div>
  )
}
