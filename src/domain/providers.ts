import type { ApiPreset } from './types'

export const MIMO_OPENAI_BASE_URL = 'https://api.xiaomimimo.com/v1'
export const MIMO_TOKEN_PLAN_CN_BASE_URL = 'https://token-plan-cn.xiaomimimo.com/v1'
export const MIMO_TOKEN_PLAN_SGP_BASE_URL = 'https://token-plan-sgp.xiaomimimo.com/v1'
export const MIMO_TOKEN_PLAN_SGP_ANTHROPIC_BASE_URL = 'https://token-plan-sgp.xiaomimimo.com/anthropic'
export const QWEN_DASHSCOPE_CN_COMPATIBLE_BASE_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
export const QWEN_DASHSCOPE_INTL_COMPATIBLE_BASE_URL = 'https://dashscope-intl.aliyuncs.com/compatible-mode/v1'
export const DEEPSEEK_OPENAI_BASE_URL = 'https://api.deepseek.com'
export const DEEPSEEK_DEFAULT_MODEL = 'deepseek-v4-pro'
export const GEMINI_VERTEX_GLOBAL_BASE_URL = 'https://aiplatform.googleapis.com'
export const GEMINI_VERTEX_DEFAULT_MODEL = 'gemini-3.1-pro-preview'
export const GEMINI_VERTEX_UNAVAILABLE_MODEL_ALIASES = new Set(['gemini-3.1-pro'])

export const mimoTextModels = [
  { value: 'mimo-v2.5-pro', label: 'MiMo-V2.5-Pro' },
  { value: 'mimo-v2.5', label: 'MiMo-V2.5' },
  { value: 'mimo-v2-pro', label: 'MiMo-V2-Pro' },
  { value: 'mimo-v2-omni', label: 'MiMo-V2-Omni' },
]

export const qwenTextModels = [
  { value: 'qwen3.7-max', label: 'Qwen3.7-Max' },
  { value: 'qwen3-max', label: 'Qwen3-Max' },
  { value: 'qwen3.6-plus', label: 'Qwen3.6-Plus' },
  { value: 'qwen-plus', label: 'Qwen Plus' },
  { value: 'qwen-max', label: 'Qwen Max' },
  { value: 'qwen-flash', label: 'Qwen Flash' },
]

export const deepseekTextModels = [
  { value: DEEPSEEK_DEFAULT_MODEL, label: 'DeepSeek V4 Pro' },
  { value: 'deepseek-v4-flash', label: 'DeepSeek V4 Flash' },
]

export const geminiVertexTextModels = [
  { value: GEMINI_VERTEX_DEFAULT_MODEL, label: 'Gemini 3.1 Pro Preview' },
  { value: 'gemini-2.5-pro', label: 'Gemini 2.5 Pro' },
  { value: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash' },
]

export const capabilityLabels = ['structured_json', 'long_context', 'tts', 'asr', 'vision', 'omni', 'cheap_batch']

export const capabilityHelp: Record<string, string> = {
  structured_json: '能稳定返回 JSON，生成卡片字段更不容易乱。',
  long_context: '能处理更长字幕片段，适合一整集分块分析。',
  tts: '支持语音合成，可在导出时额外生成 AI 朗读音频。',
  asr: '后续用于无字幕视频识别，V1 暂未开放。',
  vision: '后续可结合画面理解剧情，V1 暂未开放。',
  omni: '支持图像、视频、音频等多模态理解；当前先保留为能力标签。',
  cheap_batch: '适合批量便宜生成，质量通常需要人工抽查。',
}

export const apiPresets: ApiPreset[] = [
  {
    id: 'local',
    label: '预览模式',
    provider: 'local',
    base_url: '',
    model: 'local-fallback',
    capabilities: ['structured_json'],
    note: '不用 API Key，只用于浏览器演示和流程预览；正式抽取学习点与制卡必须配置模型 API。',
    key_hint: '不需要填写',
  },
  {
    id: 'mimo-token-plan-sgp',
    label: 'MIMO Token Plan SGP',
    provider: 'mimo',
    base_url: MIMO_TOKEN_PLAN_SGP_BASE_URL,
    model: 'mimo-v2.5-pro',
    capabilities: ['structured_json', 'long_context'],
    note: '新加坡 Token Plan 专属 OpenAI 兼容端点；你的 tp-... Key 优先选这个。',
    key_hint: 'Token Plan 专属 API Key，通常是 tp-...',
  },
  {
    id: 'mimo-token-plan-sgp-anthropic',
    label: 'MIMO SGP Anthropic',
    provider: 'claude',
    base_url: MIMO_TOKEN_PLAN_SGP_ANTHROPIC_BASE_URL,
    model: 'mimo-v2.5-pro',
    capabilities: ['structured_json', 'long_context'],
    note: '兼容 Anthropic 协议的 Token Plan 端点；适合 Claude Code/OpenCode 类接口。',
    key_hint: 'Token Plan 专属 API Key，通常是 tp-...',
  },
  {
    id: 'mimo-v25-pro',
    label: 'MIMO Public V2.5 Pro',
    provider: 'mimo',
    base_url: MIMO_OPENAI_BASE_URL,
    model: 'mimo-v2.5-pro',
    capabilities: ['structured_json', 'long_context'],
    note: '小米 MiMo 旗舰文本/Agent 模型，适合高质量解释、长字幕和复杂筛选。',
    key_hint: 'MiMo API Key，sk-... 或 Token Plan 的 tp-...',
  },
  {
    id: 'mimo-v25',
    label: 'MIMO V2.5 Omni',
    provider: 'mimo',
    base_url: MIMO_OPENAI_BASE_URL,
    model: 'mimo-v2.5',
    capabilities: ['structured_json', 'long_context', 'vision', 'asr', 'omni'],
    note: '小米 MiMo V2.5 全模态模型；V1 先用于文本制卡，后续可接图像/音频理解。',
    key_hint: 'MiMo API Key，sk-... 或 tp-...',
  },
  {
    id: 'mimo-token-plan-cn',
    label: 'MIMO Token Plan',
    provider: 'mimo',
    base_url: MIMO_TOKEN_PLAN_CN_BASE_URL,
    model: 'mimo-v2.5-pro',
    capabilities: ['structured_json', 'long_context'],
    note: '套餐用户可用；如果控制台给了新加坡/欧洲专属端点，直接改 Base URL。',
    key_hint: 'Token Plan Key，通常是 tp-...',
  },
  {
    id: 'gemini-31-pro-preview-vertex',
    label: 'Gemini 3.1 Pro Preview Vertex',
    provider: 'gemini-vertex',
    base_url: GEMINI_VERTEX_GLOBAL_BASE_URL,
    model: GEMINI_VERTEX_DEFAULT_MODEL,
    capabilities: ['structured_json', 'long_context'],
    note: '使用本机 gcloud 登录的 Vertex AI；当前项目实测 global 端点可调用，thinking 会保留。',
    key_hint: '不需要 API Key，先运行 gcloud auth login / 设置项目',
  },
  {
    id: 'deepseek-v4-pro',
    label: 'DeepSeek V4 Pro',
    provider: 'openai-compatible',
    base_url: DEEPSEEK_OPENAI_BASE_URL,
    model: DEEPSEEK_DEFAULT_MODEL,
    capabilities: ['structured_json', 'long_context'],
    note: 'DeepSeek 当前旗舰模型；默认保留 Thinking，适合高质量筛选、上下文理解和解释生成。',
    key_hint: 'DeepSeek 控制台里的 API Key',
  },
  {
    id: 'deepseek-v4-flash',
    label: 'DeepSeek V4 Flash',
    provider: 'openai-compatible',
    base_url: DEEPSEEK_OPENAI_BASE_URL,
    model: 'deepseek-v4-flash',
    capabilities: ['structured_json', 'long_context', 'cheap_batch'],
    note: 'DeepSeek V4 快速低成本模型；适合批量字幕生成，Thinking 同样会被流式处理。',
    key_hint: 'DeepSeek 控制台里的 API Key',
  },
  {
    id: 'qwen37-max-cn',
    label: 'Qwen3.7 Max',
    provider: 'openai-compatible',
    base_url: QWEN_DASHSCOPE_CN_COMPATIBLE_BASE_URL,
    model: 'qwen3.7-max',
    capabilities: ['structured_json', 'long_context'],
    note: '阿里云百炼北京地域 OpenAI 兼容端点；当前官方 Max 系列优先选这个。',
    key_hint: '北京地域 DashScope / 百炼 API Key',
  },
  {
    id: 'qwen36-plus-cn',
    label: 'Qwen3.6 Plus',
    provider: 'openai-compatible',
    base_url: QWEN_DASHSCOPE_CN_COMPATIBLE_BASE_URL,
    model: 'qwen3.6-plus',
    capabilities: ['structured_json', 'long_context', 'cheap_batch'],
    note: '质量和成本更均衡，适合批量生成字幕解释和文档卡字段。',
    key_hint: '北京地域 DashScope / 百炼 API Key',
  },
  {
    id: 'qwen',
    label: 'Qwen / 通义',
    provider: 'openai-compatible',
    base_url: QWEN_DASHSCOPE_CN_COMPATIBLE_BASE_URL,
    model: 'qwen-plus',
    capabilities: ['structured_json', 'long_context', 'cheap_batch'],
    note: '中文解释通常稳，适合中英双语卡片字段生成。',
    key_hint: 'DashScope API Key',
  },
  {
    id: 'qwen37-max-intl',
    label: 'Qwen3.7 Max Intl',
    provider: 'openai-compatible',
    base_url: QWEN_DASHSCOPE_INTL_COMPATIBLE_BASE_URL,
    model: 'qwen3.7-max',
    capabilities: ['structured_json', 'long_context'],
    note: '新加坡/国际地域 OpenAI 兼容端点；需要使用对应地域的 DashScope Key。',
    key_hint: '国际地域 DashScope API Key',
  },
  {
    id: 'kimi',
    label: 'Kimi / Moonshot',
    provider: 'openai-compatible',
    base_url: 'https://api.moonshot.cn/v1',
    model: 'moonshot-v1-32k',
    capabilities: ['structured_json', 'long_context'],
    note: '长上下文友好，适合字幕块较长时使用。',
    key_hint: 'Moonshot API Key',
  },
  {
    id: 'grok',
    label: 'Grok / xAI',
    provider: 'openai-compatible',
    base_url: 'https://api.x.ai/v1',
    model: 'grok-3-mini',
    capabilities: ['structured_json', 'long_context'],
    note: '这是 xAI 文本模型配置；Grok TTS 请在下方“语音 TTS”单独配置。',
    key_hint: 'xAI API Key',
  },
  {
    id: 'openrouter',
    label: 'OpenRouter',
    provider: 'openai-compatible',
    base_url: 'https://openrouter.ai/api/v1',
    model: 'anthropic/claude-3.5-sonnet',
    capabilities: ['structured_json', 'long_context'],
    note: '适合一个 Key 路由多个模型；模型名要填 OpenRouter 的完整 ID。',
    key_hint: 'OpenRouter API Key',
  },
  {
    id: 'custom-compatible',
    label: '自定义兼容',
    provider: 'openai-compatible',
    base_url: '',
    model: '',
    capabilities: ['structured_json', 'cheap_batch'],
    note: '其他 OpenAI-compatible 服务用这个；按服务商后台复制 Base URL、Model 和 Key。',
    key_hint: 'API Key',
  },
  {
    id: 'claude',
    label: 'Claude 原生',
    provider: 'claude',
    base_url: '',
    model: 'claude-3-5-sonnet-latest',
    capabilities: ['structured_json', 'long_context'],
    note: '解释质量通常好，适合追求更自然、更像老师的中文说明。',
    key_hint: 'Anthropic API Key',
  },
  {
    id: 'gemini',
    label: 'Gemini 原生',
    provider: 'gemini',
    base_url: '',
    model: 'gemini-2.5-flash',
    capabilities: ['structured_json', 'long_context'],
    note: '适合长字幕理解；Gemini TTS 请在下方“语音 TTS”单独配置。',
    key_hint: 'Gemini API Key',
  },
]

export const featuredApiPresetIds = new Set([
  'mimo-token-plan-sgp',
  'qwen37-max-cn',
  'deepseek-v4-pro',
  'deepseek-v4-flash',
  'custom-compatible',
])

export const featuredApiPresets = apiPresets.filter((preset) => featuredApiPresetIds.has(preset.id))
export const advancedApiPresets = apiPresets.filter((preset) => !featuredApiPresetIds.has(preset.id))
