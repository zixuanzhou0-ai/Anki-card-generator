import type { ApiPreset, CardKind, ContentToggles, GenerateRequest, Level, TemplateId, TtsPreset } from './types'

export const MIMO_OPENAI_BASE_URL = 'https://api.xiaomimimo.com/v1'
export const MIMO_TOKEN_PLAN_CN_BASE_URL = 'https://token-plan-cn.xiaomimimo.com/v1'
export const MIMO_TOKEN_PLAN_SGP_BASE_URL = 'https://token-plan-sgp.xiaomimimo.com/v1'
export const MIMO_TOKEN_PLAN_SGP_ANTHROPIC_BASE_URL = 'https://token-plan-sgp.xiaomimimo.com/anthropic'
export const PROJECT_STORAGE_KEY = 'anki-card-generator:last-project'

export const mimoTextModels = [
  { value: 'mimo-v2.5-pro', label: 'MiMo-V2.5-Pro' },
  { value: 'mimo-v2.5', label: 'MiMo-V2.5' },
  { value: 'mimo-v2-pro', label: 'MiMo-V2-Pro' },
  { value: 'mimo-v2-omni', label: 'MiMo-V2-Omni' },
]

export const mimoTtsModels = [
  { value: 'mimo-v2.5-tts', label: 'MiMo-V2.5-TTS' },
  { value: 'mimo-v2.5-tts-voicedesign', label: 'MiMo-V2.5-TTS-VoiceDesign' },
  { value: 'mimo-v2.5-tts-voiceclone', label: 'MiMo-V2.5-TTS-VoiceClone' },
  { value: 'mimo-v2-tts', label: 'MiMo-V2-TTS' },
]

export const mimoTtsVoices = ['Mia', 'Chloe', 'Milo', 'Dean', 'mimo_default', '冰糖', '茉莉', '苏打', '白桦', 'default_en', 'default_zh']

export const levels: Array<{ id: Level; label: string; note: string }> = [
  { id: 'A1', label: 'A1 入门', note: '基础表达' },
  { id: 'A2', label: 'A2 基础', note: '短句高频' },
  { id: 'B1', label: 'B1 日常交流', note: '自然口语' },
  { id: 'B2', label: 'B2 独立表达', note: '表达块' },
  { id: 'C1', label: 'C1 高阶表达', note: '语气和隐含义' },
  { id: 'C2', label: 'C2 接近母语', note: '细微语域' },
]

export const levelOrder: Level[] = levels.map((level) => level.id)

export function defaultCollectionLevels(level: Level): Level[] {
  const index = Math.max(0, levelOrder.indexOf(level))
  const lower = Math.max(0, index - 1)
  return levelOrder.slice(lower, index + 1)
}

export function normalizeCollectionLevels(value: unknown, currentLevel: Level): Level[] {
  if (!Array.isArray(value)) return defaultCollectionLevels(currentLevel)
  const selected = value.filter((item): item is Level => levelOrder.includes(item as Level))
  const unique = Array.from(new Set(selected))
  return unique.length ? unique.sort((a, b) => levelOrder.indexOf(a) - levelOrder.indexOf(b)) : defaultCollectionLevels(currentLevel)
}

export const contentOptions: Array<{ key: keyof ContentToggles; label: string; defaultOn: boolean }> = [
  { key: 'daily', label: '日常表达', defaultOn: true },
  { key: 'slang', label: '俚语', defaultOn: true },
  { key: 'sarcasm', label: '吐槽 / 讽刺', defaultOn: true },
  { key: 'business', label: '职场表达', defaultOn: true },
  { key: 'culture', label: '文化梗', defaultOn: true },
  { key: 'profanity', label: '脏话 / 粗口', defaultOn: false },
  { key: 'romance', label: '暧昧 / 恋爱表达', defaultOn: false },
  { key: 'rare', label: '低频生僻表达', defaultOn: false },
]

export const cardOptions: Array<{ id: CardKind; label: string; note: string }> = [
  { id: 'listening', label: '听力卡', note: '先听原声，不显示字幕' },
  { id: 'phrase', label: '词伙卡', note: '释义、搭配、语境、中文感' },
  { id: 'cloze', label: '填空卡', note: '翻面后核对关键表达' },
]

export const templateOptions: Array<{ id: TemplateId; label: string; note: string; locked?: boolean }> = [
  { id: 'immersive', label: '沉浸语言 V10', note: '当前主力模板：视频、音频、答案重点优先' },
  { id: 'dictionary', label: '词典解释', note: '下一轮打磨，暂不开放', locked: true },
  { id: 'minimal', label: '极简复习', note: '下一轮打磨，暂不开放', locked: true },
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
    label: '本地草稿',
    provider: 'local',
    base_url: '',
    model: 'local-fallback',
    capabilities: ['structured_json'],
    note: '不用 API Key，先用本地规则生成草稿，适合测试流程。',
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
    id: 'deepseek',
    label: 'DeepSeek',
    provider: 'openai-compatible',
    base_url: 'https://api.deepseek.com/v1',
    model: 'deepseek-chat',
    capabilities: ['structured_json', 'long_context', 'cheap_batch'],
    note: '推荐作为入门默认项：成本友好，适合批量生成解释草稿。',
    key_hint: 'DeepSeek 控制台里的 API Key',
  },
  {
    id: 'qwen',
    label: 'Qwen / 通义',
    provider: 'openai-compatible',
    base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    model: 'qwen-plus',
    capabilities: ['structured_json', 'long_context', 'cheap_batch'],
    note: '中文解释通常稳，适合中英双语卡片字段生成。',
    key_hint: 'DashScope API Key',
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

export const ttsPresets: TtsPreset[] = [
  {
    id: 'disabled',
    label: '关闭 TTS',
    provider: 'disabled',
    base_url: '',
    model: '',
    voice: '',
    note: '只使用视频原声音频，不额外生成 AI 朗读。',
    key_hint: '不需要填写',
  },
  {
    id: 'mimo-token-plan-sgp-tts',
    label: 'MIMO SGP TTS',
    provider: 'mimo',
    base_url: MIMO_TOKEN_PLAN_SGP_BASE_URL,
    model: 'mimo-v2.5-tts',
    voice: 'Mia',
    note: '新加坡 Token Plan 专属 TTS；走 /chat/completions + audio，不是 /audio/speech。',
    key_hint: 'Token Plan 专属 API Key，通常是 tp-...',
  },
  {
    id: 'mimo-v25-tts',
    label: 'MIMO V2.5 TTS',
    provider: 'mimo',
    base_url: MIMO_OPENAI_BASE_URL,
    model: 'mimo-v2.5-tts',
    voice: 'Mia',
    note: '小米 MiMo V2.5 基础语音合成；支持 Mia、Chloe、Milo、Dean 等内置声音。',
    key_hint: '公共平台 Key，通常是 sk-...；tp- Key 请选 SGP TTS。',
  },
  {
    id: 'mimo-v25-voice-design',
    label: 'MIMO VoiceDesign',
    provider: 'mimo',
    base_url: MIMO_OPENAI_BASE_URL,
    model: 'mimo-v2.5-tts-voicedesign',
    voice: 'A warm, clear English teacher voice with natural pacing.',
    note: 'MiMo V2.5 声音设计模型；Voice 栏填写声音描述，不填内置 voice_id。',
    key_hint: 'MiMo API Key',
  },
  {
    id: 'mimo-v25-voice-clone',
    label: 'MIMO VoiceClone',
    provider: 'mimo',
    base_url: MIMO_OPENAI_BASE_URL,
    model: 'mimo-v2.5-tts-voiceclone',
    voice: 'mimo_default',
    note: 'MiMo V2.5 声音克隆模型；当前先保留模型入口，参考平台要求填 voice。',
    key_hint: 'MiMo API Key',
  },
  {
    id: 'mimo-v2-tts',
    label: 'MIMO V2 TTS',
    provider: 'mimo',
    base_url: MIMO_OPENAI_BASE_URL,
    model: 'mimo-v2-tts',
    voice: 'default_en',
    note: 'MiMo V2 语音合成模型，适合旧套餐；常用 default_en、default_zh、mimo_default。',
    key_hint: 'MiMo API Key',
  },
  {
    id: 'grok',
    label: 'Grok / xAI TTS',
    provider: 'grok',
    base_url: 'https://api.x.ai/v1',
    model: '',
    voice: 'eve',
    note: '单独填写 xAI API Key；Grok TTS 使用 voice_id，例如 eve、ara、leo、rex、sal。',
    key_hint: 'xAI API Key',
  },
  {
    id: 'gemini-tts',
    label: 'Gemini TTS',
    provider: 'gemini',
    base_url: '',
    model: 'gemini-2.5-flash-preview-tts',
    voice: 'Kore',
    note: '单独填写 Gemini API Key；模型和声音按 Google AI Studio 后台调整。',
    key_hint: 'Gemini API Key',
  },
  {
    id: 'openai-speech',
    label: 'OpenAI-compatible Speech',
    provider: 'openai-compatible',
    base_url: 'https://api.openai.com/v1',
    model: 'gpt-4o-mini-tts',
    voice: 'alloy',
    note: '适配 /audio/speech 兼容接口；也可填 Groq 等服务商的 speech Base URL。',
    key_hint: 'Speech API Key',
  },
]

export const featuredApiPresetIds = new Set(['mimo-token-plan-sgp', 'deepseek', 'custom-compatible'])
export const featuredTtsPresetIds = new Set(['disabled', 'mimo-token-plan-sgp-tts', 'grok', 'gemini-tts'])

export const featuredApiPresets = apiPresets.filter((preset) => featuredApiPresetIds.has(preset.id))
export const advancedApiPresets = apiPresets.filter((preset) => !featuredApiPresetIds.has(preset.id))
export const featuredTtsPresets = ttsPresets.filter((preset) => featuredTtsPresetIds.has(preset.id))
export const advancedTtsPresets = ttsPresets.filter((preset) => !featuredTtsPresetIds.has(preset.id))

export const defaultToggles = contentOptions.reduce((result, item) => {
  result[item.key] = item.defaultOn
  return result
}, {} as ContentToggles)

export const defaultRequest: GenerateRequest = {
  title: '',
  source_mode: 'local',
  source_url: '',
  url_import_mode: 'video',
  url_auto_subtitle_fallback: true,
  skip_video_slicing: false,
  video_path: '',
  subtitle_path: '',
  document_path: '',
  language: 'English',
  level: 'B1',
  collection_levels: defaultCollectionLevels('B1'),
  template_id: 'immersive',
  content_toggles: defaultToggles,
  card_types: ['listening', 'phrase', 'cloze'],
  max_segments: 0,
  api_config: {
    provider: 'openai-compatible',
    base_url: 'https://api.deepseek.com/v1',
    api_key: '',
    model: 'deepseek-chat',
    capabilities: ['structured_json', 'long_context'],
    tts_config: {
      enabled: false,
      provider: 'grok',
      base_url: 'https://api.x.ai/v1',
      api_key: '',
      model: '',
      voice: 'eve',
      language: 'auto',
      sample_rate: 24000,
      bit_rate: 128000,
    },
  },
}

export const REQUEST_STORAGE_KEY = 'anki-card-generator.request.v1'
export const SECRET_PREFS_STORAGE_KEY = 'anki-card-generator.secret-prefs.v1'
