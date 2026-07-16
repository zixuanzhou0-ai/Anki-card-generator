import { useMemo, useState } from 'react'
import { CheckCircle2, CircleAlert, Cloud, PlugZap, Save, Search, SlidersHorizontal, Trash2 } from 'lucide-react'

import type { ApiConfig, SavedTtsProfile, TtsConfig, TtsPreset, TtsProvider } from '../../domain/types'
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
import {
  canReuseTtsKey,
  catalogFilters,
  filterSavedTtsProfile,
  filterTtsPreset,
  getTtsPresetTone,
  type CatalogFilter,
} from './settingsRecommendations'

type ModelOption = {
  label: string
  value: string
}

type TtsSettingsPanelProps = {
  advancedTtsPresets: TtsPreset[]
  apiConfig: ApiConfig
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
  simpleMode?: boolean
  hideSaveAction?: boolean
  showAdvancedTts: boolean
  tts: TtsConfig
  ttsProfileDirty: boolean
  ttsKeySaved: boolean
  ttsProfileStatus: string
  ttsTestMessage: string
  ttsTestMeta: string
  ttsTestOk?: boolean
  ttsTestTitle: string
  ttsTestTone: string
  ttsTesting: boolean
  onApplySavedTtsProfile: (profileId: string) => void
  onApplyTtsPreset: (preset: TtsPreset) => void
  onDeleteSavedCredential?: () => void
  onPatchTts: (patch: Partial<TtsConfig>) => void
  onSaveTtsProfile: () => void
  onSetShowAdvancedTts: (value: boolean | ((current: boolean) => boolean)) => void
  onTestTts: () => void
}

export function TtsSettingsPanel({
  advancedTtsPresets,
  apiConfig,
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
  simpleMode = false,
  hideSaveAction = false,
  showAdvancedTts,
  tts,
  ttsProfileDirty,
  ttsKeySaved,
  ttsProfileStatus,
  ttsTestMessage,
  ttsTestMeta,
  ttsTestOk,
  ttsTestTitle,
  ttsTestTone,
  ttsTesting,
  onApplySavedTtsProfile,
  onApplyTtsPreset,
  onDeleteSavedCredential,
  onPatchTts,
  onSaveTtsProfile,
  onSetShowAdvancedTts,
  onTestTts,
}: TtsSettingsPanelProps) {
  const [catalogFilter, setCatalogFilter] = useState<CatalogFilter>('all')
  const [catalogSearch, setCatalogSearch] = useState('')
  const allTtsPresets = useMemo(
    () => [...featuredTtsPresets, ...advancedTtsPresets],
    [advancedTtsPresets, featuredTtsPresets],
  )
  const visibleSavedProfiles = useMemo(
    () => savedTtsProfiles.filter((profile) => filterSavedTtsProfile(profile, catalogFilter, catalogSearch)),
    [catalogFilter, catalogSearch, savedTtsProfiles],
  )
  const visiblePresets = useMemo(
    () => allTtsPresets.filter((preset) => filterTtsPreset(preset, catalogFilter, catalogSearch)),
    [allTtsPresets, catalogFilter, catalogSearch],
  )

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

  const customTtsPreset = allTtsPresets.find((preset) => preset.id === 'openai-speech')
  const applyCustomTts = () => {
    if (customTtsPreset) {
      onApplyTtsPreset(customTtsPreset)
      return
    }
    onPatchTts({
      enabled: true,
      provider: 'openai-compatible',
      base_url: 'https://api.openai.com/v1',
      model: 'gpt-4o-mini-tts',
      voice: 'alloy',
      api_key: '',
    })
  }

  const selectedPreset = allTtsPresets.find(isPresetSelected)
  const activeSavedProfile = savedTtsProfiles.find((profile) => profile.id === activeTtsProfileId)
  const providerLabel: Record<TtsProvider, string> = {
    disabled: '关闭 TTS',
    gemini: 'Gemini TTS',
    'gemini-vertex': 'Gemini Vertex TTS',
    grok: 'Grok / xAI TTS',
    mimo: 'MIMO / 小米 TTS',
    'openai-compatible': 'OpenAI-compatible Speech',
    qwen: 'Qwen / 千问 TTS',
  }
  const currentTtsTitle = tts.enabled
    ? (activeSavedProfile?.label ?? selectedPreset?.label ?? providerLabel[tts.provider])
    : 'TTS 当前关闭'
  const currentTtsMeta =
    tts.enabled && tts.provider === 'gemini-vertex'
      ? `${tts.model || GEMINI_VERTEX_TTS_DEFAULT_MODEL} · ${tts.voice || GEMINI_VERTEX_TTS_DEFAULT_VOICE} · 本机 gcloud OAuth`
      : tts.enabled
        ? `${tts.model || '未填写模型名'} · ${tts.voice || '未选择音色'}`
        : '视频卡导出前需要开启整句 TTS 和表达 TTS'
  const ttsCanReuseMainKey = tts.enabled && canReuseTtsKey(apiConfig, tts.provider)
  const ttsAuthReady =
    !tts.enabled || tts.provider === 'gemini-vertex' || ttsCanReuseMainKey || ttsKeySaved || Boolean(tts.api_key.trim())
  const ttsKeyHint = !tts.enabled
    ? 'TTS 已关闭，不需要配置语音 Key。'
    : ttsCanReuseMainKey
      ? '当前语音可复用模型 API Key，不需要重复填写。'
      : tts.provider === 'gemini-vertex'
        ? '当前语音使用本机 gcloud OAuth。'
        : '当前语音需要独立 TTS Key，或保存过的本机凭据。'
  const outputVolume = Number.isFinite(Number(tts.output_volume))
    ? Math.min(1, Math.max(0.4, Number(tts.output_volume)))
    : 0.65
  const outputVolumePercent = Math.round(outputVolume * 100)
  const catalogSavedProfiles = simpleMode ? savedTtsProfiles : visibleSavedProfiles
  const catalogPresets = simpleMode ? featuredTtsPresets : visiblePresets
  const catalogEmpty = !catalogSavedProfiles.length && !catalogPresets.length
  const canDeleteSavedCredential =
    ttsKeySaved &&
    tts.enabled &&
    tts.provider !== 'disabled' &&
    tts.provider !== 'gemini-vertex' &&
    Boolean(onDeleteSavedCredential)

  return (
    <section className="settings-section settings-section-single">
      <div className="panel-heading">
        <PlugZap size={20} />
        <h3>语音 TTS</h3>
      </div>

      <div className="settings-setup-hero">
        <div>
          <span>语音目录</span>
          <strong>{simpleMode ? '选择一个语音方案。' : '选择 TTS 厂商，也可以手动接入 Speech 接口。'}</strong>
          <small>
            {simpleMode
              ? '选择方案，完成授权，然后生成一段真实测试语音。'
              : '语音目录只负责填表；Base URL、Model、voice 和音量都可以继续调整。'}
          </small>
        </div>
        <div className={`settings-readiness-pill ${ttsAuthReady ? 'ok' : 'warn'}`}>
          {ttsAuthReady ? <CheckCircle2 size={16} /> : <CircleAlert size={16} />}
          {ttsAuthReady ? '授权已就绪' : '需要 TTS Key'}
        </div>
      </div>

      <div className="settings-directory-layout">
        <aside className="settings-directory-panel" aria-label="语音厂商和模型目录">
          {!simpleMode ? (
            <>
              <label className="settings-search-field">
                <Search size={16} />
                <input
                  value={catalogSearch}
                  onChange={(event) => setCatalogSearch(event.target.value)}
                  placeholder="搜索语音厂商、模型、voice"
                />
              </label>
              <div className="settings-filter-row" aria-label="语音目录筛选">
                {catalogFilters.map((filter) => (
                  <button
                    type="button"
                    key={filter.id}
                    className={catalogFilter === filter.id ? 'selected' : ''}
                    onClick={() => setCatalogFilter(filter.id)}
                  >
                    {filter.label}
                  </button>
                ))}
              </div>
            </>
          ) : (
            <div className="settings-simple-directory-heading">
              <strong>选择语音方案</strong>
              <small>选择推荐、已保存或关闭方案；连接参数和音频参数在高级模式中设置。</small>
            </div>
          )}
          <div className="settings-catalog-list">
            {!simpleMode && catalogFilter !== 'saved' ? (
              <button type="button" className="settings-catalog-item manual" onClick={applyCustomTts}>
                <span>手动添加</span>
                <strong>OpenAI-compatible Speech</strong>
                <small>自己填写任意兼容 Speech 接口的 Base URL、model、voice 和 Key。</small>
                <em>自定义</em>
              </button>
            ) : null}
            {simpleMode && catalogSavedProfiles.length ? (
              <p className="settings-catalog-group-label">已保存方案</p>
            ) : null}
            {catalogSavedProfiles.map((profile) => (
              <button
                type="button"
                className={`settings-catalog-item saved ${profile.id === activeTtsProfileId ? 'selected' : ''}`}
                key={profile.id}
                onClick={() => onApplySavedTtsProfile(profile.id)}
              >
                <span>我的语音</span>
                <strong>{profile.label}</strong>
                <small>
                  {simpleMode ? (
                    profile.auth === 'gcloud' ? (
                      'gcloud OAuth'
                    ) : profile.has_api_key ? (
                      '已保存 Key'
                    ) : (
                      '未保存 Key'
                    )
                  ) : (
                    <>
                      {profile.provider} · {profile.model || '无模型'} · {profile.voice || '无音色'}
                    </>
                  )}
                </small>
                <em>
                  {profile.auth === 'gcloud' ? 'gcloud OAuth' : profile.has_api_key ? '已保存 Key' : '未保存 Key'}
                </em>
              </button>
            ))}
            {simpleMode ? <p className="settings-catalog-group-label">推荐与关闭方案</p> : null}
            {catalogPresets.map((preset) => (
              <button
                type="button"
                className={`settings-catalog-item ${getTtsPresetTone(preset)} ${!activeSavedProfile && isPresetSelected(preset) ? 'selected' : ''}`}
                key={preset.id}
                onClick={() => onApplyTtsPreset(preset)}
              >
                <span>{preset.provider}</span>
                <strong>{preset.label}</strong>
                <small>
                  {simpleMode ? (
                    preset.note
                  ) : (
                    <>
                      {preset.model || '无模型名'} · {preset.voice || '无 voice'}
                    </>
                  )}
                </small>
                <em>{preset.key_hint}</em>
              </button>
            ))}
            {catalogEmpty ? (
              <div className="settings-catalog-empty">
                {simpleMode ? '还没有推荐或已保存的语音方案。' : '没有找到匹配的语音厂商或模型。'}
              </div>
            ) : null}
          </div>
        </aside>

        <div className="settings-config-panel">
          <div className="settings-current-main">
            <span>当前语音配置</span>
            <strong>{currentTtsTitle}</strong>
            <small>
              {simpleMode
                ? !tts.enabled
                  ? '当前已关闭'
                  : tts.provider === 'gemini-vertex'
                    ? '使用本机 gcloud OAuth'
                    : ttsKeySaved
                      ? 'TTS Key 已保存在本机系统凭据'
                      : ttsCanReuseMainKey
                        ? '复用当前模型授权'
                        : '需要填写并验证 TTS Key'
                : currentTtsMeta}
            </small>
          </div>
          <div className="tts-enable-row settings-primary-toggle">
            <label className="toggle">
              <input type="checkbox" checked={tts.enabled} onChange={handleEnabledChange} />
              <span>导出时生成 AI 朗读（整句 + 表达）</span>
            </label>
            <small>关闭时不能导出视频卡；开启后为每张卡生成整句 TTS 和表达 TTS。</small>
          </div>
          <div className={`settings-profile-status ${ttsProfileDirty ? 'warn' : 'ok'}`}>
            <span>{ttsProfileStatus}</span>
            <small>{ttsKeyHint}</small>
          </div>

          {tts.enabled ? (
            <div className="api-grid settings-direct-config-grid">
              {!simpleMode ? (
                <>
                  <label className="field settings-provider-field">
                    <span>语音服务</span>
                    <select
                      value={tts.provider}
                      onChange={(event) => handleProviderChange(event.target.value as TtsProvider)}
                    >
                      <option value="disabled">关闭 TTS</option>
                      <option value="mimo">MIMO / 小米 TTS</option>
                      <option value="qwen">Qwen / 千问 TTS</option>
                      <option value="grok">Grok / xAI TTS</option>
                      <option value="gemini">Gemini TTS</option>
                      <option value="gemini-vertex">Gemini Vertex TTS</option>
                      <option value="openai-compatible">OpenAI-compatible Speech</option>
                    </select>
                  </label>
                  <label className="field settings-long-field">
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
                  </label>
                  <label className="field settings-long-field">
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
                  </label>
                  <label className="field settings-voice-field">
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
                  </label>
                </>
              ) : null}
              {tts.provider === 'gemini-vertex' ? (
                <div className="settings-auth-card settings-auth-card-compact">
                  <Cloud size={18} />
                  <div>
                    <span>Vertex TTS 授权</span>
                    <strong>使用本机 gcloud OAuth</strong>
                    <small>
                      不需要填写 TTS API Key；测试 TTS 会检查 gcloud 登录、Vertex 项目权限、语音模型和音色。
                    </small>
                  </div>
                </div>
              ) : simpleMode && (ttsCanReuseMainKey || ttsKeySaved) ? (
                <div className="settings-auth-card settings-auth-card-compact">
                  <PlugZap size={18} />
                  <div>
                    <span>TTS 授权</span>
                    <strong>{ttsKeySaved ? 'TTS Key 已保存在本机' : '复用当前模型授权'}</strong>
                    <small>当前语音方案可直接测试；如需填写独立 Key，请进入高级模式。</small>
                  </div>
                </div>
              ) : (
                <label className="field settings-key-field">
                  <span>TTS API Key</span>
                  <input
                    type="password"
                    value={tts.api_key}
                    onChange={(event) => onPatchTts({ api_key: event.target.value })}
                    placeholder={
                      ttsKeySaved
                        ? '已保存到系统凭据，留空会自动使用'
                        : tts.provider === 'mimo'
                          ? '可留空复用 MIMO 文本 Key'
                          : tts.provider === 'qwen'
                            ? '可留空复用千问文本 Key'
                            : 'xai-... / AIza... / sk-...'
                    }
                  />
                  <small>{ttsKeyHint} 保存后，这个 Key 才会单独绑定到当前语音。</small>
                </label>
              )}
            </div>
          ) : (
            <div className="tts-disabled-note">
              <strong>{currentTtsTitle}</strong>
              <span>
                {simpleMode ? (
                  '当前没有生成 AI 朗读；选择推荐方案可重新开启。'
                ) : (
                  <>{currentTtsMeta}；请打开开关或选择一个语音厂商。</>
                )}
              </span>
            </div>
          )}

          {!hideSaveAction ? (
            <div className="settings-config-actions">
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
          ) : null}
          {canDeleteSavedCredential ? (
            <div className="settings-config-actions settings-credential-actions" aria-label="已保存的语音凭据">
              <button
                className="secondary-button cancel-button"
                type="button"
                onClick={onDeleteSavedCredential}
                disabled={ttsTesting || appBusy}
                title="只删除当前语音保存在本机系统凭据中的 Key"
              >
                <Trash2 size={16} aria-hidden="true" />
                删除已保存的 Key
              </button>
            </div>
          ) : null}
          <ConnectionTestCard
            buttonLabel="测试 TTS"
            disabled={ttsTesting || appBusy}
            message={ttsTestMessage}
            meta={simpleMode ? (ttsTestOk ? '当前语音方案已验证' : '测试会生成一段真实语音') : ttsTestMeta}
            ok={ttsTestOk}
            statusLabel="TTS 状态"
            testing={ttsTesting}
            testingLabel="测试中..."
            title={ttsTestTitle}
            tone={ttsTestTone}
            onTest={onTestTts}
          />
        </div>
      </div>

      {!simpleMode ? (
        <>
          <button className="advanced-toggle" type="button" onClick={() => onSetShowAdvancedTts((value) => !value)}>
            <SlidersHorizontal size={16} />
            {showAdvancedTts ? '收起语音参数' : '高级：语言、采样率、码率、音量'}
          </button>

          {tts.enabled && showAdvancedTts ? (
            <div className="api-grid tts-api-grid advanced-config-grid">
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

          <details className="settings-disclosure">
            <summary>
              <span>高级说明</span>
              <strong>语音模型 / 授权 / 费用</strong>
            </summary>
            <div className="settings-callout tts-callout">
              <CircleAlert size={18} />
              <div>
                <strong>TTS 是独立能力，但 MIMO / Qwen / Gemini 可以复用同厂商授权。</strong>
                <p>其他兼容 Speech 接口的厂商可用自定义入口填写 Base URL、model、voice 和 Key。</p>
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
        </>
      ) : null}
    </section>
  )
}
