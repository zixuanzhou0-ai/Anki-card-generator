import { useMemo, useState } from 'react'
import { Boxes, CheckCircle2, CircleAlert, Cloud, KeyRound, PlugZap, Save, Search } from 'lucide-react'

import type { ApiConfig, ApiPreset, HermesProxyStatus, Provider, SavedApiProfile } from '../../domain/types'
import {
  DEEPSEEK_DEFAULT_MODEL,
  DEEPSEEK_OPENAI_BASE_URL,
  GEMINI_VERTEX_DEFAULT_MODEL,
  GEMINI_VERTEX_GLOBAL_BASE_URL,
} from '../../domain/options'
import { isHermesLocalApiConfig } from '../../services/apiConfig'
import { ConnectionTestCard } from './ConnectionTestCard'
import { catalogFilters, filterApiPreset, filterSavedApiProfile, getApiPresetTone, type CatalogFilter } from './settingsRecommendations'

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
  apiKeySaved: boolean
  activeApiProfileId: string
  apiProfileDirty: boolean
  apiProfileStatus: string
  appBusy: boolean
  capabilityHelp: Record<string, string>
  capabilityLabels: string[]
  featuredApiPresets: ApiPreset[]
  hermesChecking: boolean
  hermesStarting: boolean
  hermesStatus: HermesProxyStatus | null
  mimoOpenAiBaseUrl: string
  mimoTextModels: ModelOption[]
  savedApiProfiles: SavedApiProfile[]
  simpleMode?: boolean
  showCapabilities: boolean
  onApplyApiPreset: (preset: ApiPreset) => void
  onCheckHermes: () => void
  onApplySavedApiProfile: (profileId: string) => void
  onPatchApi: (patch: Partial<ApiConfig>) => void
  onSaveApiProfile: () => void
  onSetShowCapabilities: (value: boolean | ((current: boolean) => boolean)) => void
  onStartHermes: () => void
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
  apiKeySaved,
  activeApiProfileId,
  apiProfileDirty,
  apiProfileStatus,
  appBusy,
  capabilityHelp,
  capabilityLabels,
  featuredApiPresets,
  hermesChecking,
  hermesStarting,
  hermesStatus,
  mimoOpenAiBaseUrl,
  mimoTextModels,
  savedApiProfiles,
  simpleMode = false,
  showCapabilities,
  onApplyApiPreset,
  onApplySavedApiProfile,
  onCheckHermes,
  onPatchApi,
  onSaveApiProfile,
  onSetShowCapabilities,
  onStartHermes,
  onTestApi,
}: ApiSettingsPanelProps) {
  const [catalogFilter, setCatalogFilter] = useState<CatalogFilter>('all')
  const [catalogSearch, setCatalogSearch] = useState('')
  const allApiPresets = useMemo(() => [...featuredApiPresets, ...advancedApiPresets], [advancedApiPresets, featuredApiPresets])
  const visibleSavedProfiles = useMemo(
    () => savedApiProfiles.filter((profile) => filterSavedApiProfile(profile, catalogFilter, catalogSearch)),
    [catalogFilter, catalogSearch, savedApiProfiles],
  )
  const visiblePresets = useMemo(
    () => allApiPresets.filter((preset) => filterApiPreset(preset, catalogFilter, catalogSearch)),
    [allApiPresets, catalogFilter, catalogSearch],
  )

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

  const customPreset = allApiPresets.find((preset) => preset.id === 'custom-compatible')
  const applyCustomModel = () => {
    if (customPreset) {
      onApplyApiPreset(customPreset)
      return
    }
    onPatchApi({
      provider: 'openai-compatible',
      base_url: '',
      model: '',
      api_key: '',
      capabilities: ['structured_json', 'cheap_batch'],
    })
  }

  const usesHermesLocal = isHermesLocalApiConfig(apiConfig)
  const selectedPreset = allApiPresets.find(isPresetSelected)
  const activeSavedProfile = savedApiProfiles.find((profile) => profile.id === activeApiProfileId)
  const providerLabel: Record<Provider, string> = {
    claude: 'Claude 原生',
    gemini: 'Gemini 原生',
    'gemini-vertex': 'Gemini Vertex',
    local: '预览模式',
    mimo: 'MIMO / 小米',
    'openai-compatible': 'OpenAI-compatible',
  }
  const currentModelTitle = activeSavedProfile?.label ?? selectedPreset?.label ?? providerLabel[apiConfig.provider]
  const currentModelMeta =
    apiConfig.provider === 'local'
      ? '无需 API Key，仅用于演示预览，不可正式制卡'
      : usesHermesLocal
        ? `${apiConfig.model} · Hermes 本机 xAI OAuth`
        : apiConfig.provider === 'gemini-vertex'
          ? `${apiConfig.model || GEMINI_VERTEX_DEFAULT_MODEL} · 使用本机 gcloud OAuth`
          : `${apiConfig.model || '未填写模型名'} · ${apiConfig.base_url || '原生端点'}`
  const authReady =
    apiConfig.provider !== 'local' &&
    (apiConfig.provider === 'gemini-vertex' ||
      (usesHermesLocal && hermesStatus?.state === 'ready') ||
      apiKeySaved ||
      Boolean(apiConfig.api_key.trim()))
  const readinessLabel =
    apiConfig.provider === 'local'
      ? '需要正式模型'
      : usesHermesLocal
        ? hermesStatus?.state === 'ready'
          ? '本机 OAuth 已就绪'
          : hermesStatus?.state === 'stopped'
            ? '代理待启动'
            : hermesStatus?.state === 'oauth_unready'
              ? 'OAuth 未就绪'
              : '需要检测 Hermes'
        : authReady
          ? '授权已就绪'
          : '需要填写 Key'
  const catalogEmpty = !visibleSavedProfiles.length && !visiblePresets.length

  return (
    <section className="settings-section settings-section-single">
      <div className="panel-heading">
        <Boxes size={20} />
        <h3>模型 API</h3>
      </div>

      <div className="settings-setup-hero">
        <div>
          <span>模型目录</span>
          <strong>{simpleMode ? '选择一个模型方案。' : '选择厂商，也可以直接手动填写。'}</strong>
          <small>{simpleMode ? '选择方案，完成授权，然后测试连接；连接参数保留在高级模式。' : '推荐只负责筛选目录；Base URL、Model 和 API Key 始终可编辑。'}</small>
        </div>
        <div className={`settings-readiness-pill ${authReady ? 'ok' : 'warn'}`}>
          {authReady ? <CheckCircle2 size={16} /> : <CircleAlert size={16} />}
          {readinessLabel}
        </div>
      </div>

      <div className="settings-directory-layout">
        <aside className="settings-directory-panel" aria-label="厂商和模型目录">
          <label className="settings-search-field">
            <Search size={16} />
            <input
              value={catalogSearch}
              onChange={(event) => setCatalogSearch(event.target.value)}
              placeholder="搜索厂商、模型、Base URL"
            />
          </label>
          <div className="settings-filter-row" aria-label="模型目录筛选">
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
          <div className="settings-catalog-list">
            {catalogFilter !== 'saved' ? (
              <button type="button" className="settings-catalog-item manual" onClick={applyCustomModel}>
                <span>手动添加</span>
                <strong>OpenAI-compatible 模型</strong>
                <small>自己填写任意厂商的 Base URL、Model 和 API Key。</small>
                <em>自定义</em>
              </button>
            ) : null}
            {visibleSavedProfiles.map((profile) => (
              <button
                type="button"
                className={`settings-catalog-item saved ${profile.id === activeApiProfileId ? 'selected' : ''}`}
                key={profile.id}
                onClick={() => onApplySavedApiProfile(profile.id)}
              >
                <span>我的模型</span>
                <strong>{profile.label}</strong>
                <small>
                  {profile.provider} · {profile.model || '未填写模型'} ·{' '}
                  {profile.auth === 'gcloud'
                    ? 'gcloud OAuth'
                    : profile.auth === 'local_oauth'
                      ? 'Hermes 本机 OAuth'
                      : profile.has_api_key
                        ? '已保存 Key'
                        : '未保存 Key'}
                </small>
                <em>已保存</em>
              </button>
            ))}
            {visiblePresets.map((preset) => (
              <button
                type="button"
                className={`settings-catalog-item ${getApiPresetTone(preset)} ${!activeSavedProfile && isPresetSelected(preset) ? 'selected' : ''}`}
                key={preset.id}
                onClick={() => onApplyApiPreset(preset)}
              >
                <span>{preset.provider}</span>
                <strong>{preset.label}</strong>
                <small>
                  {preset.model || '手动填写模型'} · {preset.base_url || '原生端点'}
                </small>
                <em>{preset.key_hint}</em>
              </button>
            ))}
            {catalogEmpty ? <div className="settings-catalog-empty">没有找到匹配的厂商或模型。</div> : null}
          </div>
        </aside>

        <div className="settings-config-panel">
          <div className="settings-current-main">
            <span>当前配置</span>
            <strong>{currentModelTitle}</strong>
            <small>{currentModelMeta}</small>
          </div>
          <div className={`settings-profile-status ${apiProfileDirty ? 'warn' : 'ok'}`}>
            <span>{apiProfileStatus}</span>
            <small>
              {usesHermesLocal
                ? 'Hermes 使用本机 xAI OAuth；应用不读取或保存真实 xAI Token。'
                : apiConfig.provider === 'gemini-vertex'
                  ? 'Vertex 使用本机 gcloud OAuth，不保存 API Key。'
                  : '保存后 Key 只绑定当前模型，不会共享给其他厂商。'}
            </small>
          </div>
          <div className="api-grid settings-direct-config-grid">
            <label className="field settings-provider-field">
              <span>Provider</span>
              <select value={apiConfig.provider} onChange={(event) => handleProviderChange(event.target.value as Provider)}>
                <option value="local">预览模式（不可正式制卡）</option>
                <option value="mimo">MIMO / 小米</option>
                <option value="openai-compatible">OpenAI-compatible</option>
                <option value="claude">Claude 原生</option>
                <option value="gemini">Gemini 原生</option>
                <option value="gemini-vertex">Gemini Vertex</option>
              </select>
            </label>
            <label className="field settings-long-field">
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
            </label>
            <label className="field settings-long-field">
              <span>Model</span>
              <input
                aria-label="Model"
                value={apiConfig.model}
                onChange={(event) => onPatchApi({ model: event.target.value })}
                list="api-text-models"
                placeholder={
                  apiConfig.provider === 'mimo'
                    ? 'mimo-v2.5-pro'
                    : apiConfig.provider === 'gemini-vertex'
                      ? GEMINI_VERTEX_DEFAULT_MODEL
                      : 'deepseek-v4-pro'
                }
              />
              <datalist id="api-text-models">
                {mimoTextModels.map((model) => (
                  <option key={model.value} value={model.value}>
                    {model.label}
                  </option>
                ))}
              </datalist>
            </label>
            {usesHermesLocal ? (
              <div className="settings-auth-card settings-auth-card-compact" role="status" aria-label="Hermes 本机代理状态">
                <PlugZap size={18} />
                <div>
                  <span>Hermes 本机 OAuth</span>
                  <strong>{hermesStatus?.state === 'ready' ? 'Grok 4.5 已就绪' : '等待本机代理'}</strong>
                  <small>{hermesStatus?.message ?? '点击检测状态；测试连接时也会按需启动 Hermes 代理。'}</small>
                  <div className="settings-inline-actions">
                    <button type="button" className="secondary-button" onClick={onCheckHermes} disabled={hermesChecking || appBusy}>
                      {hermesChecking ? '检测中…' : '检测状态'}
                    </button>
                    <button type="button" className="secondary-button" onClick={onStartHermes} disabled={hermesStarting || appBusy}>
                      {hermesStarting ? '启动中…' : hermesStatus?.state === 'ready' ? '重新检测' : '启动代理'}
                    </button>
                  </div>
                </div>
              </div>
            ) : apiConfig.provider === 'gemini-vertex' ? (
              <div className="settings-auth-card settings-auth-card-compact">
                <Cloud size={18} />
                <div>
                  <span>Vertex 授权</span>
                  <strong>使用本机 gcloud OAuth</strong>
                  <small>不需要填写 API Key；测试连接会检查 gcloud 登录、项目权限、模型名和区域端点。</small>
                </div>
              </div>
            ) : (
              <label className="field settings-key-field">
                <span>API Key</span>
                <input
                  type="password"
                  value={apiConfig.api_key}
                  onChange={(event) => onPatchApi({ api_key: event.target.value })}
                  placeholder={
                    apiKeySaved
                      ? '已保存到系统凭据，留空会自动使用'
                      : apiConfig.provider === 'mimo'
                        ? 'sk-... / tp-...'
                        : 'sk-...'
                  }
                />
                <small>点击“保存模型方案”后保存到本机系统凭据 / DPAPI。</small>
              </label>
            )}
          </div>
          <div className="settings-config-actions">
            <button className="primary-button settings-save-button" type="button" onClick={onSaveApiProfile} disabled={appBusy}>
              <Save size={17} />
              保存模型方案
            </button>
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
        </div>
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

      <details className="settings-disclosure">
        <summary>
          <span>高级说明</span>
          <strong>安全 / 费用 / 自定义厂商</strong>
        </summary>
        <div className="settings-callout">
          <PlugZap size={18} />
          <div>
            <strong>目录只是帮你填表，不会锁死配置。</strong>
            <p>选择任意厂商后仍可继续修改 Base URL、Model 和能力标签；其他兼容 OpenAI API 的服务商直接选自定义。</p>
          </div>
        </div>
        <div className="settings-callout risk-callout">
          <CircleAlert size={18} />
          <div>
            <strong>字幕、学习点和卡片字段会发送给你选择的模型服务商。</strong>
            <p>API Key 保存到本机凭据；界面只显示“已保存”，不会长期回显明文。</p>
          </div>
        </div>
      </details>
    </section>
  )
}
