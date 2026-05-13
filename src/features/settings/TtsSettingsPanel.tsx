import { CircleAlert, PlugZap } from 'lucide-react'

import type { SecretPrefs, TtsConfig, TtsPreset, TtsProvider } from '../../domain/types'
import { ConnectionTestCard } from './ConnectionTestCard'

type ModelOption = {
  label: string
  value: string
}

type TtsSettingsPanelProps = {
  advancedTtsPresets: TtsPreset[]
  appBusy: boolean
  featuredTtsPresets: TtsPreset[]
  mimoOpenAiBaseUrl: string
  mimoTokenPlanSgpBaseUrl: string
  mimoTtsModels: ModelOption[]
  mimoTtsVoices: string[]
  secretPrefs: SecretPrefs
  showAdvancedTts: boolean
  tts: TtsConfig
  ttsTestMessage: string
  ttsTestMeta: string
  ttsTestOk?: boolean
  ttsTestTitle: string
  ttsTestTone: string
  ttsTesting: boolean
  onApplyTtsPreset: (preset: TtsPreset) => void
  onPatchTts: (patch: Partial<TtsConfig>) => void
  onSetShowAdvancedTts: (value: boolean | ((current: boolean) => boolean)) => void
  onTestTts: () => void
  onToggleRememberTtsKey: () => void
}

export function TtsSettingsPanel({
  advancedTtsPresets,
  appBusy,
  featuredTtsPresets,
  mimoOpenAiBaseUrl,
  mimoTokenPlanSgpBaseUrl,
  mimoTtsModels,
  mimoTtsVoices,
  secretPrefs,
  showAdvancedTts,
  tts,
  ttsTestMessage,
  ttsTestMeta,
  ttsTestOk,
  ttsTestTitle,
  ttsTestTone,
  ttsTesting,
  onApplyTtsPreset,
  onPatchTts,
  onSetShowAdvancedTts,
  onTestTts,
  onToggleRememberTtsKey,
}: TtsSettingsPanelProps) {
  const isPresetSelected = (preset: TtsPreset) =>
    tts.provider === preset.provider &&
    tts.base_url === preset.base_url &&
    tts.model === preset.model &&
    tts.voice === preset.voice &&
    (preset.provider !== 'disabled' ? tts.enabled : !tts.enabled)

  const handleEnabledChange = () => {
    onPatchTts({
      enabled: !tts.enabled,
      provider: !tts.enabled ? (tts.provider === 'disabled' ? 'mimo' : tts.provider) : 'disabled',
      base_url: !tts.enabled && tts.provider === 'disabled' ? mimoTokenPlanSgpBaseUrl : tts.base_url,
      model: !tts.enabled && !tts.model ? 'mimo-v2.5-tts' : tts.model,
      voice: !tts.enabled && !tts.voice ? 'Mia' : tts.voice,
    })
  }

  const handleProviderChange = (provider: TtsProvider) => {
    onPatchTts({
      provider,
      enabled: provider !== 'disabled',
      base_url:
        provider === 'mimo'
          ? tts.base_url || mimoTokenPlanSgpBaseUrl
          : provider === 'grok'
            ? 'https://api.x.ai/v1'
            : provider === 'openai-compatible'
              ? tts.base_url || 'https://api.openai.com/v1'
              : tts.base_url,
      model: provider === 'mimo' && !tts.model ? 'mimo-v2.5-tts' : tts.model,
      voice: provider === 'mimo' ? tts.voice || 'Mia' : provider === 'grok' ? tts.voice || 'eve' : tts.voice,
    })
  }

  const renderPreset = (preset: TtsPreset) => (
    <button
      type="button"
      key={preset.id}
      className={`preset-card ${isPresetSelected(preset) ? 'selected' : ''}`}
      onClick={() => onApplyTtsPreset(preset)}
    >
      <strong>{preset.label}</strong>
      <span>{preset.note}</span>
      <small>{preset.key_hint}</small>
    </button>
  )

  return (
    <section className="settings-section settings-section-single">
      <div className="panel-heading">
        <PlugZap size={20} />
        <h3>语音 TTS</h3>
      </div>
      <details className="settings-disclosure">
        <summary>
          <span>TTS 说明与费用</span>
          <strong>语音模型 / 授权 / 费用</strong>
        </summary>
        <div className="settings-callout tts-callout">
          <CircleAlert size={18} />
          <div>
            <strong>TTS 是独立配置，MIMO 语音模型也在这里选。</strong>
            <p>
              MIMO V2.5 TTS、VoiceDesign、VoiceClone 和 V2 TTS 都可以作为独立语音模型配置。
              如果上方文本模型已经配置了 MIMO Key，TTS 会默认复用它；只有想单独换语音服务时才需要另填 TTS Key。
            </p>
          </div>
        </div>
        <div className="settings-callout risk-callout">
          <CircleAlert size={18} />
          <div>
            <strong>TTS 会额外调用语音服务，并可能产生费用。</strong>
            <p>导出牌组如果包含视频片段、字幕或合成音频，默认仅供个人学习；分享前请确认素材和声音服务授权。</p>
          </div>
        </div>
      </details>

      <ConnectionTestCard
        buttonLabel="测试 TTS"
        disabled={ttsTesting || appBusy}
        message={ttsTestMessage}
        meta={ttsTestMeta}
        ok={ttsTestOk}
        statusLabel="TTS 状态"
        testing={ttsTesting}
        testingLabel="测试中..."
        title={ttsTestTitle}
        tone={ttsTestTone}
        onTest={onTestTts}
      />

      <div className="settings-subheading">
        <strong>常用语音</strong>
        <span>视频卡优先用原声；只在需要额外朗读时开启 TTS。</span>
      </div>
      <div className="preset-grid compact-presets tts-preset-grid" aria-label="TTS 推荐预设">
        {featuredTtsPresets.map(renderPreset)}
      </div>
      <button className="advanced-toggle" type="button" onClick={() => onSetShowAdvancedTts((value) => !value)}>
        {showAdvancedTts ? '收起高级 TTS' : '高级 TTS 模型和参数'}
      </button>
      {showAdvancedTts ? (
        <div className="preset-grid compact-presets secondary-presets" aria-label="更多 TTS 预设">
          {advancedTtsPresets.map(renderPreset)}
        </div>
      ) : null}

      <div className="tts-enable-row">
        <label className="toggle">
          <input type="checkbox" checked={tts.enabled} onChange={handleEnabledChange} />
          <span>导出时生成整句和词伙 TTS</span>
        </label>
        <small>开启后会额外生成整句朗读，并给顶部重点词伙生成小喇叭音频。</small>
      </div>

      {tts.enabled ? (
        <div className="api-grid tts-api-grid">
          <label className="field">
            <span>语音服务</span>
            <select value={tts.provider} onChange={(event) => handleProviderChange(event.target.value as TtsProvider)}>
              <option value="disabled">关闭 TTS</option>
              <option value="mimo">MIMO / 小米 TTS</option>
              <option value="grok">Grok / xAI TTS</option>
              <option value="gemini">Gemini TTS</option>
              <option value="openai-compatible">OpenAI-compatible Speech</option>
            </select>
            <small>这里选择语音服务商，不影响上面的文本模型 Provider。</small>
          </label>
          <label className="field">
            <span>语音 Base URL</span>
            <input
              value={tts.base_url}
              onChange={(event) => onPatchTts({ base_url: event.target.value })}
              placeholder={tts.provider === 'mimo' ? mimoOpenAiBaseUrl : 'https://api.x.ai/v1'}
            />
            <small>
              {tts.provider === 'mimo'
                ? `MIMO 默认 ${mimoOpenAiBaseUrl}；你的 tp-... 套餐 Key 优先用 ${mimoTokenPlanSgpBaseUrl}。`
                : 'Grok 默认 https://api.x.ai/v1；Gemini 可留空。'}
            </small>
          </label>
          <label className="field">
            <span>语音 API Key</span>
            <input
              type="password"
              value={tts.api_key}
              onChange={(event) => onPatchTts({ api_key: event.target.value })}
              placeholder={tts.provider === 'mimo' ? 'sk-... / tp-...' : 'xai-... / AIza...'}
            />
            <small>MIMO TTS 可留空并复用上方 MIMO Key；填写后优先使用这里的 Key，且不会写入本地缓存。</small>
          </label>
          <label className="toggle secret-toggle">
            <input type="checkbox" checked={secretPrefs.rememberTtsKey} onChange={onToggleRememberTtsKey} />
            <span>记住本机 TTS API Key（Windows Credential Manager）</span>
          </label>
          <label className="field">
            <span>语音模型</span>
            <input
              value={tts.model}
              onChange={(event) => onPatchTts({ model: event.target.value })}
              placeholder={
                tts.provider === 'mimo'
                  ? 'mimo-v2.5-tts'
                  : tts.provider === 'grok'
                    ? '留空即可，Grok TTS 不需要模型名'
                    : tts.provider === 'gemini'
                      ? 'gemini-2.5-flash-preview-tts'
                      : 'gpt-4o-mini-tts'
              }
              list="mimo-tts-models"
            />
            <datalist id="mimo-tts-models">
              {mimoTtsModels.map((model) => (
                <option key={model.value} value={model.value}>
                  {model.label}
                </option>
              ))}
            </datalist>
            <small>
              {tts.provider === 'mimo'
                ? '官方要求模型 ID 小写：mimo-v2.5-tts、voicedesign、voiceclone、mimo-v2-tts。'
                : 'Grok TTS 当前不需要模型名，可留空；Gemini / Speech API 需要模型名。'}
            </small>
          </label>
          <label className="field">
            <span>声音 / voice_id</span>
            <input
              value={tts.voice}
              onChange={(event) => onPatchTts({ voice: event.target.value })}
              placeholder={
                tts.provider === 'mimo'
                  ? 'Mia / Chloe / Milo / Dean / mimo_default'
                  : tts.provider === 'grok'
                    ? 'eve / ara / leo / rex / sal'
                    : 'Kore / alloy'
              }
              list={tts.provider === 'mimo' ? 'mimo-tts-voices' : undefined}
            />
            <datalist id="mimo-tts-voices">
              {mimoTtsVoices.map((voice) => (
                <option key={voice} value={voice} />
              ))}
            </datalist>
            <small>
              MIMO V2.5 内置声音可填 Mia、Chloe、Milo、Dean；VoiceDesign 模型这里填声音描述，VoiceClone 模型这里填
              data:audio/...;base64。
            </small>
          </label>
          {showAdvancedTts ? (
            <>
              <label className="field">
                <span>Language</span>
                <input
                  value={tts.language}
                  onChange={(event) => onPatchTts({ language: event.target.value })}
                  placeholder="auto / en / zh / ja"
                />
                <small>MIMO / Grok 支持 auto 或 BCP-47 语言码；英语卡建议 auto 或 en。</small>
              </label>
              <label className="field">
                <span>Sample Rate</span>
                <input
                  type="number"
                  min={8000}
                  max={48000}
                  value={tts.sample_rate}
                  onChange={(event) => onPatchTts({ sample_rate: Number(event.target.value) })}
                />
                <small>MIMO / Grok 常用 24000；不确定就保持默认。</small>
              </label>
              <label className="field">
                <span>Bit Rate</span>
                <input
                  type="number"
                  min={32000}
                  max={192000}
                  step={32000}
                  value={tts.bit_rate}
                  onChange={(event) => onPatchTts({ bit_rate: Number(event.target.value) })}
                />
                <small>MP3 常用 128000，体积和质量比较均衡。</small>
              </label>
            </>
          ) : null}
        </div>
      ) : (
        <div className="tts-disabled-note">
          <strong>TTS 当前关闭</strong>
          <span>导出时只使用视频原声；需要顶部词伙小喇叭和 AI 朗读时，打开上面的开关或选择一个常用语音预设。</span>
        </div>
      )}
    </section>
  )
}
