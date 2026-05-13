import { Boxes, CircleAlert, KeyRound, PlugZap } from 'lucide-react'

import type { ApiConfig, ApiPreset, Provider, SecretPrefs } from '../../domain/types'
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
  appBusy: boolean
  capabilityHelp: Record<string, string>
  capabilityLabels: string[]
  featuredApiPresets: ApiPreset[]
  mimoOpenAiBaseUrl: string
  mimoTextModels: ModelOption[]
  secretPrefs: SecretPrefs
  showAdvancedApi: boolean
  showCapabilities: boolean
  onApplyApiPreset: (preset: ApiPreset) => void
  onPatchApi: (patch: Partial<ApiConfig>) => void
  onSetShowAdvancedApi: (value: boolean | ((current: boolean) => boolean)) => void
  onSetShowCapabilities: (value: boolean | ((current: boolean) => boolean)) => void
  onTestApi: () => void
  onToggleRememberModelKey: () => void
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
  appBusy,
  capabilityHelp,
  capabilityLabels,
  featuredApiPresets,
  mimoOpenAiBaseUrl,
  mimoTextModels,
  secretPrefs,
  showAdvancedApi,
  showCapabilities,
  onApplyApiPreset,
  onPatchApi,
  onSetShowAdvancedApi,
  onSetShowCapabilities,
  onTestApi,
  onToggleRememberModelKey,
}: ApiSettingsPanelProps) {
  const isPresetSelected = (preset: ApiPreset) =>
    apiConfig.provider === preset.provider &&
    apiConfig.base_url === preset.base_url &&
    apiConfig.model === preset.model

  const handleProviderChange = (provider: Provider) => {
    onPatchApi({
      provider,
      base_url: provider === 'mimo' ? apiConfig.base_url || mimoOpenAiBaseUrl : apiConfig.base_url,
      model: provider === 'mimo' && !apiConfig.model ? 'mimo-v2.5-pro' : apiConfig.model,
      capabilities:
        provider === 'mimo'
          ? Array.from(new Set([...apiConfig.capabilities, 'structured_json', 'long_context']))
          : apiConfig.capabilities,
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
            <strong>你现在用 MIMO，可以直接选 MIMO V2.5 Pro。</strong>
            <p>
              Token Plan 用户优先选 MIMO Token Plan SGP。程序会按官方要求自动使用 api-key 请求头、
              小写模型 ID 和更大的 max_completion_tokens；填好 Key 后先点“测试连接”。
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

      <div className="settings-subheading">
        <strong>推荐配置</strong>
        <span>普通用户只需要选一个服务商、填 Key、点测试。</span>
      </div>
      <div className="preset-grid compact-presets" aria-label="API 推荐预设">
        {featuredApiPresets.map(renderPreset)}
      </div>

      <button
        className="advanced-toggle"
        type="button"
        onClick={() => onSetShowAdvancedApi((value) => !value)}
      >
        {showAdvancedApi ? '收起更多服务商' : '展开更多服务商'}
      </button>
      {showAdvancedApi ? (
        <div className="preset-grid compact-presets secondary-presets" aria-label="更多 API 预设">
          {advancedApiPresets.map(renderPreset)}
        </div>
      ) : null}

      <div className="api-grid">
        <label className="field">
          <span>Provider</span>
          <select value={apiConfig.provider} onChange={(event) => handleProviderChange(event.target.value as Provider)}>
            <option value="local">本地草稿</option>
            <option value="mimo">MIMO / 小米</option>
            <option value="openai-compatible">OpenAI-compatible</option>
            <option value="claude">Claude 原生</option>
            <option value="gemini">Gemini 原生</option>
          </select>
          <small>MIMO 已有独立选项；其他兼容 OpenAI API 的服务商选 OpenAI-compatible。</small>
        </label>
        <label className="field">
          <span>Base URL</span>
          <input
            value={apiConfig.base_url}
            onChange={(event) => onPatchApi({ base_url: event.target.value })}
            placeholder={apiConfig.provider === 'mimo' ? mimoOpenAiBaseUrl : 'https://api.deepseek.com/v1'}
          />
          <small>
            {apiConfig.provider === 'mimo'
              ? `默认 ${mimoOpenAiBaseUrl}；Token Plan 可改成控制台专属端点。`
              : apiConfig.provider === 'claude' && apiConfig.base_url
                ? '当前使用 Anthropic-compatible 自定义端点；通常会自动请求 /v1/messages。'
                : 'OpenAI-compatible 必填；Claude / Gemini 原生模式不用填。'}
          </small>
        </label>
        <label className="field">
          <span>Model</span>
          <input
            value={apiConfig.model}
            onChange={(event) => onPatchApi({ model: event.target.value })}
            list="mimo-text-models"
            placeholder={apiConfig.provider === 'mimo' ? 'mimo-v2.5-pro' : 'deepseek-chat'}
          />
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
              : '填模型 ID，不是产品名。比如 deepseek-chat、qwen-plus。'}
          </small>
        </label>
        <label className="field">
          <span>API Key</span>
          <input
            type="password"
            value={apiConfig.api_key}
            onChange={(event) => onPatchApi({ api_key: event.target.value })}
            placeholder={apiConfig.provider === 'mimo' ? 'sk-... / tp-...' : 'sk-...'}
          />
          <small>只用于当前会话的字幕理解和卡片解释生成；不会写入本地缓存，也不会自动拿去做 TTS。</small>
        </label>
        <label className="toggle secret-toggle">
          <input
            type="checkbox"
            checked={secretPrefs.rememberModelKey}
            onChange={onToggleRememberModelKey}
          />
          <span>记住本机模型 API Key（Windows Credential Manager）</span>
        </label>
      </div>
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
          <p>Key 填错、模型名不存在、Base URL 少了 /v1、余额不足、服务商网络不可达。</p>
        </div>
      </div>
    </section>
  )
}
