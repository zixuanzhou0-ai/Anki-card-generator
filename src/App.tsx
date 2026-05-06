import { useEffect, useMemo, useRef, useState } from 'react'
import type { ChangeEvent, MouseEvent, SyntheticEvent } from 'react'
import { convertFileSrc, invoke } from '@tauri-apps/api/core'
import { listen } from '@tauri-apps/api/event'
import { open as openDialog } from '@tauri-apps/plugin-dialog'
import { getCurrentWindow } from '@tauri-apps/api/window'
import {
  Boxes,
  CheckCircle2,
  CircleAlert,
  CircleDot,
  Download,
  ExternalLink,
  FileText,
  Film,
  FolderOpen,
  KeyRound,
  Languages,
  Layers3,
  Link2,
  Loader2,
  MessageSquareText,
  Minus,
  PlugZap,
  Play,
  Settings2,
  Square,
  Sparkles,
  Subtitles,
  Wand2,
  X,
} from 'lucide-react'

type Level = 'A1' | 'A2' | 'B1' | 'B2' | 'C1' | 'C2'
type CardKind = 'listening' | 'phrase' | 'cloze' | 'knowledge'
type TemplateId = 'immersive' | 'dictionary' | 'minimal'
type Provider = 'local' | 'mimo' | 'openai-compatible' | 'claude' | 'gemini'
type TtsProvider = 'disabled' | 'mimo' | 'grok' | 'gemini' | 'openai-compatible'
type SourceMode = 'local' | 'url' | 'document'
type UrlImportMode = 'video' | 'subtitles'
type SettingsTab = 'api' | 'tts' | 'env'
type SegmentFilter = 'all' | 'recommended' | 'needs_review' | 'reject' | 'duplicate'
type PhraseReviewStatus = 'recommended' | 'needs_review' | 'reject' | 'duplicate' | 'unreviewed' | string
type ResizeDirection =
  | 'East'
  | 'North'
  | 'NorthEast'
  | 'NorthWest'
  | 'South'
  | 'SouthEast'
  | 'SouthWest'
  | 'West'

type ContentToggles = {
  daily: boolean
  slang: boolean
  sarcasm: boolean
  business: boolean
  culture: boolean
  profanity: boolean
  romance: boolean
  rare: boolean
}

type ApiConfig = {
  provider: Provider
  base_url: string
  api_key: string
  model: string
  capabilities: string[]
  tts_provider?: string
  tts_model?: string
  tts_config: TtsConfig
}

type TtsConfig = {
  enabled: boolean
  provider: TtsProvider
  base_url: string
  api_key: string
  model: string
  voice: string
  language: string
  sample_rate: number
  bit_rate: number
}

type ApiPreset = {
  id: string
  label: string
  provider: Provider
  base_url: string
  model: string
  capabilities: string[]
  note: string
  key_hint: string
}

type TtsPreset = {
  id: string
  label: string
  provider: TtsProvider
  base_url: string
  model: string
  voice: string
  note: string
  key_hint: string
}

type ApiTestResult = {
  ok: boolean
  provider: string
  model: string
  message: string
  latency_ms?: number
}

type TtsTestResult = {
  ok: boolean
  provider: string
  model: string
  voice: string
  message: string
  latency_ms?: number
  bytes?: number
}

type ExportResult = {
  apkg_path: string
  media_dir: string
  deck_name?: string
  media_prefix?: string
  media_manifest?: Record<string, { sha256: string; bytes: number }>
  cards: number
  segments: number
  media_summary?: {
    video_segments: number
    video_files: number
    original_audio_files: number
    sentence_tts_files: number
    phrase_tts_files: number
    media_files: number
    media_bytes: number
    media_mb: number
  }
  warnings?: string[]
}

type AnkiVerifyResult = {
  ok: boolean
  message: string
  failed_checks: string[]
  deck_name?: string
  card_count?: number
  expected_cards?: number | null
  media_count_expected?: number
  media_count_referenced?: number
  media_count_checked?: number
  missing_media?: string[]
  mismatched_media?: Array<{ file: string; expected_sha256: string; actual_sha256: string }>
  unexpected_media_references?: string[]
  unreferenced_expected_media?: string[]
}

type WorkerProgress = {
  command: string
  stage: string
  percent: number
  message: string
}

type EnvStatusItem = {
  id: string
  label: string
  status: 'ok' | 'action' | 'blocked'
  detail: string
  fix?: string
}

type GenerateRequest = {
  title: string
  source_mode: SourceMode
  source_url: string
  url_import_mode: UrlImportMode
  url_auto_subtitle_fallback: boolean
  skip_video_slicing: boolean
  video_path: string
  subtitle_path: string
  document_path: string
  language: string
  level: Level
  collection_levels: Level[]
  template_id: TemplateId
  content_toggles: ContentToggles
  card_types: CardKind[]
  max_segments: number
  api_config: ApiConfig
}

type Card = {
  id: string
  type: CardKind
  type_label: string
  enabled: boolean
  card_role?: 'primary' | 'specialist' | string
  learning_goal?: string
  decision_reason?: string
  skipped_card_types?: Record<string, string>
  phrase_value_score?: number | string | null
  phrase_decision_reason?: string
  phrase_reject_reason?: string
  phrase_card_focus?: string
  phrase_review_status?: PhraseReviewStatus
  english: string
  chinese: string
  phrase: string
  definition: string
  collocations: string
  context: string
  example: string
  chinese_feel: string
  why: string
  difficulty: string
  teacher_note: string
  cloze: string
  quality?: {
    score: number
    status: 'recommended' | 'needs_review' | 'reject'
    issues: string[]
  }
}

type Segment = {
  id: string
  start: number
  end: number
  media_start?: number
  media_end?: number
  media_source_time?: string
  source_time: string
  text: string
  duration: number
  recommendation: number
  phrase: string
  phrase_value_score?: number | string | null
  phrase_decision_reason?: string
  phrase_reject_reason?: string
  phrase_card_focus?: string
  phrase_review_status?: PhraseReviewStatus
  phrase_review_source?: string
  cards: Card[]
}

type Project = {
  id: string
  title: string
  source_mode?: SourceMode
  source_url?: string
  source_info?: {
    title?: string
    webpage_url?: string
    duration?: number
    uploader?: string
    download_dir?: string
  } | null
  video_path: string
  subtitle_path: string
  document_path?: string
  language: string
  level: Level
  collection_levels?: Level[]
  template_id: TemplateId
  content_toggles: ContentToggles
  card_types: CardKind[]
  max_segments?: number
  auto_max_segments?: boolean
  skip_video_slicing?: boolean
  segments: Segment[]
  warning?: string | null
  created_at: number
}

type EnvStatus = {
  python?: string
  python_executable?: string
  venv?: boolean
  ffmpeg?: boolean
  ffmpeg_path?: string
  ffmpeg_version?: string
  genanki?: boolean
  yt_dlp?: boolean
  yt_dlp_version?: string
  yt_dlp_js_runtime?: string
  anki_connect?: boolean
  anki_connect_detail?: string
  packages?: Record<string, string>
  status_items?: EnvStatusItem[]
  worker?: string
}

type SecretPrefs = {
  rememberModelKey: boolean
  rememberTtsKey: boolean
}

const MIMO_OPENAI_BASE_URL = 'https://api.xiaomimimo.com/v1'
const MIMO_TOKEN_PLAN_CN_BASE_URL = 'https://token-plan-cn.xiaomimimo.com/v1'
const MIMO_TOKEN_PLAN_SGP_BASE_URL = 'https://token-plan-sgp.xiaomimimo.com/v1'
const MIMO_TOKEN_PLAN_SGP_ANTHROPIC_BASE_URL = 'https://token-plan-sgp.xiaomimimo.com/anthropic'
const PROJECT_STORAGE_KEY = 'anki-card-generator:last-project'

const mimoTextModels = [
  { value: 'mimo-v2.5-pro', label: 'MiMo-V2.5-Pro' },
  { value: 'mimo-v2.5', label: 'MiMo-V2.5' },
  { value: 'mimo-v2-pro', label: 'MiMo-V2-Pro' },
  { value: 'mimo-v2-omni', label: 'MiMo-V2-Omni' },
]

const mimoTtsModels = [
  { value: 'mimo-v2.5-tts', label: 'MiMo-V2.5-TTS' },
  { value: 'mimo-v2.5-tts-voicedesign', label: 'MiMo-V2.5-TTS-VoiceDesign' },
  { value: 'mimo-v2.5-tts-voiceclone', label: 'MiMo-V2.5-TTS-VoiceClone' },
  { value: 'mimo-v2-tts', label: 'MiMo-V2-TTS' },
]

const mimoTtsVoices = ['Mia', 'Chloe', 'Milo', 'Dean', 'mimo_default', '冰糖', '茉莉', '苏打', '白桦', 'default_en', 'default_zh']

const levels: Array<{ id: Level; label: string; note: string }> = [
  { id: 'A1', label: 'A1 入门', note: '基础表达' },
  { id: 'A2', label: 'A2 基础', note: '短句高频' },
  { id: 'B1', label: 'B1 日常交流', note: '自然口语' },
  { id: 'B2', label: 'B2 独立表达', note: '表达块' },
  { id: 'C1', label: 'C1 高阶表达', note: '语气和隐含义' },
  { id: 'C2', label: 'C2 接近母语', note: '细微语域' },
]

const levelOrder: Level[] = levels.map((level) => level.id)

function defaultCollectionLevels(level: Level): Level[] {
  const index = Math.max(0, levelOrder.indexOf(level))
  const lower = Math.max(0, index - 1)
  return levelOrder.slice(lower, index + 1)
}

function normalizeCollectionLevels(value: unknown, currentLevel: Level): Level[] {
  if (!Array.isArray(value)) return defaultCollectionLevels(currentLevel)
  const selected = value.filter((item): item is Level => levelOrder.includes(item as Level))
  const unique = Array.from(new Set(selected))
  return unique.length ? unique.sort((a, b) => levelOrder.indexOf(a) - levelOrder.indexOf(b)) : defaultCollectionLevels(currentLevel)
}

const contentOptions: Array<{ key: keyof ContentToggles; label: string; defaultOn: boolean }> = [
  { key: 'daily', label: '日常表达', defaultOn: true },
  { key: 'slang', label: '俚语', defaultOn: true },
  { key: 'sarcasm', label: '吐槽 / 讽刺', defaultOn: true },
  { key: 'business', label: '职场表达', defaultOn: true },
  { key: 'culture', label: '文化梗', defaultOn: true },
  { key: 'profanity', label: '脏话 / 粗口', defaultOn: false },
  { key: 'romance', label: '暧昧 / 恋爱表达', defaultOn: false },
  { key: 'rare', label: '低频生僻表达', defaultOn: false },
]

const cardOptions: Array<{ id: CardKind; label: string; note: string }> = [
  { id: 'listening', label: '听力卡', note: '先听原声，不显示字幕' },
  { id: 'phrase', label: '词伙卡', note: '释义、搭配、语境、中文感' },
  { id: 'cloze', label: '填空卡', note: '翻面后核对关键表达' },
]

const templateOptions: Array<{ id: TemplateId; label: string; note: string; locked?: boolean }> = [
  { id: 'immersive', label: '沉浸语言 V9', note: '当前主力模板：视频、音频、答案重点优先' },
  { id: 'dictionary', label: '词典解释', note: '下一轮打磨，暂不开放', locked: true },
  { id: 'minimal', label: '极简复习', note: '下一轮打磨，暂不开放', locked: true },
]

const capabilityLabels = ['structured_json', 'long_context', 'tts', 'asr', 'vision', 'omni', 'cheap_batch']

const capabilityHelp: Record<string, string> = {
  structured_json: '能稳定返回 JSON，生成卡片字段更不容易乱。',
  long_context: '能处理更长字幕片段，适合一整集分块分析。',
  tts: '支持语音合成，可在导出时额外生成 AI 朗读音频。',
  asr: '后续用于无字幕视频识别，V1 暂未开放。',
  vision: '后续可结合画面理解剧情，V1 暂未开放。',
  omni: '支持图像、视频、音频等多模态理解；当前先保留为能力标签。',
  cheap_batch: '适合批量便宜生成，质量通常需要人工抽查。',
}

const apiPresets: ApiPreset[] = [
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

const ttsPresets: TtsPreset[] = [
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

const featuredApiPresetIds = new Set(['mimo-token-plan-sgp', 'deepseek', 'custom-compatible'])
const featuredTtsPresetIds = new Set(['disabled', 'mimo-token-plan-sgp-tts', 'grok', 'gemini-tts'])

const featuredApiPresets = apiPresets.filter((preset) => featuredApiPresetIds.has(preset.id))
const advancedApiPresets = apiPresets.filter((preset) => !featuredApiPresetIds.has(preset.id))
const featuredTtsPresets = ttsPresets.filter((preset) => featuredTtsPresetIds.has(preset.id))
const advancedTtsPresets = ttsPresets.filter((preset) => !featuredTtsPresetIds.has(preset.id))

const defaultToggles = contentOptions.reduce((result, item) => {
  result[item.key] = item.defaultOn
  return result
}, {} as ContentToggles)

const defaultRequest: GenerateRequest = {
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

const REQUEST_STORAGE_KEY = 'anki-card-generator.request.v1'
const SECRET_PREFS_STORAGE_KEY = 'anki-card-generator.secret-prefs.v1'

function isTauriRuntime() {
  return Boolean((window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__)
}

function normalizeMimoModelId(value: string) {
  const trimmed = value.trim()
  return trimmed.toLowerCase().startsWith('mimo-') ? trimmed.toLowerCase() : trimmed
}

function isMimoTokenPlanKey(value: string) {
  return value.trim().toLowerCase().startsWith('tp-')
}

function isMimoTokenPlanBase(value: string) {
  return value.trim().toLowerCase().includes('token-plan-')
}

function isMimoApiConfig(api: ApiConfig) {
  return api.provider === 'mimo' || api.base_url.toLowerCase().includes('xiaomimimo.com')
}

function resolveTtsConfig(tts: TtsConfig, api: ApiConfig): TtsConfig {
  if (tts.provider !== 'mimo') return tts

  const canReuseMainMimo = isMimoApiConfig(api) && api.api_key.trim()
  const mainApiKey = canReuseMainMimo ? api.api_key.trim() : ''
  const explicitTtsKey = tts.api_key.trim()
  const staleTokenPlanTtsKey =
    mainApiKey &&
    isMimoTokenPlanKey(mainApiKey) &&
    isMimoTokenPlanKey(explicitTtsKey) &&
    explicitTtsKey !== mainApiKey
  const apiKey = staleTokenPlanTtsKey ? mainApiKey : explicitTtsKey || mainApiKey
  let baseUrl = tts.base_url.trim()

  if (!baseUrl && canReuseMainMimo) {
    baseUrl = api.base_url.trim()
  }
  if (!baseUrl) {
    baseUrl = isMimoTokenPlanKey(apiKey) ? MIMO_TOKEN_PLAN_SGP_BASE_URL : MIMO_OPENAI_BASE_URL
  }
  if (isMimoTokenPlanKey(apiKey) && !isMimoTokenPlanBase(baseUrl)) {
    baseUrl = MIMO_TOKEN_PLAN_SGP_BASE_URL
  }

  return {
    ...tts,
    api_key: apiKey,
    base_url: baseUrl,
    model: normalizeMimoModelId(tts.model || 'mimo-v2.5-tts'),
    voice: tts.voice || 'Mia',
  }
}

function normalizeSavedMimoConfig(saved: GenerateRequest): GenerateRequest {
  const apiBase = saved.api_config.base_url.toLowerCase()
  const isMimoText = saved.api_config.provider === 'mimo' || apiBase.includes('xiaomimimo.com')
  const ttsBase = saved.api_config.tts_config.base_url.toLowerCase()
  const isMimoTts = saved.api_config.tts_config.provider === 'mimo' || ttsBase.includes('xiaomimimo.com')

  return {
    ...saved,
    api_config: {
      ...saved.api_config,
      model: isMimoText ? normalizeMimoModelId(saved.api_config.model) : saved.api_config.model,
      tts_config: {
        ...saved.api_config.tts_config,
        model: isMimoTts ? normalizeMimoModelId(saved.api_config.tts_config.model) : saved.api_config.tts_config.model,
      },
    },
  }
}

function stripRequestSecrets(request: GenerateRequest): GenerateRequest {
  return {
    ...request,
    api_config: {
      ...request.api_config,
      api_key: '',
      tts_config: {
        ...request.api_config.tts_config,
        api_key: '',
      },
    },
  }
}

function loadSavedRequest(): GenerateRequest {
  if (typeof window === 'undefined') return defaultRequest
  try {
    const raw = window.localStorage.getItem(REQUEST_STORAGE_KEY)
    if (!raw) return defaultRequest
    const saved = JSON.parse(raw) as Partial<GenerateRequest>
    const savedApi = (saved.api_config ?? {}) as Partial<ApiConfig>
    const savedTts = (savedApi.tts_config ?? {}) as Partial<TtsConfig>
    const legacyTtsProvider = savedApi.tts_provider?.trim()
    const legacyTtsModel = savedApi.tts_model?.trim()
    return stripRequestSecrets(normalizeSavedMimoConfig({
      ...defaultRequest,
      ...saved,
      url_import_mode: (saved.url_import_mode ?? defaultRequest.url_import_mode) as UrlImportMode,
      url_auto_subtitle_fallback: saved.url_auto_subtitle_fallback ?? defaultRequest.url_auto_subtitle_fallback,
      skip_video_slicing: saved.skip_video_slicing ?? defaultRequest.skip_video_slicing,
      collection_levels: normalizeCollectionLevels(saved.collection_levels, (saved.level ?? defaultRequest.level) as Level),
      content_toggles: {
        ...defaultRequest.content_toggles,
        ...(saved.content_toggles ?? {}),
      },
      api_config: {
        ...defaultRequest.api_config,
        ...savedApi,
        tts_config: {
          ...defaultRequest.api_config.tts_config,
          ...savedTts,
          provider: (savedTts.provider ?? legacyTtsProvider ?? defaultRequest.api_config.tts_config.provider) as TtsProvider,
          voice: savedTts.voice ?? legacyTtsModel ?? defaultRequest.api_config.tts_config.voice,
          enabled: savedTts.enabled ?? Boolean(legacyTtsProvider),
        },
      },
      card_types: saved.card_types?.length ? saved.card_types : defaultRequest.card_types,
    }))
  } catch {
    return defaultRequest
  }
}

function loadSavedProject(): Project | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(PROJECT_STORAGE_KEY)
    if (!raw) return null
    const saved = JSON.parse(raw) as Project
    if (!saved || !Array.isArray(saved.segments) || saved.segments.length === 0) return null
    return {
      ...saved,
      template_id: saved.template_id ?? 'immersive',
      source_mode: saved.source_mode ?? 'local',
      segments: saved.segments.map((segment) => ({
        ...segment,
        cards: Array.isArray(segment.cards) ? segment.cards : [],
      })),
    }
  } catch {
    return null
  }
}

function loadSecretPrefs(): SecretPrefs {
  if (typeof window === 'undefined') return { rememberModelKey: false, rememberTtsKey: false }
  try {
    const raw = window.localStorage.getItem(SECRET_PREFS_STORAGE_KEY)
    if (!raw) return { rememberModelKey: false, rememberTtsKey: false }
    const parsed = JSON.parse(raw) as Partial<SecretPrefs>
    return {
      rememberModelKey: Boolean(parsed.rememberModelKey),
      rememberTtsKey: Boolean(parsed.rememberTtsKey),
    }
  } catch {
    return { rememberModelKey: false, rememberTtsKey: false }
  }
}

async function runWorker<T>(command: string, payload: unknown): Promise<T> {
  return invoke<T>('run_worker', { command, payload })
}

async function saveSecret(key: 'model_api_key' | 'tts_api_key', value: string) {
  if (!isTauriRuntime()) return
  await invoke('save_secret', { key, value })
}

async function loadSecret(key: 'model_api_key' | 'tts_api_key') {
  if (!isTauriRuntime()) return ''
  return (await invoke<string | null>('load_secret', { key })) ?? ''
}

async function deleteSecret(key: 'model_api_key' | 'tts_api_key') {
  if (!isTauriRuntime()) return
  await invoke('delete_secret', { key })
}

function createDemoProject(request: GenerateRequest): Project {
  if (request.source_mode === 'document') {
    const segment: Segment = {
      id: 'doc_demo_001',
      start: 0,
      end: 0,
      source_time: '文档知识点 1',
      text: 'What is spaced repetition and why does it improve long-term memory?',
      duration: 0,
      recommendation: 5,
      phrase: 'spaced repetition',
      cards: [
        {
          id: 'doc_demo_001_knowledge',
          type: 'knowledge',
          type_label: '知识卡',
          enabled: true,
          english: 'What is spaced repetition and why does it improve long-term memory?',
          chinese: '间隔重复会在遗忘前重新唤起记忆，让长期记忆更稳固。',
          phrase: 'spaced repetition',
          definition: '一种把复习安排在逐渐拉长的时间间隔中的学习方法。',
          collocations: 'spaced repetition system; review interval; active recall',
          context: '适合从文章、教材、讲义中抽取核心概念和可复习问题。',
          example: 'Anki uses spaced repetition to schedule the next review.',
          chinese_feel: '中文里更接近“隔一段时间再复习，而不是一次性死背”。',
          why: '这是理解 Anki 工作方式的基础概念，也容易迁移到任何学科。',
          difficulty: 'B1 日常交流',
          teacher_note: '这张卡要记住的是机制，不是背定义：为什么“隔开复习”更有效。',
          cloze: '____ improves long-term memory by scheduling reviews before forgetting.',
          quality: {
            score: 88,
            status: 'recommended',
            issues: [],
          },
        },
      ],
    }
    return {
      id: 'demo_document_project',
      title: request.title || '文档知识卡 Demo',
      source_mode: request.source_mode,
      source_url: '',
      source_info: null,
      video_path: '',
      subtitle_path: '',
      document_path: request.document_path || 'demo.md',
      language: request.language,
      level: request.level,
      collection_levels: request.collection_levels,
      template_id: request.template_id,
      content_toggles: request.content_toggles,
      card_types: ['knowledge'],
      segments: [segment],
      warning: '浏览器预览模式：真实文档解析和 apkg 导出需要在 Tauri 桌面端运行。',
      created_at: Date.now(),
    }
  }

  const sampleSegments: Segment[] = [
    {
      id: 'seg_demo_001',
      start: 754.2,
      end: 758.4,
      source_time: '00:12:34.200 - 00:12:38.400',
      text: "I'm not really in the mood right now.",
      duration: 4.2,
      recommendation: 5,
      phrase: 'in the mood',
      cards: [],
    },
    {
      id: 'seg_demo_002',
      start: 941.1,
      end: 945.3,
      source_time: '00:15:41.100 - 00:15:45.300',
      text: "Can we figure this out later?",
      duration: 4.2,
      recommendation: 4,
      phrase: 'figure out',
      cards: [],
    },
  ]

  sampleSegments.forEach((segment) => {
    segment.cards = request.card_types.map((type) => {
      const label = cardOptions.find((card) => card.id === type)?.label ?? type
      const cloze = segment.text.replace(new RegExp(segment.phrase, 'i'), '____')
      return {
        id: `${segment.id}_${type}`,
        type,
        type_label: label,
        enabled: true,
        english: segment.text,
        chinese:
          segment.id === 'seg_demo_001'
            ? '我现在真的没那个心情。'
            : '我们能不能晚点再把这件事弄明白？',
        phrase: segment.phrase,
        definition: `${segment.phrase} 是一个高频口语词伙，表达状态、处理问题或理解含义。`,
        collocations:
          segment.phrase === 'in the mood'
            ? 'not in the mood; in the mood for coffee; in the mood to talk'
            : 'figure it out; figure out why; figure out what happened',
        context: '常见于朋友、家人、同事之间的自然对话，语气比正式书面表达更松弛。',
        example:
          segment.phrase === 'in the mood'
            ? "I'm not in the mood to go out tonight."
            : "Give me a minute. I'll figure it out.",
        chinese_feel:
          segment.phrase === 'in the mood'
            ? '中文里更接近“没那个心情”。'
            : '中文里更接近“弄明白 / 想清楚”。',
        why: '这句短、真实、可迁移，适合用来训练听力和表达块。',
        difficulty: levels.find((level) => level.id === request.level)?.label ?? request.level,
        teacher_note: `这句值得学，因为 ${segment.phrase} 是真实口语里的高频表达。`,
        cloze,
        quality: {
          score: 86,
          status: 'recommended',
          issues: [],
        },
      }
    })
  })

  return {
    id: 'demo_project',
    title: request.title || 'Friends S01E01 Demo',
    source_mode: request.source_mode,
    source_url: request.source_url,
    source_info: request.source_mode === 'url' ? { title: 'URL Demo', webpage_url: request.source_url } : null,
    video_path: request.video_path || 'demo.mp4',
    subtitle_path: request.subtitle_path || 'demo.srt',
    language: request.language,
    level: request.level,
    collection_levels: request.collection_levels,
    template_id: request.template_id,
    content_toggles: request.content_toggles,
    card_types: request.card_types,
    segments: sampleSegments,
    warning: '浏览器预览模式：真实视频切片和 apkg 导出需要在 Tauri 桌面端运行。',
    created_at: Date.now(),
  }
}

function badgeText(count: number) {
  return count > 0 ? `${count} 张已选` : '未选择卡片'
}

function qualityLabel(card: Card) {
  const status = card.quality?.status
  if (status === 'recommended') return '推荐保留'
  if (status === 'needs_review') return '需要检查'
  if (status === 'reject') return '建议删除'
  return '未评分'
}

function qualityClass(card: Card) {
  return card.quality?.status ?? 'unknown'
}

const segmentFilterOptions: Array<{ id: SegmentFilter; label: string }> = [
  { id: 'all', label: '全部' },
  { id: 'recommended', label: '推荐' },
  { id: 'needs_review', label: '待审' },
  { id: 'reject', label: '已拒绝' },
  { id: 'duplicate', label: '重复合并' },
]

function phraseValueScore(value: number | string | null | undefined) {
  const score = Number(value)
  return Number.isFinite(score) ? score : null
}

function isPlaceholderPhrase(value: string | null | undefined) {
  const phrase = String(value ?? '').trim().toLowerCase()
  return !phrase || phrase === 'key expression' || phrase === 'n/a'
}

function segmentPhraseTitle(segment: Segment) {
  if (!isPlaceholderPhrase(segment.phrase)) return segment.phrase
  return '未识别词伙'
}

function segmentPhraseLabel(segment: Segment) {
  return isPlaceholderPhrase(segment.phrase) ? '未识别词伙' : segment.phrase
}

function segmentReviewStatus(segment: Segment): SegmentFilter | 'unreviewed' {
  const status = String(segment.phrase_review_status ?? '').trim()
  if (status === 'recommended' || status === 'needs_review' || status === 'reject' || status === 'duplicate') {
    return status
  }
  if (segment.cards.some((card) => card.quality?.status === 'recommended')) return 'recommended'
  if (segment.cards.some((card) => card.quality?.status === 'needs_review')) return 'needs_review'
  if (!segment.cards.length || segment.cards.every((card) => card.quality?.status === 'reject')) return 'reject'
  return 'unreviewed'
}

function segmentStatusLabel(status: SegmentFilter | 'unreviewed') {
  if (status === 'recommended') return '推荐'
  if (status === 'needs_review') return '待审'
  if (status === 'reject') return '已拒绝'
  if (status === 'duplicate') return '重复合并'
  return '未评审'
}

function segmentMatchesFilter(segment: Segment, filter: SegmentFilter) {
  if (filter === 'all') return true
  return segmentReviewStatus(segment) === filter
}

function segmentMediaStart(segment: Segment) {
  return Number.isFinite(Number(segment.media_start)) ? Number(segment.media_start) : segment.start
}

function segmentMediaEnd(segment: Segment) {
  return Number.isFinite(Number(segment.media_end)) ? Number(segment.media_end) : segment.end
}

function segmentBudgetLabel(value: number | undefined) {
  return value && value > 0 ? `${value} 段上限` : '自动片段'
}

function isRecommendedCardForExport(segment: Segment, card: Card) {
  const quality = card.quality?.status
  if (quality === 'recommended') return true
  if (quality === 'reject') return false
  const reviewStatus = segmentReviewStatus(segment)
  const score = phraseValueScore(card.phrase_value_score ?? segment.phrase_value_score)
  return reviewStatus === 'recommended' || Boolean(score && score >= 4)
}

function isReviewableCardForExport(segment: Segment, card: Card) {
  if (card.quality?.status === 'reject') return false
  if (isRecommendedCardForExport(segment, card)) return true
  const reviewStatus = segmentReviewStatus(segment)
  const score = phraseValueScore(card.phrase_value_score ?? segment.phrase_value_score)
  return card.quality?.status === 'needs_review' || reviewStatus === 'needs_review' || Boolean(score && score >= 3)
}

function applyCardSelection(project: Project, mode: 'recommended' | 'reviewable') {
  let selected = 0
  const nextProject = {
    ...project,
    segments: project.segments.map((segment) => ({
      ...segment,
      cards: segment.cards.map((card) => {
        const enabled =
          mode === 'recommended'
            ? isRecommendedCardForExport(segment, card)
            : isReviewableCardForExport(segment, card)
        if (enabled) selected += 1
        return { ...card, enabled }
      }),
    })),
  }
  return { project: nextProject, selected }
}

function App() {
  const [request, setRequest] = useState<GenerateRequest>(() => loadSavedRequest())
  const [project, setProject] = useState<Project | null>(() => loadSavedProject())
  const [envStatus, setEnvStatus] = useState<EnvStatus | null>(null)
  const [status, setStatus] = useState('准备生成 Anki 卡片。')
  const [busy, setBusy] = useState(false)
  const [activeSegmentId, setActiveSegmentId] = useState<string | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [apiTesting, setApiTesting] = useState(false)
  const [apiTestResult, setApiTestResult] = useState<ApiTestResult | null>(null)
  const [ttsTesting, setTtsTesting] = useState(false)
  const [ttsTestResult, setTtsTestResult] = useState<TtsTestResult | null>(null)
  const [lastExport, setLastExport] = useState<ExportResult | null>(null)
  const [ankiVerifying, setAnkiVerifying] = useState(false)
  const [ankiVerifyResult, setAnkiVerifyResult] = useState<AnkiVerifyResult | null>(null)
  const [previewRate, setPreviewRate] = useState(0.75)
  const [workerProgress, setWorkerProgress] = useState<WorkerProgress | null>(null)
  const [showAdvancedApi, setShowAdvancedApi] = useState(false)
  const [showAdvancedTts, setShowAdvancedTts] = useState(false)
  const [showCapabilities, setShowCapabilities] = useState(false)
  const [settingsTab, setSettingsTab] = useState<SettingsTab>('api')
  const [secretPrefs, setSecretPrefs] = useState<SecretPrefs>(() => loadSecretPrefs())
  const [segmentFilter, setSegmentFilter] = useState<SegmentFilter>('all')
  const previewPanelRef = useRef<HTMLElement | null>(null)
  const settingsDialogRef = useRef<HTMLElement | null>(null)

  const selectedCardCount = useMemo(() => {
    return project?.segments.reduce(
      (total, segment) => total + segment.cards.filter((card) => card.enabled).length,
      0,
    ) ?? 0
  }, [project])

  const qualityCounts = useMemo(() => {
    const segments = project?.segments ?? []
    const cards = segments.flatMap((segment) => segment.cards)
    return {
      total: cards.length,
      recommended: segments.reduce(
        (total, segment) => total + segment.cards.filter((card) => isRecommendedCardForExport(segment, card)).length,
        0,
      ),
      review: segments.reduce(
        (total, segment) =>
          total +
          segment.cards.filter(
            (card) => !isRecommendedCardForExport(segment, card) && isReviewableCardForExport(segment, card),
          ).length,
        0,
      ),
      rejected: segments.reduce(
        (total, segment) => total + segment.cards.filter((card) => !isReviewableCardForExport(segment, card)).length,
        0,
      ),
    }
  }, [project])

  const qualityDiagnostics = useMemo(() => {
    const segments = project?.segments ?? []
    const scored = segments
      .map((segment) => phraseValueScore(segment.phrase_value_score))
      .filter((score): score is number => typeof score === 'number')
    const avgScore = scored.length
      ? scored.reduce((total, score) => total + score, 0) / scored.length
      : null
    const rejectReasons = segments
      .filter((segment) => segmentReviewStatus(segment) === 'reject')
      .map((segment) => segment.phrase_reject_reason || segment.phrase_decision_reason || '未给出拒绝理由')
      .slice(0, 3)
    const shortReason =
      project && qualityCounts.recommended < 5
        ? project.segments.length < 6
          ? '字幕片段太少或切分后有效候选不足。'
          : qualityCounts.recommended === 0
            ? '当前筛选没有推荐卡，可能是词伙评分不足、模型返回空或筛选太严格。'
            : '推荐卡偏少，通常是重复合并、低价值表达或模型评审较严格。'
        : ''
    return {
      candidates: segments.length,
      avgScore,
      duplicate: segments.filter((segment) => segmentReviewStatus(segment) === 'duplicate').length,
      rejectedSegments: segments.filter((segment) => segmentReviewStatus(segment) === 'reject').length,
      rejectReasons,
      shortReason,
    }
  }, [project, qualityCounts.recommended])

  const segmentReviewCounts = useMemo(() => {
    const segments = project?.segments ?? []
    return {
      all: segments.length,
      recommended: segments.filter((segment) => segmentReviewStatus(segment) === 'recommended').length,
      needs_review: segments.filter((segment) => segmentReviewStatus(segment) === 'needs_review').length,
      reject: segments.filter((segment) => segmentReviewStatus(segment) === 'reject').length,
      duplicate: segments.filter((segment) => segmentReviewStatus(segment) === 'duplicate').length,
    }
  }, [project])

  const visibleSegments = useMemo(() => {
    return project?.segments.filter((segment) => segmentMatchesFilter(segment, segmentFilter)) ?? []
  }, [project, segmentFilter])

  const activeTemplate = templateOptions.find((template) => template.id === request.template_id)
  const sourceReady =
    request.source_mode === 'url'
      ? Boolean(request.source_url.trim())
      : request.source_mode === 'document'
        ? Boolean(request.document_path?.trim())
        : Boolean(request.video_path && request.subtitle_path)
  const apiReady = request.api_config.provider === 'local' || Boolean(apiTestResult?.ok)
  const envReady =
    !isTauriRuntime() ||
    Boolean(
      envStatus?.genanki &&
        (request.source_mode === 'document' ||
          (request.source_mode === 'url' && request.url_import_mode === 'subtitles' && envStatus.yt_dlp) ||
          (envStatus.ffmpeg && (request.source_mode === 'local' || envStatus.yt_dlp))),
    )
  const currentSelectionCount = project ? selectedCardCount : request.card_types.length
  const readiness = [
    {
      id: 'source',
      label: request.source_mode === 'url' ? 'URL' : request.source_mode === 'document' ? '文档' : '素材',
      done: sourceReady,
      detail: sourceReady
        ? '已就绪'
        : request.source_mode === 'url'
          ? '待输入链接'
          : request.source_mode === 'document'
            ? '待选择 TXT/Markdown'
            : '待选择视频和字幕',
    },
    {
      id: 'env',
      label: '环境',
      done: envReady,
      detail: envReady ? '可用' : envStatus ? '缺少依赖' : '未检查',
    },
    {
      id: 'api',
      label: 'API',
      done: apiReady,
      detail:
        request.api_config.provider === 'local'
          ? '本地草稿'
          : apiTestResult?.ok
            ? '已通过'
            : apiTestResult
              ? '失败'
              : '未测试',
    },
    {
      id: 'cards',
      label: '卡片',
      done: currentSelectionCount > 0,
      detail: `${currentSelectionCount} 张`,
    },
  ]
  const apiTestTone = apiTesting ? 'testing' : apiTestResult ? (apiTestResult.ok ? 'ok' : 'warn') : 'idle'
  const apiTestTitle = apiTesting
    ? '正在测试连接'
    : apiTestResult
      ? apiTestResult.ok
        ? '连接成功'
        : '连接失败'
      : '尚未测试'
  const apiTestMessage = apiTesting
    ? '正在向当前接口发送一条短测试消息，通常几秒内会返回。'
    : apiTestResult?.message ?? '换 Provider、Base URL、模型名或 API Key 后，都建议点一次测试连接。'
  const apiTestMeta = apiTestResult
    ? `${apiTestResult.provider} · ${apiTestResult.model || '未填模型'}${
        apiTestResult.latency_ms ? ` · ${apiTestResult.latency_ms} ms` : ''
      }`
    : `${request.api_config.provider} · ${request.api_config.model || '未填模型'}`
  const tts = request.api_config.tts_config
  const ttsTestTone = ttsTesting ? 'testing' : ttsTestResult ? (ttsTestResult.ok ? 'ok' : 'warn') : 'idle'
  const ttsTestTitle = ttsTesting
    ? '正在测试 TTS'
    : ttsTestResult
      ? ttsTestResult.ok
        ? 'TTS 连接成功'
        : 'TTS 连接失败'
      : tts.enabled
        ? 'TTS 已开启，尚未测试'
        : 'TTS 已关闭'
  const ttsTestMessage = ttsTesting
    ? '正在生成一小段测试音频，用来确认 Key、语音和接口可用。'
    : ttsTestResult?.message ??
      (tts.enabled
        ? 'MIMO / Grok / Gemini / Speech API 都在这里单独测试，和上面的文本模型测试互不影响。'
        : '关闭时不会生成 AI 朗读，只会把视频原声音频放进卡片。')
  const ttsTestMeta = ttsTestResult
    ? `${ttsTestResult.provider} · ${ttsTestResult.model || '无模型名'} · ${ttsTestResult.voice || '无 voice'}${
        ttsTestResult.latency_ms ? ` · ${ttsTestResult.latency_ms} ms` : ''
      }${ttsTestResult.bytes ? ` · ${ttsTestResult.bytes} bytes` : ''}`
    : `${tts.provider} · ${tts.model || '无模型名'} · ${tts.voice || '无 voice'}`
  const statusTone = busy || workerProgress
    ? 'active'
    : /失败|缺少|不能|请先|不存在|错误|没有/.test(status)
      ? 'warn'
      : /完成|通过|成功|可用|已打开|已切换|已套用|已保留/.test(status)
        ? 'ok'
        : 'idle'

  useEffect(() => {
    window.localStorage.setItem(REQUEST_STORAGE_KEY, JSON.stringify(stripRequestSecrets(request)))
  }, [request])

  useEffect(() => {
    window.localStorage.setItem(SECRET_PREFS_STORAGE_KEY, JSON.stringify(secretPrefs))
  }, [secretPrefs])

  useEffect(() => {
    if (!isTauriRuntime()) return
    let cancelled = false
    const restore = async () => {
      try {
        const [modelKey, ttsKey] = await Promise.all([
          secretPrefs.rememberModelKey ? loadSecret('model_api_key') : Promise.resolve(''),
          secretPrefs.rememberTtsKey ? loadSecret('tts_api_key') : Promise.resolve(''),
        ])
        if (cancelled) return
        setRequest((current) => ({
          ...current,
          api_config: {
            ...current.api_config,
            api_key: current.api_config.api_key || modelKey,
            tts_config: {
              ...current.api_config.tts_config,
              api_key: current.api_config.tts_config.api_key || ttsKey,
            },
          },
        }))
      } catch {
        setStatus('系统凭据读取失败，请在设置页重新填写 API Key。')
      }
    }
    restore()
    return () => {
      cancelled = true
    }
  }, [secretPrefs.rememberModelKey, secretPrefs.rememberTtsKey])

  useEffect(() => {
    if (!isTauriRuntime()) return
    if (secretPrefs.rememberModelKey && request.api_config.api_key.trim()) {
      saveSecret('model_api_key', request.api_config.api_key.trim()).catch(() => {
        setStatus('模型 API Key 保存到系统凭据失败。')
      })
    }
  }, [secretPrefs.rememberModelKey, request.api_config.api_key])

  useEffect(() => {
    if (!isTauriRuntime()) return
    if (secretPrefs.rememberTtsKey && request.api_config.tts_config.api_key.trim()) {
      saveSecret('tts_api_key', request.api_config.tts_config.api_key.trim()).catch(() => {
        setStatus('TTS API Key 保存到系统凭据失败。')
      })
    }
  }, [secretPrefs.rememberTtsKey, request.api_config.tts_config.api_key])

  useEffect(() => {
    if (typeof window === 'undefined') return
    if (project) {
      window.localStorage.setItem(PROJECT_STORAGE_KEY, JSON.stringify(project))
    } else {
      window.localStorage.removeItem(PROJECT_STORAGE_KEY)
    }
  }, [project])

  useEffect(() => {
    if (!project) {
      setActiveSegmentId(null)
      return
    }
    const hasActiveSegment = visibleSegments.some((segment) => segment.id === activeSegmentId)
    if (!hasActiveSegment) {
      setActiveSegmentId(visibleSegments[0]?.id ?? null)
    }
  }, [project, activeSegmentId, visibleSegments])

  useEffect(() => {
    if (!isTauriRuntime()) return
    let stopListening: (() => void) | undefined
    listen<WorkerProgress>('worker-progress', (event) => {
      setWorkerProgress(event.payload)
      setStatus(event.payload.message)
    })
      .then((unlisten) => {
        stopListening = unlisten
      })
      .catch(() => {
        setWorkerProgress(null)
      })
    return () => {
      stopListening?.()
    }
  }, [])

  useEffect(() => {
    if (!settingsOpen) return
    const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const focusTimer = window.setTimeout(() => {
      settingsDialogRef.current?.focus()
    }, 0)
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        setSettingsOpen(false)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => {
      window.clearTimeout(focusTimer)
      window.removeEventListener('keydown', handleKeyDown)
      previouslyFocused?.focus()
    }
  }, [settingsOpen])

  const runWindowAction = async (action: 'minimize' | 'toggleMaximize' | 'close') => {
    if (!isTauriRuntime()) return
    const appWindow = getCurrentWindow()
    if (action === 'minimize') {
      await appWindow.minimize()
    } else if (action === 'toggleMaximize') {
      await appWindow.toggleMaximize()
    } else {
      await appWindow.close()
    }
  }

  const startWindowDrag = async (event: MouseEvent<HTMLElement>) => {
    if (!isTauriRuntime() || event.button !== 0) return
    const target = event.target as HTMLElement
    if (target.closest('button,input,select,textarea,a,label,summary,.topbar-actions,.window-controls')) return
    await getCurrentWindow().startDragging()
  }

  const handleTopbarDoubleClick = async (event: MouseEvent<HTMLElement>) => {
    const target = event.target as HTMLElement
    if (target.closest('button,input,select,textarea,a,label,summary,.topbar-actions,.window-controls')) return
    await runWindowAction('toggleMaximize')
  }

  const startWindowResize = async (direction: ResizeDirection, event: MouseEvent<HTMLDivElement>) => {
    if (!isTauriRuntime() || event.button !== 0) return
    event.preventDefault()
    event.stopPropagation()
    await getCurrentWindow().startResizeDragging(direction)
  }

  const focusPreviewPanel = () => {
    previewPanelRef.current?.focus({ preventScroll: true })
    setStatus(project ? '已定位到卡片预览区，可继续审核和编辑。' : '卡片预览区当前没有生成草稿，请先生成卡片。')
  }

  const patchRequest = (patch: Partial<GenerateRequest>) => {
    setRequest((current) => ({ ...current, ...patch }))
  }

  const selectCurrentLevel = (level: Level) => {
    patchRequest({
      level,
      collection_levels: defaultCollectionLevels(level),
    })
  }

  const toggleCollectionLevel = (level: Level) => {
    setRequest((current) => {
      const selected = normalizeCollectionLevels(current.collection_levels, current.level)
      const next = selected.includes(level) ? selected.filter((item) => item !== level) : [...selected, level]
      return {
        ...current,
        collection_levels: normalizeCollectionLevels(next.length ? next : selected, current.level),
      }
    })
  }

  const applyCollectionPreset = (mode: 'current' | 'below' | 'around') => {
    setRequest((current) => {
      const index = Math.max(0, levelOrder.indexOf(current.level))
      const collectionLevels =
        mode === 'current'
          ? [current.level]
          : mode === 'below'
            ? levelOrder.slice(0, index + 1)
            : levelOrder.slice(Math.max(0, index - 1), Math.min(levelOrder.length, index + 2))
      return {
        ...current,
        collection_levels: collectionLevels,
      }
    })
  }

  const selectSourceMode = (mode: SourceMode) => {
    const nextCardTypes: CardKind[] =
      mode === 'document'
        ? ['knowledge']
        : request.card_types.includes('knowledge')
          ? ['listening', 'phrase', 'cloze']
          : request.card_types

    setLastExport(null)
    setAnkiVerifyResult(null)
    setProject(null)
    setActiveSegmentId(null)
    setWorkerProgress(null)
    patchRequest({ source_mode: mode, card_types: nextCardTypes })
    setStatus(
      mode === 'url'
        ? '已切换到视频链接模式，请粘贴 YouTube 或视频 URL。'
        : mode === 'document'
          ? '已切换到文档资料模式，请选择 TXT、Markdown、DOCX、EPUB 或 PDF。'
          : '已切换到本地视频模式，请选择视频和 SRT 字幕。',
    )
  }

  const patchApi = (patch: Partial<ApiConfig>) => {
    setRequest((current) => ({
      ...current,
      api_config: { ...current.api_config, ...patch },
    }))
    setApiTestResult(null)
  }

  const patchTts = (patch: Partial<TtsConfig>) => {
    setRequest((current) => ({
      ...current,
      api_config: {
        ...current.api_config,
        tts_config: { ...current.api_config.tts_config, ...patch },
      },
    }))
    setTtsTestResult(null)
  }

  const toggleRememberSecret = (kind: 'model' | 'tts') => {
    const prefKey = kind === 'model' ? 'rememberModelKey' : 'rememberTtsKey'
    const secretKey = kind === 'model' ? 'model_api_key' : 'tts_api_key'
    setSecretPrefs((current) => {
      const enabled = !current[prefKey]
      if (!enabled) {
        deleteSecret(secretKey).catch(() => {
          setStatus('系统凭据删除失败，请稍后重试。')
        })
      }
      if (enabled) {
        const value = kind === 'model' ? request.api_config.api_key.trim() : request.api_config.tts_config.api_key.trim()
        if (value) {
          saveSecret(secretKey, value).catch(() => {
            setStatus('系统凭据保存失败，请确认当前桌面端有凭据访问权限。')
          })
        }
      }
      return { ...current, [prefKey]: enabled }
    })
  }

  const applyApiPreset = (preset: ApiPreset) => {
    setRequest((current) => ({
      ...current,
      api_config: {
        ...current.api_config,
        provider: preset.provider,
        base_url: preset.base_url,
        model: preset.model,
        capabilities: preset.capabilities,
      },
    }))
    setApiTestResult(null)
    setStatus(`已套用 ${preset.label} 预设，请填写 API Key 后测试连接。`)
  }

  const applyTtsPreset = (preset: TtsPreset) => {
    const shouldReuseMainMimoKey = preset.provider === 'mimo' && isMimoApiConfig(request.api_config) && request.api_config.api_key.trim()
    patchTts({
      enabled: preset.provider !== 'disabled',
      provider: preset.provider,
      base_url: preset.base_url,
      model: preset.model,
      voice: preset.voice,
      api_key: shouldReuseMainMimoKey ? '' : request.api_config.tts_config.api_key,
    })
    setStatus(
      preset.provider === 'disabled'
        ? '已关闭 TTS，导出时只使用视频原声音频。'
        : `已套用 ${preset.label}，请填写对应 API Key 后测试 TTS。`,
    )
  }

  const toggleContent = (key: keyof ContentToggles) => {
    setRequest((current) => ({
      ...current,
      content_toggles: {
        ...current.content_toggles,
        [key]: !current.content_toggles[key],
      },
    }))
  }

  const toggleCardType = (type: CardKind) => {
    setRequest((current) => {
      const exists = current.card_types.includes(type)
      const next = exists
        ? current.card_types.filter((item) => item !== type)
        : [...current.card_types, type]
      return { ...current, card_types: next.length ? next : current.card_types }
    })
  }

  const selectPath = async (kind: 'video' | 'subtitle' | 'document') => {
    if (!isTauriRuntime()) {
      const prompt =
        kind === 'video'
          ? '输入视频绝对路径'
          : kind === 'subtitle'
            ? '输入 SRT 绝对路径'
            : '输入 TXT / Markdown / DOCX / EPUB / PDF 绝对路径'
      const value = window.prompt(prompt)
      if (value) {
        patchRequest(
          kind === 'video'
            ? { video_path: value }
            : kind === 'subtitle'
              ? { subtitle_path: value }
              : { document_path: value },
        )
      }
      return
    }

    const selected = await openDialog({
      multiple: false,
      directory: false,
      filters:
        kind === 'video'
          ? [{ name: 'Video', extensions: ['mp4', 'mkv', 'mov', 'avi', 'webm'] }]
          : kind === 'subtitle'
            ? [{ name: 'Subtitle', extensions: ['srt'] }]
            : [{ name: 'Document', extensions: ['txt', 'md', 'markdown', 'pdf', 'docx', 'epub'] }],
    })

    if (typeof selected === 'string') {
      patchRequest(
        kind === 'video'
          ? { video_path: selected }
          : kind === 'subtitle'
            ? { subtitle_path: selected }
            : { document_path: selected },
      )
    }
  }

  const checkEnv = async () => {
    setBusy(true)
    setWorkerProgress(null)
    setStatus('正在检查 Python、ffmpeg 和 genanki。')
    try {
      if (!isTauriRuntime()) {
        setEnvStatus({ python: 'browser-preview', ffmpeg: false, genanki: false })
        setStatus('当前是浏览器预览模式，真实导出请运行 Tauri 桌面端。')
      } else {
        const result = await runWorker<EnvStatus>('check_env', {})
        setEnvStatus(result)
        setStatus(result.ffmpeg && result.genanki ? '环境检查通过。' : '环境缺少依赖，请查看状态卡。')
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  const testApi = async () => {
    const api = request.api_config
    const failBeforeRequest = (message: string) => {
      setApiTestResult({
        ok: false,
        provider: api.provider,
        model: api.model,
        message,
      })
      setStatus(`API 测试失败：${message}`)
    }

    if (api.provider !== 'local' && !api.api_key.trim()) {
      failBeforeRequest('还没有填写 API Key。')
      return
    }
    if (api.provider !== 'local' && !api.model.trim()) {
      failBeforeRequest('还没有填写模型名。')
      return
    }
    if ((api.provider === 'openai-compatible' || api.provider === 'mimo') && !api.base_url.trim()) {
      failBeforeRequest(api.provider === 'mimo' ? 'MIMO 需要填写 Base URL。' : 'OpenAI-compatible 需要填写 Base URL。')
      return
    }

    setApiTesting(true)
    setApiTestResult(null)
    setWorkerProgress(null)
    setStatus('正在测试模型 API 连接。')
    try {
      if (!isTauriRuntime()) {
        const result = {
          ok: api.provider === 'local',
          provider: api.provider,
          model: api.model,
          message:
            api.provider === 'local'
              ? '本地草稿模式可用。'
              : '浏览器预览模式不能真实测试 API，请运行桌面端。',
        }
        setApiTestResult(result)
        setStatus(result.message)
      } else {
        const result = await runWorker<ApiTestResult>('test_api', { api_config: api })
        setApiTestResult(result)
        setStatus(result.ok ? `API 测试通过：${result.message}` : `API 测试失败：${result.message}`)
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      setApiTestResult({
        ok: false,
        provider: api.provider,
        model: api.model,
        message,
      })
      setStatus(`API 测试失败：${message}`)
    } finally {
      setApiTesting(false)
    }
  }

  const testTts = async () => {
    const currentTts = resolveTtsConfig(request.api_config.tts_config, request.api_config)
    const failBeforeRequest = (message: string) => {
      setTtsTestResult({
        ok: false,
        provider: currentTts.provider,
        model: currentTts.model,
        voice: currentTts.voice,
        message,
      })
      setStatus(`TTS 测试失败：${message}`)
    }

    if (!currentTts.enabled || currentTts.provider === 'disabled') {
      failBeforeRequest('TTS 当前是关闭状态。')
      return
    }
    if (!currentTts.api_key.trim()) {
      failBeforeRequest('还没有填写 TTS API Key。')
      return
    }
    if (currentTts.provider === 'grok' && !currentTts.voice.trim()) {
      failBeforeRequest('Grok TTS 需要填写 voice_id，例如 eve、ara、leo、rex、sal。')
      return
    }
    if (currentTts.provider === 'gemini' && !currentTts.model.trim()) {
      failBeforeRequest('Gemini TTS 需要填写 TTS 模型名。')
      return
    }
    if (
      (currentTts.provider === 'openai-compatible' || currentTts.provider === 'mimo') &&
      (!currentTts.base_url.trim() || !currentTts.model.trim())
    ) {
      failBeforeRequest(
        currentTts.provider === 'mimo'
          ? 'MIMO TTS 需要 Base URL 和模型名。'
          : 'OpenAI-compatible Speech 需要 Base URL 和模型名。',
      )
      return
    }
    if (
      currentTts.provider === 'mimo' &&
      isMimoTokenPlanKey(currentTts.api_key) &&
      !isMimoTokenPlanBase(currentTts.base_url)
    ) {
      failBeforeRequest(
        `你填的是 tp- 开头的 Token Plan Key，TTS Base URL 必须用 ${MIMO_TOKEN_PLAN_SGP_BASE_URL}，不能用公共 ${MIMO_OPENAI_BASE_URL}。请点 “MIMO SGP TTS” 预设。`,
      )
      return
    }

    setTtsTesting(true)
    setTtsTestResult(null)
    setWorkerProgress(null)
    setStatus('正在测试 TTS 语音接口。')
    try {
      if (!isTauriRuntime()) {
        const result: TtsTestResult = {
          ok: false,
          provider: currentTts.provider,
          model: currentTts.model,
          voice: currentTts.voice,
          message: '浏览器预览模式不能真实测试 TTS，请运行桌面端。',
        }
        setTtsTestResult(result)
        setStatus(result.message)
      } else {
        const result = await runWorker<TtsTestResult>('test_tts', {
          tts_config: currentTts,
          api_config: request.api_config,
          language: request.language,
        })
        setTtsTestResult(result)
        setStatus(result.ok ? `TTS 测试通过：${result.message}` : `TTS 测试失败：${result.message}`)
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      setTtsTestResult({
        ok: false,
        provider: currentTts.provider,
        model: currentTts.model,
        voice: currentTts.voice,
        message,
      })
      setStatus(`TTS 测试失败：${message}`)
    } finally {
      setTtsTesting(false)
    }
  }

  const generate = async () => {
    if (request.source_mode === 'url' && !request.source_url.trim()) {
      setStatus('请先输入 YouTube / 视频 URL。')
      return
    }
    if (request.source_mode === 'document' && !request.document_path.trim()) {
      setStatus('请先选择 TXT、Markdown、DOCX、EPUB 或 PDF 文档。')
      return
    }
    if (request.source_mode === 'local' && (!request.video_path || !request.subtitle_path)) {
      setStatus('请先选择视频和 SRT 字幕。')
      return
    }
    setLastExport(null)
    setAnkiVerifyResult(null)
    setWorkerProgress({ command: 'generate', stage: 'start', percent: 1, message: '准备开始生成。' })
    setBusy(true)
    setStatus(
      request.source_mode === 'url'
        ? request.url_import_mode === 'subtitles'
          ? '正在下载 URL 字幕并跳过视频切片，然后生成卡片草稿。'
          : '正在下载 URL 视频和字幕，然后生成卡片草稿。'
        : request.source_mode === 'document'
          ? '正在解析文档、总结知识点并生成卡片草稿。'
          : '正在解析字幕、筛选片段并生成卡片草稿。',
    )
    try {
      if (!isTauriRuntime()) {
        const demo = createDemoProject(request)
        setProject(demo)
        setSegmentFilter('all')
        setActiveSegmentId(demo.segments[0]?.id ?? null)
        setStatus(
          request.source_mode === 'url'
            ? '已生成浏览器演示卡片。URL 下载需要在 Tauri 桌面端运行。'
            : request.source_mode === 'document'
              ? '已生成浏览器演示文档卡。真实文档解析和 apkg 导出请用 Tauri 桌面端。'
              : '已生成浏览器演示卡片。真实视频切片和 apkg 导出请用 Tauri 桌面端。',
        )
        setWorkerProgress({ command: 'generate', stage: 'done', percent: 100, message: '演示卡片生成完成。' })
      } else {
        const result = await runWorker<Project>('generate', request)
        setProject(result)
        setSegmentFilter('all')
        setActiveSegmentId(result.segments[0]?.id ?? null)
        const recommendedCount = result.segments.reduce(
          (total, segment) => total + segment.cards.filter((card) => isRecommendedCardForExport(segment, card)).length,
          0,
        )
        const shortHint =
          recommendedCount < 5
            ? '推荐卡偏少，通常是字幕太短、重复太多、词伙评分不足或模型返回空；可以在质量仪表盘查看原因。'
            : ''
        setStatus(
          result.warning ||
            (result.source_mode === 'url'
              ? `URL 导入成功，已生成 ${result.segments.length} 个片段组，推荐 ${recommendedCount} 张。${shortHint}`
              : result.source_mode === 'document'
                ? `文档导入成功，已生成 ${result.segments.length} 个知识点组。`
              : `已生成 ${result.segments.length} 个片段组，推荐 ${recommendedCount} 张。${shortHint}`),
        )
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  const exportApkg = async () => {
    if (!project) {
      setStatus('还没有可导出的卡片。')
      return
    }
    let projectForExport = project
    if (selectedCardCount === 0) {
      const recommendedSelection = applyCardSelection(project, 'recommended')
      if (recommendedSelection.selected === 0) {
        setStatus('当前没有启用的卡片，也没有可自动启用的推荐卡。请改用“推荐+待审”或手动勾选至少一张。')
        return
      }
      projectForExport = recommendedSelection.project
      setProject(projectForExport)
      setStatus(`已自动启用 ${recommendedSelection.selected} 张推荐卡，继续导出。`)
    }
    if (!isTauriRuntime()) {
      setStatus('浏览器预览模式不能导出 apkg，请运行 npm run tauri:dev。')
      return
    }

    const outputDir = await openDialog({ directory: true, multiple: false })
    if (typeof outputDir !== 'string') {
      return
    }

    setBusy(true)
    setWorkerProgress({ command: 'export', stage: 'start', percent: 1, message: '准备开始导出。' })
    setStatus(
      projectForExport.source_mode === 'document'
        ? '正在打包文档知识卡 apkg。'
        : projectForExport.skip_video_slicing
          ? '正在打包字幕-only 卡包，并按需生成 TTS。'
          : '正在切视频、生成音频并打包 apkg。',
    )
    try {
      const result = await runWorker<ExportResult>('export', {
        project: { ...projectForExport, template_id: request.template_id, api_config: request.api_config },
        output_dir: outputDir,
      })
      setLastExport(result)
      setAnkiVerifyResult(null)
      const mediaHint = result.media_summary
        ? `媒体约 ${result.media_summary.media_mb} MB，视频 ${result.media_summary.video_segments} 段，词伙 TTS ${result.media_summary.phrase_tts_files} 条。`
        : ''
      setStatus(`导出完成：${result.cards} 张卡，${result.segments} 个片段。${mediaHint} ${result.apkg_path}`)
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  const revealExport = async () => {
    if (!lastExport?.apkg_path) return
    try {
      await invoke('reveal_path', { path: lastExport.apkg_path })
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error))
    }
  }

  const openAnkiImport = async () => {
    if (!lastExport?.apkg_path) return
    try {
      await invoke('open_anki_import', { apkgPath: lastExport.apkg_path })
      setStatus('已打开 Anki 导入窗口。')
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error))
    }
  }

  const verifyAnkiImport = async () => {
    if (!lastExport?.apkg_path) return
    if (!isTauriRuntime()) {
      setStatus('浏览器预览模式不能连接 AnkiConnect。')
      return
    }
    setAnkiVerifying(true)
    setAnkiVerifyResult(null)
    setStatus('正在通过 AnkiConnect 核验导入后的卡片和媒体。')
    try {
      const result = await runWorker<AnkiVerifyResult>('verify_anki_import', {
        export_result: lastExport,
      })
      setAnkiVerifyResult(result)
      setStatus(result.message)
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error))
    } finally {
      setAnkiVerifying(false)
    }
  }

  const setCardsEnabled = (enabled: boolean, segmentId?: string) => {
    setLastExport(null)
    setAnkiVerifyResult(null)
    setProject((current) => {
      if (!current) return current
      return {
        ...current,
        segments: current.segments.map((segment) =>
          segmentId && segment.id !== segmentId
            ? segment
            : {
                ...segment,
                cards: segment.cards.map((card) => ({ ...card, enabled })),
              },
        ),
      }
    })
  }

  const selectCardsByQuality = (mode: 'recommended' | 'reviewable') => {
    setLastExport(null)
    setAnkiVerifyResult(null)
    if (!project) return
    const result = applyCardSelection(project, mode)
    setProject(result.project)
    setStatus(
      mode === 'recommended'
        ? `已只保留推荐卡：${result.selected} 张。待审和建议删除已关闭。`
        : `已保留推荐卡和待审卡：${result.selected} 张。建议删除已关闭。`,
    )
  }

  const updateCard = (segmentId: string, cardId: string, patch: Partial<Card>) => {
    setLastExport(null)
    setAnkiVerifyResult(null)
    setProject((current) => {
      if (!current) return current
      return {
        ...current,
        segments: current.segments.map((segment) =>
          segment.id === segmentId
            ? {
                ...segment,
                cards: segment.cards.map((card) => (card.id === cardId ? { ...card, ...patch } : card)),
              }
            : segment,
        ),
      }
    })
  }

  const selectTemplate = (templateId: TemplateId) => {
    setLastExport(null)
    setAnkiVerifyResult(null)
    patchRequest({ template_id: templateId })
    setProject((current) => (current ? { ...current, template_id: templateId } : current))
  }

  const activeSegment = project?.segments.find((segment) => segment.id === activeSegmentId)
  const activeSegmentVideoSrc =
    activeSegment && project?.video_path && isTauriRuntime() ? convertFileSrc(project.video_path) : ''

  const handlePreviewLoaded = (event: SyntheticEvent<HTMLVideoElement>, segment: Segment) => {
    const video = event.currentTarget
    video.currentTime = Math.max(0, segmentMediaStart(segment))
    video.playbackRate = previewRate
  }

  const handlePreviewTimeUpdate = (event: SyntheticEvent<HTMLVideoElement>, segment: Segment) => {
    const video = event.currentTarget
    const start = segmentMediaStart(segment)
    const end = segmentMediaEnd(segment)
    video.playbackRate = previewRate
    if (video.currentTime >= end || video.currentTime < start) {
      video.currentTime = Math.max(0, start)
    }
  }

  return (
    <div className="app-shell">
      <header
        className="topbar"
        onMouseDown={startWindowDrag}
        onDoubleClick={handleTopbarDoubleClick}
      >
        <div className="brand-lockup">
          <div className="app-mark" aria-hidden="true">
            <img src="/app-icon.png" alt="" />
          </div>
          <div>
            <p className="eyebrow">Anki Card Generator V1</p>
            <h1>Anki 卡片生成器</h1>
          </div>
        </div>
        <div className="window-drag-region" />
        <div className="topbar-actions">
          <div className="mini-summary" aria-label="项目摘要">
            <span>{project ? `${project.segments.length} 个片段` : '等待生成'}</span>
            <span>{badgeText(selectedCardCount)}</span>
            <span>{project ? `${qualityCounts.review} 张待审` : segmentBudgetLabel(request.max_segments)}</span>
            <span>{activeTemplate?.label ?? '沉浸视频'}</span>
          </div>
          <div className={`status-chip ${statusTone}`} title={status} role="status" aria-live="polite" aria-atomic="true">
            <CheckCircle2 size={16} />
            <span>{status}</span>
          </div>
          <button className="ghost-button" type="button" onClick={() => setSettingsOpen(true)}>
            <Settings2 size={18} />
            设置
          </button>
          <button className="primary-button" type="button" onClick={generate} disabled={busy}>
            {busy ? <Loader2 className="spin" size={18} /> : <Wand2 size={18} />}
            生成卡片
          </button>
        </div>
        <div className="window-controls" aria-label="窗口控制">
          <button type="button" onClick={() => runWindowAction('minimize')} aria-label="最小化">
            <Minus size={17} />
          </button>
          <button type="button" onClick={() => runWindowAction('toggleMaximize')} aria-label="最大化">
            <Square size={15} />
          </button>
          <button className="close-window" type="button" onClick={() => runWindowAction('close')} aria-label="关闭">
            <X size={18} />
          </button>
        </div>
      </header>

      <main className="workspace">
        <section className="desktop-workspace">
          <nav className="app-rail" aria-label="功能导航">
            <div className="rail-brand" aria-hidden="true">
              <img src="/app-icon.png" alt="" />
            </div>
            <div className="rail-items">
              <button
                className={`rail-item ${request.source_mode !== 'document' ? 'active' : ''}`}
                type="button"
                title="视频制卡"
                aria-label="视频制卡"
                onClick={() => selectSourceMode(request.source_mode === 'url' ? 'url' : 'local')}
              >
                <Film size={19} />
              </button>
              <button className="rail-item" type="button" title="卡片预览" aria-label="卡片预览" onClick={focusPreviewPanel}>
                <MessageSquareText size={19} />
              </button>
              <button
                className={`rail-item ${request.source_mode === 'document' ? 'active' : ''}`}
                type="button"
                title="文档制卡"
                aria-label="文档制卡"
                onClick={() => selectSourceMode('document')}
              >
                <FileText size={19} />
              </button>
            </div>
            <button
              className="rail-item rail-settings"
              type="button"
              title="偏好"
              aria-label="偏好"
              onClick={() => setSettingsOpen(true)}
            >
              <Settings2 size={19} />
            </button>
          </nav>
          <aside className="control-column">
          <section className="panel readiness-panel">
            <div className="readiness-head">
              <span>生成就绪</span>
              <strong>
                {readiness.filter((item) => item.done).length}/{readiness.length}
              </strong>
            </div>
            <div className="readiness-grid">
              {readiness.map((item) => (
                <span className={item.done ? 'ready' : 'pending'} key={item.id}>
                  {item.done ? <CheckCircle2 size={14} /> : <CircleAlert size={14} />}
                  <strong>{item.label}</strong>
                  <small>{item.detail}</small>
                </span>
              ))}
            </div>
          </section>

          {workerProgress ? (
            <section className={`panel progress-panel ${workerProgress.percent >= 100 ? 'done' : ''}`}>
              <div className="progress-head">
                <span>{workerProgress.command === 'export' ? '导出进度' : '生成进度'}</span>
                <strong>{workerProgress.percent}%</strong>
              </div>
              <div className="progress-bar" aria-label="任务进度">
                <span style={{ width: `${workerProgress.percent}%` }} />
              </div>
              <p>
                <CircleDot size={14} />
                {workerProgress.message}
              </p>
            </section>
          ) : null}

          <section className={`panel status-panel ${statusTone}`} role="status" aria-live="polite" aria-atomic="true">
            <div className="status-panel-head">
              <span>当前状态</span>
              <strong>{busy ? '处理中' : '就绪'}</strong>
            </div>
            <p>{status}</p>
          </section>

          <section className="setup-grid">
            <div className="panel source-panel">
              <div className="panel-heading">
                <FolderOpen size={20} />
                <h3>素材</h3>
              </div>
              <label className="field">
                <span>项目标题</span>
                <input
                  value={request.title}
                  onChange={(event) => patchRequest({ title: event.target.value })}
                  placeholder="例如 Friends S01E01"
                />
              </label>
              <div className="source-switch" aria-label="素材来源">
                <button
                  type="button"
                  className={request.source_mode === 'local' ? 'selected' : ''}
                  aria-pressed={request.source_mode === 'local'}
                  onClick={() => selectSourceMode('local')}
                >
                  <Film size={18} />
                  <span>本地视频</span>
                  <small>视频 + SRT</small>
                </button>
                <button
                  type="button"
                  className={request.source_mode === 'url' ? 'selected' : ''}
                  aria-pressed={request.source_mode === 'url'}
                  onClick={() => selectSourceMode('url')}
                >
                  <Link2 size={18} />
                  <span>视频链接</span>
                  <small>YouTube / URL</small>
                </button>
                <button
                  type="button"
                  className={request.source_mode === 'document' ? 'selected' : ''}
                  aria-pressed={request.source_mode === 'document'}
                  onClick={() => selectSourceMode('document')}
                >
                  <FileText size={18} />
                  <span>文档资料</span>
                  <small>PDF / Word / EPUB</small>
                </button>
              </div>
              <div className="source-mode-hint" data-mode={request.source_mode}>
                {request.source_mode === 'url'
                  ? '当前是视频链接：粘贴 YouTube 或视频 URL，生成时自动下载视频和字幕。'
                  : request.source_mode === 'document'
                    ? '当前是文档资料：选择文档后生成结构化卡片。'
                    : '当前是本地视频：选择视频和 SRT 字幕后生成语言卡。'}
              </div>
              {request.source_mode === 'url' ? (
                <>
                  <label className="field">
                    <span>YouTube / 视频 URL</span>
                    <input
                      value={request.source_url}
                      onChange={(event) => patchRequest({ source_url: event.target.value })}
                      placeholder="https://www.youtube.com/watch?v=..."
                    />
                    <small>
                      YouTube 属于中等/高风险输入源；失败时可以切到字幕-only 或手动上传 SRT 继续制卡。
                    </small>
                  </label>
                  <div className="url-fallback-options" aria-label="URL 导入 fallback">
                    <div className="segmented compact-segmented">
                      <button
                        type="button"
                        className={request.url_import_mode === 'video' ? 'selected' : ''}
                        onClick={() => patchRequest({ url_import_mode: 'video', skip_video_slicing: false })}
                      >
                        下载视频+字幕
                      </button>
                      <button
                        type="button"
                        className={request.url_import_mode === 'subtitles' ? 'selected' : ''}
                        onClick={() => patchRequest({ url_import_mode: 'subtitles', skip_video_slicing: true })}
                      >
                        只用字幕生成
                      </button>
                    </div>
                    <label className="toggle">
                      <input
                        type="checkbox"
                        checked={request.url_auto_subtitle_fallback}
                        onChange={() =>
                          patchRequest({ url_auto_subtitle_fallback: !request.url_auto_subtitle_fallback })
                        }
                      />
                      <span>视频下载失败时自动 fallback 到字幕-only</span>
                    </label>
                    <label className="toggle">
                      <input
                        type="checkbox"
                        checked={request.skip_video_slicing}
                        onChange={() => {
                          const next = !request.skip_video_slicing
                          patchRequest({
                            skip_video_slicing: next,
                            url_import_mode: next ? 'subtitles' : request.url_import_mode,
                          })
                        }}
                      />
                      <span>导出时跳过视频切片，只保留字幕和 TTS</span>
                    </label>
                  </div>
                </>
              ) : request.source_mode === 'document' ? (
                <label className="field file-field">
                  <span>文档资料</span>
                  <div>
                    <input
                      value={request.document_path}
                      onChange={(event) => patchRequest({ document_path: event.target.value })}
                      placeholder="选择文档资料"
                    />
                    <button type="button" onClick={() => selectPath('document')} aria-label="选择文档资料">
                      <FileText size={18} />
                    </button>
                  </div>
                  <small>支持 TXT、Markdown、DOCX、EPUB、PDF。扫描版 PDF 需要后续 OCR。</small>
                </label>
              ) : (
                <>
                  <label className="field file-field">
                    <span>视频文件</span>
                    <div>
                      <input
                        value={request.video_path}
                        onChange={(event) => patchRequest({ video_path: event.target.value })}
                        placeholder="选择本地视频"
                      />
                      <button type="button" onClick={() => selectPath('video')} aria-label="选择视频文件">
                        <Film size={18} />
                      </button>
                    </div>
                  </label>
                  <label className="field file-field">
                    <span>SRT 字幕</span>
                    <div>
                      <input
                        value={request.subtitle_path}
                        onChange={(event) => patchRequest({ subtitle_path: event.target.value })}
                        placeholder="选择 SRT 字幕"
                      />
                      <button type="button" onClick={() => selectPath('subtitle')} aria-label="选择字幕文件">
                        <Subtitles size={18} />
                      </button>
                    </div>
                  </label>
                </>
              )}
            </div>

            <div className="panel settings-panel">
              <div className="panel-heading">
                <Languages size={20} />
                <h3>学习设置</h3>
              </div>
              <div className="two-fields">
                <label className="field">
                  <span>学习语言</span>
                  <select
                    value={request.language}
                    onChange={(event) => patchRequest({ language: event.target.value })}
                  >
                    <option>English</option>
                    <option>Français</option>
                    <option>Español</option>
                    <option>日本語</option>
                  </select>
                </label>
                <label className="field">
                  <span>最大片段数</span>
                  <div className="segment-budget-input">
                    <input
                      type="number"
                      min={3}
                      max={120}
                      value={request.max_segments > 0 ? request.max_segments : ''}
                      placeholder="自动"
                      disabled={request.max_segments <= 0}
                      onChange={(event) => patchRequest({ max_segments: Number(event.target.value) })}
                    />
                    <button
                      type="button"
                      className={request.max_segments <= 0 ? 'selected' : ''}
                      onClick={() => patchRequest({ max_segments: request.max_segments <= 0 ? 35 : 0 })}
                    >
                      自动
                    </button>
                  </div>
                  <small>{request.max_segments <= 0 ? '根据视频长度、字幕密度和句子完整性自动计算。' : '手动限制最终进入制卡的片段数量。'}</small>
                </label>
              </div>
              <div className="settings-subheading level-subheading">
                <strong>当前水平</strong>
                <span>控制解释深度和质量门槛</span>
              </div>
              <div className="segmented level-segmented" aria-label="当前学习水平">
                {levels.map((level) => (
                  <button
                    type="button"
                    key={level.id}
                    className={request.level === level.id ? 'selected' : ''}
                    onClick={() => selectCurrentLevel(level.id)}
                  >
                    <strong>{level.id}</strong>
                    <span>{level.note}</span>
                  </button>
                ))}
              </div>
              <div className="level-range-panel" aria-label="收录难度范围">
                <div className="settings-subheading level-subheading">
                  <strong>收录难度范围</strong>
                  <span>{normalizeCollectionLevels(request.collection_levels, request.level).join(' / ')}</span>
                </div>
                <div className="range-actions" aria-label="收录范围快捷设置">
                  <button type="button" onClick={() => applyCollectionPreset('current')}>
                    只当前
                  </button>
                  <button type="button" onClick={() => applyCollectionPreset('below')}>
                    当前及以下
                  </button>
                  <button type="button" onClick={() => applyCollectionPreset('around')}>
                    上下一级
                  </button>
                </div>
                <div className="level-range-grid">
                  {levels.map((level) => {
                    const selected = normalizeCollectionLevels(request.collection_levels, request.level).includes(level.id)
                    return (
                      <button
                        type="button"
                        key={level.id}
                        className={selected ? 'selected' : ''}
                        onClick={() => toggleCollectionLevel(level.id)}
                        aria-pressed={selected}
                      >
                        <strong>{level.id}</strong>
                        <span>{level.note}</span>
                      </button>
                    )
                  })}
                </div>
              </div>
              <div className="toggle-grid">
                {contentOptions.map((item) => (
                  <label className="toggle" key={item.key}>
                    <input
                      type="checkbox"
                      checked={request.content_toggles[item.key]}
                      onChange={() => toggleContent(item.key)}
                    />
                    <span>{item.label}</span>
                  </label>
                ))}
              </div>
            </div>
          </section>

          <section className="panel generation-panel">
            <div className="panel-heading">
              <Layers3 size={20} />
              <h3>卡片和模板</h3>
            </div>
            {request.source_mode === 'document' ? (
              <div className="doc-card-mode">
                <FileText size={18} />
                <div>
                  <strong>知识点卡</strong>
                  <span>正面是问题或概念提示，反面是结构化答案、解释、例子和为什么值得记。</span>
                </div>
              </div>
            ) : (
              <div className="choice-row">
                {cardOptions.map((item) => (
                  <button
                    type="button"
                    key={item.id}
                    className={`choice ${request.card_types.includes(item.id) ? 'selected' : ''}`}
                    onClick={() => toggleCardType(item.id)}
                  >
                    <strong>{item.label}</strong>
                    <span>{item.note}</span>
                  </button>
                ))}
              </div>
            )}
            <div className="choice-row">
              {templateOptions.map((item) => (
                <button
                  type="button"
                  key={item.id}
                  className={`choice template-choice ${request.template_id === item.id ? 'selected' : ''} ${
                    item.locked ? 'locked' : ''
                  }`}
                  onClick={() => {
                    if (!item.locked) selectTemplate(item.id)
                  }}
                  disabled={item.locked}
                >
                  <strong>{item.label}</strong>
                  <span>{item.note}</span>
                </button>
              ))}
            </div>
          </section>
          </aside>

          <section
            className={`panel preview-panel template-${request.template_id}`}
            ref={previewPanelRef}
            tabIndex={-1}
            aria-labelledby="preview-title"
          >
            <div className="preview-header">
              <div className="panel-heading">
                <MessageSquareText size={20} />
                <h3 id="preview-title">Anki 卡片列表预览</h3>
              </div>
              <div className="preview-actions">
                <button className="ghost-button" type="button" onClick={() => setCardsEnabled(true)} disabled={!project}>
                  全选
                </button>
                <button className="ghost-button" type="button" onClick={() => setCardsEnabled(false)} disabled={!project}>
                  全不选
                </button>
                <button className="ghost-button" type="button" onClick={() => selectCardsByQuality('recommended')} disabled={!project}>
                  只保留推荐
                </button>
                <button className="ghost-button" type="button" onClick={() => selectCardsByQuality('reviewable')} disabled={!project}>
                  推荐+待审
                </button>
                <button className="primary-button export-button" type="button" onClick={exportApkg} disabled={busy || !project}>
                  <Download size={18} />
                  导出 .apkg
                </button>
              </div>
            </div>

            <div className="review-dashboard" aria-label="生成审核概览">
              <div className="metric-card primary">
                <span>有效卡片</span>
                <strong>{project ? `${selectedCardCount}/${qualityCounts.total}` : '-'}</strong>
                <small>{project ? '当前勾选后会进入导出' : '等待本次生成结果'}</small>
              </div>
              <div className="metric-card">
                <span>推荐保留</span>
                <strong>{project ? qualityCounts.recommended : '-'}</strong>
                <small>{project ? `${qualityCounts.review} 张待审 · ${qualityCounts.rejected} 张建议删除` : '生成后显示质量分布'}</small>
              </div>
              <div className="metric-card">
                <span>片段预算</span>
                <strong>{project ? project.segments.length : request.max_segments > 0 ? request.max_segments : '自动'}</strong>
                  <small>
                    {project?.max_segments ? `${project.auto_max_segments ? '自动预算' : '预算'} ${project.max_segments} · ` : ''}
                    {request.level} · {request.language} · {activeTemplate?.label ?? '沉浸视频'}
                  </small>
              </div>
              <div className="metric-card">
                <span>平均词伙评分</span>
                <strong>{project ? (qualityDiagnostics.avgScore === null ? '-' : qualityDiagnostics.avgScore.toFixed(1)) : '-'}</strong>
                <small>{project ? `候选 ${qualityDiagnostics.candidates} · 重复合并 ${qualityDiagnostics.duplicate}` : '生成后显示评分'}</small>
              </div>
              <div className="metric-card">
                <span>拒绝原因</span>
                <strong>{project ? qualityDiagnostics.rejectedSegments : '-'}</strong>
                <small>
                  {project
                    ? qualityDiagnostics.shortReason ||
                      qualityDiagnostics.rejectReasons[0] ||
                      (project.skip_video_slicing ? '字幕-only 导出，不含视频切片。' : '推荐数量正常')
                    : '会说明为什么卡片少'}
                </small>
              </div>
            </div>

            <div className="review-filters" aria-label="片段质量筛选">
              {segmentFilterOptions.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  className={segmentFilter === option.id ? 'selected' : ''}
                  aria-pressed={segmentFilter === option.id}
                  onClick={() => setSegmentFilter(option.id)}
                  disabled={!project}
                >
                  <span>{option.label}</span>
                  <strong>{project ? segmentReviewCounts[option.id] : '-'}</strong>
                </button>
              ))}
            </div>

            {lastExport ? (
              <div className="export-result" role="status">
                <CheckCircle2 size={18} />
                <div>
                  <strong>已导出 {lastExport.cards} 张卡</strong>
                  {lastExport.media_summary ? (
                    <div className="export-media-summary" aria-label="导出媒体统计">
                      <span>视频 {lastExport.media_summary.video_segments} 段</span>
                      <span>原声 {lastExport.media_summary.original_audio_files} 条</span>
                      <span>整句 TTS {lastExport.media_summary.sentence_tts_files} 条</span>
                      <span>词伙 TTS {lastExport.media_summary.phrase_tts_files} 条</span>
                      <span>{lastExport.media_summary.media_mb} MB</span>
                    </div>
                  ) : null}
                  {lastExport.warnings?.length ? (
                    <div className="export-warnings" aria-label="导出警告">
                      {lastExport.warnings.map((warning) => (
                        <span key={warning}>{warning}</span>
                      ))}
                    </div>
                  ) : null}
                  <span>{lastExport.apkg_path}</span>
                </div>
                <button className="ghost-button" type="button" onClick={revealExport}>
                  定位文件
                </button>
                <button className="primary-button" type="button" onClick={openAnkiImport}>
                  <ExternalLink size={18} />
                  打开 Anki
                </button>
                <button className="ghost-button" type="button" onClick={verifyAnkiImport} disabled={ankiVerifying}>
                  {ankiVerifying ? <Loader2 className="spin" size={18} /> : <PlugZap size={18} />}
                  核验媒体
                </button>
                {ankiVerifyResult ? (
                  <div className={`anki-verify-result ${ankiVerifyResult.ok ? 'ok' : 'warn'}`}>
                    <strong>{ankiVerifyResult.ok ? '媒体一致' : '需要检查媒体'}</strong>
                    <span>
                      卡片 {ankiVerifyResult.card_count ?? 0}
                      {ankiVerifyResult.expected_cards ? `/${ankiVerifyResult.expected_cards}` : ''} · 媒体{' '}
                      {ankiVerifyResult.media_count_checked ?? 0}/{ankiVerifyResult.media_count_expected ?? 0}
                    </span>
                    {ankiVerifyResult.failed_checks?.length ? (
                      <small>{ankiVerifyResult.failed_checks.join(' / ')}</small>
                    ) : null}
                    {ankiVerifyResult.missing_media?.length ? (
                      <small>缺失：{ankiVerifyResult.missing_media.slice(0, 3).join('、')}</small>
                    ) : null}
                    {ankiVerifyResult.mismatched_media?.length ? (
                      <small>哈希不一致：{ankiVerifyResult.mismatched_media.slice(0, 3).map((item) => item.file).join('、')}</small>
                    ) : null}
                  </div>
                ) : null}
              </div>
            ) : null}

            {!project ? (
              <div className="empty-state">
                <Sparkles size={28} />
                <h4>当前没有打开的生成草稿</h4>
                <p>
                  这里不是 Anki 同步视图，只显示本软件生成后可编辑、可导出的草稿。已经导入到 Anki 的卡包和我用于
                  验证模板的临时卡，不会自动回填到这里。选择素材后点击“生成卡片”，生成完成后才会出现片段和卡片列表。
                </p>
              </div>
            ) : (
              <div className="preview-layout">
                <div className="segment-list">
                  {visibleSegments.map((segment) => {
                    const status = segmentReviewStatus(segment)
                    const score = phraseValueScore(segment.phrase_value_score)
                    return (
                      <button
                        type="button"
                        key={segment.id}
                        className={`segment-tab ${segment.id === activeSegmentId ? 'selected' : ''}`}
                        onClick={() => setActiveSegmentId(segment.id)}
                      >
                        <span>{segment.source_time}</span>
                        <strong>{segmentPhraseTitle(segment)}</strong>
                        <small>
                          {segment.cards.filter((card) => card.enabled).length} 张卡 · 推荐 {segment.recommendation}/5
                        </small>
                        <em className={`segment-status ${status}`}>
                          {segmentStatusLabel(status)}
                          {score !== null ? ` · ${score}/5` : ''}
                        </em>
                        <small className="segment-reason">
                          {segment.phrase_reject_reason ||
                            segment.phrase_decision_reason ||
                            segment.phrase_card_focus ||
                            '等待模型或规则给出推荐理由'}
                        </small>
                      </button>
                    )
                  })}
                  {visibleSegments.length === 0 ? (
                    <div className="filter-empty-state">
                      <strong>当前筛选下没有片段</strong>
                      <span>切换到“全部”可以查看完整生成结果。</span>
                    </div>
                  ) : null}
                </div>

                {activeSegment ? (
                  <div className="segment-detail">
                    <div className="segment-toolbar">
                      <div className="preview-rate" aria-label="预览播放速度">
                        <span>播放</span>
                        {[0.75, 1].map((rate) => (
                          <button
                            type="button"
                            key={rate}
                            className={previewRate === rate ? 'selected' : ''}
                            onClick={() => setPreviewRate(rate)}
                          >
                            {rate}x
                          </button>
                        ))}
                      </div>
                      <div className="segment-actions">
                        <button className="ghost-button" type="button" onClick={() => setCardsEnabled(true, activeSegment.id)}>
                          本段全选
                        </button>
                        <button className="ghost-button" type="button" onClick={() => setCardsEnabled(false, activeSegment.id)}>
                          本段停用
                        </button>
                      </div>
                    </div>
                    <div
                      className={`media-preview ${activeSegmentVideoSrc ? 'has-video' : ''}`}
                      aria-label="片段视频预览"
                    >
                      {activeSegmentVideoSrc ? (
                        <>
                          <video
                            key={`${activeSegment.id}-${previewRate}`}
                            controls
                            playsInline
                            preload="metadata"
                            src={activeSegmentVideoSrc}
                            onLoadedMetadata={(event) => handlePreviewLoaded(event, activeSegment)}
                            onTimeUpdate={(event) => handlePreviewTimeUpdate(event, activeSegment)}
                          />
                          <span className="media-time">{activeSegment.media_source_time ?? activeSegment.source_time}</span>
                        </>
                      ) : (
                        <>
                          <Play size={28} />
                          <span>{activeSegment.media_source_time ?? activeSegment.source_time}</span>
                        </>
                      )}
                    </div>
                    <div className="segment-copy">
                      <div>
                        <span className="label">英文原句</span>
                        <strong>{activeSegment.text}</strong>
                      </div>
                      <div>
                        <span className="label">重点词伙</span>
                        <strong>{segmentPhraseLabel(activeSegment)}</strong>
                      </div>
                    </div>

                    {(activeSegment.phrase_review_status ||
                      activeSegment.phrase_decision_reason ||
                      activeSegment.phrase_reject_reason ||
                      activeSegment.phrase_card_focus ||
                      activeSegment.phrase_value_score !== undefined) ? (
                      <div className={`phrase-review-panel status-${segmentReviewStatus(activeSegment)}`}>
                        <div>
                          <span>词伙评审</span>
                          <strong>
                            {segmentStatusLabel(segmentReviewStatus(activeSegment))}
                            {phraseValueScore(activeSegment.phrase_value_score) !== null
                              ? ` · ${phraseValueScore(activeSegment.phrase_value_score)}/5`
                              : ''}
                          </strong>
                        </div>
                        {activeSegment.phrase_card_focus ? <p>{activeSegment.phrase_card_focus}</p> : null}
                        {activeSegment.phrase_decision_reason ? <p>{activeSegment.phrase_decision_reason}</p> : null}
                        {activeSegment.phrase_reject_reason ? <p>{activeSegment.phrase_reject_reason}</p> : null}
                      </div>
                    ) : null}

                    <div className="card-editor-list">
                      {activeSegment.cards.length === 0 ? (
                        <div className="segment-empty-note">
                          <strong>这个片段没有生成可导出的卡</strong>
                          <span>
                            {activeSegment.phrase_reject_reason ||
                              activeSegment.phrase_decision_reason ||
                              '模型或规则认为它暂时不适合做精品词伙卡。'}
                          </span>
                        </div>
                      ) : null}
                      {activeSegment.cards.map((card) => {
                        const skippedEntries = Object.entries(card.skipped_card_types ?? {})
                        const cardPhraseScore = phraseValueScore(card.phrase_value_score ?? activeSegment.phrase_value_score)
                        const cardPhraseStatus =
                          (card.phrase_review_status as SegmentFilter | undefined) ?? segmentReviewStatus(activeSegment)
                        return (
                        <article className={`card-editor card-${qualityClass(card)}`} key={card.id}>
                          <div className="card-editor-head">
                            <label className="toggle card-toggle">
                              <input
                                type="checkbox"
                                checked={card.enabled}
                                onChange={() =>
                                  updateCard(activeSegment.id, card.id, { enabled: !card.enabled })
                                }
                              />
                              <span>{card.type_label}</span>
                            </label>
                            <div className="card-meta-row">
                              <span className="difficulty">{card.difficulty}</span>
                              <span className={`quality-badge ${qualityClass(card)}`}>
                                {qualityLabel(card)}
                                {typeof card.quality?.score === 'number' ? ` · ${card.quality.score}` : ''}
                              </span>
                            </div>
                          </div>
                          {(card.learning_goal || card.decision_reason || skippedEntries.length > 0) ? (
                            <div className="card-plan" aria-label="卡片生成规划">
                              <div>
                                <span className={`role-badge ${card.card_role ?? 'primary'}`}>
                                  {card.card_role === 'specialist' ? '专项卡' : '主卡'}
                                </span>
                                {card.learning_goal ? <strong>{card.learning_goal}</strong> : null}
                              </div>
                              {card.decision_reason ? <p>{card.decision_reason}</p> : null}
                              {skippedEntries.length > 0 ? (
                                <details className="skipped-card-types">
                                  <summary>已合并 {skippedEntries.length} 个低价值卡型</summary>
                                  <div>
                                    {skippedEntries.map(([type, reason]) => (
                                      <span key={type}>
                                        {type}: {reason}
                                      </span>
                                    ))}
                                  </div>
                                </details>
                              ) : null}
                            </div>
                          ) : null}
                          {card.quality?.issues?.length ? (
                            <div className="quality-issues" aria-label="卡片质量提示">
                              {card.quality.issues.map((issue) => (
                                <span key={issue}>{issue}</span>
                              ))}
                            </div>
                          ) : null}
                          {(cardPhraseScore !== null ||
                            card.phrase_decision_reason ||
                            card.phrase_reject_reason ||
                            card.phrase_card_focus) ? (
                            <div className={`phrase-card-review status-${cardPhraseStatus}`}>
                              <span>
                                词伙分
                                {cardPhraseScore !== null ? ` ${cardPhraseScore}/5` : ''}
                              </span>
                              {card.phrase_card_focus ? <strong>{card.phrase_card_focus}</strong> : null}
                              {card.phrase_decision_reason ? <p>{card.phrase_decision_reason}</p> : null}
                              {card.phrase_reject_reason ? <p>{card.phrase_reject_reason}</p> : null}
                            </div>
                          ) : null}
                          <div className="edit-grid">
                            <label>
                              中文意思
                              <textarea
                                value={card.chinese}
                                onChange={(event: ChangeEvent<HTMLTextAreaElement>) =>
                                  updateCard(activeSegment.id, card.id, { chinese: event.target.value })
                                }
                              />
                            </label>
                            <label>
                              重点词伙
                              <textarea
                                value={card.phrase}
                                onChange={(event: ChangeEvent<HTMLTextAreaElement>) =>
                                  updateCard(activeSegment.id, card.id, { phrase: event.target.value })
                                }
                              />
                            </label>
                            <label>
                              释义 / 搭配
                              <textarea
                                value={`${card.definition}\n${card.collocations}`}
                                onChange={(event: ChangeEvent<HTMLTextAreaElement>) => {
                                  const [definition, ...rest] = event.target.value.split('\n')
                                  updateCard(activeSegment.id, card.id, {
                                    definition,
                                    collocations: rest.join('\n'),
                                  })
                                }}
                              />
                            </label>
                            <label>
                              老师评语
                              <textarea
                                value={card.teacher_note}
                                onChange={(event: ChangeEvent<HTMLTextAreaElement>) =>
                                  updateCard(activeSegment.id, card.id, { teacher_note: event.target.value })
                                }
                              />
                            </label>
                          </div>
                        </article>
                        )
                      })}
                    </div>
                  </div>
                ) : null}
              </div>
            )}
          </section>
        </section>
      </main>

      {settingsOpen ? (
        <div className="settings-overlay" role="presentation" onClick={() => setSettingsOpen(false)}>
          <section
            className="settings-dialog"
            ref={settingsDialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="settings-title"
            tabIndex={-1}
            onClick={(event) => event.stopPropagation()}
          >
            <div className="settings-dialog-header">
              <div>
                <p className="eyebrow">Settings</p>
                <h2 id="settings-title">设置</h2>
              </div>
              <button
                className="icon-button"
                type="button"
                onClick={() => setSettingsOpen(false)}
                aria-label="关闭设置"
              >
                <X size={18} />
              </button>
            </div>
            <div className="settings-tabs" role="tablist" aria-label="设置分类">
              <button
                type="button"
                role="tab"
                aria-selected={settingsTab === 'api'}
                className={settingsTab === 'api' ? 'selected' : ''}
                onClick={() => setSettingsTab('api')}
              >
                模型 API
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={settingsTab === 'tts'}
                className={settingsTab === 'tts' ? 'selected' : ''}
                onClick={() => setSettingsTab('tts')}
              >
                语音 TTS
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={settingsTab === 'env'}
                className={settingsTab === 'env' ? 'selected' : ''}
                onClick={() => setSettingsTab('env')}
              >
                本地环境
              </button>
            </div>

            <div className="settings-content">
              {settingsTab === 'env' ? (
              <section className="settings-section settings-section-single">
                <div className="panel-heading">
                  <Settings2 size={20} />
                  <h3>本地环境</h3>
                </div>
                <p>
                  首次启动按顺序检查 Python venv、FFmpeg、yt-dlp、genanki、AnkiConnect 和 YouTube challenge solver。
                  不含任何 API Key。
                </p>
                <div className="settings-row">
                  <button className="ghost-button" type="button" onClick={checkEnv} disabled={busy}>
                    {busy ? <Loader2 className="spin" size={18} /> : <CheckCircle2 size={18} />}
                    检查环境
                  </button>
                  <div className="env-grid">
                    {envStatus ? (
                      <>
                        <span>Python {envStatus.python ?? '-'}</span>
                        <span className={envStatus.ffmpeg ? 'ok' : 'warn'}>ffmpeg</span>
                        <span className={envStatus.genanki ? 'ok' : 'warn'}>genanki</span>
                        <span className={envStatus.yt_dlp ? 'ok' : 'warn'}>
                          yt-dlp {envStatus.yt_dlp_version ?? ''}
                        </span>
                        <span className={envStatus.yt_dlp_js_runtime ? 'ok' : 'warn'}>
                          JS {envStatus.yt_dlp_js_runtime || '未配置'}
                        </span>
                        <span className={envStatus.anki_connect ? 'ok' : 'warn'}>
                          AnkiConnect {envStatus.anki_connect ? '可用' : '未连接'}
                        </span>
                      </>
                    ) : (
                      <span>尚未检查</span>
                    )}
                  </div>
                </div>
                <div className="first-run-steps" aria-label="普通用户 5 步安装">
                  {['解压发布包', '运行 setup_runtime.ps1', '打开 exe', '填写 API Key 并测试', '用内置示例导出 APKG'].map(
                    (step, index) => (
                      <span key={step}>
                        <strong>{index + 1}</strong>
                        {step}
                      </span>
                    ),
                  )}
                </div>
                {envStatus?.status_items?.length ? (
                  <div className="env-checklist" aria-label="环境检查明细">
                    {envStatus.status_items.map((item) => (
                      <div className={`env-check-item ${item.status}`} key={item.id}>
                        <strong>{item.label}</strong>
                        <span>{item.detail}</span>
                        {item.status !== 'ok' && item.fix ? <small>{item.fix}</small> : null}
                      </div>
                    ))}
                  </div>
                ) : null}
                {envStatus?.worker ? (
                  <small className="diagnostic-footnote">
                    Worker: {envStatus.worker}
                    {envStatus.python_executable ? ` · Python: ${envStatus.python_executable}` : ''}
                  </small>
                ) : null}
              </section>
              ) : null}

              {settingsTab === 'api' ? (
              <section className="settings-section settings-section-single">
                <div className="panel-heading">
                  <Boxes size={20} />
                  <h3>模型 API</h3>
                </div>
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

                <div className={`api-test-card ${apiTestTone}`} aria-live="polite" aria-atomic="true">
                  <div className="api-test-icon" aria-hidden="true">
                    {apiTesting ? (
                      <Loader2 className="spin" size={22} />
                    ) : apiTestResult?.ok ? (
                      <CheckCircle2 size={22} />
                    ) : apiTestResult ? (
                      <CircleAlert size={22} />
                    ) : (
                      <PlugZap size={22} />
                    )}
                  </div>
                  <div className="api-test-copy">
                    <span className="label">连接状态</span>
                    <strong>{apiTestTitle}</strong>
                    <p>{apiTestMessage}</p>
                    <small>{apiTestMeta}</small>
                  </div>
                  <button className="primary-button" type="button" onClick={testApi} disabled={apiTesting}>
                    {apiTesting ? <Loader2 className="spin" size={18} /> : <PlugZap size={18} />}
                    {apiTesting ? '测试中...' : '测试连接'}
                  </button>
                </div>

                <div className="settings-subheading">
                  <strong>推荐配置</strong>
                  <span>普通用户只需要选一个服务商、填 Key、点测试。</span>
                </div>
                <div className="preset-grid compact-presets" aria-label="API 推荐预设">
                  {featuredApiPresets.map((preset) => {
                    const selected =
                      request.api_config.provider === preset.provider &&
                      request.api_config.base_url === preset.base_url &&
                      request.api_config.model === preset.model
                    return (
                      <button
                        type="button"
                        key={preset.id}
                        className={`preset-card ${selected ? 'selected' : ''}`}
                        onClick={() => applyApiPreset(preset)}
                      >
                        <strong>{preset.label}</strong>
                        <span>{preset.note}</span>
                        <small>{preset.key_hint}</small>
                      </button>
                    )
                  })}
                </div>

                <button
                  className="advanced-toggle"
                  type="button"
                  onClick={() => setShowAdvancedApi((value) => !value)}
                >
                  {showAdvancedApi ? '收起更多服务商' : '展开更多服务商'}
                </button>
                {showAdvancedApi ? (
                  <div className="preset-grid compact-presets secondary-presets" aria-label="更多 API 预设">
                    {advancedApiPresets.map((preset) => {
                      const selected =
                        request.api_config.provider === preset.provider &&
                        request.api_config.base_url === preset.base_url &&
                        request.api_config.model === preset.model
                      return (
                        <button
                          type="button"
                          key={preset.id}
                          className={`preset-card ${selected ? 'selected' : ''}`}
                          onClick={() => applyApiPreset(preset)}
                        >
                          <strong>{preset.label}</strong>
                          <span>{preset.note}</span>
                          <small>{preset.key_hint}</small>
                        </button>
                      )
                    })}
                  </div>
                ) : null}

                <div className="api-grid">
                  <label className="field">
                    <span>Provider</span>
                    <select
                      value={request.api_config.provider}
                      onChange={(event) => {
                        const provider = event.target.value as Provider
                        patchApi({
                          provider,
                          base_url:
                            provider === 'mimo'
                              ? request.api_config.base_url || MIMO_OPENAI_BASE_URL
                              : request.api_config.base_url,
                          model:
                            provider === 'mimo' && !request.api_config.model
                              ? 'mimo-v2.5-pro'
                              : request.api_config.model,
                          capabilities:
                            provider === 'mimo'
                              ? Array.from(new Set([...request.api_config.capabilities, 'structured_json', 'long_context']))
                              : request.api_config.capabilities,
                        })
                      }}
                    >
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
                      value={request.api_config.base_url}
                      onChange={(event) => patchApi({ base_url: event.target.value })}
                      placeholder={request.api_config.provider === 'mimo' ? MIMO_OPENAI_BASE_URL : 'https://api.deepseek.com/v1'}
                    />
                    <small>
                      {request.api_config.provider === 'mimo'
                        ? `默认 ${MIMO_OPENAI_BASE_URL}；Token Plan 可改成控制台专属端点。`
                        : request.api_config.provider === 'claude' && request.api_config.base_url
                          ? '当前使用 Anthropic-compatible 自定义端点；通常会自动请求 /v1/messages。'
                        : 'OpenAI-compatible 必填；Claude / Gemini 原生模式不用填。'}
                    </small>
                  </label>
                  <label className="field">
                    <span>Model</span>
                    <input
                      value={request.api_config.model}
                      onChange={(event) => patchApi({ model: event.target.value })}
                      list="mimo-text-models"
                      placeholder={request.api_config.provider === 'mimo' ? 'mimo-v2.5-pro' : 'deepseek-chat'}
                    />
                    <datalist id="mimo-text-models">
                      {mimoTextModels.map((model) => (
                        <option key={model.value} value={model.value}>
                          {model.label}
                        </option>
                      ))}
                    </datalist>
                    <small>
                      {request.api_config.provider === 'mimo'
                        ? '官方要求模型 ID 小写：mimo-v2.5-pro、mimo-v2.5、mimo-v2-pro、mimo-v2-omni。'
                        : '填模型 ID，不是产品名。比如 deepseek-chat、qwen-plus。'}
                    </small>
                  </label>
                  <label className="field">
                    <span>API Key</span>
                    <input
                      type="password"
                      value={request.api_config.api_key}
                      onChange={(event) => patchApi({ api_key: event.target.value })}
                      placeholder={request.api_config.provider === 'mimo' ? 'sk-... / tp-...' : 'sk-...'}
                    />
                    <small>只用于当前会话的字幕理解和卡片解释生成；不会写入本地缓存，也不会自动拿去做 TTS。</small>
                  </label>
                  <label className="toggle secret-toggle">
                    <input
                      type="checkbox"
                      checked={secretPrefs.rememberModelKey}
                      onChange={() => toggleRememberSecret('model')}
                    />
                    <span>记住本机模型 API Key（Windows Credential Manager）</span>
                  </label>
                </div>
                <button className="capability-heading collapsible-heading" type="button" onClick={() => setShowCapabilities((value) => !value)}>
                  <KeyRound size={18} />
                  <strong>模型能力标签</strong>
                  <span>{showCapabilities ? '收起' : '高级选项，默认不用改'}</span>
                </button>
                {showCapabilities ? (
                  <div className="capabilities capability-grid">
                    {capabilityLabels.map((capability) => {
                      const selected = request.api_config.capabilities.includes(capability)
                      return (
                        <button
                          type="button"
                          key={capability}
                          className={selected ? 'cap selected' : 'cap'}
                          onClick={() => {
                            const capabilities = selected
                              ? request.api_config.capabilities.filter((item) => item !== capability)
                              : [...request.api_config.capabilities, capability]
                            patchApi({ capabilities })
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
              ) : null}

              {settingsTab === 'tts' ? (
              <section className="settings-section settings-section-single">
                <div className="panel-heading">
                  <PlugZap size={20} />
                  <h3>语音 TTS</h3>
                </div>
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
                    <p>
                      导出牌组如果包含视频片段、字幕或合成音频，默认仅供个人学习；分享前请确认素材和声音服务授权。
                    </p>
                  </div>
                </div>

                <div className={`api-test-card ${ttsTestTone}`} aria-live="polite" aria-atomic="true">
                  <div className="api-test-icon" aria-hidden="true">
                    {ttsTesting ? (
                      <Loader2 className="spin" size={22} />
                    ) : ttsTestResult?.ok ? (
                      <CheckCircle2 size={22} />
                    ) : ttsTestResult ? (
                      <CircleAlert size={22} />
                    ) : (
                      <PlugZap size={22} />
                    )}
                  </div>
                  <div className="api-test-copy">
                    <span className="label">TTS 状态</span>
                    <strong>{ttsTestTitle}</strong>
                    <p>{ttsTestMessage}</p>
                    <small>{ttsTestMeta}</small>
                  </div>
                  <button className="primary-button" type="button" onClick={testTts} disabled={ttsTesting || busy}>
                    {ttsTesting ? <Loader2 className="spin" size={18} /> : <PlugZap size={18} />}
                    {ttsTesting ? '测试中...' : '测试 TTS'}
                  </button>
                </div>

                <div className="settings-subheading">
                  <strong>常用语音</strong>
                  <span>视频卡优先用原声；只在需要额外朗读时开启 TTS。</span>
                </div>
                <div className="preset-grid compact-presets tts-preset-grid" aria-label="TTS 推荐预设">
                  {featuredTtsPresets.map((preset) => {
                    const selected =
                      tts.provider === preset.provider &&
                      tts.base_url === preset.base_url &&
                      tts.model === preset.model &&
                      tts.voice === preset.voice &&
                      (preset.provider !== 'disabled' ? tts.enabled : !tts.enabled)
                    return (
                      <button
                        type="button"
                        key={preset.id}
                        className={`preset-card ${selected ? 'selected' : ''}`}
                        onClick={() => applyTtsPreset(preset)}
                      >
                        <strong>{preset.label}</strong>
                        <span>{preset.note}</span>
                        <small>{preset.key_hint}</small>
                      </button>
                    )
                  })}
                </div>
                <button
                  className="advanced-toggle"
                  type="button"
                  onClick={() => setShowAdvancedTts((value) => !value)}
                >
                  {showAdvancedTts ? '收起高级 TTS' : '高级 TTS 模型和参数'}
                </button>
                {showAdvancedTts ? (
                  <div className="preset-grid compact-presets secondary-presets" aria-label="更多 TTS 预设">
                    {advancedTtsPresets.map((preset) => {
                      const selected =
                        tts.provider === preset.provider &&
                        tts.base_url === preset.base_url &&
                        tts.model === preset.model &&
                        tts.voice === preset.voice &&
                        (preset.provider !== 'disabled' ? tts.enabled : !tts.enabled)
                      return (
                        <button
                          type="button"
                          key={preset.id}
                          className={`preset-card ${selected ? 'selected' : ''}`}
                          onClick={() => applyTtsPreset(preset)}
                        >
                          <strong>{preset.label}</strong>
                          <span>{preset.note}</span>
                          <small>{preset.key_hint}</small>
                        </button>
                      )
                    })}
                  </div>
                ) : null}

                <div className="tts-enable-row">
                  <label className="toggle">
                    <input
                      type="checkbox"
                      checked={tts.enabled}
                      onChange={() =>
                        patchTts({
                          enabled: !tts.enabled,
                          provider: !tts.enabled ? (tts.provider === 'disabled' ? 'mimo' : tts.provider) : 'disabled',
                          base_url:
                            !tts.enabled && tts.provider === 'disabled' ? MIMO_TOKEN_PLAN_SGP_BASE_URL : tts.base_url,
                          model: !tts.enabled && !tts.model ? 'mimo-v2.5-tts' : tts.model,
                          voice: !tts.enabled && !tts.voice ? 'Mia' : tts.voice,
                        })
                      }
                    />
                    <span>导出时生成整句和词伙 TTS</span>
                  </label>
                  <small>开启后会额外生成整句朗读，并给顶部重点词伙生成小喇叭音频。</small>
                </div>

                {tts.enabled ? (
                <div className="api-grid tts-api-grid">
                  <label className="field">
                    <span>语音服务</span>
                    <select
                      value={tts.provider}
                      onChange={(event) => {
                        const provider = event.target.value as TtsProvider
                        patchTts({
                          provider,
                          enabled: provider !== 'disabled',
                          base_url:
                            provider === 'mimo'
                              ? tts.base_url || MIMO_TOKEN_PLAN_SGP_BASE_URL
                              : provider === 'grok'
                              ? 'https://api.x.ai/v1'
                              : provider === 'openai-compatible'
                                ? tts.base_url || 'https://api.openai.com/v1'
                                : tts.base_url,
                          model: provider === 'mimo' && !tts.model ? 'mimo-v2.5-tts' : tts.model,
                          voice:
                            provider === 'mimo'
                              ? tts.voice || 'Mia'
                              : provider === 'grok'
                                ? tts.voice || 'eve'
                                : tts.voice,
                        })
                      }}
                    >
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
                      onChange={(event) => patchTts({ base_url: event.target.value })}
                      placeholder={tts.provider === 'mimo' ? MIMO_OPENAI_BASE_URL : 'https://api.x.ai/v1'}
                    />
                    <small>
                      {tts.provider === 'mimo'
                        ? `MIMO 默认 ${MIMO_OPENAI_BASE_URL}；你的 tp-... 套餐 Key 优先用 ${MIMO_TOKEN_PLAN_SGP_BASE_URL}。`
                        : 'Grok 默认 https://api.x.ai/v1；Gemini 可留空。'}
                    </small>
                  </label>
                  <label className="field">
                    <span>语音 API Key</span>
                    <input
                      type="password"
                      value={tts.api_key}
                      onChange={(event) => patchTts({ api_key: event.target.value })}
                      placeholder={tts.provider === 'mimo' ? 'sk-... / tp-...' : 'xai-... / AIza...'}
                    />
                    <small>MIMO TTS 可留空并复用上方 MIMO Key；填写后优先使用这里的 Key，且不会写入本地缓存。</small>
                  </label>
                  <label className="toggle secret-toggle">
                    <input
                      type="checkbox"
                      checked={secretPrefs.rememberTtsKey}
                      onChange={() => toggleRememberSecret('tts')}
                    />
                    <span>记住本机 TTS API Key（Windows Credential Manager）</span>
                  </label>
                  <label className="field">
                    <span>语音模型</span>
                    <input
                      value={tts.model}
                      onChange={(event) => patchTts({ model: event.target.value })}
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
                      onChange={(event) => patchTts({ voice: event.target.value })}
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
                      MIMO V2.5 内置声音可填 Mia、Chloe、Milo、Dean；VoiceDesign 模型这里填声音描述，
                      VoiceClone 模型这里填 data:audio/...;base64。
                    </small>
                  </label>
                  {showAdvancedTts ? (
                    <>
                      <label className="field">
                        <span>Language</span>
                        <input
                          value={tts.language}
                          onChange={(event) => patchTts({ language: event.target.value })}
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
                          onChange={(event) => patchTts({ sample_rate: Number(event.target.value) })}
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
                          onChange={(event) => patchTts({ bit_rate: Number(event.target.value) })}
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
              ) : null}
            </div>
          </section>
        </div>
      ) : null}

      {isTauriRuntime() ? (
        <div className="resize-handles" aria-hidden="true">
          <div className="resize-handle resize-n" onMouseDown={(event) => startWindowResize('North', event)} />
          <div className="resize-handle resize-e" onMouseDown={(event) => startWindowResize('East', event)} />
          <div className="resize-handle resize-s" onMouseDown={(event) => startWindowResize('South', event)} />
          <div className="resize-handle resize-w" onMouseDown={(event) => startWindowResize('West', event)} />
          <div className="resize-handle resize-ne" onMouseDown={(event) => startWindowResize('NorthEast', event)} />
          <div className="resize-handle resize-nw" onMouseDown={(event) => startWindowResize('NorthWest', event)} />
          <div className="resize-handle resize-se" onMouseDown={(event) => startWindowResize('SouthEast', event)} />
          <div className="resize-handle resize-sw" onMouseDown={(event) => startWindowResize('SouthWest', event)} />
        </div>
      ) : null}
    </div>
  )
}

export default App
