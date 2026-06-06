import { CircleAlert, Cloud, PlugZap, Save } from 'lucide-react'

import type { SavedTtsProfile, TtsConfig, TtsPreset, TtsProvider } from '../../domain/types'
import {
  GEMINI_VERTEX_TTS_DEFAULT_MODEL,
  GEMINI_VERTEX_TTS_DEFAULT_VOICE,
  GEMINI_VERTEX_TTS_GLOBAL_BASE_URL,
  geminiVertexTtsModels,
  geminiVertexTtsVoices,
  QWEN_TTS_DEFAULT_MODEL,
  QWEN_TTS_DEFAULT_VOICE,
} from '../../domain/ttsProviders'
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
  qwenTtsModels: ModelOption[]
  qwenTtsVoices: string[]
  activeTtsProfileId: string
  savedTtsProfiles: SavedTtsProfile[]
  showAdvancedTts: boolean
  tts: TtsConfig
  ttsProfileDirty: boolean
  ttsProfileStatus: string
  ttsTestMessage: string
  ttsTestMeta: string
  ttsTestOk?: boolean
  ttsTestTitle: string
  ttsTestTone: string
  ttsTesting: boolean
  onApplySavedTtsProfile: (profileId: string) => void
  onApplyTtsPreset: (preset: TtsPreset) => void
  onPatchTts: (patch: Partial<TtsConfig>) => void
  onSaveTtsProfile: () => void
  onSetShowAdvancedTts: (value: boolean | ((current: boolean) => boolean)) => void
  onTestTts: () => void
}

export function TtsSettingsPanel({
  advancedTtsPresets,
  appBusy,
  featuredTtsPresets,
  mimoOpenAiBaseUrl,
  mimoTokenPlanSgpBaseUrl,
  mimoTtsModels,
  mimoTtsVoices,
  qwenTtsModels,
  qwenTtsVoices,
  activeTtsProfileId,
  savedTtsProfiles,
  showAdvancedTts,
  tts,
  ttsProfileDirty,
  ttsProfileStatus,
  ttsTestMessage,
  ttsTestMeta,
  ttsTestOk,
  ttsTestTitle,
  ttsTestTone,
  ttsTesting,
  onApplySavedTtsProfile,
  onApplyTtsPreset,
  onPatchTts,
  onSaveTtsProfile,
  onSetShowAdvancedTts,
  onTestTts,
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
      provider: !tts.enabled ? (tts.provider === 'disabled' ? 'qwen' : tts.provider) : 'disabled',
      base_url: !tts.enabled && tts.provider === 'disabled' ? 'https://dashscope.aliyuncs.com/api/v1' : tts.base_url,
      model: !tts.enabled && !tts.model ? QWEN_TTS_DEFAULT_MODEL : tts.model,
      voice: !tts.enabled && !tts.voice ? QWEN_TTS_DEFAULT_VOICE : tts.voice,
    })
  }

  const handleProviderChange = (provider: TtsProvider) => {
    const providerChanged = provider !== tts.provider
    const defaultModel =
      provider === 'mimo'
        ? 'mimo-v2.5-tts'
        : provider === 'qwen'
          ? QWEN_TTS_DEFAULT_MODEL
          : provider === 'gemini'
            ? 'gemini-2.5-flash-preview-tts'
            : provider === 'gemini-vertex'
              ? GEMINI_VERTEX_TTS_DEFAULT_MODEL
              : provider === 'openai-compatible'
                ? 'gpt-4o-mini-tts'
                : ''
    const defaultVoice =
      provider === 'mimo'
        ? 'Mia'
        : provider === 'qwen'
          ? QWEN_TTS_DEFAULT_VOICE
          : provider === 'grok'
            ? 'eve'
            : provider === 'gemini' || provider === 'gemini-vertex'
              ? GEMINI_VERTEX_TTS_DEFAULT_VOICE
              : provider === 'openai-compatible'
                ? 'alloy'
                : ''
    const nextBaseUrl =
      provider === 'disabled'
        ? ''
        : provider === 'gemini'
          ? tts.base_url
          : provider === 'mimo'
            ? tts.base_url.includes('xiaomimimo.com')
              ? tts.base_url
              : mimoTokenPlanSgpBaseUrl
            : provider === 'qwen'
              ? tts.base_url.includes('dashscope')
                ? tts.base_url
                : 'https://dashscope.aliyuncs.com/api/v1'
              : provider === 'grok'
                ? 'https://api.x.ai/v1'
                : provider === 'gemini-vertex'
                  ? tts.base_url.includes('aiplatform.googleapis.com')
                    ? tts.base_url
                    : GEMINI_VERTEX_TTS_GLOBAL_BASE_URL
                  : provider === 'openai-compatible'
                    ? tts.base_url || 'https://api.openai.com/v1'
                    : tts.base_url

    onPatchTts({
      provider,
      enabled: provider !== 'disabled',
      base_url: nextBaseUrl,
      api_key: providerChanged ? '' : tts.api_key,
      model: providerChanged ? defaultModel : tts.model || defaultModel,
      voice: providerChanged ? defaultVoice : tts.voice || defaultVoice,
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

  const allTtsPresets = [...featuredTtsPresets, ...advancedTtsPresets]
  const selectedPreset = allTtsPresets.find(isPresetSelected)
  const activeSavedProfile = savedTtsProfiles.find((profile) => profile.id === activeTtsProfileId)
  const profileSelectValue = activeSavedProfile
    ? `saved:${activeSavedProfile.id}`
    : selectedPreset
      ? `preset:${selectedPreset.id}`
      : '__custom'
  const handleProfileSelect = (value: string) => {
    if (value.startsWith('saved:')) {
      onApplySavedTtsProfile(value.slice('saved:'.length))
      return
    }
    if (value.startsWith('preset:')) {
      const preset = allTtsPresets.find((item) => item.id === value.slice('preset:'.length))
      if (preset) onApplyTtsPreset(preset)
    }
  }
  const providerLabel: Record<TtsProvider, string> = {
    disabled: '关闭 TTS',
    gemini: 'Gemini TTS',
    'gemini-vertex': 'Gemini Vertex TTS',
    grok: 'Grok / xAI TTS',
    mimo: 'MIMO / 小米 TTS',
    'openai-compatible': 'OpenAI-compatible Speech',
    qwen: 'Qwen / 千问 TTS',
  }
  const currentTtsTitle = tts.enabled ? (selectedPreset?.label ?? providerLabel[tts.provider]) : 'TTS 当前关闭'
  const currentTtsMeta =
    tts.enabled && tts.provider === 'gemini-vertex'
      ? `${tts.model || GEMINI_VERTEX_TTS_DEFAULT_MODEL} · ${tts.voice || GEMINI_VERTEX_TTS_DEFAULT_VOICE} · 本机 gcloud OAuth`
      : tts.enabled
        ? `${tts.model || '未填写模型名'} · ${tts.voice || '未选择音色'}`
        : '导出时只使用视频原声'
  const outputVolume = Number.isFinite(Number(tts.output_volume))
    ? Math.min(1, Math.max(0.4, Number(tts.output_volume)))
    : 0.65
  const outputVolumePercent = Math.round(outputVolume * 100)

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
            <strong>TTS 是独立配置，千问和 MIMO 语音模型都在这里选。</strong>
            <p>
              千问3 TTS、MIMO V2.5 TTS、VoiceDesign、VoiceClone 和 V2 TTS 都可以作为独立语音模型配置。
              如果上方文本模型已经配置了同服务商 Key，TTS 会默认复用它；只有想单独换语音服务时才需要另填 TTS Key。
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

      <div className="settings-profile-picker">
        <div className="settings-subheading">
          <strong>快速切换语音</strong>
          <span>需要 AI 朗读时选一个方案，调好音色后保存到“我的语音”。</span>
        </div>
        <div className="settings-profile-select-row">
          <label className="field compact-field">
            <span>语音方案</span>
            <select value={profileSelectValue} onChange={(event) => handleProfileSelect(event.target.value)}>
              <option value="__custom" disabled>
                当前手动配置
              </option>
              {savedTtsProfiles.length ? (
                <optgroup label="我的语音">
                  {savedTtsProfiles.map((profile) => (
                    <option key={profile.id} value={`saved:${profile.id}`}>
                      {profile.label}
                    </option>
                  ))}
                </optgroup>
              ) : null}
              <optgroup label="推荐语音">
                {featuredTtsPresets.map((preset) => (
                  <option key={preset.id} value={`preset:${preset.id}`}>
                    {preset.label}
                  </option>
                ))}
              </optgroup>
              <optgroup label="更多语音服务">
                {advancedTtsPresets.map((preset) => (
                  <option key={preset.id} value={`preset:${preset.id}`}>
                    {preset.label}
                  </option>
                ))}
              </optgroup>
            </select>
          </label>
          <button
            className="primary-button settings-save-button"
            type="button"
            onClick={onSaveTtsProfile}
            disabled={appBusy}
          >
            <Save size={17} />
            保存语音方案
          </button>
        </div>
        <div className={`settings-profile-status ${ttsProfileDirty ? 'warn' : 'ok'}`}>
          <span>{ttsProfileStatus}</span>
          <small>
            {tts.provider === 'gemini-vertex'
              ? 'Vertex TTS 使用本机 gcloud OAuth，不保存 TTS API Key。'
              : '保存后 Key 只绑定当前语音方案，不会共享给其他语音服务。'}
          </small>
        </div>
        <details className="settings-disclosure compact-provider-drawer">
          <summary>
            <span>浏览全部语音方案</span>
            <strong>
              我的语音 {savedTtsProfiles.length} · 预设 {allTtsPresets.length}
            </strong>
          </summary>
          {savedTtsProfiles.length ? (
            <div className="profile-drawer-list" aria-label="我的语音">
              {savedTtsProfiles.map((profile) => (
                <button
                  type="button"
                  className={`profile-option-button ${profile.id === activeTtsProfileId ? 'selected' : ''}`}
                  key={profile.id}
                  onClick={() => onApplySavedTtsProfile(profile.id)}
                >
                  <strong>{profile.label}</strong>
                  <span>
                    {profile.provider} · {profile.model || '无模型'} · {profile.voice || '无音色'}
                  </span>
                  <small>
                    {profile.auth === 'gcloud' ? 'gcloud OAuth' : profile.has_api_key ? '已保存 Key' : '未保存 Key'}
                  </small>
                </button>
              ))}
            </div>
          ) : null}
          <div className="profile-drawer-list" aria-label="推荐语音预设">
            {featuredTtsPresets.map(renderPreset)}
          </div>
          <div className="profile-drawer-list secondary-presets" aria-label="更多语音预设">
            {advancedTtsPresets.map(renderPreset)}
          </div>
        </details>
      </div>

      <div className="tts-enable-row">
        <label className="toggle">
          <input type="checkbox" checked={tts.enabled} onChange={handleEnabledChange} />
          <span>导出时生成整句和表达 TTS</span>
        </label>
        <small>开启后会额外生成整句朗读，并给顶部重点表达生成小喇叭音频。</small>
      </div>

      {tts.enabled ? (
        <div className="settings-current-card tts-current-card">
          <div className="settings-current-main">
            <span>当前语音方案</span>
            <strong>{currentTtsTitle}</strong>
            <small>{currentTtsMeta}</small>
          </div>
          {tts.provider === 'gemini-vertex' ? (
            <div className="settings-auth-card">
              <Cloud size={18} />
              <div>
                <span>Vertex TTS 授权</span>
                <strong>使用本机 gcloud OAuth</strong>
                <small>不需要填写 TTS API Key；测试 TTS 会检查 gcloud 登录、Vertex 项目权限、语音模型和音色。</small>
              </div>
            </div>
          ) : (
            <>
              <label className="field settings-key-field">
                <span>TTS API Key</span>
                <input
                  type="password"
                  value={tts.api_key}
                  onChange={(event) => onPatchTts({ api_key: event.target.value })}
                  placeholder={
                    tts.provider === 'mimo'
                      ? '可留空复用 MIMO 文本 Key'
                      : tts.provider === 'qwen'
                        ? '可留空复用千问文本 Key'
                        : 'xai-... / AIza... / sk-...'
                  }
                />
                <small>同服务商文本 Key 可自动复用；点击“保存语音方案”后，这个 Key 才会单独绑定到当前语音。</small>
              </label>
            </>
          )}
        </div>
      ) : (
        <div className="tts-disabled-note">
          <strong>{currentTtsTitle}</strong>
          <span>{currentTtsMeta}；需要顶部表达小喇叭和 AI 朗读时，打开上面的开关或选择一个语音方案。</span>
        </div>
      )}

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

      <button className="advanced-toggle" type="button" onClick={() => onSetShowAdvancedTts((value) => !value)}>
        {showAdvancedTts ? '收起语音参数' : '高级：语音服务、模型、音色参数'}
      </button>

      {tts.enabled && showAdvancedTts ? (
        <div className="api-grid tts-api-grid advanced-config-grid">
          <label className="field">
            <span>语音服务</span>
            <select value={tts.provider} onChange={(event) => handleProviderChange(event.target.value as TtsProvider)}>
              <option value="disabled">关闭 TTS</option>
              <option value="mimo">MIMO / 小米 TTS</option>
              <option value="qwen">Qwen / 千问 TTS</option>
              <option value="grok">Grok / xAI TTS</option>
              <option value="gemini">Gemini TTS</option>
              <option value="gemini-vertex">Gemini Vertex TTS</option>
              <option value="openai-compatible">OpenAI-compatible Speech</option>
            </select>
            <small>这里选择语音服务商，不影响上面的文本模型 Provider。</small>
          </label>
          <label className="field">
            <span>语音 Base URL</span>
            <input
              value={tts.base_url}
              onChange={(event) => onPatchTts({ base_url: event.target.value })}
              placeholder={
                tts.provider === 'mimo'
                  ? mimoOpenAiBaseUrl
                  : tts.provider === 'qwen'
                    ? 'https://dashscope.aliyuncs.com/api/v1'
                    : tts.provider === 'gemini-vertex'
                      ? GEMINI_VERTEX_TTS_GLOBAL_BASE_URL
                      : 'https://api.x.ai/v1'
              }
            />
            <small>
              {tts.provider === 'mimo'
                ? `MIMO 默认 ${mimoOpenAiBaseUrl}；你的 tp-... 套餐 Key 优先用 ${mimoTokenPlanSgpBaseUrl}。`
                : tts.provider === 'qwen'
                  ? '千问 TTS 默认北京地域 https://dashscope.aliyuncs.com/api/v1；新加坡改成 intl 端点。'
                  : tts.provider === 'gemini-vertex'
                    ? 'Vertex Gemini-TTS 默认 global 端点；如需指定区域可填 https://us-central1-aiplatform.googleapis.com。'
                    : 'Grok 默认 https://api.x.ai/v1；Gemini API Key 版可留空。'}
            </small>
          </label>
          <label className="field">
            <span>语音模型</span>
            <input
              value={tts.model}
              onChange={(event) => onPatchTts({ model: event.target.value })}
              placeholder={
                tts.provider === 'mimo'
                  ? 'mimo-v2.5-tts'
                  : tts.provider === 'qwen'
                    ? 'qwen3-tts-flash'
                    : tts.provider === 'grok'
                      ? '留空即可，Grok TTS 不需要模型名'
                      : tts.provider === 'gemini'
                        ? 'gemini-2.5-flash-preview-tts'
                        : tts.provider === 'gemini-vertex'
                          ? GEMINI_VERTEX_TTS_DEFAULT_MODEL
                          : 'gpt-4o-mini-tts'
              }
              list={
                tts.provider === 'qwen'
                  ? 'qwen-tts-models'
                  : tts.provider === 'gemini-vertex'
                    ? 'gemini-vertex-tts-models'
                    : 'mimo-tts-models'
              }
            />
            <datalist id="mimo-tts-models">
              {mimoTtsModels.map((model) => (
                <option key={model.value} value={model.value}>
                  {model.label}
                </option>
              ))}
            </datalist>
            <datalist id="qwen-tts-models">
              {qwenTtsModels.map((model) => (
                <option key={model.value} value={model.value}>
                  {model.label}
                </option>
              ))}
            </datalist>
            <datalist id="gemini-vertex-tts-models">
              {geminiVertexTtsModels.map((model) => (
                <option key={model.value} value={model.value}>
                  {model.label}
                </option>
              ))}
            </datalist>
            <small>
              {tts.provider === 'mimo'
                ? '官方要求模型 ID 小写：mimo-v2.5-tts、voicedesign、voiceclone、mimo-v2-tts。'
                : tts.provider === 'qwen'
                  ? '英语卡推荐 qwen3-tts-flash + Jennifer/Aiden；需要语气控制时用 qwen3-tts-instruct-flash。'
                  : tts.provider === 'gemini-vertex'
                    ? 'Google Cloud 最新预览模型默认 gemini-3.1-flash-tts-preview；Language 留 auto 时导出会按学习语言选择。'
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
                  : tts.provider === 'qwen'
                    ? 'Jennifer / Aiden / Serena / Cherry'
                    : tts.provider === 'grok'
                      ? 'eve / ara / leo / rex / sal'
                      : tts.provider === 'gemini-vertex'
                        ? 'Kore / Aoede / Puck / Charon'
                        : 'Kore / alloy'
              }
              list={
                tts.provider === 'mimo'
                  ? 'mimo-tts-voices'
                  : tts.provider === 'qwen'
                    ? 'qwen-tts-voices'
                    : tts.provider === 'gemini-vertex'
                      ? 'gemini-vertex-tts-voices'
                      : undefined
              }
            />
            <datalist id="mimo-tts-voices">
              {mimoTtsVoices.map((voice) => (
                <option key={voice} value={voice} />
              ))}
            </datalist>
            <datalist id="qwen-tts-voices">
              {qwenTtsVoices.map((voice) => (
                <option key={voice} value={voice} />
              ))}
            </datalist>
            <datalist id="gemini-vertex-tts-voices">
              {geminiVertexTtsVoices.map((voice) => (
                <option key={voice} value={voice} />
              ))}
            </datalist>
            <small>
              {tts.provider === 'gemini-vertex'
                ? 'Gemini Vertex TTS 可先试 Kore、Aoede、Puck、Charon；多语言卡建议 Language 保持 auto。'
                : 'MIMO V2.5 内置声音可填 Mia、Chloe、Milo、Dean；千问英语卡优先试 Jennifer 或 Aiden。'}
            </small>
          </label>
          <label className="field">
            <span>Language</span>
            <input
              value={tts.language}
              onChange={(event) => onPatchTts({ language: event.target.value })}
              placeholder="auto / en-US / fr-FR / es-MX / ja-JP / ru-RU"
            />
            <small>留 auto 时导出会按学习语言选择默认 BCP-47 代码；手动填写时优先使用这里的值。</small>
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
          <label className="field tts-volume-field">
            <span>导出 TTS 音量：{outputVolumePercent}%</span>
            <input
              type="range"
              min={0.4}
              max={1}
              step={0.05}
              value={outputVolume}
              onChange={(event) => onPatchTts({ output_volume: Number(event.target.value) })}
            />
            <small>只降低 AI TTS 的整句和表达朗读，不改变原视频原声；默认 65%。</small>
          </label>
        </div>
      ) : null}
    </section>
  )
}
