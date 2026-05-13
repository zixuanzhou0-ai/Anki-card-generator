import { Languages } from 'lucide-react'

import type { ContentToggles, GenerateRequest, Level } from '../../domain/types'
import { normalizeCollectionLevels } from '../../domain/options'

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

type CollectionPreset = 'current' | 'below' | 'around'

type LearningSettingsPanelProps = {
  contentOptions: ContentOption[]
  levels: LevelOption[]
  request: GenerateRequest
  onApplyCollectionPreset: (preset: CollectionPreset) => void
  onPatchRequest: (patch: Partial<GenerateRequest>) => void
  onSelectCurrentLevel: (level: Level) => void
  onToggleCollectionLevel: (level: Level) => void
  onToggleContent: (key: keyof ContentToggles) => void
}

export function LearningSettingsPanel({
  contentOptions,
  levels,
  request,
  onApplyCollectionPreset,
  onPatchRequest,
  onSelectCurrentLevel,
  onToggleCollectionLevel,
  onToggleContent,
}: LearningSettingsPanelProps) {
  const collectionLevels = normalizeCollectionLevels(request.collection_levels, request.level)
  const selectedContentCount = contentOptions.filter((item) => request.content_toggles[item.key]).length
  const currentLevel = levels.find((level) => level.id === request.level) ?? levels[0]
  const segmentBudgetLabel = request.max_segments <= 0 ? '自动片段' : `${request.max_segments} 段`

  return (
    <div className="panel settings-panel">
      <div className="panel-heading">
        <Languages size={20} />
        <div className="panel-title-stack">
          <h3>学习设置</h3>
          <span>{`${request.language} · ${request.level} · ${segmentBudgetLabel}`}</span>
        </div>
      </div>
      <div className="learning-core-card">
        <label className="learning-setting-row">
          <span>
            <strong>学习语言</strong>
            <small>生成解释、例句和老师评语时使用</small>
          </span>
          <select
            aria-label="学习语言"
            value={request.language}
            onChange={(event) => onPatchRequest({ language: event.target.value })}
          >
            <option>English</option>
            <option>Français</option>
            <option>Español</option>
            <option>日本語</option>
          </select>
        </label>
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
      </div>
      <div className="settings-subheading level-subheading refined-level-heading">
        <strong>当前水平</strong>
        <span>{currentLevel ? `${currentLevel.label} · ${currentLevel.note}` : '控制解释深度和质量门槛'}</span>
      </div>
      <div className="level-strip" aria-label="当前学习水平">
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
      <details className="compact-details inspector-fold level-range-panel" aria-label="收录难度范围">
        <summary>
          <span>收录难度范围</span>
          <strong>{collectionLevels.join(' / ')}</strong>
        </summary>
        <div className="level-range-body">
          <div className="range-actions" aria-label="收录范围快捷设置">
            <button type="button" onClick={() => onApplyCollectionPreset('current')}>
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
      </details>
      <details className="compact-details content-preferences">
        <summary>
          <span>内容偏好</span>
          <strong>{selectedContentCount} 项已选</strong>
        </summary>
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
      </details>
    </div>
  )
}
