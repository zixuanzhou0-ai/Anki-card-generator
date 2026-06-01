import { Boxes, CircleAlert, Cloud, KeyRound, PlugZap } from 'lucide-react'

import type { ApiConfig, ApiPreset, Provider, SecretPrefs } from '../../domain/types'
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
      capabilities:
        provider === 'mimo' || useDeepSeekDefaults || useVertexDefaults
          ? Array.from(new Set([...apiConfig.capabilities, 'structured_json', 'long_context']))
          : apiConfig.capabilities,
    })
  }

  const useGeminiVertex = () => {
    onPatchApi({
      provider: 'gemini-vertex',
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

  const selectedPreset = [...featuredApiPresets, ...advancedApiPresets].find(isPresetSelected)
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
              DeepSeek V4 / Qwen / MIMO 这类 Thinking 模型会流式接收推理过程并只解析最终 JSON；填好 Key 后先点“测试连接”。
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

      <div className="settings-subheading">
        <strong>推荐配置</strong>
        <span>普通用户只需要选一个服务商、填 Key、点测试。</span>
      </div>
      <div className="preset-grid compact-presets" aria-label="API 推荐预设">
        {featuredApiPresets.map(renderPreset)}
      </div>

      <button className="advanced-toggle" type="button" onClick={() => onSetShowAdvancedApi((value) => !value)}>
        {showAdvancedApi ? '收起更多服务商' : '展开更多服务商'}
      </button>
      {showAdvancedApi ? (
        <div className="preset-grid compact-presets secondary-presets" aria-label="更多 API 预设">
          {advancedApiPresets.map(renderPreset)}
        </div>
      ) : null}

      <div className="settings-current-card">
        <div className="settings-current-main">
          <span>当前模型方案</span>
          <strong>{currentModelTitle}</strong>
          <small>{currentModelMeta}</small>
        </div>
        <label className="field settings-key-field">
          <span>API Key</span>
          <input
            type="password"
            value={apiConfig.api_key}
            onChange={(event) => onPatchApi({ api_key: event.target.value })}
            placeholder={
              apiConfig.provider === 'gemini-vertex'
                ? '使用本机 gcloud，不需要填写'
                : apiConfig.provider === 'mimo'
                  ? 'sk-... / tp-...'
                  : 'sk-...'
            }
          />
          <small>
            {apiConfig.provider === 'gemini-vertex'
              ? 'Vertex 模式通过 gcloud auth print-access-token 静默授权，不保存 OAuth token。'
              : '只用于字幕理解和卡片解释生成；记住后保存到本机系统凭据 / DPAPI，不写入明文缓存。'}
          </small>
        </label>
        <label className="toggle secret-toggle settings-current-toggle">
          <input type="checkbox" checked={secretPrefs.rememberModelKey} onChange={onToggleRememberModelKey} />
          <span>记住本机模型 API Key（系统凭据 / DPAPI 加密）</span>
        </label>
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

      {showAdvancedApi ? (
        <div className="api-grid advanced-config-grid">
        <label className="field">
          <span>Provider</span>
          <select value={apiConfig.provider} onChange={(event) => handleProviderChange(event.target.value as Provider)}>
            <option value="local">本地草稿</option>
            <option value="mimo">MIMO / 小米</option>
            <option value="openai-compatible">OpenAI-compatible</option>
            <option value="claude">Claude 原生</option>
            <option value="gemini">Gemini 原生</option>
            <option value="gemini-vertex">Gemini Vertex</option>
          </select>
          <small>MIMO 已有独立选项；Vertex 使用本机 gcloud 登录，其他兼容 OpenAI API 的服务商选 OpenAI-compatible。</small>
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
