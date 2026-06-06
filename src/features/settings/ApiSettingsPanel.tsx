import { Boxes, CircleAlert, Cloud, KeyRound, PlugZap, Save } from 'lucide-react'

import type { ApiConfig, ApiPreset, Provider, SavedApiProfile } from '../../domain/types'
import {
  DEEPSEEK_DEFAULT_MODEL,
  DEEPSEEK_OPENAI_BASE_URL,
  GEMINI_VERTEX_DEFAULT_MODEL,
  GEMINI_VERTEX_GLOBAL_BASE_URL,
} from '../../domain/options'
import { ConnectionTestCard } from './ConnectionTestCard'

type ModelOption = {
  label: string
  value: string
}

type ApiSettingsPanelProps = {
  advancedApiPresets: ApiPreset[]
  apiConfig: ApiConfig
  apiTestMessage: string
  apiTestMeta: string
  apiTestOk?: boolean
  apiTestTitle: string
  apiTestTone: string
  apiTesting: boolean
  activeApiProfileId: string
  apiProfileDirty: boolean
  apiProfileStatus: string
  appBusy: boolean
  capabilityHelp: Record<string, string>
  capabilityLabels: string[]
  featuredApiPresets: ApiPreset[]
  mimoOpenAiBaseUrl: string
  mimoTextModels: ModelOption[]
  savedApiProfiles: SavedApiProfile[]
  showAdvancedApi: boolean
  showCapabilities: boolean
  onApplyApiPreset: (preset: ApiPreset) => void
  onApplySavedApiProfile: (profileId: string) => void
  onPatchApi: (patch: Partial<ApiConfig>) => void
  onSaveApiProfile: () => void
  onSetShowAdvancedApi: (value: boolean | ((current: boolean) => boolean)) => void
  onSetShowCapabilities: (value: boolean | ((current: boolean) => boolean)) => void
  onTestApi: () => void
}

export function ApiSettingsPanel({
  advancedApiPresets,
  apiConfig,
  apiTestMessage,
  apiTestMeta,
  apiTestOk,
  apiTestTitle,
  apiTestTone,
  apiTesting,
  activeApiProfileId,
  apiProfileDirty,
  apiProfileStatus,
  appBusy,
  capabilityHelp,
  capabilityLabels,
  featuredApiPresets,
  mimoOpenAiBaseUrl,
  mimoTextModels,
  savedApiProfiles,
  showAdvancedApi,
  showCapabilities,
  onApplyApiPreset,
  onApplySavedApiProfile,
  onPatchApi,
  onSaveApiProfile,
  onSetShowAdvancedApi,
  onSetShowCapabilities,
  onTestApi,
}: ApiSettingsPanelProps) {
  const isPresetSelected = (preset: ApiPreset) =>
    apiConfig.provider === preset.provider && apiConfig.base_url === preset.base_url && apiConfig.model === preset.model

  const handleProviderChange = (provider: Provider) => {
    const useVertexDefaults = provider === 'gemini-vertex'
    const useDeepSeekDefaults =
      provider === 'openai-compatible' &&
      (apiConfig.provider === 'local' ||
        apiConfig.provider === 'mimo' ||
        !apiConfig.base_url.trim() ||
        !apiConfig.model.trim())
    onPatchApi({
      provider,
      base_url:
        provider === 'mimo'
          ? apiConfig.base_url || mimoOpenAiBaseUrl
          : useVertexDefaults
            ? GEMINI_VERTEX_GLOBAL_BASE_URL
            : useDeepSeekDefaults
              ? DEEPSEEK_OPENAI_BASE_URL
              : apiConfig.base_url,
      model:
        provider === 'mimo' && !apiConfig.model
          ? 'mimo-v2.5-pro'
          : useVertexDefaults
            ? GEMINI_VERTEX_DEFAULT_MODEL
            : useDeepSeekDefaults
              ? DEEPSEEK_DEFAULT_MODEL
              : apiConfig.model,
      api_key: useVertexDefaults ? '' : apiConfig.api_key,
      capabilities:
        provider === 'mimo' || useDeepSeekDefaults || useVertexDefaults
          ? Array.from(new Set([...apiConfig.capabilities, 'structured_json', 'long_context']))
          : apiConfig.capabilities,
    })
  }

  const useGeminiVertex = () => {
    onPatchApi({
      provider: 'gemini-vertex',
      api_key: '',
      base_url: GEMINI_VERTEX_GLOBAL_BASE_URL,
      model: GEMINI_VERTEX_DEFAULT_MODEL,
      capabilities: Array.from(new Set([...apiConfig.capabilities, 'structured_json', 'long_context'])),
    })
  }

  const renderPreset = (preset: ApiPreset) => (
    <button
      type="button"
      key={preset.id}
      className={`preset-card ${isPresetSelected(preset) ? 'selected' : ''}`}
      onClick={() => onApplyApiPreset(preset)}
    >
      <strong>{preset.label}</strong>
      <span>{preset.note}</span>
      <small>{preset.key_hint}</small>
    </button>
  )

  const allApiPresets = [...featuredApiPresets, ...advancedApiPresets]
  const selectedPreset = allApiPresets.find(isPresetSelected)
  const activeSavedProfile = savedApiProfiles.find((profile) => profile.id === activeApiProfileId)
  const profileSelectValue = activeSavedProfile
    ? `saved:${activeSavedProfile.id}`
    : selectedPreset
      ? `preset:${selectedPreset.id}`
      : '__custom'
  const handleProfileSelect = (value: string) => {
    if (value.startsWith('saved:')) {
      onApplySavedApiProfile(value.slice('saved:'.length))
      return
    }
    if (value.startsWith('preset:')) {
      const preset = allApiPresets.find((item) => item.id === value.slice('preset:'.length))
      if (preset) onApplyApiPreset(preset)
    }
  }
  const providerLabel: Record<Provider, string> = {
    claude: 'Claude 原生',
    gemini: 'Gemini 原生',
    'gemini-vertex': 'Gemini Vertex',
    local: '本地草稿',
    mimo: 'MIMO / 小米',
    'openai-compatible': 'OpenAI-compatible',
  }
  const currentModelTitle = selectedPreset?.label ?? providerLabel[apiConfig.provider]
  const currentModelMeta =
    apiConfig.provider === 'local'
      ? '无需 API Key，适合快速预览流程'
      : apiConfig.provider === 'gemini-vertex'
        ? `${apiConfig.model || GEMINI_VERTEX_DEFAULT_MODEL} · 使用本机 gcloud OAuth`
        : `${apiConfig.model || '未填写模型名'} · ${apiConfig.base_url || '原生端点'}`

  return (
    <section className="settings-section settings-section-single">
      <div className="panel-heading">
        <Boxes size={20} />
        <h3>模型 API</h3>
      </div>
      <details className="settings-disclosure">
        <summary>
          <span>模型说明与隐私</span>
          <strong>安全 / 费用 / MIMO Token Plan</strong>
        </summary>
        <div className="settings-callout">
          <PlugZap size={18} />
          <div>
            <strong>强模型优先选 DeepSeek V4 Pro、Qwen3.7 Max 或 MIMO V2.5 Pro。</strong>
            <p>
              DeepSeek V4 / Qwen / MIMO 这类 Thinking 模型会流式接收推理过程并只解析最终 JSON；填好 Key
              后先点“测试连接”。
            </p>
          </div>
        </div>
        <div className="settings-callout risk-callout">
          <CircleAlert size={18} />
          <div>
            <strong>字幕、文档和卡片字段会发送给你选择的模型服务商。</strong>
            <p>
              API Key 只保留在当前会话，关闭或刷新后可能需要重新填写；不要把私人素材或不想上传的内容交给第三方模型。
            </p>
          </div>
        </div>
      </details>

      <div className="settings-profile-picker">
        <div className="settings-subheading">
          <strong>快速切换模型</strong>
          <span>先选方案，再填 Key，最后保存到“我的模型”。</span>
        </div>
        <div className="settings-profile-select-row">
          <label className="field compact-field">
            <span>模型方案</span>
            <select value={profileSelectValue} onChange={(event) => handleProfileSelect(event.target.value)}>
              <option value="__custom" disabled>
                当前手动配置
              </option>
              {savedApiProfiles.length ? (
                <optgroup label="我的模型">
                  {savedApiProfiles.map((profile) => (
                    <option key={profile.id} value={`saved:${profile.id}`}>
                      {profile.label}
                    </option>
                  ))}
                </optgroup>
              ) : null}
              <optgroup label="推荐配置">
                {featuredApiPresets.map((preset) => (
                  <option key={preset.id} value={`preset:${preset.id}`}>
                    {preset.label}
                  </option>
                ))}
              </optgroup>
              <optgroup label="更多服务商">
                {advancedApiPresets.map((preset) => (
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
            onClick={onSaveApiProfile}
            disabled={appBusy}
          >
            <Save size={17} />
            保存模型方案
          </button>
        </div>
        <div className={`settings-profile-status ${apiProfileDirty ? 'warn' : 'ok'}`}>
          <span>{apiProfileStatus}</span>
          <small>
            {apiConfig.provider === 'gemini-vertex'
              ? 'Vertex 使用本机 gcloud OAuth，不保存 API Key。'
              : '保存后 Key 只绑定当前模型方案，不会共享给其他服务商。'}
          </small>
        </div>
        <details className="settings-disclosure compact-provider-drawer">
          <summary>
            <span>浏览全部模型方案</span>
            <strong>
              我的模型 {savedApiProfiles.length} · 预设 {allApiPresets.length}
            </strong>
          </summary>
          {savedApiProfiles.length ? (
            <div className="profile-drawer-list" aria-label="我的模型">
              {savedApiProfiles.map((profile) => (
                <button
                  type="button"
                  className={`profile-option-button ${profile.id === activeApiProfileId ? 'selected' : ''}`}
                  key={profile.id}
                  onClick={() => onApplySavedApiProfile(profile.id)}
                >
                  <strong>{profile.label}</strong>
                  <span>
                    {profile.provider} · {profile.model || '未填写模型'}
                  </span>
                  <small>
                    {profile.auth === 'gcloud' ? 'gcloud OAuth' : profile.has_api_key ? '已保存 Key' : '未保存 Key'}
                  </small>
                </button>
              ))}
            </div>
          ) : null}
          <div className="profile-drawer-list" aria-label="推荐模型预设">
            {featuredApiPresets.map(renderPreset)}
          </div>
          <div className="profile-drawer-list secondary-presets" aria-label="更多模型预设">
            {advancedApiPresets.map(renderPreset)}
          </div>
        </details>
      </div>

      <div className="settings-current-card">
        <div className="settings-current-main">
          <span>当前模型方案</span>
          <strong>{currentModelTitle}</strong>
          <small>{currentModelMeta}</small>
        </div>
        {apiConfig.provider === 'gemini-vertex' ? (
          <div className="settings-auth-card">
            <Cloud size={18} />
            <div>
              <span>Vertex 授权</span>
              <strong>使用本机 gcloud OAuth</strong>
              <small>不需要填写 API Key；点击“测试连接”会检查 gcloud 登录、项目权限、模型名和区域端点。</small>
            </div>
          </div>
        ) : (
          <>
            <label className="field settings-key-field">
              <span>API Key</span>
              <input
                type="password"
                value={apiConfig.api_key}
                onChange={(event) => onPatchApi({ api_key: event.target.value })}
                placeholder={apiConfig.provider === 'mimo' ? 'sk-... / tp-...' : 'sk-...'}
              />
              <small>只用于字幕理解和卡片解释生成；点击“保存模型方案”后保存到本机系统凭据 / DPAPI。</small>
            </label>
          </>
        )}
      </div>

      <ConnectionTestCard
        buttonLabel="测试连接"
        disabled={apiTesting || appBusy}
        message={apiTestMessage}
        meta={apiTestMeta}
        ok={apiTestOk}
        statusLabel="连接状态"
        testing={apiTesting}
        testingLabel="测试中..."
        title={apiTestTitle}
        tone={apiTestTone}
        onTest={onTestApi}
      />

      <button className="advanced-toggle" type="button" onClick={() => onSetShowAdvancedApi((value) => !value)}>
        {showAdvancedApi ? '收起手动配置' : '高级：手动编辑 Provider / Base URL / Model'}
      </button>
      {showAdvancedApi ? (
        <div className="api-grid advanced-config-grid">
          <label className="field">
            <span>Provider</span>
            <select
              value={apiConfig.provider}
              onChange={(event) => handleProviderChange(event.target.value as Provider)}
            >
              <option value="local">本地草稿</option>
              <option value="mimo">MIMO / 小米</option>
              <option value="openai-compatible">OpenAI-compatible</option>
              <option value="claude">Claude 原生</option>
              <option value="gemini">Gemini 原生</option>
              <option value="gemini-vertex">Gemini Vertex</option>
            </select>
            <small>
              MIMO 已有独立选项；Vertex 使用本机 gcloud 登录，其他兼容 OpenAI API 的服务商选 OpenAI-compatible。
            </small>
          </label>
          <label className="field">
            <span>Base URL</span>
            <input
              value={apiConfig.base_url}
              onChange={(event) => onPatchApi({ base_url: event.target.value })}
              placeholder={
                apiConfig.provider === 'mimo'
                  ? mimoOpenAiBaseUrl
                  : apiConfig.provider === 'gemini-vertex'
                    ? GEMINI_VERTEX_GLOBAL_BASE_URL
                    : 'https://api.deepseek.com'
              }
            />
            <small>
              {apiConfig.provider === 'mimo'
                ? `默认 ${mimoOpenAiBaseUrl}；Token Plan 可改成控制台专属端点。`
                : apiConfig.provider === 'gemini-vertex'
                  ? 'Vertex global 端点用 https://aiplatform.googleapis.com；区域端点可填 https://us-central1-aiplatform.googleapis.com。'
                  : apiConfig.provider === 'claude' && apiConfig.base_url
                    ? '当前使用 Anthropic-compatible 自定义端点；通常会自动请求 /v1/messages。'
                    : 'OpenAI-compatible 必填；Claude / Gemini 原生模式不用填。'}
            </small>
          </label>
          <div className="field model-field">
            <span>Model</span>
            <div className="model-input-row">
              <input
                aria-label="Model"
                value={apiConfig.model}
                onChange={(event) => onPatchApi({ model: event.target.value })}
                list="mimo-text-models"
                placeholder={
                  apiConfig.provider === 'mimo'
                    ? 'mimo-v2.5-pro'
                    : apiConfig.provider === 'gemini-vertex'
                      ? GEMINI_VERTEX_DEFAULT_MODEL
                      : 'deepseek-v4-pro'
                }
              />
              <button
                type="button"
                className={`model-provider-chip ${apiConfig.provider === 'gemini-vertex' ? 'selected' : ''}`}
                title="使用本机 gcloud 登录调用 Vertex AI"
                onClick={useGeminiVertex}
              >
                <Cloud size={15} />
                Vertex AI
              </button>
            </div>
            <datalist id="mimo-text-models">
              {mimoTextModels.map((model) => (
                <option key={model.value} value={model.value}>
                  {model.label}
                </option>
              ))}
            </datalist>
            <small>
              {apiConfig.provider === 'mimo'
                ? '官方要求模型 ID 小写：mimo-v2.5-pro、mimo-v2.5、mimo-v2-pro、mimo-v2-omni。'
                : apiConfig.provider === 'gemini-vertex'
                  ? '填 Vertex publisher model ID；当前 global 端点已实测 gemini-3.1-pro-preview 可用。'
                  : '填模型 ID，不是产品名。比如 deepseek-v4-pro、deepseek-v4-flash、qwen3.7-max。'}
            </small>
          </div>
        </div>
      ) : null}
      <button
        className="capability-heading collapsible-heading"
        type="button"
        onClick={() => onSetShowCapabilities((value) => !value)}
      >
        <KeyRound size={18} />
        <strong>模型能力标签</strong>
        <span>{showCapabilities ? '收起' : '高级选项，默认不用改'}</span>
      </button>
      {showCapabilities ? (
        <div className="capabilities capability-grid">
          {capabilityLabels.map((capability) => {
            const selected = apiConfig.capabilities.includes(capability)
            return (
              <button
                type="button"
                key={capability}
                className={selected ? 'cap selected' : 'cap'}
                onClick={() => {
                  const capabilities = selected
                    ? apiConfig.capabilities.filter((item) => item !== capability)
                    : [...apiConfig.capabilities, capability]
                  onPatchApi({ capabilities })
                }}
              >
                <strong>{capability}</strong>
                <span>{capabilityHelp[capability]}</span>
              </button>
            )
          })}
        </div>
      ) : null}
      <div className="settings-help-grid">
        <div>
          <CircleAlert size={18} />
          <strong>测试通过代表什么？</strong>
          <p>代表 Key、Base URL、模型名和基础文本生成接口可用，可以进入生成流程。</p>
        </div>
        <div>
          <CircleAlert size={18} />
          <strong>测试失败常见原因</strong>
          <p>Key 填错、模型名不存在、Base URL 和地域不匹配、余额不足、服务商网络不可达。</p>
        </div>
      </div>
    </section>
  )
}
