import { Languages } from 'lucide-react'

import type { GenerateRequest, Level } from '../../domain/types'
import { learningLanguageOptions, normalizeLearningLanguage } from '../../domain/options'

type LevelOption = {
  id: Level
  label: string
  note: string
}

type LearningSettingsPanelProps = {
  levels: LevelOption[]
  previewRate: number
  request: GenerateRequest
  onPreviewRateChange: (rate: number) => void
  onPatchRequest: (patch: Partial<GenerateRequest>) => void
  onSelectCurrentLevel: (level: Level) => void
}

export function LearningSettingsPanel({
  levels,
  previewRate,
  request,
  onPreviewRateChange,
  onPatchRequest,
  onSelectCurrentLevel,
}: LearningSettingsPanelProps) {
  const currentLevel = levels.find((level) => level.id === request.level) ?? levels[0]
  const currentLanguage =
    learningLanguageOptions.find((item) => item.code === normalizeLearningLanguage(request.language)) ??
    learningLanguageOptions[0]
  const autoLevel = request.level_mode !== 'manual'
  const levelSummary = autoLevel ? '自动判断' : request.level

  return (
    <div className="panel settings-panel">
      <div className="panel-heading">
        <Languages size={20} />
        <div className="panel-title-stack">
          <h3>学习设置</h3>
          <span>{`${currentLanguage.label} · ${levelSummary}`}</span>
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
            value={normalizeLearningLanguage(request.language)}
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
                ? '默认自动判断每张卡的难度'
                : currentLevel
                  ? `${currentLevel.label} · 作为解释深度偏好`
                  : '控制解释深度和学习难度标注'}
            </small>
          </span>
          <div className="level-strip" aria-label="当前语言水平">
            <button
              type="button"
              className={autoLevel ? 'selected' : ''}
              aria-pressed={autoLevel}
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
                aria-pressed={!autoLevel && request.level === level.id}
                aria-label={`${level.id}${level.note}`}
                title={`${level.label} · ${level.note}`}
                onClick={() => onSelectCurrentLevel(level.id)}
              >
                <strong>{level.id}</strong>
              </button>
            ))}
          </div>
        </div>
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
    </div>
  )
}
